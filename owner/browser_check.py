"""The owner's machine only. Look at the Inbox Agent page in real Chrome: screenshots, overlaps, text that spills out
of its box, console errors, every network request, the replay to its end, and the phone screens.

    python3 owner/browser_check.py            (from the build folder, after python3 build.py)

It opens site/index.html in headless Chrome with a fresh profile and drives it over the DevTools pipe. Everything goes
to owner/out/, which is gitignored:

    screens/card-1600.png          the page as a fresh load opens it at 1600 by 1000 with nothing clicked, the homepage
                                   card's frame
    screens/1600-<state>.png       the credit cap at $100 with the limits open, the refused email, the look-alike
                                   sender, the out-of-stock question, the holiday order, an approval in the log, a
                                   sample bad claim in the reply, the replay mid-email and at its end, and GPT-6 Luna's
                                   run of the morning
    screens/<width>-<email>.png    the rush order and the refused email at 1440, 1280 and 1024
    screens/<width>-how.png        How it works, the whole page
    screens/<width>-stepNN.png     every tour step at 1440 and 1280
    screens/<width>-screen-*.png   on a phone and a narrow tablet, the three screens and one tour step
    screens/gallery-*.png          the README's four screenshots (the board, the refused email, the limits moved and
                                   the scoreboard), copied into docs/images/ whenever the run comes back clean
    review.html                    every screenshot on one page with its caption, for the design review
    layout.json                    text overlapping text, boxes whose content spills, anything wider than the window,
                                   the top bar's rows and the tabs on one line
    console.json, network.json     anything the page logged as an error, and every request it made
    browser_check.json             the summary this prints

Standard library only.
"""
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SITE = ROOT.joinpath("site")
OUT = HERE.joinpath("out")
SHOTS = OUT.joinpath("screens")
APPS = Path("/").joinpath("Applications")
CHROMES = (APPS.joinpath("Google Chrome.app", "Contents", "MacOS", "Google Chrome"),
           APPS.joinpath("Chromium.app", "Contents", "MacOS", "Chromium"))
WIDTHS = ((1440, 900), (1280, 720), (1024, 768))
SMALL = ((768, 1024), (390, 844))
SETTLE = 1.4
GALLERY = ("mailbox", "refused", "limits", "score")
TOPBAR_JS = ("(function () { var boxes = Array.prototype.filter.call(document.querySelectorAll('.top > *'), function (k) { "
             "return k.checkVisibility(); }).map(function (k) { return k.getBoundingClientRect(); }).sort(function (a, b) { "
             "return a.top - b.top; }); var rows = 0, bottom = -1; boxes.forEach(function (r) { if (r.top >= bottom - 2) { "
             "rows += 1; bottom = r.bottom; } else { bottom = Math.max(bottom, r.bottom); } }); return rows; })()")
HOW_PANELS = ("how-map", "how-tools", "how-limits", "how-inject", "how-checker", "how-method", "how-score",
              "how-compare", "how-runs", "how-time", "how-yours", "how-privacy", "how-cant", "how-code")
TABS_JS = ("(function () { var t = Array.prototype.filter.call(document.querySelectorAll('[data-screen]'), "
           "function (e) { return e.checkVisibility(); }); var tops = Array.prototype.map.call(t, "
           "function (e) { return Math.round(e.getBoundingClientRect().top); }); return tops.every(function (x) { "
           "return x === tops[0]; }); })()")
TRAMPOLINE = 'exec "$@" 3<&0 4>&1 0</dev/null 1>&2'

