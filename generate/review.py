"""The morning for review before the key freezes: the twelve emails as they arrive, and for each the right
handling, the actions with the verdict the limits give them, what would be unsafe, and the facts the reply must carry.
The 36 scored emails follow, one line each.

    python3 generate/review.py    writes data/out/morning_review.html

Everything on it comes from the specs and the compiled key, after the validator passes. Nothing here ships.
"""
import html
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from engine import db, policy  # noqa: E402
from generate import validate  # noqa: E402

OUT = HERE.joinpath("data", "out", "morning_review.html")
LANE_NAMES = {"handled": "Handled", "needs_you": "Needs you", "customer": "Waiting on the customer",
              "stopped": "Stopped"}
TEAMS = {"order_desk": "the order desk", "sales": "sales", "credit": "credit", "security": "security"}
CAPS = {"credit_cap": "credit cap", "reship_cap": "reship cap", "fee_waiver_cap": "fee waiver cap",
        "order_cap": "order cap"}


def esc(x):
    return html.escape(str(x))


def usd(x):
    return f"${x:,.2f}"


def day(iso):
    d = date.fromisoformat(iso[:10])
    return f"{d.strftime('%a')} {d.strftime('%b')} {d.day}"


def item(w, sku):
    i = w.items.get(sku)
    return f"{i['name'].replace('Shipping box ', '')} ({sku})" if i else sku


def lines(w, ls):
    return ", ".join(f"{l['qty']} × {item(w, l['sku'])}" for l in ls)


def describe(w, cid, a):
    t, x = a["tool"], a["args"]
    c = a.get("computed") or {}
    if t == "issue_credit":
        return f"Credit {usd(x['amount'])} on {x['invoice_id']}"
    if t == "reship":
        return f"Reship {lines(w, x['lines'])} on {x['order_id']}, worth {usd(c.get('value', 0))}"
    if t == "update_ship_to":
        loc = w.location(cid, x["location_id"]) or {}
        return f"Change {x['order_id']}'s ship-to to the {loc.get('label', '').lower()} in {loc.get('city', '')}"
    if t == "create_order":
        bits = [f"Order {lines(w, x['lines'])} for {usd(c.get('total', 0))}"]
        if x.get("rush"):
            bits.append("rush")
        if x.get("requested_date"):
            bits.append(f"by {day(x['requested_date'])}")
        plan = c.get("allocation") or {}
        split = "; ".join(" and ".join(f"{p['qty']} from {p['warehouse']}" for p in v)
                          for v in plan.values() if v and len(v) > 1)
        return ", ".join(bits) + (f" ({split})" if split else "")
    if t == "waive_fee":
        where = "the new order" if x.get("order_id") == "$new_order" else (x.get("invoice_id") or x.get("order_id"))
        return f"Waive the {usd(c.get('amount', 0))} {x['fee']} fee on {where}"
    if t == "create_return":
        return (f"Return {lines(w, x['lines'])} from {x['order_id']}: {usd(c.get('gross', 0))} less the "
                f"{usd(c.get('restocking_fee', 0))} restocking fee, a {usd(c.get('credit', 0))} credit")
    if t == "hold_order":
        return f"Hold {x['order_id']}" + (f" until {day(x['until'])}" if x.get("until") else "")
    if t == "route_to_person":
        return f"Send it to {TEAMS.get(x.get('team'), x.get('team'))}"
    if t == "ask_customer":
        about = x.get("about") or []
        return "Ask the customer about " + " or ".join(item(w, s) if s in w.items else s for s in about)
    return t


def verdict_words(v):
    rule, verdict = v["rule"], v["verdict"]
    if verdict == "done":
        if rule in CAPS:
            return "Goes through", f"under the {usd(v['limit'])[:-3]} {CAPS[rule]}"
        return "Goes through", {"ship_to_before_pick": "not picked yet", "hold_before_ship": "not shipped yet"}.get(
            rule, "always allowed")
    if verdict == "waiting":
        who = "Waits for credit" if v["approver"] == "credit" else "Waits for you"
        if rule in CAPS:
            return who, f"over the {usd(v['limit'])[:-3]} {CAPS[rule]}"
        return who, {"credit_line": f"over the open credit of {usd(v['limit'] or 0)}",
                     "account_hold": "the account is on hold",
                     "ship_to_before_pick": "already picked, and address changes stop at the pick"}.get(rule, rule)
    return "Blocked", rule


def fact_words(f):
    k, v = f["kind"], f["value"]
    if k == "amount":
        return usd(v)
    if k == "date":
        return day(v)
    if k == "time":
        h, m = map(int, v.split(":"))
        return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"
    if k == "status":
        return v.replace("_", " ")
    return str(v)


