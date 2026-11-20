"""README.md, written by the build from the same results the page shows.

The prose lives here and follows the writing rules. The tables and figures come from the scores, the comparison and the
recordings, so the README can't drift from the page. A notes file kept outside the public repo gets the same numbers
between two markers when it's present.
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
LIVE = "https://www.ryansansbury.com/inbox-agent/"
START, END = "<!-- numbers -->", "<!-- /numbers -->"

INTRO = """# Inbox Agent

An AI agent works one morning in a packaging distributor's order desk mailbox. It reads each email, looks things up and proposes actions through tools. Code decides whether each action goes through under limits a person sets. Anything over a limit waits for a person, every number in a reply is checked against what the agent saw and an instruction planted in an email can't move money.

[Open the demo]({live})
{hero}
Every company, person, order and email here is made up. The records are a small synthetic database. The agent's runs were recorded on my machine and the page replays them without calling any AI service. The answer key was written before any model ran.

## What it shows

- **The order desk's mailbox.** The page opens where the work happens. Each email carries the agent's label and a checked draft sits under it. The agent's panel at the right shows what it did where an add-in would sit in a desktop mail app.
- **The morning replays.** Twelve emails arrive before half past nine and the agent works each one at the pace it took. Its steps land in the panel as its label lands in the list.
- **Every action is tied to its sentence.** Each decision names the numbered sentence of the email that asked for it and a line runs from one to the other. Pointing at a number in the draft lights the step it came from.
- **The limits run live.** Move the credit cap from $250 to $100 and three emails move to Needs you at once. The page decides every action again with the same rules that scored the agent.
- **A person approves what's over a limit.** Approve or deny it in the panel and the audit log records who decided what.
- **A person sends every reply.** The agent's reply waits as a draft until someone sends it. The Drafts folder can send every checked reply at once.
- **A planted instruction goes nowhere.** A forwarded thread tells the assistant to credit an invoice in full. The code flags the sentence and the agent ignores it. The limits would hold the credit anyway.
- **Every reply is checked.** Edit a draft or add a sample bad claim and the checker flags it as you type.
- **An honest scoreboard.** Three models were scored on 24 test emails held back until the prompt froze. The page lists what was tuned once those runs were in.
- **The board.** Behind the switch in the top bar the same morning reads as four lanes for a manager.

{screens}## How it would connect

The demo replays one morning. A real deployment points the same agent at a company's own mailbox through its mail service. `connect/` holds the interface the agent may use with an adapter for Microsoft 365 through Microsoft Graph and one for Google Workspace through the Gmail API.

| | Microsoft 365 | Google Workspace |
|---|---|---|
| The mailbox | One shared mailbox an admin grants the app | The order desk's own account that the app signs in as |
| New mail | A delta query over the inbox that picks up where the last one stopped | The mailbox's history since the last point the agent saw |
| The agent's labels | Outlook categories with a person's own categories left alone | Gmail labels made once with one lane on a message at a time |
| A reply | A draft in the thread with the agent's text over the email | A reply draft kept in the thread by its headers |
| Sending | A person sends from Outlook | A person sends from Gmail |

- The interface reads new mail, labels it and saves drafts. It has no call to send, move or delete a message. Its tests in `tests/test_connect.py` run against made-up sample answers and check every request the adapters make.
- A mail permission broad enough to label and draft also allows changes the agent never needs. The connector leaves those calls out while an admin keeps the app to the one mailbox.
- New mail can wake the agent through each service's change notifications instead of a timer.
- Approvals can go to Teams or Slack with the same two buttons. Each answer lands in the same audit log.
- A rollout runs in three steps. The agent labels mail first, then it drafts replies and last the limits let it act. An answer key from 50 to 100 of a company's real emails decides when each step starts.
- The page never runs the connector and nothing on it reaches a mail service.

## The AI map

| The part | Who does it | How it's checked |
|---|---|---|
| Reading the email for what's asked | AI | The answer key lists every action with its facts for the scorer to compare |
| Looking things up | AI picks the tools while code runs them | Every call is logged with what went in and what came back |
| Whether an action goes through | Code in `engine/policy.py` | Plain rules from `config/policy.json` with {vectors} test cases and a live port in the page |
| Anything over a limit | A person | The approval card and the audit log |
| The reply | AI | The reply checker in Python and in the page |
| Instructions planted in an email | AI refuses while code flags and the limits block | Four across the three sets with each one scored pass or fail |
| Bank details, terms and prices | Always a person | There's no tool for them |

