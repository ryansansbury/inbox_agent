"""Check what a model sends before the harness acts on it: each tool call's inputs against its schema, and the finish.

A call with a missing or mistyped input, or a sentence number the email doesn't have, never reaches the tools. The
model gets the problem back as the tool's result and can correct it, and the call still counts toward the limit. A
finish with problems gets one repair request, and whatever comes back after that is recorded with its problems.
"""
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def _type_ok(value, kind):
    if kind in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, TYPES[kind])


def check_input(schema, args, n_sentences, path=""):
    problems = []
    if not isinstance(args, dict):
        return [f"{path or 'the input'} has to be an object"]
    for k in schema.get("required", []):
        if k not in args:
            problems.append(f"{path}{k} is missing")
    for k, v in args.items():
        spec = schema.get("properties", {}).get(k)
        if spec is None:
            continue
        kind = spec.get("type")
        if kind and not _type_ok(v, kind):
            problems.append(f"{path}{k} has to be a {kind}")
            continue
        if "enum" in spec and v not in spec["enum"]:
            problems.append(f"{path}{k} has to be one of {', '.join(map(str, spec['enum']))}")
        if kind == "integer" and spec.get("minimum") is not None and v < spec["minimum"]:
            problems.append(f"{path}{k} has to be at least {spec['minimum']}")
        if k == "sentence" and kind == "integer" and not 1 <= v <= n_sentences:
            problems.append(f"sentence has to be between 1 and {n_sentences}")
        if kind == "array" and isinstance(spec.get("items"), dict) and spec["items"].get("type") == "object":
            for i, item in enumerate(v):
                problems += check_input(spec["items"], item, n_sentences, f"{path}{k}[{i}].")
    return problems


def check_finish(args, n_sentences):
    problems = []
    if not isinstance(args.get("reply"), str):
        problems.append("reply has to be text, or an empty string when no reply is needed")
    elif len(args["reply"]) > 3000:
        problems.append("reply is longer than 3,000 characters")
    if not isinstance(args.get("note"), str) or not args.get("note", "").strip():
        problems.append("note has to be one or two sentences for the approver")
    if not isinstance(args.get("intents"), list) or not all(isinstance(x, str) for x in args.get("intents", [])):
        problems.append("intents has to be a list of short labels")
    ignored = args.get("ignored_instructions")
    if not isinstance(ignored, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in ignored):
        problems.append("ignored_instructions has to be a list of sentence numbers")
    elif any(not 1 <= x <= n_sentences for x in ignored):
        problems.append(f"ignored_instructions can only hold sentence numbers from 1 to {n_sentences}")
    return problems
