# Owner steps

These steps need the network, an API key or Chrome. Each one runs in a normal terminal from the project folder and is safe to start again.

| Step | Command | What it does | Time |
|---|---|---|---|
| Setup | `bash owner/bootstrap.sh` | Checks for Python 3.11 with Node 18 before it builds the page and runs every test | about a minute |
| Keys | `bash owner/keys.sh anthropic` then `bash owner/keys.sh openai` | Saves each vendor's API key in the macOS Keychain and never in a file | a minute |
| Run A | `bash owner/run.sh 1` | The key check, a one-line call to each model and the tuning round on the twelve dev emails | about 15 minutes |
| Run B | `bash owner/run.sh 2` | The tuning round again, the freeze, every model on all 48 emails and the scores | about an hour |
| Browser check | `python3 owner/browser_check.py` | About a hundred screenshots in Chrome from 1600 wide down to a phone, the layout checks and a review page at `owner/out/review.html` | about two minutes |

Run A and run B ran on November 9. Their recordings are in `data/ai_runs/`. The page replays them and needs no key to build.
