"""The tools over a fresh copy of the records: reads return records, actions go through the policy, only a done
changes anything, every run is isolated, look-alike senders can't move anything, and approvals land in the audit log."""
import unittest

from engine.tools import Store
from generate import validate

SPECS = {s["id"]: s for s in validate.load_specs()}


def store(eid, seq=0):
    return Store(SPECS[eid], seq=seq)


class Reads(unittest.TestCase):
    def test_customer_by_sender_and_its_money(self):
        c = store("m05").run("get_customer", {"email": "clara@tallowandteak.example"})
        self.assertEqual((c["customer_id"], c["available_credit"], c["open_balance"]), ("C-1003", 2843.00, 1820.00))
        self.assertEqual(c["payment_history"], {"invoices_paid": 12, "paid_on_time": 12})

    def test_unknown_sender_and_unknown_records(self):
        s = store("m10")
        self.assertIn("error", s.run("get_customer", {"email": "bea.lockhart@pellbrook-payables.example"}))
        self.assertIn("error", s.run("get_order", {"order_id": "SO-99999"}))
        self.assertIn("error", s.run("get_shipment", {"order_id": "SO-20817"}))
        self.assertIn("error", s.run("no_such_tool", {}))

    def test_shipments_stock_prices_and_equivalents(self):
        s = store("m01")
        sh = s.run("get_shipment", {"order_id": "SO-20812"})
        self.assertEqual((sh["tracking"], sh["status"], sh["eta"]), ("PRO 5521-8804", "out_for_delivery",
                                                                     "2026-10-27 14:00"))
        st = s.run("check_stock", {"sku": "BX-141414-32"})
        self.assertEqual(st["available_total"], 0)
        self.assertEqual(st["warehouses"]["North"]["inbound"], [{"qty": 60, "date": "2026-11-10"}])
        eq = s.run("find_equivalents", {"sku": "BX-141414-32"})["equivalents"]
        self.assertEqual([(e["sku"], e["available"]) for e in eq], [("BX-141414-32E", 45)])
        p = s.run("get_price", {"customer_id": "C-1008", "sku": "BX-161210-32"})
        self.assertEqual((p["list_price"], p["contract_price"], p["price"]), (27.06, 22.40, 22.40))

    def test_find_orders_shows_the_latest_twenty(self):
        s = store("m03")
        everything = s.w.find_orders("C-1002")
        out = s.run("find_orders", {"customer_id": "C-1002"})
        self.assertEqual(len(out["orders"]), min(20, len(everything)))
        self.assertEqual(out.get("older_not_shown", 0), max(0, len(everything) - 20))
        self.assertEqual(out["orders"][-1]["order_id"], everything[-1]["id"])
        week = store("m12").run("find_orders", {"customer_id": "C-1004", "placed_from": "2026-10-26",
                                                 "status": "open"})
        self.assertEqual([o["order_id"] for o in week["orders"]], ["SO-20832", "SO-20835"])


class Actions(unittest.TestCase):
    def test_done_changes_the_copy_and_says_so(self):
        s = store("m02", seq=1)
        out = s.run("issue_credit", {"customer_id": "C-1001", "invoice_id": "INV-30941", "amount": 168.0,
                                     "sentence": 4})
        self.assertEqual((out["result"], out["credit_memo"], out["invoice_open_after"]), ("done", "CM-2234", 1756.0))
        inv = s.run("get_invoice", {"invoice_id": "INV-30941"})
        self.assertEqual(inv["credits"], [{"credit_memo": "CM-2234", "amount": 168.0}])

    def test_waiting_changes_nothing_and_opens_a_card(self):
        s = store("d07")
        out = s.run("issue_credit", {"customer_id": "C-1002", "invoice_id": "INV-30917", "amount": 312.0,
                                     "sentence": 3})
        self.assertEqual((out["result"], out["waiting_on"], out["limit"]), ("waiting", "order_desk", 250))
        self.assertEqual(s.run("get_invoice", {"invoice_id": "INV-30917"})["credits"], [])
        self.assertEqual(len(s.approvals), 1)

    def test_blocked_changes_nothing(self):
        s = store("t04")
        out = s.run("update_ship_to", {"order_id": "SO-20820", "location_id": "L2", "sentence": 1})
        self.assertEqual((out["result"], out["rule"]), ("blocked", "ship_to_after_ship"))
        self.assertEqual(s.run("get_order", {"order_id": "SO-20820"})["ship_to"]["location_id"], "L1")

    def test_a_look_alike_sender_moves_nothing(self):
        s = store("m10")
        out = s.run("issue_credit", {"customer_id": "C-1001", "invoice_id": "INV-30941", "amount": 50, "sentence": 3})
        self.assertEqual(out["rule"], "other_account")
        out = s.run("hold_order", {"order_id": "SO-20828", "sentence": 3})
        self.assertEqual(out["result"], "blocked")

    def test_an_order_then_a_fee_on_it(self):
        s = store("m05", seq=4)
        o = s.run("create_order", {"customer_id": "C-1003", "lines": [{"sku": "BX-121006-32", "qty": 60}],
                                   "rush": True, "sentence": 2})
        self.assertEqual((o["order_id"], o["total"]), ("SO-20852", 1284.0))
        self.assertEqual(o["allocation"], {"BX-121006-32": [{"warehouse": "North", "qty": 40},
                                                            {"warehouse": "Valley", "qty": 20}]})
        w = s.run("waive_fee", {"order_id": o["order_id"], "fee": "rush", "sentence": 3})
        self.assertEqual((w["result"], w["amount"]), ("waiting", 95.0))

    def test_runs_never_touch_each_other(self):
        a, b = store("m02", seq=1), store("m02", seq=1)
        a.run("issue_credit", {"customer_id": "C-1001", "invoice_id": "INV-30941", "amount": 168.0, "sentence": 4})
        self.assertEqual(b.run("get_invoice", {"invoice_id": "INV-30941"})["open"], 1924.0)

    def test_each_email_has_its_own_ids(self):
        ids = set()
        for seq in range(48):
            s = Store(SPECS["m02"], seq=seq)
            ids.add(s.run("issue_credit", {"customer_id": "C-1001", "invoice_id": "INV-30941", "amount": 10,
                                           "sentence": 4})["credit_memo"])
        self.assertEqual(len(ids), 48)


