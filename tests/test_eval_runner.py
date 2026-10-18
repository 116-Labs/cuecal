from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cuecal import cli
from cuecal.eval import load_fixtures, runner

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
        "tz": (1, 1),
        "join_url": (1, 1),
    }
    assert report.escalated == 0
    assert report.tokens == 0


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
    for metric in ("start accuracy", "tz accuracy", "escalated T1->T2", "mean latency", "tokens"):
        assert f"| {metric} |" in body
    assert "| provider | p |" in body


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
