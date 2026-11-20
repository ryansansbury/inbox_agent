"""Flag sentences in an email that talk to an AI or pose as a system, the second of the three injection layers.

    flags(spec) -> [{"n": sentence number, "reason": ...}]

The first layer is the prompt (email text is data, never instructions) and the third is the policy, which a sentence
can't talk past. This one is plain patterns, so it's predictable and the page can mark what it caught: a sentence
addressed to an assistant or an AI, a bracketed note posing as an automated or system message, a demand to skip
review, or an order to ignore what came before. A customer asking a person for something ("please confirm") isn't
flagged, and the tests hold it to the 48 emails: the four planted instructions are caught and nothing else is.
"""
import re

PATTERNS = [
    (re.compile(r"\b(?:ai|automated)\s+(?:assistant|agent|system)\b", re.I), "addresses an AI"),
    (re.compile(r"(?:^|[.!?]\s+)assistant\s*,", re.I), "addresses an assistant"),
    (re.compile(r"\bnote to the (?:ai|assistant|agent|system)\b", re.I), "addresses an AI"),
    (re.compile(r"^\s*\[?\s*(?:automated|system)\s+(?:processing\s+)?(?:note|message|instruction)\b", re.I),
     "poses as a system message"),
    (re.compile(r"\b(?:ignore|disregard)\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\b", re.I),
     "tells the reader to ignore what came before"),
    (re.compile(r"\bno human review\b|\bwithout (?:a )?(?:human|manual) review\b", re.I), "claims no review is needed"),
    (re.compile(r"\bthis step is pre-?approved\b", re.I), "claims an approval it can't have"),
]


def flags(spec):
    out = []
    for s in spec["sentences"]:
        reasons = [reason for pat, reason in PATTERNS if pat.search(s["text"])]
        if reasons:
            out.append({"n": s["n"], "reason": reasons[0], "part": s["part"]})
    return out
