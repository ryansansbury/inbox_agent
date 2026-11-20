"""The page's data, words and look: the bundle agrees with the engine, every word the script asks for is in WORDS.md,
every text color clears contrast on its background, the credit cap beat moves the three emails it should in the
recordings, the code view keeps private files out, and the first load stays under a megabyte."""
import json
import re
import unittest
from pathlib import Path

import build
from app import bundle, code_view, words
from engine import policy

HERE = Path(__file__).resolve().parent.parent
SITE = HERE.joinpath("site")


def luminance(hex_color):
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def tokens():
    css = SITE.joinpath("app.css").read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\}", css, re.S).group(1)
    out = {}
    for k, v in re.findall(r"--([\w-]+):\s*#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", root):
        out[k] = "#" + (v if len(v) == 6 else "".join(c * 2 for c in v))
    return out


class Look(unittest.TestCase):
    # Every text color the page sets on a background, by token: ink on the page, the cards and the panels, each status
    # on its own tint, and the top bar's words on graphite. WCAG AA asks 4.5 to 1 for body text.
    PAIRS = [("ink", "bg"), ("ink2", "bg"), ("muted", "bg"), ("ink", "card"), ("ink2", "card"), ("muted", "card"),
             ("muted", "soft"), ("ink2", "soft"), ("amber", "amber-bg"), ("amber", "amber-soft"), ("amber", "card"),
             ("green", "green-bg"), ("green", "card"), ("red", "red-bg"), ("red", "card"), ("slate", "slate-bg"),
             ("top-ink", "top"), ("top-muted", "top"), ("ink", "amber-line")]

    def test_every_text_color_clears_contrast(self):
        t = tokens()
        low = [f"{a} on {b} is {contrast(t[a], t[b]):.2f}" for a, b in self.PAIRS if contrast(t[a], t[b]) < 4.5]
        self.assertEqual(low, [])

    def test_the_status_colors_tell_apart_by_lightness_too(self):
        # Each state also carries an icon and a word, so color is never alone. The tints still differ from each other.
        t = tokens()
        tints = [luminance(t[k]) for k in ("green-bg", "amber-bg", "red-bg", "slate-bg")]
        self.assertEqual(len({round(x, 2) for x in tints}), 4)


class Words(unittest.TestCase):
    def test_every_word_the_script_asks_for_is_in_words_md(self):
        js = SITE.joinpath("app.js").read_text(encoding="utf-8")
        ui = words.load().ui()
        missing = []
        for table, key in re.findall(r"tw\(\"([\w]+)\", \"([\w.]+)\"", js):
            entries = ui.get(table) if isinstance(ui.get(table), dict) else {}
            if key.endswith("."):  # a key the script finishes at run time, like "route." and a team
                if not any(k.startswith(key) for k in entries):
                    missing.append(f"{table}.{key}")
            elif key not in entries:
                missing.append(f"{table}.{key}")
        for key in re.findall(r"word\(\"([\w]+)\"", js):
            if key not in ui:
                missing.append(key)
        for table in re.findall(r"has\(\"([\w]+)\"", js) + re.findall(r"tw\(\"([\w]+)\", ", js):
            if table not in ui:
                missing.append(table)
        self.assertEqual(sorted(set(missing)), [])

    def test_every_did_line_and_rule_the_runs_can_reach_has_words(self):
        ui = words.load().ui()
        data = bundle.build(words.load())
        lacking = set()
        for runs in data["runs"].values():
            for run in runs.values():
                for a in run["actions"]:
                    v = a["verdict"]
                    if a["tool"] not in ("route_to_person", "ask_customer"):
                        if f"{v['rule']}.{v['verdict']}" not in ui["why"]:
                            lacking.add(f"why {v['rule']}.{v['verdict']}")
                        if a["tool"] not in ui["what"]:
                            lacking.add(f"what {a['tool']}")
        for rule in ("credit_cap", "reship_cap", "fee_waiver_cap", "order_cap", "credit_line", "account_hold",
                     "ship_to_before_pick"):
            if rule not in ui["chip"]:
                lacking.add(f"chip {rule}")
        self.assertEqual(sorted(lacking), [])


