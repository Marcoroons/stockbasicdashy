"""
portfolio.py - portfolio health engine.

Computes the "what do I own / what am I exposed to" numbers from a list of
holdings: position values & weights, period returns, and risk metrics
(CAGR, volatility, Sharpe, Sortino, max drawdown, beta).

Honest notes:
  - Returns assume you held your CURRENT holdings across the whole period
    (a "what these positions would have done"), not your actual trade timing.
  - Totals assume ONE currency. Mixing, say, USD and IDR holdings makes the
    portfolio total meaningless - keep a portfolio in a single currency.
  - The risk-free rate (for Sharpe/Sortino) is an assumption you can change.
"""

from __future__ import annotations

import math

import pandas as pd

import stock_analyzer as sa

TRADING_DAYS = 252
PERIOD_DAYS = {"1y": 365, "2y": 730, "5y": 1825, "10y": 3650}


def combined_value_series(holdings: list[dict], period: str = "5y"):
    """Sum of shares × price across holdings, aligned on dates."""
    cols = []
    for h in holdings:
        hist = sa.price_history(h["ticker"], period=period)
        if hist is None or hist.empty:
            continue
        v = hist["Close"] * float(h["shares"])
        v.name = h["ticker"]
        cols.append(v)
    if not cols:
        return None
    df = pd.concat(cols, axis=1).ffill().dropna(how="all")
    return df.sum(axis=1)


def _ret_since(series, days: int):
    if series is None or len(series) < 2:
        return None
    target = series.index[-1] - pd.Timedelta(days=days)
    past = series.asof(target)
    if past is None or past != past or past == 0:
        return None
    return series.iloc[-1] / past - 1


def period_returns(series) -> dict:
    if series is None or len(series) < 2:
        return {}
    out = {
        "daily": series.iloc[-1] / series.iloc[-2] - 1,
        "weekly": _ret_since(series, 7),
        "monthly": _ret_since(series, 30),
        "lifetime": series.iloc[-1] / series.iloc[0] - 1,
    }
    last = series.index[-1]
    jan1 = pd.Timestamp(year=last.year, month=1, day=1, tz=series.index.tz)
    base = series.asof(jan1)
    out["ytd"] = (series.iloc[-1] / base - 1) if (base and base == base) else None
    return out


def risk_metrics(series, risk_free: float = 0.04) -> dict:
    """CAGR, volatility, Sharpe, Sortino, max drawdown from a value series."""
    if series is None or len(series) < 3:
        return {}
    rets = series.pct_change().dropna()
    years = (series.index[-1] - series.index[0]).days / 365.25
    cagr = ((series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1
            if years > 0 and series.iloc[0] > 0 else None)
    vol = rets.std() * math.sqrt(TRADING_DAYS)
    downside = rets[rets < 0]
    dvol = downside.std() * math.sqrt(TRADING_DAYS) if len(downside) > 1 else None
    sharpe = ((cagr - risk_free) / vol) if (cagr is not None and vol) else None
    sortino = ((cagr - risk_free) / dvol) if (cagr is not None and dvol) else None
    mdd = (series / series.cummax() - 1).min()
    return {"cagr": cagr, "volatility": vol, "sharpe": sharpe,
            "sortino": sortino, "max_drawdown": float(mdd), "years": years}


def portfolio_beta(port_series, benchmark: str = "^GSPC", period: str = "5y"):
    """Returns-based beta of the portfolio vs a benchmark index."""
    if port_series is None:
        return None
    b = sa.price_history(benchmark, period=period)
    if b is None or b.empty:
        return None
    df = pd.concat([port_series.rename("p"), b["Close"].rename("m")], axis=1).dropna()
    if len(df) < 10:
        return None
    r = df.pct_change().dropna()
    var = r["m"].var()
    return (r["p"].cov(r["m"]) / var) if var else None


def positions(holdings: list[dict]) -> tuple[list[dict], float]:
    """Per-holding value, weight, gain/loss, sector. Fetches fundamentals each."""
    rows, total = [], 0.0
    for h in holdings:
        try:
            f = sa.fetch_fundamentals(h["ticker"])
        except Exception:
            continue
        price = f.price
        shares = float(h["shares"])
        cost_basis = float(h.get("cost_basis") or 0)
        value = price * shares if price else None
        cost = cost_basis * shares if cost_basis else None
        rows.append({
            "ticker": h["ticker"], "shares": shares, "price": price,
            "value": value, "cost": cost, "sector": f.sector or "Unknown",
            "currency": f.currency or "", "dividend_yield": f.dividend_yield,
            "gain_loss": (value / cost - 1) if (value and cost) else None,
        })
        if value:
            total += value
    for r in rows:
        r["weight"] = (r["value"] / total) if (r["value"] and total) else None
    return rows, total


def sector_allocation(rows: list[dict]) -> dict:
    alloc = {}
    for r in rows:
        if r["weight"]:
            alloc[r["sector"]] = alloc.get(r["sector"], 0) + r["weight"]
    return dict(sorted(alloc.items(), key=lambda kv: -kv[1]))