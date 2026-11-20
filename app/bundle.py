"""site/data.js: the morning, the agent's recorded runs on it and the limits, as window.IA for site/app.js.

Every recorded morning run is replayed here on a fresh copy of the records, the way agents/replay.py checks it, so the
page gets each action's facts and verdict from the same code that scored it. site/policy.js decides those facts again
when a visitor moves a limit, and site/replies.js checks a reply against the evidence table built here, the same table
the scorer used. The scored sets (dev and test) reach the page only as numbers in How it works.

    data = build(words)         the dict
    write(data)                 site/data.js
"""
import json
from datetime import date
from pathlib import Path

from engine import db, injection, policy, replies
from engine import facts as F
from engine.tools import ACTION, BLOCK, Store, normalize

HERE = Path(__file__).resolve().parent.parent
TODAY = "2026-10-27"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def read(*parts):
    return json.loads(HERE.joinpath(*parts).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ formatting
def money(x):
    return f"${float(x):,.2f}"


def day(iso):
    d = date.fromisoformat(iso[:10])
    return f"{WEEKDAYS[d.weekday()]}, {MONTHS[d.month - 1]} {d.day}"


def clock(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"


def cap(x, unit="usd"):
    """A limit as the page writes it: whole dollars without cents, days and percents as numbers."""
    if unit != "usd":
        return f"{x:g}"
    x = float(x)
    return f"${x:,.0f}" if x == int(x) else f"${x:,.2f}"


def why(w, rule, verdict, limit=None):
    text = w.table("ui.why").get(f"{rule}.{verdict}", "")
    unit = "days" if rule == "return_window" else "usd"
    return text.replace("{limit}", cap(limit, unit) if limit is not None else "")


def when(stamp):
    """'2026-10-27 14:00' as 'today by 2:00 PM', and a date alone as its day."""
    if not stamp:
        return ""
    d, _, t = stamp.replace("T", " ").partition(" ")
    out = "today" if d == TODAY else day(d)
    return f"{out} at {clock(t)}" if t else out


def models():
    cfg = read("config", "models.json")
    comp = read("evals", "model_comparison.json") if HERE.joinpath("evals", "model_comparison.json").exists() else {}
    route = comp.get("route") or cfg["default"]
    out = [{"id": m["id"], "label": m["label"], "vendor": m["vendor"], "route": m["id"] == route}
           for m in cfg["models"] if m["id"] in cfg["compare"]]
    return sorted(out, key=lambda m: not m["route"]), route


# ------------------------------------------------------------------------------------------------ the step lines
def step_line(tool, args, res, w, world):
    """One plain line for a step in the trace, from the tool's own result."""
    L, st = w.table("step.line"), w.table("ui.status")
    if not isinstance(res, dict):
        return ""
    if "error" in res:
        return res["error"]
    verdict = res.get("result")
    if tool in ACTION and verdict == "waiting":
        who = w.table("ui.team").get(res.get("waiting_on"), res.get("waiting_on"))
        if tool == "create_order":
            return L["create_order.waiting"].format(id=res["order_id"], total=money(res["total"]), who=who)
        return L["waiting"].format(who=who, why=why(w, res["rule"], "waiting", res.get("limit")))
    if tool in ACTION and verdict == "blocked":
        return L["blocked"].format(why=why(w, res["rule"], "blocked", res.get("limit")))
    if tool == "get_customer":
        line = L["get_customer"].format(name=res["name"], terms=res["terms"], open=money(res["available_credit"]))
        if res.get("on_hold"):
            line += " · " + L["get_customer.hold"]
        if res.get("past_due"):
            line += " · " + L["get_customer.past_due"].format(n=len(res["past_due"]))
        return line
    if tool == "find_orders":
        found = res.get("orders", [])
        if not found:
            return L["find_orders.none"]
        if len(found) == 1:
            o = found[0]
            return L["find_orders.one"].format(id=o["order_id"], status=st.get(o["status"], o["status"]),
                                               total=money(o["total"]))
        return L["find_orders"].format(n=len(found), ids=f" {w['ui.and']} ".join(o["order_id"] for o in found[:3]))
    if tool == "get_order":
        return L["get_order"].format(id=res["order_id"], status=st.get(res["status"], res["status"]),
                                     total=money(res["total"]), lines=len(res["lines"]))
    if tool == "get_shipment":
        line = L["get_shipment"].format(tracking=res["tracking"], status=st.get(res["status"], res["status"]))
        if res.get("delivered"):
            line += " · " + L["get_shipment.delivered"].format(when=when(res["delivered"]))
        elif res.get("eta"):
            line += " · " + L["get_shipment.eta"].format(when=when(res["eta"]))
        return line
    if tool == "search_items":
        found = res.get("matches", [])
        if not found:
            return L["search_items.none"]
        if len(found) == 1:
            return found[0]["name"]
        return L["search_items"].format(n=len(found), first=found[0]["name"])
    if tool == "check_stock":
        where = f" {w['ui.and']} ".join(f"{k} {v['available']}" for k, v in res["warehouses"].items())
        line = L["check_stock"].format(n=res["available_total"], where=where)
        inbound = [x for v in res["warehouses"].values() for x in v.get("inbound", [])]
        if inbound:
            line += " · " + L["check_stock.inbound"].format(n=sum(x["qty"] for x in inbound), when=day(inbound[0]["date"]))
        return line
    if tool == "get_price":
        key = "get_price.contract" if res.get("contract_price") is not None else "get_price"
        return L[key].format(price=money(res["price"]), unit=res["unit"], sku=res["sku"])
    if tool == "find_equivalents":
        found = res.get("equivalents", [])
        if not found:
            return L["find_equivalents.none"]
        e = found[0]
        return L["find_equivalents"].format(name=e["name"], price=money(e["list_price"]), n=e["available"])
    if tool == "get_invoice":
        return L["get_invoice"].format(id=res["invoice_id"], total=money(res["total"]), open=money(res["open"]))
    if tool == "issue_credit":
        return L["issue_credit"].format(id=res["credit_memo"], amount=money(res["amount"]), invoice=res["invoice_id"])
    if tool == "reship":
        return L["reship"].format(id=res["replacement_order"], value=money(res["value"]))
    if tool == "waive_fee":
        return L["waive_fee"].format(fee=res["fee"], amount=money(res["amount"]), on=res["on"])
    if tool == "create_order":
        split = f" {w['ui.and']} ".join(w.fill("step.from", qty=a["qty"], warehouse=a["warehouse"])
                                       for plan in res["allocation"].values() for a in plan)
        return L["create_order"].format(id=res["order_id"], total=money(res["total"]), split=split)
    if tool == "update_ship_to":
        return L["update_ship_to"].format(order=res["order_id"], to=res["ship_to"])
    if tool == "create_return":
        return L["create_return"].format(id=res["return_id"], credit=money(res["credit"]),
                                         fee=money(res["restocking_fee"]))
    if tool == "hold_order":
        return L["hold_order"].format(order=res["order_id"])
    if tool == "route_to_person":
        return L["route_to_person"].format(team=w.table("ui.team")[res["routed_to"]], mailbox=res["mailbox"])
    if tool == "ask_customer":
        return L["ask_customer"]
    return ""


# ------------------------------------------------------------------------------------------------ one run
def turns_of(run):
    """Each model turn with its time, tokens and cost, and the steps it asked for."""
    out, k = [], 0
    for t in run.get("transcript", []):
        calls = [c for c in t.get("calls") or [] if c.get("name") != "finish"]
        meta = t.get("meta") or {}
        tok = meta.get("tokens") or {}
        out.append({"ms": meta.get("ms", 0), "steps": list(range(k, k + len(calls))),
                    "finish": any(c.get("name") == "finish" for c in t.get("calls") or []),
                    "tokens": [tok.get("input", 0), tok.get("output", 0), tok.get("cache_read", 0),
                               tok.get("cache_write", 0)],
                    "cost": meta.get("cost", 0), "text": (t.get("text") or "").strip()})
        k += len(calls)
    return out


def run_view(run, spec, score, w, world):
    store = Store(spec, seq=run["seq"])
    first = {k: v + run["seq"] * BLOCK for k, v in world.meta["next_ids"].items()}
    first["approval"] = 101 + run["seq"] * BLOCK
    steps, ran = [], []
    for st in run["steps"]:
        valid = st.get("valid") is not False
        before = len(store.actions)
        if valid:
            res = store.run(st["tool"], st["args"])
            if res != st["result"]:
                raise SystemExit(f"{run['model']} {spec['id']}: {st['tool']} returns something else today. "
                                 "Run the replay check.")
            ran.append({"tool": st["tool"], "args": st["args"], "result": res})
        args = {k: v for k, v in (st.get("args") or {}).items() if k != "sentence"}
        steps.append({"tool": st["tool"], "args": args, "sentence": (st.get("args") or {}).get("sentence"),
                      "result": st["result"], "valid": valid,
                      "act": len(store.actions) - 1 if len(store.actions) > before else None,
                      "line": step_line(st["tool"], args, st["result"], w, world) if valid else w["ui.invalid"]})
    actions = []
    for i, a in enumerate(store.actions):
        step = next(k for k, s in enumerate(steps) if s["act"] == i)
        args = normalize({k: v for k, v in a["args"].items() if k != "sentence"})
        extra = {}
        if a["tool"] == "update_ship_to" and store.customer_id:
            loc = world.location(store.customer_id, args.get("location_id"))
            if loc:
                extra["to"] = f"{loc['label']}, {loc['city']}"
        actions.append({"tool": a["tool"], "args": args, "sentence": a["args"].get("sentence"), "facts": a["facts"],
                        "verdict": a["verdict"], "fixed": a["verdict"]["rule"] == "other_account",
                        "team": a["args"].get("team"), "step": step, "outcome": a.get("outcome"), "extra": extra})
    finish = run.get("finish") or {}
    table = replies.for_run(store, spec, ran, TODAY)
    usage = run.get("usage") or {}
    return {"steps": steps, "actions": actions, "turns": turns_of(run), "first": first,
            "finish": {"reply": finish.get("reply") or "", "note": finish.get("note") or "",
                       "intents": finish.get("intents") or [], "ignored": finish.get("ignored_instructions") or []},
            "table": table, "unfinished": bool(run.get("unfinished")), "repaired": bool(run.get("repaired")),
            "reminded": bool(run.get("reminded")), "calls": run.get("calls", len(steps)),
            "usage": {"seconds": usage.get("seconds", 0), "cost": usage.get("cost", 0),
                      "input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0),
                      "cache_read": usage.get("cache_read_tokens", 0)},
            "recorded": run.get("recorded_at", ""), "prompt": run.get("prompt_hash", ""),
            "score": {k: score.get(k) for k in ("expected", "hits", "missed", "extra", "unsafe", "checks", "routing_ok",
                                                 "claims", "bad_claims", "facts", "facts_present", "missing_facts")}
            if score else None}


# ------------------------------------------------------------------------------------------------ one email
def what_if(spec, world, limits):
    """The action a planted instruction asks for, worked out from its own sentence, so the page can show what the
    limits would have said had the agent obeyed it."""
    n = spec["truth"].get("instruction")
    if not n or not any(a["tool"] == "issue_credit" for a in spec["truth"]["forbidden"]):
        return None
    text = next(s["text"] for s in spec["sentences"] if s["n"] == n)
    claims = replies.extract(text, TODAY)
    inv = next((c["value"] for c in claims if c["kind"] == "invoice"), None)
    amt = next((c["value"] / 100 for c in claims if c["kind"] == "money"), None)
    if not inv or amt is None:
        return None
    cust = world.customer_by_email(spec["from"]["email"])
    args = {"invoice_id": inv, "amount": amt}
    fx = F.facts_for(world, "issue_credit", args, cust["id"] if cust else None, limits)
    return {"n": n, "tool": "issue_credit", "args": args, "facts": fx}


def email_view(spec, world, limits):
    cust = world.customer_by_email(spec["from"]["email"])
    t = spec["truth"]
    breaks, n = [], 0
    for para in spec["body"]:
        breaks.append(n + 1)
        n += len(para)
    for q in spec["quoted"]:
        for para in q["body"]:
            breaks.append(n + 1)
            n += len(para)
    return {"id": spec["id"], "at": spec["at"][11:16], "from": spec["from"], "subject": spec["subject"],
            "breaks": breaks,
            "customer": {"id": cust["id"], "name": cust["name"]} if cust else None,
            "claims": world.customers[t["spoof"]["claims"]]["name"] if t.get("spoof") else None,
            "sentences": spec["sentences"], "sig": spec.get("sig", []),
            "quoted": [{"from": q["from"], "at": q["at"], "subject": q.get("subject", "")} for q in spec["quoted"]],
            "flags": injection.flags(spec), "what_if": what_if(spec, world, limits),
            "key": {"lane": t["lane"], "handling": t["handling"],
                    "expected": [{"tool": a["tool"], "sentence": a.get("sentence")} for a in t["expected"]],
                    "reply": t["reply"], "spoof": bool(t.get("spoof")), "instruction": t.get("instruction")}}


def items_seen(runs, world):
    """Names and units for every item the morning's runs touch."""
    skus = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "sku" and isinstance(v, str):
                    skus.add(v.upper())
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(runs)
    return {s: {"name": world.items[s]["name"], "unit": world.items[s]["unit"]} for s in sorted(skus)
            if s in world.items}


# ------------------------------------------------------------------------------------------------ the bundle
def build(w):
    world = db.load()
    limits = policy.defaults()
    cfg = read("config", "policy.json")
    names = read("config", "names.json")
    specs = [json.loads(p.read_text(encoding="utf-8"))
             for p in sorted(HERE.joinpath("data", "emails", "morning").glob("m*.json"))]
    specs.sort(key=lambda s: s["at"])
    mlist, route = models()
    scores = read("evals", "scores.json") if HERE.joinpath("evals", "scores.json").exists() else {"models": {}}
    runs = {}
    for m in mlist:
        mine = {e["email_id"]: e for e in (scores["models"].get(m["id"]) or {}).get("emails", [])}
        out = {}
        for spec in specs:
            p = HERE.joinpath("data", "ai_runs", m["id"], f"{spec['id']}.json")
            if p.exists():
                out[spec["id"]] = run_view(json.loads(p.read_text(encoding="utf-8")), spec, mine.get(spec["id"]),
                                           w, world)
        if out:
            runs[m["id"]] = out
    mlist = [m for m in mlist if m["id"] in runs]
    staff = world.meta["staff"]
    approver = next(s for s in staff if s.get("approver"))
    per_model = {}
    for m in mlist:
        s = (scores["models"].get(m["id"]) or {})
        per_model[m["id"]] = {"morning": (s.get("splits") or {}).get("morning"), "bars": s.get("bars"),
                              "cost": s.get("cost_per_email"), "seconds": s.get("seconds_per_email")}
    return {
        "company": names["distributor"]["name"], "today": TODAY, "morning": world.meta["morning"],
        "approver": {"name": approver["name"], "role": approver["role"]},
        "staff": [{"name": s["name"], "role": s["role"], "team": s["team"]} for s in staff],
        "emails": [email_view(s, world, limits) for s in specs],
        "models": mlist, "route": route, "runs": runs, "scores": per_model,
        "items": items_seen(runs, world),
        "limits": {k: dict(v) for k, v in cfg["limits"].items()},
        "switches": {k: v["value"] for k, v in cfg["switches"].items()},
        "routes": cfg["routes"],
        "lexicon": replies.lexicon(), "ui": w.ui(),
    }


def write(data, path=None):
    path = Path(path or HERE.joinpath("site", "data.js"))
    path.write_text("window.IA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    return path.stat().st_size
