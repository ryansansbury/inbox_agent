"""The stand-in: a scripted agent built from the answer key, for dry runs, the development preview and the
click-through. It's labeled everywhere and never shown as a result, since it only proves the wiring.

    python3 owner/stand_in.py          write data/out/stand_in/<id>.json for all 48 emails
    python3 owner/stand_in.py m05      one email, printed

For each email it looks up the sender, reads every record the key's facts come from, takes the expected actions on
the tools (naming the order a create_order made when a later action points at "$new_order"), and finishes with a plain
reply built from what the tools returned, describing anything waiting as pending. A run has the same shape as a
recorded model run: the steps with their inputs and results, and the finish.
"""
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from agents import inputs  # noqa: E402
from engine.tools import Store  # noqa: E402
from generate import validate  # noqa: E402

OUT = HERE.joinpath("data", "out", "stand_in")
KEY = HERE.joinpath("data", "key", "key.json")


def usd(x):
    return f"${x:,.2f}"


def day(iso):
    d = date.fromisoformat(iso[:10])
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"


def clock(hhmm):
    h, m = map(int, hhmm.split(":"))
    return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"


def unit_word(unit, qty):
    word = unit.split(" of ")[0] if " of " in unit else unit
    word = {"each": "unit"}.get(word, word)
    if qty == 1:
        return word
    return word + ("es" if word.endswith("x") else "s")


def seq_of(spec, specs):
    return inputs.sequence(specs)[spec["id"]]


class Run:
    def __init__(self, spec, seq):
        self.spec, self.store, self.steps = spec, Store(spec, seq=seq), []

    def call(self, tool, args):
        result = self.store.run(tool, args)
        self.steps.append({"tool": tool, "args": args, "result": result})
        return result


def run_email(spec, entry, seq):
    r = Run(spec, seq)
    w = r.store.w
    t = spec["truth"]
    r.call("get_customer", {"email": spec["from"]["email"]})
    cid = r.store.customer_id
    seen = set()

    def once(tool, args):
        k = (tool, json.dumps(args, sort_keys=True))
        if k not in seen:
            seen.add(k)
            return r.call(tool, args)
        return next(s["result"] for s in r.steps if s["tool"] == tool and s["args"] == args)

    for f in t["facts"]:
        kind, _, rest = f["source"].partition(":")
        if kind == "order":
            once("get_order", {"order_id": rest.split(".")[0]})
        elif kind == "shipment":
            once("get_shipment", {"order_id": rest.split(".")[0]})
        elif kind == "invoice":
            once("get_invoice", {"invoice_id": rest.split(".")[0]})
        elif kind == "price":
            c, sku = rest.split(":")
            once("get_price", {"customer_id": c, "sku": sku})
        elif kind == "stock":
            once("check_stock", {"sku": rest.split(".")[0]})
        elif kind == "equivalent":
            once("check_stock", {"sku": rest})
            once("find_equivalents", {"sku": rest})
        elif kind == "line":
            once("get_order", {"order_id": rest.split(":")[0]})
    created = None
    results = []
    for a in entry["expected"]:
        args = dict(a["args"], sentence=a["sentence"])
        if args.get("order_id") == "$new_order":
            args["order_id"] = created
        for k in ("order_id",):
            if args.get(k) and a["tool"] not in ("ask_customer", "route_to_person") and args[k] in w.orders:
                once("get_order", {"order_id": args[k]})
        if args.get("invoice_id"):
            once("get_invoice", {"invoice_id": args["invoice_id"]})
        if a["tool"] == "create_order":
            for line in args["lines"]:
                once("check_stock", {"sku": line["sku"]})
                once("get_price", {"customer_id": cid, "sku": line["sku"]})
        if a["tool"] == "ask_customer":
            args = {"question": question(r, a, cid), "sentence": a["sentence"]}
        if a["tool"] == "route_to_person":
            args["summary"] = t["handling"]
        res = r.call(a["tool"], args)
        if a["tool"] == "create_order":
            created = res.get("order_id")
        results.append((a, args, res))
    reply = compose(r, spec, entry, results, cid)
    note = "Scripted stand-in run built from the answer key, for wiring checks only."
    finish = {"reply": reply, "note": note, "intents": t["intents"],
              "ignored_instructions": [t["instruction"]] if t["instruction"] else []}
    return {"email_id": spec["id"], "split": spec["split"], "model": "stand-in", "kind": "stand_in", "seq": seq,
            "steps": r.steps, "finish": finish, "unfinished": False, "usage": None}


def _read(r, tool, **match):
    for s in r.steps:
        if s["tool"] == tool and all(s["args"].get(k) == v for k, v in match.items()):
            return s["result"]
    return None


