from __future__ import annotations

import io
import json
import shutil
import urllib.error
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cuecal import cli
from cuecal.eval import load_fixtures, runner
from cuecal.models import MeetingCandidate, Message

FIXTURES = Path(__file__).parent / "fixtures" / "eval"
SUBSET = (
    FIXTURES / "invites" / "core" / "core-001-zoom-eastern.json",
    FIXTURES / "negatives" / "invoice_email.json",
)


@pytest.fixture
def subset_dir(tmp_path: Path) -> Path:
    for src in SUBSET:
        shutil.copy(src, tmp_path / src.name)
    return tmp_path


def test_tier1_scores_every_field_on_a_template_invite(subset_dir: Path):
    report = runner.evaluate(load_fixtures(subset_dir), tier=1)
    assert report.total == 2
    assert report.label_correct == 2
    assert report.field_accuracy() == {
        "title": (1, 1),
        "start": (1, 1),
        "end": (1, 1),
        "tz": (1, 1),
        "join_url": (1, 1),
        "attendees": (1, 1),
    }
    assert report.escalated == 0
    assert report.escalated_t2() == (0, 0)
    assert (report.input_tokens, report.output_tokens) == (0, 0)
    assert report.peak_ram_bytes is None


def _ics_fixture(tmp_path: Path):
    shutil.copy(FIXTURES / "invites" / "core" / "core-007-gcal-ics-tzid-meet.json", tmp_path)
    return load_fixtures(tmp_path)[0]


def _candidate(fixture, **changes) -> MeetingCandidate:
    cand = runner.run_tier1(fixture)[1]
    assert cand is not None
    return replace(cand, **changes)


def test_end_and_attendees_match_the_ics_invite(tmp_path: Path):
    fixture = _ics_fixture(tmp_path)
    expected = fixture.expected.candidate
    cand = _candidate(fixture)
    assert runner._field_matches("end", expected, cand)
    assert runner._field_matches("attendees", expected, cand)


def test_attendees_match_regardless_of_order(tmp_path: Path):
    fixture = _ics_fixture(tmp_path)
    cand = _candidate(fixture, attendees=["lena@example.com", "team@example.com"])
    assert runner._field_matches("attendees", fixture.expected.candidate, cand)


def test_attendees_mismatch_on_a_missing_or_extra_attendee(tmp_path: Path):
    fixture = _ics_fixture(tmp_path)
    expected = fixture.expected.candidate
    missing = _candidate(fixture, attendees=["team@example.com"])
    extra = _candidate(fixture, attendees=[*expected.attendees, "x@example.com"])
    assert not runner._field_matches("attendees", expected, missing)
    assert not runner._field_matches("attendees", expected, extra)


def test_end_mismatches_on_a_different_instant_or_a_missing_end(tmp_path: Path):
    fixture = _ics_fixture(tmp_path)
    expected = fixture.expected.candidate
    later = _candidate(fixture, end=_candidate(fixture).end + timedelta(hours=1))
    assert not runner._field_matches("end", expected, later)
    assert not runner._field_matches("end", expected, _candidate(fixture, end=None))


def test_expected_none_end_matches_only_a_candidate_without_end(subset_dir: Path):
    fixture = load_fixtures(subset_dir)[0]
    expected = fixture.expected.candidate
    assert expected.end is None
    assert runner._field_matches("end", expected, _candidate(fixture))
    some_end = datetime(2026, 10, 22, 14, tzinfo=UTC)
    assert not runner._field_matches("end", expected, _candidate(fixture, end=some_end))


def test_no_candidate_fails_end_and_attendees(tmp_path: Path):
    expected = _ics_fixture(tmp_path).expected.candidate
    assert not runner._field_matches("end", expected, None)
    assert not runner._field_matches("attendees", expected, None)


def _result(latency_ms: float, **kw) -> runner.FixtureResult:
    return runner.FixtureResult(
        fixture_id="f",
        predicted_label="new_invite",
        label_correct=True,
        escalated=False,
        latency_ms=latency_ms,
        **kw,
    )


def test_latency_percentiles_use_nearest_rank_over_fixed_latencies():
    results = [_result(float(ms)) for ms in range(1, 21)]
    report = runner.EvalReport(tier=1, provider=None, model=None, results=results)
    assert report.latency_percentile(50) == 10.0
    assert report.latency_percentile(95) == 19.0
    body = runner.render_markdown(report)
    assert "| p50 latency | 10.00 ms |" in body
    assert "| p95 latency | 19.00 ms |" in body


