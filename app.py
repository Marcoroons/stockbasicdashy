"""
app.py - the dashboard you'll actually use.

Run locally:   streamlit run app.py
Deploy:        push to GitHub -> Streamlit Community Cloud (see README)

Degrades gracefully: if Supabase secrets aren't set yet, the watchlist falls
back to in-session memory so you can use the app before finishing DB setup.
"""

from __future__ import annotations

import streamlit as st

import stock_analyzer as sa
import scoring as sc
import peers as pr
import news as nw

# --- optional database (works without it) ---------------------------------- #
try:
    import db
    _HAS_DB = "SUPABASE_URL" in st.secrets
except Exception:
    _HAS_DB = False


st.set_page_config(page_title="Stock Dashboard", page_icon="📈", layout="wide")


# --- caching: don't refetch fundamentals on every rerun --------------------- #
@st.cache_data(ttl=900, show_spinner=False)   # 15 min
def get_fundamentals(ticker: str):
    return sa.fetch_fundamentals(ticker)


@st.cache_data(ttl=900, show_spinner=False)
def get_peer_comparison(ticker: str):
    f = get_fundamentals(ticker)
    plist = pr.peers_for(ticker)
    return (pr.compare_to_peers(f, plist), plist) if plist else (None, [])


@st.cache_data(ttl=1800, show_spinner=False)
def get_news(ticker: str):
    return nw.recent_news(ticker)


# --- watchlist helpers (DB or session fallback) ----------------------------- #
def wl_list():
    if _HAS_DB:
        return [r["ticker"] for r in db.list_watchlist()]
    return st.session_state.setdefault("watchlist", [])


def wl_pin(ticker):
    ticker = ticker.upper()
    if _HAS_DB:
        db.pin(ticker)
    else:
        wl = st.session_state.setdefault("watchlist", [])
        if ticker not in wl:
            wl.append(ticker)


def wl_unpin(ticker):
    if _HAS_DB:
        db.unpin(ticker)
    else:
        st.session_state.get("watchlist", []).remove(ticker)


# --- live price (delayed on free feeds; refreshes on a timer) --------------- #
@st.fragment(run_every="20s")
def live_price(ticker: str):
    try:
        fast = sa.yf.Ticker(ticker).fast_info
        price = fast.get("last_price") or fast.get("lastPrice")
        prev = fast.get("previous_close") or fast.get("previousClose")
        if price and prev:
            delta = price - prev
            st.metric(f"{ticker} (≈15-min delayed)",
                      f"{price:,.2f}", f"{delta:+.2f} ({delta/prev:+.2%})")
        elif price:
            st.metric(f"{ticker} (≈15-min delayed)", f"{price:,.2f}")
    except Exception:
        st.caption("Live price unavailable right now.")


# --- main views ------------------------------------------------------------- #
def show_scorecard(f):
    overall, cats, scored = sc.composite_score(f)
    v = sa.value_stock(f)
    rr = sc.risk_reward(f, v.blended_intrinsic)
    bull, bear = sc.bull_bear(scored)

    c1, c2, c3 = st.columns(3)
    c1.metric("Your score", f"{overall:.0f}/100" if overall else "n/a")
    c2.metric("Favorability",
              f"{rr.favorability_pct:.0f}%" if rr.favorability_pct else "n/a",
              help="Reward vs risk. 50% = even. Reward = upside to target; "
                   "risk = downside to 52-week low.")
    c3.metric("Reward : Risk",
              f"{rr.ratio:.2f} : 1" if rr.ratio else "n/a")

    st.caption(sc.lean_from_score(overall) + "  —  this is your framework, not advice.")

    st.write("**Category scores**")
    st.dataframe(
        {"category": list(cats.keys()),
         "score /100": [round(s, 0) for s in cats.values()],
         "your weight": [f"{sc.CATEGORY_WEIGHTS[c]:.0%}" for c in cats]},
        use_container_width=True, hide_index=True,
    )

    b1, b2 = st.columns(2)
    with b1:
        st.write("**Bull case** (numbers in favour)")
        for label, _ in bull:
            st.write(f"✅ {label}")
        if not bull:
            st.caption("Nothing scored strong.")
    with b2:
        st.write("**Bear case** (numbers against)")
        for label, _ in bear:
            st.write(f"⚠️ {label}")
        if not bear:
            st.caption("Nothing scored weak.")

    st.info(f"Analyst view (third-party data, not our signal): {sc.analyst_view(f)}")


