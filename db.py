"""
db.py - Supabase watchlist (pin / unpin / list).

Connection credentials live in Streamlit secrets, NOT in this file and NOT in
the repo. See README for setup. The official supabase client runs server-side
inside Streamlit, so your key is never exposed to the browser.
"""

from __future__ import annotations

import streamlit as st
from supabase import create_client, Client


@st.cache_resource
def get_client() -> Client:
    """One cached client per server session."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def list_watchlist() -> list[dict]:
    res = get_client().table("watchlist").select("*").order("created_at").execute()
    return res.data or []


def pin(ticker: str, note: str | None = None) -> None:
    """Add or update a pinned ticker. upsert => no duplicates."""
    get_client().table("watchlist").upsert(
        {"ticker": ticker.upper(), "note": note, "pinned": True},
        on_conflict="ticker",
    ).execute()


def unpin(ticker: str) -> None:
    get_client().table("watchlist").delete().eq("ticker", ticker.upper()).execute()


def save_snapshot(ticker: str, data: dict) -> None:
    """Cache the last analysis so the dashboard loads instantly next time."""
    get_client().table("snapshots").upsert(
        {"ticker": ticker.upper(), "data": data},
        on_conflict="ticker",
    ).execute()


def load_snapshot(ticker: str) -> dict | None:
    res = get_client().table("snapshots").select("data").eq(
        "ticker", ticker.upper()).execute()
    return res.data[0]["data"] if res.data else None
