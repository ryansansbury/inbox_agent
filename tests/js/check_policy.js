/* Run site/policy.js on tests/vectors/policy.json and compare with what engine/policy.py decided.

     node tests/js/check_policy.js

   Prints each disagreement and exits 1 if there is any. */
"use strict";
const fs = require("fs");
const path = require("path");
const here = path.resolve(__dirname, "..", "..");
const P = require(path.join(here, "site", "policy.js"));
const v = JSON.parse(fs.readFileSync(path.join(here, "tests", "vectors", "policy.json"), "utf8"));

function canon(x) {
  if (Array.isArray(x)) return x.map(canon);
  if (x && typeof x === "object") {
    const out = {};
    for (const k of Object.keys(x).sort()) out[k] = canon(x[k]);
    return out;
  }
  return x;
}
const same = (a, b) => JSON.stringify(canon(a)) === JSON.stringify(canon(b));

let bad = 0;
for (const c of v.decisions) {
  const got = P.decide(c.tool, c.facts, c.limits);
  if (!same(got, c.want)) {
    bad += 1;
    if (bad <= 10) console.log("DECIDE", c.tool, JSON.stringify(c.facts), "\n  python", JSON.stringify(c.want), "\n  js    ", JSON.stringify(got));
  }
}
for (const c of v.return_credits) {
  const got = P.returnCredit(c.gross, {restocking_pct: c.pct});
  if (!same(got, c.want)) {
    bad += 1;
    console.log("RETURN CREDIT", c.gross, c.pct, "python", JSON.stringify(c.want), "js", JSON.stringify(got));
  }
}
for (const c of v.lanes) {
  const got = P.lane(c.actions);
  if (got !== c.want) {
    bad += 1;
    console.log("LANE", JSON.stringify(c.actions), "python", c.want, "js", got);
  }
}
const n = v.decisions.length + v.return_credits.length + v.lanes.length;
console.log(`${n - bad} of ${n} policy vectors agree`);
process.exit(bad ? 1 : 0);
