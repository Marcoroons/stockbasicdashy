"""
profile.py - the investor profiling keystone.

A risk & goals self-assessment (the industry-standard kind) that infers the
user's investing characteristics from their answers, then personalises the rest
of the platform. NOT a clinical psychometric test, and NOT financial advice -
it matches investments to the user's *stated* preferences.

The profile drives two things downstream:
  1. weights_for_profile()  -> reweights the scorecard to what the user cares about
  2. assess_suitability()   -> answers "does this suit me?" with explicit reasons
"""

from __future__ import annotations

# --- onboarding questions --------------------------------------------------- #
# Each option carries either a categorical value (for a named dimension) or
# numeric "risk points" (for dimension == 'risk_pts'). Keep it short and clear.
QUESTIONS = [
    {"id": "goal", "dim": "goal",
     "q": "What do you mainly want this money to do?",
     "opts": [("Generate income now", "income"),
              ("Grow as much as possible long term", "growth"),
              ("A balance of growth and income", "balanced")]},
    {"id": "horizon", "dim": "horizon",
     "q": "When will you likely need this money?",
     "opts": [("Within 3 years", "short"),
              ("3 to 10 years", "medium"),
              ("More than 10 years", "long")]},
    {"id": "income_need", "dim": "income_need",
     "q": "Do you need regular cash income from these investments?",
     "opts": [("Yes, I rely on it", "high"),
              ("Some would be welcome", "medium"),
              ("No, I'm reinvesting everything", "none")]},
    {"id": "experience", "dim": "experience",
     "q": "How would you describe your investing experience?",
     "opts": [("Just starting out", "beginner"),
              ("Some experience", "intermediate"),
              ("Very experienced", "advanced")]},
    {"id": "style", "dim": "style",
     "q": "Which approach appeals to you most?",
     "opts": [("Buy cheap, undervalued companies", "value"),
              ("Back fast-growing companies", "growth"),
              ("Own steady dividend payers", "dividend"),
              ("Just track the whole market", "index")]},
    # --- risk-points questions (sum -> risk tolerance) ---
    {"id": "drawdown", "dim": "risk_pts",
     "q": "Your portfolio drops 30% in a few months. You...",
     "opts": [("Sell to stop the bleeding", 0),
              ("Feel uneasy but hold", 13),
              ("Hold calmly, it happens", 20),
              ("Buy more while it's cheap", 25)]},
    {"id": "volatility", "dim": "risk_pts",
     "q": "Which return pattern do you prefer?",
     "opts": [("Steady ~4%/yr, rarely down", 0),
              ("~7%/yr with occasional dips", 12),
              ("~10%/yr with regular swings", 20),
              ("Max growth, big swings are fine", 25)]},
    {"id": "allocation", "dim": "risk_pts",
     "q": "How much of your total savings is this money?",
     "opts": [("Almost all of it", 0),
              ("Roughly half", 12),
              ("A small portion I can afford to risk", 25)]},
    {"id": "loss_limit", "dim": "risk_pts",
     "q": "The most you could stomach losing in a bad year is...",
     "opts": [("Under 10%", 0), ("About 20%", 12),
              ("About 35%", 20), ("50%+ if the upside is there", 25)]},
]

RISK_LEVELS = ["very_conservative", "conservative", "moderate", "growth", "aggressive"]


def score_answers(answers: dict) -> dict:
    """answers: {question_id: chosen_value}. Returns a profile dict."""
    profile = {}
    risk_pts = 0
    for qn in QUESTIONS:
        val = answers.get(qn["id"])
        if val is None:
            continue
        if qn["dim"] == "risk_pts":
            risk_pts += int(val)
        else:
            profile[qn["dim"]] = val

    # 4 risk questions, max 100. Horizon nudges the band (short caps, long lifts).
    if profile.get("horizon") == "short":
        risk_pts -= 12
    elif profile.get("horizon") == "long":
        risk_pts += 8
    risk_pts = max(0, min(100, risk_pts))

    if risk_pts < 20:
        level = "very_conservative"
    elif risk_pts < 40:
        level = "conservative"
    elif risk_pts < 60:
        level = "moderate"
    elif risk_pts < 80:
        level = "growth"
    else:
        level = "aggressive"

    profile["risk_pts"] = risk_pts
    profile["risk_tolerance"] = level
    # volatility & drawdown tolerance track the same scale (kept explicit per spec)
    profile["volatility_tolerance"] = level
    profile["drawdown_tolerance"] = level
    return profile