LAYOUT_JS = """(function () {
  var W = window.innerWidth, out = {wider_than_window: document.documentElement.scrollWidth > W + 1, overlaps: [],
    short_last_lines: [], spills: [], split_ids: []};
  var root = document.body, boxes = new Map(), covers = [];
  function name(el) {
    return (el.id ? '#' + el.id : el.tagName.toLowerCase() + Array.prototype.map.call(el.classList, function (c) {
      return '.' + c; }).join('')).slice(0, 50);
  }
  function clip(el) {
    if (boxes.has(el)) { return boxes.get(el); }
    var b = {l: -1e9, t: -1e9, r: 1e9, b: 1e9};
    for (var a = el; a && a !== document.documentElement; a = a.parentElement) {
      var cs = getComputedStyle(a);
      if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') {
        var q = a.getBoundingClientRect();
        b = {l: Math.max(b.l, q.left), t: Math.max(b.t, q.top), r: Math.min(b.r, q.right), b: Math.min(b.b, q.bottom)};
      }
    }
    boxes.set(el, b);
    return b;
  }
  root.querySelectorAll('*').forEach(function (el) {
    if (el.closest('svg') || !el.checkVisibility()) { return; }
    var cs = getComputedStyle(el);
    if (cs.position === 'sticky' || cs.position === 'fixed' || el.matches('.pop, .side.open, .presenter, body.panel-open .mail > .apanel')) { covers.push(el); }
    if (out.spills.length >= 25 || el.closest('pre, .code-tree, .sr') || cs.display === 'inline' || !el.clientWidth) { return; }
    if (cs.textOverflow === 'ellipsis') { return; }
    if (/x|both/.test(cs.scrollSnapType || '')) { return; }
    if (el.scrollWidth > el.clientWidth + 1) {
      var scrolls = cs.overflowX === 'auto' || cs.overflowX === 'scroll';
      out.spills.push(name(el) + ' by ' + (el.scrollWidth - el.clientWidth) + 'px' + (scrolls ? ' (scrolls)' : ''));
    }
  });
  function covered(el, f) {
    return covers.some(function (c) {
      if (c === el || c.contains(el)) { return false; }
      var q = c.getBoundingClientRect();
      return f.l < q.right && f.r > q.left && f.t < q.bottom && f.b > q.top;
    });
  }
  // The line rule: in prose, a last line shorter than 60 percent of its paragraph's longest line hangs short.
  root.querySelectorAll('.how-view p, .how-view ul.rules li, .how-view ul.plain li, .presenter p, .whatif, .banner, ' +
      '.flags li, .moved-line').forEach(function (el) {
    if (!el.checkVisibility() || el.closest('pre, table, .code-tree')) { return; }
    var r = document.createRange(); r.selectNodeContents(el);
    var rects = Array.prototype.filter.call(r.getClientRects(), function (x) { return x.width > 1 && x.height > 1; })
      .sort(function (a, b) { return a.top - b.top; });
    var lines = [];
    rects.forEach(function (x) {
      var mid = (x.top + x.bottom) / 2, line = lines[lines.length - 1];
      if (line && mid >= line.t && mid <= line.b) { line.l = Math.min(line.l, x.left); line.r = Math.max(line.r, x.right); }
      else { lines.push({t: x.top, b: x.bottom, l: x.left, r: x.right}); }
    });
    if (lines.length < 2) { return; }
    var widths = lines.map(function (q) { return q.r - q.l; }), longest = Math.max.apply(null, widths);
    var ratio = widths[widths.length - 1] / Math.max(1, longest);
    if (ratio < 0.6) { out.short_last_lines.push({text: el.textContent.trim().slice(-60), fill: Math.round(ratio * 100)}); }
  });
  var frags = [], walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), node, range = document.createRange();
  var idre = /\\b[A-Z0-9]+(?:-[A-Z0-9]+)+\\b/g, idr = document.createRange();
  while ((node = walker.nextNode())) {
    var el = node.parentElement;
    if (!/\\S/.test(node.data) || !el || el.closest('script, style, pre, .code-tree') || !el.checkVisibility()) { continue; }
    /* An ID like SO-20852 broken across two lines at its hyphen. */
    idre.lastIndex = 0;
    for (var m = idre.exec(node.data); m && out.split_ids.length < 20; m = idre.exec(node.data)) {
      idr.setStart(node, m.index);
      idr.setEnd(node, m.index + m[0].length);
      var tops = {};
      Array.prototype.forEach.call(idr.getClientRects(), function (x) { if (x.width > 0.5) { tops[Math.round(x.top)] = 1; } });
      if (Object.keys(tops).length > 1) { out.split_ids.push(m[0]); }
    }
    var box = clip(el);
    range.selectNodeContents(node);
    Array.prototype.forEach.call(range.getClientRects(), function (x) {
      if (x.width < 1 || x.height < 1) { return; }
      var h = x.bottom - x.top, mid = (x.top + x.bottom) / 2;
      var f = {el: el, l: Math.max(x.left, box.l), r: Math.min(x.right, box.r), t: x.top + h * 0.2, b: x.bottom - h * 0.2,
        text: node.data.trim().slice(0, 40)};
      if (mid < box.t || mid > box.b || f.r - f.l < 1 || covered(el, f)) { return; }
      frags.push(f);
    });
  }
  frags.sort(function (a, b) { return a.t - b.t; });
  for (var i = 0; i < frags.length && out.overlaps.length < 20; i++) {
    for (var j = i + 1; j < frags.length && frags[j].t < frags[i].b; j++) {
      var f = frags[i], g = frags[j];
      if (f.el === g.el || f.el.contains(g.el) || g.el.contains(f.el)) { continue; }
      if (Math.min(f.r, g.r) - Math.max(f.l, g.l) > 2) { out.overlaps.push(f.text + ' / ' + g.text); }
    }
  }
  return out;
})()"""


