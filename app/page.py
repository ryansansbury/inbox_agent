"""site/index.html: the top bar, the summary line, the board, the drawer, the limits and the log, and How it works.

The board, the drawer, the limits and the log are filled by site/app.js from window.IA. How it works is rendered here,
since it reads the scores, the comparison, the injection results, the reply checker's results and the recordings, which
don't change in the browser. The limits sentences and the morning in time are rendered here too and kept live by the
script. Every visible word comes from WORDS.md. Nothing inline, so the site's content security policy holds.
"""
import base64
import html
import re
from pathlib import Path

from app.readme import SHOTS

HERE = Path(__file__).resolve().parent.parent
esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731
MARK = ('<svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true"><rect x="1" y="1" width="28" height="28" '
        'rx="8" fill="#f59e0b"/><path d="M7 11h16v10H7z" fill="none" stroke="#1e2227" stroke-width="2" '
        'stroke-linejoin="round"/><path d="M7 11l8 6 8-6" fill="none" stroke="#1e2227" stroke-width="2" '
        'stroke-linejoin="round"/></svg>')
ICON = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 30 30'><rect x='1' y='1' width='28' height='28' rx='8' "
        "fill='#f59e0b'/><path d='M7 11h16v10H7z' fill='none' stroke='#1e2227' stroke-width='2' stroke-linejoin='round'/>"
        "<path d='M7 11l8 6 8-6' fill='none' stroke='#1e2227' stroke-width='2' stroke-linejoin='round'/></svg>")
PLAY = ('<svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true"><path d="M0 0l10 6-10 6z" '
        'fill="currentColor"/></svg>')
LANES = ("needs_you", "handled", "customer", "stopped")
REPO = "https://github.com/ryansansbury/inbox_agent"
SITE = "https://ryansansbury.com/"
LIVE = "https://www.ryansansbury.com/inbox-agent/"
# The link preview's image is the top 838 rows of the homepage card, which is 1.91 to 1 and needs no crop on LinkedIn.
SHARE = "https://www.ryansansbury.com/images/share/inbox-agent.png?v=1"


def share(w):
    """The tags a shared link reads for its preview, in the same set the homepage uses."""
    title, text, alt = esc(w["page.title"]), esc(w["page.description"]), esc(dict(SHOTS)["mailbox"])
    return (f"<link rel='canonical' href='{LIVE}'><meta property='og:type' content='website'>"
            f"<meta property='og:url' content='{LIVE}'><meta property='og:site_name' content='ryansansbury.com'>"
            f"<meta property='og:title' content='{title}'><meta property='og:description' content='{text}'>"
            f"<meta property='og:image' content='{SHARE}'><meta property='og:image:width' content='1600'>"
            f"<meta property='og:image:height' content='838'><meta property='og:image:alt' content='{alt}'>"
            f"<meta name='twitter:card' content='summary_large_image'><meta name='twitter:title' content='{title}'>"
            f"<meta name='twitter:description' content='{text}'><meta name='twitter:image' content='{SHARE}'>")


# An ID like SO-20852 or a name like GPT-6 stays on one line. Chrome breaks after a hyphen that comes before a digit, so
# every one in the page's text goes in a span that doesn't wrap. site/app.js does the same for what it renders.
ID = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)+\b")
KEEP_OUT = ("option", "title", "textarea", "script", "style")


def keep_ids(page):
    out, inside = [], None
    for part in re.split(r"(<[^>]*>)", page):
        tag = re.match(r"<(/?)([a-zA-Z0-9]+)", part)
        if tag:
            name = tag.group(2).lower()
            if not tag.group(1) and name in KEEP_OUT:
                inside = name
            elif tag.group(1) and name == inside:
                inside = None
        elif not inside and not part.startswith("<"):
            part = ID.sub(lambda m: f"<span class='nw'>{m.group(0)}</span>", part)
        out.append(part)
    return "".join(out)


# ------------------------------------------------------------------------------------------------ formatting
def f3(x):
    return "" if x is None else f"{x:.3f}"


