"""Check a reply against what the agent saw: every number, date, time, ID and item in it has to come from a tool result,
the email or the limits, and every promise has to match an action the rules let through.

    t = table(results, spec, limits, today)  everything the agent saw, as plain lists (the build writes it to the page)
    check(reply, t)                          [{"kind", "text", "start", "end", "status", "reason"}]

It finds order, invoice, PO, tracking, credit memo, return and approval numbers, item SKUs, sizes (12x10x6) and
measures (2 inch, 80 gauge, 32 ECT), dollar amounts, percentages, counts (2 bundles, 30 days), dates (October 29, 10/29,
Thursday, tomorrow) and times (2 PM). An amount is also supported when it's a difference, a sum or a quantity times a
price of amounts the agent saw ($4.66 a bundle from $27.06 and $22.40). A promise (credited, reshipped, placed, waived,
changed the address, opened a return, put on hold) is supported by a done action of its kind. If that action waits for
a person, the sentence has to say so ("pending," "once approved," "for review"), or it's premature. A promise with no
action behind it is unsupported, and a sentence that says it can't or won't do something isn't a promise. Each claim
comes back supported, unsupported or premature with its reason. site/replies.js runs the same checks on the same table,
and tests/vectors/replies.json holds the cases both must agree on. It doesn't judge tone, which the page says.
"""
import re
from datetime import date, timedelta

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
          "december"]
ABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
        "nov": 11, "dec": 12}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
SMALL = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60}
MONTH_RE = "|".join(MONTHS + sorted(ABBR, key=len, reverse=True))
DAY_RE = "|".join(DAYS)
SMALL_RE = "|".join(sorted(SMALL, key=len, reverse=True))
UNIT_RE = (r"bundles?|cases?|rolls?|bags?|boxes|box|units?|pallets?|coils?|cartons?|pieces?|days?|weeks?|invoices?|"
           r"orders?|items?")
COUNT_MID = r"(?:(?:more|extra|additional|missing|short|damaged|crushed|sealed|unopened|replacement|opened|new)\s+)?"
SKU_RE = r"\b(?:BX|MB|PM|PD|RM|TP|SF|VF|LB|PL|ST|EP)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b"
MEASURE_UNITS = {"inch": "in", "inches": "in", "in": "in", "gauge": "gauge", "ect": "ect", "ft": "ft", "feet": "ft",
                 "lb": "lb", "lbs": "lb", "yd": "yd", "yds": "yd", "yards": "yd"}