def test_latency_percentiles_of_an_empty_report_are_zero():
    report = runner.EvalReport(tier=1, provider=None, model=None, results=[])
    assert report.latency_percentile(95) == 0.0


def _low_confidence_fixture(subset_dir: Path):
    fixture = load_fixtures(subset_dir)[0]
    fixture.input.text = fixture.input.text.replace("Eastern Time (US and Canada)", "")
    return fixture


def _mock_tier2(confidence: float, *, valid: bool = True, tokens=(120, 30)):
    calls: list[Message] = []

    def provider(message: Message, partial: MeetingCandidate | None) -> runner.Tier2Response:
        calls.append(message)
        assert partial is not None
        cand = replace(
            partial,
            tz="America/New_York",
            join_url="https://llm.invalid/j/1",
            start=datetime.fromisoformat("2026-10-22T09:00:00-04:00"),
            confidence=confidence,
            tier="llm",
        )
        return runner.Tier2Response(
            candidate=cand,
            valid=valid,
            confidence=confidence,
            input_tokens=tokens[0],
            output_tokens=tokens[1],
        )

    provider.calls = calls  # type: ignore[attr-defined]
    return provider


def test_tier2_reports_input_and_output_tokens_from_the_provider(subset_dir: Path):
    fixtures = [_low_confidence_fixture(subset_dir), load_fixtures(subset_dir)[1]]
    report = runner.evaluate(fixtures, tier=2, tier2=_mock_tier2(0.9), ram_sampler=lambda: None)
    assert (report.input_tokens, report.output_tokens) == (120, 30)
    body = runner.render_markdown(report)
    assert "| input tokens | 120.0 per candidate (120 total) |" in body
    assert "| output tokens | 30.0 per candidate (30 total) |" in body


def test_tier2_runs_only_on_fixtures_tier1_escalates(subset_dir: Path):
    provider = _mock_tier2(0.9)
    runner.evaluate(load_fixtures(subset_dir), tier=2, tier2=provider, ram_sampler=lambda: None)
    assert provider.calls == []


def test_tier2_keeps_join_url_from_the_regex_partial(subset_dir: Path):
    fixture = _low_confidence_fixture(subset_dir)
    report = runner.evaluate([fixture], tier=2, tier2=_mock_tier2(0.9), ram_sampler=lambda: None)
    assert report.field_accuracy()["join_url"] == (1, 1)
    assert report.field_accuracy()["tz"] == (1, 1)


@pytest.mark.parametrize(
    ("confidence", "valid", "escalated"),
    [(0.9, True, 0), (0.7, True, 0), (0.4, True, 1), (0.9, False, 1)],
)
def test_tier2_to_tier3_escalation_is_counted_from_results(
    subset_dir: Path, confidence: float, valid: bool, escalated: int
):
    fixture = _low_confidence_fixture(subset_dir)
    provider = _mock_tier2(confidence, valid=valid)
    report = runner.evaluate([fixture], tier=2, tier2=provider, ram_sampler=lambda: None)
    assert report.escalated_t2() == (escalated, 1)
    assert f"| escalated T2->T3 | {escalated}/1 |" in runner.render_markdown(report)


def test_tier2_without_a_provider_is_still_not_built(subset_dir: Path):
    with pytest.raises(runner.TierNotBuiltError):
        runner.evaluate(load_fixtures(subset_dir), tier=2)


def test_peak_ram_keeps_the_largest_sample_and_skips_unavailable_ones(subset_dir: Path):
    fixtures = [_low_confidence_fixture(subset_dir), *load_fixtures(subset_dir)]
    samples = iter([3 * 2**20, None, 5 * 2**20])
    report = runner.evaluate(
        fixtures, tier=2, tier2=_mock_tier2(0.9), ram_sampler=lambda: next(samples)
    )
    assert report.peak_ram_bytes == 5 * 2**20
    lines = runner.render_table(report).splitlines()
    assert [ln.split()[-2:] for ln in lines if ln.startswith("peak RAM")] == [["5", "MiB"]]


def test_peak_ram_shows_dash_when_the_sampler_is_unavailable(subset_dir: Path):
    fixture = _low_confidence_fixture(subset_dir)
    report = runner.evaluate([fixture], tier=2, tier2=_mock_tier2(0.9), ram_sampler=lambda: None)
    assert report.peak_ram_bytes is None
    assert "| peak RAM | - |" in runner.render_markdown(report)


def _ps_urlopen(body, seen: list[str] | None = None):
    def fake_urlopen(url, timeout):
        if seen is not None:
            seen.append(url)
        return io.BytesIO(json.dumps(body).encode())

    return fake_urlopen