def cost(x):
    if x is None:
        return ""
    return f"${x:,.4f}" if x < 0.01 else f"${x:,.3f}" if x < 1 else f"${x:,.2f}"


def cap(x, unit):
    if unit == "usd":
        return f"${x:,.0f}" if float(x) == int(x) else f"${x:,.2f}"
    if unit == "days":
        return f"{x:g} days"
    return f"{x:g}%"


def plain(h):
    """A column's name without its markup, for an attribute."""
    return re.sub("<[^>]+>", "", str(h))


def table(head, rows, cls="grid", first_head=True):
    th = "".join(f"<th scope='col'>{esc(h)}</th>" for h in head)
    body = ""
    for r in rows:
        # Each value carries its column's name, which a phone shows beside it when the table reads as cards.
        cells = "".join((f"<th scope='row'>{c}</th>" if i == 0 and first_head else
                         f"<td data-label='{esc(plain(head[i]))}'>{c}</td>") for i, c in enumerate(r))
        body += f"<tr>{cells}</tr>"
    return f"<div class='table-wrap'><table class='{cls}'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>"


def listing(w, items):
    """'a', 'a and b' or 'a, b and c', with the joining word from WORDS.md."""
    items, word = list(items), w["ui.and"]
    if len(items) < 3:
        return f" {word} ".join(items)
    return ", ".join(items[:-1]) + f" {word} " + items[-1]


def of(w, a, b):
    return w.fill("ui.of", a=a, b=b)


def paras(w, key):
    return "".join(f"<p>{esc(p)}</p>" for p in w.paragraphs(key))


def panel(sid, title, body, lead=""):
    lead = f"<p class='lead'>{esc(lead)}</p>" if lead else ""
    return f"<section class='panel' id='{sid}'><h3>{esc(title)}</h3>{lead}{body}</section>"


# ------------------------------------------------------------------------------------------------ How it works
def how_map(w, r):
    cols = w.table("how.map.cols")
    rows = []
    for raw in w.table("how.map").values():
        part, kind, who, check = raw.split("|")
        check = check.replace("{vectors}", f"{r['vectors']:,}")
        rows.append([esc(part), f"<span class='who {esc(kind)}'>{esc(who)}</span>", esc(check)])
    return panel("how-map", w["how.map.title"], table([cols["part"], cols["who"], cols["check"]], rows, "grid map"),
                 w["how.map.lead"])


def how_tools(w):
    def lst(key):
        return "".join(f"<li><code>{esc(k)}</code><span>{esc(v)}</span></li>" for k, v in w.table(key).items())
    body = (f"<div class='two'><div><h4>{esc(w['how.tools.read_title'])}</h4><ul class='tools'>{lst('how.tools.read')}"
            f"</ul></div><div><h4>{esc(w['how.tools.act_title'])}</h4><ul class='tools act'>{lst('how.tools.act')}"
            f"</ul></div></div><p class='note'>{esc(w['how.tools.note'])}</p>")
    return panel("how-tools", w["how.tools.title"], body, w["how.tools.lead"])


def rule_lines(w, data):
    """The limits as sentences, at the defaults. The script rewrites them when a limit moves."""
    lines, L, C = [], w.table("ui.rule_line"), w.table("ui.rule_cap")
    caps = [C[k].replace("{v}", cap(s["value"], s["unit"])) for k, s in data["limits"].items() if k in C]
    if caps:
        joined = listing(w, caps)
        lines.append(w.fill("ui.rule_caps", caps=joined[0].upper() + joined[1:]))
    for k, spec in data["limits"].items():
        if k in L:
            lines.append(L[k].replace("{v}", cap(spec["value"], spec["unit"])))
    for k, on in data["switches"].items():
        lines.append(L[f"{k}.{'on' if on else 'off'}"])
    lines.append(w.table("ui.limits")["never"])
    return "".join(f"<li>{esc(x)}</li>" for x in lines)


def how_limits(w, data):
    return panel("how-limits", w["how.limits.title"], f"<ul class='rules' id='rule-lines'>{rule_lines(w, data)}</ul>",
                 w["how.limits.lead"])


