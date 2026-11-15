"""What the AI calls of a search cost, estimated from token counts and a price list.

The provider's bill is what counts: these figures are there so that a search's spending can be
read at a glance and limited in money instead of in tokens, which mix cheap and dear models.
"""

from __future__ import annotations

# US dollars per million tokens: input, output, input read from the prompt cache.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
CACHE_WRITE = 1.25  # writing to the 5-minute cache costs this many times the input price
BATCH = 0.5         # a batch is charged at half price, cache reads and writes included
KINDS = ("input", "output", "cache_read", "cache_write")


def price_of(model: str, own: dict | None = None) -> tuple[float, float, float] | None:
    """The price of a model: one given in the settings first, then the list above. A dated or
    suffixed id ("claude-sonnet-5-5-20261001") takes the price of the id it starts with."""
    for prices in (own or {}, PRICES):
        for name in sorted(prices, key=len, reverse=True):
            if model == name or model.startswith(name):
                p = list(prices[name]) + [None] * 3
                return float(p[0]), float(p[1]), float(p[2] if p[2] is not None else p[0] * 0.1)
    return None


def cost(model: str, usage: dict, batch: dict | None = None, own: dict | None = None) -> float | None:
    """Dollars for these token counts, or None when the model's price is not known."""
    price = price_of(model, own)
    if price is None:
        return None
    dollars_in, dollars_out, dollars_read = price

    def of(u: dict) -> float:
        return (u.get("input", 0) * dollars_in + u.get("output", 0) * dollars_out + u.get("cache_read", 0) * dollars_read
                + u.get("cache_write", 0) * dollars_in * CACHE_WRITE) / 1_000_000

    return round(of(usage) + of(batch or {}) * BATCH, 4)


def usage_of(clients, own: dict | None = None) -> dict[str, dict]:
    """Tokens and cost by model for the AI clients of one search. Two clients on the same model
    are added together; a client that keeps no breakdown reports its total only."""
    out: dict[str, dict] = {}
    for c in {id(c): c for c in clients if c is not None}.values():
        row = out.setdefault(getattr(c, "model", "unknown"), {**dict.fromkeys(KINDS, 0), "batch": dict.fromkeys(KINDS, 0), "tokens": 0})
        for k in KINDS:
            row[k] += getattr(c, "usage", {}).get(k, 0)
            row["batch"][k] += getattr(c, "batch_usage", {}).get(k, 0)
        row["tokens"] += getattr(c, "tokens_used", 0)
    for model, row in out.items():
        counted = sum(row[k] + row["batch"][k] for k in KINDS)
        row["cost"] = cost(model, row, row["batch"], own) if counted or not row["tokens"] else None
    return {m: r for m, r in out.items() if r["tokens"]}


def total(usage: dict[str, dict]) -> float | None:
    """The cost of everything, or None when some of it has no known price."""
    costs = [r["cost"] for r in usage.values()]
    return None if any(c is None for c in costs) else round(sum(costs), 4)


def in_words(usage: dict[str, dict]) -> str:
    """For a summary line: "about $0.38 (claude-sonnet-5-5 $0.36, claude-haiku-5-5 $0.02)"."""
    whole = total(usage)
    if whole is None or not usage:
        return ""
    parts = ", ".join(f"{m} ${r['cost']:.2f}" for m, r in usage.items())
    return f"about ${whole:.2f}" + (f" ({parts})" if len(usage) > 1 else "")
