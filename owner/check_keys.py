"""The owner's machine only. One tiny call to each model in the comparison, so a missing key or a renamed model
shows up before the tuning round instead of in the middle of it. Each call is a few tokens.

    python3 owner/check_keys.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from agents import inputs, llm  # noqa: E402
from owner.record_ai_runs import key_for  # noqa: E402


def main():
    cfg = json.loads(HERE.joinpath("config", "models.json").read_text(encoding="utf-8"))
    bad = 0
    for m in cfg["models"]:
        if m["id"] not in cfg["compare"] or not m.get("enabled", True):
            continue
        try:
            backend = llm.backend_for(dict(m, max_tokens=64), key_for, retries=1)
            out = backend.turn("Reply with the single word ready. Don't call a tool.", inputs.tools(),
                               [{"role": "user", "text": "Are you ready?"}])
            print(f"{m['label']}: ready ({out['meta'].get('model') or m['model']}, {out['meta']['ms']} ms)")
        except (RuntimeError, ValueError, SystemExit) as e:
            bad += 1
            print(f"{m['label']}: not ready, {e}")
    if bad:
        print("The lines above say which model isn't ready and why.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
