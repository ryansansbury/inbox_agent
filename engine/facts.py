"""The numbers the policy needs for an action, worked out from the records.

    facts_for(world, tool, args, customer_id, limits, created=None) -> facts

Each action's facts hold what the rules compare (an amount, the open credit, how far the order has gone) and what the
action would produce (a credit after the restocking fee, a new order's total and its split across warehouses). The
validator uses this to compute every verdict in the key, and the tools use it in Phase 2, so both always agree.
"created" carries an order made earlier in the same email, which a later action can name as "$new_order".
"""
from engine.db import money
from engine.policy import return_credit


def _order(world, order_id, created):
    if order_id == "$new_order":
        return created
    return world.orders.get(order_id)


def _lines_within(order, lines):
    by_sku = {}
    for x in order["lines"]:
        by_sku[x["sku"]] = by_sku.get(x["sku"], 0) + x["qty"]
    return all(l["sku"] in by_sku and 0 < l["qty"] <= by_sku[l["sku"]] for l in lines)


def _line_price(order, sku):
    return next(x["price"] for x in order["lines"] if x["sku"] == sku)


def facts_for(world, tool, args, customer_id, limits, created=None):
    if tool == "ask_customer":
        return {}
    if tool == "route_to_person":
        return {"team": args.get("team")}
    if tool == "issue_credit":
        inv = world.invoices.get(args.get("invoice_id"))
        found = bool(inv) and inv["customer_id"] == customer_id
        return {"invoice_found": found, "amount": money(args.get("amount", 0)),
                "invoice_open_to_credit": world.open_to_credit(inv["id"]) if found else 0}
    order = _order(world, args.get("order_id"), created)
    mine = bool(order) and order["customer_id"] == customer_id
    if tool == "reship":
        ok = mine and _lines_within(order, args["lines"])
        value = money(sum(l["qty"] * _line_price(order, l["sku"]) for l in args["lines"])) if ok else 0
        return {"order_status": order["status"] if mine else None, "within_order": ok, "value": value}
    if tool == "waive_fee":
        target = order
        if args.get("invoice_id"):
            inv = world.invoices.get(args["invoice_id"])
            target = inv if inv and inv["customer_id"] == customer_id else None
        fee = next((f for f in (target or {}).get("fees", []) if f["type"] == args.get("fee")), None)
        return {"fee_found": bool(fee), "amount": money(fee["amount"]) if fee else money(args.get("amount", 0))}
    if tool == "create_order":
        c = world.customers[customer_id]
        plans = {l["sku"]: world.allocate(l["sku"], l["qty"]) for l in args["lines"]}
        total = money(sum(l["qty"] * world.price(customer_id, l["sku"]) for l in args["lines"]))
        fees = [{"type": "rush", "amount": world.meta["fees"]["rush"]}] if args.get("rush") else []
        return {"total": total, "available_credit": world.available_credit(customer_id), "on_hold": c["on_hold"],
                "stock_ok": all(p is not None for p in plans.values()), "allocation": plans, "fees": fees}
    if tool == "update_ship_to":
        found = mine and world.location(customer_id, args.get("location_id")) is not None
        return {"order_status": order["status"] if mine else None, "location_found": found}
    if tool == "create_return":
        ok = mine and _lines_within(order, args["lines"])
        delivered = world.delivered_on(order["id"]) if mine else None
        gross = money(sum(l["qty"] * _line_price(order, l["sku"]) for l in args["lines"])) if ok else 0
        credit, fee = return_credit(gross, limits)
        return {"within_order": ok, "unopened": bool(args.get("unopened")),
                "days_since_delivery": (world.today - delivered).days if delivered else None,
                "gross": gross, "restocking_fee": fee, "credit": credit}
    if tool == "hold_order":
        return {"order_status": order["status"] if mine else None}
    return {}


def new_order(world, customer_id, args, facts, order_id):
    """The order a create_order makes, so a later action in the same email can point at it."""
    lines = [{"sku": l["sku"], "qty": l["qty"], "price": world.price(customer_id, l["sku"]), "picked": 0, "shipped": 0}
             for l in args["lines"]]
    return {"id": order_id, "customer_id": customer_id, "po": args.get("po"), "status": "open", "lines": lines,
            "fees": [dict(f) for f in facts["fees"]], "ship_to": args.get("location_id", "L1")}
