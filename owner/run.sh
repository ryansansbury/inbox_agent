#!/bin/bash
# The owner's machine only. The agent's recordings in two runs, with a stop between them to revise the prompt. Each run is
# safe to start again, since a recorded run that matches today's prompt and email is skipped.
#
#   bash owner/run.sh 1   Run A (about 15 minutes): the check, the keys, a one-line call to each model, then the
#                         tuning round, every model on the twelve dev emails. Then read the results and revise the
#                         prompt.
#   bash owner/run.sh 2   Run B (about an hour, unattended): the tuning round again on the revised prompt and the
#                         freeze, then every model on all 48 emails, and the scores.
#
# Run from the build folder:   bash owner/run.sh 1
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n== %s\n' "$*"; }
have() { security find-generic-password -s "$1" >/dev/null 2>&1; }
key_from() {
  local vendor="$1"
  shift
  if have "inbox-agent-$vendor"; then
    echo "The $vendor key is saved as inbox-agent-$vendor."
    return 0
  fi
  for service in "$@"; do
    if have "$service"; then
      bash owner/keys.sh "$vendor" --from "$service"
      return 0
    fi
  done
  return 1
}
frozen() {
  python3 -c "import sys; sys.path.insert(0, '.'); from evals import freeze; sys.exit(0 if freeze.ready('$1') else 1)"
}

one() {
  say "The check"
  bash owner/bootstrap.sh
  say "The keys"
  if ! key_from anthropic; then
    echo "No Anthropic API key is in the Keychain yet. Copy your key from the Anthropic console, then run:"
    echo "  bash owner/keys.sh anthropic"
    echo "and start this run again."
    exit 1
  fi
  if ! key_from openai; then
    echo "No OpenAI key is in the Keychain yet. Copy your key from the OpenAI dashboard, then run:"
    echo "  bash owner/keys.sh openai"
    echo "and start this run again."
    exit 1
  fi
  say "A one-line call to each model"
  python3 owner/check_keys.py
  say "The tuning round: every model on the twelve dev emails"
  status=0
  python3 owner/record_ai_runs.py --split dev --models compare || status=$?
  python3 evals/compare.py --round
  echo
  if [ "$status" -ne 0 ]; then
    echo "Run A stopped early for a model. The lines above say why."
    exit 1
  fi
  echo "Run A is done, and the tuning round is recorded. Revise the prompt, then start run B."
}

two() {
  if ! frozen key; then
    echo "The answer key isn't frozen and unchanged. Freeze it with python3 evals/freeze.py key before run B."
    exit 1
  fi
  if ! frozen prompt; then
    say "The tuning round again on the revised prompt"
    if ! python3 owner/record_ai_runs.py --split dev --models compare; then
      echo "A model stopped early in the tuning round. The lines above say why."
      exit 1
    fi
    python3 evals/compare.py --round
    python3 - <<'PY'
import json
import sys
from pathlib import Path
sys.path.insert(0, ".")
from evals import freeze
rounds = json.loads(Path("evals/tuning_rounds.json").read_text())["rounds"]
last, earlier = rounds[-1], rounds[:-1]
def mean(r, models):
    f1 = [r["dev"][m]["f1"] for m in models]
    return sum(f1) / len(f1), sum(r["dev"][m]["unsafe"] for m in models)
pairs = [(r, sorted(set(r["dev"]) & set(last["dev"]))) for r in earlier]
best = max((mean(r, ms) + (ms,) for r, ms in pairs if ms), default=(0.0, 0, sorted(last["dev"])),
           key=lambda x: (x[0], -x[1]))
now = mean(last, best[2])
print(f"Dev F1 across the models: {now[0]:.3f} with {now[1]} unsafe, against {best[0]:.3f} with {best[1]} before.")
if now[0] < best[0] or now[1] > best[1]:
    sys.exit("The revised prompt did worse on the dev emails and isn't frozen.")
freeze.freeze("prompt")
print("Froze the prompt, the tool descriptions and the code that scores.")
PY
  fi
  say "Every model on all 48 emails"
  python3 owner/record_ai_runs.py --split all --models compare
  say "The scores"
  python3 evals/compare.py
  echo
  echo "Run B is done, and the runs are recorded. python3 build.py builds the page from them."
}

case "${1:-}" in
  1) one ;;
  2) two ;;
  *) echo "Usage: bash owner/run.sh 1|2   (see the top of this file)"; exit 1 ;;
esac
