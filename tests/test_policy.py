"""The limits as code: every cap at, under and over its line, the order rules in their order, the ship-to and return
rules, and the lane each mix of verdicts lands in. Phase 2 turns these into the parity vectors for site/policy.js."""
import unittest

from engine import policy

D = policy.defaults()


def v(tool, **facts):
    return policy.decide(tool, facts, D)["verdict"]


class Caps(unittest.TestCase):
    def test_the_defaults_are_the_spec(self):
        self.assertEqual((D["credit_cap"], D["reship_cap"], D["fee_waiver_cap"], D["order_cap"], D["return_days"],
                          D["restocking_pct"]), (250, 500, 75, 2500, 30, 15))

    def test_credit_at_under_and_over_the_cap(self):
        base = dict(invoice_found=True, invoice_open_to_credit=5000)
        self.assertEqual(v("issue_credit", amount=250.00, **base), "done")
        self.assertEqual(v("issue_credit", amount=249.99, **base), "done")
        self.assertEqual(v("issue_credit", amount=250.01, **base), "waiting")

    def test_a_credit_needs_its_invoice_and_room_on_it(self):
        self.assertEqual(v("issue_credit", amount=10, invoice_found=False, invoice_open_to_credit=0), "blocked")
        self.assertEqual(v("issue_credit", amount=600, invoice_found=True, invoice_open_to_credit=500), "blocked")
        self.assertEqual(v("issue_credit", amount=0, invoice_found=True, invoice_open_to_credit=500), "blocked")

    def test_reship_and_fee_waiver_caps(self):
        ok = dict(order_status="delivered", within_order=True)
        self.assertEqual(v("reship", value=500.00, **ok), "done")
        self.assertEqual(v("reship", value=500.01, **ok), "waiting")
        self.assertEqual(v("reship", value=10, order_status="open", within_order=True), "blocked")
        self.assertEqual(v("reship", value=10, order_status="delivered", within_order=False), "blocked")
        self.assertEqual(v("waive_fee", amount=75.00, fee_found=True), "done")
        self.assertEqual(v("waive_fee", amount=95.00, fee_found=True), "waiting")
        self.assertEqual(v("waive_fee", amount=5.00, fee_found=False), "blocked")

    def test_moving_a_limit_changes_the_verdict(self):
        lowered = dict(D, credit_cap=100)
        f = dict(amount=168.00, invoice_found=True, invoice_open_to_credit=1924.00)
        self.assertEqual(policy.decide("issue_credit", f, D)["verdict"], "done")
        self.assertEqual(policy.decide("issue_credit", f, lowered)["verdict"], "waiting")


class Orders(unittest.TestCase):
    def test_stock_then_hold_then_credit_line_then_the_order_cap(self):
        ok = dict(stock_ok=True, on_hold=False, available_credit=3000.00)
        self.assertEqual(v("create_order", total=1284.00, **ok), "done")
        self.assertEqual(v("create_order", total=1284.00, **dict(ok, stock_ok=False)), "blocked")
        self.assertEqual(policy.decide("create_order", dict(ok, total=100, on_hold=True), D)["rule"], "account_hold")
        r = policy.decide("create_order", dict(ok, total=3000.01), D)
        self.assertEqual((r["verdict"], r["rule"], r["approver"]), ("waiting", "credit_line", "credit"))
        r = policy.decide("create_order", dict(ok, total=2712.00, available_credit=17652.00), D)
        self.assertEqual((r["verdict"], r["rule"], r["approver"]), ("waiting", "order_cap", "order_desk"))
        self.assertEqual(v("create_order", total=2500.00, **dict(ok, available_credit=9000)), "done")

    def test_ship_to_by_how_far_the_order_has_gone(self):
        self.assertEqual(v("update_ship_to", order_status="open", location_found=True), "done")
        self.assertEqual(v("update_ship_to", order_status="picked", location_found=True), "waiting")
        self.assertEqual(v("update_ship_to", order_status="shipped", location_found=True), "blocked")
        self.assertEqual(v("update_ship_to", order_status="open", location_found=False), "blocked")

    def test_returns_window_then_opened_then_the_credit_cap(self):
        ok = dict(within_order=True, unopened=True, days_since_delivery=12, gross=216.00)
        self.assertEqual(v("create_return", **ok), "done")
        self.assertEqual(v("create_return", **dict(ok, days_since_delivery=30)), "done")
        self.assertEqual(v("create_return", **dict(ok, days_since_delivery=31)), "blocked")
        self.assertEqual(v("create_return", **dict(ok, unopened=False)), "blocked")
        self.assertEqual(v("create_return", **dict(ok, gross=580.00)), "waiting")

    def test_holds_routes_and_questions(self):
        self.assertEqual(v("hold_order", order_status="picked"), "done")
        self.assertEqual(v("hold_order", order_status="shipped"), "blocked")
        self.assertEqual(v("route_to_person", team="security"), "done")
        self.assertEqual(v("route_to_person", team="legal"), "blocked")
        self.assertEqual(v("ask_customer"), "done")


class Lanes(unittest.TestCase):
    def test_each_lane(self):
        done = {"verdict": "done"}
        self.assertEqual(policy.lane([]), "handled")
        self.assertEqual(policy.lane([{"tool": "issue_credit", "verdict": done}]), "handled")
        self.assertEqual(policy.lane([{"tool": "create_order", "verdict": done},
                                      {"tool": "waive_fee", "verdict": {"verdict": "waiting"}}]), "needs_you")
        self.assertEqual(policy.lane([{"tool": "route_to_person", "team": "order_desk", "verdict": done}]), "needs_you")
        self.assertEqual(policy.lane([{"tool": "ask_customer", "verdict": done}]), "customer")
        self.assertEqual(policy.lane([{"tool": "route_to_person", "team": "security", "verdict": done}]), "stopped")
        self.assertEqual(policy.lane([{"tool": "refuse"}]), "stopped")


if __name__ == "__main__":
    unittest.main()