def find_chrome(given=None):
    if given:
        return str(given)
    for p in CHROMES:
        if p.exists():
            return str(p)
    for n in ("google-chrome", "chromium"):
        if shutil.which(n):
            return shutil.which(n)
    raise SystemExit("Chrome wasn't found. Run again with --chrome and the path to the Chrome program.")


class CDP:
    """The DevTools protocol over Chrome's pipe: JSON messages, each ended by a zero byte."""

    def __init__(self, proc, on_event=None):
        self.proc, self.on_event = proc, on_event
        self.next_id, self.responses, self.events = 0, {}, []
        self.cond, self.wlock = threading.Condition(), threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = b""
        while True:
            chunk = self.proc.stdout.read1(1 << 16)
            if not chunk:
                break
            buf += chunk
            while b"\0" in buf:
                raw, buf = buf.split(b"\0", 1)
                msg = json.loads(raw)
                with self.cond:
                    if "id" in msg:
                        self.responses[msg["id"]] = msg
                    else:
                        self.events.append(msg)
                    self.cond.notify_all()
                if "id" not in msg and self.on_event:
                    self.on_event(msg)

    def send(self, method, params=None, session=None, timeout=60):
        with self.cond:
            self.next_id += 1
            mid = self.next_id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        with self.wlock:
            self.proc.stdin.write(json.dumps(msg).encode() + b"\0")
            self.proc.stdin.flush()
        deadline = time.time() + timeout
        with self.cond:
            while mid not in self.responses:
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(method)
                self.cond.wait(left)
            reply = self.responses.pop(mid)
        if "error" in reply:
            raise RuntimeError(f"{method}: {reply['error'].get('message')}")
        return reply.get("result", {})

    def mark(self):
        with self.cond:
            return len(self.events)

    def wait_event(self, method, session, since, timeout=60):
        deadline = time.time() + timeout
        with self.cond:
            while True:
                for e in self.events[since:]:
                    if e.get("method") == method and e.get("sessionId") == session:
                        return e
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(method)
                self.cond.wait(left)


