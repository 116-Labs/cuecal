"""Eval runner: scores the extractor tiers against fixtures and renders comparison tables."""

from __future__ import annotations

import json
import math
import sqlite3
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from dateutil import parser as dt_parser

from cuecal import db
from cuecal.config import LLMConfig, LocalLLMConfig, Tier0Config
from cuecal.eval.schema import EvalFixture, ExpectedCandidate
from cuecal.extract import escalate, extract, tier1
from cuecal.extract.decision import Tier0Client
from cuecal.models import MeetingCandidate, Message

FIELDS = ("title", "start", "end", "tz", "join_url", "attendees")
BUILT_TIERS = (1, 2, 3)
_PAID_PROVIDERS = ("anthropic", "openai")


class TierNotBuiltError(RuntimeError):
    """Raised when an eval is requested for an extraction tier that does not exist yet."""


class EvalConfigError(ValueError):
    """Raised when an LLM tier eval lacks the provider settings it needs."""


@dataclass
class Tier2Response:
    candidate: MeetingCandidate | None
    valid: bool
    confidence: float
    input_tokens: int = 0
    output_tokens: int = 0


Tier2Provider = Callable[[Message, MeetingCandidate | None], Tier2Response]
RamSampler = Callable[[], int | None]


@dataclass
class FixtureResult:
    fixture_id: str
    predicted_label: str
    label_correct: bool
    escalated: bool
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    escalated_t2: bool | None = None
    ran_llm: bool = False
    field_correct: dict[str, bool] = field(default_factory=dict)
    check: str | None = None
    dropped_invite: bool = False
    wrong_start: bool = False


@dataclass
class EvalReport:
    tier: int
    provider: str | None
    model: str | None
    results: list[FixtureResult]
    peak_ram_bytes: int | None = None
    check_enabled: bool = False

    @property
    def total(self) -> int:
        return len(self.results)

    def field_accuracy(self) -> dict[str, tuple[int, int]]:
        """Per field: (correct, scored)."""
        out: dict[str, tuple[int, int]] = {}
        for name in FIELDS:
            scored = [r.field_correct[name] for r in self.results if name in r.field_correct]
            out[name] = (sum(scored), len(scored))
        return out

    @property
    def label_correct(self) -> int:
        return sum(r.label_correct for r in self.results)

    @property
    def escalated(self) -> int:
        return sum(r.escalated for r in self.results)

    def escalated_t2(self) -> tuple[int, int]:
        """Tier 2 results that would go to Tier 3: (escalated, Tier 2 runs)."""
        ran = [r.escalated_t2 for r in self.results if r.escalated_t2 is not None]
        return sum(ran), len(ran)

    def tier3_ids(self) -> list[str]:
        return [r.fixture_id for r in self.results if r.escalated_t2]

    def check_results(self) -> dict[str, int]:
        """How many candidates got each Tier 2.5 result."""
        counts: dict[str, int] = {}
        for r in self.results:
            if r.check is not None:
                counts[r.check] = counts.get(r.check, 0) + 1
        return counts

    def dropped_invite_ids(self) -> list[str]:
        """`new_invite` fixtures Tier 2.5 dropped: one half of #172's recall bar."""
        return [r.fixture_id for r in self.results if r.dropped_invite]

    def wrong_start_ids(self) -> list[str]:
        """Tier 2.5-confirmed starts that miss the expected start: the other half."""
        return [r.fixture_id for r in self.results if r.wrong_start]

    @property
    def llm_runs(self) -> int:
        return sum(r.ran_llm for r in self.results)

    @property
    def input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.results)

    @property
    def output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.results)

    @property
    def mean_latency_ms(self) -> float:
        return sum(r.latency_ms for r in self.results) / self.total if self.total else 0.0

    def latency_percentile(self, pct: float) -> float:
        """Nearest-rank percentile of per-candidate latency."""
        if not self.results:
            return 0.0
        ordered = sorted(r.latency_ms for r in self.results)
        rank = max(1, math.ceil(pct / 100 * len(ordered)))
        return ordered[rank - 1]