def test_ollama_ps_sampler_reads_the_loaded_model_size(monkeypatch):
    seen: list[str] = []
    body = {
        "models": [
            {"name": "gemma3:1b", "model": "gemma3:1b", "size": 900, "size_vram": 0},
            {"name": "other:7b", "model": "other:7b", "size": 5000, "size_vram": 5000},
        ]
    }
    monkeypatch.setattr(runner.urllib.request, "urlopen", _ps_urlopen(body, seen))
    assert runner.ollama_ps_sampler("http://ollama.invalid:11434/", "gemma3:1b")() == 900
    assert seen == ["http://ollama.invalid:11434/api/ps"]


@pytest.mark.parametrize(
    ("model", "listed"),
    [
        ("gemma3", "gemma3:latest"),
        ("gemma3:latest", "gemma3"),
        ("localhost:5000/library/llama3", "localhost:5000/library/llama3:latest"),
    ],
)
def test_ollama_ps_sampler_matches_an_untagged_model_to_its_latest_tag(
    monkeypatch, model: str, listed: str
):
    body = {"models": [{"name": listed, "model": listed, "size": 900}]}
    monkeypatch.setattr(runner.urllib.request, "urlopen", _ps_urlopen(body))
    assert runner.ollama_ps_sampler("http://ollama.invalid", model)() == 900


def test_ollama_ps_sampler_does_not_match_a_different_tag(monkeypatch):
    body = {"models": [{"name": "gemma3:1b", "model": "gemma3:1b", "size": 900}]}
    monkeypatch.setattr(runner.urllib.request, "urlopen", _ps_urlopen(body))
    assert runner.ollama_ps_sampler("http://ollama.invalid", "gemma3")() is None


def test_ollama_ps_sampler_returns_none_when_unreachable_or_not_loaded(monkeypatch):
    def down(url, timeout):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(runner.urllib.request, "urlopen", down)
    assert runner.ollama_ps_sampler("http://ollama.invalid", "m")() is None
    monkeypatch.setattr(runner.urllib.request, "urlopen", _ps_urlopen({"models": []}))
    assert runner.ollama_ps_sampler("http://ollama.invalid", "m")() is None


def test_ollama_ps_sampler_returns_none_on_a_malformed_body(monkeypatch):
    bad = {"models": [{"name": "m", "size": "big"}]}
    monkeypatch.setattr(runner.urllib.request, "urlopen", _ps_urlopen(bad))
    assert runner.ollama_ps_sampler("http://ollama.invalid", "m")() is None
    monkeypatch.setattr(runner.urllib.request, "urlopen", _ps_urlopen([1, 2]))
    assert runner.ollama_ps_sampler("http://ollama.invalid", "m")() is None


def test_ollama_provider_defaults_to_the_ps_sampler(subset_dir: Path, monkeypatch):
    body = {"models": [{"name": "m", "size": 7 * 2**20}]}
    monkeypatch.setattr(runner.urllib.request, "urlopen", _ps_urlopen(body))
    fixture = _low_confidence_fixture(subset_dir)
    report = runner.evaluate(
        [fixture], tier=2, provider="ollama", model="m", tier2=_mock_tier2(0.9)
    )
    assert report.peak_ram_bytes == 7 * 2**20


def test_ollama_tokens_reads_prompt_and_eval_counts():
    assert runner.ollama_tokens({"prompt_eval_count": 42, "eval_count": 7}) == (42, 7)
    assert runner.ollama_tokens({}) == (0, 0)


def test_tier1_counts_a_low_confidence_candidate_as_escalated(subset_dir: Path):
    fixture = load_fixtures(subset_dir)[0]
    fixture.input.text = fixture.input.text.replace("Eastern Time (US and Canada)", "")
    report = runner.evaluate([fixture], tier=1)
    assert report.escalated == 1


@pytest.mark.parametrize("tier", [2, 3])
def test_unbuilt_tiers_raise_tier_not_built(subset_dir: Path, tier: int):
    with pytest.raises(runner.TierNotBuiltError, match=r"not built \(#8\)"):
        runner.evaluate(load_fixtures(subset_dir), tier=tier)


def test_markdown_output_is_a_table_with_every_metric(subset_dir: Path):
    report = runner.evaluate(load_fixtures(subset_dir), tier=1, provider="p", model="m")
    lines = runner.render_markdown(report).splitlines()
    assert lines[0] == "| Metric | Value |"
    assert lines[1] == "| --- | --- |"
    body = "\n".join(lines[2:])
    for metric in NEW_AND_EXISTING_METRICS:
        assert f"| {metric} |" in body
    assert "| provider | p |" in body
    assert "| escalated T2->T3 | 0/0 |" in body
    assert "| peak RAM | - |" in body


