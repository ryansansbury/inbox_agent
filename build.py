"""Build the Inbox Agent page from the recorded data.

    python3 build.py

It stops if the fixtures or the email specs differ from what their sources build, or if the validator finds any truth
the records don't support. Then it replays every recorded morning run on today's engine (app/bundle.py stops on any
step that returns something else), writes site/data.js, renders site/index.html with How it works from the scores,
copies the source into site/code.js, and writes the README with the same numbers. It stops if a word from the
never list or another demo's name reaches anything that ships, the data and the code included, or if the first load
passes a megabyte. Standard library only.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from app import bundle, code_view, never, page, readme, results, words  # noqa: E402
from generate import emails, fixtures, validate  # noqa: E402

SITE = HERE.joinpath("site")
FONTS = ("inter-latin.woff2", "jetbrains-mono-latin.woff2", "Inter-LICENSE.txt", "JetBrainsMono-OFL.txt")
FIRST_LOAD = ("index.html", "app.css", "app.js", "data.js", "policy.js", "replies.js", "fonts/inter-latin.woff2",
              "fonts/jetbrains-mono-latin.woff2")
BUDGET = 1024 * 1024


def check_world():
    world = fixtures.build()
    stale = [n for n, v in world.items() if not HERE.joinpath("data", "fixtures", f"{n}.json").exists() or
             HERE.joinpath("data", "fixtures", f"{n}.json").read_text(encoding="utf-8") !=
             json.dumps(v, indent=1, ensure_ascii=False) + "\n"]
    stale += [s["id"] for s in emails.specs() if not emails.path_for(s).exists() or
              emails.path_for(s).read_text(encoding="utf-8") != emails.dump(s)]
    if stale:
        sys.exit(f"Stopped: rebuild the world first, {', '.join(stale)} differ from their sources "
                 "(python3 generate/fixtures.py, then python3 generate/emails.py).")
    specs = validate.load_specs()
    broken = [s["id"] for s in specs if validate.check(s)[0]] + validate.check_set(specs)[0]
    if broken:
        sys.exit(f"Stopped: the validator fails ({', '.join(broken)}). Run python3 generate/validate.py.")
    return specs


def main():
    t0 = time.time()
    specs = check_world()
    w = words.load()
    missing = [f for f in FONTS if not SITE.joinpath("fonts", f).exists()]
    if missing:
        sys.exit(f"Stopped: site/fonts/ is missing {', '.join(missing)}.")
    data = bundle.build(w)
    if not data["runs"]:
        sys.exit("Stopped: no recorded morning runs in data/ai_runs/. Run the owner's recording first.")
    r = results.gather(data["models"])
    SITE.joinpath("index.html").write_text(page.render(w, data, r), encoding="utf-8")
    bundle.write(data)
    readme.write(data, r)
    code_view.write(code_view.collect())
    shipped = [SITE.joinpath(n) for n in ("index.html", "app.css", "app.js", "data.js", "code.js", "policy.js",
                                         "replies.js")]
    shipped += [HERE.joinpath("WORDS.md"), HERE.joinpath("README.md"), HERE.joinpath("config", "names.json")]
    shipped += sorted(HERE.joinpath("docs").glob("*.md"))
    shipped += sorted(HERE.joinpath("data", "fixtures").glob("*.json")) + sorted(HERE.joinpath("data", "emails").glob("*/*.json"))
    problems = never.scan(shipped)
    if problems:
        sys.exit("Stopped: " + "; ".join(problems))
    weight = sum(SITE.joinpath(n).stat().st_size for n in FIRST_LOAD)
    if weight > BUDGET:
        sys.exit(f"Stopped: the first load is {weight / 1024:.0f} KB, over the {BUDGET // 1024} KB budget.")
    runs = sum(len(v) for v in data["runs"].values())
    print(f"Checked the world ({len(specs)} emails), replayed {runs} recorded morning runs and built the page in "
          f"{time.time() - t0:.2f} s. First load {weight / 1024:.0f} KB, the code view "
          f"{SITE.joinpath('code.js').stat().st_size / 1024:.0f} KB on demand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