def _same_instant(expected: str, actual: datetime | None) -> bool:
    if actual is None:
        return False
    exp = dt_parser.isoparse(expected)
    if (exp.tzinfo is None) != (actual.tzinfo is None):
        return False
    return exp == actual


def _field_matches(name: str, expected: ExpectedCandidate, actual: MeetingCandidate | None) -> bool:
    if actual is None:
        return False
    if name in ("start", "end"):
        want = getattr(expected, name)
        got = getattr(actual, name)
        if want is None:
            return got is None
        return _same_instant(want, got)
    if name == "attendees":
        return set(expected.attendees) == set(actual.attendees)
    return getattr(expected, name) == getattr(actual, name)


def _tier1(message: Message) -> tuple[str, MeetingCandidate | None, bool]:
    cand = extract(message)
    if cand is None:
        return "not_invite", None, False
    fallback = cand.tier == "regex"
    escalated = fallback or cand.confidence < tier1.HIGH
    return ("mentions_meeting" if fallback else "new_invite"), cand, escalated


def run_tier1(fixture: EvalFixture) -> tuple[str, MeetingCandidate | None, bool]:
    """Return (label, candidate, escalated). Escalated means a higher tier would be needed."""
    return _tier1(fixture.input.to_message(message_id=fixture.id))


def tier2_escalates(response: Tier2Response, min_confidence: float) -> bool:
    """The #8 rule: a Tier 2 result goes to Tier 3 when it fails validation or is unsure."""
    return not response.valid or response.confidence < min_confidence


def _keep_regex_links(cand: MeetingCandidate, partial: MeetingCandidate | None) -> MeetingCandidate:
    if partial is None:
        return cand
    return replace(
        cand,
        join_url=partial.join_url,
        meeting_id=partial.meeting_id,
        passcode=partial.passcode,
    )


def ollama_tokens(body: dict[str, Any]) -> tuple[int, int]:
    """(input, output) tokens from an Ollama generate or chat response body."""
    return int(body.get("prompt_eval_count") or 0), int(body.get("eval_count") or 0)


def _ollama_tagged(name: str) -> str:
    # A registry host may carry a port (`localhost:5000/library/llama3`): only the last segment
    # holds a tag.
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


def ollama_ps_sampler(host: str, model: str | None, timeout: float = 2.0) -> RamSampler:
    """Sample `GET /api/ps` for the loaded model's size in bytes; None when unreachable."""
    wanted = None if model is None else _ollama_tagged(model)

    def sample() -> int | None:
        try:
            with urllib.request.urlopen(f"{host.rstrip('/')}/api/ps", timeout=timeout) as resp:
                loaded = json.load(resp).get("models") or []
            sizes = [
                int(m.get("size") or 0)
                for m in loaded
                if isinstance(m, dict)
                and (
                    wanted is None
                    or wanted
                    in {_ollama_tagged(n) for n in (m.get("name"), m.get("model")) if n}
                )
            ]
        except (OSError, ValueError, TypeError, AttributeError):
            return None
        return max(sizes) if sizes else None

    return sample


def require_built_tier(tier: int) -> None:
    if tier not in BUILT_TIERS:
        raise TierNotBuiltError(f"tier {tier} not built")


def llm_config_for(
    tier: int, base: LLMConfig, *, provider: str | None = None, model: str | None = None
) -> LLMConfig:
    """Enable only the tier under test: tier 2 alone, or tier 3 alone without a Tier 2 hop."""
    if tier == 2:
        if provider and provider != "ollama":
            raise EvalConfigError('tier 2 supports only the "ollama" provider')
        local = base.local or LocalLLMConfig()
        if model:
            local = replace(local, model=model)
        return replace(base, local=local, paid=None)
    if tier == 3:
        if base.paid is None:
            raise EvalConfigError("tier 3 needs [llm.paid] in the config")
        paid = base.paid
        if provider:
            if provider not in _PAID_PROVIDERS:
                raise EvalConfigError(f"tier 3 provider must be one of {list(_PAID_PROVIDERS)}")
            paid = replace(paid, provider=provider)
        if model:
            paid = replace(paid, model=model)
        return replace(base, local=None, paid=paid)
    return replace(base, local=None, paid=None)