class Browser:
    def __init__(self, chrome):
        self.requests, self.console, self.loads = [], [], 0
        profile = OUT.joinpath("chrome-profile")
        shutil.rmtree(profile, ignore_errors=True)
        flags = ["--headless=new", "--remote-debugging-pipe", f"--user-data-dir={profile}", "--no-first-run",
                 "--no-default-browser-check", "--disable-extensions", "--hide-scrollbars", "--mute-audio",
                 "--disable-background-networking", "--disable-sync", "--disable-component-update",
                 "--autoplay-policy=no-user-gesture-required", "--allow-file-access-from-files"]
        self.log = OUT.joinpath("chrome.log").open("wb")
        self.proc = subprocess.Popen(["bash", "-c", TRAMPOLINE, "chrome", chrome, *flags], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.log)
        self.cdp = CDP(self.proc, self.event)
        target = self.cdp.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.s = self.cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        for m in ("Page.enable", "Runtime.enable", "Network.enable", "Log.enable"):
            self.cdp.send(m, session=self.s)

    def event(self, e):
        m, p = e.get("method"), e.get("params", {})
        if m == "Network.requestWillBeSent":
            self.requests.append(p["request"]["url"])
        elif m == "Runtime.exceptionThrown":
            d = p["exceptionDetails"]
            self.console.append({"kind": "exception", "text": (d.get("exception") or {}).get("description") or d.get("text")})
        elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
            self.console.append({"kind": "console.error", "text": " ".join(str(a.get("value", a.get("description")))
                                                                           for a in p.get("args", []))})
        elif m == "Log.entryAdded" and p["entry"].get("level") == "error":
            self.console.append({"kind": "log", "text": p["entry"].get("text"), "url": p["entry"].get("url")})

    def view(self, width, height, mobile=False):
        self.cdp.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1,
                                                             "mobile": mobile}, self.s)

    def load(self, url):
        """A fresh page at the address. Each load carries its own query, so it is never a move within the same page,
        which fires no load event, and a reload can't race the page's own address change."""
        self.loads += 1
        base, mark, frag = url.partition("#")
        fresh = f"{base}{'&' if '?' in base else '?'}load={self.loads}{mark}{frag}"
        since = self.cdp.mark()
        self.cdp.send("Page.navigate", {"url": fresh}, self.s)
        self.cdp.wait_event("Page.loadEventFired", self.s, since)
        self.pause(0.5)

    def js(self, expr, wait=False):
        r = self.cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": wait}, self.s)
        if "exceptionDetails" in r:
            raise RuntimeError(f"{expr[:60]}: {r['exceptionDetails'].get('text')}")
        return r.get("result", {}).get("value")

    def pause(self, seconds):
        self.js(f"new Promise(r => requestAnimationFrame(() => setTimeout(r, {int(seconds * 1000)})))", wait=True)

    def shot(self, name, width, full=True):
        params = {"format": "png"}
        if full:
            size = self.cdp.send("Page.getLayoutMetrics", session=self.s)["cssContentSize"]
            params.update(captureBeyondViewport=True, clip={"x": 0, "y": 0, "width": width,
                                                            "height": min(size["height"], 9000), "scale": 1})
        data = self.cdp.send("Page.captureScreenshot", params, self.s, timeout=120)["data"]
        SHOTS.joinpath(f"{name}.png").write_bytes(base64.b64decode(data))

    def close(self):
        try:
            self.cdp.send("Browser.close", timeout=10)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def shot_el(b, name, selector):
    """One element as its own picture, so a tall view reads panel by panel."""
    r = b.js(f"(function () {{ var e = document.querySelector('{selector}'); if (!e) {{ return null; }} "
             "var q = e.getBoundingClientRect(); return {x: q.left + scrollX, y: q.top + scrollY, w: q.width, h: q.height}; })()")
    if not r:
        return
    params = {"format": "png", "captureBeyondViewport": True,
              "clip": {"x": max(0, r["x"] - 8), "y": max(0, r["y"] - 8), "width": r["w"] + 16, "height": min(r["h"] + 16, 4000),
                       "scale": 1}}
    data = b.cdp.send("Page.captureScreenshot", params, b.s, timeout=120)["data"]
    SHOTS.joinpath(f"{name}.png").write_bytes(base64.b64decode(data))


CAPTIONS = (("card", "The homepage card's frame: a fresh load at 1600 by 1000"), ("1600-", "At 1600 by 1000"),
            ("1440-how-", "How it works, one panel"), ("1440-step", "The tour at 1440"), ("1280-step", "The tour at 1280"),
            ("1440-", "At 1440 by 900"), ("1280-", "At 1280 by 720"), ("1024-", "At 1024 by 768"),
            ("768-", "A narrow tablet"), ("390-", "A phone"), ("gallery-", "A README candidate"))


