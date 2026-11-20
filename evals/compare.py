"""Score every model's recorded runs, compare them, and pick the route.

    python3 evals/compare.py           write evals/scores.json and evals/model_comparison.json
    python3 evals/compare.py --round   also add today's prompt and its dev scores to evals/tuning_rounds.json

Each model's runs are checked by agents/replay.py first, and a model with a run that doesn't replay is reported, not
scored. The route is the cheapest model per email that meets every bar on the test emails, or, when none does, the
one with no unsafe action and the best test F1.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from agents import inputs, replay  # noqa: E402
from evals import score  # noqa: E402
from generate import validate  # noqa: E402

RUNS = HERE.joinpath("data", "ai_runs")
SCORES = HERE.joinpath("evals", "scores.json")
COMPARISON = HERE.joinpath("evals", "model_comparison.json")
ROUNDS = HERE.joinpath("evals", "tuning_rounds.json")


def models():
    return json.loads(HERE.joinpath("config", "models.json").read_text(encoding="utf-8"))


def score_model(model_id, specs, seqs):
    folder = RUNS.joinpath(model_id)
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))] if folder.exists() else []
    broken = {r["email_id"]: replay.problems(r, specs[r["email_id"]], seqs) for r in runs}
    broken = {k: v for k, v in broken.items() if v}
    key = json.loads(HERE.joinpath("data", "key", "key.json").read_text(encoding="utf-8"))
    scored = [score.score_run(r, specs[r["email_id"]], key[r["email_id"]]) for r in runs if r["email_id"] not in broken]
    summary = score.summarize(scored)
    costs = [r["usage"]["cost"] for r in runs if r["usage"].get("cost") is not None]
    secs = [r["usage"]["seconds"] for r in runs]
    return {"runs": len(runs), "replay_problems": broken, "splits": summary,
            "bars": score.bars(summary) if "test" in summary else None,
            "cost_per_email": round(sum(costs) / len(costs), 5) if costs else None,
            "seconds_per_email": round(sum(secs) / len(secs), 1) if secs else None,
            "total_cost": round(sum(costs), 4) if costs else None, "emails": [s for s in scored]}


def pick(results):
    ready = {m: r for m, r in results.items() if r["bars"] and all(r["bars"].values()) and not r["replay_problems"]}
    if ready:
        return min(ready, key=lambda m: (ready[m]["cost_per_email"] or 0, m)), "the cheapest model that meets every bar"
    safe = {m: r for m, r in results.items() if "test" in r["splits"] and not r["splits"]["test"]["unsafe"]}
    pool = safe or {m: r for m, r in results.items() if "test" in r["splits"]}
    if not pool:
        return None, "no test runs yet"
    best = max(pool, key=lambda m: (pool[m]["splits"]["test"]["f1"], -(pool[m]["cost_per_email"] or 0)))
    return best, "no model meets every bar, so the safest with the best test F1"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--round", action="store_true", help="log today's prompt and its dev scores as a tuning round")
    a = ap.parse_args(argv)
    cfg = models()
    specs = {s["id"]: s for s in validate.load_specs()}
    seqs = inputs.sequence(list(specs.values()))
    results = {}
    for m in cfg["models"]:
        if m["id"] in cfg["compare"] and m.get("enabled", True):
            results[m["id"]] = score_model(m["id"], specs, seqs)
    for mid, r in results.items():
        label = next(m["label"] for m in cfg["models"] if m["id"] == mid)
        print(f"{label}: {r['runs']} runs, ${r['cost_per_email'] or 0:.4f} and {r['seconds_per_email'] or 0} s an email"
              + (f", {len(r['replay_problems'])} that don't replay" if r["replay_problems"] else ""))
        for split, s in r["splits"].items():
            print(f"  {split:8} F1 {s['f1']:.3f} (P {s['precision']:.3f}, R {s['recall']:.3f})  unsafe {len(s['unsafe'])}"
                  f"  injections {sum(s['injections'].values())} of {len(s['injections'])}  routing {s['routing']}"
                  f"  facts {s['facts']}  bad claims {s['unsupported_claims'] + s['premature_claims']}"
                  f"  unfinished {s['unfinished']}")
    route, why = pick(results)
    SCORES.write_text(json.dumps({"prompt_hash": inputs.prompt_hash(), "scored": date.today().isoformat(),
                                  "models": results}, indent=1) + "\n", encoding="utf-8")
    COMPARISON.write_text(json.dumps({
        "prompt_hash": inputs.prompt_hash(), "scored": date.today().isoformat(), "route": route, "why": why,
        "models": {m: {k: v for k, v in r.items() if k != "emails"} for m, r in results.items()}}, indent=1) + "\n",
        encoding="utf-8")
    print(f"Route: {route or 'not picked yet'} ({why}). Wrote evals/scores.json and evals/model_comparison.json.")
    if a.round:
        log = json.loads(ROUNDS.read_text(encoding="utf-8")) if ROUNDS.exists() else {"rounds": []}
        entry = {"round": len(log["rounds"]) + 1, "date": date.today().isoformat(), "prompt_hash": inputs.prompt_hash(),
                 "dev": {m: {k: r["splits"]["dev"][k] for k in ("f1", "precision", "recall", "routing", "facts",
                                                                   "unsupported_claims", "premature_claims",
                                                                   "unfinished")}
                         | {"unsafe": len(r["splits"]["dev"]["unsafe"])}
                         for m, r in results.items() if "dev" in r["splits"]}}
        log["rounds"].append(entry)
        ROUNDS.write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")
        print(f"Logged tuning round {entry['round']} in evals/tuning_rounds.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
