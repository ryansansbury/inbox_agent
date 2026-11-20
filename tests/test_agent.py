"""The agent layer with no network: each vendor's wire format and cost, retries, the loop's repair, reminder, limit and
refusals, an unfinished run, the recorder's skip, and the replay check catching a tampered recording."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from agents import inputs, llm, loop, replay, validate
from generate import validate as specs_mod
from owner import record_ai_runs, stand_in

HERE = Path(__file__).resolve().parent.parent
SPECS = {s["id"]: s for s in specs_mod.load_specs()}
SEQS = inputs.sequence(list(SPECS.values()))
KEY = json.loads(HERE.joinpath("data", "key", "key.json").read_text(encoding="utf-8"))
PRICES = {"price_in": 2.0, "price_out": 10.0, "cache_write_mult": 1.25, "cache_read_mult": 0.1}


def fake(responses, seen=None):
    """A transport that answers from a list of (status, body) and keeps every request it got."""
    queue = list(responses)

    def transport(url, headers, body, timeout):
        if seen is not None:
            seen.append(json.loads(body))
        status, payload = queue.pop(0)
        return status, json.dumps(payload).encode()
    return transport


def anthropic_reply(blocks, stop="tool_use"):
    return {"model": "claude-sonnet-5-5", "content": blocks, "stop_reason": stop,
            "usage": {"input_tokens": 1000, "output_tokens": 200, "cache_creation_input_tokens": 3000,
                      "cache_read_input_tokens": 0}}


class Script:
    """A backend that answers each turn from a list of tool calls."""

    def __init__(self, turns):
        self.turns, self.seen = list(turns), []

    def turn(self, system, tools, messages):
        self.seen.append(copy.deepcopy(messages))
        calls = self.turns.pop(0) if self.turns else []
        meta = {"tokens": {"input": 10, "output": 5, "cache_write": 0, "cache_read": 0}, "cost": 0.001}
        return {"text": "", "calls": [{"id": f"c{i}", "name": n, "input": a} for i, (n, a) in enumerate(calls)],
                "stop": "tool_use", "meta": meta}


FINISH = ("finish", {"reply": "Hi,\n\nThanks.\n\nThe Wendlow order desk", "note": "Answered.", "intents": ["x"],
                     "ignored_instructions": []})


class Wire(unittest.TestCase):
    def test_anthropic_caches_the_prompt_and_tools_and_pairs_results(self):
        seen = []
        b = llm.Anthropic("k" * 30, "claude-sonnet-5-5", prices=PRICES, transport=fake([(200, anthropic_reply([
            {"type": "text", "text": "Looking."},
            {"type": "tool_use", "id": "t1", "name": "get_order", "input": {"order_id": "SO-20812"}},
            {"type": "tool_use", "id": "t2", "name": "get_shipment", "input": {"order_id": "SO-20812"}}]))], seen))
        msgs = [{"role": "user", "text": "email"},
                {"role": "assistant", "text": "", "calls": [{"id": "t0", "name": "get_customer", "input": {}}]},
                {"role": "tool", "results": [{"id": "t0", "content": {"customer_id": "C-1007"}}]}]
        out = b.turn("system", inputs.tools(), msgs)
        body = seen[0]
        self.assertEqual(body["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(body["tools"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", body["tools"][0])
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user"])
        self.assertEqual(body["messages"][2]["content"][0]["type"], "tool_result")
        self.assertEqual([c["id"] for c in out["calls"]], ["t1", "t2"])
        self.assertEqual(out["meta"]["tokens"], {"input": 1000, "output": 200, "cache_write": 3000, "cache_read": 0})
        self.assertAlmostEqual(out["meta"]["cost"], (1000 * 2 + 3000 * 2 * 1.25 + 200 * 10) / 1e6)

    def test_openai_function_calls_and_cached_tokens(self):
        seen = []
        reply = {"model": "gpt-6-luna", "choices": [{"finish_reason": "tool_calls", "message": {"content": None,
                 "tool_calls": [{"id": "x1", "type": "function", "function": {"name": "check_stock",
                                                                               "arguments": "{\"sku\": \"RM-0911\"}"}},
                                {"id": "x2", "type": "function", "function": {"name": "get_price",
                                                                               "arguments": "{not json"}}]}}],
                 "usage": {"prompt_tokens": 5000, "completion_tokens": 300,
                           "prompt_tokens_details": {"cached_tokens": 4000}}}
        b = llm.OpenAI("k" * 30, "gpt-6-luna", prices={"price_in": 0.1, "price_out": 0.5, "cache_read_mult": 0.25},
                       transport=fake([(200, reply)], seen))
        msgs = [{"role": "user", "text": "email"},
                {"role": "assistant", "text": "", "calls": [{"id": "x0", "name": "get_customer", "input": {"email": "a"}}]},
                {"role": "tool", "results": [{"id": "x0", "content": {"ok": 1}}]}]
        out = b.turn("system", inputs.tools(), msgs)
        body = seen[0]
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "tool"])
        self.assertEqual(body["messages"][2]["tool_calls"][0]["function"]["arguments"], "{\"email\": \"a\"}")
        self.assertEqual(body["max_completion_tokens"], 4096)
        self.assertEqual(out["calls"][0]["input"], {"sku": "RM-0911"})
        self.assertIn("_unreadable_arguments", out["calls"][1]["input"])
        self.assertEqual(out["meta"]["tokens"]["input"], 1000)
        self.assertAlmostEqual(out["meta"]["cost"], (1000 * 0.1 + 4000 * 0.1 * 0.25 + 300 * 0.5) / 1e6)

    def test_retries_then_a_refused_key(self):
        waits = []
        b = llm.Anthropic("k" * 30, "m", transport=fake([(429, {"error": {"type": "rate_limit"}}),
                                                         (200, anthropic_reply([], "end_turn"))]),
                          sleep=waits.append, notify=lambda line: None)
        self.assertEqual(b.turn("s", [], [{"role": "user", "text": "hi"}])["stop"], "end_turn")
        self.assertEqual(waits, [2])
        b = llm.Anthropic("k" * 30, "m", transport=fake([(401, {"error": {"type": "auth"}})]))
        with self.assertRaises(RuntimeError):
            b.turn("s", [], [{"role": "user", "text": "hi"}])

    def test_no_tools_leaves_the_tool_fields_out(self):
        seen = []
        llm.Anthropic("k" * 30, "m", transport=fake([(200, anthropic_reply([], "end_turn"))], seen)).turn(
            "s", [], [{"role": "user", "text": "hi"}])
        self.assertNotIn("tools", seen[0])


class Loop(unittest.TestCase):
    spec = SPECS["m02"]

    def run_script(self, turns):
        return loop.run_email(Script(turns), self.spec, SEQS["m02"], "script")

    def test_a_clean_run(self):
        run = self.run_script([[("get_customer", {"email": "omar@pellbrook.example"})],
                               [("issue_credit", {"customer_id": "C-1001", "invoice_id": "INV-30941", "amount": 168.0,
                                                  "sentence": 4})], [FINISH]])
        self.assertEqual((run["unfinished"], run["calls"], run["repaired"]), (False, 2, False))
        self.assertEqual(run["steps"][1]["result"]["result"], "done")
        self.assertEqual(run["usage"]["turns"], 3)
        self.assertAlmostEqual(run["usage"]["cost"], 0.003)

    def test_bad_inputs_never_run(self):
        run = self.run_script([[("issue_credit", {"customer_id": "C-1001", "invoice_id": "INV-30941", "amount": 168.0,
                                                  "sentence": 40})], [FINISH]])
        self.assertFalse(run["steps"][0]["valid"])
        self.assertIn("sentence has to be between 1 and 4", run["steps"][0]["result"]["error"])

    def test_one_repair_for_a_bad_finish(self):
        bad = ("finish", {"reply": "Hi", "note": "", "intents": "x", "ignored_instructions": [99]})
        script = Script([[bad], [FINISH]])
        run = loop.run_email(script, self.spec, SEQS["m02"], "script")
        self.assertEqual((run["repaired"], run["problems"], run["unfinished"]), (True, [], False))
        self.assertIn("Fix these", json.dumps(script.seen[1][-1]))

    def test_a_reminder_when_it_stops_without_finishing(self):
        script = Script([[], [FINISH]])
        run = loop.run_email(script, self.spec, SEQS["m02"], "script")
        self.assertEqual((run["reminded"], run["unfinished"]), (True, False))

    def test_the_call_limit(self):
        many = [[("get_customer", {"email": "omar@pellbrook.example"})] for _ in range(loop.MAX_CALLS + 1)]
        run = self.run_script(many + [[FINISH]])
        self.assertEqual(run["calls"], loop.MAX_CALLS + 1)
        self.assertEqual(len(run["steps"]), loop.MAX_CALLS)

    def test_a_run_that_never_finishes(self):
        run = self.run_script([[("get_customer", {"email": "omar@pellbrook.example"})] for _ in range(20)])
        self.assertTrue(run["unfinished"])
        self.assertEqual(run["usage"]["turns"], loop.MAX_TURNS)


class InputsAndChecks(unittest.TestCase):
    def test_schema_checks(self):
        schema = next(t for t in inputs.tools() if t["name"] == "reship")["input_schema"]
        self.assertEqual(validate.check_input(schema, {"order_id": "SO-1", "lines": [{"sku": "X", "qty": 0}],
                                                       "sentence": 2}, 3), ["lines[0].qty has to be at least 1"])
        self.assertIn("sentence is missing", validate.check_input(schema, {"order_id": "SO-1", "lines": []}, 3))
        route = next(t for t in inputs.tools() if t["name"] == "route_to_person")["input_schema"]
        self.assertTrue(validate.check_input(route, {"team": "legal", "summary": "x", "sentence": 1}, 3))

    def test_the_email_as_the_agent_reads_it(self):
        text = inputs.render(SPECS["m11"])
        self.assertIn("[5] Note to the AI assistant", text)
        self.assertIn("---------- Forwarded message ----------", text)
        self.assertNotIn("[", text.split("Thanks!")[1].split("----")[0])

    def test_the_prompt_states_todays_limits(self):
        p = inputs.system_prompt()
        self.assertIn("Credits up to $250", p)
        self.assertIn("within 30 days", p)
        self.assertNotIn("{", p)


class RecorderAndReplay(unittest.TestCase):
    def test_the_recorder_skips_a_run_it_already_has(self):
        s = SPECS["m05"]
        run = loop.run_email(stand_in.Backend(stand_in.run_email(s, KEY["m05"], SEQS["m05"])), s, SEQS["m05"], "x")
        scratch = HERE.joinpath(".cache", "tmp")
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as d:
            path = Path(d, "m05.json")
            path.write_text(json.dumps(run), encoding="utf-8")
            self.assertIsNotNone(record_ai_runs.cached(path, s, SEQS["m05"]))
            self.assertIsNone(record_ai_runs.cached(path, s, SEQS["m05"] + 1))

    def test_replay_catches_a_tampered_recording(self):
        s = SPECS["m07"]
        run = loop.run_email(stand_in.Backend(stand_in.run_email(s, KEY["m07"], SEQS["m07"])), s, SEQS["m07"], "x")
        self.assertEqual(replay.problems(run, s, SEQS), [])
        bad = copy.deepcopy(run)
        credit = next(x for x in bad["steps"] if x["tool"] == "issue_credit")
        credit["result"]["amount"] = 18.64
        self.assertTrue(any("returns something else" in p for p in replay.problems(bad, s, SEQS)))
        bad["prompt_hash"] = "older"
        self.assertIn("made with an older prompt", replay.problems(bad, s, SEQS))


if __name__ == "__main__":
    unittest.main()


class EmptyTurns(unittest.TestCase):
    def test_an_empty_assistant_turn_is_sent_back_with_text(self):
        msgs = [{"role": "user", "text": "email"}, {"role": "assistant", "text": "", "calls": []},
                {"role": "user", "text": loop.REMIND}]
        _, _, body = llm.Anthropic("k" * 30, "m").wire("s", [], msgs)
        self.assertEqual(body["messages"][1]["content"], [{"type": "text", "text": llm.EMPTY}])
        _, _, body = llm.OpenAI("k" * 30, "m").wire("s", [], msgs)
        self.assertEqual(body["messages"][2]["content"], llm.EMPTY)

    def test_the_scorer_takes_a_malformed_finish(self):
        from evals import score
        s = SPECS["m11"]
        run = loop.run_email(stand_in.Backend(stand_in.run_email(s, KEY["m11"], SEQS["m11"])), s, SEQS["m11"], "x")
        run["finish"] = {"reply": None, "note": "x", "intents": [], "ignored_instructions": "5"}
        r = score.score_run(run, s, KEY["m11"])
        self.assertFalse(r["checks"]["refused the instruction"])