def how_inject(w, data, r):
    inj = r["injections"]
    layers = "".join(f"<li><strong>{esc(t.split('|')[0])}</strong><span>{esc(t.split('|')[1])}</span></li>"
                     for t in w.table("how.inject.layers").values())
    cols = w.table("how.inject.cols")
    head = [cols["email"], cols["asks"], cols["flagged"], cols["limits"]] + \
        [cols["refused"].replace("{model}", m["label"]) for m in data["models"]]
    rows = []
    for x in inj["rows"]:
        wi = x["what_if"]
        if wi:
            asks = (f"{esc(w.table('ui.what_short')[wi['tool']])} · "
                    f"<span class='num'>${wi['args']['amount']:,.2f}</span>")
            v = (x["verdict"] or {}).get("verdict")
            lim = esc(w["how.inject.wait"] if v == "waiting" else w["how.inject.block"] if v == "blocked" else "")
        else:  # an instruction with no amount, like credits on every open invoice, meets the same cap
            asks = f"{esc(w.table('ui.what_short')['issue_credit'])} · {esc(w['how.inject.no_amount'])}"
            lim = esc(w.fill("how.inject.over_cap", cap=cap(inj["cap"], "usd")))
        yes = lambda ok: (f"<span class='ok'>{esc(w['how.inject.yes'])}</span>" if ok  # noqa: E731
                          else f"<span class='bad'>{esc(w['how.inject.no'])}</span>")
        rows.append([f"<code>{esc(x['id'])}</code>", asks, yes(x["flagged"]), lim] +
                    [yes(x["refused"].get(m["id"])) for m in data["models"]])
    every = all(all(v for v in x["refused"].values()) and x["flagged"] for x in inj["rows"])
    if every:
        key = "how.inject.none_other" if inj["elsewhere"] == 0 else "how.inject.all"
        summary = w.fill(key, planted=inj["planted"], elsewhere=inj["elsewhere"], others=inj["others"])
    else:
        summary = w["how.inject.some"]
    body = (f"<ol class='layers'>{layers}</ol>{table(head, rows, 'grid inject')}"
            f"<p class='note'>{esc(summary)}</p>")
    return panel("how-inject", w["how.inject.title"], body, w["how.inject.lead"])


def how_checker(w, r):
    c = r["checker"]
    cols = w.table("how.checker.cols")
    rows = [[esc(x["label"]), f"{x['checked']:,}", f"{x['supported']:,}", str(x["unsupported"]), str(x["premature"])]
            for x in c["rows"]]
    body = table([cols[k] for k in ("model", "claims", "backed", "unbacked", "early")], rows)
    if c["flagged"]:
        items = "".join(f"<li><span class='tag'>{esc(f['model'])} · {esc(f['email'])}</span><q>{esc(f['text'])}</q>"
                        f"<span class='why'>{esc(f['reason'])}</span></li>" for f in c["flagged"])
        body += f"<h4>{esc(w['how.checker.flagged'])}</h4><ul class='flagged'>{items}</ul>"
    else:
        body += f"<p>{esc(w['how.checker.none'])}</p>"
    body += f"<p class='note'>{esc(w['how.checker.note'])}</p>"
    return panel("how-checker", w["how.checker.title"], body, w["how.checker.lead"])


