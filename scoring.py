"""
scoring.py - Phase 2 calibration layer.

Turns raw metrics into YOUR score. The two things you calibrate are:
  1. CATEGORY_WEIGHTS  - how much each category matters to you.
  2. METRIC_CONFIG      - the bands that map a raw value to a 0-100 sub-score,
                          plus each metric's weight inside its category.

Everything here is a transparent starting point, NOT investment advice and NOT
universal truth. Good bands differ by sector (a bank's debt/equity is not a
software firm's). Treat these as v1 and tune them as you learn.

Run:
    python scoring.py AAPL
    python scoring.py MSFT --target-pe 22
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Optional

import stock_analyzer as sa


# --------------------------------------------------------------------------- #
# GLOSSARY  - plain-English meaning of every metric, for the dashboard tooltips
# --------------------------------------------------------------------------- #
GLOSSARY = {
    "roe": ("Return on Equity",
            "Profit made per $1 of shareholder money. Higher is better, but high "
            "ROE built on heavy debt is a red flag - always read it next to debt."),
    "roa": ("Return on Assets",
            "Profit per $1 of everything the company owns. Useful for asset-heavy "
            "businesses; debt-blind, so it complements ROE."),
    "gross_margin": ("Gross Margin",
            "Share of revenue left after the direct cost of making the product. "
            "High and STABLE margins hint at pricing power / a moat."),
    "operating_margin": ("Operating Margin",
            "Profit left after running the business, before interest and tax. "
            "Measures core operational efficiency."),
    "profit_margin": ("Net Profit Margin",
            "The bottom line: profit as a share of revenue after everything."),
    "pe": ("Price / Earnings",
            "Price paid per $1 of annual earnings. Lower can mean cheaper, but a "
            "low P/E on a shrinking business is a trap. Negative = no earnings."),
    "peg": ("PEG Ratio",
            "P/E divided by growth rate. Normalises P/E for growth - under ~1 is "
            "often 'cheap for how fast it's growing'."),
    "ev_to_ebitda": ("EV / EBITDA",
            "Whole-company value vs core earnings. Pros prefer it to P/E because "
            "it's neutral to differences in debt and tax. Lower is cheaper."),
    "price_to_sales": ("Price / Sales",
            "Price per $1 of revenue. Handy for companies not yet profitable."),
    "pb": ("Price / Book",
            "Price vs accounting net worth. Matters most for banks and asset-heavy "
            "firms; less meaningful for asset-light software."),
    "debt_to_equity": ("Debt / Equity",
            "Borrowed money vs shareholder money. Higher = more leverage = more "
            "risk in a downturn. Acceptable levels vary a lot by sector."),
    "current_ratio": ("Current Ratio",
            "Short-term assets vs short-term bills. Above 1 means it can cover the "
            "next year's obligations; very high can mean idle cash."),
    "quick_ratio": ("Quick Ratio",
            "Like current ratio but excludes inventory - a stricter liquidity test."),
    "revenue_growth": ("Revenue Growth",
            "How fast sales are growing year over year. Consistency beats one big year."),
    "earnings_growth": ("Earnings Growth",
            "How fast profit is growing. Watch it's not just cost-cutting."),
    "fcf_yield": ("Free Cash Flow Yield",
            "Real cash generated per $1 of market value. Cash is far harder to fake "
            "than reported earnings - a core quality check."),
    "cash_conversion": ("Cash Conversion",
            "Free cash flow divided by net income. Consistently below ~1 means "
            "reported profit isn't turning into actual cash - a warning sign."),
    "dividend_yield": ("Dividend Yield",
            "Annual dividend as a share of price. Zero isn't bad - many great "
            "growth firms reinvest instead of paying out."),
    "payout_ratio": ("Payout Ratio",
            "Share of earnings paid as dividends. Above 100% means paying more than "
            "it earns - usually unsustainable."),
}


# --------------------------------------------------------------------------- #
# CALIBRATION  - edit these to make the score yours
# --------------------------------------------------------------------------- #
CATEGORY_WEIGHTS = {
    "quality":   0.25,
    "valuation": 0.20,
    "health":    0.15,
    "growth":    0.15,
    "cashflow":  0.15,
    "income":    0.10,
}

# Each metric: category, in-category weight, direction, and scoring bands.
# direction 'higher' -> bigger value = better; 'lower' -> smaller = better.
# Bands are (threshold, score) ascending by threshold.
METRIC_CONFIG = {
    # ---- quality ----
    "roe":              dict(cat="quality", w=1.0, dir="higher",
                             bands=[(0,20),(0.05,40),(0.10,55),(0.15,75),(0.20,90),(0.30,100)]),
    "roa":              dict(cat="quality", w=0.7, dir="higher",
                             bands=[(0,20),(0.02,45),(0.05,65),(0.08,85),(0.12,100)]),
    "gross_margin":     dict(cat="quality", w=0.8, dir="higher",
                             bands=[(0,10),(0.20,40),(0.35,60),(0.50,80),(0.65,100)]),
    "operating_margin": dict(cat="quality", w=0.9, dir="higher",
                             bands=[(0,10),(0.05,40),(0.10,60),(0.20,85),(0.30,100)]),
    "profit_margin":    dict(cat="quality", w=0.8, dir="higher",
                             bands=[(0,10),(0.05,45),(0.10,65),(0.20,90),(0.30,100)]),
    # ---- valuation (lower is better) ----
    "pe":               dict(cat="valuation", w=1.0, dir="lower",
                             bands=[(12,100),(18,85),(25,65),(35,45),(50,25),(80,10)]),
    "peg":              dict(cat="valuation", w=0.9, dir="lower",
                             bands=[(1.0,100),(1.5,80),(2.0,60),(3.0,35),(5.0,15)]),
    "ev_to_ebitda":     dict(cat="valuation", w=0.9, dir="lower",
                             bands=[(8,100),(12,80),(16,60),(22,40),(30,20)]),
    "price_to_sales":   dict(cat="valuation", w=0.6, dir="lower",
                             bands=[(1,100),(3,80),(6,60),(10,40),(20,20)]),
    "pb":               dict(cat="valuation", w=0.6, dir="lower",
                             bands=[(1,100),(2,85),(4,60),(7,40),(12,20)]),
    # ---- health (debt lower better, liquidity higher better) ----
    "debt_to_equity":   dict(cat="health", w=1.0, dir="lower",
                             bands=[(0.3,100),(0.6,85),(1.0,70),(1.5,50),(2.5,30),(4.0,15)]),
    "current_ratio":    dict(cat="health", w=0.8, dir="higher",
                             bands=[(0.8,20),(1.0,50),(1.5,80),(2.0,100)]),
    "quick_ratio":      dict(cat="health", w=0.8, dir="higher",
                             bands=[(0.5,30),(0.8,55),(1.0,80),(1.5,100)]),
    # ---- growth ----
    "revenue_growth":   dict(cat="growth", w=1.0, dir="higher",
                             bands=[(-0.05,10),(0,30),(0.05,55),(0.10,75),(0.20,90),(0.35,100)]),
    "earnings_growth":  dict(cat="growth", w=1.0, dir="higher",
                             bands=[(-0.05,10),(0,30),(0.05,55),(0.10,75),(0.20,90),(0.40,100)]),
    # ---- cash flow ----
    "fcf_yield":        dict(cat="cashflow", w=1.0, dir="higher",
                             bands=[(0,15),(0.02,45),(0.04,65),(0.06,85),(0.10,100)]),
    "cash_conversion":  dict(cat="cashflow", w=0.8, dir="higher",
                             bands=[(0,10),(0.5,40),(0.8,70),(1.0,100)]),
    # ---- income ----
    "dividend_yield":   dict(cat="income", w=0.8, dir="higher",
                             bands=[(0,40),(0.01,55),(0.02,70),(0.035,90),(0.05,100)]),
    "payout_ratio":     dict(cat="income", w=0.7, dir="lower",
                             bands=[(0.6,100),(0.75,80),(0.9,55),(1.0,35),(1.5,15)]),
}


# --------------------------------------------------------------------------- #
# Scoring machinery
# --------------------------------------------------------------------------- #
def _score_higher(value: float, bands) -> float:
    s = 0.0
    for thr, sc in bands:
        if value >= thr:
            s = sc
    return s


def _score_lower(value: float, bands) -> float:
    for thr, sc in bands:
        if value <= thr:
            return sc
    return 0.0


def _metric_value(f: sa.Fundamentals, key: str) -> Optional[float]:
    """Resolve a config key to a value on the Fundamentals object."""
    if key == "pe":
        return f.pe_forward or f.pe_trailing
    if key == "peg":
        return f.peg_ratio
    if key == "pb":
        return f.pb_ratio
    return getattr(f, key, None)


@dataclass
class MetricScore:
    key: str
    label: str
    value: Optional[float]
    score: Optional[float]
    category: str


def score_metric(f: sa.Fundamentals, key: str, cfg: dict) -> MetricScore:
    val = _metric_value(f, key)
    label = GLOSSARY.get(key, (key, ""))[0]
    if val is None:
        return MetricScore(key, label, None, None, cfg["cat"])
    # earnings-based valuation is meaningless when earnings are negative
    if key == "pe" and val <= 0:
        return MetricScore(key, label, val, 0.0, cfg["cat"])
    sc = (_score_higher(val, cfg["bands"]) if cfg["dir"] == "higher"
          else _score_lower(val, cfg["bands"]))
    return MetricScore(key, label, val, sc, cfg["cat"])


def composite_score(f: sa.Fundamentals,
                    metric_config=METRIC_CONFIG,
                    category_weights=CATEGORY_WEIGHTS):
    """Returns (overall_0_to_100, per_category_dict, list_of_MetricScore)."""
    scored = [score_metric(f, k, c) for k, c in metric_config.items()]

    cat_scores = {}
    for cat in category_weights:
        items = [(metric_config[m.key]["w"], m.score)
                 for m in scored if m.category == cat and m.score is not None]
        if items:
            wsum = sum(w for w, _ in items)
            cat_scores[cat] = sum(w * s for w, s in items) / wsum if wsum else None

    avail = {c: category_weights[c] for c in cat_scores}
    total_w = sum(avail.values())
    overall = (sum(category_weights[c] * cat_scores[c] for c in cat_scores) / total_w
               if total_w else None)
    return overall, cat_scores, scored


def lean_from_score(overall: Optional[float]) -> str:
    if overall is None:
        return "INSUFFICIENT DATA"
    if overall >= 75:
        return f"STRONG on your metrics ({overall:.0f}/100)"
    if overall >= 60:
        return f"FAVOURABLE ({overall:.0f}/100)"
    if overall >= 45:
        return f"MIXED ({overall:.0f}/100)"
    return f"WEAK on your metrics ({overall:.0f}/100)"


# --------------------------------------------------------------------------- #
# Risk / reward as a percentage
# --------------------------------------------------------------------------- #
@dataclass
class RiskReward:
    reward_pct: Optional[float] = None   # upside to target
    risk_pct: Optional[float] = None     # downside to floor
    ratio: Optional[float] = None        # reward : risk
    favorability_pct: Optional[float] = None  # 0-100, 50 = even


def risk_reward(f: sa.Fundamentals, blended_intrinsic: Optional[float]) -> RiskReward:
    """Reward = upside to a target (analyst mean, else your blended intrinsic).
    Risk   = downside to a floor (52-week low). Both relative to today's price.
    Favorability = reward / (reward + risk), as a percent.

    This is a heuristic, not a probability. The 'floor' is an assumption; a
    stock can always fall below its 52-week low."""
    if not f.price:
        return RiskReward()
    target = f.analyst_target_mean or blended_intrinsic
    floor = f.week52_low
    if not target or not floor:
        return RiskReward()

    reward = (target - f.price) / f.price
    risk = (f.price - floor) / f.price
    r = max(reward, 0.0)
    k = max(risk, 1e-6)  # avoid div-by-zero if price sits at/below the floor
    favor = r / (r + k) * 100
    ratio = (r / k) if k > 1e-6 else None
    return RiskReward(reward_pct=reward, risk_pct=risk, ratio=ratio,
                      favorability_pct=favor)


# --------------------------------------------------------------------------- #
# Data-driven bull / bear case  (your "positive and negative" list)
# --------------------------------------------------------------------------- #
def bull_bear(scored, strong=75, weak=35):
    """Reads the company's OWN numbers - not opinions. Strengths are metrics
    that score well, weaknesses are those that score poorly."""
    bull, bear = [], []
    for m in scored:
        if m.score is None:
            continue
        if m.score >= strong:
            bull.append((m.label, m.value))
        elif m.score <= weak:
            bear.append((m.label, m.value))
    return bull, bear


def analyst_view(f: sa.Fundamentals) -> str:
    """Summarises what analysts currently say. This is third-party sentiment
    surfaced as data - not a recommendation from this tool."""
    if not f.recommendation_key and f.recommendation_mean is None:
        return "No analyst coverage available."
    parts = []
    if f.recommendation_key:
        parts.append(f"consensus: {f.recommendation_key.replace('_', ' ')}")
    if f.recommendation_mean is not None:
        parts.append(f"mean rating {f.recommendation_mean:.2f} (1=strong buy, 5=sell)")
    if f.num_analysts:
        parts.append(f"{f.num_analysts} analysts")
    if f.analyst_target_low and f.analyst_target_high:
        parts.append(f"targets {f.analyst_target_low:.0f}-{f.analyst_target_high:.0f}")
    return " | ".join(parts)


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def _pct(x):
    return "n/a" if x is None else f"{x*100:.1f}%"


def scorecard_report(ticker: str, target_pe=18.0, discount=0.09, growth=0.10) -> dict:
    f = sa.fetch_fundamentals(ticker)
    v = sa.value_stock(f, target_pe=target_pe, discount_rate=discount, growth_stage1=growth)
    overall, cats, scored = composite_score(f)
    rr = risk_reward(f, v.blended_intrinsic)
    bull, bear = bull_bear(scored)

    L = ["=" * 66, f" SCORECARD  -  {f.name or f.ticker} ({f.ticker})", "=" * 66]
    L.append(f" Overall: {lean_from_score(overall)}")
    L.append("")
    L.append(" Category breakdown:")
    for c, w in CATEGORY_WEIGHTS.items():
        s = cats.get(c)
        L.append(f"   {c:<10} weight {w:>4.0%}   "
                 f"{('%.0f/100' % s) if s is not None else 'n/a':>8}")
    L.append("")
    L.append(" Risk / reward:")
    L.append(f"   Upside to target : {_pct(rr.reward_pct)}")
    L.append(f"   Downside to floor: {_pct(rr.risk_pct)}")
    if rr.ratio is not None:
        L.append(f"   Reward:risk      : {rr.ratio:.2f} : 1")
    L.append(f"   Favorability     : "
             f"{('%.0f%%' % rr.favorability_pct) if rr.favorability_pct is not None else 'n/a'}"
             "  (50% = even)")
    L.append("")
    L.append(" Bull case (numbers in favour):")
    L += [f"   + {lbl}" for lbl, _ in bull] or ["   (none scored strong)"]
    L.append(" Bear case (numbers against):")
    L += [f"   - {lbl}" for lbl, _ in bear] or ["   (none scored weak)"]
    L.append("")
    L.append(f" Analyst view: {analyst_view(f)}")
    L.append("=" * 66)
    print("\n".join(L))
    return {"overall": overall, "categories": cats,
            "risk_reward": rr.__dict__, "bull": bull, "bear": bear}


def profile_flags(f: sa.Fundamentals):
    """Plain-language warnings about WHEN the scorecard is misleading.
    The point you raised: earnings aren't everything. These flags tell you when
    to lean on the story/growth/cash side instead of the earnings-based score."""
    flags = []
    pe = f.pe_forward or f.pe_trailing
    if f.eps_trailing is not None and f.eps_trailing <= 0:
        if f.revenue_growth and f.revenue_growth > 0.15:
            flags.append("Pre-profit growth company: P/E-based scores understate it. "
                         "Weigh revenue growth, cash runway and the narrative instead.")
        else:
            flags.append("Currently unprofitable: earnings-based metrics are unreliable here.")
    if pe and pe > 40:
        flags.append("Priced for high growth (very high P/E): highly sensitive to any miss.")
    if f.debt_to_equity and f.debt_to_equity > 2:
        flags.append("Heavily leveraged: more fragile in downturns or rising rates.")
    if f.cash_conversion is not None and f.cash_conversion < 0.6:
        flags.append("Profit isn't fully turning into cash: check earnings quality.")
    if f.beta and f.beta > 1.5:
        flags.append("High beta: expect larger swings than the broad market.")
    if f.num_analysts and f.num_analysts < 4:
        flags.append("Thin analyst coverage: consensus and targets are less reliable.")
    return flags


def main():
    p = argparse.ArgumentParser(description="Score a stock on your calibrated metrics.")
    p.add_argument("ticker")
    p.add_argument("--target-pe", type=float, default=18.0)
    p.add_argument("--discount", type=float, default=0.09)
    p.add_argument("--growth", type=float, default=0.10)
    a = p.parse_args()
    scorecard_report(a.ticker, a.target_pe, a.discount, a.growth)


if __name__ == "__main__":
    main()