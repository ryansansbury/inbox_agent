"""Write tests/vectors/replies.json: replies the Python and JavaScript reply checkers must judge the same way.

    python3 tests/make_reply_vectors.py   (tests/make_vectors.py runs it too)

Each of the 48 stand-in replies with its run's evidence table, a broken copy of each (a wrong amount, a moved date, an
invented order number, a promise made too early or with nothing behind it), and a set of hand-written sentences that
exercise every pattern: abbreviations, slashes, weekdays, word counts, times, sizes, measures and negations.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from engine import replies  # noqa: E402
from engine.tools import Store  # noqa: E402
from generate import validate  # noqa: E402
from owner import stand_in  # noqa: E402

OUT = HERE.joinpath("tests", "vectors", "replies.json")
TODAY = "2026-10-27"
EXTRA = [
    "Your order ships Thursday, Oct. 29 by 2 p.m. and the 3rd box is 12x10x6 at 32 ECT.",
    "We can't waive the $95 rush fee, and we won't credit invoice 30921 without approval.",
    "Two bundles go out tomorrow, and the other twelve cases ship next Monday or on 11/2.",
    "The 18 inch, 80 gauge film is 15% off until noon, then $64.00 a case for 30 days.",
    "PO 4471 and PO PF-88213 match SO-20812, INV-30942, CM-2231, RA-1182, AP-101 and PRO 5521-8804.",
    "We've placed your order and it's been placed on hold until Friday, October 30 for review.",
    "We've issued a credit of $186.40 and we're reshipping the replacements today.",
    "Your refund is pending approval, and the return authorization follows once it's reviewed.",
    "We've updated the address on SO-20817 and changed the ship-to as asked.",
    "Saturday, October 31 works, and so does Sunday, November 1 or Friday, November 2.",
    "Order 20812 and invoice no. 30921 are both open, with 2026 totals of $1,284 and $0.50.",
    "Hi Clara,\n\nWe've waived the fee.\nThanks,\nThe desk",
    "",
]


def mutate(reply):
    """A broken copy: the first amount off by a dollar, the first date moved, and an invented order and promise."""
    out = re.sub(r"\$(\d[\d,]*)\.(\d{2})", lambda m: f"${int(m.group(1).replace(',', '')) + 1}.{m.group(2)}", reply,
                 count=1)
    out = re.sub(r"\b(October|November) (\d{1,2})\b", lambda m: f"{m.group(1)} {int(m.group(2)) % 28 + 1}", out,
                 count=1)
    return out + " We've also waived the liftgate fee and placed order SO-29999 for you."


def main():
    specs = validate.load_specs()
    key = json.loads(HERE.joinpath("data", "key", "key.json").read_text(encoding="utf-8"))
    tables, cases = {}, []
    for s in specs:
        run = stand_in.run_email(s, key[s["id"]], stand_in.seq_of(s, specs))
        store = Store(s, seq=run["seq"])
        steps = [{"tool": x["tool"], "args": x["args"], "result": store.run(x["tool"], x["args"])} for x in run["steps"]]
        tables[s["id"]] = replies.for_run(store, s, steps, TODAY)
        reply = run["finish"]["reply"]
        for text in (reply, mutate(reply)) if reply else (reply,):
            cases.append({"table": s["id"], "reply": text, "want": replies.check(text, tables[s["id"]])})
    for text in EXTRA:
        for tid in ("m05", "m01", "m07"):
            cases.append({"table": tid, "reply": text, "want": replies.check(text, tables[tid])})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"lexicon": replies.lexicon(), "tables": tables, "cases": cases}) + "\n",
                   encoding="utf-8")
    claims = sum(len(c["want"]) for c in cases)
    bad = sum(1 for c in cases for x in c["want"] if x["status"] != "supported")
    print(f"Wrote tests/vectors/replies.json: {len(cases)} replies with {claims} claims, {bad} of them flagged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
