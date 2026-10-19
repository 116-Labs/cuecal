"""Escalate Tier 0/1 partials to Tier 2, then at most one hop to Tier 3; telemetry per candidate.

A tier runs only when its provider is configured. Any failure keeps the partial and names why,
so the caller routes it to pending; nothing here raises into the run.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from cuecal import db, notify, secrets
from cuecal.config import Config, LLMConfig, LocalLLMConfig, PaidLLMConfig
from cuecal.extract import tier1, tier2, tier3
from cuecal.extract.providers import AnthropicProvider, OllamaProvider, OpenAIProvider, Provider
from cuecal.models import MeetingCandidate, Message

logger = logging.getLogger("cuecal.extract")

LOCAL_TIER = "local"
PAID_TIER = "paid"
UNKNOWN_TIMEZONE = "recipient timezone unknown; set [llm].timezone"
LOCAL_UNREACHABLE = "tier 2 skipped: local model unreachable earlier this run"


def needs_escalation(cand: MeetingCandidate) -> bool:
    """A regex-fallback partial or anything below Tier 1 HIGH, as `cuecal eval` counts it."""
    return cand.tier == "regex" or cand.confidence < tier1.HIGH


@dataclass
class Outcome:
    candidate: MeetingCandidate
    pending_reason: str | None = None
    attempts: list[tier2.Attempt] = field(default_factory=list)


def paid_key_problem(cfg: Config) -> str | None:
    """Why the Tier 3 API key cannot be read from the keyring, or None when it can."""
    paid = cfg.llm.paid
    if paid is None or not paid.api_key_secret:
        return None
    entry = cfg.secrets[paid.api_key_secret]
    try:
        key = secrets.get_secret(entry)
    except Exception as exc:  # noqa: BLE001 - any keyring backend failure is reported
        return f"keyring read for entry {entry!r} failed: {exc}"
    if not key:
        return f"keyring entry {entry!r} (service 'cuecal') is missing"
    return None


def build_local_provider(local: LocalLLMConfig) -> Provider:
    return OllamaProvider(
        host=local.host,
        model=local.model,
        keep_alive=local.keep_alive,
        timeout=local.timeout_seconds,
    )


def build_paid_provider(paid: PaidLLMConfig, secret_names: dict[str, str]) -> Provider:
    getter = None
    if paid.api_key_secret:
        entry = secret_names[paid.api_key_secret]

        def getter() -> str | None:
            return secrets.get_secret(entry)

    if paid.provider == "anthropic":
        return AnthropicProvider(model=paid.model, api_key=getter, base_url=paid.base_url)
    return OpenAIProvider(model=paid.model, api_key=getter, base_url=paid.base_url)


class Escalator:
    def __init__(
        self,
        llm: LLMConfig,
        *,
        conn: sqlite3.Connection,
        notifiers: Sequence[notify.Notifier] = (),
        local: Provider | None = None,
        paid: Provider | None = None,
        now: Callable[[], datetime] | None = None,
        record: bool = True,
    ) -> None:
        self.llm = llm
        self.conn = conn
        self.notifiers = list(notifiers)
        self.local = local
        self.paid = paid
        self.now = now or (lambda: datetime.now(UTC))
        self.record = record
        self._cap_notified_day: str | None = None
        self._usage_write_failed = False
        self._timezone_warned = False
        self._local_unreachable = False

    @classmethod
    def from_config(
        cls,
        cfg: Config,
        *,
        conn: sqlite3.Connection,
        notifiers: Sequence[notify.Notifier] = (),
        record: bool = True,
    ) -> Escalator:
        """Build the configured tiers; a missing Tier 3 key is reported here, before extraction."""
        local = build_local_provider(cfg.llm.local) if cfg.llm.local else None
        paid = None
        if cfg.llm.paid is not None:
            problem = paid_key_problem(cfg)
            if problem:
                logger.error("llm.paid: %s; tier 3 is off for this run", problem)
            else:
                paid = build_paid_provider(cfg.llm.paid, cfg.secrets)
        return cls(cfg.llm, conn=conn, notifiers=notifiers, local=local, paid=paid, record=record)

    def process(
        self,
        message: Message,
        cand: MeetingCandidate,
        *,
        base_latency_ms: float = 0.0,
        timezone: str | None = None,
    ) -> Outcome:
        """Escalate when needed; `timezone` overrides [llm].timezone, as eval fixtures do."""
        outcome = Outcome(cand)
        if needs_escalation(cand):
            try:
                outcome = self._escalate(message, cand, timezone)
            except Exception as exc:  # noqa: BLE001 - one candidate must never stop the run
                logger.error("escalation failed for %r: %s", cand.title, exc, exc_info=exc)
                outcome = Outcome(cand, pending_reason=f"escalation error: {exc}")
        self._telemetry(message, outcome, base_latency_ms)
        return outcome

    def _escalate(
        self, message: Message, cand: MeetingCandidate, override_tz: str | None
    ) -> Outcome:
        if self.local is None and self.llm.paid is None:
            return Outcome(cand)
        resolved = tier2.recipient_timezone(self.llm.timezone, override_tz)
        if resolved is None:
            self._warn_unknown_timezone()
        timezone = resolved or "UTC"
        outcome = Outcome(cand)
        notes: list[str] = []
        if self.local is not None and self._local_unreachable:
            notes.append(LOCAL_UNREACHABLE)
        elif self.local is not None:
            attempt = self._attempt(self.local, message, cand, LOCAL_TIER, timezone)
            outcome.attempts.append(attempt)
            if attempt.passed:
                outcome.candidate = tier2.merge(cand, attempt.gate.fields, LOCAL_TIER)
                outcome.pending_reason = None if resolved else UNKNOWN_TIMEZONE
                return outcome
            notes.append(f"tier 2 failed: {attempt.gate.reason}")
            logger.info("tier 2 failed for %r: %s", cand.title, attempt.gate.reason)
            # Each retry could wait the full timeout under the run lock and starve the next poll.
            if attempt.unreachable:
                self._local_unreachable = True
                logger.warning("tier 2 unreachable; skipped for the rest of this run")
        if self.llm.paid is not None:
            paid_attempt = self._paid(message, cand, timezone, notes)
            if paid_attempt is not None:
                outcome.attempts.append(paid_attempt)
                if paid_attempt.passed:
                    outcome.candidate = tier2.merge(cand, paid_attempt.gate.fields, PAID_TIER)
                    outcome.pending_reason = None if resolved else UNKNOWN_TIMEZONE
                    return outcome
                notes.append(f"tier 3 failed: {paid_attempt.gate.reason}")
                logger.info("tier 3 failed for %r: %s", cand.title, paid_attempt.gate.reason)
        outcome.pending_reason = "; ".join(notes)
        return outcome

    def _paid(
        self, message: Message, cand: MeetingCandidate, timezone: str, notes: list[str]
    ) -> tier2.Attempt | None:
        if self.paid is None:
            notes.append("tier 3 off: API key missing from the keyring")
            return None
        day = self.now().astimezone(ZoneInfo(timezone)).date().isoformat()
        capped = (
            "tier 3 usage could not be recorded; treated as capped"
            if self._usage_write_failed
            else tier3.cap_reason(self.conn, self.llm.paid, day)
        )
        if capped:
            self._report_cap(capped, day, cand)
            notes.append(capped)
            return None
        # min_confidence gates Tier 2 -> 3 only; thresholds.auto_create judges Tier 3 results.
        attempt = self._attempt(self.paid, message, cand, PAID_TIER, timezone, min_confidence=0.0)
        if not attempt.usage_known:
            logger.error("tier 3 returned no usable token counts; tier 3 is capped for %s", day)
        try:
            tier3.record_usage(
                self.conn,
                self.llm.paid,
                day,
                attempt.input_tokens,
                attempt.output_tokens,
                known=attempt.usage_known,
            )
        except sqlite3.Error as exc:
            self._usage_write_failed = True
            logger.error("tier 3 usage could not be recorded (%s); tier 3 is capped", exc)
        return attempt

    def _attempt(
        self,
        provider: Provider,
        message: Message,
        cand: MeetingCandidate,
        tier: str,
        timezone: str,
        *,
        min_confidence: float | None = None,
    ) -> tier2.Attempt:
        return tier2.attempt(
            provider,
            message,
            cand,
            tier=tier,
            timezone=timezone,
            window_hours=self.llm.start_past_window_hours,
            min_confidence=self.llm.min_confidence if min_confidence is None else min_confidence,
        )

    def _warn_unknown_timezone(self) -> None:
        if self._timezone_warned:
            return
        self._timezone_warned = True
        logger.warning(
            "no IANA zone in [llm].timezone, TZ or /etc/localtime; LLM results go to pending"
        )

    def _report_cap(self, reason: str, day: str, cand: MeetingCandidate) -> None:
        logger.warning("%s; %r goes to pending", reason, cand.title)
        if self._cap_notified_day == day:
            return
        self._cap_notified_day = day
        try:
            first_today = db.claim_cap_notice(self.conn, day)
        except sqlite3.Error:
            first_today = True
        if not first_today:
            return
        notify.notify_alert(
            self.notifiers,
            "CueCal: paid LLM tier skipped",
            f"{reason}. Candidates that need Tier 3 go to `cuecal pending` until tomorrow.",
        )

    def _telemetry(self, message: Message, outcome: Outcome, base_latency_ms: float) -> None:
        last = outcome.attempts[-1] if outcome.attempts else None
        record = {
            "source": getattr(message, "source", "") or "",
            "message_id": getattr(message, "id", "") or "",
            "tier": outcome.candidate.tier,
            "provider": last.provider if last else None,
            "model": last.model if last else None,
            "input_tokens": sum(a.input_tokens for a in outcome.attempts),
            "output_tokens": sum(a.output_tokens for a in outcome.attempts),
            "latency_ms": round(base_latency_ms + sum(a.latency_ms for a in outcome.attempts), 3),
            "outcome": outcome.pending_reason or "ok",
        }
        logger.info("extraction telemetry", extra=record)
        if not self.record:
            return
        try:
            db.record_extraction(self.conn, **record)
        except sqlite3.Error as exc:
            logger.warning("extraction telemetry not stored: %s", exc)
