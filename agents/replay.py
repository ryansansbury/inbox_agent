"""Check a recorded run against the frozen engine before the build or the scores use it.

    problems(run, spec) -> [str]

Every step that ran is run again on a fresh copy of the records and has to return exactly what the recording says, so
a recording can't disagree with the code that scores it. The run has to have been made with today's prompt and on
today's version of the email, and a finished run's finish has to pass the same checks the loop applied.
"""
import json

from agents import inputs, validate
from engine.tools import Store


def problems(run, spec, seqs=None):
    out = []
    if run.get("prompt_hash") != inputs.prompt_hash():
        out.append("made with an older prompt")
    seq = run.get("seq", 0)
    if seqs is not None and seqs.get(spec["id"]) != seq:
        out.append(f"its ID block is {seq}, not {seqs.get(spec['id'])}")
    if run.get("input_hash") != inputs.input_hash(spec, seq):
        out.append("made on an older version of the email")
    store = Store(spec, seq=seq)
    for i, step in enumerate(run["steps"], 1):
        if step.get("valid") is False:
            continue
        again = store.run(step["tool"], step["args"])
        if json.loads(json.dumps(again)) != step["result"]:
            out.append(f"step {i} ({step['tool']}) returns something else today")
    if run.get("finish") is not None:
        out += [f"finish: {p}" for p in validate.check_finish(run["finish"], len(spec["sentences"]))
                if p not in run.get("problems", [])]
    return out