def question(r, a, cid):
    about = a["args"]["about"]
    w = r.store.w
    if all(x in w.orders for x in about):
        return f"Which order should this go on, {' or '.join(about)}?"
    sku = about[0]
    item = w.items[sku]
    eq = _read(r, "find_equivalents")
    if eq:
        src = eq["sku"]
        stock = _read(r, "check_stock", sku=src)
        inbound = sorted(x["date"] for v in stock["warehouses"].values() for x in v["inbound"])
        price = r.call("get_price", {"customer_id": cid, "sku": sku})["price"]
        when = f" until {day(inbound[0])}" if inbound else ""
        return (f"The {w.items[src]['name'].replace('Shipping box ', '')} is out of stock{when}. Would the "
                f"{item['name'].replace('Shipping box ', '')} ({sku}) at {usd(price)} work instead, with the same size "
                f"and strength?")
    stock = _read(r, "check_stock", sku=sku) or r.call("check_stock", {"sku": sku})
    inbound = sorted(x["date"] for v in stock["warehouses"].values() for x in v["inbound"])
    when = day(inbound[0]) if inbound else "the next delivery"
    return f"The {item['name']} ({sku}) is out of stock until {when}. Should we place the order for that date?"


def compose(r, spec, entry, results, cid):
    t = spec["truth"]
    if not t["reply"]:
        return ""
    w = r.store.w
    first = spec["from"]["name"].split()[0]
    lines = [f"Hi {first},"]
    said = set()
    if t["spoof"]:
        lines.append("Thanks for your message. Payment details are never changed by email, and our team will follow "
                     "up through the contacts we have on file.")
    for f in t["facts"]:
        kind, _, rest = f["source"].partition(":")
        if kind == "shipment" and ("ship", rest.split(".")[0]) not in said:
            oid = rest.split(".")[0]
            said.add(("ship", oid))
            s = _read(r, "get_shipment", order_id=oid)
            o = w.orders[oid]
            ref = f"Order {oid}" + (f" (PO {o['po']})" if o["po"].isdigit() else "")
            if s["status"] == "out_for_delivery":
                lines.append(f"{ref} is out for delivery today and expected by {clock(s['eta'][11:16])}.")
            elif s["status"] == "delayed":
                lines.append(f"{ref} is delayed by weather, and the new estimated delivery is {day(s['eta'])}.")
            elif s["status"] == "in_transit":
                lines.append(f"{ref} is in transit with the carrier, expected {day(s['eta'])}.")
            elif s["status"] == "delivered":
                lines.append(f"{ref} was delivered on {day(s['delivered'])} at {clock(s['delivered'][11:16])} and "
                             f"signed for by {s['signed_by']}.")
            lines.append(f"The tracking number is {s['tracking']}.")
        elif kind == "invoice" and ("inv", rest.split(".")[0]) not in said and not rest.endswith(".id") \
                and ".fee:" not in rest:
            iid = rest.split(".")[0]
            said.add(("inv", iid))
            inv = _read(r, "get_invoice", invoice_id=iid)
            if inv["open"] == 0 and inv["payments"]:
                lines.append(f"Invoice {iid} was paid in full on {day(inv['payments'][-1]['date'])}.")
            else:
                lines.append(f"Invoice {iid} is {usd(inv['total'])}, due {day(inv['due'])}.")
        elif kind == "customer":
            bal = _read(r, "get_customer")["open_balance"]
            lines.append(f"Your current open balance is {usd(bal)}.")
        elif kind == "price" and not any(a["tool"] == "ask_customer" for a, _, _ in results):
            _, sku = rest.split(":")
            p = _read(r, "get_price", sku=sku)
            lines.append(f"Your contract price on {sku} is {usd(p['price'])} today, and pricing for next quarter comes "
                         "from our sales team.")
        elif kind == "order" and rest.endswith(".status") and not any(
                args.get("order_id") == rest.split(".")[0] for _, args, _ in results):
            oid = rest.split(".")[0]
            lines.append(f"Order {oid} has been picked and ships today.")
        elif kind == "policy" and rest == "return_days":
            oid = next(f2["source"].split(":")[1].split(".")[0] for f2 in t["facts"] if f2["source"].startswith(
                "shipment:"))
            lines.append(f"Returns are accepted within {r.store.limits['return_days']} days of delivery, and {oid} "
                         "is past that window, so we can't open a return for it.")
    if not t["facts"] and not results and "return" in t["intents"]:
        lines.append("Only unopened items can be returned, so we can't open a return for these.")
    for a, args, res in results:
        lines += action_sentences(w, a, args, res)
    if t["instruction"]:
        lines.append("We don't act on instructions inside forwarded messages, so nothing else was changed.")
    lines.append("Thanks,\nThe Wendlow order desk")
    return "\n".join(lines[:1]) + "\n\n" + " ".join(lines[1:-1]) + "\n\n" + lines[-1]