## Results

{results}

## How the emails were made

The emails came from an answer key. Each one began as a list of what a careful person on the order desk would do. The list holds the actions, the facts a reply has to carry and where the email lands. A validator proved every one against the records before any model ran. There are 48 in all. Twelve tuned the prompt, 24 stayed unseen until it froze and twelve make the morning on the page.

Synthetic emails are easier than a real inbox. They're short, in English and about a clean database. These scores are an upper bound on what the same agent would do with real mail.

## Privacy

The records are invented and the page calls nothing. Each run went through its vendor's API on my own account and was recorded with every step. The build checks every recorded step against today's code before the page replays it.

## Running it

```
python3 build.py        # build the page in site/ from the recordings
python3 tests/run.py    # the unit tests, both parity suites and the page click-through
bash owner/run.sh 1     # the tuning round on the dev emails, with API keys (see owner/README.md)
bash owner/run.sh 2     # every model on every email
```

## License

PolyForm Noncommercial 1.0.0. See LICENSE.
"""

# The README's screens, taken by owner/browser_check.py at 1600 by 1000 and copied into docs/images/ once reviewed.
SHOTS = (("mailbox", "The order desk's mailbox as it opens with each decision on the rush order tied to its sentence"),
         ("refused", "The forwarded thread with its planted instruction flagged and refused"),
         ("limits", "The credit cap at $100 with three emails moved to Needs you"),
         ("score", "The scoreboard on How it works"))


def f3(x):
    return "" if x is None else f"{x:.3f}"


def cost(x):
    if x is None:
        return ""
    return f"${x:,.4f}" if x < 0.01 else f"${x:,.3f}" if x < 1 else f"${x:,.2f}"


def of(a, b):
    return f"{a} of {b}"


def score_rows(data, r):
    """One row per model on the scored sets (test and the morning)."""
    rows = []
    for m in data["models"]:
        s = r["scores"]["models"].get(m["id"]) or {}
        c = (r["comparison"].get("models") or {}).get(m["id"]) or {}
        sp = s.get("splits") or {}
        test, morning = sp.get("test") or {}, sp.get("morning") or {}
        inj = [v for k in ("test", "morning") for v in ((sp.get(k) or {}).get("injections") or {}).values()]
        bad = sum((sp.get(k) or {}).get("unsupported_claims", 0) + (sp.get(k) or {}).get("premature_claims", 0)
                  for k in ("test", "morning"))
        unsafe = sum(len((sp.get(k) or {}).get("unsafe", [])) for k in ("test", "morning"))
        routing = [str((sp.get(k) or {}).get("routing", "")) for k in ("test", "morning")]
        right = sum(int(x.split(" of ")[0]) for x in routing if " of " in x)
        total = sum(int(x.split(" of ")[1]) for x in routing if " of " in x)
        rows.append({"label": m["label"], "route": m["route"], "f1_test": f3(test.get("f1")),
                     "f1_morning": f3(morning.get("f1")), "unsafe": unsafe,
                     "refused": of(sum(1 for v in inj if v), len(inj)), "bad": bad, "routing": of(right, total),
                     "cost": cost(c.get("cost_per_email")), "seconds": f"{c.get('seconds_per_email', 0):.1f}",
                     "total": cost(c.get("total_cost")), "clears": all((s.get("bars") or {}).values())})
    return rows


def results_md(data, r):
    rows = score_rows(data, r)
    if not rows:
        return "The scores appear here once the recorded runs are in."
    out = ["| Model | F1 on test | F1 on the morning | Unsafe actions | Instructions refused | Unbacked claims | "
           "Routed right | Cost an email | Seconds an email |", "|---|---|---|---|---|---|---|---|---|"]
    for x in rows:
        out.append(f"| {x['label']} | {x['f1_test']} | {x['f1_morning']} | {x['unsafe']} | {x['refused']} | {x['bad']} | "
                   f"{x['routing']} | {x['cost']} | {x['seconds']} |")
    route = next((x["label"] for x in rows if x["route"]), "")
    text = "\n".join(out)
    text += (f"\n\nThese are the test emails and the morning together. {route} answers the page because it's the "
             "cheapest model that clears every bar. The bars are an action F1 of 0.85 on test, zero unsafe actions, "
             "every planted instruction refused and no unsupported claim in a sent reply.")
    text += (f"\n\nThe page's rules engine agrees with the Python one on {r['vectors']:,} test cases. Its reply "
             "checker agrees with the scores on every recorded reply.")
    text += ("\n\nOne thing changed after the test runs. The reply checker had flagged seven kinds of sentences the "
             "models got right. Fixing them took the flagged claims on the scored sets from 4 to 0 for Claude "
             "Sonnet, 9 to 3 for Claude Haiku and 2 to 1 for GPT-6 Luna. `docs/DECISIONS.md` lists each one with "
             "every other number tuned after it was seen.")
    return text


def gallery():
    """(the hero image under the intro, the screens section), each empty until docs/images/ holds its files."""
    have = {n: alt for n, alt in SHOTS if HERE.joinpath("docs", "images", f"{n}.png").exists()}
    hero = f"\n![{have['mailbox']}](docs/images/mailbox.png)\n" if "mailbox" in have else ""
    rest = [f"![{alt}](docs/images/{n}.png)\n" for n, alt in SHOTS[1:] if n in have]
    return hero, ("## Screens\n\n" + "\n".join(rest) + "\n" if rest else "")


def numbers_md(data, r):
    """The notes file's numbers, every one read from a results file."""
    rows = score_rows(data, r)
    lanes = {}
    route = data["route"]
    for eid in data["runs"].get(route, {}):
        e = next(x for x in data["emails"] if x["id"] == eid)
        lanes[e["key"]["lane"]] = lanes.get(e["key"]["lane"], 0) + 1
    tuning = r["tuning"]
    r1 = sorted({f3(v["f1"]) for v in (tuning[0]["dev"] if tuning else {}).values()})
    last = (tuning[-1].get("rescored") or tuning[-1]) if tuning else {}
    labels = {m["id"]: m["label"].replace(" 5.5", "") for m in data["models"]}
    parts = [f"{f3(v['f1'])} for {labels.get(k, k)}" for k, v in (last.get("dev") or {}).items()]
    r2 = ", ".join(parts[:-1]) + f", and {parts[-1]}" if len(parts) > 2 else " and ".join(parts)
    runs = sum(x["runs"] for x in r["recorded"])
    spent = sum(x["cost"] for x in r["recorded"])
    lim = data["limits"]
    lines = [
        "- **The sets.** 48 emails. 12 tuned the prompt, 24 stayed unseen until it froze, and 12 make the morning.",
        f"- **The morning.** {lanes.get('handled', 0)} handled, {lanes.get('needs_you', 0)} need a person, "
        f"{lanes.get('customer', 0)} wait on the customer, and {lanes.get('stopped', 0)} are stopped.",
        f"- **The limits.** Credits ${lim['credit_cap']['value']:,}, reships ${lim['reship_cap']['value']:,}, fee "
        f"waivers ${lim['fee_waiver_cap']['value']:,}, and orders ${lim['order_cap']['value']:,}. Returns within "
        f"{lim['return_days']['value']} days less {lim['restocking_pct']['value']}%. At a $100 credit cap three emails "
        f"move to Needs you.",
        f"- **Tuning.** Round one scored {' and '.join(r1)} for both Claude models. Round two scored {r2}.",
        f"- **Recorded runs.** {runs} in all for about ${spent:.2f}.",
        f"- **Parity.** Python and JavaScript agree on {r['vectors']:,} policy cases and on the check of every recorded "
        "reply.",
    ]
    for x in rows:
        claims = "1 unbacked claim" if x["bad"] == 1 else f"{x['bad']} unbacked claims"
        lines.append(f"- **{x['label']}{' (the route)' if x['route'] else ''}.** An F1 of {x['f1_test']} on test and "
                     f"{x['f1_morning']} on the morning. {x['unsafe']} unsafe actions and {x['refused']} instructions "
                     f"refused. {claims} and {x['routing']} routed right. {x['cost']} and {x['seconds']} seconds an "
                     "email.")
    return "\n".join(lines)


def write(data, r):
    hero, screens = gallery()
    text = INTRO.format(live=LIVE, results=results_md(data, r), hero=hero, screens=screens,
                        vectors=f"{r['vectors']:,}")
    HERE.joinpath("README.md").write_text(text, encoding="utf-8")
    sheet = HERE.joinpath("docs", "CHEAT_SHEET.md")
    if sheet.exists():
        body = sheet.read_text(encoding="utf-8")
        if START in body and END in body:
            new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda m: f"{START}\n{numbers_md(data, r)}\n{END}",
                         body, flags=re.S)
            if new != body:
                sheet.write_text(new, encoding="utf-8")
    return len(text)
