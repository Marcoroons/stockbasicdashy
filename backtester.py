"""
backtest.py - historical returns + forward projection.

Honest framing (please keep this in mind):
  - A BACKTEST reports what already happened to a real price series. It is the
    past, not a forecast. A great backtest does not promise a great future.
  - The PROJECTION simply grows your money at an annual rate YOU assume. It's a
    what-if calculator, not a prediction. Past CAGR does not predict future CAGR.
  - Figures use adjusted prices (splits + dividends reflected), so they
    approximate TOTAL return assuming dividends were reinvested.
"""

from __future__ import annotations

import datetime as dt

import stock_analyzer as sa


def _adj_close(ticker: str, start: str, end: str):
    """Adjusted close series between two ISO dates (dividends/splits reflected)."""
    try:
        h = sa.yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
    except Exception:
        return None
    if h is None or h.empty:
        return None
    s = h["Close"].dropna()
    return s if len(s) >= 2 else None


def cagr(start_value: float, end_value: float, years: float):
    if start_value <= 0 or years <= 0 or end_value <= 0:
        return None
    return (end_value / start_value) ** (1 / years) - 1


def _date_range(years: float):
    end = dt.date.today()
    start = end - dt.timedelta(days=int(years * 365.25))
    return start.isoformat(), end.isoformat()


def lump_sum(ticker: str, amount: float, years: float):
    """Invest `amount` once at the start, hold to today."""
    start, end = _date_range(years)
    s = _adj_close(ticker, start, end)
    if s is None:
        return None
    p0, p1 = float(s.iloc[0]), float(s.iloc[-1])
    shares = amount / p0
    end_value = shares * p1
    actual_years = (s.index[-1] - s.index[0]).days / 365.25
    return {
        "mode": "lump_sum",
        "invested": amount,
        "end_value": end_value,
        "profit": end_value - amount,
        "total_return": end_value / amount - 1,
        "cagr": cagr(amount, end_value, actual_years),
        "years": actual_years,
        "value_series": shares * s,        # portfolio value over time (for chart)
    }


def _irr_monthly(cashflows: list[float]):
    """Money-weighted monthly IRR via bisection. cashflows indexed by month."""
    def npv(r):
        return sum(cf / ((1 + r) ** i) for i, cf in enumerate(cashflows))
    lo, hi = -0.99, 1.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        v = npv(mid)
        if abs(v) < 1e-6:
            return mid
        if npv(lo) * v < 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def dca(ticker: str, monthly: float, years: float):
    """Invest `monthly` at the start of each month (dollar-cost averaging)."""
    start, end = _date_range(years)
    s = _adj_close(ticker, start, end)
    if s is None:
        return None
    months = s.resample("MS").first().dropna()
    if len(months) < 2:
        return None

    total_shares = invested = 0.0
    value_curve = {}
    flows = []
    for date, price in months.items():
        price = float(price)
        if price <= 0:
            continue
        total_shares += monthly / price
        invested += monthly
        flows.append(-monthly)
        value_curve[date] = total_shares * price  # value at each contribution

    end_price = float(s.iloc[-1])
    end_value = total_shares * end_price
    flows.append(end_value)  # final inflow for IRR
    mr = _irr_monthly(flows)
    annualized = ((1 + mr) ** 12 - 1) if mr is not None else None

    import pandas as pd
    return {
        "mode": "dca",
        "invested": invested,
        "end_value": end_value,
        "profit": end_value - invested,
        "total_return": end_value / invested - 1 if invested else None,
        "cagr": annualized,         # money-weighted (IRR), comparable to lump-sum CAGR
        "years": (s.index[-1] - s.index[0]).days / 365.25,
        "contributions": len(months),
        "value_series": pd.Series(value_curve),
    }


def project(principal: float, annual_rate: float, years: int,
            monthly_contribution: float = 0.0):
    """Grow `principal` at `annual_rate`, optionally adding monthly. ASSUMPTION
    ONLY. Returns [(year, balance)] including year 0."""
    rows = [(0, principal)]
    bal = principal
    mr = (1 + annual_rate) ** (1 / 12) - 1   # effective monthly rate
    for m in range(1, int(years) * 12 + 1):
        bal = bal * (1 + mr) + monthly_contribution
        if m % 12 == 0:
            rows.append((m // 12, bal))
    return rows