"""The agent's tools over a fresh copy of the records.

    store = Store(email)                    a private copy for one email's run
    result = store.run("get_order", {...})  read tools return records
    result = store.run("issue_credit", {...})

Read tools return records the agent can quote. Action tools never act directly: each works out its facts
(engine/facts.py), asks the policy (engine/policy.py), and only a "done" changes the copy. "waiting" opens an approval
card for a person, and "blocked" changes nothing. Every action is limited to the sender's own account, so a look-alike
or outside sender can't move anything. Every call lands in the audit log with its actor: the agent proposes, the rules
decide, and later a person approves or denies. New IDs come from per-email blocks, so no two emails' runs share one.
"""
import json
import re
from pathlib import Path

from engine import db, facts as F, policy
from engine.db import money

HERE = Path(__file__).resolve().parent.parent
SPEC = json.loads(HERE.joinpath("config", "tools.json").read_text(encoding="utf-8"))
READ = [t["name"] for t in SPEC["read"]]
ACTION = [t["name"] for t in SPEC["action"]]
BLOCK = 3  # IDs set aside per email for each kind of new record

RULES = {
    "credit_cap": "Credits over ${limit} wait for a person.",
    "reship_cap": "Reships worth over ${limit} wait for a person.",
    "fee_waiver_cap": "Fee waivers over ${limit} wait for a person.",
    "order_cap": "New orders over ${limit} wait for a person.",
    "credit_line": "The order is over the account's open credit of ${limit}, so credit reviews it first.",
    "account_hold": "The account is on hold, so credit reviews new orders first.",
    "ship_to_before_pick": "The order has been picked, so a person decides whether to reroute it.",
    "ship_to_after_ship": "The order has shipped, so the ship-to can't change here. A person can ask the carrier to "
                          "reroute it.",
    "ship_to_unknown": "That location isn't on the account.",
    "return_window": "Returns are accepted within {limit} days of delivery.",
    "return_opened": "Only unopened items can be returned.",
    "return_over_order": "Those quantities aren't on the order.",
    "reship_over_order": "Those quantities aren't on the order.",
    "reship_not_shipped": "The order hasn't shipped yet.",
    "credit_needs_invoice": "Credits go against one of this account's invoices.",
    "credit_over_invoice": "The credit is more than the invoice has left to credit.",
    "fee_not_found": "That fee isn't on the invoice or the order.",
    "not_enough_stock": "There isn't enough stock to fill it.",
    "hold_before_ship": "Orders can be held until they ship.",
    "hold_after_ship": "The order has already shipped.",
    "other_account": "That belongs to a different account than the sender's.",
    "unknown_team": "The teams are order_desk, sales, credit and security.",
    "always": "",
}


STOP = {"the", "of", "a", "an", "and", "for", "with", "some", "more", "our", "your", "please", "box", "boxes",
        "item", "items", "bundle", "bundles", "case", "cases", "roll", "rolls"}
SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)(?:\s*x\s*(\d+(?:\.\d+)?))?", re.I)
MEASURE = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(inches|inch|in\b|\"|gauge|ga\b|ect\b)", re.I)
MEASURE_UNIT = {"inches": "in", "inch": "in", "in": "in", '"': "in", "gauge": "gauge", "ga": "gauge", "ect": "ect"}


def normalize(args):
    """Customers write IDs every which way, so the tools accept them the same way: 30927, INV 30927 and inv-30927 are
    all INV-30927, 20812 is SO-20812, 1006 is C-1006, and item numbers in any case are upper case."""
    out = json.loads(json.dumps(args or {}))
    for k, prefix, digits in (("order_id", "SO-", 5), ("invoice_id", "INV-", 5), ("customer_id", "C-", 4)):
        v = out.get(k)
        if isinstance(v, str):
            m = re.fullmatch(r"\s*(?:so|inv|c|order|invoice|po)?[\s#:.-]*(\d{%d})\s*" % digits, v, re.I)
            if m:
                out[k] = prefix + m.group(1)
    if isinstance(out.get("sku"), str):
        out["sku"] = out["sku"].strip().upper()
    if isinstance(out.get("lines"), list):
        for line in out["lines"]:
            if isinstance(line, dict) and isinstance(line.get("sku"), str):
                line["sku"] = line["sku"].strip().upper()
    return out