class Approvals(unittest.TestCase):
    def test_approve_applies_and_logs_the_approver(self):
        s = store("d07")
        out = s.run("issue_credit", {"customer_id": "C-1002", "invoice_id": "INV-30917", "amount": 312.0,
                                     "sentence": 3})
        card = s.resolve(out["approval_id"], True)
        self.assertEqual(card["status"], "approved")
        self.assertEqual(s.run("get_invoice", {"invoice_id": "INV-30917"})["credits"][0]["amount"], 312.0)
        self.assertEqual([(e["actor"], e["result"]) for e in s.audit],
                         [("agent", "proposed"), ("rules", "waiting"), ("approver", "approved")])

    def test_deny_changes_nothing_and_a_held_order_is_cancelled(self):
        s = store("m09")
        out = s.run("create_order", {"customer_id": "C-1009", "lines": [{"sku": "BX-121212-44", "qty": 40},
                                                                        {"sku": "VF-KP-30", "qty": 10}], "sentence": 3})
        self.assertEqual((out["result"], out["waiting_on"]), ("waiting", "credit"))
        self.assertEqual(s.run("get_order", {"order_id": out["order_id"]})["status"], "pending_approval")
        s.resolve(out["approval_id"], False)
        self.assertEqual(s.run("get_order", {"order_id": out["order_id"]})["status"], "cancelled")
        self.assertEqual(s.audit[-1]["actor"], "approver")


if __name__ == "__main__":
    unittest.main()


class SearchAndIds(unittest.TestCase):
    def test_every_description_in_the_emails_finds_its_item_first(self):
        s = store("d09")
        for query, sku in [("18x12x12 boxes", "BX-181212-32"), ("12 inch foam", "VF-FOAM-12"),
                           ("heavy 12x12x12", "BX-121212-44"), ("30 inch kraft paper", "VF-KP-30"),
                           ("fragile tape", "TP-FRG-2"), ("fragile labels", "LB-FRG"), ("packing peanuts", "VF-PEA-14"),
                           ("9x6x3 mailer boxes", "MB-090603"), ("9x11.5 rigid mailers", "RM-0911"),
                           ("heavy 24x18x12", "BX-241812-44"), ("14x10x6 boxes", "BX-141006-32"),
                           ("6x6x6 boxes", "BX-060606-32"), ("12x10x6 boxes", "BX-121006-32"),
                           ("18 inch 80 gauge film", "SF-18-80"), ("3 inch clear tape", "TP-3C-110"),
                           ("recycled 14x14x14", "BX-141414-32E"), ("8.5x12 padded mailers", "PD-0812")]:
            self.assertEqual(s.run("search_items", {"query": query})["matches"][0]["sku"], sku, query)
        self.assertEqual(s.run("search_items", {"query": "unicorn glitter"})["matches"], [])
        self.assertEqual(s.run("search_items", {"query": "16x12x10", "customer_id": "C-1008"})["matches"][0]["price"],
                         22.40)

    def test_bare_numbers_reach_the_record(self):
        from engine.tools import normalize
        self.assertEqual(normalize({"invoice_id": "30927", "order_id": "so 20812", "customer_id": "1006"}),
                         {"invoice_id": "INV-30927", "order_id": "SO-20812", "customer_id": "C-1006"})
        s = store("t05")
        self.assertEqual(s.run("get_invoice", {"invoice_id": "30927"})["invoice_id"], "INV-30927")
        out = s.run("waive_fee", {"invoice_id": "inv 30927", "fee": "liftgate", "sentence": 3})
        self.assertEqual(out["result"], "done")
