"""Escalate Tier 0/1 partials to Tier 2, then at most one hop to Tier 3; telemetry per candidate.

A tier runs only when its provider is configured. Any failure keeps the partial and names why,
so the caller routes it to pending; nothing here raises into the run.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from cuecal import db, notify, secrets
from cuecal.config import Config, LLMConfig, LocalLLMConfig, PaidLLMConfig
from cuecal.extract import decision, tier1, tier2, tier3
from cuecal.extract.decision import Tier0Busy, Tier0Client, Tier0Unavailable
from cuecal.extract.providers import AnthropicProvider, OllamaProvider, OpenAIProvider, Provider
from cuecal.models import MeetingCandidate, Message

logger = logging.getLogger("cuecal.extract")

LOCAL_TIER = "local"
PAID_TIER = "paid"
UNKNOWN_TIMEZONE = "recipient timezone unknown; set [llm].timezone"
LOCAL_UNREACHABLE = "tier 2 skipped: local model unreachable earlier this run"
CHECK_UNAVAILABLE_EARLIER = "tier 2.5 unavailable: decision model failed earlier this run"
TIER3_UNCONFIGURED = "tier 3 off: no [llm.paid] table"
NEAR_MISS_LABELS = ("not_invite", "mentions_meeting")
LOG_ONLY_LABELS = ("reschedule", "cancel")
# The duration Tier 2's prompt assumes when a message states no end.
CONFIRMED_DURATION = timedelta(minutes=30)
# Tier 2.5 results, written as the telemetry outcome (#172).
CONFIRMED = "confirmed"
DROPPED = "dropped"
LOG_ONLY = "log_only"
INCONCLUSIVE = "inconclusive"
BUSY = "busy"
UNAVAILABLE = "unavailable"


def needs_escalation(cand: MeetingCandidate) -> bool:
    """A regex-fallback partial or anything below Tier 1 HIGH, as `cuecal eval` counts it."""
    return cand.tier == "regex" or cand.confidence < tier1.HIGH


def start_options(
    draft: tier2.LLMFields, partial: MeetingCandidate, timezone: str
) -> list[tuple[str, datetime]]:
    """The distinct starts in Gemma's answer and the Tier 0/1 partial, labelled for the model."""
    found: list[tuple[datetime, str]] = []
    if draft.start is not None:
        found.append((draft.start, draft.tz))
    if partial.start is not None:
        zone = tier2.recipient_timezone(timezone, partial.tz) or timezone
        start = partial.start
        if start.tzinfo is None:
            start = start.replace(tzinfo=ZoneInfo(zone))
        found.append((start, zone))
    options: list[tuple[str, datetime]] = []
    for start, zone in found:
        if all(start != seen for _, seen in options):
            options.append((decision.format_start(start, zone), start))
    return options


def _on_to_tier3(note: str, cand: MeetingCandidate) -> str:
    logger.info("%s; %r goes on to tier 3", note, cand.title)
    return note


def confirmed_candidate(
    partial: MeetingCandidate, gate: tier2.GateResult, start: datetime
) -> MeetingCandidate:
    """Gemma's fields with the confirmed start; an end Gemma got wrong becomes start + 30 min."""
    draft = gate.draft
    start = start.astimezone(ZoneInfo(draft.tz))
    end = draft.end
    if gate.rule == tier2.END_RULE or end <= start:
        end = start + CONFIRMED_DURATION
    return tier2.merge(partial, dataclasses.replace(draft, start=start, end=end), LOCAL_TIER)


@dataclass(frozen=True)
class CheckResult:
    """What Tier 2.5 decided for one candidate; ``label`` is its invite answer, if it got one."""

    result: str
    latency_ms: float
    label: str | None = None


