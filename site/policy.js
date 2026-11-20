/* The limits in the browser: the same rules as engine/policy.py, line for line, so moving a limit on the page
   recomputes every verdict exactly as the scores were computed. tests/vectors/policy.json holds the cases both must
   agree on, and tests/js/check_policy.js runs them. No network, no dependencies. */
(function (root) {
  "use strict";

  const TEAMS = ["order_desk", "sales", "credit", "security"];
  const cents = (x) => Math.round(Number(x) * 100);
  const has = (o, k) => o[k] !== undefined && o[k] !== null;
  const getOr = (o, k, d) => (o[k] === undefined ? d : o[k]);

  function returnCredit(gross, limits) {
    const g = cents(gross);
    const fee = Math.floor((g * Math.trunc(limits.restocking_pct) + 50) / 100);
    return [(g - fee) / 100, fee / 100];
  }

  function v(verdict, rule, approver, amount, limit) {
    return {verdict, rule, approver: approver === undefined ? null : approver,
      amount: amount === undefined ? null : amount, limit: limit === undefined ? null : limit};
  }

  function decide(tool, f, lim) {
    if (tool === "ask_customer") return v("done", "always");
    if (tool === "route_to_person") return TEAMS.includes(f.team) ? v("done", "always") : v("blocked", "unknown_team");
    if (tool === "issue_credit") {
      if (!f.invoice_found) return v("blocked", "credit_needs_invoice");
      if (cents(f.amount) <= 0 || cents(f.amount) > cents(f.invoice_open_to_credit)) {
        return v("blocked", "credit_over_invoice", null, f.amount, f.invoice_open_to_credit);
      }
      if (cents(f.amount) > cents(lim.credit_cap)) return v("waiting", "credit_cap", "order_desk", f.amount, lim.credit_cap);
      return v("done", "credit_cap", null, f.amount, lim.credit_cap);
    }
    if (tool === "reship") {
      if (!["shipped", "delivered"].includes(f.order_status)) return v("blocked", "reship_not_shipped");
      if (!f.within_order) return v("blocked", "reship_over_order");
      if (cents(f.value) > cents(lim.reship_cap)) return v("waiting", "reship_cap", "order_desk", f.value, lim.reship_cap);
      return v("done", "reship_cap", null, f.value, lim.reship_cap);
    }
    if (tool === "waive_fee") {
      if (!f.fee_found) return v("blocked", "fee_not_found");
      if (cents(f.amount) > cents(lim.fee_waiver_cap)) {
        return v("waiting", "fee_waiver_cap", "order_desk", f.amount, lim.fee_waiver_cap);
      }
      return v("done", "fee_waiver_cap", null, f.amount, lim.fee_waiver_cap);
    }
    if (tool === "create_order") {
      if (!f.stock_ok) return v("blocked", "not_enough_stock");
      if (getOr(lim, "orders_within_credit", true)) {
        if (f.on_hold) return v("waiting", "account_hold", "credit", f.total);
        if (cents(f.total) > cents(f.available_credit)) {
          return v("waiting", "credit_line", "credit", f.total, f.available_credit);
        }
      }
      if (cents(f.total) > cents(lim.order_cap)) return v("waiting", "order_cap", "order_desk", f.total, lim.order_cap);
      return v("done", "order_cap", null, f.total, lim.order_cap);
    }
    if (tool === "update_ship_to") {
      if (!f.location_found) return v("blocked", "ship_to_unknown");
      if (f.order_status === "open") return v("done", "ship_to_before_pick");
      if (f.order_status === "picked") {
        if (getOr(lim, "ship_to_before_pick", true)) return v("waiting", "ship_to_before_pick", "order_desk");
        return v("done", "ship_to_before_pick");
      }
      return v("blocked", "ship_to_after_ship");
    }
    if (tool === "create_return") {
      if (!f.within_order) return v("blocked", "return_over_order");
      if (!has(f, "days_since_delivery") || f.days_since_delivery > lim.return_days) {
        return v("blocked", "return_window", null, has(f, "days_since_delivery") ? f.days_since_delivery : null,
          lim.return_days);
      }
      if (!f.unopened) return v("blocked", "return_opened");
      const credit = returnCredit(f.gross, lim)[0];
      if (cents(credit) > cents(lim.credit_cap)) return v("waiting", "credit_cap", "order_desk", credit, lim.credit_cap);
      return v("done", "credit_cap", null, credit, lim.credit_cap);
    }
    if (tool === "hold_order") {
      return ["open", "picked"].includes(f.order_status) ? v("done", "hold_before_ship") : v("blocked", "hold_after_ship");
    }
    return v("blocked", "unknown_tool");
  }

  function lane(actions) {
    const verdict = (a) => (a.verdict || {}).verdict;
    if (actions.some((a) => a.tool === "refuse" ||
        (a.tool === "route_to_person" && ["sales", "credit", "security"].includes(a.team)))) return "stopped";
    if (actions.some((a) => verdict(a) === "waiting" || (a.tool === "route_to_person" && a.team === "order_desk"))) {
      return "needs_you";
    }
    if (actions.some((a) => a.tool === "ask_customer")) return "customer";
    return "handled";
  }

  const api = {decide, lane, returnCredit, TEAMS};
  root.IAPolicy = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