def _escalator(
    tier: int,
    llm: LLMConfig,
    secret_names: dict[str, str] | None,
    provider: str | None,
    model: str | None,
    tier0: Tier0Config | None,
) -> escalate.Escalator | None:
    if tier < 2:
        return None
    cfg = llm_config_for(tier, llm, provider=provider, model=model)
    check = None
    # Tier 2 is the only eval tier with a Gemma hop for Tier 2.5 to follow; paid is off there,
    # so whatever would reach Tier 3 is counted, never called (#172).
    if tier == 2 and llm.check.enabled:
        if tier0 is None:
            raise EvalConfigError("[llm.check] enabled = true needs a [tier0] table")
        check = Tier0Client.from_config(tier0)
    # Usage and telemetry stay in memory: an eval never spends from the run's daily cap.
    conn = sqlite3.connect(":memory:")
    db.migrate(conn)
    return escalate.Escalator(
        cfg,
        conn=conn,
        local=escalate.build_local_provider(cfg.local) if cfg.local else None,
        paid=escalate.build_paid_provider(cfg.paid, secret_names or {}) if cfg.paid else None,
        check=check,
    )


def _confirmed(check: escalate.CheckResult | None) -> bool:
    return check is not None and check.result == escalate.CONFIRMED


def _confirmed_start_wrong(fixture: EvalFixture, cand: MeetingCandidate) -> bool:
    expected = fixture.expected.candidate
    return expected is None or not _field_matches("start", expected, cand)


def evaluate(
    fixtures: list[EvalFixture],
    *,
    tier: int,
    provider: str | None = None,
    model: str | None = None,
    llm: LLMConfig | None = None,
    secret_names: dict[str, str] | None = None,
    tier2: Tier2Provider | None = None,
    min_confidence: float | None = None,
    ram_sampler: RamSampler | None = None,
    tier0: Tier0Config | None = None,
) -> EvalReport:
    """Score `tier` on the fixtures; tiers 2-3 run on Tier 1's escalated candidates only.

    `tier2` replaces the configured Tier 2 provider with a stub when `tier` is 2. With
    `[llm.check]` on, tier 2 asks the `tier0` host as Tier 2.5 after each Gemma failure.
    """
    require_built_tier(tier)
    llm = llm or LLMConfig()
    stub = tier2 if tier == 2 else None
    threshold = llm.min_confidence if min_confidence is None else min_confidence
    escalator = None if stub else _escalator(tier, llm, secret_names, provider, model, tier0)
    if escalator is not None:
        active = escalator.local or escalator.paid
        provider = provider or active.name
        model = model or active.model
    if ram_sampler is None and tier == 2 and provider == "ollama":
        ram_sampler = ollama_ps_sampler((llm.local or LocalLLMConfig()).host, model)
    results: list[FixtureResult] = []
    peak_ram: int | None = None
    for fixture in fixtures:
        started = time.perf_counter()
        message = fixture.input.to_message(message_id=fixture.id)
        label, cand, escalated = _tier1(message)
        input_tokens = output_tokens = 0
        escalated_t2: bool | None = None
        ran_llm = False
        check: escalate.CheckResult | None = None
        if stub is not None and escalated:
            response = stub(message, cand)
            ran_llm = True
            input_tokens, output_tokens = response.input_tokens, response.output_tokens
            escalated_t2 = tier2_escalates(response, threshold)
            if response.valid and response.candidate is not None:
                cand = _keep_regex_links(response.candidate, cand)
        elif escalator is not None and cand is not None:
            outcome = escalator.process(message, cand, timezone=fixture.input.recipient_tz)
            cand = outcome.candidate
            check = outcome.check
            if check is not None and outcome.drop_reason is not None:
                label = check.label or label
            elif escalated and (outcome.pending_reason is None or _confirmed(check)):
                label = "new_invite"
            ran_llm = bool(outcome.attempts)
            input_tokens = sum(a.input_tokens for a in outcome.attempts)
            output_tokens = sum(a.output_tokens for a in outcome.attempts)
            if any(a.tier == escalate.LOCAL_TIER for a in outcome.attempts):
                escalated_t2 = outcome.reached_tier3
        latency_ms = (time.perf_counter() - started) * 1000
        if ram_sampler is not None:
            sample = ram_sampler()
            if sample is not None:
                peak_ram = sample if peak_ram is None else max(peak_ram, sample)
        expected = fixture.expected.candidate
        scores = (
            {name: _field_matches(name, expected, cand) for name in FIELDS}
            if expected is not None
            else {}
        )
        results.append(
            FixtureResult(
                fixture_id=fixture.id,
                predicted_label=label,
                label_correct=label == fixture.expected.label,
                escalated=escalated,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                escalated_t2=escalated_t2,
                ran_llm=ran_llm,
                field_correct=scores,
                check=check.result if check else None,
                dropped_invite=(
                    check is not None
                    and check.result in (escalate.DROPPED, escalate.LOG_ONLY)
                    and fixture.expected.label == "new_invite"
                ),
                wrong_start=(
                    _confirmed(check)
                    and cand is not None
                    and _confirmed_start_wrong(fixture, cand)
                ),
            )
        )
    return EvalReport(
        tier=tier,
        provider=provider,
        model=model,
        results=results,
        peak_ram_bytes=peak_ram,
        check_enabled=escalator is not None and escalator.check is not None,
    )


