"""The code section of How it works: the project's real source, copied into the page on every build.

An allowlist picks the folders. The planning files, the references, the recordings, the private tools and the name
lists never go in, and the build's never-word scan reads the code with the rest of the page. The files go to
site/code.js as data apart from the page's script, and the page loads that file only when How it works opens.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FOLDERS = ("engine", "agents", "connect", "prompts", "app", "generate", "evals", "owner", "config", "tests")
TOP = ("build.py", "WORDS.md", "site/app.js", "site/app.css", "site/policy.js", "site/replies.js")
SUFFIXES = (".py", ".js", ".css", ".md", ".sh", ".json")
SKIP = ("owner/out/", "evals/frozen.json", "evals/scores.json", "evals/model_comparison.json",
        "evals/tuning_rounds.json", "tests/vectors/")
DEFAULT = "engine/policy.py"
FEATURED = ("engine/policy.py", "engine/tools.py", "engine/replies.py", "engine/injection.py", "evals/score.py")


def collect(root=HERE):
    """{path: text} for every file the code section shows."""
    root = Path(root)
    paths = [root.joinpath(t) for t in TOP]
    for folder in FOLDERS:
        if root.joinpath(folder).exists():
            paths += sorted(root.joinpath(folder).rglob("*"))
    files = {}
    for p in paths:
        rel = p.relative_to(root).as_posix()
        if p.is_file() and p.suffix in SUFFIXES and "__pycache__" not in rel and not rel.startswith(SKIP):
            files[rel] = p.read_text(encoding="utf-8")
    return files


def write(files, path=None):
    path = Path(path or HERE.joinpath("site", "code.js"))
    path.write_text("window.IACODE = " + json.dumps({"files": files, "default": DEFAULT, "featured": list(FEATURED)},
                                                     ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    return path.stat().st_size
