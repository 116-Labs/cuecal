"""Tier 3: paid-model escalation under a daily token and USD cap kept in the state DB."""

from __future__ import annotations

import sqlite3

from cuecal import db
from cuecal.config import PaidLLMConfig

UNKNOWN_USAGE = "tier 3 returned no usable token counts today; treated as capped"


def cost_usd(paid: PaidLLMConfig, input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * paid.input_usd_per_mtok + output_tokens * paid.output_usd_per_mtok
    ) / 1_000_000


def cap_reason(conn: sqlite3.Connection, paid: PaidLLMConfig, day: str) -> str | None:
    """Why Tier 3 must be skipped today, or None. Unreadable or unknown usage counts as capped."""
    try:
        tokens, usd = db.get_llm_usage(conn, day)
        unknown = db.llm_usage_unknown(conn, day)
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return f"tier 3 usage unreadable ({exc}); treated as capped"
    if unknown:
        return UNKNOWN_USAGE
    if tokens >= paid.daily_token_cap:
        return f"tier 3 daily token cap reached ({tokens}/{paid.daily_token_cap})"
    if usd >= paid.daily_usd_cap:
        return f"tier 3 daily USD cap reached (${usd:.4f}/${paid.daily_usd_cap:.2f})"
    return None


def record_usage(
    conn: sqlite3.Connection,
    paid: PaidLLMConfig,
    day: str,
    input_tokens: int,
    output_tokens: int,
    *,
    known: bool = True,
) -> None:
    """Add a call's cost to the day; unknown usage caps the day instead of counting as zero."""
    if not known:
        db.mark_llm_usage_unknown(conn, day)
        return
    db.add_llm_usage(
        conn,
        day,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usd=cost_usd(paid, input_tokens, output_tokens),
    )