def how_method(w, data, r):
    rounds = r["tuning"]
    r1 = rounds[0]["dev"] if rounds else {}
    last = (rounds[-1].get("rescored") or rounds[-1]) if rounds else {}
    r1_f1 = sorted({f3(v["f1"]) for v in r1.values()})
    labels = {m["id"]: m["label"].replace(" 5.5", "") for m in data["models"]}
    claude = {m["id"] for m in data["models"] if m["vendor"] == "Anthropic"}
    dev2 = last.get("dev") or {}
    r2 = sorted({f3(v["f1"]) for k, v in dev2.items() if k in claude})
    r2_other = listing(w, [f"{f3(v['f1'])} for {labels.get(k, k)}" for k, v in dev2.items() if k not in claude])
    fr = r["froze"] or {"day": "", "prompt_same": False}
    if len(r1_f1) != 1:
        raise SystemExit("Round one's models scored differently, and how.method.tune says both scored the same.")
    if len(r2) != 1 or not r2_other:
        raise SystemExit("Round two's Claude models scored differently or ran alone, and how.method.tune says each Claude "
                         "model scored the same beside another model.")
    tune = w.fill("how.method.tune", r1=r1_f1[0], r2=r2[0], r2_other=r2_other)
    freeze = w.fill("how.method.freeze", prompt_day=fr["day"])
    if fr.get("prompt_same"):
        freeze += " " + w["how.method.same"]
    steps = [w["how.method.key"], tune, freeze, w["how.method.after"]]
    body = "<ol class='method'>" + "".join(f"<li><p>{esc(s)}</p></li>" for s in steps) + "</ol>"
    return panel("how-method", w["how.method.title"], body)


def how_score(w, data, r):
    cols, bars = w.table("how.score.cols"), w.table("how.score.bar")
    rows = []
    for m in data["models"]:
        s = r["scores"]["models"].get(m["id"]) or {}
        sp = s.get("splits") or {}
        test, morning = sp.get("test") or {}, sp.get("morning") or {}
        unsafe = sum(len((sp.get(k) or {}).get("unsafe", [])) for k in ("test", "morning"))
        inj = [v for k in ("test", "morning") for v in ((sp.get(k) or {}).get("injections") or {}).values()]
        claims = sum((sp.get(k) or {}).get("unsupported_claims", 0) + (sp.get(k) or {}).get("premature_claims", 0)
                     for k in ("test", "morning"))
        routing = [str((sp.get(k) or {}).get("routing", "")) for k in ("test", "morning")]
        right = sum(int(x.split(" of ")[0]) for x in routing if " of " in x)
        total = sum(int(x.split(" of ")[1]) for x in routing if " of " in x)
        missed = [k for k, ok in (s.get("bars") or {}).items() if not ok]
        verdict = (f"<span class='ok'>{esc(w['how.score.yes'])}</span>" if not missed else
                   f"<span class='bad'>{esc(w.fill('how.score.no', n=listing(w, [bars.get(k, k) for k in missed])))}"
                   "</span>")
        rows.append([esc(m["label"]), f3(test.get("f1")), f3(morning.get("f1")), str(unsafe),
                     esc(of(w, sum(1 for v in inj if v), len(inj))), str(claims), esc(of(w, right, total)), verdict])
    head = [cols[k] for k in ("model", "f1_test", "f1_morning", "unsafe", "injections", "claims", "routing", "bars")]
    body = table(head, rows, "grid score") + f"<p class='note'>{esc(w['how.score.note'])}</p>"
    return panel("how-score", w["how.score.title"], body, w["how.score.lead"])


def how_compare(w, data, r):
    comp = r["comparison"]
    cols = w.table("how.compare.cols")
    rows = []
    for m in data["models"]:
        s = (comp.get("models") or {}).get(m["id"]) or {}
        sp = s.get("splits") or {}
        steps = [(sp.get(k) or {}).get("steps_per_email") for k in ("test", "morning", "dev")]
        n = [(sp.get(k) or {}).get("emails", 0) for k in ("test", "morning", "dev")]
        avg = sum((a or 0) * b for a, b in zip(steps, n)) / max(1, sum(n))
        rows.append([esc(m["label"]) + (f" <span class='route'>{esc(w['how.compare.badge'])}</span>" if m["route"] else ""),
                     cost(s.get("cost_per_email")), f"{s.get('seconds_per_email', 0):.1f}", f"{avg:.1f}",
                     cost(s.get("total_cost"))])
    head = [cols[k] for k in ("model", "cost", "seconds", "steps", "total")]
    label = next((m["label"] for m in data["models"] if m["route"]), "")
    body = table(head, rows, "grid compare")
    if comp.get("why") == "the cheapest model that meets every bar":
        body += f"<p>{esc(w.fill('how.compare.route', model=label))}</p><p>{esc(w['how.compare.others'])}</p>"
    if any(m["id"] == "openai-luna" for m in data["models"]):
        body += f"<p class='note'>{esc(w['how.compare.luna'])}</p>"
    return panel("how-compare", w["how.compare.title"], body, w["how.compare.lead"])


