"""The shell builds and reads every word from WORDS.md, and the never list and the other demos' names stay out of it
and out of the cast."""
import json
import re
import tempfile
import unittest
from pathlib import Path

import build
from app import never, page, words

HERE = Path(__file__).resolve().parent.parent


class Build(unittest.TestCase):
    def test_the_shell_builds_from_words(self):
        self.assertEqual(build.main(), 0)
        html = HERE.joinpath("site", "index.html").read_text(encoding="utf-8")
        w = words.load()
        self.assertIn(f"<title>{w['page.title']}</title>", html)
        self.assertIn(w["page.footer"], html)

    def test_no_inline_style_or_script_and_nothing_from_another_site(self):
        html = HERE.joinpath("site", "index.html").read_text(encoding="utf-8") if HERE.joinpath(
            "site", "index.html").exists() else ""
        if not html:
            build.main()
            html = HERE.joinpath("site", "index.html").read_text(encoding="utf-8")
        self.assertNotIn(" style=", html)
        self.assertNotRegex(html, r"<script>(?!</script>)|<script[^>]*>[^<]+</script>")
        self.assertNotRegex(html, r"src=['\"](https?:)?//")
        self.assertEqual(set(re.findall(r"href=['\"](https?://[^/'\"]+)", html)),
                         {"https://www.ryansansbury.com", "https://github.com"})
        # The link preview names the live page and its image on the site, and loads nothing.
        self.assertIn("<link rel='canonical' href='https://www.ryansansbury.com/inbox-agent/'>", html)
        self.assertRegex(html, r"<meta property='og:image' content='https://www\.ryansansbury\.com/images/share/"
                               r"inbox-agent\.png\?v=\d+'>")

    def test_a_missing_word_fails_loudly(self):
        with self.assertRaises(words.MissingWord):
            words.Words({}, {})["page.title"]

    def test_the_foreign_list_catches_another_demos_name(self):
        scratch = HERE.joinpath(".cache", "tmp")
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as d:
            f = Path(d, "x.txt")
            f.write_text("A note about Zephyrine Sensors and its alerts.", encoding="utf-8")
            self.assertTrue(any("another demo" in p for p in never.scan([f], never_words=(), foreign_words=("zephyrine",))))
            self.assertEqual(never.scan([f], never_words=(), foreign_words=("quillon",)), [])

    def test_no_first_name_from_an_earlier_cast(self):
        if not never.first_names():
            self.skipTest("the first-names list stays private")
        self.assertEqual(never.shared_first_names(["Grace Holt", "Hazel Garrity"]), ["Grace Holt"])
        self.assertIn("grace", never.first_names())
        self.assertNotIn("grace", never.foreign())

    def test_the_cast_is_cleared_and_stands_alone(self):
        cast = json.loads(HERE.joinpath("config", "names.json").read_text(encoding="utf-8"))
        companies = [cast["distributor"]["name"]] + [c["name"] for c in cast["customers"]]
        people = cast["people"]
        text = " | ".join(companies + people)
        self.assertEqual(never.hits(text, never.words()), [])
        self.assertEqual(never.hits(text, never.foreign()), [])
        self.assertEqual(never.shared_first_names(people), [])
        self.assertEqual(len(cast["customers"]), 10)
        self.assertGreaterEqual(len(people), 20)
        self.assertTrue(all(c["kind"] and c["field"] for c in cast["customers"]))
        for part in (0, -1):
            names = [p.split()[part] for p in people]
            self.assertEqual(len(set(names)), len(names), "two people share a first name or a surname")

    def test_whole_words_only(self):
        self.assertEqual(never.hits("a category of cats", ["cat"]), [])
        self.assertEqual(never.hits("the cat sat", ["cat"]), ["cat"])


if __name__ == "__main__":
    unittest.main()
