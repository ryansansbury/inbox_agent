"""The limits a person sets, as code: whether each action the agent proposes goes through, waits for a person, or never
happens.

    decide(tool, facts, limits=None) -> {"verdict": "done" | "waiting" | "blocked", "rule": ..., "approver": ...}

The facts are the numbers the rules need (an amount, the open credit, how far an order has gone), worked out from the
records by engine/facts.py, so this file holds no lookups and ports line for line to site/policy.js. The defaults live
in config/policy.json, and the page passes its own limits when a visitor moves one.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
LANES = ("handled", "needs_you", "customer", "stopped")
TEAMS = ("order_desk", "sales", "credit", "security")


def defaults(path=None):
    """The limits and switches as plain values, from config/policy.json."""
    raw = json.loads(Path(path or HERE.joinpath("config", "policy.json")).read_text(encoding="utf-8"))
    out = {k: v["value"] for k, v in raw["limits"].items()}
    out.update({k: v["value"] for k, v in raw["switches"].items()})
    return out


def _v(verdict, rule, approver=None, amount=None, limit=None):
    return {"verdict": verdict, "rule": rule, "approver": approver, "amount": amount, "limit": limit}


def _cents(x):
    return round(float(x) * 100)


def return_credit(gross, limits):
    """A return's credit and its restocking fee: the fee is the percentage of the gross in whole cents, rounded half
    up, so Python and the page's JavaScript agree to the cent."""
    g = _cents(gross)
    fee = (g * int(limits["restocking_pct"]) + 50) // 100
    return (g - fee) / 100, fee / 100


def decide(tool, facts, limits=None):
    lim = dict(defaults()) if limits is None else limits
    f = facts
    if tool in ("ask_customer",):
        return _v("done", "always")
    if tool == "route_to_person":
        return _v("done", "always") if f.get("team") in TEAMS else _v("blocked", "unknown_team")
    if tool == "issue_credit":
        if not f.get("invoice_found"):
            return _v("blocked", "credit_needs_invoice")
        if _cents(f["amount"]) <= 0 or _cents(f["amount"]) > _cents(f["invoice_open_to_credit"]):
            return _v("blocked", "credit_over_invoice", amount=f["amount"], limit=f["invoice_open_to_credit"])
        if _cents(f["amount"]) > _cents(lim["credit_cap"]):
            return _v("waiting", "credit_cap", "order_desk", f["amount"], lim["credit_cap"])
        return _v("done", "credit_cap", amount=f["amount"], limit=lim["credit_cap"])
    if tool == "reship":
        if f.get("order_status") not in ("shipped", "delivered"):
            return _v("blocked", "reship_not_shipped")
        if not f.get("within_order"):
            return _v("blocked", "reship_over_order")
        if _cents(f["value"]) > _cents(lim["reship_cap"]):
            return _v("waiting", "reship_cap", "order_desk", f["value"], lim["reship_cap"])
        return _v("done", "reship_cap", amount=f["value"], limit=lim["reship_cap"])
    if tool == "waive_fee":
        if not f.get("fee_found"):
            return _v("blocked", "fee_not_found")
        if _cents(f["amount"]) > _cents(lim["fee_waiver_cap"]):
            return _v("waiting", "fee_waiver_cap", "order_desk", f["amount"], lim["fee_waiver_cap"])
        return _v("done", "fee_waiver_cap", amount=f["amount"], limit=lim["fee_waiver_cap"])
    if tool == "create_order":
        if not f.get("stock_ok"):
            return _v("blocked", "not_enough_stock")
        if lim.get("orders_within_credit", True):
            if f.get("on_hold"):
                return _v("waiting", "account_hold", "credit", f["total"])
            if _cents(f["total"]) > _cents(f["available_credit"]):
                return _v("waiting", "credit_line", "credit", f["total"], f["available_credit"])
        if _cents(f["total"]) > _cents(lim["order_cap"]):
            return _v("waiting", "order_cap", "order_desk", f["total"], lim["order_cap"])
        return _v("done", "order_cap", amount=f["total"], limit=lim["order_cap"])
    if tool == "update_ship_to":
        if not f.get("location_found"):
            return _v("blocked", "ship_to_unknown")
        if f.get("order_status") == "open":
            return _v("done", "ship_to_before_pick")
        if f.get("order_status") == "picked":
            if lim.get("ship_to_before_pick", True):
                return _v("waiting", "ship_to_before_pick", "order_desk")
            return _v("done", "ship_to_before_pick")
        return _v("blocked", "ship_to_after_ship")
    if tool == "create_return":
        if not f.get("within_order"):
            return _v("blocked", "return_over_order")
        if f.get("days_since_delivery") is None or f["days_since_delivery"] > lim["return_days"]:
            return _v("blocked", "return_window", amount=f.get("days_since_delivery"), limit=lim["return_days"])
        if not f.get("unopened"):
            return _v("blocked", "return_opened")
        credit = return_credit(f["gross"], lim)[0]
        if _cents(credit) > _cents(lim["credit_cap"]):
            return _v("waiting", "credit_cap", "order_desk", credit, lim["credit_cap"])
        return _v("done", "credit_cap", amount=credit, limit=lim["credit_cap"])
    if tool == "hold_order":
        if f.get("order_status") in ("open", "picked"):
            return _v("done", "hold_before_ship")
        return _v("blocked", "hold_after_ship")
    return _v("blocked", "unknown_tool")


def lane(actions):
    """Where an email's card sits on the board, from its actions and their verdicts.

    actions: [{"tool": ..., "verdict": {...}, "team": ... (routes only)}], plus {"tool": "refuse"} when the email held an
    instruction the agent refused. A route to sales, credit or security, or a refusal, is never the agent's call. A route
    to the order desk or anything waiting needs the approver. A question to the customer waits on the customer.
    """
    if any(a["tool"] == "refuse" or (a["tool"] == "route_to_person" and a.get("team") in ("sales", "credit", "security"))
           for a in actions):
        return "stopped"
    if any(a.get("verdict", {}).get("verdict") == "waiting" or
           (a["tool"] == "route_to_person" and a.get("team") == "order_desk") for a in actions):
        return "needs_you"
    if any(a["tool"] == "ask_customer" for a in actions):
        return "customer"
    return "handled"
