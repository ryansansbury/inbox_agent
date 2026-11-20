"""No phrase twice on the page. Any five words in a row that appear in two entries a reader can see fail the test.

Entries that are alternatives of each other never show together (one or many, on or off, the variants of a summary
line), so they're only compared with the rest. Card labels repeat by design, one per card, and the meta description
isn't on the page. Everything else in WORDS.md counts, the tour and How it works included."""
import re
import unittest
from collections import defaultdict

from app import words

N = 5
# Tables whose entries are variants, of which the page shows one at a time.
ALTERNATIVES = ("ui.claims", "ui.drafted", "ui.what_if", "ui.moved", "ui.steps", "ui.pill", "ui.turn", "ui.ignored",
                "ui.reply_none", "ui.time", "ui.verdict", "ui.edit", "ui.raw", "ui.replay", "ui.sample_text",
                "ui.status", "ui.key", "ui.act", "ui.tour", "ui.limits")
GROUPS = ({"how.inject.all", "how.inject.none_other", "how.inject.some"}, {"how.checker.flagged", "how.checker.none"},
          {"ui.tour_text.5", "ui.tour_touch.5"})
# Labels that repeat once per card or row by design, and words that never reach the page as prose.
LABELS = ("ui.did", "ui.chip", "ui.intent", "ui.check", "ui.who", "ui.team", "ui.what_short", "ui.logwhat", "ui.actor",
          "ui.unit", "ui.detail", "step.", "page.description", "page.aria", "page.links", "how.map.cols",
          "how.score.cols", "how.compare.cols", "how.connect.cols", "how.runs.cols", "how.checker.cols", "how.inject.cols")


def entries():
    w = words.load()
    out = {}
    for key, raw in w.raw.items():
        if key.startswith(LABELS):
            continue
        rows = [ln.strip()[2:] for ln in raw.splitlines() if ln.strip().startswith("- ") and " = " in ln]
        if rows:
            for row in rows:
                name, _, label = row.partition(" = ")
                out[f"{key}.{name.strip()}"] = label.replace("|", " | ")
        else:
            out[key] = w.entries[key]
    return out


def alternatives(a, b):
    if any(a in g and b in g for g in GROUPS):
        return True
    for table in ALTERNATIVES:
        if a.startswith(table + ".") and b.startswith(table + "."):
            return True
    base = lambda k: re.sub(r"\.(on|off)$", "", k)  # noqa: E731
    return a.startswith("ui.rule_line.") and b.startswith("ui.rule_line.") and base(a) == base(b)


def grams(text):
    for part in re.sub(r"\{\w+\}", " | ", text).split("|"):
        toks = re.findall(r"[a-z0-9']+", part.lower())
        for i in range(len(toks) - N + 1):
            yield " ".join(toks[i:i + N])


class NoRepeatedPhrase(unittest.TestCase):
    def test_no_five_word_phrase_shows_twice(self):
        seen = defaultdict(set)
        for key, text in entries().items():
            for g in grams(text):
                seen[g].add(key)
        clashes = []
        for g, keys in seen.items():
            keys = sorted(keys)
            pairs = [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:] if not alternatives(a, b)]
            if pairs:
                clashes.append(f"{g!r} in {pairs[0][0]} and {pairs[0][1]}")
        self.assertEqual(sorted(clashes), [])

    def test_no_phrase_repeats_inside_one_entry(self):
        doubled = []
        for key, text in entries().items():
            gs = list(grams(text))
            dup = {g for g in gs if gs.count(g) > 1}
            if dup:
                doubled.append(f"{key}: {sorted(dup)[0]!r}")
        self.assertEqual(doubled, [])


if __name__ == "__main__":
    unittest.main()


class WritingRule(unittest.TestCase):
    """The owner's writing rule of 11/16 on every word that ships, when the private lint is here. The public copy
    doesn't carry tools/, so it skips there."""

    def test_the_page_and_the_docs_pass_the_lint(self):
        import subprocess
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        lint = root.joinpath("tools", "lint_copy.py")
        if not lint.exists():
            self.skipTest("the lint stays private")
        runs = [["--strict", "WORDS.md"]] + [["--strict", "--repeats", d] for d in ("README.md", "docs/DECISIONS.md", "owner/README.md")]
        for args in runs:
            done = subprocess.run([sys.executable, str(lint)] + args, cwd=str(root), capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout[-1500:])
