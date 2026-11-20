"""What the agent is given: the system prompt with today's limits filled in, the tools, and one email as text with its
sentences numbered, the way a person on the order desk would see it.

prompt_hash() covers the prompt and every tool description, so changing either one counts as a new prompt, and the
recorder never reuses a run made with an older one. input_hash() covers the email as the agent sees it and the
email's ID block.
"""
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from engine import policy

HERE = Path(__file__).resolve().parent.parent
PROMPT = HERE.joinpath("prompts", "agent.md")
TOOLS = HERE.joinpath("config", "tools.json")


def _money(v):
    return f"{v:,.0f}" if float(v) == int(v) else f"{v:,.2f}"


def system_prompt(limits=None):
    lim = limits or policy.defaults()
    text = PROMPT.read_text(encoding="utf-8")
    for k, v in lim.items():
        if isinstance(v, bool):
            continue
        text = text.replace("{" + k + "}", _money(v) if k.endswith("cap") else f"{v:g}")
    return text


def tools():
    """The tool list in a neutral shape, [{"name", "description", "input_schema"}], finish last."""
    raw = json.loads(TOOLS.read_text(encoding="utf-8"))
    return raw["read"] + raw["action"] + [raw["finish"]]


def _when(iso):
    d = datetime.fromisoformat(iso)
    h = d.hour % 12 or 12
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}, {d.year} at {h}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def render(spec):
    """The email as the agent reads it. Sentences are numbered in reading order. Signatures aren't, since no action
    answers a signature."""
    out = [f"An email arrived in the order inbox on {_when(spec['at'])}.", "",
           f"From: {spec['from']['name']} <{spec['from']['email']}>", f"To: {spec['to']}",
           f"Subject: {spec['subject']}", ""]
    sents = {s["n"]: s["text"] for s in spec["sentences"]}
    n = 0
    for para in spec["body"]:
        for _ in para:
            n += 1
            out.append(f"[{n}] {sents[n]}")
        out.append("")
    out += spec["sig"] + [""]
    for q in spec["quoted"]:
        out += ["---------- Forwarded message ----------", f"From: {q['from']}", f"Date: {_when(q['at'])}",
                f"Subject: {q['subject']}", ""]
        for para in q["body"]:
            for _ in para:
                n += 1
                out.append(f"[{n}] {sents[n]}")
            out.append("")
        out += q.get("sig", []) + [""]
    return "\n".join(out).rstrip() + "\n"


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def prompt_hash():
    return digest({"prompt": system_prompt(), "tools": tools()})


def input_hash(spec, seq):
    return digest({"email": render(spec), "seq": seq})


def today():
    return date(2026, 10, 27)


def sequence(specs):
    """Each email's place across the whole set (the morning in time order, then dev, then test), which picks its block
    of new IDs, so no two emails' runs share an order, credit memo or return number."""
    order = sorted(specs, key=lambda s: ({"morning": 0, "dev": 1, "test": 2}[s["split"]], s["at"], s["id"]))
    return {s["id"]: i for i, s in enumerate(order)}
