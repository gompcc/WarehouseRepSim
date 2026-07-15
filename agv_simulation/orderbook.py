"""The canonical order book: a fixed, pregenerated list of orders.

Why it exists (user spec, 2026-07-14): for slotting strategies like
aisle_proximal to be *computable*, every experiment arm must face the same
order flow — then "the most commonly occurring" products are a countable
fact of the book, not a property of a random stream. The canonical book is
**15 hours of real demand at 3,000 lines/hr ≈ 45,000 lines** (~2,250
orders).

Distributions:
- Order size: ``max(1, round(N(ORDER_LINES_MEAN=20, ORDER_LINES_SD=9)))``
  distinct lines per order.
- Product frequency: FLAT (user spec 2026-07-15) — every SKU equally
  likely (``aisles.sku_weight`` returns 1.0), so demand is even across
  the 2000 products while each order stays random.

The book lives in SKU space (no catalog/placement involved), so it is
identical across slotting arms by construction. It is generated once from
``BOOK_SEED`` and persisted to ``data/order_book.json`` (plus a
``data/order_book_frequencies.json`` count table for slotting to consume);
regeneration is byte-identical.

Seeds still matter for experiments: runs read the same book starting at a
per-seed offset (see ``models.Order``), so arms stay paired per seed while
seeds provide independent demand windows for error bars.
"""

from __future__ import annotations

import bisect
import json
import os
import random

from .constants import NUM_SKUS, ORDER_LINES_MEAN, ORDER_LINES_SD
from .aisles import sku_weight

BOOK_SEED = 20260714
LINES_PER_HOUR = 3000
HOURS = 15
TOTAL_LINES = LINES_PER_HOUR * HOURS  # 45,000

# Stamped into the book's metadata; a cached book generated under a
# different demand model regenerates automatically on load.
POPULARITY = "flat (uniform over SKUs; user spec 2026-07-15)"

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
BOOK_PATH = os.path.join(_DATA_DIR, "order_book.json")
FREQ_PATH = os.path.join(_DATA_DIR, "order_book_frequencies.json")


def generate_order_book(
    total_lines: int = TOTAL_LINES,
    mean: float = ORDER_LINES_MEAN,
    sd: float = ORDER_LINES_SD,
    seed: int = BOOK_SEED,
) -> list[list[int]]:
    """Deterministically generate the order list (same seed → same book).

    Sampling is popularity-weighted WITHOUT replacement within an order
    (an order's lines are distinct SKUs), via inverse-CDF + rejection —
    the hottest SKU is ~0.1% of the mass, so rejections are rare.
    """
    rng = random.Random(seed)
    cum: list[float] = []
    acc = 0.0
    for sku in range(1, NUM_SKUS + 1):
        acc += sku_weight(sku)
        cum.append(acc)
    total_w = cum[-1]

    book: list[list[int]] = []
    lines_so_far = 0
    while lines_so_far < total_lines:
        n = max(1, round(rng.gauss(mean, sd)))
        chosen: set[int] = set()
        while len(chosen) < min(n, NUM_SKUS):
            sku = bisect.bisect_left(cum, rng.random() * total_w) + 1
            chosen.add(sku)
        order = sorted(chosen)
        book.append(order)
        lines_so_far += len(order)
    return book


def sku_frequencies(book: list[list[int]]) -> dict[int, int]:
    """How often each SKU occurs across the book — 'the most commonly
    occurring' table that frequency-based slotting consumes."""
    freq: dict[int, int] = {}
    for order in book:
        for sku in order:
            freq[sku] = freq.get(sku, 0) + 1
    return freq


def ensure_order_book(path: str = BOOK_PATH) -> list[list[int]]:
    """Load the canonical book, generating and persisting it on first use
    (both the book and its frequency table). A cached book built under a
    different demand model (metadata popularity mismatch) regenerates."""
    if os.path.exists(path):
        with open(path) as f:
            payload = json.load(f)
        if payload.get("metadata", {}).get("popularity") == POPULARITY:
            return payload["orders"]
    book = generate_order_book()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "metadata": {
            "seed": BOOK_SEED,
            "lines_per_hour": LINES_PER_HOUR,
            "hours": HOURS,
            "total_lines": sum(len(o) for o in book),
            "orders": len(book),
            "order_size": f"max(1, round(N({ORDER_LINES_MEAN}, {ORDER_LINES_SD})))",
            "popularity": POPULARITY,
        },
        "orders": book,
    }
    with open(path, "w") as f:
        json.dump(payload, f)
    if path == BOOK_PATH:  # frequency table rides with the canonical book
        freq = sku_frequencies(book)
        with open(FREQ_PATH, "w") as f:
            json.dump({str(k): v for k, v in sorted(freq.items())}, f)
    return book