@dataclass
class Outcome:
    candidate: MeetingCandidate
    pending_reason: str | None = None
    attempts: list[tier2.Attempt] = field(default_factory=list)
    # Set when Tier 2.5 decided the message is no new invite: no event and no pending item.
    drop_reason: str | None = None
    check: CheckResult | None = None
    # True once the candidate got as far as Tier 3, whether or not Tier 3 could be called.
    reached_tier3: bool = False


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
        check: Tier0Client | None = None,
    ) -> None:
        self.llm = llm
        self.conn = conn
        self.notifiers = list(notifiers)
        self.local = local
        self.paid = paid
        self.check = check
        self.now = now or (lambda: datetime.now(UTC))
        self.record = record
        self._cap_notified_day: str | None = None
        self._usage_write_failed = False
        self._timezone_warned = False
        self._local_unreachable = False
        self._check_unavailable = False

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
        check = None
        if cfg.llm.check.enabled and cfg.tier0 is not None:
            check = Tier0Client.from_config(cfg.tier0)
        return cls(
            cfg.llm,
            conn=conn,
            notifiers=notifiers,
            local=local,
            paid=paid,
            record=record,
            check=check,
        )

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
        gate: tier2.GateResult | None = None
        if self.local is not None and self._local_unreachable:
            notes.append(LOCAL_UNREACHABLE)
        elif self.local is not None:
            attempt = self._attempt(self.local, message, cand, LOCAL_TIER, timezone)
            gate = attempt.gate
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
        if self.local is not None and self.check is not None:
            note = self._tier_2_5(self.check, message, outcome, gate, timezone)
            if note is None:
                return outcome
            notes.append(note)
        outcome.reached_tier3 = True
        if self.llm.paid is None:
            notes.append(TIER3_UNCONFIGURED)
        else:
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

    def _tier_2_5(
        self,
        check: Tier0Client,
        message: Message,
        outcome: Outcome,
        gate: tier2.GateResult | None,
        timezone: str,
    ) -> str | None:
        """Tier 2.5 (#82): None once it drops or pends ``outcome``, else the note for Tier 3."""
        started = time.perf_counter()
        result, label, note = self._ask_check(check, message, outcome, gate, timezone)
        outcome.check = CheckResult(result, (time.perf_counter() - started) * 1000, label)
        return note

    def _ask_check(
        self,
        check: Tier0Client,
        message: Message,
        outcome: Outcome,
        gate: tier2.GateResult | None,
        timezone: str,
    ) -> tuple[str, str | None, str | None]:
        """(Tier 2.5 result, invite label, note for Tier 3 or None)."""
        if self._check_unavailable:
            return UNAVAILABLE, None, CHECK_UNAVAILABLE_EARLIER
        cand = outcome.candidate
        try:
            answer = check.classify(message.text, lock_timeout=check.timeout)
        except (Tier0Busy, Tier0Unavailable) as exc:
            result, note = self._check_failed("tier 2.5", exc)
            return result, None, note
        invite = answer.label
        verdict = f"tier 2.5: {invite} at {answer.probability:.2f}"
        if answer.probability < self.llm.check.invite_threshold:
            return INCONCLUSIVE, invite, _on_to_tier3(f"{verdict}, inconclusive", cand)
        if invite in NEAR_MISS_LABELS + LOG_ONLY_LABELS:
            if invite in NEAR_MISS_LABELS and self.record:
                decision.record_near_miss(self.conn, message, answer, reason=verdict)
            logger.info("%s; %r dropped before tier 3", verdict, cand.title)
            outcome.drop_reason = verdict
            return (DROPPED if invite in NEAR_MISS_LABELS else LOG_ONLY), invite, None
        if gate is None or gate.draft is None:
            note = f"{verdict}; this tier 2 failure gets no start check"
            return INCONCLUSIVE, invite, _on_to_tier3(note, cand)
        starts = start_options(gate.draft, cand, timezone)
        if not starts:
            return INCONCLUSIVE, invite, _on_to_tier3(f"{verdict}; no start to check", cand)
        state = f"Received at: {message.ts.isoformat()}\n{message.text}"
        try:
            labels = [label for label, _ in starts]
            reply = check.confirm_start(state, labels, lock_timeout=check.timeout)
        except (Tier0Busy, Tier0Unavailable) as exc:
            result, note = self._check_failed("start check", exc)
            return result, invite, f"{verdict}; {note}"
        named = [s for s in starts if reply.label in (decision.YES, s[0])]
        if not named or reply.probability < self.llm.check.start_threshold:
            note = f"tier 2.5: start {reply.label!r} at {reply.probability:.2f}, not confirmed"
            return INCONCLUSIVE, invite, _on_to_tier3(note, cand)
        [(label, start)] = named
        outcome.candidate = confirmed_candidate(cand, gate, start)
        outcome.pending_reason = f"tier 2.5: start {label} confirmed at {reply.probability:.2f}"
        logger.info("%s; %r goes to pending without tier 3", outcome.pending_reason, cand.title)
        return CONFIRMED, invite, None

    def _check_failed(self, step: str, exc: Exception) -> tuple[str, str]:
        """(result, note) for a busy or failed host; a failure skips Tier 2.5 for the run."""
        if isinstance(exc, Tier0Busy):
            logger.info("%s busy: %s", step, exc)
            return BUSY, f"{step} busy: {exc}"
        self._check_unavailable = True
        logger.warning("%s unavailable; tier 2.5 skipped for the rest of this run: %s", step, exc)
        return UNAVAILABLE, f"{step} unavailable: {exc}"

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
        latency_ms = base_latency_ms + sum(a.latency_ms for a in outcome.attempts)
        result = outcome.pending_reason or outcome.drop_reason or "ok"
        if outcome.check is not None:
            latency_ms += outcome.check.latency_ms
            result = outcome.check.result
        record = {
            "source": getattr(message, "source", "") or "",
            "message_id": getattr(message, "id", "") or "",
            "tier": outcome.candidate.tier,
            "provider": last.provider if last else None,
            "model": last.model if last else None,
            "input_tokens": sum(a.input_tokens for a in outcome.attempts),
            "output_tokens": sum(a.output_tokens for a in outcome.attempts),
            "latency_ms": round(latency_ms, 3),
            "outcome": result,
        }
        logger.info("extraction telemetry", extra=record)
        if not self.record:
            return
        try:
            db.record_extraction(self.conn, **record)
        except sqlite3.Error as exc:
            logger.warning("extraction telemetry not stored: %s", exc)
