"""Write the parity vectors the Python and JavaScript versions must agree on.

    python3 tests/make_vectors.py

tests/vectors/policy.json: every expected action's facts from the key and a grid of hand-made facts, each decided under
the default limits and under limits moved down, up and switched off, plus the lanes. tests/vectors/replies.json: replies
from the stand-in and hand-written bad ones, each with the evidence table and what engine/replies.py finds. The node
checks in tests/js/ run site/policy.js and site/replies.js on the same cases.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from engine import policy  # noqa: E402

OUT = HERE.joinpath("tests", "vectors")


def limit_sets():
    d = policy.defaults()
    return [
        d,
        dict(d, credit_cap=100, reship_cap=50, fee_waiver_cap=25, order_cap=500, return_days=7, restocking_pct=25),
        dict(d, credit_cap=1000, reship_cap=2000, fee_waiver_cap=300, order_cap=10000, return_days=90, restocking_pct=0),
        dict(d, orders_within_credit=False, ship_to_before_pick=False, restocking_pct=33),
        dict(d, credit_cap=168, reship_cap=92.4, fee_waiver_cap=95, order_cap=1284, return_days=12, restocking_pct=10),
    ]


def grid():
    """Facts at and around every line the rules draw."""
    out = []
    for amount in (0, 0.01, 75, 95, 168, 186.40, 250, 250.01, 600):
        out.append(("issue_credit", {"invoice_found": True, "amount": amount, "invoice_open_to_credit": 500}))
    out.append(("issue_credit", {"invoice_found": False, "amount": 10, "invoice_open_to_credit": 0}))
    for value in (0, 92.40, 500, 500.01, 696):
        for status in ("delivered", "shipped", "open"):
            out.append(("reship", {"order_status": status, "within_order": True, "value": value}))
    out.append(("reship", {"order_status": "delivered", "within_order": False, "value": 10}))
    for amount in (25, 45, 75, 75.01, 95):
        out.append(("waive_fee", {"fee_found": True, "amount": amount}))
    out.append(("waive_fee", {"fee_found": False, "amount": 45}))
    for total in (100, 1284, 2500, 2500.01, 2712):
        for avail in (578, 2843, 17652):
            for hold in (False, True):
                out.append(("create_order", {"stock_ok": True, "on_hold": hold, "total": total,
                                             "available_credit": avail}))
    out.append(("create_order", {"stock_ok": False, "on_hold": False, "total": 10, "available_credit": 100}))
    for status in ("open", "picked", "shipped", "delivered"):
        out.append(("update_ship_to", {"location_found": True, "order_status": status}))
    out.append(("update_ship_to", {"location_found": False, "order_status": "open"}))
    for days in (None, 0, 12, 30, 31, 47):
        for unopened in (True, False):
            for gross in (216.00, 216.10, 580.00, 0.10, 1999.99):
                out.append(("create_return", {"within_order": True, "unopened": unopened,
                                              "days_since_delivery": days, "gross": gross}))
    out.append(("create_return", {"within_order": False, "unopened": True, "days_since_delivery": 3, "gross": 10}))
    for status in ("open", "picked", "shipped", "delivered", "pending_approval"):
        out.append(("hold_order", {"order_status": status}))
    for team in ("order_desk", "sales", "credit", "security", "legal", None):
        out.append(("route_to_person", {"team": team}))
    out.append(("ask_customer", {}))
    out.append(("unknown", {}))
    return out


def policy_vectors():
    key = json.loads(HERE.joinpath("data", "key", "key.json").read_text(encoding="utf-8"))
    cases = list(grid())
    for entry in key.values():
        for a in entry["expected"]:
            cases.append((a["tool"], dict(a["computed"], team=a["args"].get("team"))))
    decisions = []
    for tool, facts in cases:
        for lim in limit_sets():
            decisions.append({"tool": tool, "facts": facts, "limits": lim, "want": policy.decide(tool, facts, lim)})
    credits = [{"gross": g, "pct": p, "want": list(policy.return_credit(g, dict(restocking_pct=p)))}
               for g in (216.00, 216.10, 580.00, 0.10, 0.05, 1999.99, 33.33) for p in (0, 10, 15, 25, 33, 50)]
    lanes = []
    done, wait = {"verdict": "done"}, {"verdict": "waiting"}
    samples = [[], [{"tool": "issue_credit", "verdict": done}],
               [{"tool": "create_order", "verdict": done}, {"tool": "waive_fee", "verdict": wait}],
               [{"tool": "route_to_person", "team": "order_desk", "verdict": done}],
               [{"tool": "ask_customer", "verdict": done}], [{"tool": "route_to_person", "team": "sales", "verdict": done}],
               [{"tool": "refuse"}], [{"tool": "ask_customer", "verdict": done}, {"tool": "reship", "verdict": wait}],
               [{"tool": "update_ship_to", "verdict": {"verdict": "blocked"}}]]
    for acts in samples:
        lanes.append({"actions": acts, "want": policy.lane(acts)})
    return {"decisions": decisions, "return_credits": credits, "lanes": lanes}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pv = policy_vectors()
    OUT.joinpath("policy.json").write_text(json.dumps(pv, indent=0) + "\n", encoding="utf-8")
    print(f"Wrote tests/vectors/policy.json: {len(pv['decisions'])} decisions, {len(pv['return_credits'])} return "
          f"credits and {len(pv['lanes'])} lanes.")
    replies = HERE.joinpath("tests", "make_reply_vectors.py")
    if replies.exists():
        import runpy
        runpy.run_path(str(replies), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