def how_runs(w, r):
    cols = w.table("how.runs.cols")
    rows = []
    for x in r["recorded"]:
        when = x["first"][:10]
        rows.append([esc(x["label"]), str(x["runs"]), "<code>" + esc(", ".join(x["prompts"])) + "</code>", esc(when),
                     f"{x['input']:,}", f"{x['output']:,}", f"{x['cached']:,}", cost(x["cost"])])
    head = [cols[k] for k in ("model", "runs", "prompt", "recorded", "input", "output", "cached", "cost")]
    return panel("how-runs", w["how.runs.title"], table(head, rows, "grid runs"), w["how.runs.lead"])


def how_time(w):
    inputs = w.table("how.time.inputs")
    defaults = {"hand": 4, "approval": 2, "check": 1}
    fields = "".join(f"<label class='num-in'><span>{esc(v)}</span><input type='number' min='0' max='60' step='0.5' "
                     f"id='time-{k}' value='{defaults[k]}'></label>" for k, v in inputs.items())
    return panel("how-time", w["how.time.title"],
                 f"<div class='time-in'>{fields}</div><p class='time-out' id='time-out' aria-live='polite'></p>",
                 w["how.time.lead"])


def how_list(w, sid, title, key, lead=""):
    items = "".join(f"<li>{esc(v)}</li>" for v in w.table(key).values())
    return panel(sid, w[title], f"<ul class='plain'>{items}</ul>", lead)


def how_connect(w):
    """How it would connect: the two mail services side by side, then what a real deployment needs."""
    cols = w.table("how.connect.cols")
    rows = [[esc(c) for c in v.split("|")] for v in w.table("how.connect.rows").values()]
    items = "".join(f"<li>{esc(v)}</li>" for v in w.table("how.connect").values())
    body = table([cols["part"], cols["ms"], cols["google"]], rows, "grid map") + f"<ul class='plain'>{items}</ul>"
    return panel("how-yours", w["how.connect.title"], body, w["how.connect.lead"])


def how_code(w):
    feats = "".join(f"<button type='button' class='cfeat' data-file='{esc(k)}'><code>{esc(k)}</code>"
                    f"<span>{esc(v)}</span></button>" for k, v in w.table("how.code.feat").items())
    body = (f"<div class='feats'>{feats}</div><div class='codebox'>"
            f"<nav class='code-tree' id='code-tree' aria-label='{esc(w['how.code.tree'])}'>"
            f"<p class='muted'>{esc(w['how.code.loading'])}</p></nav>"
            "<div class='code-pane'><div class='code-head'><code id='code-path'></code></div>"
            "<pre class='code' tabindex='0'><code id='code-body'></code></pre></div></div>")
    return panel("how-code", w["how.code.title"], body, w["how.code.lead"])


def how(w, data, r):
    return ("<div class='how'>"
            f"<header class='how-head'><h2>{esc(w['how.title'])}</h2><p class='lead'>{esc(w['how.lead'])}</p></header>"
            f"{how_map(w, r)}{how_tools(w)}{how_limits(w, data)}{how_inject(w, data, r)}{how_checker(w, r)}"
            f"{how_method(w, data, r)}{how_score(w, data, r)}{how_compare(w, data, r)}{how_runs(w, r)}{how_time(w)}"
            f"{how_connect(w)}"
            f"{panel('how-privacy', w['how.privacy.title'], paras(w, 'how.privacy'))}"
            f"{how_list(w, 'how-cant', 'how.cant.title', 'how.cant')}"
            f"{how_code(w)}</div>")


# ------------------------------------------------------------------------------------------------ the page
def byline(w):
    links = w.table("page.links")
    return (f"<p class='byline'><a href='{SITE}'>{esc(links['site'])}</a> · "
            f"<a href='{REPO}'>{esc(links['code'])}</a></p>")


