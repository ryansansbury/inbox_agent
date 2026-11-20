"""Freeze the key, then the prompt, so nothing scored is tuned after the fact.

    python3 evals/freeze.py key         once the morning is approved: the fixtures, the 48 emails, the
                                        compiled key, the limits, the cast and the tool schemas
    python3 evals/freeze.py prompt      after the dev round: the agent prompt, the tool descriptions, the agent
                                        loop, and the engine and scorer that decide and score
    python3 evals/freeze.py --check     list anything changed since it was frozen, and exit 1 if so

Each stage writes its hashes into evals/frozen.json once. Freezing a stage again needs --again, and the old hashes
move to "history" with the time, so a change after the fact shows. The tool schemas belong to the key and the tool
descriptions to the prompt, since the dev round may reword a description but never what a tool takes. The recorder
refuses model runs until the key is frozen, and test and morning runs until the prompt is. The validator has to pass
before the key freezes. Standard library only.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

FROZEN = HERE.joinpath("evals", "frozen.json")
STAGES = {
    "key": ["data/fixtures/*.json", "data/emails/*/*.json", "data/key/key.json", "config/policy.json",
            "config/names.json"],
    "prompt": ["prompts/*.md", "evals/score.py", "engine/replies.py", "engine/injection.py", "engine/policy.py",
               "engine/facts.py", "engine/tools.py", "engine/db.py", "agents/*.py"],
}


def sha(data):
    return hashlib.sha256(data).hexdigest()[:16]


def tools_part(part):
    """The tool schemas (names and inputs) or their descriptions, hashed apart."""
    raw = json.loads(HERE.joinpath("config", "tools.json").read_text(encoding="utf-8"))
    tools = raw["read"] + raw["action"] + [raw["finish"]]
    if part == "schemas":
        body = [{"name": t["name"], "input_schema": _strip(t["input_schema"])} for t in tools]
    else:
        body = [{"name": t["name"], "description": t["description"], "fields": _descriptions(t["input_schema"])}
                for t in tools]
    return sha(json.dumps(body, sort_keys=True).encode())


def _strip(schema):
    if isinstance(schema, dict):
        return {k: _strip(v) for k, v in schema.items() if k != "description"}
    if isinstance(schema, list):
        return [_strip(x) for x in schema]
    return schema


def _descriptions(schema, path=""):
    out = {}
    if isinstance(schema, dict):
        if "description" in schema:
            out[path or "."] = schema["description"]
        for k, v in schema.items():
            if k != "description":
                out.update(_descriptions(v, f"{path}/{k}"))
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            out.update(_descriptions(v, f"{path}/{i}"))
    return out


def current(stage):
    out = {}
    for pattern in STAGES[stage]:
        for p in sorted(HERE.glob(pattern)):
            out[p.relative_to(HERE).as_posix()] = sha(p.read_bytes())
    out["config/tools.json#" + ("schemas" if stage == "key" else "descriptions")] = tools_part(
        "schemas" if stage == "key" else "descriptions")
    return out


def load():
    return json.loads(FROZEN.read_text(encoding="utf-8")) if FROZEN.exists() else {}


def now():
    return datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(timespec="seconds")


def freeze(stage, again=False):
    data = load()
    if stage in data and not again:
        raise SystemExit(f"{stage} is already frozen at {data['at'][stage]}. Use --again to refreeze, and the old "
                         f"hashes go to history.")
    if stage == "key":
        ok = subprocess.run([sys.executable, str(HERE.joinpath("generate", "validate.py"))], capture_output=True,
                            text=True)
        if ok.returncode != 0:
            raise SystemExit("The validator fails, so the key can't freeze. Run generate/validate.py.")
    if stage == "prompt" and "key" not in data:
        raise SystemExit("Freeze the key first.")
    if stage in data:
        data.setdefault("history", []).append({"stage": stage, "at": data["at"][stage], "replaced": now(),
                                               "hashes": data[stage]})
    data[stage] = current(stage)
    data.setdefault("at", {})[stage] = now()
    FROZEN.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return data


def changed(stage):
    """What differs from the frozen hashes: [(name, why)]. None when the stage isn't frozen."""
    data = load()
    if stage not in data:
        return None
    then, now_hashes = data[stage], current(stage)
    out = []
    for name in sorted(set(then) | set(now_hashes)):
        if name not in now_hashes:
            out.append((name, "removed"))
        elif name not in then:
            out.append((name, "added"))
        elif then[name] != now_hashes[name]:
            out.append((name, "changed"))
    return out


def ready(stage):
    c = changed(stage)
    return c is not None and not c


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", nargs="?", choices=list(STAGES))
    ap.add_argument("--again", action="store_true", help="refreeze a stage, keeping the old hashes in history")
    ap.add_argument("--check", action="store_true", help="list changes since each stage was frozen")
    a = ap.parse_args(argv)
    if a.check or not a.stage:
        bad = False
        for stage in STAGES:
            c = changed(stage)
            if c is None:
                print(f"{stage}: not frozen yet")
                continue
            print(f"{stage}: frozen {load()['at'][stage]}, {'unchanged' if not c else f'{len(c)} changed'}")
            for name, why in c:
                print(f"  {why}: {name}")
                bad = True
        return 1 if bad else 0
    data = freeze(a.stage, a.again)
    print(f"Froze {a.stage} at {data['at'][a.stage]}: {len(data[a.stage])} hashes in evals/frozen.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
