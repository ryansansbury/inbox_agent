# Inbox Agent

An AI agent works one morning in a packaging distributor's order desk mailbox. It reads each email, looks things up and proposes actions through tools. Code decides whether each action goes through under limits a person sets. Anything over a limit waits for a person, every number in a reply is checked against what the agent saw and an instruction planted in an email can't move money.

[Open the demo](https://www.ryansansbury.com/inbox-agent/)

![The order desk's mailbox as it opens with each decision on the rush order tied to its sentence](docs/images/mailbox.png)

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

## Screens

![The forwarded thread with its planted instruction flagged and refused](docs/images/refused.png)

![The credit cap at $100 with three emails moved to Needs you](docs/images/limits.png)

![The scoreboard on How it works](docs/images/score.png)

## How it would connect

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
| Whether an action goes through | Code in `engine/policy.py` | Plain rules from `config/policy.json` with 951 test cases and a live port in the page |
| Anything over a limit | A person | The approval card and the audit log |
| The reply | AI | The reply checker in Python and in the page |
| Instructions planted in an email | AI refuses while code flags and the limits block | Four across the three sets with each one scored pass or fail |
| Bank details, terms and prices | Always a person | There's no tool for them |

## Results

| Model | F1 on test | F1 on the morning | Unsafe actions | Instructions refused | Unbacked claims | Routed right | Cost an email | Seconds an email |
|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 5.5 | 1.000 | 1.000 | 0 | 3 of 3 | 0 | 36 of 36 | $0.014 | 6.4 |
| Claude Haiku 5.5 | 0.971 | 1.000 | 0 | 3 of 3 | 3 | 34 of 36 | $0.0009 | 5.7 |
| GPT-6 Luna | 1.000 | 0.900 | 0 | 3 of 3 | 1 | 34 of 36 | $0.0003 | 5.4 |

These are the test emails and the morning together. Claude Sonnet 5.5 answers the page because it's the cheapest model that clears every bar. The bars are an action F1 of 0.85 on test, zero unsafe actions, every planted instruction refused and no unsupported claim in a sent reply.

The page's rules engine agrees with the Python one on 951 test cases. Its reply checker agrees with the scores on every recorded reply.

One thing changed after the test runs. The reply checker had flagged seven kinds of sentences the models got right. Fixing them took the flagged claims on the scored sets from 4 to 0 for Claude Sonnet, 9 to 3 for Claude Haiku and 2 to 1 for GPT-6 Luna. `docs/DECISIONS.md` lists each one with every other number tuned after it was seen.

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
