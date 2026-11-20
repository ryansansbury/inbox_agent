/* The node click-through. It runs the built page's own scripts against a small DOM (dom.js) and opens every email for
   every model, checks that every decision has a sentence to land on, opens a raw call, moves the credit cap and
   watches three cards move, flips both switches, approves and denies and undoes, adds every sample bad claim and
   types a promise, plays the whole replay and pauses it partway, opens How it works and the code view, walks every
   tour step forward and back and checks that leaving puts everything back, and on a stand-in phone moves between the
   three screens. Exits 1 on any failed check.

       node tests/js/check_app.js [site folder]

   It can't see layout, color, motion or real timing. owner/browser_check.py covers those in real Chrome. */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const {Document, Element} = require("./dom.js");

/* The live page's security policy allows no inline style or script, so every piece of markup the script writes is
   watched for a style attribute, an inline handler or a javascript: address. */
const inlineSeen = [];
const markup = Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML");
Object.defineProperty(Element.prototype, "innerHTML", {
  configurable: true,
  get() { return markup.get.call(this); },
  set(v) {
    const m = /<[^>]*\s(?:style|on[a-z]+)\s*=|javascript:/i.exec(String(v));
    if (m) { inlineSeen.push(String(v).slice(Math.max(0, m.index - 20), m.index + 60)); }
    markup.set.call(this, v);
  },
});

const SITE = path.resolve(process.argv[2] || path.join(__dirname, "..", "..", "site"));
const checks = [], errors = [];
function check(name, ok, detail) { checks.push({name, ok: !!ok, detail: detail === undefined ? "" : String(detail).slice(0, 300)}); }

