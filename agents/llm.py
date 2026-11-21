"""How the agent reaches a model, with each vendor's native tool calling.

Every backend answers the same call:

    backend.turn(system, tools, messages) -> {"text", "calls": [{"id", "name", "input"}], "stop", "meta"}

The conversation stays in one neutral shape (a user's text, an assistant's text and tool calls, and the tools'
results), and each backend writes it in its own vendor's wire format:
- Anthropic: the Messages API with tools, tool_use and tool_result blocks, and the system prompt and the tool list
  cached, since both are the same for every email.
- OpenAI: Chat Completions with function tools, tool_calls and tool messages. OpenAI caches long prompts on its own.
Both retry rate limits and server errors with backoff, and report tokens, cached tokens, time and cost at the list
prices in config/models.json. The caller hands each key in, since keys live in the macOS Keychain and never in the repo.
Only owner scripts call a backend, and the build replays what they recorded.
"""
import json
import sys
import time
import urllib.error
import urllib.request

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
RETRY_STATUS = (408, 409, 429, 500, 502, 503, 504, 529)
MAX_TOKENS = 4096
TIMEOUT = 180
EMPTY = "(no text)"  # what an empty assistant turn reads as when it's sent back, since neither API takes an empty one


def urllib_transport(url, headers, body, timeout):
    """POST body to url. Returns (status, response bytes), with an HTTP error's status and body returned too."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def cost(tokens, prices):
    """Dollars for one call: fresh input, cache writes and cache reads at their multiples of the input price, and
    output. None when a price or a count is missing."""
    p_in, p_out = prices.get("price_in"), prices.get("price_out")
    if None in (p_in, p_out, tokens.get("input"), tokens.get("output")):
        return None
    total = (tokens["input"] * p_in + tokens.get("cache_write", 0) * p_in * prices.get("cache_write_mult", 1.25)
             + tokens.get("cache_read", 0) * p_in * prices.get("cache_read_mult", 0.1) + tokens["output"] * p_out)
    return round(total / 1e6, 6)


def error_text(raw):
    try:
        e = json.loads(raw).get("error") or {}
        return f"{e.get('type', '')} {e.get('message', '')}".strip()[:300]
    except (ValueError, AttributeError):
        return (raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw))[:300]


class _Backend:
    vendor = ""

    def __init__(self, key, model, label="", keychain="", prices=None, max_tokens=MAX_TOKENS, timeout=TIMEOUT,
                 retries=6, transport=None, sleep=time.sleep, notify=None):
        if not key:
            raise ValueError(f"{self.vendor} needs an API key in the Keychain under {keychain or 'its service'}.")
        self.key, self.model, self.label, self.keychain = key, model, label or model, keychain
        self.prices = prices or {}
        self.max_tokens, self.timeout, self.retries = max_tokens, timeout, retries
        self.transport, self.sleep = transport or urllib_transport, sleep
        self.notify = notify or (lambda line: print(line, file=sys.stderr, flush=True))

    def turn(self, system, tools, messages):
        url, headers, body = self.wire(system, tools, messages)
        t0 = time.time()
        for attempt in range(self.retries + 1):
            status, raw = self.transport(url, headers, json.dumps(body).encode(), self.timeout)
            if status == 200:
                out = self.parse(raw)
                out["meta"]["ms"] = round((time.time() - t0) * 1000)
                out["meta"]["cost"] = cost(out["meta"]["tokens"], self.prices)
                return out
            if status in (401, 403):
                raise RuntimeError(f"{self.vendor} refused the key ({status}). Save it again with: bash owner/keys.sh "
                                   f"{self.vendor.lower()}")
            if status in RETRY_STATUS and attempt < self.retries:
                wait = min(2 * 3 ** attempt, 45)
                self.notify(f"    {self.label}: {self.vendor} answered {status} ({error_text(raw)[:120]}). "
                            f"Trying again in {wait} s.")
                self.sleep(wait)
                continue
            raise RuntimeError(f"{self.vendor} answered {status}: {error_text(raw)}")

    def described(self):
        out = {"vendor": self.vendor, "model": self.model, "label": self.label}
        if getattr(self, "reasoning_effort", None):
            out["reasoning_effort"] = self.reasoning_effort
        return out


class Anthropic(_Backend):
    vendor = "Anthropic"

    def wire(self, system, tools, messages):
        defs = [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools]
        if defs:
            defs[-1] = dict(defs[-1], cache_control={"type": "ephemeral"})
        wire = []
        for m in messages:
            if m["role"] == "user":
                content = [{"type": "text", "text": m["text"]}]
            elif m["role"] == "assistant":
                content = ([{"type": "text", "text": m["text"]}] if m.get("text") else []) + [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]} for c in m["calls"]]
                content = content or [{"type": "text", "text": EMPTY}]
            else:
                content = [{"type": "tool_result", "tool_use_id": r["id"],
                            "content": json.dumps(r["content"], ensure_ascii=False)} for r in m["results"]]
            role = "assistant" if m["role"] == "assistant" else "user"
            if wire and wire[-1]["role"] == role:
                wire[-1]["content"] += content
            else:
                wire.append({"role": role, "content": content})
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": wire}
        if defs:
            body.update(tools=defs, tool_choice={"type": "auto"})
        headers = {"x-api-key": self.key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
        return ANTHROPIC_URL, headers, body

    def parse(self, raw):
        data = json.loads(raw)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        calls = [{"id": b["id"], "name": b["name"], "input": b.get("input") or {}}
                 for b in data.get("content", []) if b.get("type") == "tool_use"]
        u = data.get("usage") or {}
        tokens = {"input": u.get("input_tokens"), "output": u.get("output_tokens"),
                  "cache_write": u.get("cache_creation_input_tokens") or 0,
                  "cache_read": u.get("cache_read_input_tokens") or 0}
        return {"text": text, "calls": calls, "stop": data.get("stop_reason"),
                "meta": {"model": data.get("model"), "tokens": tokens, "usage": u}}


class OpenAI(_Backend):
    vendor = "OpenAI"

    def __init__(self, key, model, base_url="https://api.openai.com/v1", token_param="max_completion_tokens",
                 reasoning_effort=None, **kw):
        super().__init__(key, model, **kw)
        self.url, self.token_param = base_url.rstrip("/") + "/chat/completions", token_param
        self.reasoning_effort = reasoning_effort

    def wire(self, system, tools, messages):
        defs = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}} for t in tools]
        wire = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                wire.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                msg = {"role": "assistant", "content": m.get("text") or (None if m["calls"] else EMPTY)}
                if m["calls"]:
                    msg["tool_calls"] = [{"id": c["id"], "type": "function", "function": {
                        "name": c["name"], "arguments": json.dumps(c["input"], ensure_ascii=False)}} for c in m["calls"]]
                wire.append(msg)
            else:
                wire += [{"role": "tool", "tool_call_id": r["id"], "content": json.dumps(r["content"],
                                                                                         ensure_ascii=False)}
                         for r in m["results"]]
        body = {"model": self.model, "messages": wire, self.token_param: self.max_tokens}
        if defs:
            body.update(tools=defs, tool_choice="auto")
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        headers = {"authorization": f"Bearer {self.key}", "content-type": "application/json"}
        return self.url, headers, body

    def parse(self, raw):
        data = json.loads(raw)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = []
        for c in msg.get("tool_calls") or []:
            fn = c.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {"_unreadable_arguments": (fn.get("arguments") or "")[:500]}
            calls.append({"id": c.get("id"), "name": fn.get("name"), "input": args if isinstance(args, dict) else {}})
        u = data.get("usage") or {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        prompt = u.get("prompt_tokens")
        tokens = {"input": prompt - cached if prompt is not None else None, "output": u.get("completion_tokens"),
                  "cache_write": 0, "cache_read": cached}
        return {"text": msg.get("content") or "", "calls": calls, "stop": choice.get("finish_reason"),
                "meta": {"model": data.get("model"), "tokens": tokens, "usage": u}}


def backend_for(entry, key_for, **kw):
    """The backend a config/models.json entry describes. key_for(service) returns that service's key from the
    Keychain. It's owner code, so this module never reads a key itself."""
    prices = {k: entry[k] for k in ("price_in", "price_out", "cache_write_mult", "cache_read_mult") if k in entry}
    common = dict(label=entry.get("label", ""), keychain=entry.get("keychain", ""), prices=prices, **kw)
    if entry.get("max_tokens"):
        common["max_tokens"] = entry["max_tokens"]
    if entry["via"] == "anthropic":
        return Anthropic(key_for(entry["keychain"]), entry["model"], **common)
    if entry["via"] == "openai":
        return OpenAI(key_for(entry["keychain"]), entry["model"], base_url=entry.get("base_url", "https://api.openai.com/v1"),
                      token_param=entry.get("token_param", "max_completion_tokens"),
                      reasoning_effort=entry.get("reasoning_effort"), **common)
    raise ValueError(f"{entry.get('id')} names an unknown way to reach its model: {entry.get('via')}")