class Data(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = bundle.build(words.load())

    def test_every_recorded_verdict_is_what_the_rules_say_at_the_defaults(self):
        limits = policy.defaults()
        off = []
        for m, runs in self.data["runs"].items():
            for eid, run in runs.items():
                for a in run["actions"]:
                    if a["fixed"]:
                        continue
                    if policy.decide(a["tool"], dict(a["facts"], team=a.get("team")), limits) != a["verdict"]:
                        off.append(f"{m} {eid} {a['tool']}")
        self.assertEqual(off, [])

    def test_the_credit_cap_at_100_moves_three_emails_in_the_routed_run(self):
        low = dict(policy.defaults(), credit_cap=100)

        def lanes(limits):
            out = {}
            for eid, run in self.data["runs"][self.data["route"]].items():
                acts = [{"tool": a["tool"], "team": a.get("team"),
                         "verdict": a["verdict"] if a["fixed"] else policy.decide(
                             a["tool"], dict(a["facts"], team=a.get("team")), limits)} for a in run["actions"]]
                if run["finish"]["ignored"]:
                    acts.append({"tool": "refuse"})
                out[eid] = policy.lane(acts)
            return out
        a, b = lanes(policy.defaults()), lanes(low)
        self.assertEqual(sorted(k for k in a if a[k] != b[k]), ["m02", "m07", "m08"])
        self.assertTrue(all(b[k] == "needs_you" for k in ("m02", "m07", "m08")))

    def test_the_route_comes_first_and_every_model_has_the_whole_morning(self):
        self.assertTrue(self.data["models"][0]["route"])
        for m in self.data["models"]:
            self.assertEqual(len(self.data["runs"][m["id"]]), 12)

    def test_the_bundle_carries_no_vendor_call_ids_or_keys(self):
        text = json.dumps(self.data)
        self.assertNotIn("toolu_", text)
        self.assertNotRegex(text, r"sk-[A-Za-z0-9]{8}")
        self.assertNotIn("keychain", text)


class Ships(unittest.TestCase):
    def test_the_code_view_keeps_private_files_out(self):
        files = code_view.collect()
        bad = [f for f in files if f.startswith(("tools/", "reference/", "mockups/", "data/", "owner/out/"))
               or "foreign" in f or "private" in f or f.endswith(".txt")]
        self.assertEqual(bad, [])
        for f in code_view.FEATURED:
            self.assertIn(f, files)

    def test_the_first_load_is_under_a_megabyte(self):
        build.main()
        weight = sum(SITE.joinpath(n).stat().st_size for n in build.FIRST_LOAD)
        self.assertLess(weight, build.BUDGET)


if __name__ == "__main__":
    unittest.main()


class MailboxStyles(unittest.TestCase):
    """Every class the mailbox puts on the page has a rule of its own in the stylesheet (11/19). A rename that leaves
    one behind, the way .panel-body once lost its padding and its scrolling, fails here."""

    def test_every_mailbox_class_has_a_rule(self):
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        css = root.joinpath("site", "app.css").read_text(encoding="utf-8")
        used = ["conn", "layouts", "mail", "rail", "fold", "mlist", "mhead", "msearch", "mspan", "mrow", "mbody",
                "lab", "tags", "read", "read-body", "rfrom", "draft", "draft-head", "draft-inner", "draft-foot",
                "btn-send", "apanel", "ptabs", "panel-body", "checked", "threads", "folders-phone", "agent-toggle", "av",
                "mnone", "sent-note"]
        missing = [c for c in used if not re.search(r"\." + re.escape(c) + r"(?![\w-])", css)]
        self.assertEqual(missing, [])
        js = root.joinpath("site", "app.js").read_text(encoding="utf-8") + root.joinpath("app", "page.py").read_text(encoding="utf-8")
        for c in used:
            self.assertRegex(js, r"class='[^']*\b" + re.escape(c) + r"\b", f"{c} is no longer used, so drop it here")


class DarkMode(unittest.TestCase):
    """The dark theme's words clear 4.5 to 1 on the surfaces they sit on, like the light theme's (11/19)."""
    PAIRS = (("--ink", "--card"), ("--ink2", "--card"), ("--muted", "--card"), ("--muted", "--soft"), ("--ink", "--bg"),
             ("--muted", "--bg"), ("--amber", "--amber-bg"), ("--amber", "--amber-soft"), ("--green", "--green-bg"),
             ("--red", "--red-bg"), ("--slate", "--slate-bg"), ("--ink", "--k-sel"), ("--ink", "--k-hit"),
             ("--k-tooltext", "--k-tool"), ("--ink2", "--k-rail"), ("--ink2", "--k-conn"), ("--ink", "--k-lit"))

    def test_every_dark_text_color_clears_contrast(self):
        css = Path(__file__).resolve().parent.parent.joinpath("site", "app.css").read_text(encoding="utf-8")
        block = re.search(r"body\.dark \{([^}]*)\}", css).group(1)
        t = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", block))
        low = [f"{a} on {b} is {contrast(t[a], t[b]):.2f}" for a, b in self.PAIRS if contrast(t[a], t[b]) < 4.5]
        self.assertEqual(low, [])

    def test_no_light_only_text_color_is_left_in_the_stylesheet(self):
        """A text color written as a literal has to read on the dark card, unless its rule also sets its own literal
        background (the top bar, the code, the raw calls). Dark mode shipped once with five that didn't (11/19)."""
        css = Path(__file__).resolve().parent.parent.joinpath("site", "app.css").read_text(encoding="utf-8")
        card = re.search(r"body\.dark \{[^}]*--card:\s*(#[0-9a-fA-F]{6})", css).group(1)
        low = []
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            sel = sel.strip().splitlines()[-1]
            if sel.startswith(("@", ":root", "body.dark")):
                continue
            own = re.search(r"background(?:-color)?:\s*#[0-9a-fA-F]{3,6}", body) or "var(--top" in body
            for hexa in re.findall(r"(?<![-\w])color:\s*(#[0-9a-fA-F]{6})\b", body):
                if not own and contrast(hexa, card) < 4.5:
                    low.append(f"{sel} {hexa}")
        self.assertEqual(low, [])

    def test_the_new_text_variables_read_in_both_themes(self):
        css = Path(__file__).resolve().parent.parent.joinpath("site", "app.css").read_text(encoding="utf-8")
        light = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", css[css.index(":root"):css.index("}", css.index(":root"))]))
        dark = dict(light, **dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", re.search(r"body\.dark \{([^}]*)\}", css).group(1))))
        pairs = (("--k-redtext", "--red-bg"), ("--k-ambertext", "--amber-bg"), ("--k-aitext", "--k-lit2"), ("--k-slatetext", "--slate-bg"))
        low = [f"{name} {a} on {b}" for name, t in (("light", light), ("dark", dark)) for a, b in pairs if contrast(t[a], t[b]) < 4.5]
        self.assertEqual(low, [])
        self.assertGreaterEqual(contrast("#ffffff", "#15803d"), 4.5)

    def test_the_phone_folder_chips_outrank_the_rule_that_hides_them(self):
        css = Path(__file__).resolve().parent.parent.joinpath("site", "app.css").read_text(encoding="utf-8")
        self.assertIn(".mhead .folders-phone { display: flex; }", css)
        self.assertNotRegex(css, r"\n  \.folders-phone \{ display: flex")

    def test_the_phone_scrollers_snap_and_fade(self):
        """A line that scrolls sideways on purpose snaps, which is how Chrome's check tells it from text spilling out
        of its box, and fades at its right edge so the cut reads as more to come."""
        css = Path(__file__).resolve().parent.parent.joinpath("site", "app.css").read_text(encoding="utf-8")
        for selector in ("  .conn ul {", "\n.folders-phone {"):
            rule = css[css.index(selector):]
            rule = rule[:rule.index("}")]
            self.assertIn("overflow-x: auto", rule)
            self.assertIn("scroll-snap-type: x proximity", rule)
            self.assertIn("mask-image: linear-gradient(to right", rule)
        self.assertNotRegex(css, r"\.conn \{[^}]*overflow-x")
