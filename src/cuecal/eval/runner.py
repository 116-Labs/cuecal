"""Eval runner: scores the extractor tiers against fixtures and renders comparison tables."""

from __future__ import annotations

import json
import math
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from dateutil import parser as dt_parser

from cuecal.eval.schema import EvalFixture, ExpectedCandidate
from cuecal.extract import extract, tier1
from cuecal.models import MeetingCandidate, Message

FIELDS = ("title", "start", "end", "tz", "join_url", "attendees")
BUILT_TIERS = (1,)
# Provisional Tier 2 -> Tier 3 gate until `[llm] min_confidence` lands with #8.
DEFAULT_MIN_CONFIDENCE = 0.7
DEFAULT_OLLAMA_HOST = "http://localhost:11434"


class TierNotBuiltError(RuntimeError):
    """Raised when an eval is requested for an extraction tier that does not exist yet."""


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
    field_correct: dict[str, bool] = field(default_factory=dict)


@dataclass
class EvalReport:
    tier: int
    provider: str | None
    model: str | None
    results: list[FixtureResult]
    peak_ram_bytes: int | None = None

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


def run_tier1(fixture: EvalFixture) -> tuple[str, MeetingCandidate | None, bool]:
    """Return (label, candidate, escalated). Escalated means a higher tier would be needed."""
    message = fixture.input.to_message(message_id=fixture.id)
    cand = extract(message)
    if cand is None:
        return "not_invite", None, False
    fallback = cand.tier == "regex"
    escalated = fallback or cand.confidence < tier1.HIGH
    return ("mentions_meeting" if fallback else "new_invite"), cand, escalated


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
        raise TierNotBuiltError(f"tier {tier} not built (#8)")


def evaluate(
    fixtures: list[EvalFixture],
    *,
    tier: int,
    provider: str | None = None,
    model: str | None = None,
    tier2: Tier2Provider | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ram_sampler: RamSampler | None = None,
) -> EvalReport:
    runs_tier2 = tier == 2 and tier2 is not None
    if not runs_tier2:
        require_built_tier(tier)
    if ram_sampler is None and runs_tier2 and provider == "ollama":
        ram_sampler = ollama_ps_sampler(DEFAULT_OLLAMA_HOST, model)
    results: list[FixtureResult] = []
    peak_ram: int | None = None
    for fixture in fixtures:
        started = time.perf_counter()
        label, cand, escalated = run_tier1(fixture)
        input_tokens = output_tokens = 0
        escalated_t2: bool | None = None
        if runs_tier2 and escalated:
            response = tier2(fixture.input.to_message(message_id=fixture.id), cand)
            input_tokens, output_tokens = response.input_tokens, response.output_tokens
            escalated_t2 = tier2_escalates(response, min_confidence)
            if response.valid and response.candidate is not None:
                cand = _keep_regex_links(response.candidate, cand)
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
                field_correct=scores,
            )
        )
    return EvalReport(
        tier=tier, provider=provider, model=model, results=results, peak_ram_bytes=peak_ram
    )


def _pct(correct: int, scored: int) -> str:
    return f"{100 * correct / scored:.1f}%" if scored else "n/a"


def _per_candidate(total: int, count: int) -> str:
    mean = total / count if count else 0.0
    return f"{mean:.1f} per candidate ({total} total)"


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
    rows.append(("escalated T2->T3", f"{t3}/{t2_runs}"))
    rows.append(("mean latency", f"{report.mean_latency_ms:.2f} ms"))
    rows.append(("p50 latency", f"{report.latency_percentile(50):.2f} ms"))
    rows.append(("p95 latency", f"{report.latency_percentile(95):.2f} ms"))
    rows.append(("input tokens", _per_candidate(report.input_tokens, t2_runs)))
    rows.append(("output tokens", _per_candidate(report.output_tokens, t2_runs)))
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