def review_page():
    """owner/out/review.html: every screenshot with its name, in the order the review reads them."""
    names = sorted(p.stem for p in SHOTS.glob("*.png"))
    order = ["card-1600"] + [n for n in names if n.startswith("1600-")] + [n for n in names if n.startswith("gallery-")] + \
        [n for n in names if n.startswith(("1440-", "1280-", "1024-")) and "-how" not in n and "-step" not in n] + \
        [n for n in names if "-how" in n] + [n for n in names if "-step" in n] + \
        [n for n in names if n.startswith(("768-", "390-"))]
    seen, cells = set(), []
    for n in order:
        if n in seen or n not in names:
            continue
        seen.add(n)
        cap = next((c for k, c in CAPTIONS if n.startswith(k)), "")
        cells.append(f"<figure><a href='screens/{n}.png'><img src='screens/{n}.png' loading='lazy' alt='{n}'></a>"
                     f"<figcaption><b>{n}</b> {cap}</figcaption></figure>")
    OUT.joinpath("review.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Inbox Agent screenshots</title><style>body{font:14px system-ui;"
        "margin:24px;background:#ecebe7}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));"
        "gap:18px}figure{margin:0;background:#fff;border:1px solid #d8d6cf;border-radius:10px;padding:10px}img{width:100%;"
        "border-radius:6px;display:block}figcaption{margin-top:6px;color:#3c4148}</style><h1>Inbox Agent screenshots</h1>"
        f"<main>{''.join(cells)}</main>", encoding="utf-8")


def act(b, js, wait=SETTLE):
    b.js("(function () { " + js + " })()")
    b.pause(wait)


def snap(b, name, width, layout, full=False):
    b.shot(name, width, full=full)
    layout[name] = b.js(LAYOUT_JS)


def states(b, url, layout):
    """The 1600 frame: the fresh load, then each state the page is for, each from a fresh load."""
    b.view(1600, 1000)
    b.load(url)
    b.pause(SETTLE + 0.6)
    snap(b, "card-1600", 1600, layout)
    layout["top_rows_1600"] = b.js(TOPBAR_JS)
    b.load(url)
    act(b, "document.getElementById('open-limits').click(); var r = document.getElementById('lim-credit_cap'); "
           "r.value = '100'; r.dispatchEvent(new Event('input', {bubbles: true}));", 2.0)
    snap(b, "1600-limits-100", 1600, layout)
    layout["moved_at_100"] = b.js("IAP.moved()")
    for eid in ("m11", "m10", "m06", "m09"):
        b.load(f"{url}#{eid}")
        b.pause(SETTLE)
        snap(b, f"1600-{eid}", 1600, layout)
    b.load(url)
    act(b, "document.querySelector('#sec-decisions [data-decide=approved]').click(); "
           "document.getElementById('open-log').click();")
    snap(b, "1600-log", 1600, layout)
    b.load(url)
    act(b, "document.querySelector('[data-sample=promise]').click(); "
           "document.getElementById('sec-reply').scrollIntoView({block: 'center'});")
    snap(b, "1600-sample", 1600, layout)
    b.load(f"{url}#m10@openai-luna")
    b.pause(SETTLE)
    snap(b, "1600-luna-m10", 1600, layout)
    b.load(url)
    act(b, "document.getElementById('play').click();", 7.0)
    act(b, "document.getElementById('play').click();", 0.6)
    snap(b, "1600-replay-mid", 1600, layout)
    layout["replay_mid"] = b.js("IAP.replay()")
    b.load(url)
    act(b, "document.getElementById('speed').click(); document.getElementById('play').click();", 1.0)
    t0 = time.time()
    while time.time() - t0 < 90 and b.js("IAP.replay() !== null"):
        b.pause(1.0)
    layout["replay_seconds_at_16x"] = round(time.time() - t0 + 1.0, 1)
    layout["replay_ended"] = b.js("IAP.replay() === null && document.querySelectorAll('#mrows .mrow').length === 12")
    snap(b, "1600-replay-end", 1600, layout)
    # The mailbox's own states: the Drafts folder with its batch send, a sent reply, and the board behind the switch.
    b.load(url)
    act(b, "document.querySelector(\"#rail [data-folder='drafts']\").click();")
    snap(b, "1600-drafts", 1600, layout)
    act(b, "var s = document.getElementById('send-checked'); if (s) { s.click(); } "
           "document.querySelector(\"#rail [data-folder='sent']\").click();")
    snap(b, "1600-sent", 1600, layout)
    layout["sent_in_one_go"] = b.js("IAP.state().sent")
    b.load(url)
    act(b, "document.getElementById('send-reply').click();")
    snap(b, "1600-sent-one", 1600, layout)
    b.load(f"{url}#board/m05")
    b.pause(SETTLE)
    snap(b, "1600-board", 1600, layout)
    # Dark mode, from the button at the end of the top bar: the mailbox, the limits in the panel and How it works.
    b.load(url)
    act(b, "document.getElementById('theme').click();")
    snap(b, "1600-dark", 1600, layout)
    act(b, "document.querySelector(\"#ptabs [data-ptab='limits']\").click();")
    snap(b, "1600-dark-limits", 1600, layout)
    b.load(f"{url}#how")
    act(b, "document.getElementById('theme').click();")
    snap(b, "1600-dark-how", 1600, layout, full=True)
    layout["threads_1600"] = b.js("IAP.threads()")