CHECK = ('<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5" '
         'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
CROSS = ('<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" fill="none" '
         'stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>')


def conn(w):
    """The strip under the top bar: the mailbox the agent works and what it can and can't do there."""
    c = w.table("page.conn")
    yes = "".join(f"<li class='yes'>{CHECK}{esc(c[k])}</li>" for k in ("read", "label", "draft"))
    no = "".join(f"<li class='no'>{CROSS}{esc(c[k])}</li>" for k in ("send", "delete", "limit"))
    return (f"<div class='conn' id='conn' aria-label='{esc(c['aria'])}'><b id='conn-address'></b><ul>{yes}{no}</ul>"
            f"<span class='demo'>{esc(c['demo'])}</span></div>")


def mailbox(w):
    """The mailbox's panes. site/app.js fills each one from window.IA."""
    m = w.table("ui.mail")
    return ("<div class='mail' id='mail'>"
            f"<nav class='rail' id='rail' aria-label='{esc(w.table('ui.folder')['aria'])}'></nav>"
            f"<section class='mlist' id='mlist' aria-label='{esc(m['list_aria'])}'>"
            f"<div class='mhead'><label class='msearch'><span class='sr'>{esc(w['page.search'])}</span>"
            f"<input type='search' id='q' placeholder='{esc(w['page.search'])}' autocomplete='off'></label>"
            "<div class='mspan' id='mspan'></div></div><div class='mrows' id='mrows'></div></section>"
            f"<section class='read' id='read' aria-label='{esc(m['read_aria'])}'><div class='read-body' id='read-body'>"
            "</div></section>"
            f"<aside class='apanel' id='panel' aria-label='{esc(m['panel_aria'])}'><div class='ptabs' id='ptabs' "
            "role='tablist'></div><div class='panel-body' id='panel-body'></div></aside>"
            "<svg class='threads' id='threads' aria-hidden='true'></svg></div>")


def lanes(w):
    out = ""
    for k in LANES:
        title, lead = w.table("ui.lane")[k].split("|")
        out += (f"<div class='lane' data-lane='{k}'><h2>{esc(title)} <span class='n' id='n-{k}'></span></h2>"
                f"<p class='lead'>{esc(lead)}</p><div class='cards' id='cards-{k}'></div></div>")
    return out


def render(w, data, r):
    aria = w.table("page.aria")
    models = "".join(f"<option value='{esc(m['id'])}'>{esc(m['label'])}</option>" for m in data["models"])
    screens = "".join(f"<button type='button' data-screen='{k}' data-for='board' aria-controls='{k}'>{esc(v)}</button>"
                      for k, v in w.table("page.screens").items())
    screens += "".join(f"<button type='button' data-screen='{k}' data-for='mail' aria-controls='{k}'>{esc(v)}</button>"
                       for k, v in w.table("page.screens_mail").items())
    lay = w.table("page.layout")
    icon = "data:image/svg+xml;base64," + base64.b64encode(ICON.encode()).decode()
    replay = w.table("ui.replay")
    return keep_ids(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta name='robots' content='index, follow'><meta name='referrer' content='no-referrer'>"
        f"<meta name='description' content='{esc(w['page.description'])}'>{share(w)}"
        f"<title>{esc(w['page.title'])}</title><link rel='icon' href='{icon}'>"
        "<link rel='stylesheet' href='app.css'></head><body class='mode-work layout-mail'>"
        f"<a class='skip' href='#main'>{esc(w['page.skip'])}</a>"
        f"<header class='top' aria-label='{esc(aria['top'])}'>"
        f"<a class='brand' href='#' id='home'>{MARK}<b>{esc(w['page.title'])}</b>"
        f"<span>{esc(w.fill('page.subtitle', company=data['company']))}</span></a>"
        "<div class='grow'></div><div class='replay' id='replay'>"
        f"<button type='button' class='btn-amber' id='play'>{PLAY}<span id='play-label'><span class='long'>"
        f"{esc(replay['play'])}</span><span class='short'>{esc(replay['play_short'])}</span></span></button>"
        f"<button type='button' class='btn-ghost small' id='skip' hidden>{esc(replay['skip'])}</button>"
        f"<span class='clock' id='clock' role='timer' aria-label='{esc(aria['clock'])}'>9:30 AM</span>"
        f"<button type='button' class='speed' id='speed' aria-label='{esc(replay['speed'])}'>2×</button></div>"
        f"<div class='layouts' role='group' aria-label='{esc(lay['label'])}'>"
        f"<button type='button' id='lay-mail' data-layout='mail' aria-pressed='true'>{esc(lay['mail'])}</button>"
        f"<button type='button' id='lay-board' data-layout='board' aria-pressed='false'>{esc(lay['board'])}</button></div>"
        f"<label class='rec'><i aria-hidden='true'></i><span>{esc(w['page.recorded'])}</span>"
        f"<select id='model' aria-label='{esc(w['page.model'])}'>{models}</select></label>"
        f"<button type='button' class='btn-ghost' id='open-limits' aria-pressed='false' aria-controls='side'>"
        f"{esc(w['page.limits'])}</button>"
        f"<button type='button' class='btn-ghost' id='open-log' aria-pressed='false' aria-controls='side'>"
        f"<span class='long'>{esc(w['page.log'])}</span><span class='short'>{esc(w['page.log_short'])}</span>"
        "<span class='count' id='log-count'></span></button>"
        f"<button type='button' class='btn-ghost' id='how-link' aria-pressed='false'>{esc(w['page.how'])}</button>"
        f"<button type='button' class='btn-ghost' id='tour-start'>{esc(w['page.tour'])}</button>"
        f"<button type='button' class='btn-ghost theme' id='theme' aria-pressed='false' aria-label='{esc(w['page.dark'])}' "
        f"title='{esc(w['page.dark'])}'><svg class='moon' viewBox='0 0 24 24' width='16' height='16' aria-hidden='true'><path d='M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z' fill='none' stroke='currentColor' stroke-width='1.9' stroke-linejoin='round'/></svg><svg class='sun' viewBox='0 0 24 24' width='16' height='16' aria-hidden='true'><circle cx='12' cy='12' r='4' fill='none' stroke='currentColor' stroke-width='1.9'/><path d='M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8' stroke='currentColor' stroke-width='1.9' stroke-linecap='round'/></svg></button></header>"
        f"{conn(w)}<div class='summary' id='summary'></div>"
        f"<nav class='screens' id='screens' aria-label='{esc(aria['screens'])}'>{screens}</nav>"
        f"<main id='main' tabindex='-1'>{mailbox(w)}<div class='work' id='work'>"
        f"<section class='board' id='board' aria-label='{esc(aria['board'])}'>"
        f"<div class='incoming' id='incoming' hidden><span class='lbl'>{esc(w['ui.incoming'])}</span>"
        f"<div class='cards' id='cards-incoming'></div></div><div class='lanes'>{lanes(w)}</div>"
        f"<footer class='board-foot'><p>{esc(w['page.footer'])}</p>{byline(w)}</footer></section>"
        f"<aside class='drawer' id='drawer' aria-label='{esc(aria['drawer'])}'>"
        "<div class='drawer-body' id='drawer-body'></div></aside>"
        f"<aside class='side' id='side' aria-label='{esc(aria['side'])}'><div class='side-body' id='side-body'></div>"
        "</aside></div>"
        f"<section class='how-view' id='how' hidden><div class='how-top'><button type='button' class='btn' "
        f"id='how-back'>{esc(w['page.back'])}</button></div>{how(w, data, r)}"
        f"<footer class='how-foot'><p>{esc(w['page.footer'])}</p>{byline(w)}</footer></section></main>"
        "<svg class='tour' id='tour' aria-hidden='true' hidden></svg>"
        "<div class='presenter' id='presenter' role='dialog' aria-live='polite' hidden></div>"
        "<div class='pop' id='pop' role='tooltip' hidden></div>"
        "<script src='policy.js'></script><script src='replies.js'></script><script src='data.js'></script>"
        "<script src='app.js'></script></body></html>\n"
    )
