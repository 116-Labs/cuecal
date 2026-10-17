"""Eval runner: scores the extractor tiers against fixtures and renders comparison tables."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from dateutil import parser as dt_parser

from cuecal.eval.schema import EvalFixture, ExpectedCandidate
from cuecal.extract import extract, tier1
from cuecal.models import MeetingCandidate

FIELDS = ("title", "start", "tz", "join_url")
BUILT_TIERS = (1,)


class TierNotBuiltError(RuntimeError):
    """Raised when an eval is requested for an extraction tier that does not exist yet."""


@dataclass
class FixtureResult:
    fixture_id: str
    predicted_label: str
    label_correct: bool
    escalated: bool
    latency_ms: float
    tokens: int = 0
    field_correct: dict[str, bool] = field(default_factory=dict)


@dataclass
class EvalReport:
    tier: int
    provider: str | None
    model: str | None
    results: list[FixtureResult]

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

    @property
    def tokens(self) -> int:
        return sum(r.tokens for r in self.results)

    @property
    def mean_latency_ms(self) -> float:
        return sum(r.latency_ms for r in self.results) / self.total if self.total else 0.0


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
    if name == "start":
        if expected.start is None:
            return actual.start is None
        return _same_instant(expected.start, actual.start)
    return getattr(expected, name) == getattr(actual, name)


def run_tier1(fixture: EvalFixture) -> tuple[str, MeetingCandidate | None, bool]:
    """Return (label, candidate, escalated). Escalated means a higher tier would be needed."""
    message = fixture.input.to_message(message_id=fixture.id)
    cand = extract(message)
    if cand is None:
        return "not_invite", None, False
    fallback = cand.tier == "regex"
    escalated = fallback or cand.confidence < tier1.HIGH
    return ("mentions_meeting" if fallback else "new_invite"), cand, escalated


def require_built_tier(tier: int) -> None:
    if tier not in BUILT_TIERS:
        raise TierNotBuiltError(f"tier {tier} not built (#8)")


def evaluate(
    fixtures: list[EvalFixture],
    *,
    tier: int,
    provider: str | None = None,
    model: str | None = None,
) -> EvalReport:
    require_built_tier(tier)
    results: list[FixtureResult] = []
    for fixture in fixtures:
        started = time.perf_counter()
        label, cand, escalated = run_tier1(fixture)
        latency_ms = (time.perf_counter() - started) * 1000
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
                field_correct=scores,
            )
        )
    return EvalReport(tier=tier, provider=provider, model=model, results=results)


def _pct(correct: int, scored: int) -> str:
    return f"{100 * correct / scored:.1f}%" if scored else "n/a"


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
    rows.append(("escalated T2->T3", "0/0"))
    rows.append(("mean latency", f"{report.mean_latency_ms:.2f} ms"))
    rows.append(("tokens", str(report.tokens)))
    return rows


def render_table(report: EvalReport) -> str:
    rows = _rows(report)
    width = max(len(k) for k, _ in rows)
    return "\n".join(f"{k.ljust(width)}  {v}" for k, v in rows)


def render_markdown(report: EvalReport) -> str:
    lines = ["| Metric | Value |", "| --- | --- |"]
    lines.extend(f"| {k} | {v} |" for k, v in _rows(report))
    return "\n".join(lines)