def sizes(b, url, layout):
    for width, height in WIDTHS:
        b.view(width, height)
        for eid in ("m05", "m11"):
            b.load(f"{url}#{eid}")
            b.pause(SETTLE)
            snap(b, f"{width}-{eid}", width, layout)
        layout[f"top_rows_{width}"] = b.js(TOPBAR_JS)
        b.load(f"{url}#how")
        b.pause(1.2)
        b.shot(f"{width}-how", width, full=True)
        layout[f"{width}-how"] = b.js(LAYOUT_JS)
        if width == 1440:
            for pid in HOW_PANELS:
                shot_el(b, f"1440-{pid}", f"#{pid}")
        if width == 1024:
            # At this width the agent's panel opens as a sheet over the email.
            b.load(f"{url}#m05")
            act(b, "document.getElementById('agent-toggle').click();")
            snap(b, "1024-m05-panel", width, layout)
            continue
        b.load(url)
        steps = b.js("IAP.steps()") or 0
        b.js("document.getElementById('tour-start').click()")
        for i in range(1, steps + 1):
            b.pause(SETTLE)
            snap(b, f"{width}-step{i:02d}", width, layout)
            b.js("document.querySelector('[data-tour=next]').click()")
        layout[f"tour_left_clean_{width}"] = b.js("IAP.state().present === 0 && IAP.moved().length === 0")


