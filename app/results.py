"""The numbers How it works shows, gathered from the scores, the comparison, the tuning log, the freeze and the
recordings. Nothing here is typed by hand: every figure on the page comes from a file the scorer or the recorder wrote.

    r = gather()
"""
import json
from datetime import datetime
from pathlib import Path

from engine import db, injection, policy
from generate import validate

HERE = Path(__file__).resolve().parent.parent
SCORED = ("test", "morning")


def read(*parts, default=None):
    p = HERE.joinpath(*parts)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _runs(model):
    out = []
    for p in sorted(HERE.joinpath("data", "ai_runs", model).glob("*.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def recorded(models):
    """Per model: how many runs, which prompt, when, and the tokens and cost they took."""
    rows = []
    for m in models:
        runs = _runs(m["id"])
        if not runs:
            continue
        u = [r.get("usage") or {} for r in runs]
        stamps = sorted(r.get("recorded_at", "") for r in runs if r.get("recorded_at"))
        rows.append({"model": m["id"], "label": m["label"], "runs": len(runs),
                     "prompts": sorted({r.get("prompt_hash", "") for r in runs}),
                     "first": stamps[0] if stamps else "", "last": stamps[-1] if stamps else "",
                     "input": sum(x.get("input_tokens", 0) for x in u),
                     "output": sum(x.get("output_tokens", 0) for x in u),
                     "cached": sum(x.get("cache_read_tokens", 0) for x in u),
                     "cost": sum(x.get("cost", 0) for x in u)})
    return rows


def injections(models, scores):
    """Each planted instruction across the sets: what it asks, whether the code flagged it, each model's refusal and
    what the limits would say to the action it asks for."""
    world = db.load()
    limits = policy.defaults()
    rows, flagged_elsewhere, planted = [], 0, 0
    from app.bundle import what_if  # the same reading of the sentence the page uses
    specs = validate.load_specs()
    for spec in specs:
        n = spec["truth"].get("instruction")
        hit = [f["n"] for f in injection.flags(spec)]
        if not n:
            flagged_elsewhere += len(hit)  # a flag in an email with nothing planted is a false alarm
            continue
        planted += 1
        wi = what_if(spec, world, limits)
        verdict = policy.decide(wi["tool"], wi["facts"], limits) if wi else None
        refused = {}
        for m in models:
            split = ((scores.get("models", {}).get(m["id"]) or {}).get("splits") or {}).get(spec["split"]) or {}
            refused[m["id"]] = split.get("injections", {}).get(spec["id"])
        rows.append({"id": spec["id"], "split": spec["split"], "flagged": n in hit, "what_if": wi,
                     "verdict": verdict, "refused": refused})
    return {"rows": rows, "planted": planted, "elsewhere": flagged_elsewhere, "others": len(specs) - planted,
            "cap": limits["credit_cap"]}


def checker(models, scores):
    """The reply checker's results on the scored sets, per model, and every claim it flagged there."""
    rows, flagged = [], []
    for m in models:
        s = scores.get("models", {}).get(m["id"]) or {}
        tot = {"supported": 0, "unsupported": 0, "premature": 0}
        for e in s.get("emails", []):
            if e["split"] not in SCORED:
                continue
            for k in tot:
                tot[k] += (e.get("claims") or {}).get(k, 0)
            for c in e.get("bad_claims", []):
                flagged.append({"model": m["label"], "email": e["email_id"], "text": c["text"],
                                "status": c["status"], "reason": c["reason"]})
        rows.append({"model": m["id"], "label": m["label"], "checked": sum(tot.values()), **tot})
    return {"rows": rows, "flagged": flagged}


def vectors():
    v = read("tests", "vectors", "policy.json", default={})
    return sum(len(x) for x in v.values() if isinstance(x, list))


def froze():
    """When the prompt stage first froze, and whether the prompt itself is the same in every freeze since. The later
    entries are refreezes of the scoring code, each kept in the history with what it replaced."""
    f = read("evals", "frozen.json", default={})
    entries = [h for h in f.get("history", []) if h.get("stage") == "prompt"]
    current = f.get("prompt") or {}
    first = entries[0]["at"] if entries else (f.get("at") or {}).get("prompt")
    if not first:
        return None
    hashes = [h.get("hashes", {}).get("prompts/agent.md") for h in entries]
    hashes.append((current.get("hashes") or current).get("prompts/agent.md"))
    d = datetime.fromisoformat(first)
    return {"day": f"{d.strftime('%B')} {d.day}", "first": first, "refreezes": len(entries),
            "prompt_same": len({x for x in hashes if x}) == 1 and all(hashes)}


def tuning():
    t = read("evals", "tuning_rounds.json", default={"rounds": []})
    return t["rounds"]


def gather(models):
    scores = read("evals", "scores.json", default={"models": {}})
    comp = read("evals", "model_comparison.json", default={})
    return {"scores": scores, "comparison": comp, "injections": injections(models, scores),
            "checker": checker(models, scores), "recorded": recorded(models), "vectors": vectors(),
            "froze": froze(), "tuning": tuning()}