def _stem(word):
    w = word.lower()
    for end in ("es", "s"):
        if len(w) > 4 and w.endswith(end) and not w.endswith("ss"):
            return w[: -len(end)]
    return w


def rule_text(v):
    text = RULES.get(v["rule"], "")
    limit = v.get("limit")
    if limit is not None:
        text = text.replace("${limit}", f"${limit:,.2f}" if isinstance(limit, float) and limit % 1 else f"${limit:,.0f}")
        text = text.replace("{limit}", f"{limit:g}")
    return text


def _when(iso):
    return iso.replace("T", " ") if iso else None


class Store:
    def __init__(self, email=None, seq=0, limits=None, world=None):
        self.w = world or db.load()
        self.limits = limits or policy.defaults()
        self.email = email
        self.at = email["at"] if email else self.w.meta["today"] + "T09:00"
        sender = (email or {}).get("from", {}).get("email")
        cust = self.w.customer_by_email(sender) if sender else None
        self.customer_id = cust["id"] if cust else None
        self.next = {k: v + seq * BLOCK for k, v in self.w.meta["next_ids"].items()}
        self.next["approval"] = 101 + seq * BLOCK
        self.audit, self.approvals, self.actions, self.created = [], [], [], []

    # ------------------------------------------------------------------------------------------------- dispatch
    def run(self, name, args):
        """A tool's result as a snapshot, so a later change to the records never rewrites an earlier result."""
        args = normalize(args)
        if name in READ:
            try:
                out = getattr(self, "_" + name)(**{k: v for k, v in args.items() if v not in (None, "")})
            except TypeError:
                out = {"error": f"{name} doesn't take those inputs."}
        elif name in ACTION:
            out = self._act(name, args)
        else:
            out = {"error": f"There's no tool named {name}."}
        return json.loads(json.dumps(out))

    def _new_id(self, kind, prefix):
        n = self.next[kind]
        self.next[kind] += 1
        return f"{prefix}{n}"

    def _log(self, actor, tool, target, result, rule=None, detail=None):
        self.audit.append({"at": self.at, "actor": actor, "tool": tool, "target": target, "result": result,
                           "rule": rule, "detail": detail})

    # ---------------------------------------------------------------------------------------------- read tools
    def _order_summary(self, o):
        loc = self.w.location(o["customer_id"], o["ship_to"]) or {}
        return {"order_id": o["id"], "po": o["po"], "placed": _when(o["placed"]), "status": o["status"],
                "total": self.w.order_value(o), "ship_to": f"{loc.get('label')}, {loc.get('city')}",
                "lines": len(o["lines"])}

    def _find_orders(self, customer_id, po=None, status=None, placed_from=None, placed_to=None, sku=None):
        if customer_id not in self.w.customers:
            return {"error": f"No account {customer_id}."}
        found = self.w.find_orders(customer_id, po, status, placed_from, placed_to, sku)
        shown = found[-20:]
        out = {"orders": [self._order_summary(o) for o in shown]}
        if len(found) > len(shown):
            out["older_not_shown"] = len(found) - len(shown)
        return out

    def _get_order(self, order_id):
        o = self.w.orders.get(order_id)
        if not o:
            return {"error": f"No order {order_id}."}
        loc = self.w.location(o["customer_id"], o["ship_to"]) or {}
        lines = []
        for x in o["lines"]:
            line = {"sku": x["sku"], "name": self.w.items[x["sku"]]["name"], "qty": x["qty"], "picked": x["picked"],
                    "shipped": x["shipped"], "price": x["price"], "amount": money(x["qty"] * x["price"])}
            if x.get("damaged"):
                line["damaged_on_delivery"] = x["damaged"]
            lines.append(line)
        out = {"order_id": o["id"], "customer_id": o["customer_id"], "po": o.get("po"),
               "placed": _when(o.get("placed")), "requested": o.get("requested"), "status": o["status"],
               "warehouse": o.get("warehouse"),
               "ship_to": {"location_id": o["ship_to"], "label": loc.get("label"), "city": loc.get("city")},
               "lines": lines, "fees": o["fees"], "total": self.w.order_value(o), "invoice_id": o.get("invoice_id")}
        if o.get("picked"):
            out["picked_at"] = _when(o["picked"])
        if o.get("pick_note"):
            out["pick_note"] = o["pick_note"]
        if o.get("hold"):
            out["hold"] = o["hold"]
        return out

    def _get_shipment(self, order_id):
        if order_id not in self.w.orders:
            return {"error": f"No order {order_id}."}
        s = self.w.shipment(order_id)
        if not s:
            return {"error": f"{order_id} hasn't shipped yet. Its status is {self.w.orders[order_id]['status']}."}
        return {"order_id": order_id, "tracking": s["tracking"], "mode": s["mode"], "carrier": "the carrier",
                "shipped": s["shipped"], "status": s["status"], "eta": _when(s["eta"]),
                "delivered": _when(s["delivered"]), "signed_by": s["signed_by"], "exception": s["exception"],
                "events": [{"at": _when(e["at"]), "text": e["text"]} for e in s["events"]]}

    def _get_customer(self, email=None, customer_id=None):
        c = self.w.customer_by_email(email) if email else self.w.customers.get(customer_id)
        if not c:
            return {"error": f"No account has the address {email}." if email else f"No account {customer_id}."}
        cid = c["id"]
        return {"customer_id": cid, "name": c["name"], "terms": c["terms"], "credit_limit": c["credit_limit"],
                "open_balance": self.w.open_balance(cid), "open_orders": self.w.open_orders_value(cid),
                "available_credit": self.w.available_credit(cid), "on_hold": c["on_hold"],
                "past_due": [{"invoice_id": i["id"], "due": i["due"], "open": self.w.invoice_open(i["id"])}
                             for i in self.w.past_due(cid)],
                "payment_history": self.w.payment_history(cid), "tax": c["tax"], "contacts": c["contacts"],
                "locations": [{"location_id": x["id"], "label": x["label"], "city": x["city"]} for x in c["locations"]],
                "contract_prices": [{"sku": k, "price": v} for k, v in sorted(c["contract_prices"].items())]}

    def _search_items(self, query, customer_id=None):
        q = query.lower()
        size = SIZE.search(q)
        dims = [float(x) for x in size.groups() if x] if size else None
        measures = [(float(n), MEASURE_UNIT[u.lower()]) for n, u in MEASURE.findall(q)]
        words = {_stem(w) for w in re.findall(r"[a-z]+", SIZE.sub(" ", q)) if len(w) > 2} - {_stem(w) for w in STOP}
        heavy = bool({"heavy", "double", "strong"} & words)
        recycled = bool({"recycled", "eco", "kraft"} & words) and dims is not None
        found = []
        for item in self.w.items.values():
            name = item["name"].lower()
            score = 0
            if dims:
                if not item["dims"] or [float(x) for x in item["dims"]] != dims:
                    continue
                score += 10
                if item["category"] == "boxes":
                    strong = item["strength"] == "44 ECT"
                    score += 3 if strong == heavy else -3
                    score += 1 if (item["line"] == "recycled") == recycled else -1
            name_words = {_stem(w) for w in re.findall(r"[a-z]+", name)}
            score += 2 * len(words & name_words - {"heavy", "double", "strong", "recycled", "eco"})
            for n, unit in measures:
                if re.search(r"\b%s %s\b" % (re.escape(f"{n:g}"), unit), name):
                    score += 4
            if score > 0:
                found.append((score, item))
        found.sort(key=lambda x: (-x[0], x[1]["sku"]))
        out = []
        for score, item in found[:8]:
            row = {"sku": item["sku"], "name": item["name"], "unit": item["unit"], "strength": item["strength"],
                   "line": item["line"], "list_price": item["list_price"], "available": self.w.available(item["sku"])}
            if customer_id in self.w.customers:
                row["price"] = self.w.price(customer_id, item["sku"])
            out.append(row)
        return {"query": query, "matches": out} if out else {"query": query, "matches": [],
                                                              "note": "Nothing in the catalog matches. Ask the customer."}

    def _check_stock(self, sku):
        if sku not in self.w.items:
            return {"error": f"No item {sku}."}
        st = self.w.stock(sku)
        return {"sku": sku, "name": self.w.items[sku]["name"], "unit": self.w.items[sku]["unit"],
                "warehouses": {wh: {"available": v["available"], "inbound": v["inbound"]} for wh, v in st.items()},
                "available_total": self.w.available(sku)}

    def _get_price(self, customer_id, sku):
        if customer_id not in self.w.customers or sku not in self.w.items:
            return {"error": "No such account or item."}
        item = self.w.items[sku]
        contract = self.w.customers[customer_id]["contract_prices"].get(sku)
        return {"sku": sku, "name": item["name"], "unit": item["unit"], "list_price": item["list_price"],
                "contract_price": contract, "price": contract if contract is not None else item["list_price"]}

    def _find_equivalents(self, sku):
        if sku not in self.w.items:
            return {"error": f"No item {sku}."}
        item = self.w.items[sku]
        return {"sku": sku, "name": item["name"],
                "equivalents": [{"sku": i["sku"], "name": i["name"], "unit": i["unit"], "list_price": i["list_price"],
                                 "available": self.w.available(i["sku"])} for i in self.w.equivalents(sku)]}

    def _get_invoice(self, invoice_id=None, order_id=None):
        if not invoice_id and order_id in self.w.orders:
            invoice_id = self.w.orders[order_id].get("invoice_id")
        inv = self.w.invoices.get(invoice_id)
        if not inv:
            return {"error": f"No invoice {invoice_id or 'for ' + str(order_id)}."}
        pays = [{"date": p["date"], "amount": p["amount"]} for p in self.w.raw["payments"]
                if p["invoice_id"] == inv["id"]]
        credits = [{"credit_memo": c["id"], "amount": c["amount"]} for c in self.created
                   if c["type"] == "credit_memo" and c["invoice_id"] == inv["id"]]
        return {"invoice_id": inv["id"], "order_id": inv["order_id"], "customer_id": inv["customer_id"],
                "date": inv["date"], "due": inv["due"],
                "lines": [dict(x, name=self.w.items[x["sku"]]["name"]) for x in inv["lines"]], "fees": inv["fees"],
                "total": inv["total"], "paid": money(sum(p["amount"] for p in pays)), "payments": pays,
                "credits": credits, "open": self.w.invoice_open(inv["id"])}

    # -------------------------------------------------------------------------------------------- action tools
    def _target(self, name, args):
        for k in ("order_id", "invoice_id", "team"):
            if args.get(k):
                return args[k]
        return args.get("customer_id") or name

    def _act(self, name, args):
        target = self._target(name, args)
        self._log("agent", name, target, "proposed", detail={k: v for k, v in args.items() if k != "sentence"})
        cid = self.customer_id
        if args.get("customer_id") and args["customer_id"] != cid:
            v = {"verdict": "blocked", "rule": "other_account", "approver": None, "amount": None, "limit": None}
            fx = {}
        elif name == "ask_customer":
            fx = {}
            v = policy.decide(name, fx, self.limits)
        else:
            fx = F.facts_for(self.w, name, args, cid, self.limits)
            v = policy.decide(name, dict(fx, team=args.get("team")), self.limits)
        record = {"tool": name, "args": args, "facts": fx, "verdict": v}
        self.actions.append(record)
        self._log("rules", name, target, v["verdict"], v["rule"], rule_text(v) or None)
        if v["verdict"] == "done":
            out = self._apply(name, args, fx)
            out.update(result="done")
        elif v["verdict"] == "waiting":
            out = self._wait(name, args, fx, v)
        else:
            out = {"result": "blocked", "rule": v["rule"],
                   "note": (rule_text(v) + " Don't promise it in the reply.").strip()}
        record["outcome"] = out
        return out

    def resolve(self, approval_id, approve, by="the approver"):
        """A person approves or denies a waiting card. Approving applies the action as if the rules had let it
        through, and either way the audit log records who decided."""
        card = next(c for c in self.approvals if c["approval_id"] == approval_id)
        if card["status"] != "waiting":
            return card
        if card["tool"] == "create_order":
            order = next(o for o in self.w.orders.values() if o.get("id") == card.get("order_id"))
            order["status"] = "open" if approve else "cancelled"
            card["outcome"] = {"order_id": order["id"], "status": order["status"]}
        elif approve:
            card["outcome"] = self._apply(card["tool"], card["args"], card["facts"])
        card["status"] = "approved" if approve else "denied"
        self._log("approver", card["tool"], self._target(card["tool"], card["args"]), card["status"],
                  card["verdict"]["rule"], by)
        return card

    def _wait(self, name, args, fx, v):
        ap = self._new_id("approval", "AP-")
        card = {"approval_id": ap, "tool": name, "args": args, "facts": fx, "verdict": v, "status": "waiting"}
        self.approvals.append(card)
        out = {"result": "waiting", "approval_id": ap, "waiting_on": v["approver"], "rule": v["rule"],
               "note": rule_text(v) + " It happens only if a person approves it, so describe it as pending."}
        if name == "create_order":
            so = self._new_id("order", "SO-")
            order = self._new_order(args, fx, so)
            order["status"] = "pending_approval"
            self.w.orders[so] = order
            self.created.append({"type": "order", "id": so})
            card["order_id"] = so
            out.update(order_id=so, total=fx["total"])
        if name == "create_return":
            out.update(gross=fx["gross"], restocking_fee=fx["restocking_fee"], credit=fx["credit"])
        if name == "reship":
            out["value"] = fx["value"]
        if v.get("amount") is not None:
            out["amount"] = v["amount"]
        if v.get("limit") is not None:
            out["limit"] = v["limit"]
        return out

    def _new_order(self, args, fx, so):
        order = F.new_order(self.w, self.customer_id, args, fx, so)
        order.update(placed=self.at, requested=args.get("requested_date"), allocation=fx["allocation"],
                     warehouse=None, picked=None, pick_note=None, invoice_id=None)
        return order

    def _apply(self, name, args, fx):
        w = self.w
        if name == "issue_credit":
            cm = self._new_id("credit", "CM-")
            w.credits[args["invoice_id"]] = money(w.credits.get(args["invoice_id"], 0) + fx["amount"])
            self.created.append({"type": "credit_memo", "id": cm, "invoice_id": args["invoice_id"],
                                 "amount": fx["amount"]})
            return {"credit_memo": cm, "invoice_id": args["invoice_id"], "amount": fx["amount"],
                    "invoice_open_after": w.invoice_open(args["invoice_id"])}
        if name == "reship":
            so = self._new_id("order", "SO-")
            src = w.orders[args["order_id"]]
            w.orders[so] = {"id": so, "customer_id": src["customer_id"], "po": src["po"], "status": "open",
                            "lines": [{"sku": l["sku"], "qty": l["qty"], "price": 0.0, "picked": 0, "shipped": 0}
                                      for l in args["lines"]], "fees": [], "ship_to": src["ship_to"],
                            "replaces": src["id"], "placed": self.at, "invoice_id": None}
            self.created.append({"type": "order", "id": so})
            return {"replacement_order": so, "replaces": src["id"], "lines": args["lines"], "value": fx["value"],
                    "charge": 0.0}
        if name == "waive_fee":
            holder = w.invoices.get(args.get("invoice_id")) or w.orders.get(args.get("order_id"))
            for f in holder["fees"]:
                if f["type"] == args["fee"]:
                    f["waived"] = True
            return {"fee": args["fee"], "amount": fx["amount"], "on": holder["id"]}
        if name == "create_order":
            so = self._new_id("order", "SO-")
            order = self._new_order(args, fx, so)
            w.orders[so] = order
            self.created.append({"type": "order", "id": so})
            return {"order_id": so, "total": fx["total"], "fees": fx["fees"],
                    "lines": [{"sku": x["sku"], "qty": x["qty"], "price": x["price"]} for x in order["lines"]],
                    "allocation": fx["allocation"], "requested_date": args.get("requested_date")}
        if name == "update_ship_to":
            w.orders[args["order_id"]]["ship_to"] = args["location_id"]
            loc = w.location(self.customer_id, args["location_id"])
            return {"order_id": args["order_id"], "ship_to": f"{loc['label']}, {loc['city']}"}
        if name == "create_return":
            ra = self._new_id("return", "RA-")
            self.created.append({"type": "return", "id": ra, "order_id": args["order_id"], "credit": fx["credit"]})
            return {"return_id": ra, "order_id": args["order_id"], "gross": fx["gross"],
                    "restocking_fee": fx["restocking_fee"], "restocking_pct": self.limits["restocking_pct"],
                    "credit": fx["credit"], "credit_issued": "when the return arrives"}
        if name == "hold_order":
            w.orders[args["order_id"]]["hold"] = {"until": args.get("until")}
            return {"order_id": args["order_id"], "held_until": args.get("until")}
        if name == "route_to_person":
            return {"routed_to": args["team"], "mailbox": json.loads(HERE.joinpath(
                "config", "policy.json").read_text(encoding="utf-8"))["routes"][args["team"]]}
        if name == "ask_customer":
            return {"note": "Put the question in the reply."}
        return {}
