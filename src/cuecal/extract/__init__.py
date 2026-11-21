"""Extractor entry point: Tier 0 (regex gate or decision model with fallback) then Tier 1."""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from cuecal import secrets
from cuecal.config import Config, Tier0Config
from cuecal.extract import tier0, tier1, tier2
from cuecal.extract.decision import (
    Route,
    Tier0Client,
    Tier0Decision,
    Tier0Unavailable,
    WorkersAIClient,
    record_workers_ai_usage,
    workers_ai_cap_reason,
)
from cuecal.extract.providers import ProviderError, UnusableAnswer
from cuecal.models import MeetingCandidate, Message

logger = logging.getLogger("cuecal.extract")


def _candidate_from_message(message: Message, links: list[tier0.MeetingLink]) -> MeetingCandidate:
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


def extract(message: Message) -> MeetingCandidate | None:
    """Run Tier 0 then Tier 1.

    Returns None when the message is dropped at Tier 0. Otherwise returns a candidate; when
    its confidence is below tier1.HIGH it is partial (link and meeting ID filled) and should
    go to Tier 2.
    """
    links = tier0.gate(message)
    return None if links is None else _candidate_from_message(message, links)


def _ics_candidate(message: Message) -> MeetingCandidate | None:
    """A parsed calendar invitation outranks a negative text-only Tier 0 decision."""
    for attachment in message.attachments:
        if "BEGIN:VCALENDAR" in attachment:
            cand = tier1.parse_ics(attachment, message.permalink or message.id)
            if cand:
                return cand
    return None


@dataclass(frozen=True)
class Tier0Outcome:
    candidate: MeetingCandidate | None = None
    decision: Tier0Decision | None = None
    used_regex_fallback: bool = False
    provider: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class Tier0Runner:
    """Run the configured Tier 0 decision client with Workers AI and regex degraded fallback."""

    def __init__(
        self,
        cfg: Tier0Config,
        *,
        conn: sqlite3.Connection,
        local: Tier0Client | None = None,
        workers_ai: WorkersAIClient | None = None,
        timezone: str = "",
        now: Callable[[], datetime] | None = None,
        dry_run: bool = False,
    ) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        self.conn = conn
        self.local = local or Tier0Client.from_config(cfg)
        self.workers_ai = workers_ai
        self.timezone = timezone
        self.now = now or (lambda: datetime.now(UTC))
        self._degraded_warned = False
        self._usage_write_failed = False

    @classmethod
    def from_config(
        cls, cfg: Config, *, conn: sqlite3.Connection, dry_run: bool = False
    ) -> Tier0Runner | None:
        if cfg.tier0 is None:
            return None
        wa = cfg.tier0.workers_ai
        cloud = None
        if wa is not None and wa.enabled and not dry_run:
            entry = cfg.secrets[wa.api_key_secret]
            cloud = WorkersAIClient.from_config(cfg.tier0, wa, lambda: secrets.get_secret(entry))
        return cls(
            cfg.tier0, conn=conn, workers_ai=cloud, timezone=cfg.llm.timezone, dry_run=dry_run
        )

    def extract(self, message: Message) -> Tier0Outcome:
        try:
            dec = self.local.classify(message.text)
            return self._route_decision(
                message, Tier0Outcome(decision=dec, provider="llama-server")
            )
        except Tier0Unavailable:
            cloud = self._try_workers_ai(message)
            if cloud is not None:
                return cloud
            if not self._degraded_warned:
                self._degraded_warned = True
                logger.warning(
                    "tier 0 host %s unavailable; running degraded on the regex gate",
                    self.local.host,
                )
            return Tier0Outcome(candidate=extract(message), used_regex_fallback=True)

    def _try_workers_ai(self, message: Message) -> Tier0Outcome | None:
        wa_cfg = self.cfg.workers_ai
        if self.dry_run or self.workers_ai is None or wa_cfg is None or not wa_cfg.enabled:
            return None
        zone = ZoneInfo(tier2.recipient_timezone(self.timezone) or "UTC")
        day = self.now().astimezone(zone).date().isoformat()
        capped = (
            "Workers AI usage could not be recorded; treated as capped"
            if self._usage_write_failed
            else workers_ai_cap_reason(self.conn, wa_cfg.daily_token_cap, day)
        )
        if capped:
            logger.info("tier 0 Workers AI skipped: %s", capped)
            return None
        try:
            res = self.workers_ai.classify(message.text)
        except UnusableAnswer as exc:
            u = exc.usage
            self._record_usage(day, u.input_tokens, u.output_tokens, u.usage_known)
            logger.info("tier 0 Workers AI unusable response: %s", exc)
            return None
        except ProviderError as exc:
            logger.info("tier 0 Workers AI failed: %s", exc)
            return None
        self._record_usage(day, res.input_tokens, res.output_tokens, res.usage_known)
        if not res.usage_known or self._usage_write_failed:
            logger.info("tier 0 Workers AI returned unknown or unrecorded token usage")
            return None
        base = Tier0Outcome(
            decision=res.decision,
            provider="workers-ai",
            model=self.workers_ai.model,
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
        )
        return self._route_decision(message, base)

    def _record_usage(self, day: str, in_tok: int, out_tok: int, known: bool) -> None:
        try:
            record_workers_ai_usage(self.conn, day, in_tok, out_tok, known=known)
        except sqlite3.Error as exc:
            self._usage_write_failed = True
            logger.error("tier 0 Workers AI usage could not be recorded (%s); capped", exc)

    def _route_decision(self, message: Message, base: Tier0Outcome) -> Tier0Outcome:
        assert base.decision is not None
        dec = base.decision
        if dec.route in (Route.TIER1_2, Route.PENDING):
            cand = _candidate_from_message(message, tier0.find_links(message.text))
            if dec.route is Route.PENDING:
                cand = dataclasses.replace(cand, confidence=dec.probability)
            return dataclasses.replace(base, candidate=cand)
        if dec.route in (Route.DROP, Route.NEAR_MISS):
            ics = _ics_candidate(message)
            if ics is not None:
                return dataclasses.replace(base, candidate=ics)
        logger.info(
            "tier 0 %s %s:%s (%s %.2f)",
            dec.route.value,
            message.source,
            message.id,
            dec.label,
            dec.probability,
        )
        return base