PATTERNS = [  # (kind, how its value is read, regex) in priority order; a later match can't overlap an earlier one
    ("tracking", "tracking", r"\bPRO\s?(\d{4})-(\d{4})\b"),
    ("order", "id", r"\bSO-(\d{5})\b"),
    ("invoice", "id", r"\bINV-(\d{5})\b"),
    ("credit_memo", "id", r"\bCM-(\d{4})\b"),
    ("return", "id", r"\bRA-(\d{4})\b"),
    ("approval", "id", r"\bAP-(\d{2,4})\b"),
    ("sku", "upper", SKU_RE),
    ("order", "id", r"\border\s+(?:number\s+|no\.\s*|#\s*)?(\d{5})\b"),
    ("invoice", "id", r"\binvoice\s+(?:number\s+|no\.\s*|#\s*)?(\d{5})\b"),
    ("po", "po", r"\bPO\s*#?\s*([A-Z]{0,3}-?\d{3,6})\b"),
    ("date", "weekday_month", r"\b(" + DAY_RE + r"),?\s+(" + MONTH_RE + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b"),
    ("date", "month_day", r"\b(" + MONTH_RE + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b"),
    ("date", "iso", r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    ("date", "numeric", r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?\b"),
    ("date", "relative", r"\b(today|tomorrow|yesterday)\b"),
    ("date", "weekday", r"\b(?:(next|this)\s+)?(" + DAY_RE + r")\b"),
    ("time", "clock", r"\b(\d{1,2})(?::(\d{2}))?\s?([ap])\.?m\b"),
    ("time", "noon", r"\bnoon\b"),
    ("money", "money", r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?"),
    ("percent", "float", r"\b(\d+(?:\.\d+)?)\s?(?:%|percent\b)"),
    ("size", "size", r"\b(\d+(?:\.\d+)?)\s?x\s?(\d+(?:\.\d+)?)(?:\s?x\s?(\d+(?:\.\d+)?))?\b"),
    ("measure", "measure", r"\b(\d+(?:\.\d+)?)[\s-]?(inches|inch|in(?=\s?x\s?\d)|gauge|ect|ft|feet|lbs|lb|yds|yd|"
                           r"yards)\b"),
    ("count", "count", r"\b(\d+|" + SMALL_RE + r")\s+" + COUNT_MID + r"(?:of the\s+)?(" + UNIT_RE + r")\b"),
    ("number", "whole", r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b"),
]
FLAGS = re.I | re.A
COMPILED = [(k, how, re.compile(p, FLAGS)) for k, how, p in PATTERNS]
LIST_MARKER = re.compile(r"^[ \t]*\d{1,2}[.)](?=\s)", re.M | re.A)
ID_PREFIX = {"order": "SO-", "invoice": "INV-", "credit_memo": "CM-", "return": "RA-", "approval": "AP-"}

PROMISES = [  # (kind, [regex], the action tools that back it)
    ("credit", [r"\bcredit(?:ed)?\s+(?:you|your account|it|them|the (?:difference|amount)|\$)",
                r"\b(?:issued|applied|posted|processed|created|added)\b[^.!?]*\bcredit\b",
                r"\bcredit\b[^.!?]*\b(?:has been|was|is now|is)\s+(?:issued|applied|posted|processed|created|added)\b",
                r"\bcredit memo\b", r"\brefund(?:ed|ing)?\b"],
     ["issue_credit", "create_return"]),
    ("reship", [r"\breship(?:ped|ping)?\b", r"\bre-?sen(?:d|t|ding)\b", r"\breplacing\b",
                r"\b(?:sent|sending|shipped|shipping|ship|send|sends)\b[^.!?]*\breplacements?\b",
                r"\breplacements?\b[^.!?]*\b(?:is|are|has been|have been|was|were|will be)\s+(?:on (?:the|its|their) way|"
                r"shipped|sent|going out|scheduled|out)\b"], ["reship"]),
    ("order", [r"\border\b[^.!?]*\b(?:is|has been|was)\s+(?:placed|entered|booked)\b",
               r"\b(?:placed|entered|booked|created|put in)\s+(?:(?:your|the|an|a|this|that)\s+)?(?:new\s+|rush\s+|"
               r"holiday\s+|replacement\s+)?order\b", r"\b(?:placed|entered|booked)\s+it\s+as\s+(?:an?\s+)?order\b"],
     ["create_order", "reship"]),
    ("waive", [r"\bwaiv(?:e|ed|ing)\b", r"\b(?:removed|taken off|took off)\b[^.!?]*\bfee\b"], ["waive_fee"]),
    ("ship_to", [r"\b(?:updated|changed|switched)\b[^.!?]*\b(?:ship-?to|address|destination)\b",
                 r"\b(?:ship-?to|address)\b[^.!?]*\b(?:updated|changed|switched)\b"], ["update_ship_to"]),
    ("return", [r"\breturn (?:authorization|number|label)\b", r"\b(?:opened|set up|created|approved|started)\b[^.!?]*"
                r"\breturn\b"], ["create_return"]),
    ("hold", [r"\b(?:put|placed|holding|held)\b[^.!?]*\bon hold\b", r"\b(?:placed|put)\s+a\s+hold\s+on\b",
              r"\b(?:held|on hold) until\b"],
     ["hold_order", "*waiting"]),
]
PROMISES_C = [(k, [re.compile(p, FLAGS) for p in ps], tools) for k, ps, tools in PROMISES]
NEGATION = re.compile(r"\b(?:not|can't|cannot|can not|won't|unable|isn't|aren't|couldn't|don't|didn't|doesn't|"
                      r"haven't|hasn't|wasn't|weren't|shouldn't|wouldn't|no longer|never|without|no (?:returns?|"
                      r"credits?|refunds?|orders?|changes?|actions?|holds?|replacements?|reships?|fee waivers?))\b",
                      FLAGS)
CONDITIONAL = re.compile(r"\b(?:once|when|after|before|until|as soon as|if)\b", FLAGS)
PENDING = re.compile(r"\b(?:pending|waiting|awaiting|once (?:it'?s |it is |that's |that is )?approved|for approval|"
                     r"needs? (?:a )?(?:person|approval|sign-?off|review)|review|reviews|reviewing|reviewed|"
                     r"will confirm|after (?:approval|review)|until approved|requested|submitted|on hold|request|"
                     r"on our own|over (?:what we can|our (?:limit|cap)|the (?:limit|cap))|above (?:our|the) (?:limit|cap)|"
                     r"(?:has|have|needs?) to (?:be )?approv(?:e|ed)|a person (?:has|needs) to)\b", FLAGS)
SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)|\n+", re.A)


def _iso(d):
    return d.isoformat()


def _month(word):
    w = word.lower()
    return MONTHS.index(w) + 1 if w in MONTHS else ABBR.get(w)


def _date(today, month, day):
    try:
        return date(today.year, month, day) if month else None
    except ValueError:
        return None


def _weekday(today, which, name):
    target = DAYS.index(name.lower())
    if which and which.lower() == "next":
        return today + timedelta(days=7 - today.weekday() + target)
    return today + timedelta(days=(target - today.weekday()) % 7 or 7)


def _num(text):
    t = text.lower()
    return float(SMALL[t]) if t in SMALL else float(t)


def extract(text, today):
    """Every claim in the text: [{"kind", "text", "start", "end", "value", ...}], in reading order."""
    if isinstance(today, str):
        today = date.fromisoformat(today)
    taken, out = [(m.start(), m.end()) for m in LIST_MARKER.finditer(text)], []
    for kind, how, rx in COMPILED:
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            if any(s < b and a < e for a, b in taken):
                continue
            claim = {"kind": kind, "text": m.group(0), "start": s, "end": e}
            claim.update(_value(how, kind, m.group(0), m.groups(), today))
            taken.append((s, e))
            out.append(claim)
    return sorted(out, key=lambda c: c["start"])


def _value(how, kind, whole, g, today):
    """A claim's value, by the pattern that found it. site/replies.js has the same switch."""
    if how == "tracking":
        return {"value": f"PRO {g[0]}-{g[1]}"}
    if how == "id":
        return {"value": ID_PREFIX[kind] + g[0]}
    if how in ("upper", "po"):
        return {"value": (whole if how == "upper" else g[0]).upper()}
    if how == "weekday_month":
        d = _date(today, _month(g[1]), int(g[2]))
        out = {"value": _iso(d) if d else None}
        if d and DAYS[d.weekday()] != g[0].lower():
            out["weekday_mismatch"] = True
        return out
    if how == "month_day":
        d = _date(today, _month(g[0]), int(g[1]))
        return {"value": _iso(d) if d else None}
    if how == "iso":
        try:
            return {"value": _iso(date(int(g[0]), int(g[1]), int(g[2])))}
        except ValueError:
            return {"value": None}
    if how == "numeric":
        d = _date(today, int(g[0]), int(g[1])) if 1 <= int(g[0]) <= 12 else None
        return {"value": _iso(d) if d else None}
    if how == "relative":
        return {"value": _iso(today + timedelta(days={"today": 0, "tomorrow": 1, "yesterday": -1}[g[0].lower()]))}
    if how == "weekday":
        return {"value": _iso(_weekday(today, g[0], g[1]))}
    if how == "clock":
        h = int(g[0]) % 12 + (12 if g[2].lower() == "p" else 0)
        return {"value": f"{h:02d}:{int(g[1] or 0):02d}"}
    if how == "noon":
        return {"value": "12:00"}
    if how == "money":
        return {"value": int(g[0].replace(",", "")) * 100 + int((g[1] or "0").ljust(2, "0"))}
    if how == "float":
        return {"value": float(g[0])}
    if how == "size":
        return {"value": "x".join(_trim(x) for x in g if x)}
    if how == "measure":
        return {"value": _trim(g[0]) + MEASURE_UNITS[g[1].lower()]}
    if how == "count":
        return {"value": _num(g[0])}
    return {"value": float(whole.replace(",", ""))}


def _trim(x):
    f = float(x)
    return str(int(f)) if f == int(f) else str(f)


def sentences(text):
    """(start, end) of each sentence, for the promise checks."""
    out, start = [], 0
    for m in SENTENCE_END.finditer(text):
        if text[start:m.end()].strip():
            out.append((start, m.end()))
        start = m.end()
    if text[start:].strip():
        out.append((start, len(text)))
    return out


def check(reply, t):
    """Every claim and promise in a reply, judged against a table from table()."""
    today = date.fromisoformat(t["today"])
    out = []
    ids = {k: set(v) for k, v in t["ids"].items()}
    numbers = set(t["numbers"])
    for c in extract(reply, today):
        kind, val = c["kind"], c.get("value")
        ok, reason = True, ""
        if kind in ids:
            ok = val in ids[kind]
            reason = f"no tool result or line of the email has {val}"
        elif kind == "date":
            if c.get("weekday_mismatch"):
                ok, reason = False, "the weekday doesn't match the date"
            else:
                ok = val in t["dates"]
                reason = "no tool result or line of the email has this date"
        elif kind == "time":
            ok = val in t["times"]
            reason = "no tool result or line of the email has this time"
        elif kind == "money":
            ok = val in t["money"]
            reason = "no tool result has this amount, and no sum or difference of what the agent saw makes it"
        elif kind == "size":
            ok = val in t["sizes"]
            reason = "no item the agent saw has this size"
        elif kind == "measure":
            ok = val in t["measures"]
            reason = "no item the agent saw has this measure"
        elif kind in ("percent", "count", "number"):
            ok = val in numbers or (kind == "number" and 2025 <= val <= 2027 and val == int(val))
            reason = "no tool result or line of the email has this number"
        out.append(dict(c, status="supported" if ok else "unsupported", reason="" if ok else reason))
    acts = t["actions"]
    for s, e in sentences(reply):
        text = reply[s:e]
        if NEGATION.search(text) or text.rstrip().endswith("?"):
            continue  # what it won't or can't do, and questions, aren't promises
        for kind, rxs, tools in PROMISES_C:
            m = next((x for x in (rx.search(text) for rx in rxs) if x), None)
            if not m or CONDITIONAL.search(text[:m.end()]):
                continue  # "once it's placed" is a condition, not a claim it was
            done = any(a["tool"] in tools and a["verdict"] == "done" for a in acts)
            waiting = any((a["tool"] in tools or "*waiting" in tools) and a["verdict"] == "waiting" for a in acts)
            claim = {"kind": "promise", "promise": kind, "text": m.group(0), "start": s + m.start(),
                     "end": s + m.end(), "value": kind}
            # A held order is entered, so saying so is true when the reply calls it pending somewhere.
            scope = reply if kind == "order" else text
            if done:
                claim.update(status="supported", reason="")
            elif waiting and PENDING.search(scope):
                claim.update(status="supported", reason="")
            elif waiting:
                claim.update(status="premature", reason="it waits for a person, so the reply has to call it pending")
            else:
                claim.update(status="unsupported", reason=f"the agent didn't {_verb(kind)}")
            out.append(claim)
    return sorted(out, key=lambda c: (c["start"], c["kind"]))


def _verb(kind):
    return {"credit": "issue a credit", "reship": "reship anything", "order": "place an order",
            "waive": "waive a fee", "ship_to": "change a ship-to", "return": "open a return",
            "hold": "hold an order"}[kind]


def summary(claims):
    out = {"supported": 0, "unsupported": 0, "premature": 0}
    for c in claims:
        out[c["status"]] += 1
    return out


# ------------------------------------------------------------------------------------------- the evidence table
ID_FIELDS = {"order_id": "order", "replacement_order": "order", "replaces": "order", "invoice_id": "invoice",
             "credit_memo": "credit_memo", "return_id": "return", "approval_id": "approval", "tracking": "tracking",
             "po": "po", "sku": "sku"}
MONEY_KEYS = {"price", "amount", "total", "value", "list_price", "contract_price", "credit", "gross",
              "restocking_fee", "open", "open_balance", "open_orders", "available_credit", "credit_limit", "paid",
              "limit", "invoice_open_after", "charge"}
QTY_KEYS = {"qty", "picked", "shipped", "damaged_on_delivery", "available", "available_total", "lines"}


def table(results, spec, limits, today):
    """Everything the agent saw (tool results, the email and the limits) as plain sorted lists."""
    if isinstance(today, str):
        today = date.fromisoformat(today)
    ids = {k: set() for k in ("order", "invoice", "credit_memo", "return", "approval", "tracking", "po", "sku")}
    strings, numbers, money, qtys = [], set(), set(), set()

    def walk(x, key=None):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, bool) or x is None:
            return
        elif isinstance(x, (int, float)):
            numbers.add(float(x))
            if key in MONEY_KEYS:
                money.add(round(float(x) * 100))
            if key in QTY_KEYS and float(x) == int(x):
                qtys.add(int(x))
        else:
            s = str(x)
            strings.append(s)
            if key in ID_FIELDS:
                ids[ID_FIELDS[key]].add(s.upper() if key in ("po", "sku") else s)

    walk(results)
    walk({k: v for k, v in limits.items() if not isinstance(v, bool)})
    email_text = "\n".join([spec["subject"]] + [s["text"] for s in spec["sentences"]] + spec.get("sig", []))
    strings.append(email_text)
    for c in extract(email_text, today):
        if c["kind"] in ids:
            ids[c["kind"]].add(c["value"])
        elif c["kind"] == "money":
            money.add(c["value"])
        elif c["kind"] in ("count", "number", "percent"):
            numbers.add(c["value"])
            if c["kind"] == "count" and c["value"] == int(c["value"]):
                qtys.add(int(c["value"]))
    dates, times, sizes, measures = {today.isoformat()}, set(), set(), set()
    for s in strings:
        for m in re.finditer(r"\b(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?", s):
            dates.add(m.group(1))
            if m.group(2):
                times.add(m.group(2))
        for m in re.finditer(r"\b\d+(?:\.\d+)?\b", s):
            numbers.add(float(m.group(0)))
        for c in extract(s, today):
            if c["kind"] == "size":
                sizes.add(c["value"])
            elif c["kind"] == "measure":
                measures.add(c["value"])
            elif c["kind"] == "date" and c.get("value") and s is email_text:
                dates.add(c["value"])
            elif c["kind"] == "time" and s is email_text:
                times.add(c["value"])
    low = email_text.lower()
    monday = today - timedelta(days=today.weekday())
    for phrase, start in (("this week", monday), ("next week", monday + timedelta(days=7))):
        if phrase in low:
            dates.update((start + timedelta(days=i)).isoformat() for i in range(5))
    for d in list(dates):
        numbers.add(float(abs((date.fromisoformat(d) - today).days)))
        end = date.fromisoformat(d) + timedelta(days=int(limits.get("return_days", 30)))
        if abs((end - today).days) <= 120:
            dates.add(end.isoformat())  # the end of a return window the agent can work out
    base = sorted(money)
    derived = set(base)
    for i, a in enumerate(base):
        for b in base[i:]:
            derived.add(a + b)
            derived.add(abs(a - b))
        for q in qtys:
            if 0 < q <= 1000:
                derived.add(a * q)
    acts = [{"tool": r["tool"], "verdict": r["verdict"]} for r in spec.get("_actions", [])]
    return {"today": today.isoformat(), "ids": {k: sorted(v) for k, v in ids.items()}, "dates": sorted(dates),
            "times": sorted(times), "money": sorted(derived), "numbers": sorted(numbers), "sizes": sorted(sizes),
            "measures": sorted(measures), "actions": acts}


def for_run(store, spec, steps, today):
    """The table for one recorded or stand-in run: the tool results the agent saw (never its own inputs), the email,
    the limits, and the actions it took with their verdicts."""
    s = dict(spec, _actions=[{"tool": a["tool"], "verdict": a["verdict"]["verdict"]} for a in store.actions])
    return table([x["result"] for x in steps], s, store.limits, today)


def lexicon():
    """The patterns and word lists, exactly as this file uses them, for site/replies.js to compile the same way."""
    return {"patterns": [[k, how, p] for k, how, p in PATTERNS],
            "promises": [[k, ps, tools] for k, ps, tools in PROMISES],
            "negation": NEGATION.pattern, "pending": PENDING.pattern, "sentence_end": SENTENCE_END.pattern,
            "conditional": CONDITIONAL.pattern, "list_marker": LIST_MARKER.pattern,
            "months": MONTHS, "abbr": ABBR, "days": DAYS, "small": SMALL, "measure_units": MEASURE_UNITS,
            "id_prefix": ID_PREFIX}