NEW_AND_EXISTING_METRICS = (
    "start accuracy",
    "end accuracy",
    "tz accuracy",
    "attendees accuracy",
    "escalated T1->T2",
    "escalated T2->T3",
    "mean latency",
    "p50 latency",
    "p95 latency",
    "input tokens",
    "output tokens",
    "peak RAM",
)


def test_table_output_has_a_row_for_every_metric(subset_dir: Path):
    report = runner.evaluate(load_fixtures(subset_dir), tier=1)
    keys = [line.split("  ")[0].strip() for line in runner.render_table(report).splitlines()]
    for metric in NEW_AND_EXISTING_METRICS:
        assert metric in keys


def test_cli_eval_tier1_prints_markdown(subset_dir: Path, capsys):
    rc = cli.main(["eval", "--tier", "1", "--fixtures", str(subset_dir), "--format", "markdown"])
    assert rc == 0
    assert "| title accuracy | 100.0% (1/1) |" in capsys.readouterr().out


@pytest.mark.parametrize("tier", ["2", "3"])
def test_cli_eval_unbuilt_tier_exits_nonzero_with_message(subset_dir: Path, capsys, tier: str):
    rc = cli.main(["eval", "--tier", tier, "--fixtures", str(subset_dir)])
    assert rc != 0
    assert f"tier {tier} not built (#8)" in capsys.readouterr().err


def test_link_only_invite_scores_join_url_from_the_tier0_link(tmp_path: Path):
    shutil.copy(FIXTURES / "chat" / "slack_quick_sync_zoom.json", tmp_path)
    report = runner.evaluate(load_fixtures(tmp_path), tier=1)
    assert report.field_accuracy()["join_url"] == (1, 1)
    assert report.escalated == 1


def test_cli_eval_malformed_fixture_json_exits_nonzero_naming_the_file(tmp_path: Path, capsys):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    rc = cli.main(["eval", "--fixtures", str(tmp_path)])
    assert rc == 1
    assert "broken.json" in capsys.readouterr().err


def test_cli_eval_non_utf8_fixture_exits_nonzero_naming_the_file(tmp_path: Path, capsys):
    (tmp_path / "ansi.json").write_bytes('{"id": "caf\xe9"}'.encode("cp1252"))
    rc = cli.main(["eval", "--fixtures", str(tmp_path)])
    assert rc == 1
    assert "ansi.json" in capsys.readouterr().err


def test_cli_eval_unknown_candidate_key_exits_nonzero_naming_the_key(tmp_path: Path, capsys):
    fixture = {
        "id": "x",
        "category": "chat",
        "label": "new_invite",
        "input": {"text": "hi"},
        "expected": {
            "label": "new_invite",
            "candidate": {"title": "x", "location": "y"},
        },
    }
    (tmp_path / "extra.json").write_text(json.dumps(fixture), encoding="utf-8")
    rc = cli.main(["eval", "--fixtures", str(tmp_path)])
    assert rc == 1
    assert "location" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("top_label", "expected_label", "field"),
    [
        ("new_invite", ["new_invite"], "expected.label"),
        (["new_invite"], "new_invite", "'label'"),
    ],
)
def test_cli_eval_non_string_label_exits_nonzero_instead_of_traceback(
    tmp_path: Path, capsys, top_label, expected_label, field
):
    fixture = {
        "id": "x",
        "category": "chat",
        "label": top_label,
        "input": {"text": "hi"},
        "expected": {"label": expected_label},
    }
    (tmp_path / "bad.json").write_text(json.dumps(fixture), encoding="utf-8")
    rc = cli.main(["eval", "--fixtures", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert field in err
    assert "must be a string" in err


def test_cli_eval_empty_fixture_directory_exits_nonzero(tmp_path: Path, capsys):
    rc = cli.main(["eval", "--fixtures", str(tmp_path)])
    assert rc == 1
    assert "no fixtures" in capsys.readouterr().err


def test_cli_eval_unbuilt_tier_with_missing_fixtures_reports_tier_not_built(
    tmp_path: Path, capsys
):
    rc = cli.main(["eval", "--tier", "2", "--fixtures", str(tmp_path / "missing")])
    assert rc == 1
    assert "tier 2 not built (#8)" in capsys.readouterr().err


def test_cli_eval_runs_against_the_shipped_fixture_corpus(capsys):
    rc = cli.main(["eval", "--tier", "1", "--fixtures", str(FIXTURES)])
    assert rc == 0
    assert "fixtures" in capsys.readouterr().out