def describe(profile: dict) -> str:
    """One-line human summary."""
    if not profile:
        return "No profile yet."
    return (f"{profile.get('risk_tolerance', '?').replace('_', ' ').title()} risk · "
            f"{profile.get('goal', '?').title()} goal · "
            f"{profile.get('horizon', '?').title()} horizon · "
            f"{profile.get('style', '?').title()} style")


# --- personalisation: reweight the scorecard -------------------------------- #
def weights_for_profile(profile: dict) -> dict:
    import scoring
    w = dict(scoring.CATEGORY_WEIGHTS)
    goal = profile.get("goal")
    risk = profile.get("risk_tolerance")

    if goal == "income":
        w["income"] *= 2.4; w["health"] *= 1.4; w["growth"] *= 0.4
    elif goal == "growth":
        w["growth"] *= 2.0; w["quality"] *= 1.2; w["income"] *= 0.4

    if risk in ("very_conservative", "conservative"):
        w["health"] *= 1.5; w["valuation"] *= 1.2; w["growth"] *= 0.7
    elif risk in ("growth", "aggressive"):
        w["growth"] *= 1.4; w["health"] *= 0.8

    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


# --- suitability: "does this suit me?" -------------------------------------- #
def assess_suitability(profile: dict, f, score, rr) -> dict:
    pros, cons = [], []
    risk = profile.get("risk_tolerance", "moderate")
    goal = profile.get("goal", "balanced")
    horizon = profile.get("horizon", "medium")
    conservative = risk in ("very_conservative", "conservative")
    aggressive = risk in ("growth", "aggressive")

    if f.beta is not None:
        if conservative and f.beta > 1.2:
            cons.append(f"Beta {f.beta:.2f} — swings more than the market, above your comfort.")
        elif aggressive and f.beta > 1.2:
            pros.append(f"Beta {f.beta:.2f} — higher volatility, in line with your appetite.")
        elif f.beta < 0.9 and conservative:
            pros.append(f"Beta {f.beta:.2f} — calmer than the market, fits a conservative profile.")

    dy = f.dividend_yield or 0
    if goal == "income":
        if dy >= 0.03:
            pros.append(f"Dividend yield {dy:.1%} supports your income goal.")
        elif dy < 0.01:
            cons.append("Pays little or no dividend — doesn't serve your income goal.")
    if goal == "growth" and (f.revenue_growth or 0) >= 0.12:
        pros.append(f"Revenue growth {f.revenue_growth:.0%} aligns with a growth goal.")

    if conservative and f.debt_to_equity and f.debt_to_equity > 1.5:
        cons.append(f"Debt/Equity {f.debt_to_equity:.2f} — leveraged, riskier in a downturn.")

    if horizon == "short" and f.beta and f.beta > 1.1:
        cons.append("High volatility is risky for a short time horizon.")
    elif horizon == "long":
        pros.append("Your long horizon lets you ride out short-term swings.")

    if conservative and rr and rr.favorability_pct is not None and rr.favorability_pct < 40:
        cons.append("Thin margin of safety vs downside, which a conservative profile usually wants.")

    hard_block = conservative and (f.beta or 0) > 1.5
    if hard_block or len(cons) > len(pros) + 1:
        verdict = "Poor fit for your profile"
    elif len(pros) > len(cons):
        verdict = "Fits your profile"
    else:
        verdict = "Partial fit"

    return {"verdict": verdict, "pros": pros, "cons": cons}