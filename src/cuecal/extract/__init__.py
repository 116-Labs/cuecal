"""Deterministic extractor tiers 0-1 (zero LLM tokens)."""

from __future__ import annotations

from cuecal.extract import tier0, tier1
from cuecal.models import MeetingCandidate, Message


def extract(message: Message) -> MeetingCandidate | None:
    """Run Tier 0 then Tier 1.

    Returns None when the message is dropped at Tier 0. Otherwise returns a candidate; when
    its confidence is below tier1.HIGH it is partial (link and meeting ID filled) and should
    go to Tier 2.
    """
    links = tier0.gate(message)
    if links is None:
        return None
    cand = tier1.extract(message)
    if cand is None:
        cand = MeetingCandidate(
            title="Meeting", source_ref=message.permalink or message.id, tier="regex"
        )
    if cand.join_url is None and links:
        link = links[0]
        cand.join_url, cand.meeting_id, cand.passcode = (
            link.join_url,
            link.meeting_id,
            link.passcode,
        )
    return cand
