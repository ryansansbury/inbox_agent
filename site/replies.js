/* The reply checker in the browser: the same checks as engine/replies.py, run on the same evidence table.

   The build writes each run's table (everything the agent saw, and its actions with their verdicts) and the checker's
   patterns into data.js, so both versions compile the very same regular expressions. This file reads the values and
   judges every claim and promise when a visitor edits a reply. tests/vectors/replies.json holds the cases both must
   agree on, and tests/js/check_replies.js runs them. No network, no dependencies. */
(function (root) {
  "use strict";

  function make(L) {
    const compiled = L.patterns.map(([kind, how, src]) => [kind, how, new RegExp(src, "gi")]);
    const promises = L.promises.map(([kind, srcs, tools]) => [kind, srcs.map((s) => new RegExp(s, "i")), tools]);
    const negation = new RegExp(L.negation, "i");
    const pending = new RegExp(L.pending, "i");
    const conditional = new RegExp(L.conditional, "i");
    const listMarker = new RegExp(L.list_marker, "gm");
    const sentenceEnd = new RegExp(L.sentence_end, "g");
    const pad2 = (n) => String(n).padStart(2, "0");

    function parseIso(s) {
      const [y, m, d] = s.split("-").map(Number);
      return new Date(Date.UTC(y, m - 1, d));
    }
    function iso(d) {
      return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
    }
    function addDays(d, n) {
      return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + n));
    }
    const weekday = (d) => (d.getUTCDay() + 6) % 7;
    function exactDate(y, m, d) {
      if (!m) return null;
      const out = new Date(Date.UTC(y, m - 1, d));
      return out.getUTCFullYear() === y && out.getUTCMonth() === m - 1 && out.getUTCDate() === d ? out : null;
    }
    function month(word) {
      const w = word.toLowerCase();
      const i = L.months.indexOf(w);
      return i >= 0 ? i + 1 : (L.abbr[w] || null);
    }
    function weekdayDate(today, which, name) {
      const target = L.days.indexOf(name.toLowerCase());
      if (which && which.toLowerCase() === "next") return addDays(today, 7 - weekday(today) + target);
      return addDays(today, (((target - weekday(today)) % 7) + 7) % 7 || 7);
    }
    function trim(x) {
      return String(parseFloat(x));
    }
    function num(text) {
      const t = text.toLowerCase();
      return t in L.small ? L.small[t] : parseFloat(t);
    }

    function value(how, kind, whole, g, today) {
      switch (how) {
        case "tracking": return {value: `PRO ${g[0]}-${g[1]}`};
        case "id": return {value: L.id_prefix[kind] + g[0]};
        case "upper": return {value: whole.toUpperCase()};
        case "po": return {value: g[0].toUpperCase()};
        case "weekday_month": {
          const d = exactDate(today.getUTCFullYear(), month(g[1]), parseInt(g[2], 10));
          const out = {value: d ? iso(d) : null};
          if (d && L.days[weekday(d)] !== g[0].toLowerCase()) out.weekday_mismatch = true;
          return out;
        }
        case "month_day": {
          const d = exactDate(today.getUTCFullYear(), month(g[0]), parseInt(g[1], 10));
          return {value: d ? iso(d) : null};
        }
        case "iso": {
          const d = exactDate(parseInt(g[0], 10), parseInt(g[1], 10), parseInt(g[2], 10));
          return {value: d ? iso(d) : null};
        }
        case "numeric": {
          const m = parseInt(g[0], 10);
          const d = m >= 1 && m <= 12 ? exactDate(today.getUTCFullYear(), m, parseInt(g[1], 10)) : null;
          return {value: d ? iso(d) : null};
        }
        case "relative":
          return {value: iso(addDays(today, {today: 0, tomorrow: 1, yesterday: -1}[g[0].toLowerCase()]))};
        case "weekday": return {value: iso(weekdayDate(today, g[0], g[1]))};
        case "clock": {
          const h = (parseInt(g[0], 10) % 12) + (g[2].toLowerCase() === "p" ? 12 : 0);
          return {value: `${pad2(h)}:${pad2(parseInt(g[1] || "0", 10))}`};
        }
        case "noon": return {value: "12:00"};
        case "money":
          return {value: parseInt(g[0].replace(/,/g, ""), 10) * 100 + parseInt((g[1] || "0").padEnd(2, "0"), 10)};
        case "float": return {value: parseFloat(g[0])};
        case "size": return {value: g.filter((x) => x).map(trim).join("x")};
        case "measure": return {value: trim(g[0]) + L.measure_units[g[1].toLowerCase()]};
        case "count": return {value: num(g[0])};
        default: return {value: parseFloat(whole.replace(/,/g, ""))};
      }
    }

    function extract(text, todayIso) {
      const today = parseIso(todayIso);
      listMarker.lastIndex = 0;
      const taken = [...text.matchAll(listMarker)].map((m) => [m.index, m.index + m[0].length]);
      const out = [];
      for (const [kind, how, rx] of compiled) {
        rx.lastIndex = 0;
        for (const m of text.matchAll(rx)) {
          const s = m.index;
          const e = s + m[0].length;
          if (taken.some(([a, b]) => s < b && a < e)) continue;
          const claim = Object.assign({kind, text: m[0], start: s, end: e},
            value(how, kind, m[0], m.slice(1).map((x) => (x === undefined ? null : x)), today));
          taken.push([s, e]);
          out.push(claim);
        }
      }
      return out.sort((a, b) => a.start - b.start);
    }

    function sentences(text) {
      const out = [];
      let start = 0;
      sentenceEnd.lastIndex = 0;
      for (const m of text.matchAll(sentenceEnd)) {
        const end = m.index + m[0].length;
        if (text.slice(start, end).trim()) out.push([start, end]);
        start = end;
      }
      if (text.slice(start).trim()) out.push([start, text.length]);
      return out;
    }

    const VERBS = {credit: "issue a credit", reship: "reship anything", order: "place an order", waive: "waive a fee",
      ship_to: "change a ship-to", return: "open a return", hold: "hold an order"};

    function check(reply, t) {
      const ids = {};
      for (const [k, v] of Object.entries(t.ids)) ids[k] = new Set(v);
      const numbers = new Set(t.numbers);
      const dates = new Set(t.dates);
      const times = new Set(t.times);
      const money = new Set(t.money);
      const sizes = new Set(t.sizes);
      const measures = new Set(t.measures);
      const out = [];
      for (const c of extract(reply, t.today)) {
        const kind = c.kind;
        const val = c.value;
        let ok = true;
        let reason = "";
        if (kind in ids) {
          ok = ids[kind].has(val);
          reason = `no tool result or line of the email has ${val}`;
        } else if (kind === "date") {
          if (c.weekday_mismatch) {
            ok = false;
            reason = "the weekday doesn't match the date";
          } else {
            ok = dates.has(val);
            reason = "no tool result or line of the email has this date";
          }
        } else if (kind === "time") {
          ok = times.has(val);
          reason = "no tool result or line of the email has this time";
        } else if (kind === "money") {
          ok = money.has(val);
          reason = "no tool result has this amount, and no sum or difference of what the agent saw makes it";
        } else if (kind === "size") {
          ok = sizes.has(val);
          reason = "no item the agent saw has this size";
        } else if (kind === "measure") {
          ok = measures.has(val);
          reason = "no item the agent saw has this measure";
        } else if (["percent", "count", "number"].includes(kind)) {
          ok = numbers.has(val) || (kind === "number" && val >= 2025 && val <= 2027 && val === Math.trunc(val));
          reason = "no tool result or line of the email has this number";
        }
        out.push(Object.assign({}, c, {status: ok ? "supported" : "unsupported", reason: ok ? "" : reason}));
      }
      const acts = t.actions;
      for (const [s, e] of sentences(reply)) {
        const text = reply.slice(s, e);
        if (negation.test(text) || text.trimEnd().endsWith("?")) continue;
        for (const [kind, rxs, tools] of promises) {
          let m = null;
          for (const rx of rxs) {
            m = text.match(rx);
            if (m) break;
          }
          if (!m || conditional.test(text.slice(0, m.index + m[0].length))) continue;
          const done = acts.some((a) => tools.includes(a.tool) && a.verdict === "done");
          const scope = kind === "order" ? reply : text;
          const waiting = acts.some((a) => (tools.includes(a.tool) || tools.includes("*waiting")) && a.verdict === "waiting");
          const claim = {kind: "promise", promise: kind, text: m[0], start: s + m.index, end: s + m.index + m[0].length,
            value: kind};
          if (done) Object.assign(claim, {status: "supported", reason: ""});
          else if (waiting && pending.test(scope)) Object.assign(claim, {status: "supported", reason: ""});
          else if (waiting) {
            Object.assign(claim, {status: "premature", reason: "it waits for a person, so the reply has to call it pending"});
          } else Object.assign(claim, {status: "unsupported", reason: `the agent didn't ${VERBS[kind]}`});
          out.push(claim);
        }
      }
      return out.sort((a, b) => a.start - b.start || (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0));
    }

    function summary(claims) {
      const out = {supported: 0, unsupported: 0, premature: 0};
      for (const c of claims) out[c.status] += 1;
      return out;
    }

    return {extract, check, sentences, summary};
  }

  const api = {make};
  root.IAReplies = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
