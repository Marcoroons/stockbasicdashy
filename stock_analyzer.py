"""
stock_analyzer.py - Phase 1 core for the long-term investing dashboard.

What it does right now:
  - Pulls fundamentals (EPS, book value, market cap, beta, P/E, P/B, ROE,
    debt/equity, margins, dividend yield, analyst target, 52-week range...)
  - Pulls the company profile (what it does, sector, country, website)
  - Computes three independent intrinsic-value estimates:
        1. Graham Number      (conservative, asset+earnings based)
        2. P/E-implied price  (earnings x a target multiple you choose)
        3. Two-stage DCF       (discounted free cash flow)
  - Produces a simple, fully transparent buy/hold/avoid lean with a
    margin-of-safety check. Every threshold is a parameter you can calibrate.

What it is NOT:
  - A price predictor. Intrinsic value != future price. These are *estimates
    of what the business is plausibly worth* under stated assumptions, which
    is a different and more honest thing than forecasting the market.

Setup:
    pip install yfinance pandas
Run:
    python stock_analyzer.py AAPL
    python stock_analyzer.py MSFT --target-pe 22 --discount 0.10
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, asdict
from typing import Optional

import yfinance as yf


# --------------------------------------------------------------------------- #
# Data containers
# --------------------------------------------------------------------------- #
@dataclass
class Fundamentals:
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    summary: Optional[str] = None

    currency: Optional[str] = None
    price: Optional[float] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None

    eps_trailing: Optional[float] = None
    eps_forward: Optional[float] = None
    book_value_per_share: Optional[float] = None

    pe_trailing: Optional[float] = None
    pe_forward: Optional[float] = None
    pb_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    beta: Optional[float] = None

    # valuation extras
    price_to_sales: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    ev_to_revenue: Optional[float] = None

    # quality / profitability
    roe: Optional[float] = None
    roa: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    profit_margin: Optional[float] = None

    # health
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None

    # growth
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None

    # cash flow
    free_cash_flow: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    net_income: Optional[float] = None
    fcf_yield: Optional[float] = None          # derived: FCF / market cap
    cash_conversion: Optional[float] = None     # derived: FCF / net income

    # income / shareholder return
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None

    # analyst sentiment ("current advice", positive & negative)
    analyst_target_mean: Optional[float] = None
    analyst_target_high: Optional[float] = None
    analyst_target_low: Optional[float] = None
    recommendation_key: Optional[str] = None    # e.g. 'buy', 'hold', 'sell'
    recommendation_mean: Optional[float] = None  # 1=strong buy ... 5=strong sell
    num_analysts: Optional[int] = None

    week52_high: Optional[float] = None
    week52_low: Optional[float] = None


@dataclass
class Valuation:
    graham_number: Optional[float] = None
    pe_implied_price: Optional[float] = None
    dcf_per_share: Optional[float] = None
    # Average of whichever estimates were computable:
    blended_intrinsic: Optional[float] = None
    margin_of_safety: Optional[float] = None  # (intrinsic - price) / intrinsic


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def _g(info: dict, *keys):
    """Return the first present, non-None value among keys, else None."""
    for k in keys:
        v = info.get(k)
        if v is not None:
            return v
    return None


def fetch_fundamentals(ticker: str) -> Fundamentals:
    """Pull everything we can for one ticker. Missing fields stay None."""
    t = yf.Ticker(ticker)
    try:
        info = t.info or {}
    except Exception as e:
        raise RuntimeError(f"Could not fetch data for {ticker}: {e}")

    div_yield = _g(info, "dividendYield")
    # yfinance has historically reported this both as a fraction and a percent;
    # normalise anything that looks like a percent back to a fraction.
    if div_yield is not None and div_yield > 1:
        div_yield = div_yield / 100.0

    f = Fundamentals(
        ticker=ticker.upper(),
        name=_g(info, "longName", "shortName"),
        sector=_g(info, "sector"),
        industry=_g(info, "industry"),
        country=_g(info, "country"),
        website=_g(info, "website"),
        summary=_g(info, "longBusinessSummary"),
        currency=_g(info, "currency"),
        price=_g(info, "currentPrice", "regularMarketPrice", "previousClose"),
        market_cap=_g(info, "marketCap"),
        shares_outstanding=_g(info, "sharesOutstanding"),
        eps_trailing=_g(info, "trailingEps"),
        eps_forward=_g(info, "forwardEps"),
        book_value_per_share=_g(info, "bookValue"),
        pe_trailing=_g(info, "trailingPE"),
        pe_forward=_g(info, "forwardPE"),
        pb_ratio=_g(info, "priceToBook"),
        peg_ratio=_g(info, "pegRatio", "trailingPegRatio"),
        beta=_g(info, "beta"),
        price_to_sales=_g(info, "priceToSalesTrailing12Months"),
        ev_to_ebitda=_g(info, "enterpriseToEbitda"),
        ev_to_revenue=_g(info, "enterpriseToRevenue"),
        roe=_g(info, "returnOnEquity"),
        roa=_g(info, "returnOnAssets"),
        gross_margin=_g(info, "grossMargins"),
        operating_margin=_g(info, "operatingMargins"),
        profit_margin=_g(info, "profitMargins"),
        debt_to_equity=_g(info, "debtToEquity"),
        current_ratio=_g(info, "currentRatio"),
        quick_ratio=_g(info, "quickRatio"),
        revenue_growth=_g(info, "revenueGrowth"),
        earnings_growth=_g(info, "earningsGrowth", "earningsQuarterlyGrowth"),
        free_cash_flow=_g(info, "freeCashflow"),
        operating_cash_flow=_g(info, "operatingCashflow"),
        net_income=_g(info, "netIncomeToCommon"),
        dividend_yield=div_yield,
        payout_ratio=_g(info, "payoutRatio"),
        analyst_target_mean=_g(info, "targetMeanPrice"),
        analyst_target_high=_g(info, "targetHighPrice"),
        analyst_target_low=_g(info, "targetLowPrice"),
        recommendation_key=_g(info, "recommendationKey"),
        recommendation_mean=_g(info, "recommendationMean"),
        num_analysts=_g(info, "numberOfAnalystOpinions"),
        week52_high=_g(info, "fiftyTwoWeekHigh"),
        week52_low=_g(info, "fiftyTwoWeekLow"),
    )

    # yfinance sometimes reports debt/equity as a percentage (e.g. 150 = 1.5x);
    # normalise to a multiple so thresholds behave consistently.
    if f.debt_to_equity is not None and f.debt_to_equity > 10:
        f.debt_to_equity = f.debt_to_equity / 100.0

    # derived metrics
    if f.free_cash_flow and f.market_cap:
        f.fcf_yield = f.free_cash_flow / f.market_cap
    if f.free_cash_flow and f.net_income and f.net_income != 0:
        f.cash_conversion = f.free_cash_flow / f.net_income

    return f


# --------------------------------------------------------------------------- #
# Valuation models  (all assumptions are explicit and overridable)
# --------------------------------------------------------------------------- #
def graham_number(eps: Optional[float], bvps: Optional[float]) -> Optional[float]:
    """Benjamin Graham's rough fair-value ceiling: sqrt(22.5 * EPS * BVPS).
    Only meaningful for profitable companies with positive book value."""
    if eps and bvps and eps > 0 and bvps > 0:
        return math.sqrt(22.5 * eps * bvps)
    return None


def pe_implied_price(eps: Optional[float], target_pe: float) -> Optional[float]:
    """What the price 'should' be if the market paid your target multiple
    for these earnings. Uses forward EPS if you pass it."""
    if eps and eps > 0:
        return eps * target_pe
    return None


def dcf_per_share(
    free_cash_flow: Optional[float],
    shares: Optional[float],
    growth_stage1: float = 0.10,
    years_stage1: int = 5,
    terminal_growth: float = 0.025,
    discount_rate: float = 0.09,
) -> Optional[float]:
    """Two-stage discounted cash flow.

    Stage 1: FCF grows at `growth_stage1` for `years_stage1` years.
    Terminal: Gordon-growth perpetuity at `terminal_growth`.
    Everything discounted back at `discount_rate`.

    These four numbers ARE the opinion. Change them and the answer changes a
    lot, which is the honest truth about DCF - it's a structured guess, not an
    oracle. Defaults are deliberately moderate.
    """
    if not free_cash_flow or not shares or free_cash_flow <= 0:
        return None
    if discount_rate <= terminal_growth:
        return None  # perpetuity formula breaks otherwise

    pv = 0.0
    cf = float(free_cash_flow)
    for year in range(1, years_stage1 + 1):
        cf *= (1 + growth_stage1)
        pv += cf / (1 + discount_rate) ** year

    terminal_value = (cf * (1 + terminal_growth)) / (discount_rate - terminal_growth)
    pv += terminal_value / (1 + discount_rate) ** years_stage1

    return pv / shares


def value_stock(
    f: Fundamentals,
    target_pe: float = 18.0,
    discount_rate: float = 0.09,
    growth_stage1: float = 0.10,
) -> Valuation:
    eps_for_pe = f.eps_forward or f.eps_trailing
    g = graham_number(f.eps_trailing, f.book_value_per_share)
    pe_price = pe_implied_price(eps_for_pe, target_pe)
    dcf = dcf_per_share(
        f.free_cash_flow,
        f.shares_outstanding,
        growth_stage1=growth_stage1,
        discount_rate=discount_rate,
    )

    estimates = [x for x in (g, pe_price, dcf) if x and x > 0]
    blended = sum(estimates) / len(estimates) if estimates else None
    mos = None
    if blended and f.price:
        mos = (blended - f.price) / blended

    return Valuation(
        graham_number=g,
        pe_implied_price=pe_price,
        dcf_per_share=dcf,
        blended_intrinsic=blended,
        margin_of_safety=mos,
    )


# --------------------------------------------------------------------------- #
# A transparent, calibratable lean  (Phase 2 will make this your own)
# --------------------------------------------------------------------------- #
def simple_lean(f: Fundamentals, v: Valuation, mos_buy: float = 0.20,
                mos_avoid: float = -0.20) -> str:
    """Placeholder rule until we build your personal scoring model.
    Buy when there's a margin of safety above `mos_buy`, avoid when the price
    is well above intrinsic. This is a heuristic, not a recommendation."""
    if v.margin_of_safety is None:
        return "INSUFFICIENT DATA"
    if v.margin_of_safety >= mos_buy:
        return f"LEANS UNDERVALUED ({v.margin_of_safety:+.0%} vs price)"
    if v.margin_of_safety <= mos_avoid:
        return f"LEANS OVERVALUED ({v.margin_of_safety:+.0%} vs price)"
    return f"ROUGHLY FAIR ({v.margin_of_safety:+.0%} vs price)"


# --------------------------------------------------------------------------- #
# Pretty printing
# --------------------------------------------------------------------------- #
def _fmt(x, pct=False, money=False, big=False):
    if x is None:
        return "n/a"
    if pct:
        return f"{x*100:.2f}%"
    if big and abs(x) >= 1e9:
        return f"{x/1e9:.2f}B"
    if money:
        return f"{x:,.2f}"
    return f"{x:.2f}"


def report(f: Fundamentals, v: Valuation, lean: str) -> str:
    cur = f.currency or ""
    lines = [
        "=" * 64,
        f" {f.name or f.ticker}  ({f.ticker})",
        "=" * 64,
        f" Sector/Industry : {f.sector or 'n/a'} / {f.industry or 'n/a'}",
        f" Country/Site    : {f.country or 'n/a'}  {f.website or ''}",
        "",
        " --- MARKET ---",
        f" Price           : {_fmt(f.price, money=True)} {cur}",
        f" Market cap      : {_fmt(f.market_cap, big=True)} {cur}",
        f" 52w range       : {_fmt(f.week52_low, money=True)} - {_fmt(f.week52_high, money=True)}",
        f" Beta            : {_fmt(f.beta)}",
        f" Analyst target  : {_fmt(f.analyst_target_mean, money=True)} {cur}",
        "",
        " --- VALUE & QUALITY ---",
        f" EPS (ttm/fwd)   : {_fmt(f.eps_trailing)} / {_fmt(f.eps_forward)}",
        f" Book value/shr  : {_fmt(f.book_value_per_share)}",
        f" P/E (ttm/fwd)   : {_fmt(f.pe_trailing)} / {_fmt(f.pe_forward)}",
        f" P/B             : {_fmt(f.pb_ratio)}",
        f" PEG             : {_fmt(f.peg_ratio)}",
        f" ROE             : {_fmt(f.roe, pct=True)}",
        f" Debt/Equity     : {_fmt(f.debt_to_equity)}",
        f" Profit margin   : {_fmt(f.profit_margin, pct=True)}",
        f" Revenue growth  : {_fmt(f.revenue_growth, pct=True)}",
        f" Dividend yield  : {_fmt(f.dividend_yield, pct=True)}",
        f" Free cash flow  : {_fmt(f.free_cash_flow, big=True)} {cur}",
        "",
        " --- INTRINSIC VALUE ESTIMATES ---",
        f" Graham number   : {_fmt(v.graham_number, money=True)}",
        f" P/E-implied      : {_fmt(v.pe_implied_price, money=True)}",
        f" DCF / share     : {_fmt(v.dcf_per_share, money=True)}",
        f" Blended          : {_fmt(v.blended_intrinsic, money=True)}",
        f" Margin of safety : {_fmt(v.margin_of_safety, pct=True) if v.margin_of_safety is not None else 'n/a'}",
        "",
        f" LEAN            : {lean}",
        "=" * 64,
    ]
    if f.summary:
        snippet = f.summary[:400] + ("..." if len(f.summary) > 400 else "")
        lines += ["", " What the company does:", " " + snippet]
    return "\n".join(lines)


def analyze(ticker: str, target_pe: float = 18.0, discount_rate: float = 0.09,
            growth_stage1: float = 0.10) -> dict:
    f = fetch_fundamentals(ticker)
    v = value_stock(f, target_pe=target_pe, discount_rate=discount_rate,
                    growth_stage1=growth_stage1)
    lean = simple_lean(f, v)
    print(report(f, v, lean))
    return {"fundamentals": asdict(f), "valuation": asdict(v), "lean": lean}


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="Analyze a stock or ETF.")
    p.add_argument("ticker", help="Ticker symbol, e.g. AAPL")
    p.add_argument("--target-pe", type=float, default=18.0,
                   help="Target P/E for the earnings-based estimate")
    p.add_argument("--discount", type=float, default=0.09,
                   help="DCF discount rate (e.g. 0.09 = 9%%)")
    p.add_argument("--growth", type=float, default=0.10,
                   help="DCF stage-1 FCF growth rate (e.g. 0.10 = 10%%)")
    args = p.parse_args()
    analyze(args.ticker, target_pe=args.target_pe,
            discount_rate=args.discount, growth_stage1=args.growth)


if __name__ == "__main__":
    main()