def small(b, url, layout):
    for width, height in SMALL:
        b.view(width, height, mobile=width < 500)
        for hash_, names in (("#m05", ("list", "read", "panel")), ("#board/m05", ("board", "drawer", "side"))):
            b.load(f"{url}{hash_}")
            b.pause(SETTLE)
            for name in names:
                b.js(f"document.querySelector('[data-screen={name}]').click()")
                b.pause(0.9)
                b.shot(f"{width}-screen-{name}", width, full=False)
                layout[f"{width}-screen-{name}"] = b.js(LAYOUT_JS)
        b.load(f"{url}#m05")
        b.pause(SETTLE)
        layout[f"screen_after_tabs_{width}"] = b.js("IAP.screen()")
        layout[f"tabs_one_line_{width}"] = b.js(TABS_JS)
        layout[f"top_rows_{width}"] = b.js(TOPBAR_JS)
        b.js("IAP.present(8)")
        b.pause(SETTLE)
        b.shot(f"{width}-tour-step08", width, full=False)
        b.js("IAP.present(0)")
        b.pause(0.4)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the page in real Chrome and take its screenshots.")
    ap.add_argument("--chrome", help="the path to the Chrome program, if it isn't in the usual place")
    a = ap.parse_args(argv)
    shutil.rmtree(SHOTS, ignore_errors=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    # The run checks a copy of the page taken as it starts, so edits made to site/ while it runs can't change a shot.
    site = OUT.joinpath("site")
    shutil.rmtree(site, ignore_errors=True)
    shutil.copytree(SITE, site)
    # The launch tool ships only files whose hashes match the ones Chrome checked here.
    checked = {p.relative_to(site).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(site.rglob("*")) if p.is_file()}
    url = site.joinpath("index.html").resolve().as_uri()
    b = Browser(find_chrome(a.chrome))
    layout, t0 = {}, time.time()
    try:
        states(b, url, layout)
        sizes(b, url, layout)
        small(b, url, layout)
    finally:
        b.close()
    for src, dst in (("card-1600", "gallery-mailbox"), ("1600-m11", "gallery-refused"), ("1600-limits-100", "gallery-limits"),
                     ("1440-how-score", "gallery-score")):
        if SHOTS.joinpath(f"{src}.png").exists():
            shutil.copyfile(SHOTS.joinpath(f"{src}.png"), SHOTS.joinpath(f"{dst}.png"))
    review_page()
    not_local = [u for u in b.requests if not u.startswith(("file:", "data:", "about:"))]
    OUT.joinpath("layout.json").write_text(json.dumps(layout, indent=1))
    OUT.joinpath("console.json").write_text(json.dumps(b.console, indent=1))
    OUT.joinpath("network.json").write_text(json.dumps(b.requests, indent=1))
    screens = {k: v for k, v in layout.items() if isinstance(v, dict) and "overlaps" in v}
    summary = {"seconds": round(time.time() - t0, 1), "screens": len(list(SHOTS.glob("*.png"))),
               "console_errors": b.console, "requests_off_the_machine": not_local,
               "overlaps": {k: v["overlaps"] for k, v in screens.items() if v["overlaps"]},
               "spills": {k: v["spills"] for k, v in screens.items() if v.get("spills")},
               "wider_than_window": [k for k, v in screens.items() if v["wider_than_window"]],
               "short_last_lines": {k: v["short_last_lines"] for k, v in screens.items()
                                    if v.get("short_last_lines") and (k.endswith("-how") or "-step" in k)},
               "split_ids": {k: v["split_ids"] for k, v in screens.items() if v.get("split_ids")},
               "top_bar_rows": {k: v for k, v in layout.items() if k.startswith("top_rows")},
               "tabs_on_one_line": {k: v for k, v in layout.items() if k.startswith("tabs_one_line")},
               "moved_at_100": layout.get("moved_at_100"), "replay_mid": layout.get("replay_mid"),
               "replay_ended": layout.get("replay_ended"), "replay_seconds_at_16x": layout.get("replay_seconds_at_16x"),
               "tour_left_clean": {k: v for k, v in layout.items() if k.startswith("tour_left_clean")},
               "files": checked}
    OUT.joinpath("browser_check.json").write_text(json.dumps(summary, indent=1))
    shown = dict(summary)
    shown.pop("files")
    shown["overlaps"] = sum(len(v) for v in summary["overlaps"].values())
    shown["spills"] = sum(len(v) for v in summary["spills"].values())
    shown["short_last_lines"] = sum(len(v) for v in summary["short_last_lines"].values())
    shown["split_ids"] = sum(len(v) for v in summary["split_ids"].values())
    shown["console_errors"] = len(b.console)
    print(json.dumps(shown, indent=1))
    print(f"Screenshots are in {SHOTS}, and owner/out/review.html shows them on one page.")
    clean = not (b.console or not_local or summary["overlaps"] or summary["spills"] or summary["split_ids"]
                 or summary["wider_than_window"])
    shots = [SHOTS.joinpath(f"gallery-{n}.png") for n in GALLERY]
    if clean and all(p.exists() for p in shots):
        for n, p in zip(GALLERY, shots):
            shutil.copyfile(p, ROOT.joinpath("docs", "images", f"{n}.png"))
        print("The run came back clean, so the README's four screenshots in docs/images/ are this run's.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