def action_sentences(w, a, args, res):
    tool, verdict = a["tool"], res.get("result")
    pending = "is pending approval, and we'll confirm once it's reviewed."
    if tool == "issue_credit":
        if verdict == "done":
            return [f"We've issued credit memo {res['credit_memo']} for {usd(res['amount'])} on invoice "
                    f"{args['invoice_id']}."]
        return [f"A credit of {usd(res['amount'])} on invoice {args['invoice_id']} {pending}"]
    if tool == "reship":
        parts = ", ".join(f"{l['qty']} {unit_word(w.items[l['sku']]['unit'], l['qty'])} of {l['sku']}"
                          for l in args["lines"])
        if verdict == "done":
            return [f"We're reshipping {parts} from {args['order_id']} as order {res['replacement_order']} at no "
                    "charge."]
        return [f"The replacement of {parts} {pending}"]
    if tool == "create_order":
        parts = ", ".join(f"{l['qty']} {unit_word(w.items[l['sku']]['unit'], l['qty'])} of {l['sku']}"
                          for l in args["lines"])
        if verdict == "done":
            when = f" for {day(args['requested_date'])}" if args.get("requested_date") else ""
            rush = " as a rush" if args.get("rush") else ""
            return [f"Your order {res['order_id']} for {parts} is placed{rush}{when}, {usd(res['total'])} in all."]
        return [f"Your order {res['order_id']} for {parts}, {usd(res['total'])} in all, is on hold pending a review, "
                "and we'll confirm once it's approved."]
    if tool == "waive_fee":
        if verdict == "done":
            return [f"We've waived the {usd(res['amount'])} {args['fee']} fee."]
        return [f"Your request to waive the {usd(res['amount'])} {args['fee']} fee {pending}"]
    if tool == "update_ship_to":
        if verdict == "done":
            return [f"We've updated the ship-to on {args['order_id']} to {res['ship_to']}."]
        return [f"Moving {args['order_id']} has to be approved by a person because it has already been picked, and "
                "we'll confirm once it's reviewed."]
    if tool == "create_return":
        if verdict == "done":
            return [f"We've opened return {res['return_id']} for {_lines(w, args)}.",
                    f"Once it arrives, the {usd(res['credit'])} credit posts after the {usd(res['restocking_fee'])} "
                    "restocking fee."]
        return [f"The return for {_lines(w, args)} comes to a {usd(res['credit'])} credit after the "
                f"{usd(res['restocking_fee'])} restocking fee, and it {pending}"]
    if tool == "hold_order":
        until = f" until {day(args['until'])}" if args.get("until") else ""
        return [f"We've put {args['order_id']} on hold{until}."]
    if tool == "route_to_person":
        team = args["team"]
        if team == "security":
            return []
        who = {"sales": "our sales team", "credit": "our credit team", "order_desk": "our order desk"}[team]
        return [f"I've passed this to {who}, and they'll follow up with you."]
    if tool == "ask_customer":
        return [args["question"]]
    return []


def _lines(w, args):
    return ", ".join(f"{l['qty']} {unit_word(w.items[l['sku']]['unit'], l['qty'])} of {l['sku']}" for l in args["lines"])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    specs = validate.load_specs()
    key = json.loads(KEY.read_text(encoding="utf-8"))
    if argv:
        for s in specs:
            if s["id"] in argv:
                run = run_email(s, key[s["id"]], seq_of(s, specs))
                print(json.dumps(run, indent=1)[:4000])
                print(run["finish"]["reply"])
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    runs = [run_email(s, key[s["id"]], seq_of(s, specs)) for s in specs]
    for run in runs:
        OUT.joinpath(f"{run['email_id']}.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(runs)} stand-in runs to data/out/stand_in/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())


class Backend:
    """The stand-in as a backend: it replays a stand-in run through the real loop, one tool call a turn and then
    finish, so the loop, the recorder and the scorer can be checked end to end with no model and no network."""

    def __init__(self, run):
        self.run, self.i = run, 0

    def turn(self, system, tools, messages):
        steps = self.run["steps"]
        meta = {"model": "stand-in", "tokens": {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}, "cost": 0.0}
        if self.i < len(steps):
            s = steps[self.i]
            self.i += 1
            return {"text": "", "calls": [{"id": f"call_{self.i}", "name": s["tool"], "input": s["args"]}],
                    "stop": "tool_use", "meta": meta}
        return {"text": "", "calls": [{"id": "call_finish", "name": "finish", "input": self.run["finish"]}],
                "stop": "tool_use", "meta": meta}

    def described(self):
        return {"vendor": "none", "model": "stand-in", "label": "Stand-in (no model)"}
