"""
peers.py - sector-relative comparison.

Why this matters: a P/E of 30 is expensive for a bank and cheap for a fast
software company. Comparing a metric to its PEERS (a percentile rank) is far
more honest than a fixed threshold. This is the upgrade over absolute bands.

You supply the peer list. The starter map below is just a seed - edit freely,
or wire it to a sector lookup later.
"""

from __future__ import annotations

import stock_analyzer as sa

# Seed peer groups. Add your own; keys and values are plain tickers.
SECTOR_PEERS = {
    "AAPL": ["MSFT", "GOOGL", "AMZN", "META"],
    "MSFT": ["AAPL", "GOOGL", "AMZN", "ORCL"],
    "NVDA": ["AMD", "AVGO", "INTC", "QCOM"],
    "JPM":  ["BAC", "WFC", "C", "GS"],
    "KO":   ["PEP", "MNST", "KDP"],
}

# Which metrics to rank, and whether higher is better.
PEER_METRICS = {
    "roe": True, "operating_margin": True, "profit_margin": True,
    "revenue_growth": True, "fcf_yield": True,
    "pe_forward": False, "ev_to_ebitda": False, "debt_to_equity": False,
}


def percentile_rank(value, peer_values, higher_better=True):
    """What % of peers this value beats. 100 = best in group."""
    vals = [v for v in peer_values if v is not None]
    if value is None or not vals:
        return None
    if higher_better:
        better_than = sum(1 for v in vals if value > v)
    else:
        better_than = sum(1 for v in vals if value < v)
    return better_than / len(vals) * 100


def peers_for(ticker: str) -> list[str]:
    return SECTOR_PEERS.get(ticker.upper(), [])


def compare_to_peers(target: sa.Fundamentals, peer_tickers: list[str]) -> dict:
    """Returns {metric: {'value', 'peer_median', 'percentile'}} for each metric.
    Fetches each peer once. Caller should cache."""
    peer_funds = []
    for p in peer_tickers:
        try:
            peer_funds.append(sa.fetch_fundamentals(p))
        except Exception:
            continue  # skip a peer that fails rather than break the whole view

    out = {}
    for key, higher in PEER_METRICS.items():
        tv = getattr(target, key, None)
        pv = [getattr(f, key, None) for f in peer_funds]
        clean = sorted(v for v in pv if v is not None)
        median = clean[len(clean) // 2] if clean else None
        out[key] = {
            "value": tv,
            "peer_median": median,
            "percentile": percentile_rank(tv, pv, higher),
            "higher_better": higher,
        }
    return out