const html = fs.readFileSync(path.join(SITE, "index.html"), "utf8");
const doc = new Document(html);
check("index.html parses with every tag closed", doc.errors.length === 0, doc.errors.slice(0, 3).join("; "));
check("no script, style or font comes from another site", !/(?:src|href)=['"](?:https?:)?\/\/(?!(?:www\.)?ryansansbury\.com|github\.com)/.test(html));
check("no inline script or style", !/<script>(?!<\/script>)|<script[^>]*>[^<]+<\/script>| style=/.test(html));
check("the HTML holds no email address, so Cloudflare's email hiding leaves the page as built",
  !/[\w.+-]+@[\w-]+\.[\w.-]+/.test(html.replace(/<script[^>]*>[^<]*<\/script>/g, "")));
check("the page has a description for search", /<meta name='description' content='[^']{40,}'>/.test(html));
let phoneMode = false;
const timers = [];
const win = {document: doc, innerWidth: 1600, innerHeight: 1000, addEventListener() {}, devicePixelRatio: 1,
  setTimeout(fn) { timers.push(fn); return timers.length; }, clearTimeout(id) { if (id) { timers[id - 1] = null; } },
  location: {hash: "#board", protocol: "file:"}, history: {replaceState(s, t, url) { win.location.hash = url; }},
  scrollX: 0, scrollY: 0, matchMedia(q) { return {matches: phoneMode && /max-width: 900px/.test(q)}; }};
win.window = win;
const ctx = vm.createContext(win);
for (const name of ["policy.js", "replies.js", "data.js", "code.js", "app.js"]) {
  try { vm.runInContext(fs.readFileSync(path.join(SITE, name), "utf8"), ctx, {filename: name}); }
  catch (e) { errors.push(name + " threw: " + (e && e.stack || e)); }
}
function flush(limit) {
  let n = 0;
  for (let guard = 0; guard < (limit || 20000) && timers.some(Boolean); guard++) {
    const i = timers.findIndex(Boolean), fn = timers[i];
    timers[i] = null;
    fn();
    n += 1;
  }
  return n;
}
const IA = win.IA, IAP = win.IAP;
const click = (el) => doc.dispatch("click", el);
const change = (el, value, checked) => {
  if (value !== undefined) { el.value = value; }
  if (checked !== undefined) { if (checked) { el.setAttribute("checked", ""); } else { el.removeAttribute("checked"); } el.checked = checked; }
  doc.dispatch("change", el);
};
const input = (el, value) => { el.value = value; doc.dispatch("input", el); };
const $ = (sel) => doc.querySelector(sel);
const $$ = (sel) => doc.querySelectorAll(sel);
const laneOf = (eid) => { const c = $(`#board [data-eid='${eid}']`); return c ? c.closest(".lane") && c.closest(".lane").getAttribute("data-lane") : null; };
const counts = () => Object.fromEntries(["needs_you", "handled", "customer", "stopped"].map((k) => [k, $$(`#cards-${k} .card`).length]));
function attempt(name, fn) { try { fn(); } catch (e) { errors.push(name + ": " + (e && e.stack || e)); } }

if (IA && IAP) {
  const route = IA.route;
  attempt("opening", () => {
    flush();
    const st = IAP.state();
    check("the page opens on the rush order with the routed model", st.email === "m05" && st.model === route, st.email + " " + st.model);
    check("the board shows all twelve emails", $$("#board .card").length === 12, $$("#board .card").length);
    const c = counts();
    check("the routed model's morning lands 5 handled, 3 need you, 2 on the customer and 2 stopped",
      c.handled === 5 && c.needs_you === 3 && c.customer === 2 && c.stopped === 2, JSON.stringify(c));
    check("the rush order's card is selected", $("#board [data-eid='m05']").classList.contains("sel"));
    check("the summary has a pill for every lane", $$("#summary .pill").length === 4);
    check("the summary counts the money that went through inside the limits", /^\$[\d,]+\.\d\d$/.test($("#money").textContent), $("#money").textContent);
    check("the clock shows the end of the morning", $("#clock").textContent === "9:30 AM", $("#clock").textContent);
    check("the model picker lists every model", $$("#model option").length === IA.models.length);
    const loose = (root) => {
      const out = [];
      (function walk(n) {
        for (const k of n.childNodes) {
          if (k.nodeType === 3 && /\b[A-Z0-9]+-[A-Z0-9]/.test(k.data) && !(n.closest && n.closest(".nw, textarea, option"))) { out.push(k.data.trim().slice(0, 40)); }
          else if (k.nodeType === 1) { walk(k); }
        }
      })(root);
      return out;
    };
    const ids = loose($("#board")).concat(loose($("#drawer-body")));
    check("every ID on the board and in the drawer sits in a span that keeps it on one line", !ids.length, ids.slice(0, 3).join(" | "));
    check("the rush order's card keeps its order number whole", /<span class=['"]nw['"]>SO-20852<\/span>/.test($("#board [data-eid='m05']").innerHTML));
    check("How it works keeps GPT-6 whole in its prose and leaves the model menu alone",
      /<span class='nw'>GPT-6<\/span> Luna/.test(html) && /<option value='openai-luna'>GPT-6 Luna<\/option>/.test(html));
  });
  attempt("every email for every model", () => {
    let ok = 0, total = 0, lost = [];
    for (const m of IA.models) {
      change($("#model"), m.id);
      flush();
      for (const e of IA.emails) {
        total += 1;
        click($(`#board [data-eid='${e.id}']`));
        flush();
        const body = $("#drawer-body");
        const parts = ["#sec-email", "#sec-did", "#sec-decisions", "#sec-reply", "#sec-key"].every((s) => body.querySelector(s));
        if (parts && IAP.state().email === e.id && body.innerHTML.length > 400) { ok += 1; }
        IAP.linkPlan().filter((x) => !x.found).forEach((x) => lost.push(`${m.id} ${e.id} decision ${x.dec}`));
        const steps = body.querySelectorAll("#trace .step").length;
        if (steps !== IA.runs[m.id][e.id].steps.length) { lost.push(`${m.id} ${e.id} shows ${steps} steps`); }
      }
    }
    check("every email opens with its email, steps, decisions, reply and key for every model", ok === total, `${ok} of ${total}`);
    check("every decision names a sentence that's on the page, and every step shows", lost.length === 0, lost.slice(0, 4).join("; "));
    check("the drawer draws no connector lines", !$("#drawer svg"));
    change($("#model"), route);
    flush();
  });
  attempt("the rush order", () => {
    click($("#board [data-eid='m05']"));
    flush();
    const decs = $$("#sec-decisions .dec");
    check("the rush order has two decisions", decs.length === 2, decs.length);
    check("the order went through and the fee waiver waits", decs[0].classList.contains("done") && decs[1].classList.contains("waiting"));
    check("the waiting waiver has approve and deny", decs[1].querySelector("[data-decide='approved']") && decs[1].querySelector("[data-decide='denied']"));
    check("each decision points at its sentence", decs[0].getAttribute("data-to") === "2" && decs[1].getAttribute("data-to") === "3");
    check("the sentences the actions answer are marked in the email", $$("#sec-email .s.hit").length === 2);
    check("the reply is checked with every claim backed", $$("#reply u").length > 4 && $$("#reply u.unsupported, #reply u.premature").length === 0,
      $$("#reply u").length);
    click($("#trace [data-raw='0']"));
    flush();
    const raw = $("#trace .raw");
    check("a step opens to its raw call", raw && /get_customer/.test(raw.textContent) && /customer_id/.test(raw.textContent));
    click($("#trace [data-raw='0']"));
    flush();
    check("and closes again", !$("#trace .raw"));
    const c = IAP.claims("m05")[0];
    const src = IAP.sourceOf("m05", c);
    check("a claim in the reply traces to where it came from", src && (src.kind === "step" || src.kind === "email"), JSON.stringify(src));
  });
  attempt("the limits", () => {
    const before = counts();
    click($("#open-limits"));
    flush();
    check("the limits open as a sheet", $("#side").classList.contains("open") && $$("#side input[type='range']").length === 6);
    input($("#lim-credit_cap"), "100");
    flush();
    const after = counts();
    check("lowering the credit cap to $100 moves three emails to Needs you", after.needs_you === before.needs_you + 3 &&
      ["m02", "m07", "m08"].every((id) => laneOf(id) === "needs_you"), JSON.stringify(after));
    check("the summary says how many moved", /3/.test(($("#moved-line") || {textContent: ""}).textContent), ($("#moved-line") || {textContent: ""}).textContent);
    check("the sheet says it too", /3/.test($("#limits-moved").textContent));
    click($("#board [data-eid='m02']"));
    flush();
    check("the credit now waits for a person", $("#sec-decisions .dec.waiting") !== null);
    check("the decision says the recording differed", $("#sec-decisions .changed") !== null);
    check("the reply drafted under the defaults is held, since it calls the credit done", $$("#reply u.premature").length >= 1,
      $$("#reply u").map((u) => u.className).join(","));
    check("the drawer says the reply was drafted under the default limits", $$("#sec-reply .banner").length === 1);
    click($("[data-reset='limits']"));
    flush();
    check("reset puts every card back", JSON.stringify(counts()) === JSON.stringify(before), JSON.stringify(counts()));
    IAP.openSheet("limits", true);
    flush();
    input($("#lim-fee_waiver_cap"), "100");
    flush();
    check("raising the fee waiver cap lets the rush fee through", laneOf("m05") === "handled", laneOf("m05"));
    IAP.resetLimits();
    flush();
    IAP.openSheet("limits", true);
    flush();
    const sw = $("[data-switch='ship_to_before_pick']");
    change(sw, undefined, false);
    flush();
    check("switching off the pick rule lets the picked order's new ship-to through", laneOf("m04") === "handled", laneOf("m04"));
    IAP.resetLimits();
    flush();
    IAP.openSheet("limits", true);
    flush();
    change($("[data-switch='orders_within_credit']"), undefined, false);
    flush();
    check("switching off the credit line rule lets the holiday order through", laneOf("m09") === "handled", laneOf("m09"));
    IAP.resetLimits();
    flush();
    IAP.openSheet("limits", true);
    flush();
    input($("#lim-return_days"), "5");
    flush();
    check("a shorter return window blocks the return", /blocked/.test(IAP.didLine("m08").html), IAP.didLine("m08").html);
    IAP.resetLimits();
    flush();
    check("reset again leaves nothing moved", IAP.moved().length === 0);
  });
  attempt("approvals and the log", () => {
    IAP.select("m05");
    flush();
    const waitingBefore = IAP.waiting().length;
    click($("#sec-decisions [data-decide='approved']"));
    flush();
    check("approving the waiver moves the rush order to Handled", laneOf("m05") === "handled", laneOf("m05"));
    check("the decision shows who approved it", /Hazel Garrity/.test($("#sec-decisions .decided").textContent));
    check("one fewer thing waits", IAP.waiting().length === waitingBefore - 1, IAP.waiting().join(","));
    click($("#open-log"));
    flush();
    const rows = $$("#audit li");
    check("the log opens as a sheet with every action", rows.length > 20, rows.length);
    check("the log records the approval and who made it", rows[rows.length - 1].classList.contains("you") &&
      /Hazel Garrity/.test(rows[rows.length - 1].textContent), rows[rows.length - 1].textContent);
    check("the log lists what still waits", $$("#wait-list li").length === waitingBefore - 1);
    const holiday = IAP.waiting().indexOf("m09:create_order") >= 0;
    click($("#wait-list [data-decide='denied']"));
    flush();
    check("denying from the log resolves it too", IAP.waiting().length === waitingBefore - 2 && holiday);
    click($("[data-reset='decisions']"));
    flush();
    check("undoing the decisions puts the cards back", laneOf("m05") === "needs_you" && IAP.waiting().length === waitingBefore);
    click($("[data-close='sheet']"));
    flush();
    check("the sheet closes", !$("#side").classList.contains("open"));
  });
  attempt("the reply checker", () => {
    IAP.select("m05");
    flush();
    const kinds = $$("[data-sample]").map((b) => b.getAttribute("data-sample"));
    check("the rush order offers all four sample bad claims", kinds.join(",") === "money,date,promise,pending", kinds.join(","));
    for (const k of kinds) {
      click($("#restore-reply") || $("#edit-reply"));
      flush();
      if (IAP.state().editing) { click($("#edit-reply")); flush(); }
      click($(`[data-sample='${k}']`));
      flush();
      check(`the sample "${k}" is flagged`, $$("#findings li").length >= 1 && $$("#reply u.unsupported, #reply u.premature").length >= 1,
        $("#reply").textContent.slice(-120));
    }
    click($("#restore-reply"));
    flush();
    check("putting the agent's reply back clears the flags", !$("#findings"));
    click($("#edit-reply"));
    flush();
    const area = $("#reply-edit");
    check("editing opens the reply as text", area && area.value.length > 50);
    input(area, area.value + " We have also refunded your last order.");
    check("a typed promise is flagged as you type", /refund/i.test($$("#findings li").map((x) => x.textContent).join(" ")),
      $$("#findings li").map((x) => x.textContent).join(" | "));
    click($("#edit-reply"));
    flush();
    click($("#restore-reply"));
    flush();
    let clean = 0, total = 0;
    for (const m of IA.models) {
      for (const e of IA.emails) {
        if (!IA.runs[m.id][e.id].finish.reply) { continue; }
        total += 1;
        const bad = IAP.claims(e.id, undefined, m.id).filter((c) => c.status !== "supported").length;
        const scored = (IA.runs[m.id][e.id].score || {}).claims || {};
        if (bad === (scored.unsupported || 0) + (scored.premature || 0)) { clean += 1; }
      }
    }
    check("the page's checker agrees with the scores on every recorded reply", clean === total, `${clean} of ${total}`);
  });
  attempt("the hidden instruction", () => {
    IAP.select("m11");
    flush();
    check("the planted sentences are flagged in the email", $$("#sec-email .s.flag").length === 2, $$("#sec-email .s.flag").length);
    check("the forwarded thread is set apart", $$("#sec-email .fwd").length === 1);
    check("the page shows what the limits would have said", /4,782\.00/.test(($("#what-if") || {textContent: ""}).textContent));
    check("the card sits in Stopped", laneOf("m11") === "stopped");
    IAP.select("m10");
    flush();
    check("the look-alike sender is marked unverified", $("#sec-email .warn") !== null);
    check("the look-alike email goes to security", /security/i.test(IAP.didLine("m10").html));
  });
  attempt("the other models", () => {
    const luna = IA.models.filter((m) => m.id === "openai-luna")[0];
    if (!luna) { return; }
    change($("#model"), luna.id);
    flush();
    check("switching models re-lays the board", IAP.state().model === luna.id && $$("#board .card").length === 12);
    check("a run that differs from the answer key says so on its card", $$("#board .card .differs").length >= 1, $$("#board .card .differs").length);
    change($("#model"), route);
    flush();
    check("the routed model's cards all match the key", $$("#board .card .differs").length === 0);
  });
  attempt("the replay", () => {
    IAP.select("m05");
    flush();
    click($("#play"));
    check("the replay starts from an empty board at 7:00", $$("#board .lanes .card").length === 0 && $("#clock").textContent === "7:00 AM",
      $$("#board .lanes .card").length + " " + $("#clock").textContent);
    for (let k = 0; k < 80 && !(IAP.replay() && IAP.replay().current === "m01"); k++) { flush(1); }
    const mid = IAP.replay();
    check("the first email arrives and works in the strip", mid && mid.current === "m01" && !$("#incoming").hidden && $$("#cards-incoming .card.working").length === 1,
      JSON.stringify(mid));
    flush(30);
    const shown = IAP.replay();
    click($("#play"));
    const paused = IAP.replay();
    const ran = flush(200);
    check("pause holds the place", paused && paused.paused && IAP.replay().at === paused.at, JSON.stringify(IAP.replay()) + " ran " + ran);
    click($("#play"));
    flush();
    check("the replay plays to the end and the morning is whole", IAP.replay() === null && $$("#board .lanes .card").length === 12 &&
      $("#clock").textContent === "9:30 AM", $$("#board .lanes .card").length + " " + $("#clock").textContent);
    check("it had settled emails along the way", shown && shown.done >= 1, JSON.stringify(shown));
    click($("#play"));
    flush(25);
    click($("#skip"));
    flush();
    check("skip to the end lands the whole morning", IAP.replay() === null && $$("#board .lanes .card").length === 12);
    click($("#speed"));
    check("the speed toggles", IAP.state().speed === 4 && $("#speed").textContent === "4×");
    click($("#speed"));
    click($("#speed"));
    check("the speed comes back round to 2×", IAP.state().speed === 2);
    click($("#theme"));
    check("the dark mode button turns dark mode on and says so", IAP.state().dark === true &&
      doc.body.classList.contains("dark") && $("#theme").getAttribute("aria-pressed") === "true");
    click($("#theme"));
    check("and off again, back to the light default", IAP.state().dark === false && !doc.body.classList.contains("dark"));
  });
  attempt("how it works and the code", () => {
    click($("#how-link"));
    flush();
    check("How it works opens as its own view", IAP.view() === "how" && !$("#how").hidden);
    for (const id of ["how-map", "how-tools", "how-limits", "how-inject", "how-checker", "how-method", "how-score", "how-compare",
      "how-runs", "how-time", "how-yours", "how-privacy", "how-cant", "how-code"]) {
      check(`How it works has ${id}`, $("#" + id) !== null);
    }
    check("the scoreboard has a row for every model", $$("#how-score tbody tr").length === IA.models.length);
    check("the limits read as sentences, the four caps in one", $$("#rule-lines li").length === 6 &&
      /\$250/.test($("#rule-lines li").textContent) && /\$2,500/.test($("#rule-lines li").textContent), $$("#rule-lines li").length);
    check("the code view lists the files", $$("#code-tree button").length > 30, $$("#code-tree button").length);
    check("five featured files sit in one row", $$(".feats .cfeat").length === 5);
    click($(".cfeat[data-file='engine/replies.py']"));
    check("a featured file opens", $("#code-path").textContent === "engine/replies.py" && /def check/.test($("#code-body").textContent));
    /* A file that holds markup and a script tag opens as plain text: nothing in it becomes an element or runs. */
    const files = win.IACODE.files, probe = "site/probe.html";
    files[probe] = "<script>window.ranProbe = true;</script><img src=x onerror=\"window.ranProbe = true\"><b>bold</b>";
    IAP.openFile(probe);
    flush();
    const body = $("#code-body");
    check("the code view shows a file as text, so nothing in it can run or change the page",
      body.childNodes.length === 1 && body.childNodes[0].nodeType === 3 && /<script>/.test(body.textContent) && !win.ranProbe);
    delete files[probe];
    IAP.openFile("engine/replies.py");
    flush();
    const t0 = IAP.timeOut();
    input($("#time-hand"), "6");
    check("the morning in time follows its assumptions", IAP.timeOut() !== t0 && /72/.test(IAP.timeOut()), IAP.timeOut());
    click($("#how-back"));
    flush();
    check("back goes to the morning", IAP.view() === "work");
  });
  attempt("the tour", () => {
    IAP.setLimit("restocking_pct", 20);
    IAP.select("m03");
    flush();
    const before = JSON.stringify(IAP.state());
    click($("#tour-start"));
    flush();
    const n = IAP.steps();
    let found = 0;
    for (let i = 1; i <= n; i++) {
      if (i > 1) { click($("[data-tour='next']")); flush(); }
      if ($(".spot") && /#tour-\d+/.test(win.location.hash)) { found += 1; }
      if (i === 8) {
        check("the tour's limits step relabels three emails Needs you", ["m02", "m07", "m08"].every((id) => $(`#mrows [data-mail='${id}'] .lab.l-needs_you`) !== null));
      }
      if (i === 9) { check("the tour's approval step relabels the rush order Handled", $("#mrows [data-mail='m05'] .lab.l-handled") !== null); }
    }
    check("every tour step finds its spot and has its own address", found === n, `${found} of ${n}`);
    click($("[data-tour='back']"));
    flush();
    check("the tour goes back a step", IAP.state().present === n - 1);
    click($("[data-tour='exit']"));
    flush();
    check("leaving the tour puts everything back", JSON.stringify(IAP.state()) === before, JSON.stringify(IAP.state()) + " vs " + before);
    IAP.resetLimits();
    flush();
    check("the address of a tour step opens that step", IAP.readHash("#tour-4").tour === 4);
    check("the address of an email with a sheet and a model reads back", JSON.stringify(IAP.readHash("#m05/limits@claude-haiku")) ===
      JSON.stringify({layout: "mail", email: "m05", sheet: "limits", model: "claude-haiku"}));
    check("the board's address reads back as the board", IAP.readHash("#board/m05/log").layout === "board" &&
      IAP.readHash("#board/m05/log").sheet === "log");
  });
  attempt("every model's replay, samples and decisions", () => {
    const route = IA.route;
    let replays = 0, samples = 0, flagged = 0, decided = 0, restored = 0, waits = 0;
    for (const m of IA.models) {
      change($("#model"), m.id);
      flush();
      const lanes = JSON.stringify(IAP.lanes(m.id));
      IAP.startReplay();
      flush();
      if (IAP.replay() === null && $$("#board .lanes .card").length === 12 && JSON.stringify(IAP.lanes(m.id)) === lanes) { replays += 1; }
      for (const e of IA.emails) {
        if (!IA.runs[m.id][e.id].finish.reply) { continue; }
        IAP.select(e.id);
        flush();
        for (const b of $$("[data-sample]")) {
          const kind = b.getAttribute("data-sample");
          samples += 1;
          IAP.addSample(kind);
          flush();
          if ($$("#findings li").length >= 1) { flagged += 1; }
          const back = $("#restore-reply");
          if (back) { click(back); flush(); }
        }
      }
      for (const w of IAP.waiting()) {
        const [eid, tool] = w.split(":");
        const ev = IAP.evaluate(m.id, eid);
        const x = ev.waiting.filter((y) => y.a.tool === tool)[0];
        waits += 1;
        for (const verdict of ["approved", "denied"]) {
          IAP.decide(eid, x.i, verdict);
          flush();
          if (IAP.waiting().indexOf(w) < 0) { decided += 1; }
          IAP.decide(eid, x.i, null);
          flush();
          if (IAP.waiting().indexOf(w) >= 0) { restored += 1; }
        }
      }
    }
    check("every model's replay plays to the end and lands each card where the board has it", replays === IA.models.length, `${replays} of ${IA.models.length}`);
    check("every sample bad claim on every reply of every model is flagged", samples > 0 && flagged === samples, `${flagged} of ${samples}`);
    check("every waiting action of every model can be approved and denied", decided === waits * 2, `${decided} of ${waits * 2}`);
    check("and undoing each decision puts it back", restored === waits * 2, `${restored} of ${waits * 2}`);
    change($("#model"), route);
    flush();
  });
  attempt("the agent's own words in the decisions", () => {
    IAP.select("m06");
    flush();
    check("a question to the customer shows the question", /\?/.test(($("#sec-decisions .said") || {textContent: ""}).textContent));
    IAP.select("m10");
    flush();
    check("a route to security shows the agent's summary", ($("#sec-decisions .said") || {textContent: ""}).textContent.length > 20);
    IAP.select("m05");
    flush();
    check("an order lists its items by name", /Shipping box/.test(($("#sec-decisions .detail") || {textContent: ""}).textContent));
  });
  attempt("the keyboard", () => {
    click($("#open-limits"));
    flush();
    doc.dispatch("keydown", doc.body, {key: "Escape"});
    flush();
    check("Escape closes a sheet", !$("#side").classList.contains("open"));
    click($("#tour-start"));
    flush();
    doc.dispatch("keydown", doc.body, {key: "ArrowRight"});
    flush();
    check("the right arrow moves the tour on", IAP.state().present === 2, IAP.state().present);
    doc.dispatch("keydown", doc.body, {key: "ArrowLeft"});
    flush();
    check("the left arrow moves it back", IAP.state().present === 1, IAP.state().present);
    doc.dispatch("keydown", doc.body, {key: "Escape"});
    flush();
    check("Escape leaves the tour", IAP.state().present === 0);
  });
  attempt("the phone", () => {
    phoneMode = true;
    IAP.select("m05");
    flush();
    check("on a phone, picking an email goes to the email screen", IAP.screen() === "drawer", IAP.screen());
    IAP.toScreen("side");
    flush();
    IAP.decide("m05", 1, null);
    flush();
    check("the third screen holds what waits and the limits", $("#wait-list") !== null && $("#limits") !== null);
    check("the tab bar has three screens", $$("#screens [data-screen][data-for='board']").length === 3);
    IAP.toScreen("board");
    check("the tabs move between screens", IAP.screen() === "board");
    phoneMode = false;
    IAP.select("m05");
    flush();
  });
  attempt("the mailbox", () => {
    IAP.setLayout("mail");
    flush();
    IAP.select("m05", false);
    flush();
    const st = IAP.state();
    check("the mailbox opens on the switch", st.layout === "mail" && doc.body.classList.contains("layout-mail"));
    check("the mailbox lists all twelve emails, newest first", $$("#mrows .mrow").length === 12 &&
      $$("#mrows .mrow")[0].getAttribute("data-mail") === "m12", $$("#mrows .mrow").length);
    check("the board's drawer is empty while the mailbox shows, so no id exists twice", $("#drawer-body").innerHTML === "");
    const labels = Object.fromEntries(["needs_you", "handled", "customer", "stopped"].map((k) => [k, $$(`#mrows .lab.l-${k}`).length]));
    check("the labels match the board: 5 handled, 3 need you, 2 on the customer and 2 stopped",
      labels.handled === 5 && labels.needs_you === 3 && labels.customer === 2 && labels.stopped === 2, JSON.stringify(labels));
    check("the rush order's row is selected", $("#mrows [data-mail='m05']").classList.contains("sel"));
    check("the read pane shows the email with its sentences and the agent's draft", $("#read-body h1") !== null &&
      $("#read-body #s-2") !== null && $("#read-body #draft") !== null && $("#read-body #reply") !== null);
    check("the draft says how many facts were checked", /\d+ facts checked/.test($("#draft .draft-head").textContent),
      $("#draft .draft-head").textContent);
    check("the panel shows the decisions, the steps and the limits checked", $("#panel-body #sec-decisions") !== null &&
      $("#panel-body #trace") !== null && $("#panel-body #sec-checked") !== null);
    check("the panel has three tabs and This email is open", $$("#ptabs [data-ptab]").length === 3 &&
      $("#ptabs [data-ptab='email']").getAttribute("aria-selected") === "true");
    check("the rail has the folders, the four labels and the agent's two sheets", $$("#rail [data-folder]").length === 7 &&
      $$("#rail [data-sheet]").length === 2);
    check("the strip says what the agent can and can't do", $$("#conn li.yes").length === 3 && $$("#conn li.no").length === 3);
    check("the strip names the mailbox once the script has run", $("#conn-address").textContent === "orders@wendlow.example");
    click($("#rail [data-folder='needs_you']"));
    flush();
    check("the Needs you label shows its three emails", $$("#mrows .mrow").length === 3, $$("#mrows .mrow").length);
    click($("#rail [data-folder='inbox']"));
    flush();
    input($("#q"), "sablewood");
    flush();
    check("the search finds the two Sablewood emails", $$("#mrows .mrow").length === 2, $$("#mrows .mrow").length);
    input($("#q"), "");
    flush();
    click($("#mrows [data-mail='m11']"));
    flush();
    check("clicking a row opens that email", IAP.state().email === "m11" && $("#read-body .s.flag") !== null);
    click($("#mrows [data-mail='m05']"));
    flush();
    click($("#ptabs [data-ptab='limits']"));
    flush();
    check("the limits tab shows the limits in the panel", $("#panel-body #limits") !== null && IAP.state().sheet === "limits");
    change($("#lim-credit_cap"), "100");
    flush();
    const moved = $$("#mrows .lab.l-needs_you").length;
    check("lowering the credit cap to $100 relabels three more emails Needs you", moved === 6, moved);
    IAP.resetLimits();
    flush();
    click($("#ptabs [data-ptab='log']"));
    flush();
    check("the log tab shows what waits and the audit log", $("#panel-body #wait-list") !== null && $("#panel-body #audit") !== null);
    click($("#ptabs [data-ptab='email']"));
    flush();
    const appr = $("#panel-body [data-decide='approved']");
    if (appr) { click(appr); flush(); }
    check("approving the rush fee waiver relabels the rush order Handled", $("#mrows [data-mail='m05'] .lab.l-handled") !== null);
    const before = IAP.audit().length;
    click($("#send-reply"));
    flush();
    check("sending the draft marks it sent and writes an audit row", IAP.state().sent === 1 && IAP.audit().length === before + 1 &&
      $("#draft .sent-note") !== null && $("#mrows [data-mail='m05'] .tag-sent") !== null);
    click($("#rail [data-folder='drafts']"));
    flush();
    const ready = $("#send-checked");
    check("the Drafts folder offers to send the checked replies", ready !== null);
    if (ready) { click(ready); flush(); }
    check("sending the checked replies sends every handled reply the checker passes", IAP.state().sent >= 4, IAP.state().sent);
    click($("#rail [data-folder='inbox']"));
    flush();
    IAP.select("m06", false);
    flush();
    click($("#discard-reply"));
    flush();
    check("discarding a draft keeps it out of Drafts with an undo", $("[data-undo-draft='m06']") !== null && IAP.state().discarded === 1);
    const reset = $("[data-reset='decisions']");
    IAP.select("m05", false);
    flush();
    click($("#ptabs [data-ptab='log']"));
    flush();
    if ($("#panel-body [data-reset='decisions']")) { click($("#panel-body [data-reset='decisions']")); flush(); }
    check("undoing the decisions also takes back what was sent", IAP.state().sent === 0 && IAP.state().discarded === 0,
      JSON.stringify(IAP.state()));
    click($("#ptabs [data-ptab='email']"));
    flush();
    check("the address of the mailbox has no board in it", !/board/.test(win.location.hash), win.location.hash);
    IAP.setLayout("board");
    flush();
    check("switching to the board shows the cards and empties the mailbox", $$("#board .card").length === 12 &&
      $("#read-body").innerHTML === "" && /#board/.test(win.location.hash));
    IAP.setLayout("mail");
    flush();
    phoneMode = true;
    IAP.select("m05");
    flush();
    check("on a phone, picking an email in the mailbox goes to the email screen", IAP.screen() === "read", IAP.screen());
    check("the mailbox's tab bar has three screens", $$("#screens [data-screen][data-for='mail']").length === 3);
    phoneMode = false;
    IAP.select("m05", false);
    flush();
    void reset;
  });
}
check("no markup the script wrote carries an inline style, an inline handler or a javascript: address, so the page's security policy holds",
  !inlineSeen.length, inlineSeen[0]);
errors.forEach((e) => console.log("ERROR " + e));
const failed = checks.filter((c) => !c.ok);
failed.forEach((c) => console.log(`FAIL ${c.name} ${c.detail}`));
console.log(`${checks.length - failed.length} of ${checks.length} page checks pass` + (errors.length ? `, ${errors.length} errors` : ""));
process.exit(failed.length || errors.length ? 1 : 0);
