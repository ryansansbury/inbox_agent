"""The world and its key: the fixtures and the specs rebuild exactly, every email passes the validator, and the validator
catches each kind of broken truth, tried on copies so nothing on disk changes."""
import copy
import json
import unittest
from pathlib import Path

from app import never
from engine import db
from generate import emails, fixtures, validate

HERE = Path(__file__).resolve().parent.parent


def spec(eid):
    return copy.deepcopy(next(s for s in validate.load_specs() if s["id"] == eid))


def problems(s):
    return validate.check(s)[0]


class Rebuilds(unittest.TestCase):
    def test_the_fixtures_are_deterministic_and_match_disk(self):
        a, b = fixtures.build(), fixtures.build()
        self.assertEqual(a, b)
        for name, value in a.items():
            on_disk = json.loads(HERE.joinpath("data", "fixtures", f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk, json.loads(json.dumps(value)), name)

    def test_the_specs_match_their_sources(self):
        for s in emails.specs():
            self.assertEqual(emails.path_for(s).read_text(encoding="utf-8"), emails.dump(s), s["id"])

    def test_every_email_passes_and_the_set_holds(self):
        specs = validate.load_specs()
        self.assertEqual(len(specs), 48)
        for s in specs:
            self.assertEqual(problems(s), [], s["id"])
        set_problems, moved = validate.check_set(specs)
        self.assertEqual(set_problems, [])
        self.assertEqual(moved, ["m02", "m07", "m08"])


class CatchesBrokenTruth(unittest.TestCase):
    def test_a_wrong_amount(self):
        s = spec("m02")
        s["truth"]["expected"][0]["args"]["amount"] = 167.00
        self.assertTrue(any("168.0" in p for p in problems(s)))

    def test_a_wrong_fact(self):
        s = spec("m01")
        s["truth"]["facts"][1]["value"] = "PRO 5521-8805"
        self.assertTrue(any("the record says" in p for p in problems(s)))

    def test_a_lane_the_policy_disagrees_with(self):
        s = spec("m05")
        s["truth"]["lane"] = "handled"
        self.assertTrue(any("the policy puts it in needs_you" in p for p in problems(s)))

    def test_a_question_that_names_the_wrong_orders(self):
        s = spec("m12")
        s["truth"]["expected"][0]["args"]["about"] = ["SO-20832"]
        self.assertTrue(any("matching orders" in p for p in problems(s)))

    def test_a_sentence_that_isnt_there(self):
        s = spec("m07")
        s["truth"]["expected"][0]["sentence"] = 99
        self.assertTrue(any("sentence 99" in p for p in problems(s)))

    def test_a_blocked_action_in_expected(self):
        s = spec("d08")
        s["truth"]["expected"] = [{"tool": "create_return", "sentence": 2,
                                   "args": {"order_id": "SO-20771", "lines": [{"sku": "TP-FRG-2", "qty": 4}],
                                            "unopened": True}}]
        self.assertTrue(any("blocks create_return" in p for p in problems(s)))

    def test_a_look_alike_sender_not_sent_to_security(self):
        s = spec("m10")
        s["truth"]["expected"] = []
        self.assertTrue(any("security" in p for p in problems(s)))

    def test_a_hidden_instruction_without_its_guard(self):
        s = spec("m11")
        s["truth"]["forbidden"] = []
        self.assertTrue(any("forbid issue_credit" in p for p in problems(s)))

    def test_a_short_line_that_isnt_short(self):
        s = spec("m03")
        s["truth"]["expected"][0]["args"]["lines"][0]["qty"] = 3
        self.assertTrue(any("isn't short" in p for p in problems(s)))

    def test_a_sender_who_isnt_a_contact(self):
        s = spec("m07")
        s["from"]["email"] = "anya@brecken-electronics.example"
        self.assertTrue(problems(s))


class StandsAlone(unittest.TestCase):
    def test_the_data_holds_no_never_word_or_other_demo_name(self):
        files = list(HERE.joinpath("data", "fixtures").glob("*.json")) + list(HERE.joinpath("data", "emails").glob("*/*.json"))
        self.assertEqual(never.scan(files), [])

    def test_every_name_in_the_world_comes_from_the_cleared_cast(self):
        cast = json.loads(HERE.joinpath("config", "names.json").read_text(encoding="utf-8"))
        people = set(cast["people"])
        companies = {cast["distributor"]["name"]} | {c["name"] for c in cast["customers"]}
        w = db.load()
        self.assertEqual({c["name"] for c in w.customers.values()}, companies - {cast["distributor"]["name"]})
        self.assertEqual(w.meta["company"], cast["distributor"]["name"])
        named = {x["name"] for c in w.customers.values() for x in c["contacts"]} | {s["name"] for s in w.meta["staff"]}
        self.assertEqual(named, people)
        for s in validate.load_specs():
            if not s["truth"]["external"]:
                self.assertIn(s["from"]["name"], people, s["id"])


if __name__ == "__main__":
    unittest.main()


class Freeze(unittest.TestCase):
    def test_a_reworded_description_leaves_the_schemas_alone(self):
        from evals import freeze
        tools = json.loads(HERE.joinpath("config", "tools.json").read_text(encoding="utf-8"))
        before = freeze.tools_part("schemas"), freeze.tools_part("descriptions")
        self.assertEqual(freeze._strip(tools["read"][0]["input_schema"])["properties"]["po"], {"type": "string"})
        tools["read"][0]["description"] = "Reworded."
        self.assertEqual(freeze.tools_part("schemas"), before[0])
        self.assertIn("data/key/key.json", freeze.current("key"))
