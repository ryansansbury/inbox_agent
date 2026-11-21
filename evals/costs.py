"""What a recorded run cost at today's list prices (11/20). The tokens each call recorded are what the vendor counted,
and prices change, so a run is never recorded again for a price. The page and the model comparison work every cost out
from the tokens at the prices in config/models.json. Kept apart from agents/, which the prompt stage's freeze covers."""
from agents.llm import cost


def prices_of(entry):
    """The prices in a config/models.json entry, as agents.llm.cost reads them."""
    return {k: entry[k] for k in ("price_in", "price_out", "cache_write_mult", "cache_read_mult") if k in entry}


def repriced(run, entry):
    """A recorded run with each turn's cost and the run's total worked out again from its tokens at the entry's
    prices. The run itself isn't changed."""
    prices, turns, total = prices_of(entry), [], 0.0
    for t in run.get("transcript", []):
        meta = dict(t.get("meta") or {})
        if meta.get("tokens"):
            meta["cost"] = cost(meta["tokens"], prices)
            total += meta["cost"] or 0
        turns.append(dict(t, meta=meta))
    usage = dict(run.get("usage") or {})
    if turns and all((t.get("meta") or {}).get("cost") is not None for t in turns if (t.get("meta") or {}).get("tokens")):
        usage["cost"] = round(total, 6)
    return dict(run, transcript=turns, usage=usage)