def show_metrics(f):
    st.write("**All metrics** — hover the ❔ for what each means")
    rows = []
    for key, cfg in sc.METRIC_CONFIG.items():
        label, desc = sc.GLOSSARY.get(key, (key, ""))
        val = sc._metric_value(f, key)
        rows.append({"metric": label, "value": "n/a" if val is None else round(val, 3),
                     "what it means": desc})
    st.dataframe(rows, use_container_width=True, hide_index=True)


def show_peers(ticker):
    comp, plist = get_peer_comparison(ticker)
    if not comp:
        st.caption(f"No peer group defined for {ticker}. Add one in peers.py "
                   "(SECTOR_PEERS) to enable sector-relative ranking.")
        return
    st.write(f"**Vs peers:** {', '.join(plist)}  (percentile: 100 = best in group)")
    rows = []
    for key, d in comp.items():
        label = sc.GLOSSARY.get(key, (key,))[0]
        rows.append({
            "metric": label,
            "this stock": "n/a" if d["value"] is None else round(d["value"], 3),
            "peer median": "n/a" if d["peer_median"] is None else round(d["peer_median"], 3),
            "percentile": "n/a" if d["percentile"] is None else f"{d['percentile']:.0f}",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)


def show_news(ticker):
    items = get_news(ticker)
    st.caption(f"Headline tilt (reading aid, NOT a signal): {nw.headline_tilt(items)}")
    for h in items:
        if h["link"]:
            st.markdown(f"- [{h['title']}]({h['link']})  ·  *{h['publisher']}*")
        else:
            st.markdown(f"- {h['title']}  ·  *{h['publisher']}*")
    if not items:
        st.caption("No recent headlines found.")


# --- layout ----------------------------------------------------------------- #
def main():
    st.title("📈 Long-term Stock Dashboard")
    if not _HAS_DB:
        st.warning("Supabase not connected — watchlist is temporary this session. "
                   "See README to wire up the database.", icon="⚠️")

    with st.sidebar:
        st.header("Watchlist")
        for t in wl_list():
            cols = st.columns([3, 1])
            if cols[0].button(t, use_container_width=True, key=f"go_{t}"):
                st.session_state.ticker = t
            if cols[1].button("✕", key=f"rm_{t}"):
                wl_unpin(t)
                st.rerun()
        st.divider()
        new_t = st.text_input("Search a ticker", placeholder="e.g. AAPL").upper().strip()
        cta = st.columns(2)
        if cta[0].button("Analyze", use_container_width=True) and new_t:
            st.session_state.ticker = new_t
        if cta[1].button("📌 Pin", use_container_width=True) and new_t:
            wl_pin(new_t)
            st.session_state.ticker = new_t
            st.rerun()

    ticker = st.session_state.get("ticker")
    if not ticker:
        st.info("Search a ticker in the sidebar to begin.")
        return

    try:
        f = get_fundamentals(ticker)
    except Exception as e:
        st.error(f"Couldn't load {ticker}: {e}")
        return

    live_price(ticker)
    st.subheader(f"{f.name or ticker}  ·  {f.sector or ''} / {f.industry or ''}")
    if f.summary:
        with st.expander("What this company does"):
            st.write(f.summary)

    tabs = st.tabs(["Scorecard", "All metrics", "Vs peers", "News"])
    with tabs[0]:
        show_scorecard(f)
    with tabs[1]:
        show_metrics(f)
    with tabs[2]:
        show_peers(ticker)
    with tabs[3]:
        show_news(ticker)


if __name__ == "__main__":
    main()
