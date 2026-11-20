"""The shorthand the email files are written in. E is one email, A one action in its key, F one fact the reply must
carry. generate/emails.py turns them into the JSON specs under data/emails/.

Sentences are numbered in reading order: the body's paragraphs first, then each quoted message's. Greetings count as
sentences, and signatures don't, since no action ever answers a signature.
"""
DAY = "2026-10-27"
KEYS_OUT_OF_ARGS = ("basis", "why", "ambiguous")


def A(tool, sentence, **kw):
    out = {"tool": tool, "args": {k: v for k, v in kw.items() if k not in KEYS_OUT_OF_ARGS}}
    if sentence is not None:
        out["sentence"] = sentence
    for k in KEYS_OUT_OF_ARGS:
        if k in kw:
            out[k] = kw[k]
    return out


def F(kind, value, source):
    return {"kind": kind, "value": value, "source": source}


def E(eid, at, sender, subject, body, sig, intents, handling, expected=(), acceptable=(), forbidden=(), facts=(),
      lane="handled", quoted=None, instruction=None, spoof=None, external=False, reply=True):
    return {
        "id": eid, "at": f"{DAY}T{at}", "from": {"name": sender[0], "email": sender[1]},
        "to": "orders@wendlow.example", "subject": subject, "body": body, "sig": sig, "quoted": quoted or [],
        "truth": {"intents": intents, "handling": handling, "expected": list(expected), "acceptable": list(acceptable),
                  "forbidden": list(forbidden), "facts": list(facts), "lane": lane, "instruction": instruction,
                  "spoof": spoof, "external": external, "reply": reply},
    }
