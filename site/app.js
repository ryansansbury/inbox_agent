/* Inbox Agent. The page script for one morning of the order inbox: the board of emails in four lanes, the selected
   email's work in the drawer with each decision tied to the sentence that asked for it, the limits and the
   approvals, the replay, the tour, the phone screens and the code view. Everything comes from window.IA, which the
   build wrote, and nothing reaches the network. The rules run live through site/policy.js and the reply checker
   through site/replies.js, the same rules and patterns the scores came from. Events are handled once at the document,
   and nothing is written into the markup inline, which keeps the page inside its content security policy. Pure
   helpers sit on window.IAP for the node check. */
(function () {
  "use strict";
  var win = window, doc = document, IA = win.IA || {}, U = IA.ui || {};
  var IAP = win.IAP = {};
  var Policy = win.IAPolicy;
  var checker = win.IAReplies && IA.lexicon ? win.IAReplies.make(IA.lexicon) : null;
  var EMAILS = IA.emails || [], BYID = {};
  EMAILS.forEach(function (e, i) { e.index = i; BYID[e.id] = e; });
  var MODELS = IA.models || [];
  var LANES = ["needs_you", "handled", "customer", "stopped"];
  var MOVES = ["issue_credit", "reship", "waive_fee", "create_order", "update_ship_to", "create_return", "hold_order"];
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December"];
  var WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var SPEEDS = [2, 4, 8];
  var DEF = {limits: {}, switches: {}};
  Object.keys(IA.limits || {}).forEach(function (k) { DEF.limits[k] = IA.limits[k].value; });
  Object.keys(IA.switches || {}).forEach(function (k) { DEF.switches[k] = IA.switches[k]; });
  var S = {model: IA.route || (MODELS[0] || {}).id, email: BYID.m05 ? "m05" : (EMAILS[0] || {}).id,
    limits: copy(DEF.limits), switches: copy(DEF.switches), decisions: {}, seq: 0, sheet: null, view: "work",
    editing: false, text: {}, raw: {}, speed: 2, present: 0, screen: "list", codeFile: null, codeLoading: false,
    snap: null, layout: "mail", folder: "inbox", q: "", sent: {}, discarded: {}, dark: false};
  var R = null;
  var T = {queued: false, hot: null, before: null, moved: {}};
  var STEPS = [];

  /* ------------------------------------------------------------------ helpers */
  function copy(o) { return JSON.parse(JSON.stringify(o)); }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c];
    });
  }
  /* An ID like SO-20852 or BX-141414-32 stays on one line. Chrome breaks after a hyphen that comes before a digit, so
     after each render the IDs in the new text go into spans that don't wrap. app/page.py does the same for How it works. */
  var ID_IN = /\b[A-Z0-9]+-[A-Z0-9]/, ID_ALL = /\b[A-Z0-9]+(?:-[A-Z0-9]+)+\b/g;
  var NO_IDS = {pre: 1, textarea: 1, select: 1, option: 1, script: 1, style: 1, svg: 1};
  function keepIds(el) {
    if (!el || !el.childNodes) { return; }
    Array.prototype.slice.call(el.childNodes).forEach(function (n) {
      if (n.nodeType === 3) {
        if (!ID_IN.test(n.data)) { return; }
        var wrap = doc.createElement("span");
        wrap.innerHTML = esc(n.data).replace(ID_ALL, "<span class='nw'>$&</span>");
        el.replaceChild(wrap, n);
      } else if (n.nodeType === 1 && !NO_IDS[String(n.localName || n.nodeName).toLowerCase()] &&
          !(n.classList && n.classList.contains("nw"))) {
        keepIds(n);
      }
    });
  }
  function $(sel, root) { return (root || doc).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); }
  function fill(text, v) {
    return String(text === undefined || text === null ? "" : text).replace(/\{(\w+)\}/g, function (m, k) {
      return v && v[k] !== undefined && v[k] !== null ? v[k] : m;
    });
  }
  function word(key, v) { return fill(U[key], v); }
  function tw(table, key, v) { return fill((U[table] || {})[key], v); }
  function has(table, key) { return (U[table] || {})[key] !== undefined; }
  function group(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
  function money(x) {
    var c = Math.round(Math.abs(Number(x)) * 100);
    return (x < 0 ? "-" : "") + "$" + group(Math.floor(c / 100)) + "." + String(c % 100).padStart(2, "0");
  }
  function capMoney(x) { return Math.round(x * 100) % 100 === 0 ? "$" + group(Math.round(x)) : money(x); }
  function limitText(k, v) {
    var unit = (IA.limits[k] || {}).unit || "usd";
    return tw("unit", unit, {v: unit === "usd" ? group(Math.round(v)) : v});
  }
  function ruleLimit(rule, limit) {
    if (limit === null || limit === undefined) { return ""; }
    return rule === "return_window" ? String(limit) : capMoney(limit);
  }
  function clock12(hhmm) {
    var p = String(hhmm).split(":"), h = parseInt(p[0], 10), m = parseInt(p[1], 10);
    return ((h + 11) % 12 + 1) + ":" + String(m).padStart(2, "0") + " " + (h < 12 ? "AM" : "PM");
  }
  function shortTime(hhmm) { var p = String(hhmm).split(":"); return parseInt(p[0], 10) % 12 + ":" + p[1]; }
  function minutes(hhmm) { var p = String(hhmm).split(":"); return parseInt(p[0], 10) * 60 + parseInt(p[1], 10); }
  function hhmm(m) { return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(Math.round(m % 60)).padStart(2, "0"); }
  function isoDate(d) { return d.getUTCFullYear() + "-" + String(d.getUTCMonth() + 1).padStart(2, "0") + "-" + String(d.getUTCDate()).padStart(2, "0"); }
  function parseIso(s) { var p = s.split("-").map(Number); return new Date(Date.UTC(p[0], p[1] - 1, p[2])); }
  function dayWords(iso) { var d = parseIso(iso); return WEEKDAYS[d.getUTCDay()] + ", " + MONTHS[d.getUTCMonth()] + " " + d.getUTCDate(); }
  function secs(ms) { return (Math.round(ms / 100) / 10).toFixed(1); }
  /* The checker's reasons start lower case for the scores' lists, so the drawer gives each a capital and a period. */
  function sentence(s) {
    s = String(s || "");
    return s ? s.charAt(0).toUpperCase() + s.slice(1) + (/[.!?]$/.test(s) ? "" : ".") : "";
  }
  /* "a", "a and b", or "a, b, and c", with the joining word from WORDS.md. */
  function listing(items) {
    var and = word("and");
    if (items.length < 3) { return items.join(" " + and + " "); }
    return items.slice(0, -1).join(", ") + " " + and + " " + items[items.length - 1];
  }
  function lower1(s) { return s && /^[A-Z][a-z]/.test(s) ? s.charAt(0).toLowerCase() + s.slice(1) : s; }
  function calm() { return !!(win.matchMedia && win.matchMedia("(prefers-reduced-motion: reduce)").matches); }
  function phone() { return !!(win.matchMedia && win.matchMedia("(max-width: 900px)").matches); }
  /* A touch screen without a mouse, which is a phone or a tablet. A tap does there what pointing does with a mouse,
     and the tour says tap. */
  var TOUCH = !!(win.matchMedia && win.matchMedia("(hover: none) and (pointer: coarse)").matches);
  function raf(fn) { return (win.requestAnimationFrame || function (f) { return win.setTimeout(f, 16); })(fn); }
  function f1(x) { return String(Math.round(x * 10) / 10); }
  function modelOf(id) { return MODELS.filter(function (m) { return m.id === id; })[0] || {id: id, label: id}; }
  function runOf(m, eid) { return ((IA.runs || {})[m] || {})[eid] || null; }
  function key(m, eid) { return m + "|" + eid; }
  function staffFor(team) {
    var s = (IA.staff || []).filter(function (x) { return x.team === team; })[0];
    return team === "order_desk" || !s ? IA.approver : s;
  }

  /* ------------------------------------------------------------------ the rules, live */
  function limitsObj(lim, sw) {
    var o = {};
    lim = lim || S.limits;
    sw = sw || S.switches;
    Object.keys(lim).forEach(function (k) { o[k] = lim[k]; });
    Object.keys(sw).forEach(function (k) { o[k] = sw[k]; });
    return o;
  }
  /* Every action of one recorded run decided again under the limits, with the IDs the tools would give it, in the
     same order the tools hand them out. A person's decisions apply to actions that wait, and an approval takes its ID
     after the email's own actions, the way the tools' approvals do. */
  function evaluate(m, eid, lim, decisions) {
    var run = runOf(m, eid);
    if (!run) { return null; }
    lim = lim || limitsObj();
    decisions = decisions === undefined ? S.decisions : decisions;
    var next = {order: run.first.order, credit: run.first.credit, ret: run.first["return"], approval: run.first.approval};
    var acts = run.actions.map(function (a, i) {
      var v = a.fixed || !Policy ? a.verdict : Policy.decide(a.tool, a.facts, lim);
      var x = {i: i, a: a, v: v, changed: v.verdict !== a.verdict.verdict, id: null, approval: null, decided: null};
      if (v.verdict === "waiting") {
        x.approval = "AP-" + next.approval++;
        if (a.tool === "create_order") { x.id = "SO-" + next.order++; }
        x.decided = (decisions && decisions[key(m, eid) + "|" + i]) || null;
      } else if (v.verdict === "done") {
        if (a.tool === "issue_credit") { x.id = "CM-" + next.credit++; }
        else if (a.tool === "reship" || a.tool === "create_order") { x.id = "SO-" + next.order++; }
        else if (a.tool === "create_return") { x.id = "RA-" + next.ret++; }
      }
      return x;
    });
    acts.filter(function (x) { return x.decided && x.decided.verdict === "approved"; })
      .sort(function (p, q) { return p.decided.seq - q.decided.seq; })
      .forEach(function (x) {
        if (x.a.tool === "issue_credit") { x.id = "CM-" + next.credit++; }
        else if (x.a.tool === "reship") { x.id = "SO-" + next.order++; }
        else if (x.a.tool === "create_return") { x.id = "RA-" + next.ret++; }
      });
    var forLane = acts.map(function (x) {
      return {tool: x.a.tool, team: x.a.team, verdict: x.decided ? {verdict: x.decided.verdict} : x.v};
    });
    if (run.finish.ignored.length) { forLane.push({tool: "refuse"}); }
    return {m: m, eid: eid, run: run, acts: acts, lane: Policy ? Policy.lane(forLane) : "handled",
      changed: acts.filter(function (x) { return x.changed; }).length,
      waiting: acts.filter(function (x) { return x.v.verdict === "waiting" && !x.decided; })};
  }
  IAP.evaluate = evaluate;
  function amountOf(x, lim) {
    var f = x.a.facts || {};
    switch (x.a.tool) {
      case "issue_credit": return f.amount;
      case "reship": return f.value;
      case "waive_fee": return f.amount;
      case "create_order": return f.total;
      case "create_return": return Policy ? Policy.returnCredit(f.gross, lim || limitsObj())[0] : f.credit;
      default: return null;
    }
  }
  function lanes(m, lim, decisions) {
    var out = {};
    EMAILS.forEach(function (e) { var ev = evaluate(m, e.id, lim, decisions); if (ev) { out[e.id] = ev.lane; } });
    return out;
  }
  IAP.lanes = function (m) { return lanes(m || S.model); };
  /* The emails whose lane differs between the defaults and the visitor's limits, before any decision. */
  function movedBy() {
    var a = lanes(S.model, limitsObj(DEF.limits, DEF.switches), {}), b = lanes(S.model, limitsObj(), {});
    return Object.keys(a).filter(function (k) { return a[k] !== b[k]; });
  }
  IAP.moved = movedBy;
  function insideMoney(m) {
    var lim = limitsObj(), sum = 0;
    EMAILS.forEach(function (e) {
      if (R && !R.done[e.id]) { return; }
      var ev = evaluate(m, e.id);
      if (!ev) { return; }
      ev.acts.forEach(function (x) {
        if (x.v.verdict === "done" && ["issue_credit", "reship", "waive_fee", "create_return"].indexOf(x.a.tool) >= 0) {
          sum += Math.round((amountOf(x, lim) || 0) * 100);
        }
      });
    });
    return sum / 100;
  }
  IAP.insideMoney = insideMoney;
  function limitsChanged() {
    return Object.keys(DEF.limits).some(function (k) { return S.limits[k] !== DEF.limits[k]; }) ||
      Object.keys(DEF.switches).some(function (k) { return S.switches[k] !== DEF.switches[k]; });
  }

  /* ------------------------------------------------------------------ the lines on cards and decisions */
  function linesText(lines) {
    return listing((lines || []).map(function (l) { return l.qty + " × " + l.sku; }));
  }
  function whatFields(x) {
    var a = x.a, args = a.args || {};
    return {invoice: args.invoice_id || "", lines: linesText(args.lines) + (args.order_id ? " · " + args.order_id : ""),
      fee: args.fee || "", on: args.order_id || args.invoice_id || "", id: x.id || "", order: args.order_id || "",
      to: (a.extra || {}).to || args.location_id || "", team: tw("team", a.team || "", {})};
  }
  function whatTitle(x) { return tw("what", x.a.tool, whatFields(x)); }
  function whoWaits(x) { return tw("who", x.v.approver || "order_desk", {}); }
  function didPhrase(x, lim) {
    var a = x.a, amt = amountOf(x, lim), f = whatFields(x);
    var vals = {id: x.id || f.order, amount: amt === null ? "" : "<span class='num'>" + esc(money(amt)) + "</span>",
      fee: esc(f.fee), order: esc(f.order), who: esc(whoWaits(x)), what: esc(tw("what_short", a.tool, {}))};
    vals.id = esc(vals.id);
    if (x.decided) { return fill(esc(tw("did", x.decided.verdict, {})), vals); }
    var k = a.tool + "." + x.v.verdict;
    if (x.v.verdict === "blocked" || !has("did", k)) { return fill(esc(tw("did", "blocked", {})), vals); }
    return fill(esc(tw("did", k, {})), vals);
  }
  /* The one line on a card: what the agent did, in the order the page cares about. */
  function didLine(ev, e) {
    var acts = ev.acts, run = ev.run, lim = limitsObj();
    var route = acts.filter(function (x) { return x.a.tool === "route_to_person"; })[0];
    var planted = run.finish.ignored.length && (e.flags || []).length;
    if (planted) { return {ic: "no", html: esc(tw("did", "refuse", {}))}; }
    if (route && route.a.team === "security") { return {ic: "no", html: esc(tw("did", "route.security", {}))}; }
    if (run.finish.ignored.length) { return {ic: "no", html: esc(tw("did", "refuse", {}))}; }
    var moves = acts.filter(function (x) { return MOVES.indexOf(x.a.tool) >= 0; });
    if (moves.length) {
      var parts = moves.slice(0, 2).map(function (x) { return didPhrase(x, lim); });
      var html = parts.map(function (p, i) { return i ? lower1(p) : p; }).join(" " + esc(word("and")) + " ");
      var ic = moves.some(function (x) { return x.v.verdict === "waiting" && !x.decided; }) ? "you" :
        moves.some(function (x) { return x.v.verdict === "blocked" || (x.decided && x.decided.verdict === "denied"); }) ? "no" : "ok";
      return {ic: ic, html: html};
    }
    if (route) { return {ic: route.a.team === "order_desk" ? "you" : "no", html: esc(tw("did", "route." + route.a.team, {}))}; }
    if (acts.some(function (x) { return x.a.tool === "ask_customer"; })) { return {ic: "ask", html: esc(tw("did", "ask", {}))}; }
    if (e.claims) { return {ic: "no", html: esc(tw("did", "spoof", {}))}; }
    if (!run.finish.reply) { return {ic: "ok", html: esc(tw("did", "none", {}))}; }
    return {ic: "ok", html: esc(tw("did", "reply", {}))};
  }
  function chipOf(ev) {
    if (ev.lane === "needs_you") {
      var w = ev.waiting[0];
      if (w && has("chip", w.v.rule)) { return {cls: "you", text: tw("chip", w.v.rule, {limit: ruleLimit(w.v.rule, w.v.limit)})}; }
      return null;
    }
    if (ev.lane === "stopped") {
      var e = BYID[ev.eid], r = ev.acts.filter(function (x) { return x.a.tool === "route_to_person"; })[0];
      if (ev.run.finish.ignored.length && (e.flags || []).length) { return {cls: "no", text: tw("chip", "refuse", {})}; }
      if (r && has("chip", r.a.team)) { return {cls: "no", text: tw("chip", r.a.team, {})}; }
      if (ev.run.finish.ignored.length) { return {cls: "no", text: tw("chip", "refuse", {})}; }
    }
    return null;
  }
  function differs(run) {
    var s = run.score;
    return !!(s && ((s.missed || []).length || (s.extra || []).length || (s.unsafe || []).length || s.routing_ok === false));
  }
  IAP.didLine = function (eid, m) { var ev = evaluate(m || S.model, eid); return ev ? didLine(ev, BYID[eid]) : null; };

  /* ------------------------------------------------------------------ the address */
  function writeHash() {
    if (!win.history || !win.history.replaceState) { return; }
    var h = S.present ? "#tour-" + S.present : S.view === "how" ? "#how" :
      "#" + (S.layout === "board" ? "board/" : "") + S.email + (S.sheet ? "/" + S.sheet : "") +
      (S.model !== IA.route ? "@" + S.model : "");
    try { win.history.replaceState(null, "", h); } catch (e) { /* file:// in some browsers */ }
  }
  function readHash(h) {
    var m = /^#tour-(\d+)$/.exec(h || "");
    if (m) { return {tour: Math.min(STEPS.length || 12, Math.max(1, parseInt(m[1], 10)))}; }
    if (h === "#how") { return {how: true}; }
    m = /^#(board)?\/?(m\d\d)?(?:\/(limits|log))?(?:@([a-z0-9-]+))?$/.exec(h || "");
    if (!m || !(m[1] || m[2])) { return {}; }
    return {layout: m[1] ? "board" : "mail", email: m[2] || null, sheet: m[3] || null, model: m[4] || null};
  }
  IAP.readHash = readHash;

  /* ------------------------------------------------------------------ the summary line */
  function visible(eid) { return !R || (R.done[eid]); }
  function renderSummary() {
    var box = $("#summary");
    if (!box) { return; }
    var counts = {needs_you: 0, handled: 0, customer: 0, stopped: 0};
    EMAILS.forEach(function (e) {
      if (!visible(e.id)) { return; }
      var ev = evaluate(S.model, e.id);
      if (ev) { counts[ev.lane] += 1; }
    });
    var pills = LANES.map(function (k) {
      var n = counts[k], text = k === "needs_you" && n === 1 ? tw("pill", "needs_you.one", {}) : tw("pill", k, {n: n});
      return "<span class='pill p-" + k + "'>" + esc(text) + "</span>";
    }).join("");
    var moved = R ? [] : movedBy(), mv = "";
    if (limitsChanged() && !R) {
      var line = moved.length === 1 ? tw("moved", "one", {}) : moved.length ? tw("moved", "many", {n: moved.length}) : tw("moved", "none", {});
      mv = "<span class='moved-note' id='moved-line'>" + esc(line) + " <button type='button' data-reset='limits'>" +
        esc(word("reset")) + "</button></span>";
    }
    box.classList.toggle("has-moved", !!mv);
    box.innerHTML = "<h1>" + esc(word("day")) + "</h1><span class='sub'>" + esc(word("span", {n: EMAILS.length, from: clock12((IA.morning || {}).from || "07:00"), to: clock12((IA.morning || {}).to || "09:30")})) +
      "</span>" + pills + mv + "<span class='money'>" + esc(word("money")) + " <b id='money'>" +
      esc(money(insideMoney(S.model))) + "</b></span>";
    var lc = $("#log-count"), w = waitingAll();
    if (lc) { lc.textContent = w.length && !R ? String(w.length) : ""; }
  }

  /* ------------------------------------------------------------------ the board */
  function cardHtml(e, ev, working) {
    var run = ev.run, sel = e.id === S.email ? " sel" : "", lane = working ? "working" : ev.lane;
    var d = working ? {ic: "ask", html: esc(word("working"))} : didLine(ev, e), chip = working ? null : chipOf(ev);
    var n = run.steps.length, steps = n === 1 ? tw("steps", "one", {}) : tw("steps", "many", {n: n});
    var who = e.customer ? e.customer.name : e.from.name;
    var icon = {ok: "✓", you: "!", ask: "?", no: "✕"}[d.ic];
    return "<button type='button' class='card " + lane + sel + (T.moved[e.id] ? " moved" : "") + "' data-eid='" + e.id +
      "' aria-pressed='" + (sel ? "true" : "false") + "'><span class='row1'><span class='who'>" + esc(who) +
      "</span><span class='t'>" + esc(shortTime(e.at)) + "</span></span><span class='subj'>" + esc(e.subject) +
      "</span><span class='did'><span class='ic " + d.ic + "' aria-hidden='true'>" + icon + "</span><span>" + d.html +
      "</span></span><span class='foot'>" + (chip ? "<span class='rule " + chip.cls + "'>" + esc(chip.text) + "</span>" : "") +
      (!working && differs(run) ? "<span class='differs'>" + esc(word("differs")) + "</span>" : "") +
      "<span class='steps'>" + esc(steps) + "</span></span></button>";
  }
  function renderBoard() {
    if (S.layout === "mail") { renderRail(); renderList(); return; }
    var by = {needs_you: [], handled: [], customer: [], stopped: []}, working = "";
    EMAILS.forEach(function (e) {
      if (R && !R.done[e.id] && R.current !== e.id) { return; }
      var ev = evaluate(S.model, e.id);
      if (!ev) { return; }
      if (R && R.current === e.id && !R.done[e.id]) { working = cardHtml(e, ev, true); return; }
      by[ev.lane].push(cardHtml(e, ev, false));
    });
    var strip = $("#incoming"), slot = $("#cards-incoming");
    if (strip) { strip.hidden = !R; }
    if (slot) { slot.innerHTML = working || "<p class='none'>" + esc(tw("replay", "quiet", {})) + "</p>"; keepIds(slot); }
    LANES.forEach(function (k) {
      var box = $("#cards-" + k), n = $("#n-" + k);
      if (box) { box.innerHTML = by[k].length ? by[k].join("") : "<p class='none'>" + esc(word("lane_empty")) + "</p>"; keepIds(box); }
      if (n) { n.textContent = String(by[k].length); }
    });
  }
  /* Cards glide from where they were to their new lane. Positions are taken before a render and the difference is
     played back through a transform. */
  function positions() {
    var out = {};
    $$("#board .card").forEach(function (c) {
      var r = c.getBoundingClientRect();
      out[c.getAttribute("data-eid")] = {x: r.left, y: r.top};
    });
    return out;
  }
  function glide(before) {
    if (!before || calm() || !win.requestAnimationFrame) { return; }
    $$("#board .card").forEach(function (c) {
      var id = c.getAttribute("data-eid"), was = before[id];
      if (!was || !c.style) { return; }
      var r = c.getBoundingClientRect(), dx = was.x - r.left, dy = was.y - r.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) { return; }
      c.style.transition = "none";
      c.style.transform = "translate(" + f1(dx) + "px, " + f1(dy) + "px)";
      raf(function () {
        raf(function () {
          c.style.transition = "transform .55s cubic-bezier(.2, .7, .2, 1)";
          c.style.transform = "";
        });
      });
    });
  }

  /* ------------------------------------------------------------------ the drawer */
  function stepsShown(eid, run) { return R && R.current === eid && !R.done[eid] ? R.steps : run.steps.length; }
  function finished(eid) { return !R || R.done[eid] || R.finished[eid]; }
  function hitSentences(ev) {
    var out = {};
    ev.acts.forEach(function (x) { if (x.a.sentence) { out[x.a.sentence] = x.v.verdict; } });
    return out;
  }
  function emailHtml(e, ev, done) {
    var hits = done ? hitSentences(ev) : {}, flags = {}, run = ev.run;
    (e.flags || []).forEach(function (f) { flags[f.n] = f; });
    var breaks = {};
    (e.breaks || []).forEach(function (n) { breaks[n] = true; });
    function sent(s) {
      var cls = "s" + (flags[s.n] ? " flag" : hits[s.n] ? " hit" : ""), mark = "";
      if (flags[s.n]) { mark = "<span class='mark red'>" + s.n + "</span>"; }
      else if (hits[s.n]) { mark = "<span class='mark'>" + s.n + "</span>"; }
      /* A badge keeps the sentence's first word beside it, so no line ends on a badge alone. */
      var cut = s.text.indexOf(" "), lead = mark && cut > 0 ? s.text.slice(0, cut) : "", rest = lead ? s.text.slice(cut) : s.text;
      return (breaks[s.n] && s.n > 1 ? "<br><br>" : "") + "<span class='" + cls + "' id='s-" + s.n + "' data-n='" + s.n + "'>" +
        (lead ? "<span class='nw'>" + mark + esc(lead) + "</span>" : mark) + esc(rest) + "</span> ";
    }
    var body = e.sentences.filter(function (s) { return s.part === "body"; }).map(sent).join("");
    var fwd = (e.quoted || []).map(function (q, i) {
      var inner = e.sentences.filter(function (s) { return s.part === "quoted:" + i; }).map(sent).join("")
        .replace(/^<br><br>/, "");
      return "<div class='fwd'><p class='fwd-head'>" + esc(word("forwarded", {from: q.from})) + "</p>" + inner + "</div>";
    }).join("");
    var from = "<p class='from'>" + esc(e.from.name) + " &lt;" + esc(e.from.email) + "&gt;" +
      (e.customer ? "" : " · <span class='warn'>" + esc(word("unverified")) + "</span>") + "</p>";
    var sig = e.sig && e.sig.length ? "<p class='sig'>" + esc(e.sig.join("\n")) + "</p>" : "";
    var notes = "";
    if (done && e.flags && e.flags.length) {
      notes = "<ul class='flags'>" + e.flags.map(function (f) {
        var ign = run.finish.ignored.indexOf(f.n) >= 0;
        return "<li><span class='mark red'>" + f.n + "</span>" + esc(word("flag", {reason: f.reason})) + " <span class='" +
          (ign ? "ok" : "") + "'>" + esc(tw("ignored", ign ? "yes" : "no", {})) + "</span></li>";
      }).join("") + "</ul>";
      if (e.what_if && Policy) {
        var v = Policy.decide(e.what_if.tool, e.what_if.facts, limitsObj());
        var line = v.verdict === "waiting" ?
          tw("what_if", "waiting", {amount: money(e.what_if.args.amount), invoice: e.what_if.args.invoice_id, limit: capMoney(v.limit)}) :
          v.verdict === "blocked" ? tw("what_if", "blocked", {why: tw("why", v.rule + ".blocked", {limit: ruleLimit(v.rule, v.limit)})}) : "";
        if (line) { notes += "<p class='whatif' id='what-if'>" + esc(line) + "</p>"; }
      }
    }
    if (done && e.claims) { notes += "<p class='whatif'>" + esc(word("spoof", {name: e.claims})) + "</p>"; }
    return "<section class='sec' id='sec-email'><h3>" + esc(tw("sec", "email", {})) + "</h3><div class='email'>" + from +
      body + sig + fwd + "</div>" + notes + "</section>";
  }
  function rawHtml(step, turn) {
    var sent = {name: step.tool, input: Object.assign({}, step.args, step.sentence ? {sentence: step.sentence} : {})};
    var out = "<b>" + esc(tw("raw", "sent", {})) + "</b>" + esc(JSON.stringify(sent, null, 2)) + "<b>" +
      esc(tw("raw", "back", {})) + "</b>" + esc(JSON.stringify(step.result, null, 2));
    if (turn && turn.text) { out = "<b>" + esc(tw("raw", "said", {})) + "</b>" + esc(turn.text) + out; }
    return out;
  }
  function traceHtml(e, run, shown, done) {
    var out = "", m = modelOf(S.model);
    run.turns.forEach(function (t, ti) {
      var steps = t.steps.filter(function (i) { return i < shown; });
      if (t.finish && !t.steps.length) {
        if (done) { out += "<li class='finish'>" + esc(word("finish", {secs: secs(t.ms)})) + "</li>"; }
        return;
      }
      if (!steps.length) { return; }
      out += "<li class='turn'>" + esc(t.steps.length > 1 ? tw("turn", "many", {n: ti + 1, secs: secs(t.ms), k: t.steps.length}) :
        tw("turn", "one", {n: ti + 1, secs: secs(t.ms)})) + "</li>";
      steps.forEach(function (i) {
        var s = run.steps[i], err = s.result && s.result.error, act = s.act !== null && s.act !== undefined;
        var open = !!S.raw[key(S.model, e.id) + "|" + i];
        out += "<li class='step" + (R && R.fresh === i && R.current === e.id ? " new" : "") + "' id='st-" + i + "' data-step='" + i +
          "'><span class='k'>" + (i + 1) + "</span><span class='tool" + (err || !s.valid ? " err" : act ? " act" : "") + "'>" +
          esc(s.tool) + "</span><span class='res" + (err ? " err" : "") + "'>" + esc(s.valid ? s.line : word("invalid")) +
          "</span><button type='button' class='rawbtn' data-raw='" + i + "' aria-expanded='" + open + "'>" +
          esc(tw("raw", open ? "hide" : "show", {})) + "</button>" +
          (open ? "<div class='raw'>" + rawHtml(s, t.steps[0] === i ? t : null) + "</div>" : "") + "</li>";
      });
      if (t.finish && done) { out += "<li class='finish'>" + esc(word("finish", {secs: secs(t.ms)})) + "</li>"; }
    });
    var n = run.steps.length;
    var meta = m.label + " · " + (n === 1 ? tw("steps", "one", {}) : tw("steps", "many", {n: n})) + " · " + f1(run.usage.seconds) + " s";
    return "<section class='sec' id='sec-did'><h3>" + esc(tw("sec", "did", {})) + " <span class='aside'>" + esc(meta) +
      "</span></h3><ol class='trace' id='trace'>" + out + "</ol></section>";
  }
  function decisionHtml(e, ev, x, lim) {
    var a = x.a, v = x.v, amt = amountOf(x, lim);
    var verdict = x.decided ? x.decided.verdict : v.verdict;
    var cls = x.decided ? (x.decided.verdict === "approved" ? "done" : "blocked") : v.verdict;
    var label = v.verdict === "waiting" && v.approver === "credit" && !x.decided ? tw("verdict", "waiting_credit", {}) : tw("verdict", verdict, {});
    var whyKey = a.tool === "route_to_person" ? "route.done" : a.tool === "ask_customer" ? "ask.done" : v.rule + "." + v.verdict;
    var why = tw("why", whyKey, {limit: ruleLimit(v.rule, v.limit)});
    var ic = cls === "done" ? "ok" : cls === "waiting" ? "you" : "no", icon = {ok: "✓", you: "!", no: "✕"}[ic];
    var meta = [];
    if (a.sentence) { meta.push("<span>" + esc(word("answers", {n: a.sentence})) + "</span>"); }
    if (x.approval) { meta.push("<span class='num'>" + esc(word("approval", {id: x.approval})) + "</span>"); }
    var out = "<div class='dec " + cls + "' id='dec-" + x.i + "' data-act='" + x.i + "'" + (a.sentence ? " data-to='" + a.sentence + "'" : "") +
      "><span class='what'>" + esc(whatTitle(x)) + "</span><span class='amt'>" + (amt === null || amt === undefined ? "" : esc(money(amt))) +
      "</span>" + detailHtml(x) + "<span class='why'><span class='ic " + ic + "' aria-hidden='true'>" + icon + "</span><span><b>" + esc(label) + ".</b> " +
      esc(why) + "</span></span>" + (meta.length ? "<span class='meta'>" + meta.join("") + "</span>" : "");
    if (x.changed) { out += "<span class='changed'>" + esc(word("changed", {verdict: lower1(tw("verdict", a.verdict.verdict, {}))})) + "</span>"; }
    if (v.verdict === "waiting" && !R) {
      var person = staffFor(v.approver || "order_desk");
      if (x.decided) {
        out += "<div class='decided'><span class='ic " + (x.decided.verdict === "approved" ? "ok" : "no") + "' aria-hidden='true'>" +
          (x.decided.verdict === "approved" ? "✓" : "✕") + "</span><span>" + esc(word("decided", {verdict: tw("verdict", x.decided.verdict, {}), name: person.name})) +
          "</span><button type='button' class='linkbtn' data-undo='" + x.i + "' data-eid='" + e.id + "'>" + esc(tw("act", "undo", {})) + "</button></div>";
      } else {
        out += "<div class='acts'><button type='button' class='btn-ok' data-decide='approved' data-act='" + x.i + "' data-eid='" + e.id + "'>" +
          esc(tw("act", "approve", {})) + "</button><button type='button' class='btn-no' data-decide='denied' data-act='" + x.i +
          "' data-eid='" + e.id + "'>" + esc(tw("act", "deny", {})) + "</button><span class='as'>" + esc(tw("act", "as", {name: person.name})) + "</span></div>";
      }
    }
    return out + "</div>";
  }
  /* What the action holds in the agent's own terms: the items by name for an order, a reship or a return, and the
     agent's words for a question, a route or a credit. */
  function itemsText(lines) {
    return listing((lines || []).map(function (l) {
      var it = (IA.items || {})[String(l.sku || "").toUpperCase()];
      return l.qty + " × " + (it ? it.name : l.sku);
    }));
  }
  function detailHtml(x) {
    var a = x.a, args = a.args || {}, text = "";
    if (a.tool === "ask_customer") { text = args.question; }
    else if (a.tool === "route_to_person") { text = args.summary; }
    else if (a.tool === "issue_credit") { text = args.reason; }
    if (text) { return "<q class='said'>" + esc(text) + "</q>"; }
    if (["create_order", "reship", "create_return"].indexOf(a.tool) >= 0 && args.lines) {
      var line = itemsText(args.lines);
      if (a.tool === "create_order" && args.requested_date) { line += " · " + tw("detail", "by", {day: dayWords(args.requested_date)}); }
      if (a.tool === "create_order" && args.rush) { line += " · " + tw("detail", "rush", {}); }
      return "<span class='detail'>" + esc(line) + "</span>";
    }
    if (a.tool === "hold_order" && args.until) { return "<span class='detail'>" + esc(tw("detail", "until", {day: dayWords(args.until)})) + "</span>"; }
    return "";
  }
  function decisionsHtml(e, ev) {
    var lim = limitsObj();
    var body = ev.acts.length ? ev.acts.map(function (x) { return decisionHtml(e, ev, x, lim); }).join("") :
      "<p class='empty-note'>" + esc(word("no_actions")) + "</p>";
    return "<section class='sec' id='sec-decisions'><h3>" + esc(tw("sec", "decisions", {})) + "</h3>" + body + "</section>";
  }

  /* ------------------------------------------------------------------ the reply and its checks */
  function tableFor(ev) {
    var t = ev.run.table, out = {};
    Object.keys(t).forEach(function (k) { out[k] = t[k]; });
    out.actions = ev.acts.map(function (x) { return {tool: x.a.tool, verdict: x.v.verdict}; });
    return out;
  }
  function replyText(e, run) {
    var k = key(S.model, e.id);
    return S.text[k] !== undefined ? S.text[k] : run.finish.reply;
  }
  function claimsOf(ev, text) { return checker && text ? checker.check(text, tableFor(ev)) : []; }
  IAP.claims = function (eid, text, m) {
    var ev = evaluate(m || S.model, eid);
    return claimsOf(ev, text === undefined ? replyText(BYID[eid], ev.run) : text);
  };
  /* Where a claim's value came from: the first step whose result holds it, else the email's sentence, else worked
     out (a sum, a difference or a line total). */
  function holds(x, c) {
    if (x === null || x === undefined) { return false; }
    if (typeof x === "object") {
      for (var k in x) { if (Object.prototype.hasOwnProperty.call(x, k) && holds(x[k], c)) { return true; } }
      return false;
    }
    if (typeof x === "number") {
      if (c.kind === "money") { return Math.round(x * 100) === c.value; }
      if (["count", "number", "percent"].indexOf(c.kind) >= 0) { return x === c.value; }
      return false;
    }
    var s = String(x);
    if (c.kind === "date") { return c.value && s.slice(0, 10) === c.value; }
    if (c.kind === "time") { return s.indexOf(" " + c.value) >= 0 || s.indexOf("T" + c.value) >= 0; }
    if (c.kind === "size") { return s.toLowerCase().indexOf(String(c.value).toLowerCase()) >= 0; }
    if (c.kind === "measure") { return s.toLowerCase().replace(/\s+/g, "").indexOf(String(c.value).toLowerCase()) >= 0; }
    return s.toUpperCase() === String(c.value).toUpperCase();
  }
  function sourceOf(c, ev, e) {
    var run = ev.run;
    if (c.kind === "promise") {
      var tools = (IA.lexicon.promises.filter(function (p) { return p[0] === c.promise; })[0] || [0, 0, []])[2];
      var x = ev.acts.filter(function (y) { return tools.indexOf(y.a.tool) >= 0; })[0];
      return x ? {kind: "step", i: x.a.step} : null;
    }
    for (var i = 0; i < run.steps.length; i++) {
      if (run.steps[i].valid && holds(run.steps[i].result, c)) { return {kind: "step", i: i}; }
    }
    var low = String(c.text).toLowerCase();
    for (var j = 0; j < e.sentences.length; j++) {
      if (e.sentences[j].text.toLowerCase().indexOf(low) >= 0) { return {kind: "email", n: e.sentences[j].n}; }
    }
    if (c.kind === "date" && c.value === IA.today) { return {kind: "today"}; }
    return c.status === "supported" ? {kind: "derived"} : null;
  }
  IAP.sourceOf = function (eid, c) { var ev = evaluate(S.model, eid); return sourceOf(c, ev, BYID[eid]); };
  function claimSpans(text, claims) {
    var out = "", at = 0;
    claims.forEach(function (c, k) {
      if (c.start < at) { return; }
      out += esc(text.slice(at, c.start)) + "<u class='" + c.status + (c.kind === "promise" ? " promise" : "") + "' data-claim='" + k +
        "' tabindex='0'>" + esc(text.slice(c.start, c.end)) + "</u>";
      at = c.end;
    });
    return out + esc(text.slice(at));
  }
  function replyHtml(e, ev) {
    var run = ev.run, text = replyText(e, run), k = key(S.model, e.id);
    var head = "<h3>" + esc(tw("sec", "reply", {})) + " <span class='aside'>" + esc(e.from.name) + "</span></h3>";
    if (!text && !S.editing) {
      var why = run.unfinished ? "unfinished" : e.claims || !e.customer ? "spoof" : "none";
      return "<section class='sec' id='sec-reply'>" + head + "<p class='empty-note'>" + esc(tw("reply_none", why, {})) + "</p></section>";
    }
    var claims = claimsOf(ev, text), bad = claims.filter(function (c) { return c.status !== "supported"; });
    var summary = !claims.length ? tw("claims", "none", {}) : !bad.length ? tw("claims", "ok", {}) :
      bad.length === 1 ? tw("claims", "one", {}) : tw("claims", "many", {n: bad.length});
    var out = "<section class='sec' id='sec-reply'>" + head;
    if (S.editing) {
      out += "<label class='sr' for='reply-edit'>" + esc(tw("edit", "label", {})) + "</label><textarea class='reply-edit' id='reply-edit'>" +
        esc(text) + "</textarea>";
    }
    out += "<div class='reply' id='reply'>" + claimSpans(text, claims) + "</div>";
    out += "<p class='verdict-line' id='claims-line'><span class='ic " + (bad.length ? "no" : "ok") + "' aria-hidden='true'>" +
      (bad.length ? "!" : "✓") + "</span><span>" + esc(summary) + "</span></p>";
    if (bad.length) {
      out += "<ul class='findings' id='findings'>" + bad.map(function (c) {
        return "<li class='" + c.status + "'><q>" + esc(c.text) + "</q> " + esc(tw("status", c.status, {})) + ". " + esc(sentence(c.reason)) + "</li>";
      }).join("") + "</ul>";
    }
    if (ev.changed) { out += "<p class='banner'>" + esc(ev.changed === 1 ? tw("drafted", "one", {}) : tw("drafted", "many", {n: ev.changed})) + "</p>"; }
    if (ev.acts.some(function (x) { return x.decided; })) { out += "<p class='after'>" + esc(word("after")) + "</p>"; }
    if (!R) {
      var samples = sampleKinds(ev).map(function (s) {
        return "<button type='button' class='btn sample' data-sample='" + s + "'>" + esc(tw("sample", s, {})) + "</button>";
      }).join("");
      out += "<div class='edit-row'><button type='button' class='btn' id='edit-reply'>" + esc(tw("edit", S.editing ? "stop" : "start", {})) +
        "</button>" + (S.text[k] !== undefined ? "<button type='button' class='linkbtn' id='restore-reply'>" + esc(tw("edit", "restore", {})) +
        "</button>" : "") + "</div><div class='sample-row'><span class='lbl'>" + esc(tw("sample", "title", {})) + "</span>" + samples + "</div>";
    }
    return out + "</section>";
  }
  /* The sample bad claims a visitor can add, each one built so the checker has to flag it. */
  function sampleKinds(ev) {
    var out = ["money", "date"], done = function (tools) {
      return ev.acts.some(function (x) { return tools.indexOf(x.a.tool) >= 0 && x.v.verdict === "done"; });
    };
    if (!done(["issue_credit", "create_return"]) || !done(["reship"])) { out.push("promise"); }
    if (ev.acts.some(function (x) { return x.v.verdict === "waiting" && has("sample_text", "pending." + x.a.tool); })) { out.push("pending"); }
    return out;
  }
  function sampleText(kind, ev) {
    var t = ev.run.table, money_ = {};
    (t.money || []).forEach(function (c) { money_[c] = true; });
    if (kind === "money") {
      var claims = claimsOf(ev, ev.run.finish.reply).filter(function (c) { return c.kind === "money"; });
      var c = (claims[0] ? claims[0].value : 10000) + 1000;
      while (money_[c]) { c += 137; }
      return tw("sample_text", "money", {amount: money(c / 100)});
    }
    if (kind === "date") {
      var dates = {}, d = parseIso(IA.today);
      (t.dates || []).forEach(function (x) { dates[x] = true; });
      d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 9));
      while (dates[isoDate(d)] || d.getUTCDay() === 0 || d.getUTCDay() === 6) { d = new Date(d.getTime() + 86400000); }
      return tw("sample_text", "date", {date: dayWords(isoDate(d))});
    }
    if (kind === "promise") {
      var credit = ev.acts.some(function (x) { return ["issue_credit", "create_return"].indexOf(x.a.tool) >= 0 && x.v.verdict === "done"; });
      if (!credit) {
        var a = 2500;
        while (money_[a]) { a += 100; }
        return tw("sample_text", "promise.issue_credit", {amount: money(a / 100)});
      }
      return tw("sample_text", "promise.reship", {});
    }
    var w = ev.acts.filter(function (x) { return x.v.verdict === "waiting" && has("sample_text", "pending." + x.a.tool); })[0];
    return w ? tw("sample_text", "pending." + w.a.tool, {}) : "";
  }
  IAP.sampleText = function (eid, kind) { return sampleText(kind, evaluate(S.model, eid)); };
  function addSample(kind) {
    var e = BYID[S.email], ev = evaluate(S.model, e.id), text = replyText(e, ev.run), s = sampleText(kind, ev);
    if (!s) { return; }
    var cut = text.lastIndexOf("\n\n");
    S.text[key(S.model, e.id)] = cut > 0 ? text.slice(0, cut) + "\n\n" + s + text.slice(cut) : text + (text ? " " : "") + s;
    renderDrawer(false);
  }
  IAP.addSample = addSample;
  function recheck() {
    var e = BYID[S.email], ev = evaluate(S.model, e.id), area = $("#reply-edit");
    if (!area) { return; }
    S.text[key(S.model, e.id)] = area.value;
    var claims = claimsOf(ev, area.value), bad = claims.filter(function (c) { return c.status !== "supported"; });
    var box = $("#reply"), line = $("#claims-line"), list = $("#findings");
    if (box) { box.innerHTML = claimSpans(area.value, claims); keepIds(box); }
    if (line) {
      var summary = !claims.length ? tw("claims", "none", {}) : !bad.length ? tw("claims", "ok", {}) :
        bad.length === 1 ? tw("claims", "one", {}) : tw("claims", "many", {n: bad.length});
      line.innerHTML = "<span class='ic " + (bad.length ? "no" : "ok") + "' aria-hidden='true'>" + (bad.length ? "!" : "✓") +
        "</span><span>" + esc(summary) + "</span>";
    }
    var html = bad.map(function (c) {
      return "<li class='" + c.status + "'><q>" + esc(c.text) + "</q> " + esc(tw("status", c.status, {})) + ". " + esc(sentence(c.reason)) + "</li>";
    }).join("");
    if (list) { list.innerHTML = html; keepIds(list); list.hidden = !bad.length; }
    else if (bad.length && line && line.after) {
      var ul = doc.createElement("ul");
      ul.className = "findings";
      ul.setAttribute("id", "findings");
      ul.innerHTML = html;
      keepIds(ul);
      line.after(ul);
    }
    soonTour();
  }
  IAP.recheck = recheck;

  function keyHtml(e, run) {
    var s = run.score, lane = (tw("lane", e.key.lane, {}) || "").split("|")[0], lines = [];
    lines.push("<p>" + esc(e.key.handling) + "</p>");
    if (s) {
      var miss = (s.missed || []).map(function (t) { return tw("what_short", t, {}) || t; });
      var extra = (s.extra || []).map(function (t) { return tw("what_short", t, {}) || t; });
      if (!miss.length && !extra.length && s.routing_ok !== false) { lines.push("<p class='ok'>" + esc(tw("key", "match", {})) + "</p>"); }
      if (miss.length) { lines.push("<p class='bad'>" + esc(tw("key", "missed", {what: listing(miss)})) + "</p>"); }
      if (extra.length) { lines.push("<p class='bad'>" + esc(tw("key", "extra", {what: listing(extra)})) + "</p>"); }
      if (s.routing_ok === false) {
        Object.keys(s.checks || {}).filter(function (k) { return !s.checks[k]; }).forEach(function (k) {
          var team = /^routed to (\w+)$/.exec(k);
          var text = team ? tw("check", "routed", {team: tw("team", team[1], {})}) : tw("check", k.replace(/ /g, "_"), {});
          if (text) { lines.push("<p class='bad'>" + esc(text) + "</p>"); }
        });
      }
    }
    lines.push("<p class='muted'>" + esc(tw("key", "lane", {lane: lane})) + "</p>");
    return "<details class='key' id='sec-key'><summary>" + esc(tw("sec", "key", {})) + "<span class='aside'>" +
      esc(tw("key", "lead", {})) + "</span></summary>" + lines.join("") + "</details>";
  }
  function drawerHead(e, ev) {
    var who = e.customer ? e.from.name + " · " + e.customer.name : e.from.name;
    var intents = finished(e.id) ? (ev.run.finish.intents || []).map(function (i) {
      var raw = String(i).replace(/_/g, " ");
      return "<span>" + esc(tw("intent", i, {}) || raw.charAt(0).toUpperCase() + raw.slice(1)) + "</span>";
    }).join("") : "";
    return "<div class='dhead'><b>" + esc(who) + "</b><span class='t'>" + esc(clock12(e.at)) + "</span></div><p class='dsub'>" +
      esc(e.subject) + "</p>" + (intents ? "<div class='intents'>" + intents + "</div>" : "");
  }
  function renderDrawer(animate) {
    if (S.layout === "mail") { renderRead(animate); renderPanel(animate); drawThreads(); soonTour(); return; }
    var body = $("#drawer-body"), e = BYID[S.email];
    if (!body) { return; }
    if (!e || (R && !R.current && !R.done[S.email])) {
      body.innerHTML = "<p class='quiet'>" + esc(tw("replay", "quiet", {})) + "</p>";
      soonTour();
      return;
    }
    var ev = evaluate(S.model, e.id);
    if (!ev) { body.innerHTML = ""; return; }
    var run = ev.run, shown = stepsShown(e.id, run), done = finished(e.id);
    var html = drawerHead(e, ev) + emailHtml(e, ev, done) + traceHtml(e, run, shown, done);
    if (done) {
      html += decisionsHtml(e, ev);
      if (run.finish.note) {
        html += "<section class='sec' id='sec-note'><h3>" + esc(tw("sec", "note", {})) + "</h3><p class='note-box'>" + esc(run.finish.note) + "</p></section>";
      }
      html += replyHtml(e, ev) + keyHtml(e, run);
    }
    var keepScroll = body.scrollTop;
    body.innerHTML = html;
    keepIds(body);
    if (!animate && typeof keepScroll === "number") { body.scrollTop = keepScroll; }
    else if (animate) { body.scrollTop = 0; }
    soonTour();
  }

  /* ------------------------------------------------------------------ the tour's redraw */
  /* Queues one redraw of the tour's mark for the next frame, so a burst of changes draws once. */
  function soonTour() {
    if (T.queued) { return; }
    T.queued = true;
    raf(function () {
      T.queued = false;
      drawTour();
    });
  }
  /* Each decision names the numbered sentence that asked for it, and pointing at a decision lights that sentence. The
     click-through checks that every decision's sentence is on the page. */
  function linkPlan() {
    var out = [];
    $$("#drawer-body .dec, #panel-body .dec").forEach(function (d) {
      var n = d.getAttribute("data-to");
      out.push({dec: d.getAttribute("data-act"), n: n ? parseInt(n, 10) : null, found: !n || !!doc.getElementById("s-" + n)});
    });
    return out;
  }
  IAP.linkPlan = linkPlan;
  function lightAct(act) {
    T.litAct = act;
    $$(".s.lit, .dec.lit").forEach(function (x) { x.classList.remove("lit"); });
    if (act !== null && act !== undefined) {
      var d = doc.getElementById("dec-" + act), n = d ? d.getAttribute("data-to") : null, s = n ? doc.getElementById("s-" + n) : null;
      if (d) { d.classList.add("lit"); }
      if (s) { s.classList.add("lit"); }
    }
    if (S.layout === "mail") { drawThreads(); }
  }

  /* ------------------------------------------------------------------ the popover for a claim */
  function pointClaim(el) {
    var e = BYID[S.email], ev = evaluate(S.model, e.id), text = replyText(e, ev.run);
    var claims = claimsOf(ev, $("#reply-edit") ? $("#reply-edit").value : text), c = claims[parseInt(el.getAttribute("data-claim"), 10)];
    if (!c) { return; }
    var src = sourceOf(c, ev, e), from = "";
    if (src && src.kind === "step") { from = tw("from", "step", {n: src.i + 1}); el.setAttribute("data-src", "step:" + src.i); }
    else if (src && src.kind === "email") { from = tw("from", "email", {n: src.n}); el.setAttribute("data-src", "email:" + src.n); }
    else if (src) { from = tw("from", src.kind, {}); el.removeAttribute("data-src"); }
    /* The step or the email's sentence a claim came from lights up while the claim is pointed at. */
    $$("#trace .step.lit, .s.lit").forEach(function (x) { x.classList.remove("lit"); });
    var lit = src && src.kind === "step" ? doc.getElementById("st-" + src.i) :
      src && src.kind === "email" ? doc.getElementById("s-" + src.n) : null;
    if (lit) { lit.classList.add("lit"); }
    T.hot = el;
    var html = "<b>" + esc(tw("status", c.status, {})) + "</b>" + (from ? " · " + esc(from) : "") +
      (c.reason ? "<br><span class='why'>" + esc(sentence(c.reason)) + "</span>" : "");
    pop(el, html);
  }
  function unpoint() {
    if (!T.hot) { return; }
    T.hot = null;
    $$("#trace .step.lit, .s.lit").forEach(function (x) { x.classList.remove("lit"); });
    pop(null);
  }
  function pop(el, html) {
    var box = $("#pop");
    if (!box) { return; }
    if (!el) { box.hidden = true; return; }
    box.innerHTML = html;
    keepIds(box);
    box.hidden = false;
    if (el.getBoundingClientRect && box.style) {
      var r = el.getBoundingClientRect();
      box.style.left = Math.max(8, Math.min((win.innerWidth || 1200) - 336, r.left + (win.scrollX || 0))) + "px";
      box.style.top = (r.bottom + (win.scrollY || 0) + 6) + "px";
    }
  }

  /* ------------------------------------------------------------------ the limits and the log */
  function waitingAll() {
    var out = [];
    EMAILS.forEach(function (e) {
      var ev = evaluate(S.model, e.id);
      if (ev) { ev.waiting.forEach(function (x) { out.push({e: e, ev: ev, x: x}); }); }
    });
    return out;
  }
  IAP.waiting = function () { return waitingAll().map(function (w) { return w.e.id + ":" + w.x.a.tool; }); };
  function limitsHtml() {
    var rows = Object.keys(IA.limits || {}).map(function (k) {
      var spec = IA.limits[k], v = S.limits[k], changed = v !== DEF.limits[k];
      return "<div class='limit'><label for='lim-" + k + "'><span>" + esc(tw("limit", k, {})) + "</span><b class='" + (changed ? "changed" : "") +
        "' id='limv-" + k + "'>" + esc(limitText(k, v)) + "</b></label><input type='range' id='lim-" + k + "' data-limit='" + k + "' min='" +
        spec.min + "' max='" + spec.max + "' step='" + spec.step + "' value='" + v + "'><span class='ticks'><span>" + esc(limitText(k, spec.min)) +
        "</span><span>" + esc(limitText(k, spec.max)) + "</span></span></div>";
    }).join("");
    var sw = Object.keys(IA.switches || {}).map(function (k) {
      return "<label class='switch'><input type='checkbox' data-switch='" + k + "'" + (S.switches[k] ? " checked" : "") + "><span>" +
        esc(tw("switch", k, {})) + "</span></label>";
    }).join("");
    var moved = movedBy(), line = !limitsChanged() ? "" : moved.length === 1 ? tw("moved", "one", {}) :
      moved.length ? tw("moved", "many", {n: moved.length}) : tw("moved", "none", {});
    return "<section class='sheet' id='limits'><div class='sheet-head'><h2>" + esc(tw("limits", "title", {})) + "</h2>" +
      (phone() ? "" : "<button type='button' class='btn' data-close='sheet'>" + esc(tw("limits", "close", {})) + "</button>") + "</div><p class='lead'>" +
      esc(tw("limits", "lead", {})) + "</p>" + rows + sw + "<p class='moved-line' id='limits-moved' aria-live='polite'>" + esc(line) + "</p>" +
      "<button type='button' class='btn' data-reset='limits'" + (limitsChanged() ? "" : " disabled") + ">" + esc(word("reset")) + "</button>" +
      "<p class='never'>" + esc(tw("limits", "never", {})) + "</p></section>";
  }
  function auditRows() {
    var rows = [], lim = limitsObj();
    EMAILS.forEach(function (e) {
      var ev = evaluate(S.model, e.id);
      if (!ev) { return; }
      var at = clock12(e.at);
      ev.run.finish.ignored.forEach(function (n) {
        rows.push({at: at, actor: "agent", what: tw("logwhat", "ignored", {n: n}), eid: e.id});
      });
      ev.acts.forEach(function (x) {
        var f = whatFields(x), amt = amountOf(x, lim), parts = [tw("what_short", x.a.tool, {})];
        var target = x.a.tool === "create_order" ? x.id : f.invoice || f.order;
        if (target) { parts.push(target); }
        if (amt !== null && amt !== undefined) { parts.push(money(amt)); }
        if (x.a.tool === "route_to_person") { rows.push({at: at, actor: "agent", what: tw("logwhat", "routed", {team: tw("team", x.a.team, {})}), eid: e.id}); return; }
        if (x.a.tool === "ask_customer") { rows.push({at: at, actor: "agent", what: tw("logwhat", "asked", {}), eid: e.id}); return; }
        rows.push({at: at, actor: "agent", what: tw("logwhat", "proposed", {what: parts.join(" · ")}), eid: e.id});
        rows.push({at: at, actor: "rules", what: tw("logwhat", x.v.verdict, {what: tw("what_short", x.a.tool, {})}) +
          (x.approval && x.v.verdict === "waiting" ? " · " + x.approval : ""), eid: e.id});
      });
    });
    var mine = [];
    EMAILS.forEach(function (e) {
      var ev = evaluate(S.model, e.id);
      if (!ev) { return; }
      ev.acts.forEach(function (x) {
        if (x.decided) {
          mine.push({seq: x.decided.seq, at: tw("log", "now", {}), actor: "approver", person: staffFor(x.v.approver || "order_desk").name,
            what: tw("logwhat", x.decided.verdict, {what: tw("what_short", x.a.tool, {})}) + " · " + (x.approval || "") +
              (x.id && x.decided.verdict === "approved" && x.a.tool !== "create_order" ? " · " + x.id : ""), eid: e.id, you: true});
        }
      });
    });
    var desk = (IA.approver || {}).name || staffFor("order_desk").name;
    EMAILS.forEach(function (e) {
      var k = key(S.model, e.id);
      if (S.sent[k]) { mine.push({seq: S.sent[k], at: tw("log", "now", {}), actor: "approver", person: desk, what: tw("logwhat", "sent", {}), eid: e.id, you: true}); }
      if (S.discarded[k]) { mine.push({seq: S.discarded[k], at: tw("log", "now", {}), actor: "approver", person: desk, what: tw("logwhat", "discarded", {}), eid: e.id, you: true}); }
    });
    mine.sort(function (p, q) { return p.seq - q.seq; });
    return rows.concat(mine);
  }
  IAP.audit = auditRows;
  function logHtml() {
    var w = waitingAll(), lim = limitsObj();
    var wait = w.length ? "<ul class='wait-list' id='wait-list'>" + w.map(function (it) {
      var x = it.x, amt = amountOf(x, lim), person = staffFor(x.v.approver || "order_desk");
      return "<li><span><button type='button' class='open' data-eid='" + it.e.id + "'>" + esc(it.e.customer ? it.e.customer.name : it.e.from.name) +
        "</button> · " + esc(whatTitle(x)) + "</span><span class='num'>" + (amt === null || amt === undefined ? "" : esc(money(amt))) +
        "</span><span class='acts'><button type='button' class='btn-ok' data-decide='approved' data-act='" + x.i + "' data-eid='" + it.e.id + "'>" +
        esc(tw("act", "approve", {})) + "</button><button type='button' class='btn-no' data-decide='denied' data-act='" + x.i + "' data-eid='" +
        it.e.id + "'>" + esc(tw("act", "deny", {})) + "</button><span class='as'>" + esc(tw("act", "as", {name: person.name})) + "</span></span></li>";
    }).join("") + "</ul>" : "<p class='empty-note'>" + esc(tw("log", "none", {})) + "</p>";
    var rows = auditRows().map(function (r) {
      var actor = r.actor === "approver" ? tw("actor", "approver", {name: r.person}) : tw("actor", r.actor, {});
      return "<li class='" + (r.you ? "you" : "") + "'><button type='button' class='at' data-open='" + r.eid + "'>" + esc(r.at) +
        "</button><span class='actor'>" + esc(actor) + "</span><span class='what'>" + esc(r.what) + "</span></li>";
    }).join("");
    var any = Object.keys(S.decisions).length;
    var head = "<div class='sheet-head'><h2>" + esc(tw("log", "title", {})) + "</h2>" +
      (phone() ? "" : "<button type='button' class='btn' data-close='sheet'>" + esc(tw("log", "close", {})) + "</button>") + "</div>";
    var waiting = "<h3 class='sec-h'>" + esc(tw("log", "waiting", {})) + "</h3>" + wait;
    var audit = "<h3 class='sec-h'>" + esc(tw("log", "audit", {})) + "</h3><p class='lead'>" + esc(tw("log", "lead", {})) +
      "</p><ol class='audit' id='audit'>" + rows + "</ol>" + (any ? "<button type='button' class='btn' data-reset='decisions'>" +
        esc(tw("log", "undo", {})) + "</button>" : "");
    return {head: head, waiting: waiting, audit: audit};
  }
  function logSheet() { var l = logHtml(); return "<section class='sheet' id='log'>" + l.head + l.waiting + l.audit + "</section>"; }
  function renderSide() {
    if (S.layout === "mail") { renderPanel(false); renderRail(); drawThreads(); return; }
    var side = $("#side"), body = $("#side-body");
    if (!side || !body) { return; }
    var both = phone();
    side.classList.toggle("open", !!S.sheet || both);
    if (both) {
      var l = logHtml();
      body.innerHTML = "<div id='wait-box'><section class='sheet' id='log'>" + l.head + l.waiting + "</section></div>" +
        "<div id='limits-box'>" + limitsHtml() + "</div><div id='audit-box'><section class='sheet'>" + l.audit + "</section></div>";
    } else {
      body.innerHTML = S.sheet === "log" ? "<div id='log-box'>" + logSheet() + "</div>" :
        S.sheet === "limits" ? "<div id='limits-box'>" + limitsHtml() + "</div>" : "";
    }
    keepIds(body);
    var bl = $("#open-limits"), bg = $("#open-log");
    if (bl) { bl.setAttribute("aria-pressed", S.sheet === "limits" ? "true" : "false"); }
    if (bg) { bg.setAttribute("aria-pressed", S.sheet === "log" ? "true" : "false"); }
  }
  /* The log alone, so a slider beside it on a phone keeps the pointer while it moves. */
  function renderLogBox() {
    var box = $("#log-box"), wait = $("#wait-box"), audit = $("#audit-box");
    if (box) { box.innerHTML = logSheet(); keepIds(box); }
    if (wait || audit) {
      var l = logHtml();
      if (wait) { wait.innerHTML = "<section class='sheet' id='log'>" + l.head + l.waiting + "</section>"; keepIds(wait); }
      if (audit) { audit.innerHTML = "<section class='sheet'>" + l.audit + "</section>"; keepIds(audit); }
    }
  }
  /* Only the parts of the limits sheet that change while a slider moves, so the slider keeps the pointer. */
  function refreshLimits() {
    Object.keys(IA.limits || {}).forEach(function (k) {
      var b = $("#limv-" + k);
      if (b) { b.textContent = limitText(k, S.limits[k]); b.className = S.limits[k] !== DEF.limits[k] ? "changed" : ""; }
    });
    var moved = movedBy(), line = $("#limits-moved");
    if (line) {
      line.textContent = !limitsChanged() ? "" : moved.length === 1 ? tw("moved", "one", {}) :
        moved.length ? tw("moved", "many", {n: moved.length}) : tw("moved", "none", {});
    }
    var reset = $("[data-reset='limits']", $("#side-body"));
    if (reset) { if (limitsChanged()) { reset.removeAttribute("disabled"); } else { reset.setAttribute("disabled", ""); } }
  }
  function ruleLines() {
    var box = $("#rule-lines");
    if (!box) { return; }
    var caps = Object.keys(IA.limits || {}).filter(function (k) { return has("rule_cap", k); })
      .map(function (k) { return tw("rule_cap", k, {v: limitText(k, S.limits[k])}); });
    var joined = listing(caps), lines = [];
    if (caps.length) { lines.push(word("rule_caps", {caps: joined.charAt(0).toUpperCase() + joined.slice(1)})); }
    Object.keys(IA.limits || {}).forEach(function (k) {
      if (has("rule_line", k)) { lines.push(tw("rule_line", k, {v: limitText(k, S.limits[k])})); }
    });
    Object.keys(IA.switches || {}).forEach(function (k) { lines.push(tw("rule_line", k + "." + (S.switches[k] ? "on" : "off"), {})); });
    lines.push(tw("limits", "never", {}));
    box.innerHTML = lines.map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("");
    keepIds(box);
  }
  function setLimit(k, v) {
    var before = positions(), was = lanes(S.model);
    S.limits[k] = v;
    afterRules(before, was);
    refreshLimits();
  }
  IAP.setLimit = function (k, v) { setLimit(k, v); };
  function setSwitch(k, on) {
    var before = positions(), was = lanes(S.model);
    S.switches[k] = on;
    afterRules(before, was);
    refreshLimits();
  }
  IAP.setSwitch = setSwitch;
  function afterRules(before, was) {
    var now = lanes(S.model);
    T.moved = {};
    Object.keys(now).forEach(function (id) { if (was[id] !== now[id]) { T.moved[id] = true; } });
    renderSummary();
    renderBoard();
    glide(before);
    renderDrawer(false);
    renderLogBox();
    ruleLines();
    win.setTimeout(function () { T.moved = {}; }, 1700);
  }
  function resetLimits() {
    var before = positions(), was = lanes(S.model);
    S.limits = copy(DEF.limits);
    S.switches = copy(DEF.switches);
    afterRules(before, was);
    renderSide();
  }
  IAP.resetLimits = resetLimits;
  function decide(eid, i, verdict) {
    var before = positions(), was = lanes(S.model), k = key(S.model, eid) + "|" + i;
    if (verdict) { S.seq += 1; S.decisions[k] = {verdict: verdict, seq: S.seq}; }
    else { delete S.decisions[k]; }
    afterRules(before, was);
    renderSide();
  }
  IAP.decide = decide;
  function openSheet(name, force) {
    S.sheet = force === undefined ? (S.sheet === name ? null : name) : force ? name : null;
    if (S.sheet && phone()) { toScreen(S.layout === "mail" ? "panel" : "side", true); }
    renderSide();
    writeHash();
    var root = S.layout === "mail" ? "#panel-body " : "#side-body ";
    var first = S.sheet ? $(root + (S.sheet === "limits" ? "input" : "button")) : null;
    if (first && first.focus && !S.present) { first.focus(); }
  }
  IAP.openSheet = openSheet;

  /* ------------------------------------------------------------------ the mailbox (11/19)
     The opening view. The rail holds the folders and the agent's labels, the list holds the morning's emails, the read
     pane holds the open email with the agent's draft under it, and the panel at the right holds the agent's work where
     an add-in sits. Only one layout renders at a time, so the ids the board's drawer uses never exist twice. */
  var AV = 12;
  var MAIL_SCREENS = ["list", "read", "panel"], BOARD_SCREENS = ["board", "drawer", "side"];
  var FICON = {
    inbox: "M3 13h5l1.5 3h5L16 13h5M5 5h14l2 8v5.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5V13z",
    drafts: "M6 3h9l4 4v14H6zM15 3v4h4M9 13h7M9 17h5",
    sent: "M4 12 20 4l-6 16-3-7zM11 13l9-9",
    limits: "M4 7h10M18 7h2M4 17h4M12 17h8M16 5v4M10 15v4",
    log: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"
  };
  var ICONS = {ok: "✓", you: "!", ask: "?", no: "✕"};
  function svgOf(d) {
    return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='" + d + "' fill='none' stroke='currentColor' stroke-width='1.9' " +
      "stroke-linecap='round' stroke-linejoin='round'/></svg>";
  }
  function whoOf(e) { return e.customer ? e.customer.name : e.from.name; }
  function initials(s) {
    return (String(s).match(/[A-Za-z]+/g) || []).slice(0, 2).map(function (w) { return w.charAt(0).toUpperCase(); }).join("");
  }
  function firstLine(e) {
    var body = e.sentences.filter(function (s) { return s.part === "body"; });
    var s = body.filter(function (x) { return x.text.split(" ").length > 3; })[0] || body[0];
    return s ? s.text : "";
  }
  function shown(eid) { return !R || !!R.done[eid] || R.current === eid; }
  function laneName(lane) { return String(tw("lane", lane, {}) || lane).split("|")[0]; }
  function draftState(e, ev) {
    var k = key(S.model, e.id);
    if (S.sent[k]) { return "sent"; }
    if (S.discarded[k]) { return "gone"; }
    return finished(e.id) && replyText(e, ev.run) ? "draft" : null;
  }
  function inFolder(e, ev) {
    var f = S.folder;
    if (f === "inbox") { return true; }
    if (f === "drafts") { return draftState(e, ev) === "draft"; }
    if (f === "sent") { return draftState(e, ev) === "sent"; }
    return finished(e.id) && ev.lane === f;
  }
  function matches(e) {
    var q = String(S.q || "").trim().toLowerCase();
    if (!q) { return true; }
    return [whoOf(e), e.from.name, e.from.email, e.subject].concat(e.sentences.map(function (s) { return s.text; }))
      .join(" ").toLowerCase().indexOf(q) >= 0;
  }
  function labHtml(lane) {
    return "<span class='lab l-" + lane + "'><span class='dot' aria-hidden='true'></span>" + esc(laneName(lane)) + "</span>";
  }
  function tagHtml(state) {
    var word_ = {draft: "draft_ready", sent: "sent_tag", gone: "discarded_tag"}[state];
    return word_ ? "<span class='lab tag-" + state + "'>" + esc(tw("mail", word_, {})) + "</span>" : "";
  }
  function whyHtml(chip) {
    return chip ? "<span class='why" + (chip.cls === "no" ? " red" : "") + "'>" + esc(chip.text) + "</span>" : "";
  }
  function mrowHtml(e, ev, working) {
    var sel = e.id === S.email, who = whoOf(e);
    var d = working ? {ic: "ask", html: esc(tw("mail", "working", {}))} : didLine(ev, e);
    var tags = working ? "" : labHtml(ev.lane) + tagHtml(draftState(e, ev)) + whyHtml(chipOf(ev));
    return "<button type='button' class='mrow" + (sel ? " sel" : "") + (working ? " working" : "") + (T.moved[e.id] ? " moved" : "") +
      "' data-mail='" + e.id + "' aria-pressed='" + (sel ? "true" : "false") + "'><span class='av av-" + (e.index % AV) +
      "' aria-hidden='true'>" + esc(initials(who)) + "</span><span class='mbody'><span class='r1'><span class='who'>" + esc(who) +
      "</span><span class='t'>" + esc(shortTime(e.at)) + "</span></span><span class='subj'>" + esc(e.subject) +
      "</span><span class='snip'>" + esc(firstLine(e)) + "</span><span class='agent'><span class='ic " + d.ic +
      "' aria-hidden='true'>" + ICONS[d.ic] + "</span><span>" + d.html + "</span></span>" +
      (tags ? "<span class='tags'>" + tags + "</span>" : "") + "</span></button>";
  }
  function mailCounts() {
    var c = {inbox: 0, drafts: 0, sent: 0, needs_you: 0, handled: 0, customer: 0, stopped: 0};
    EMAILS.forEach(function (e) {
      if (!shown(e.id)) { return; }
      var ev = evaluate(S.model, e.id);
      if (!ev) { return; }
      c.inbox += 1;
      if (!finished(e.id)) { return; }
      c[ev.lane] += 1;
      var st = draftState(e, ev);
      if (st === "draft") { c.drafts += 1; }
      if (st === "sent") { c.sent += 1; }
    });
    return c;
  }
  /* The handled replies a person can send in one go: checked and with no claim the checker flags. */
  function sendable() {
    return EMAILS.filter(function (e) {
      if (!shown(e.id) || !finished(e.id)) { return false; }
      var ev = evaluate(S.model, e.id);
      if (!ev || ev.lane !== "handled" || draftState(e, ev) !== "draft") { return false; }
      return !claimsOf(ev, replyText(e, ev.run)).some(function (c) { return c.status !== "supported"; });
    });
  }
  function foldHtml(k, icon, name, n, attr) {
    var on = attr === "sheet" ? S.sheet === k : S.folder === k;
    return "<button type='button' class='fold" + (on ? " on" : "") + "' data-" + (attr || "folder") + "='" + k + "' aria-pressed='" +
      (on ? "true" : "false") + "' aria-label='" + esc(name) + "' title='" + esc(name) + "'>" + icon + "<span class='lbl'>" +
      esc(name) + "</span><span class='n'>" + (n ? n : "") + "</span></button>";
  }
  function renderRail() {
    var box = $("#rail");
    if (!box) { return; }
    var c = mailCounts(), w = R ? 0 : waitingAll().length;
    box.innerHTML = foldHtml("inbox", svgOf(FICON.inbox), tw("folder", "inbox", {}), c.inbox) +
      foldHtml("drafts", svgOf(FICON.drafts), tw("folder", "drafts", {}), c.drafts) +
      foldHtml("sent", svgOf(FICON.sent), tw("folder", "sent", {}), c.sent) +
      "<h4>" + esc(tw("folder", "labels", {})) + "</h4>" + LANES.map(function (k) {
        return foldHtml(k, "<span class='sw " + k + "' aria-hidden='true'></span>", laneName(k), c[k]);
      }).join("") + "<h4>" + esc(tw("folder", "agent", {})) + "</h4>" +
      foldHtml("limits", svgOf(FICON.limits), tw("folder", "limits", {}), 0, "sheet") +
      foldHtml("log", svgOf(FICON.log), tw("folder", "log", {}), w, "sheet");
  }
  function renderList() {
    var box = $("#mrows"), head = $("#mspan");
    if (!box) { return; }
    var rows = [];
    EMAILS.slice().sort(function (a, b) { return a.at < b.at ? 1 : a.at > b.at ? -1 : 0; }).forEach(function (e) {
      if (!shown(e.id)) { return; }
      var ev = evaluate(S.model, e.id);
      if (!ev) { return; }
      var working = !!(R && R.current === e.id && !R.done[e.id]);
      if (working ? S.folder !== "inbox" : !inFolder(e, ev)) { return; }
      if (!matches(e)) { return; }
      rows.push(mrowHtml(e, ev, working));
    });
    box.innerHTML = rows.length ? rows.join("") : "<p class='mnone'>" + esc(tw("mail", S.q ? "no_match" : "none", {})) + "</p>";
    keepIds(box);
    if (!head) { return; }
    var ready = R ? [] : sendable();
    var chips = ["inbox"].concat(LANES).concat(["drafts"]).map(function (k) {
      var name = k === "inbox" || k === "drafts" ? tw("folder", k, {}) : laneName(k);
      return "<button type='button' data-folder='" + k + "' class='" + (S.folder === k ? "on" : "") + "' aria-pressed='" +
        (S.folder === k ? "true" : "false") + "'>" + esc(name) + "</button>";
    }).join("");
    head.innerHTML = "<span>" + esc(word("span", {n: EMAILS.length, from: clock12((IA.morning || {}).from || "07:00"),
      to: clock12((IA.morning || {}).to || "09:30")})) + "</span><span>" + esc(word("money")) + " <b>" +
      esc(money(insideMoney(S.model))) + "</b></span>" +
      (S.folder === "drafts" && ready.length ? "<button type='button' class='btn send-all' id='send-checked'>" +
        esc(ready.length === 1 ? tw("mail", "send_checked_one", {}) : tw("mail", "send_checked", {n: ready.length})) + "</button>" : "") +
      "<span class='folders-phone'>" + chips + "</span>";
  }
  function draftHtml(e, ev) {
    var run = ev.run, text = replyText(e, run), k = key(S.model, e.id);
    if (!text && !S.editing) { return "<div class='draft'><div class='draft-inner'>" + replyHtml(e, ev) + "</div></div>"; }
    var ok = claimsOf(ev, text).filter(function (c) { return c.status === "supported"; }).length;
    var sent = S.sent[k], gone = S.discarded[k], person = (IA.approver || {}).name || "";
    var head = "<div class='draft-head'><b>" + esc(tw("mail", "draft_by", {})) + "</b><span>" +
      esc(ok === 1 ? tw("mail", "checked_one", {}) : tw("mail", "checked", {n: ok})) + "</span><span class='to'>" +
      esc(tw("mail", "to", {name: e.from.name})) + "</span></div>";
    var foot = sent ? "<p class='sent-note'>" + esc(tw("mail", "sent_note", {name: person})) + "</p>" :
      gone ? "<p class='sent-note'>" + esc(tw("mail", "discarded_note", {})) + " <button type='button' class='linkbtn' " +
        "data-undo-draft='" + e.id + "'>" + esc(tw("mail", "undo", {})) + "</button></p>" :
      "<div class='draft-foot'><button type='button' class='btn-send' id='send-reply'" + (R ? " disabled" : "") + ">" +
        esc(tw("mail", "send", {})) + "</button><button type='button' class='btn' id='discard-reply'" + (R ? " disabled" : "") + ">" +
        esc(tw("mail", "discard", {})) + "</button><span class='hint'>" + esc(tw("mail", "hint", {})) + "</span></div>";
    return "<div class='draft" + (sent ? " is-sent" : "") + (gone ? " is-gone" : "") + "' id='draft'>" + head +
      "<div class='draft-inner'>" + replyHtml(e, ev) + "</div>" + foot + "</div>";
  }
  function renderRead(animate) {
    var body = $("#read-body"), pane = $("#read"), e = BYID[S.email];
    if (!body) { return; }
    if (!e || (R && !R.current && !R.done[S.email])) {
      body.innerHTML = "<p class='quiet'>" + esc(tw("replay", "quiet", {})) + "</p>";
      return;
    }
    var ev = evaluate(S.model, e.id);
    if (!ev) { body.innerHTML = ""; return; }
    var done = finished(e.id), who = whoOf(e);
    var tags = done ? labHtml(ev.lane) + tagHtml(draftState(e, ev)) + whyHtml(chipOf(ev)) :
      "<span class='lab tag-draft'>" + esc(tw("mail", "working", {})) + "</span>";
    var keep = pane ? pane.scrollTop : 0;
    body.innerHTML = "<h1>" + esc(e.subject) + "</h1><div class='tags'>" + tags + "<button type='button' class='btn agent-toggle' " +
      "id='agent-toggle'>" + esc(tw("panel", "title", {})) + "</button></div><div class='rfrom'><span class='av av-" + (e.index % AV) +
      "' aria-hidden='true'>" + esc(initials(who)) + "</span><div><b>" + esc(e.from.name) + "</b> <span class='addr'>&lt;" +
      esc(e.from.email) + "&gt;" + (e.customer ? "" : " · <span class='warn'>" + esc(word("unverified")) + "</span>") +
      "</span><div class='addr'>" + esc(tw("mail", "to_desk", {})) + "</div></div><span class='t'>" + esc(clock12(e.at)) +
      "</span></div>" + emailHtml(e, ev, done) + (done ? draftHtml(e, ev) : "");
    keepIds(body);
    if (pane) { pane.scrollTop = animate ? 0 : keep; }
  }
  /* The limits each of the agent's actions met, with any it hit lit in amber. */
  function checkedHtml(ev) {
    var seen = {}, cells = [];
    ev.acts.forEach(function (x) {
      var rule = x.v.rule;
      if (!rule || seen[rule] || !(IA.limits || {})[rule]) { return; }
      seen[rule] = true;
      var hit = x.v.verdict === "waiting" || x.v.verdict === "blocked";
      cells.push("<div class='" + (hit ? "hit" : "") + "'><span>" + esc(tw("limit", rule, {})) + "</span><b>" +
        esc(limitText(rule, S.limits[rule])) + "</b></div>");
    });
    return cells.length ? "<section class='sec' id='sec-checked'><h3>" + esc(tw("panel", "checked_head", {})) + "</h3><div class='checked'>" +
      cells.join("") + "</div></section>" : "";
  }
  function agentHtml() {
    var e = BYID[S.email];
    if (!e || !shown(e.id) || (R && !R.current && !R.done[S.email])) { return "<p class='quiet'>" + esc(tw("replay", "quiet", {})) + "</p>"; }
    var ev = evaluate(S.model, e.id);
    if (!ev) { return ""; }
    var run = ev.run, done = finished(e.id), html = done ? decisionsHtml(e, ev) : "";
    html += traceHtml(e, run, stepsShown(e.id, run), done);
    if (done) {
      html += checkedHtml(ev);
      if (run.finish.note) {
        html += "<section class='sec' id='sec-note'><h3>" + esc(tw("sec", "note", {})) + "</h3><p class='note-box'>" + esc(run.finish.note) + "</p></section>";
      }
      html += keyHtml(e, run);
    }
    return html;
  }
  function renderPanel(animate) {
    var tabs = $("#ptabs"), body = $("#panel-body");
    if (!tabs || !body) { return; }
    var w = R ? 0 : waitingAll().length, cur = S.sheet || "email";
    tabs.innerHTML = ["email", "limits", "log"].map(function (k) {
      return "<button type='button' role='tab' data-ptab='" + k + "' aria-selected='" + (cur === k ? "true" : "false") + "'>" +
        esc(tw("ptab", k, {})) + (k === "log" && w ? "<span class='count'>" + w + "</span>" : "") + "</button>";
    }).join("");
    var keep = body.scrollTop;
    body.innerHTML = S.sheet === "limits" ? "<div id='limits-box'>" + limitsHtml() + "</div>" :
      S.sheet === "log" ? "<div id='log-box'>" + logSheet() + "</div>" : agentHtml();
    keepIds(body);
    body.scrollTop = animate ? 0 : keep;
  }
  /* A curve from each decision in the panel to the sentence it answers, drawn across the gutter when the panel sits
     beside the email. The sentence itself is lit, so the curve starts at the read pane's edge on the sentence's line. */
  function drawThreads() {
    var svg = $("#threads"), mail = $("#mail"), read = $("#read"), body = $("#panel-body");
    if (!svg) { return; }
    if (S.layout !== "mail" || S.sheet || S.view !== "work" || phone() || !mail || !read || !body || !mail.clientWidth ||
        (win.innerWidth || 1600) <= 1100) { svg.innerHTML = ""; return; }
    var box = mail.getBoundingClientRect(), rr = read.getBoundingClientRect(), pr = body.getBoundingClientRect(), out = "";
    $$("#panel-body .dec[data-to]").forEach(function (d) {
      var s = doc.getElementById("s-" + d.getAttribute("data-to")), rects = s ? s.getClientRects() : [];
      if (!rects.length) { return; }
      var last = rects[rects.length - 1], dr = d.getBoundingClientRect();
      var y1 = last.top + last.height / 2, y2 = dr.top + 18;
      if (y1 < rr.top + 4 || y1 > rr.bottom - 4 || y2 < pr.top + 4 || y2 > pr.bottom - 4) { return; }
      var x1 = rr.right - 8 - box.left, x2 = dr.left - box.left, mid = (x1 + x2) / 2;
      y1 -= box.top; y2 -= box.top;
      out += "<path" + (d.classList.contains("lit") ? " class='lit'" : "") + " d='M" + x1 + " " + y1 + " C" + mid + " " + y1 + " " +
        mid + " " + y2 + " " + x2 + " " + y2 + "'/><circle cx='" + x1 + "' cy='" + y1 + "' r='3'/><circle cx='" + x2 + "' cy='" +
        y2 + "' r='3.5'/>";
    });
    svg.innerHTML = out;
  }
  IAP.threads = function () { return $$("#threads path").length; };
  function screensNow() { return S.layout === "mail" ? MAIL_SCREENS : BOARD_SCREENS; }
  function setLayout(name, quiet) {
    if (name !== "mail" && name !== "board") { return; }
    S.layout = name;
    doc.body.classList.toggle("layout-mail", name === "mail");
    doc.body.classList.toggle("layout-board", name === "board");
    doc.body.classList.remove("panel-open");
    $$("[data-layout]").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-layout") === name ? "true" : "false"); });
    var clear = name === "mail" ? ["#drawer-body", "#side-body"] : ["#read-body", "#panel-body", "#mrows", "#threads", "#ptabs", "#rail"];
    clear.forEach(function (sel) { var el = $(sel); if (el) { el.innerHTML = ""; } });
    markScreen(name === "mail" ? "list" : "board");
    if (!quiet) { renderAll(true); writeHash(); }
  }
  IAP.setLayout = setLayout;
  /* Dark mode, for anyone who prefers it. Light is the default and nothing is stored, so a new visit opens light. */
  function setDark(on) {
    S.dark = !!on;
    doc.body.classList.toggle("dark", S.dark);
    var b = $("#theme");
    if (b) { b.setAttribute("aria-pressed", S.dark ? "true" : "false"); }
    drawThreads();
  }
  IAP.setDark = setDark;
  function sendReply(eid, quiet) {
    var k = key(S.model, eid);
    if (R || S.sent[k]) { return; }
    S.seq += 1;
    S.sent[k] = S.seq;
    delete S.discarded[k];
    S.editing = false;
    if (!quiet) { renderAll(false); }
  }
  IAP.send = sendReply;
  function discardReply(eid, on) {
    var k = key(S.model, eid);
    if (on) { S.seq += 1; S.discarded[k] = S.seq; } else { delete S.discarded[k]; }
    S.editing = false;
    renderAll(false);
  }
  /* The list's arrow keys: up and down open the email above or below in the list as it stands. */
  function step(by) {
    var ids = $$("#mrows .mrow").map(function (r) { return r.getAttribute("data-mail"); });
    var at = ids.indexOf(S.email), next = ids[Math.max(0, Math.min(ids.length - 1, (at < 0 ? 0 : at + by)))];
    if (next && next !== S.email) {
      select(next, false);
      var row = $("#mrows .mrow.sel");
      if (row && row.focus) { row.focus(); }
    }
  }

  /* ------------------------------------------------------------------ the replay */
  /* The morning plays from 7:00. Each email arrives at its time, its steps land one model turn at a time at the pace
     the model took (sped up), its decisions and reply land, and its card moves to its lane. The quiet minutes between
     emails pass in under a second. Every beat is a timer, so pausing keeps the place and skipping runs the rest at once. */
  function setClock(m) {
    var c = $("#clock");
    if (c) { c.textContent = clock12(hhmm(m)); }
  }
  function plan() {
    var ev = [], prev = minutes((IA.morning || {}).from || "07:00");
    EMAILS.forEach(function (e) {
      var run = runOf(S.model, e.id);
      if (!run) { return; }
      var at = minutes(e.at), from = prev;
      for (var k = 1; k <= 6; k++) {
        ev.push({wait: 90, fn: (function (m) { return function () { R.clock = m; setClock(m); }; })(from + (at - from) * k / 6)});
      }
      ev.push({wait: 60, fn: function () { arrive(e); }});
      var shown = 0;
      run.turns.forEach(function (t) {
        if (t.steps.length) {
          shown += t.steps.length;
          ev.push({ms: t.ms, fn: (function (n, first) { return function () { R.steps = n; R.fresh = first; renderDrawer(false); }; })(shown, t.steps[0])});
        }
        if (t.finish) { ev.push(t.steps.length ? {wait: 200, fn: function () { finishEmail(e); }} : {ms: t.ms, fn: function () { finishEmail(e); }}); }
      });
      if (!run.turns.some(function (t) { return t.finish; })) { ev.push({wait: 200, fn: function () { finishEmail(e); }}); }
      ev.push({wait: 650, fn: function () { settle(e); }});
      prev = at;
    });
    ev.push({wait: 500, fn: function () { endReplay(false); }});
    return ev;
  }
  function arrive(e) {
    R.current = e.id;
    R.steps = 0;
    R.lane = "handled";
    S.email = e.id;
    S.editing = false;
    renderBoard();
    renderDrawer(true);
  }
  function finishEmail(e) {
    R.steps = runOf(S.model, e.id).steps.length;
    R.finished[e.id] = true;
    renderDrawer(false);
  }
  function settle(e) {
    var before = positions();
    R.done[e.id] = true;
    R.current = null;
    renderSummary();
    renderBoard();
    glide(before);
    renderDrawer(false);
  }
  function tick() {
    if (!R || R.paused) { return; }
    var next = R.queue[R.at];
    if (!next) { return; }
    var wait = next.ms !== undefined ? Math.max(120, Math.round(next.ms / S.speed)) : next.wait;
    R.timer = win.setTimeout(function () {
      if (!R || R.paused) { return; }
      R.at += 1;
      next.fn();
      tick();
    }, wait);
  }
  function startReplay() {
    stopTour();
    if (R) { endReplay(false); }
    S.sheet = null;
    S.editing = false;
    renderSide();
    showHow(false);
    R = {queue: [], at: 0, done: {}, finished: {}, current: null, steps: 0, paused: false, timer: 0, clock: 0};
    R.queue = plan();
    setClock(minutes((IA.morning || {}).from || "07:00"));
    replayButtons();
    renderSummary();
    renderBoard();
    renderDrawer(false);
    if (phone()) { toScreen("board", true); }
    tick();
  }
  IAP.startReplay = startReplay;
  function pauseReplay() {
    if (!R) { return; }
    if (R.paused) {
      R.paused = false;
      replayButtons();
      tick();
      return;
    }
    R.paused = true;
    if (R.timer) { win.clearTimeout(R.timer); }
    replayButtons();
  }
  IAP.pauseReplay = pauseReplay;
  function endReplay(rest) {
    if (!R) { return; }
    if (R.timer) { win.clearTimeout(R.timer); }
    R = null;
    setClock(minutes((IA.morning || {}).to || "09:30"));
    replayButtons();
    renderAll(false);
    if (rest !== false) { writeHash(); }
  }
  IAP.skipReplay = function () { endReplay(true); };
  IAP.replay = function () { return R ? {at: R.at, of: R.queue.length, current: R.current, done: Object.keys(R.done).filter(function (k) { return R.done[k]; }).length, paused: R.paused} : null; };
  function replayButtons() {
    var play = $("#play"), label = $("#play-label"), skip = $("#skip"), speed = $("#speed");
    var t = U.replay || {};
    if (label) {
      label.innerHTML = !R ? "<span class='long'>" + esc(t.play) + "</span><span class='short'>" + esc(t.play_short) + "</span>" :
        esc(R.paused ? t.resume : t.pause);
    }
    if (play) { play.classList.toggle("paused", !!(R && R.paused)); }
    if (skip) { skip.hidden = !R; }
    if (speed) {
      speed.textContent = S.speed + "×";
      speed.setAttribute("title", tw("replay", "speed_title", {n: S.speed}));
    }
  }
  function cycleSpeed() {
    S.speed = SPEEDS[(SPEEDS.indexOf(S.speed) + 1) % SPEEDS.length];
    replayButtons();
  }

  /* ------------------------------------------------------------------ views */
  function renderAll(animate) {
    renderSummary();
    renderBoard();
    renderDrawer(animate);
    renderSide();
    ruleLines();
    var sel = $("#model");
    if (sel) { sel.value = S.model; }
    if (T.face) { T.face(); }
  }
  function select(eid, toDrawer) {
    if (!BYID[eid]) { return; }
    if (R) { endReplay(true); }
    var same = eid === S.email;
    S.email = eid;
    S.editing = false;
    T.hot = null;
    T.litAct = null;
    pop(null);
    $$("#mrows .mrow").forEach(function (r) {
      var on = r.getAttribute("data-mail") === eid;
      r.classList.toggle("sel", on);
      r.setAttribute("aria-pressed", on ? "true" : "false");
    });
    $$("#board .card").forEach(function (c) {
      var on = c.getAttribute("data-eid") === eid;
      c.classList.toggle("sel", on);
      c.setAttribute("aria-pressed", on ? "true" : "false");
    });
    renderDrawer(!same);
    if (S.sheet && !phone() && toDrawer !== false) { S.sheet = null; renderSide(); }
    if (phone() && toDrawer !== false) { toScreen(S.layout === "mail" ? "read" : "drawer", true); }
    writeHash();
  }
  IAP.select = select;
  function setModel(id) {
    if (!runOf(id, S.email) && !(IA.runs || {})[id]) { return; }
    if (R) { endReplay(false); }
    S.model = id;
    S.editing = false;
    T.hot = null;
    renderAll(true);
    writeHash();
  }
  IAP.setModel = setModel;
  function showHow(on) {
    S.view = on ? "how" : "work";
    var how = $("#how"), body = doc.body;
    if (how) { how.hidden = !on; }
    if (body && body.classList) { body.classList.toggle("mode-how", on); body.classList.toggle("mode-work", !on); }
    var hl = $("#how-link");
    if (hl) { hl.setAttribute("aria-pressed", on ? "true" : "false"); }
    if (on) {
      if (R) { endReplay(false); }
      loadCode();
      ruleLines();
      timeOut();
      if (win.scrollTo) { win.scrollTo(0, 0); }
    } else { soonTour(); }
    writeHash();
  }
  IAP.view = function () { return S.view; };
  IAP.showHow = showHow;

  /* ------------------------------------------------------------------ the morning in time */
  function timeOut() {
    var out = $("#time-out");
    if (!out) { return; }
    var num = function (id, d) { var el = $("#" + id), v = el ? parseFloat(el.value) : NaN; return isNaN(v) || v < 0 ? d : v; };
    var hand = num("time-hand", 4), appr = num("time-approval", 2), check = num("time-check", 1);
    var w = waitingAll().length, handled = 0, sec = 0;
    EMAILS.forEach(function (e) {
      var ev = evaluate(S.model, e.id);
      if (!ev) { return; }
      sec += ev.run.usage.seconds || 0;
      if (ev.lane === "handled") { handled += 1; }
    });
    var person = Math.round((w * appr + handled * check) * 10) / 10;
    var a = w === 1 ? tw("time", "approvals.one", {}) : tw("time", "approvals.many", {n: w});
    var c = handled === 1 ? tw("time", "checks.one", {}) : tw("time", "checks.many", {n: handled});
    /* Each sentence takes a line of its own. Its numbers follow the boxes above, so its words can't be fitted to the
       panel the way the rest of How it works is, and one sentence wrapped after the other left a word alone. */
    out.innerHTML = "<span>" + esc(tw("time", "hand", {hand: f1(hand * EMAILS.length)})) + "</span> <span>" +
      esc(tw("time", "agent", {person: f1(person), approvals: a, checks: c, secs: Math.round(sec)})) + "</span>";
  }
  IAP.timeOut = function () { timeOut(); return ($("#time-out") || {}).textContent; };

  /* ------------------------------------------------------------------ the code view */
  function loadCode() {
    if (win.IACODE) { codeTree(); return; }
    if (S.codeLoading) { return; }
    S.codeLoading = true;
    var s = doc.createElement("script");
    s.src = "code.js";
    s.onload = codeTree;
    if (doc.body && doc.body.appendChild) { doc.body.appendChild(s); }
  }
  function codeTree() {
    var tree = $("#code-tree"), code = win.IACODE;
    if (!tree || !code) { return; }
    var folder = null, out = "";
    Object.keys(code.files).sort(function (a, b) {
      var da = a.indexOf("/") >= 0, db = b.indexOf("/") >= 0;
      return da !== db ? (da ? 1 : -1) : a < b ? -1 : a > b ? 1 : 0;
    }).forEach(function (rel) {
      var top = rel.indexOf("/") >= 0 ? rel.split("/")[0] + "/" : "";
      if (top !== folder) { folder = top; if (top) { out += "<p>" + esc(top) + "</p>"; } }
      out += "<button type='button' data-file='" + esc(rel) + "'>" + esc(rel.slice(top.length)) + "</button>";
    });
    tree.innerHTML = out;
    openFile(S.codeFile || code["default"]);
  }
  function openFile(rel) {
    var code = win.IACODE;
    S.codeFile = rel;
    if (!code || !code.files[rel]) { return; }
    var p = $("#code-path"), b = $("#code-body");
    if (p) { p.textContent = rel; }
    if (b) { b.textContent = code.files[rel]; }
    $$("#code-tree button, .cfeat").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-file") === rel); });
  }
  IAP.openFile = openFile;

  /* ------------------------------------------------------------------ the phone screens */

  function markScreen(name) {
    S.screen = name;
    $$("[data-screen]").forEach(function (b) {
      var on = b.getAttribute("data-screen") === name;
      b.classList.toggle("on", on);
      b.setAttribute("aria-current", on ? "true" : "false");
    });
  }
  function toScreen(name, smooth) {
    var list = screensNow();
    if (list.indexOf(name) < 0) { return; }
    markScreen(name);
    var work = $(S.layout === "mail" ? "#mail" : "#work");
    if (!phone() || !work || !work.clientWidth) { return; }
    var left = list.indexOf(name) * work.clientWidth;
    if (work.scrollTo) { work.scrollTo({left: left, behavior: smooth && !calm() ? "smooth" : "auto"}); }
    else { work.scrollLeft = left; }
  }
  IAP.toScreen = toScreen;
  IAP.screen = function () { return S.screen; };
  function screenSeen() {
    var work = $(S.layout === "mail" ? "#mail" : "#work");
    if (!phone() || !work || !work.clientWidth) { return; }
    var name = screensNow()[Math.max(0, Math.min(2, Math.round(work.scrollLeft / work.clientWidth)))];
    if (name !== S.screen) { markScreen(name); }
  }

  /* ------------------------------------------------------------------ the tour */
  /* Each step starts from the state the tour began in, so going back and forth always lands the same way, and
     leaving the tour puts everything back. */
  function snapshot() {
    return {model: S.model, email: S.email, limits: copy(S.limits), switches: copy(S.switches), decisions: copy(S.decisions),
      seq: S.seq, sheet: S.sheet, view: S.view, text: copy(S.text), raw: copy(S.raw), editing: S.editing,
      layout: S.layout, folder: S.folder, q: S.q, sent: copy(S.sent), discarded: copy(S.discarded)};
  }
  function restore(s) {
    S.model = s.model; S.email = s.email; S.limits = copy(s.limits); S.switches = copy(s.switches);
    S.decisions = copy(s.decisions); S.seq = s.seq; S.sheet = s.sheet; S.text = copy(s.text); S.raw = copy(s.raw);
    S.editing = s.editing;
    S.folder = s.folder || "inbox"; S.q = s.q || ""; S.sent = copy(s.sent || {});
    S.discarded = copy(s.discarded || {});
    var q = $("#q");
    if (q) { q.value = S.q; }
    if (s.layout && s.layout !== S.layout) { setLayout(s.layout, true); }
  }
  function base(eid, view) {
    restore(S.snap);
    S.model = IA.route || S.model;
    S.limits = copy(DEF.limits);
    S.switches = copy(DEF.switches);
    S.decisions = {};
    S.text = {};
    S.raw = {};
    S.editing = false;
    S.sheet = null;
    S.folder = "inbox";
    S.q = "";
    S.sent = {};
    S.discarded = {};
    var q = $("#q");
    if (q) { q.value = ""; }
    if (S.layout !== "mail") { setLayout("mail", true); }
    if (eid) { S.email = eid; }
    if (view === "how") { showHow(true); } else if (S.view !== "work") { showHow(false); }
    renderAll(false);
    if (phone() && view !== "how") { toScreen(view || "read", false); }
  }
  function reveal(el) {
    if (!el || !el.getBoundingClientRect) { return; }
    var style = win.getComputedStyle;
    for (var p = el.parentElement; p && p !== doc.body; p = p.parentElement) {
      if (style && p.scrollHeight > p.clientHeight + 4 && /auto|scroll/.test(style(p).overflowY)) {
        var r = el.getBoundingClientRect(), q = p.getBoundingClientRect();
        p.scrollTop += r.top - q.top - Math.max(0, (q.height - r.height) / 2);
        return;
      }
    }
    if (S.view === "how" && win.scrollTo) {
      var b = el.getBoundingClientRect();
      win.scrollTo(0, (win.scrollY || 0) + b.top - Math.max(0, ((win.innerHeight || 0) - b.height) / 2) + 60);
    }
  }
  function spot(sel) {
    $$(".spot").forEach(function (x) { x.classList.remove("spot"); });
    var el = typeof sel === "string" ? $(sel) : sel;
    if (el) { el.classList.add("spot"); reveal(el); }
    return el;
  }
  STEPS = [
    function () { base("m05", "list"); spot("#mrows"); },
    function () { base("m05", "list"); spot("#mrows [data-mail='m05']"); },
    function () { base("m05", "panel"); spot("#panel-body #sec-decisions"); },
    function () { base("m05", "panel"); spot("#panel-body #sec-did"); },
    function () { base("m05", "read"); spot("#draft"); },
    function () { base("m05", "read"); addSample("promise"); spot("#draft"); },
    function () { base("m11", "read"); spot("#read-body #sec-email"); },
    function () {
      base("m05", "list");
      S.limits.credit_cap = 100;
      S.sheet = "limits";
      renderAll(false);
      spot("#mrows");
    },
    function () {
      base("m05", "panel");
      var ev = evaluate(S.model, "m05"), w = ev ? ev.waiting.filter(function (x) { return x.a.tool === "waive_fee"; })[0] : null;
      if (w) { S.seq += 1; S.decisions[key(S.model, "m05") + "|" + w.i] = {verdict: "approved", seq: S.seq}; }
      S.sheet = "log";
      renderAll(false);
      spot("#audit li.you");
    },
    function () { base("m05", "read"); spot("#draft .draft-foot"); },
    function () { base(null, "how"); spot("#how-score"); },
    function () { base(null, "how"); spot("#how-yours"); }
  ];
  function present(n) {
    var box = $("#presenter");
    if (R) { endReplay(false); }
    if (!n) { stopTour(); return; }
    if (!S.present) { S.snap = snapshot(); S.snapView = S.view; }
    S.present = n;
    STEPS[n - 1]();
    var titles = U.tour_title || {}, texts = TOUCH ? Object.assign({}, U.tour_text, U.tour_touch) : U.tour_text || {};
    box.innerHTML = "<h3>" + esc(titles[n]) + "</h3><p>" + esc(texts[n]) + "</p><div class='row'><span>" +
      esc(tw("tour", "step", {n: n, total: STEPS.length})) + "</span><button type='button' class='btn' data-tour='back'" +
      (n === 1 ? " disabled" : "") + ">" + esc(tw("tour", "back", {})) + "</button><button type='button' class='btn primary' data-tour='next'>" +
      esc(n === STEPS.length ? tw("tour", "done", {}) : tw("tour", "next", {})) + "</button><button type='button' class='btn' data-tour='exit' aria-label='" +
      esc(tw("tour", "exit", {})) + "'>✕</button></div>";
    keepIds(box);
    box.hidden = false;
    var spotEl = $(".spot");
    if (spotEl && spotEl.getBoundingClientRect && box.classList) {
      var sr = spotEl.getBoundingClientRect(), half = (win.innerWidth || 1600) * 0.5;
      box.classList.toggle("left", sr.left + sr.width * 0.5 > half && !phone());
    }
    writeHash();
    soonTour();
    var next = $("[data-tour='next']", box);
    if (next && next.focus) { next.focus(); }
  }
  IAP.present = present;
  IAP.steps = function () { return STEPS.length; };
  function stopTour() {
    if (!S.present) { return; }
    var box = $("#presenter");
    S.present = 0;
    if (box) { box.hidden = true; }
    $$(".spot").forEach(function (x) { x.classList.remove("spot"); });
    if (S.snap) {
      restore(S.snap);
      if (S.snapView === "how") { showHow(true); } else { showHow(false); }
      S.snap = null;
    }
    renderAll(false);
    writeHash();
  }
  IAP.stopTour = stopTour;
  var HOLES = 2;
  function drawTour() {
    var svg = $("#tour"), focus = S.present ? $(".spot") : null, root = doc.body;
    if (!svg) { return; }
    if (!focus || !focus.getBoundingClientRect) {
      svg.setAttribute("hidden", "");
      if (root && root.classList) { root.classList.remove("touring"); }
      T.tour = 0;
      return;
    }
    var fresh = T.tour !== S.present, W = f1(win.innerWidth || 0), H = f1(win.innerHeight || 0);
    T.tour = S.present;
    if (!$("#tour-cut", svg)) {
      var holes = "";
      for (var h = 0; h < HOLES; h++) { holes += "<rect class='hole' rx='12' fill='#000' x='0' y='0' width='0' height='0'/>"; }
      svg.innerHTML = "<defs><mask id='tour-cut' maskUnits='userSpaceOnUse'><rect class='all' fill='#fff' x='0' y='0'/>" + holes +
        "</mask></defs><rect class='shade all' x='0' y='0' mask='url(#tour-cut)'/>";
    }
    svg.removeAttribute("hidden");
    if (root && root.classList) { root.classList.add("touring"); }
    $$(".all", svg).forEach(function (r) { r.setAttribute("width", W); r.setAttribute("height", H); });
    var r = focus.getBoundingClientRect(), boxes = [{x: r.left - 8, y: r.top - 8, w: r.width + 16, h: r.height + 16}];
    var pres = $("#presenter");
    if (pres && !pres.hidden) { var p = pres.getBoundingClientRect(); boxes.push({x: p.left - 4, y: p.top - 4, w: p.width + 8, h: p.height + 8}); }
    svg.classList.toggle("glide", fresh && !calm());
    $$(".hole", svg).forEach(function (rect, i) {
      var b = boxes[i] || {x: 0, y: 0, w: 0, h: 0};
      ["x", "y", "width", "height"].forEach(function (k, j) {
        var v = f1([b.x, b.y, b.w, b.h][j]);
        rect.setAttribute(k, v);
        if (rect.style) { rect.style[k] = v + "px"; }
      });
    });
    if (fresh) { win.setTimeout(function () { svg.classList.remove("glide"); }, 650); }
  }

  /* ------------------------------------------------------------------ events */
  function stop(e) { if (e && e.preventDefault) { e.preventDefault(); } }
  doc.addEventListener("click", function (e) {
    var t = e.target, el;
    if (!t || !t.closest) { return; }
    if ((el = t.closest("[data-tour]"))) {
      var d = el.getAttribute("data-tour");
      if (d === "next") { present(S.present >= STEPS.length ? 0 : S.present + 1); }
      else if (d === "back") { present(Math.max(1, S.present - 1)); }
      else { present(0); }
      return;
    }
    if ((el = t.closest("#tour-start"))) { present(1); return; }
    if ((el = t.closest("[data-layout]"))) { if (S.view === "how") { showHow(false); } setLayout(el.getAttribute("data-layout")); return; }
    if ((el = t.closest("[data-mail]"))) { select(el.getAttribute("data-mail")); return; }
    if ((el = t.closest("[data-folder]"))) { S.folder = el.getAttribute("data-folder"); renderRail(); renderList(); return; }
    if ((el = t.closest("[data-ptab]"))) { var tab = el.getAttribute("data-ptab"); S.sheet = tab === "email" ? null : tab; renderSide(); writeHash(); return; }
    if ((el = t.closest("[data-sheet]"))) { openSheet(el.getAttribute("data-sheet"), true); return; }
    if ((el = t.closest("#send-reply"))) { sendReply(S.email); return; }
    if ((el = t.closest("#discard-reply"))) { discardReply(S.email, true); return; }
    if ((el = t.closest("[data-undo-draft]"))) { discardReply(el.getAttribute("data-undo-draft"), false); return; }
    if ((el = t.closest("#send-checked"))) { sendable().forEach(function (m) { sendReply(m.id, true); }); renderAll(false); return; }
    if ((el = t.closest("#agent-toggle"))) { doc.body.classList.toggle("panel-open"); return; }
    if ((el = t.closest("#theme"))) { setDark(!S.dark); return; }
    if ((el = t.closest("[data-decide]"))) {
      decide(el.getAttribute("data-eid"), parseInt(el.getAttribute("data-act"), 10), el.getAttribute("data-decide"));
      return;
    }
    if ((el = t.closest("[data-undo]"))) { decide(el.getAttribute("data-eid"), parseInt(el.getAttribute("data-undo"), 10), null); return; }
    if ((el = t.closest("#board .card"))) { select(el.getAttribute("data-eid")); return; }
    if ((el = t.closest(".wait-list .open"))) { select(el.getAttribute("data-eid")); return; }
    if ((el = t.closest("[data-open]"))) { select(el.getAttribute("data-open")); return; }
    if ((el = t.closest("[data-raw]"))) {
      var rk = key(S.model, S.email) + "|" + el.getAttribute("data-raw");
      S.raw[rk] = !S.raw[rk];
      renderDrawer(false);
      return;
    }
    if ((el = t.closest("[data-sample]"))) { addSample(el.getAttribute("data-sample")); return; }
    if ((el = t.closest("#edit-reply"))) {
      S.editing = !S.editing;
      renderDrawer(false);
      var area = $("#reply-edit");
      if (area && area.focus) { area.focus(); }
      return;
    }
    if ((el = t.closest("#restore-reply"))) { delete S.text[key(S.model, S.email)]; S.editing = false; renderDrawer(false); return; }
    if ((el = t.closest("[data-reset]"))) {
      if (el.getAttribute("data-reset") === "limits") { resetLimits(); }
      else { var before = positions(), was = lanes(S.model); S.decisions = {}; S.sent = {}; S.discarded = {}; afterRules(before, was); renderSide(); }
      return;
    }
    if ((el = t.closest("[data-close]"))) { S.sheet = null; renderSide(); writeHash(); return; }
    if ((el = t.closest("#open-limits"))) { openSheet("limits"); return; }
    if ((el = t.closest("#open-log"))) { openSheet("log"); return; }
    if ((el = t.closest("#play"))) { if (R) { pauseReplay(); } else { startReplay(); } return; }
    if ((el = t.closest("#skip"))) { endReplay(true); return; }
    if ((el = t.closest("#speed"))) { cycleSpeed(); return; }
    if ((el = t.closest("#how-link"))) { stop(e); stopTour(); showHow(S.view !== "how"); return; }
    if ((el = t.closest("#how-back"))) { showHow(false); return; }
    if ((el = t.closest("#home"))) { stop(e); stopTour(); showHow(false); select(S.email, false); return; }
    if ((el = t.closest("[data-file]"))) { openFile(el.getAttribute("data-file")); return; }
    if ((el = t.closest("[data-screen]"))) { toScreen(el.getAttribute("data-screen"), true); return; }
    /* On a touch screen a tap on a claim shows where it came from, a tap on a decision lights its sentence, and a tap
       anywhere else puts both out. */
    if (TOUCH) {
      if ((el = t.closest("#reply u[data-claim]"))) { pointClaim(el); return; }
      if (T.hot) { unpoint(); }
      if ((el = t.closest("#drawer-body .dec, #panel-body .dec"))) { lightAct(el.getAttribute("data-act")); return; }
      if (T.litAct !== null && T.litAct !== undefined) { lightAct(null); }
    }
  });
  doc.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || !t.getAttribute) { return; }
    if (t.getAttribute("id") === "model") { setModel(t.value); return; }
    if (t.getAttribute("data-switch")) { setSwitch(t.getAttribute("data-switch"), !!(t.checked === undefined ? t.hasAttribute("checked") : t.checked)); return; }
    if (t.getAttribute("data-limit")) { setLimit(t.getAttribute("data-limit"), parseFloat(t.value)); }
  });
  doc.addEventListener("input", function (e) {
    var t = e.target;
    if (!t || !t.getAttribute) { return; }
    if (t.getAttribute("data-limit")) { setLimit(t.getAttribute("data-limit"), parseFloat(t.value)); return; }
    if (t.getAttribute("id") === "reply-edit") { recheck(); return; }
    if (t.getAttribute("id") === "q") { S.q = t.value; renderList(); return; }
    if (/^time-/.test(t.getAttribute("id") || "")) { timeOut(); }
  });
  doc.addEventListener("mouseover", function (e) {
    var t = e.target, el;
    if (!t || !t.closest) { return; }
    if ((el = t.closest("#reply u[data-claim]"))) { if (T.hot !== el) { pointClaim(el); } return; }
    if ((el = t.closest("#drawer-body .dec, #panel-body .dec"))) { lightAct(el.getAttribute("data-act")); return; }
    if (T.litAct !== null && T.litAct !== undefined && !t.closest("#drawer-body .dec, #panel-body .dec")) { lightAct(null); }
    if (T.hot && !t.closest("#reply")) { unpoint(); }
  });
  doc.addEventListener("focusin", function (e) {
    var t = e.target;
    if (t && t.closest && t.closest("#reply u[data-claim]")) { pointClaim(t.closest("#reply u[data-claim]")); }
  });
  doc.addEventListener("focusout", function (e) {
    var t = e.target;
    if (t && t.closest && t.closest("#reply u[data-claim]")) { unpoint(); }
  });
  doc.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      if (S.present) { present(0); return; }
      if (T.hot) { unpoint(); return; }
      if (doc.body.classList.contains("panel-open")) { doc.body.classList.remove("panel-open"); return; }
      if (S.sheet) { S.sheet = null; renderSide(); writeHash(); return; }
    }
    if (!S.present && S.layout === "mail" && S.view === "work" && (e.key === "ArrowDown" || e.key === "ArrowUp") &&
        e.target && e.target.closest && e.target.closest("#mrows")) {
      if (e.preventDefault) { e.preventDefault(); }
      step(e.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (S.present && (e.key === "ArrowRight" || e.key === "ArrowLeft") && !(e.target && /input|textarea|select/i.test(e.target.tagName || ""))) {
      present(e.key === "ArrowRight" ? (S.present >= STEPS.length ? 0 : S.present + 1) : Math.max(1, S.present - 1));
    }
  });
  doc.addEventListener("scroll", function (e) {
    var t = e.target;
    var sid = t && t.getAttribute ? t.getAttribute("id") : "";
    if (sid === "work" || sid === "mail") { screenSeen(); }
    if (S.layout === "mail" && (sid === "read" || sid === "panel-body")) { drawThreads(); }
    if (T.hot) { pop(null); T.hot = null; }
    soonTour();
  }, true);
  if (win.addEventListener) {
    win.addEventListener("resize", function () { renderSide(); soonTour(); });
    win.addEventListener("load", function () { drawThreads(); });
    if (doc.fonts && doc.fonts.ready) { doc.fonts.ready.then(function () { drawThreads(); }); }
    win.addEventListener("hashchange", function () { route(readHash(win.location.hash)); });
  }

  /* ------------------------------------------------------------------ start */
  function route(h) {
    if (h.tour) { present(h.tour); return; }
    if (S.present) { stopTour(); }
    if (h.how) { showHow(true); return; }
    if (h.layout && h.layout !== S.layout) { setLayout(h.layout, true); }
    if (h.model && (IA.runs || {})[h.model]) { S.model = h.model; }
    if (h.email && BYID[h.email]) { S.email = h.email; }
    if (h.sheet !== undefined) { S.sheet = h.sheet; }
    if (S.view !== "work") { showHow(false); }
    renderAll(true);
  }
  /* On a touch screen the model list shows a face of its own at the top bar's size. The real list sits invisible on top
     of the face at 16px, so a phone doesn't zoom the page when it's tapped, and takes the tap (app.css). */
  function modelFace() {
    var mp = $("#model"), box = mp && mp.parentNode;
    if (!TOUCH || !box || !box.classList || $(".model-face", box)) { return; }
    var face = doc.createElement("span");
    face.className = "model-face";
    face.setAttribute("aria-hidden", "true");
    box.classList.add("faced");
    box.appendChild(face);
    var show = function () { var o = mp.options[mp.selectedIndex]; face.textContent = o ? o.text : ""; };
    mp.addEventListener("change", show);
    T.face = show;
    show();
  }
  function begin() {
    /* The mailbox's address comes from here and not the HTML, where Cloudflare would rewrite it to hide it. */
    var addr = $("#conn-address");
    if (addr) { addr.textContent = tw("mail", "address", {}); }
    modelFace();
    replayButtons();
    setClock(minutes((IA.morning || {}).to || "09:30"));
    var first = readHash((win.location || {}).hash || "");
    setLayout(first.layout || "mail", true);
    route(first);
  }
  IAP.state = function () {
    return {model: S.model, email: S.email, view: S.view, sheet: S.sheet, present: S.present, limits: copy(S.limits),
      switches: copy(S.switches), decisions: Object.keys(S.decisions).length, editing: S.editing, speed: S.speed,
      replay: !!R, screen: S.screen, layout: S.layout, folder: S.folder, sent: Object.keys(S.sent).length,
      discarded: Object.keys(S.discarded).length, dark: S.dark};
  };
  begin();
})();
