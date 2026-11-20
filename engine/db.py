"""The synthetic database the tools read, loaded fresh from data/fixtures/ so no run ever touches another.

Lookups by id, plus the account math every part of the build shares: an invoice's open amount, a customer's open
balance and open credit, payment history, stock by warehouse and equivalent items. The validator uses it now, and the
tools in Phase 2 wrap it. Standard library only.
"""
import copy
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FIXTURES = HERE.joinpath("data", "fixtures")
NAMES = ("meta", "items", "customers", "inventory", "orders", "shipments", "invoices", "payments")
_CACHE = {}


def money(x):
    return round(float(x) + 1e-9, 2)


def load(path=None):
    """A fresh, private copy of every fixture, so a run can change its copy freely."""
    key = str(path or FIXTURES)
    if key not in _CACHE:
        base = Path(path or FIXTURES)
        _CACHE[key] = {n: json.loads(base.joinpath(f"{n}.json").read_text(encoding="utf-8")) for n in NAMES}
    return World(copy.deepcopy(_CACHE[key]))


class World:
    def __init__(self, raw):
        self.raw = raw
        self.meta = raw["meta"]
        self.today = date.fromisoformat(self.meta["today"])
        self.items = {i["sku"]: i for i in raw["items"]}
        self.customers = {c["id"]: c for c in raw["customers"]}
        self.orders = {o["id"]: o for o in raw["orders"]}
        self.invoices = {i["id"]: i for i in raw["invoices"]}
        self.inventory = raw["inventory"]
        self.shipments = {}
        for s in raw["shipments"]:
            self.shipments.setdefault(s["order_id"], []).append(s)
        self.paid = {}
        for p in raw["payments"]:
            self.paid[p["invoice_id"]] = money(self.paid.get(p["invoice_id"], 0) + p["amount"])
        self.credits = {}
        self.returns = []

    # --- people and accounts ---
    def customer_by_email(self, email):
        email = (email or "").lower()
        for c in self.customers.values():
            if any(x["email"].lower() == email for x in c["contacts"]):
                return c
        return None

    def location(self, customer_id, location_id):
        return next((x for x in self.customers[customer_id]["locations"] if x["id"] == location_id), None)

    def price(self, customer_id, sku):
        return self.customers[customer_id]["contract_prices"].get(sku, self.items[sku]["list_price"])

    def invoice_open(self, invoice_id):
        inv = self.invoices[invoice_id]
        return money(inv["total"] - self.paid.get(invoice_id, 0) - self.credits.get(invoice_id, 0))

    def open_to_credit(self, invoice_id):
        """How much of an invoice can still be credited: its total less any credits already issued on it."""
        return money(self.invoices[invoice_id]["total"] - self.credits.get(invoice_id, 0))

    def open_invoices(self, customer_id):
        return [i for i in self.invoices.values() if i["customer_id"] == customer_id and self.invoice_open(i["id"]) > 0]

    def open_balance(self, customer_id):
        return money(sum(self.invoice_open(i["id"]) for i in self.open_invoices(customer_id)))

    def order_value(self, order):
        return money(sum(x["qty"] * x["price"] for x in order["lines"]) + sum(f["amount"] for f in order["fees"]))

    def open_orders_value(self, customer_id):
        return money(sum(self.order_value(o) for o in self.orders.values()
                         if o["customer_id"] == customer_id and o["status"] in ("open", "picked")))

    def available_credit(self, customer_id):
        c = self.customers[customer_id]
        return money(c["credit_limit"] - self.open_balance(customer_id) - self.open_orders_value(customer_id))

    def past_due(self, customer_id):
        return [i for i in self.open_invoices(customer_id) if date.fromisoformat(i["due"]) < self.today]

    def payment_history(self, customer_id):
        paid = [i for i in self.invoices.values() if i["customer_id"] == customer_id and i["id"] in self.paid]
        last = {}
        for p in self.raw["payments"]:
            last[p["invoice_id"]] = max(last.get(p["invoice_id"], p["date"]), p["date"])
        on_time = [i for i in paid if last[i["id"]] <= i["due"]]
        return {"invoices_paid": len(paid), "paid_on_time": len(on_time)}

    # --- orders, shipments, stock ---
    def find_orders(self, customer_id=None, po=None, status=None, placed_from=None, placed_to=None, sku=None):
        out = []
        for o in self.orders.values():
            if customer_id and o["customer_id"] != customer_id:
                continue
            if po and o["po"].lower() != str(po).lower():
                continue
            if status and o["status"] != status:
                continue
            if placed_from and o["placed"][:10] < placed_from:
                continue
            if placed_to and o["placed"][:10] > placed_to:
                continue
            if sku and not any(x["sku"] == sku for x in o["lines"]):
                continue
            out.append(o)
        return sorted(out, key=lambda o: o["placed"])

    def shipment(self, order_id):
        found = self.shipments.get(order_id) or []
        return found[-1] if found else None

    def delivered_on(self, order_id):
        s = self.shipment(order_id)
        return date.fromisoformat(s["delivered"][:10]) if s and s.get("delivered") else None

    def stock(self, sku):
        out = {}
        for wh, v in self.inventory[sku].items():
            out[wh] = {"available": max(0, v["on_hand"] - v["held"]), "on_hand": v["on_hand"], "held": v["held"],
                       "inbound": v["inbound"]}
        return out

    def available(self, sku):
        return sum(v["available"] for v in self.stock(sku).values())

    def equivalents(self, sku):
        group = self.items[sku].get("equivalent_group")
        if not group:
            return []
        return [i for i in self.items.values() if i["equivalent_group"] == group and i["sku"] != sku]

    def allocate(self, sku, qty):
        """Split a quantity across warehouses, the one with the most available first. None when stock falls short."""
        stock = sorted(self.stock(sku).items(), key=lambda kv: (-kv[1]["available"], kv[0]))
        left, plan = qty, []
        for wh, v in stock:
            take = min(left, v["available"])
            if take > 0:
                plan.append({"warehouse": wh, "qty": take})
                left -= take
        return plan if left == 0 else None
