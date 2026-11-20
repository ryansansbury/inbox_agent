"""The owner's machine only. Record the agent's runs, which the scores read and the page replays.

    python3 owner/record_ai_runs.py --split dev --models compare      the tuning round, every model
    python3 owner/record_ai_runs.py --split all --models compare      every model on every email, after the freeze
    python3 owner/record_ai_runs.py --split dev --models claude-haiku one model
    python3 owner/record_ai_runs.py --split all --stand-in            a dry run through the real loop, no network

Each run goes to data/ai_runs/<model>/<email>.json with its prompt hash, its input hash, every step with its input and
result, every turn's tokens, cost and time, and the finish, and adds a line to data/ai_runs/audit.jsonl. A run that
already matches today's prompt and email is skipped, so a stopped round can simply start again. Model runs need the
key frozen, and test and morning runs need the prompt frozen too. The stand-in's dry run goes to data/out/ instead,
since it's never a result.
"""
import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from agents import inputs, llm, loop  # noqa: E402
from evals import freeze  # noqa: E402
from generate import validate  # noqa: E402

RUNS = HERE.joinpath("data", "ai_runs")
DRY = HERE.joinpath("data", "out", "ai_runs_stand_in")
KEY = HERE.joinpath("data", "key", "key.json")


def key_for(service):
    done = subprocess.run(["security", "find-generic-password", "-s", service, "-w"], capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"No key saved as {service}. Run: bash owner/keys.sh {service.rsplit('-', 1)[-1]}")
    return done.stdout.strip()


def config():
    return json.loads(HERE.joinpath("config", "models.json").read_text(encoding="utf-8"))


def cached(path, spec, seq):
    if not path.exists():
        return None
    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("prompt_hash") == inputs.prompt_hash() and rec.get("input_hash") == inputs.input_hash(spec, seq):
        return rec
    return None


def line(run):
    acts = [f"{s['tool']} {s['result'].get('result', '')}".strip() for s in run["steps"]
            if s["tool"] not in ("get_customer", "get_order", "get_shipment", "check_stock", "get_price",
                                 "find_equivalents", "get_invoice", "find_orders")]
    u = run["usage"]
    cost = f"${u['cost']:.4f}" if u.get("cost") is not None else "cost unknown"
    end = "UNFINISHED" if run["unfinished"] else ("repaired" if run["repaired"] else "finished")
    return f"{run['calls']} calls, {', '.join(acts) or 'no actions'}, {end}, {cost}, {u['seconds']} s"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--split", required=True, choices=["dev", "test", "morning", "all"])
    ap.add_argument("--models", default="default", help="default, compare, or a model id")
    ap.add_argument("--emails", default="", help="only these, comma-separated")
    ap.add_argument("--stand-in", action="store_true", help="a dry run through the real loop, with no model")
    a = ap.parse_args(argv)
    if not freeze.ready("key"):
        raise SystemExit("The key has to be frozen and unchanged before any run. Check with: python3 evals/freeze.py --check")
    if a.split != "dev" and not a.stand_in and not freeze.ready("prompt"):
        raise SystemExit("The prompt isn't frozen yet, so only the dev round can run. Run B freezes it after the "
                         "tuning round.")
    specs = validate.load_specs()
    seqs = inputs.sequence(specs)
    chosen = [s for s in specs if (a.split == "all" or s["split"] == a.split)
              and (not a.emails or s["id"] in a.emails.split(","))]
    chosen.sort(key=lambda s: seqs[s["id"]])
    if a.stand_in:
        from owner import stand_in
        key = json.loads(KEY.read_text(encoding="utf-8"))
        models = [("stand-in", None)]
    else:
        cfg = config()
        by_id = {m["id"]: m for m in cfg["models"]}
        ids = cfg["compare"] if a.models == "compare" else [cfg["default"]] if a.models == "default" else [a.models]
        models = [(i, by_id[i]) for i in ids if by_id[i].get("enabled", True)]
    print(f"Recording {len(chosen)} emails with {', '.join(m for m, _ in models)}, prompt {inputs.prompt_hash()}")
    failed = []
    for model_id, entry in models:
        folder = DRY if a.stand_in else RUNS.joinpath(model_id)
        folder.mkdir(parents=True, exist_ok=True)
        backend = None if a.stand_in else llm.backend_for(entry, key_for)
        label = "Stand-in (no model)" if a.stand_in else entry["label"]
        for s in chosen:
            path = folder.joinpath(f"{s['id']}.json")
            seq = seqs[s["id"]]
            if cached(path, s, seq):
                print(f"  {s['id']} {model_id}: already recorded with this prompt")
                continue
            if a.stand_in:
                backend = stand_in.Backend(stand_in.run_email(s, key[s["id"]], seq))
            try:
                run = loop.run_email(backend, s, seq, model_id, label)
            except RuntimeError as e:
                print(f"  {s['id']} {model_id}: stopped, {e}")
                failed.append(model_id)
                break
            run.update(kind="stand_in" if a.stand_in else "model", date=date.today().isoformat(),
                       recorded_at=datetime.now().isoformat(timespec="seconds"),
                       backend=backend.described())
            path.write_text(json.dumps(run, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            if not a.stand_in:
                with RUNS.joinpath("audit.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"at": run["recorded_at"], "email": s["id"], "model": model_id,
                                        "calls": run["calls"], "unfinished": run["unfinished"],
                                        "tokens_in": run["usage"].get("input_tokens"),
                                        "tokens_out": run["usage"].get("output_tokens"),
                                        "cost": run["usage"].get("cost"), "seconds": run["usage"]["seconds"]}) + "\n")
            print(f"  {s['id']} {model_id}: {line(run)}")
    if failed:
        print(f"Stopped early for {', '.join(failed)}. The other models' runs are saved.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