def _pct(correct: int, scored: int) -> str:
    return f"{100 * correct / scored:.1f}%" if scored else "n/a"


def _per_candidate(total: int, count: int) -> str:
    mean = total / count if count else 0.0
    return f"{mean:.1f} per candidate ({total} total)"


def _ids(ids: list[str]) -> str:
    return f" ({', '.join(ids)})" if ids else ""


def _ram(peak: int | None) -> str:
    return "-" if peak is None else f"{peak / 2**20:.0f} MiB"


def _rows(report: EvalReport) -> list[tuple[str, str]]:
    rows = [
        ("tier", str(report.tier)),
        ("provider", report.provider or "-"),
        ("model", report.model or "-"),
        ("fixtures", str(report.total)),
    ]
    rows.append(("label accuracy", _pct(report.label_correct, report.total)))
    for name, (correct, scored) in report.field_accuracy().items():
        rows.append((f"{name} accuracy", f"{_pct(correct, scored)} ({correct}/{scored})"))
    rows.append(("escalated T1->T2", f"{report.escalated}/{report.total}"))
    t3, t2_runs = report.escalated_t2()
    if report.check_enabled:
        rows.append(("escalated T2->T3", f"{t3}/{t2_runs}{_ids(report.tier3_ids())}"))
        results = ", ".join(f"{k} {v}" for k, v in sorted(report.check_results().items()))
        rows.append(("tier 2.5 results", results or "-"))
        for name, ids in (
            ("tier 2.5 dropped invites", report.dropped_invite_ids()),
            ("tier 2.5 wrong starts", report.wrong_start_ids()),
        ):
            rows.append((name, f"{len(ids)}{_ids(ids)}"))
    else:
        rows.append(("escalated T2->T3", f"{t3}/{t2_runs}"))
    rows.append(("mean latency", f"{report.mean_latency_ms:.2f} ms"))
    rows.append(("p50 latency", f"{report.latency_percentile(50):.2f} ms"))
    rows.append(("p95 latency", f"{report.latency_percentile(95):.2f} ms"))
    rows.append(("input tokens", _per_candidate(report.input_tokens, report.llm_runs)))
    rows.append(("output tokens", _per_candidate(report.output_tokens, report.llm_runs)))
    rows.append(("peak RAM", _ram(report.peak_ram_bytes)))
    return rows


def render_table(report: EvalReport) -> str:
    rows = _rows(report)
    width = max(len(k) for k, _ in rows)
    return "\n".join(f"{k.ljust(width)}  {v}" for k, v in rows)


def render_markdown(report: EvalReport) -> str:
    lines = ["| Metric | Value |", "| --- | --- |"]
    lines.extend(f"| {k} | {v} |" for k, v in _rows(report))
    return "\n".join(lines)
