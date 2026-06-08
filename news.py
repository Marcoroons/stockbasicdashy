"""
news.py - recent headlines as CONTEXT, not as a signal.

Important: automated news sentiment is noisy and a weak predictor of returns.
This module surfaces headlines so YOU can judge the qualitative story (a
pending lawsuit, a product launch, a CEO change) that the numbers can't show.
The crude tilt score is a reading aid, not a buy/sell input. Do not let it
drive the scorecard.
"""

from __future__ import annotations

import yfinance as yf

_POS = {"beats", "surge", "record", "growth", "upgrade", "raises", "wins",
        "strong", "soars", "rally", "outperform", "expands", "approval"}
_NEG = {"miss", "plunge", "lawsuit", "probe", "downgrade", "cuts", "warns",
        "weak", "falls", "recall", "layoffs", "decline", "fraud", "delay"}


def recent_news(ticker: str, limit: int = 8) -> list[dict]:
    """Return a list of {title, publisher, link}. Handles both old and new
    yfinance payload shapes defensively."""
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        return []
    items = []
    for n in raw[:limit]:
        # Newer yfinance nests fields under 'content'
        c = n.get("content", n)
        title = c.get("title") or n.get("title")
        if not title:
            continue
        publisher = (c.get("provider", {}) or {}).get("displayName") \
            or n.get("publisher") or ""
        link = (c.get("canonicalUrl", {}) or {}).get("url") \
            or n.get("link") or ""
        items.append({"title": title, "publisher": publisher, "link": link})
    return items


def headline_tilt(headlines: list[dict]) -> str:
    """A rough positive/negative lean from headline wording. Reading aid only."""
    if not headlines:
        return "no recent headlines"
    pos = neg = 0
    for h in headlines:
        words = set(h["title"].lower().split())
        pos += len(words & _POS)
        neg += len(words & _NEG)
    if pos == neg:
        return f"mixed/neutral ({pos} positive vs {neg} negative cues)"
    lean = "positive" if pos > neg else "negative"
    return f"headlines lean {lean} ({pos} positive vs {neg} negative cues)"
