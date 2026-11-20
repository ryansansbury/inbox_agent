"""Write the 48 email specs as JSON under data/emails/<split>/<id>.json.

    python3 generate/emails.py          write them
    python3 generate/emails.py --check  fail if the files on disk differ

The emails are written in generate/inbox_morning.py, inbox_dev.py and inbox_test.py. This numbers every sentence in
reading order (the body's paragraphs, then each quoted message's), so an action, an instruction or a thread on the page
can point at one.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from generate import inbox_dev, inbox_morning, inbox_test  # noqa: E402

OUT = HERE.joinpath("data", "emails")
SPLITS = {"morning": inbox_morning.EMAILS, "dev": inbox_dev.EMAILS, "test": inbox_test.EMAILS}


def numbered(email):
    """[{"n", "text", "part"}] in reading order, part being "body" or "quoted:<i>"."""
    out = []
    for para in email["body"]:
        for s in para:
            out.append({"n": len(out) + 1, "text": s, "part": "body"})
    for i, q in enumerate(email["quoted"]):
        for para in q["body"]:
            for s in para:
                out.append({"n": len(out) + 1, "text": s, "part": f"quoted:{i}"})
    return out


def specs():
    out = []
    for split, emails in SPLITS.items():
        for e in emails:
            spec = dict(e, split=split)
            spec["sentences"] = numbered(e)
            out.append(spec)
    return out


def path_for(spec):
    return OUT.joinpath(spec["split"], f"{spec['id']}.json")


def dump(spec):
    return json.dumps(spec, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if the files on disk differ")
    a = ap.parse_args(argv)
    all_specs = specs()
    ids = [s["id"] for s in all_specs]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        sys.exit(f"Stopped: duplicate email ids {', '.join(dup)}")
    if a.check:
        bad = [s["id"] for s in all_specs if not path_for(s).exists() or path_for(s).read_text(encoding="utf-8") != dump(s)]
        on_disk = {p.stem for p in OUT.glob("*/*.json")}
        extra = sorted(on_disk - set(ids))
        print("The email specs match their sources." if not bad and not extra else
              f"Differs from the sources: {', '.join(bad + extra)}")
        return 1 if bad or extra else 0
    for split in SPLITS:
        OUT.joinpath(split).mkdir(parents=True, exist_ok=True)
        for old in OUT.joinpath(split).glob("*.json"):
            if old.stem not in ids:
                old.unlink()
    for s in all_specs:
        path_for(s).write_text(dump(s), encoding="utf-8")
    counts = {k: len(v) for k, v in SPLITS.items()}
    print(f"Wrote {len(all_specs)} email specs: {counts['morning']} morning, {counts['dev']} dev, {counts['test']} test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