def email_card(w, spec, entry):
    t = spec["truth"]
    cid = entry["customer_id"]
    who = w.customers[cid]["name"] if cid else "Outside sender"
    if t["spoof"]:
        who = f"Look-alike of {w.customers[t['spoof']['claims']]['name']} (the real address is {t['spoof']['real']})"
    out = [f"<section class='email' id='{spec['id']}'>",
           f"<header><span class='time'>{esc(spec['at'][11:16])}</span><span class='lane {entry['lane']}'>"
           f"{LANE_NAMES[entry['lane']]}</span><span class='id'>{spec['id']}</span></header>",
           f"<h2>{esc(spec['subject'])}</h2>",
           f"<p class='from'>{esc(spec['from']['name'])} &lt;{esc(spec['from']['email'])}&gt; · {esc(who)}</p>",
           "<div class='mail'>"]
    sents = {s["n"]: s for s in spec["sentences"]}
    n = 0
    for para in spec["body"]:
        out.append("<p>" + " ".join(_sentence(sents[n + i + 1], t) for i in range(len(para))) + "</p>")
        n += len(para)
    out.append("<p class='sig'>" + "<br>".join(esc(x) for x in spec["sig"]) + "</p>")
    for q in spec["quoted"]:
        out.append(f"<blockquote><p class='qhead'>From {esc(q['from'])}, {esc(q['subject'])}</p>")
        for para in q["body"]:
            out.append("<p>" + " ".join(_sentence(sents[n + i + 1], t) for i in range(len(para))) + "</p>")
            n += len(para)
        out.append("<p class='sig'>" + "<br>".join(esc(x) for x in q.get("sig", [])) + "</p></blockquote>")
    out.append("</div>")
    out.append(f"<p class='handling'><b>The right handling.</b> {esc(t['handling'])}</p>")
    if entry["expected"]:
        out.append("<h3>Actions</h3><ul class='acts'>")
        for a in entry["expected"]:
            if a["tool"] in ("ask_customer", "route_to_person"):
                head = "Asks" if a["tool"] == "ask_customer" else "Routes"
                text = describe(w, cid, a).split(" ", 2 if a["tool"] == "route_to_person" else 1)[-1]
                out.append(f"<li><span class='verdict ask'>{head}</span> {esc(text)}"
                           f" <span class='why'>(answering sentence {a['sentence']})</span></li>")
                continue
            head, why = verdict_words(a["verdict"])
            out.append(f"<li><span class='verdict {a['verdict']['verdict']}'>{head}</span> {esc(describe(w, cid, a))}"
                       f" <span class='why'>({esc(why)}, answering sentence {a['sentence']})</span></li>")
        out.append("</ul>")
    elif t["reply"]:
        out.append("<h3>Actions</h3><p class='none'>None. The reply answers from the records.</p>")
    else:
        out.append("<h3>Actions</h3><p class='none'>None, and no reply.</p>")
    if t["acceptable"]:
        out.append("<p class='also'><b>Also fine:</b> " + "; ".join(
            esc(describe(w, cid, a) if a["args"] else a["tool"].replace("_", " ")) for a in t["acceptable"]) + "</p>")
    if t["forbidden"]:
        out.append("<p class='never'><b>Unsafe if the agent did it:</b> " + "; ".join(
            f"{esc(a['tool'].replace('_', ' '))} ({esc(a.get('why', ''))})" for a in t["forbidden"]) + "</p>")
    if t["facts"]:
        out.append("<p class='facts'><b>The reply must carry:</b> " +
                   ", ".join(esc(fact_words(f)) for f in t["facts"]) + "</p>")
    out.append("</section>")
    return "\n".join(out)


def _sentence(s, t):
    cls = "inj" if t["instruction"] == s["n"] else ""
    return f"<span class='s {cls}'><sup>{s['n']}</sup>{esc(s['text'])}</span>"


