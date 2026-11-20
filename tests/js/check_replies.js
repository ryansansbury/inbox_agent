/* Run site/replies.js on tests/vectors/replies.json and compare with what engine/replies.py found.

     node tests/js/check_replies.js

   Prints each disagreement and exits 1 if there is any. */
"use strict";
const fs = require("fs");
const path = require("path");
const here = path.resolve(__dirname, "..", "..");
const R = require(path.join(here, "site", "replies.js"));
const v = JSON.parse(fs.readFileSync(path.join(here, "tests", "vectors", "replies.json"), "utf8"));

function canon(x) {
  if (Array.isArray(x)) return x.map(canon);
  if (x && typeof x === "object") {
    const out = {};
    for (const k of Object.keys(x).sort()) out[k] = canon(x[k]);
    return out;
  }
  return x;
}

const checker = R.make(v.lexicon);
let bad = 0;
let claims = 0;
for (const c of v.cases) {
  const got = checker.check(c.reply, v.tables[c.table]);
  claims += c.want.length;
  if (JSON.stringify(canon(got)) !== JSON.stringify(canon(c.want))) {
    bad += 1;
    if (bad <= 5) {
      console.log("MISMATCH", c.table, JSON.stringify(c.reply).slice(0, 160));
      const n = Math.max(got.length, c.want.length);
      for (let i = 0; i < n; i++) {
        const a = JSON.stringify(canon(c.want[i] || null));
        const b = JSON.stringify(canon(got[i] || null));
        if (a !== b) console.log("  python", a, "\n  js    ", b);
      }
    }
  }
}
console.log(`${v.cases.length - bad} of ${v.cases.length} reply vectors agree (${claims} claims)`);
process.exit(bad ? 1 : 0);
