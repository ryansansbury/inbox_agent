"""One loop for every model: the email goes in, the model calls tools, the harness runs them, and the run ends when the
model calls finish.

    run = run_email(backend, spec, seq)

Each turn the model may call several tools, which run in order on the email's own copy of the records. Inputs that
don't fit a tool's schema come back as the tool's result without running. Ten tool calls is the limit, after which
any further call is answered with "finish now." A finish with problems gets one repair request, and a model that ends
without calling finish gets one reminder. A run that still doesn't finish within twelve turns is recorded as
unfinished, and the scorer counts it as a miss. Every turn's text, calls, tokens, cost and time go in the record.
"""
import time

from agents import inputs, validate
from engine.tools import Store

MAX_CALLS = 10
MAX_TURNS = 12
REMIND = "Call the finish tool now with the reply, a note for the approver, the intents and ignored_instructions."


def run_email(backend, spec, seq, model_id="", label=""):
    store = Store(spec, seq=seq)
    tools = inputs.tools()
    schemas = {t["name"]: t["input_schema"] for t in tools}
    system = inputs.system_prompt(store.limits)
    n = len(spec["sentences"])
    messages = [{"role": "user", "text": inputs.render(spec)}]
    steps, transcript, problems = [], [], []
    finish, repaired, reminded, calls = None, False, False, 0
    t0 = time.time()
    while len(transcript) < MAX_TURNS and finish is None:
        out = backend.turn(system, tools, messages)
        meta = {k: v for k, v in out["meta"].items() if k != "usage"}
        transcript.append({"text": out["text"], "calls": out["calls"], "stop": out["stop"], "meta": meta})
        messages.append({"role": "assistant", "text": out["text"], "calls": out["calls"]})
        if not out["calls"]:
            if reminded:
                break
            reminded = True
            messages.append({"role": "user", "text": REMIND})
            continue
        results = []
        for c in out["calls"]:
            name, args = c["name"], c["input"]
            if name == "finish":
                found = validate.check_finish(args, n)
                if found and not repaired:
                    repaired = True
                    results.append({"id": c["id"], "content": {"error": "Fix these and call finish again: " +
                                                                        "; ".join(found)}})
                    continue
                finish, problems = args, found
                results.append({"id": c["id"], "content": {"ok": True}})
                break
            if name not in schemas:
                results.append({"id": c["id"], "content": {"error": f"There's no tool named {name}."}})
                continue
            calls += 1
            if calls > MAX_CALLS:
                results.append({"id": c["id"], "content": {"error": f"The limit of {MAX_CALLS} tool calls is reached. "
                                                                    "Call finish now."}})
                continue
            found = validate.check_input(schemas[name], args, n)
            if found:
                result = {"error": "Not run: " + "; ".join(found)}
            else:
                result = store.run(name, args)
            steps.append({"tool": name, "args": args, "result": result, "valid": not found})
            results.append({"id": c["id"], "content": result})
        messages.append({"role": "tool", "results": results})
    seconds = round(time.time() - t0, 1)
    usage = {"turns": len(transcript), "seconds": seconds}
    for k in ("input", "output", "cache_write", "cache_read"):
        vals = [t["meta"].get("tokens", {}).get(k) for t in transcript]
        usage[f"{k}_tokens"] = sum(v for v in vals if v) if any(v is not None for v in vals) else None
    costs = [t["meta"].get("cost") for t in transcript]
    usage["cost"] = round(sum(costs), 6) if costs and all(c is not None for c in costs) else None
    return {"email_id": spec["id"], "split": spec["split"], "seq": seq, "model": model_id, "label": label,
            "prompt_hash": inputs.prompt_hash(), "input_hash": inputs.input_hash(spec, seq), "steps": steps,
            "finish": finish, "unfinished": finish is None, "repaired": repaired, "reminded": reminded,
            "problems": problems, "calls": calls, "transcript": transcript, "usage": usage}