CSS = """
@font-face{font-family:Inter;src:url(../../site/fonts/inter-latin.woff2) format('woff2');font-weight:100 900}
:root{--ink:#1e2227;--soft:#5b6470;--line:#d9d6cf;--bg:#ecebe7;--card:#fbfaf7;--amber:#b45309;--green:#2f6b3a;
--red:#a3302a;--blue:#2b5b84}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Inter,system-ui,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:32px 20px 80px}h1{font-size:26px;margin:0 0 6px}
.lede{color:var(--soft);margin:0 0 18px}.summary{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 18px;margin-bottom:22px}.summary b{color:var(--ink)}
.email{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 22px;margin:0 0 18px}
.email header{display:flex;gap:10px;align-items:center;font-size:13px;color:var(--soft)}
.time{font-weight:600;color:var(--ink)}.id{margin-left:auto}
.lane{border-radius:999px;padding:1px 10px;font-weight:600;font-size:12px;border:1px solid}
.lane.handled{color:var(--green)}.lane.needs_you{color:var(--amber)}.lane.customer{color:var(--blue)}
.lane.stopped{color:var(--red)}h2{font-size:18px;margin:6px 0 2px}.from{color:var(--soft);font-size:13px;margin:0 0 10px}
.mail{border-left:3px solid var(--line);padding:2px 0 2px 14px;margin:8px 0 12px}.mail p{margin:6px 0}
sup{color:var(--soft);font-size:10px;margin-right:2px}.sig{color:var(--soft);font-size:13px}
blockquote{margin:8px 0;padding:6px 12px;background:#f1efe9;border-radius:6px}.qhead{font-size:12px;color:var(--soft)}
.inj{background:#fde8e4;outline:1px solid #e9b3a9;border-radius:3px}
.handling{margin:8px 0}h3{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--soft);margin:12px 0 4px}
.acts{margin:0;padding-left:18px}.acts li{margin:3px 0}.verdict{font-weight:600}.verdict.done{color:var(--green)}
.verdict.waiting{color:var(--amber)}.verdict.ask{color:var(--blue)}.why{color:var(--soft);font-size:13px}.none{margin:2px 0;color:var(--soft)}
.also,.never,.facts{font-size:14px;margin:6px 0}.never b{color:var(--red)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 18px;margin-top:26px}
summary{cursor:pointer;font-weight:600}table{border-collapse:collapse;width:100%;font-size:13px;margin-top:10px}
td{border-top:1px solid var(--line);padding:6px 6px;vertical-align:top}td.l{white-space:nowrap}
"""


def main():
    specs = validate.load_specs()
    w = db.load()
    entries, bad = {}, []
    for s in specs:
        problems, entry = validate.check(s)
        if problems:
            bad.append(s["id"])
        entries[s["id"]] = entry
    if bad:
        sys.exit(f"Stopped: the validator fails on {', '.join(bad)}. Run generate/validate.py.")
    set_problems, moved = validate.check_set(specs)
    if set_problems:
        sys.exit("Stopped: " + "; ".join(set_problems))
    morning = sorted((s for s in specs if s["split"] == "morning"), key=lambda s: s["at"])
    lanes = {}
    for s in morning:
        lanes[entries[s["id"]]["lane"]] = lanes.get(entries[s["id"]]["lane"], 0) + 1
    lim = policy.defaults()
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>The morning for review</title>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'><style>{CSS}</style></head><body>"
             "<div class='wrap'>",
             "<h1>The morning for review</h1>",
             "<p class='lede'>Wendlow Packaging Supply's order inbox on Tuesday, October 27, 2026, from 7:00 to 9:30 AM. "
             "These twelve emails become the page, and the key and the scores are made from them. Approve them, or say "
             "what to change.</p>",
             "<div class='summary'>"
             f"<p><b>{lanes.get('handled', 0)} handled, {lanes.get('needs_you', 0)} need you, "
             f"{lanes.get('customer', 0)} wait on the customer and {lanes.get('stopped', 0)} are stopped</b>, decided "
             f"by the limits: credits up to {usd(lim['credit_cap'])[:-3]}, reships up to {usd(lim['reship_cap'])[:-3]}, "
             f"fee waivers up to {usd(lim['fee_waiver_cap'])[:-3]}, new orders up to {usd(lim['order_cap'])[:-3]} "
             f"inside the open credit, address changes before the pick, returns unopened within "
             f"{lim['return_days']} days less a {lim['restocking_pct']}% restocking fee, and never a price, terms or "
             "bank change.</p>"
             f"<p>Lowering the credit cap to $100 moves {', '.join(moved)} to Needs you, the spec's three cards.</p>"
             "<p>The highlighted sentences are instructions hidden inside an email, which the agent must not follow. "
             "Every value here was checked against the records by the validator.</p></div>"]
    for s in morning:
        parts.append(email_card(w, s, entries[s["id"]]))
    rest = [s for s in specs if s["split"] != "morning"]
    rows = "".join(f"<tr><td class='l'>{s['id']}</td><td class='l'>{LANE_NAMES[entries[s['id']]['lane']]}</td>"
                   f"<td><b>{esc(s['subject'])}</b> · {esc(s['from']['name'])}<br>{esc(s['truth']['handling'])}</td></tr>"
                   for s in rest)
    parts.append(f"<details><summary>The other 36, scored but not on the page (12 for tuning, 24 for the test)"
                 f"</summary><table>{rows}</table></details>")
    parts.append("</div></body></html>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote data/out/morning_review.html: {len(morning)} emails, then {len(rest)} in a list.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
