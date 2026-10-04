from pathlib import Path

import pytest

from cuecal.eval import (
    VALID_CATEGORIES,
    VALID_LABELS,
    ClassificationLabel,
    EvalFixture,
    FixtureValidationError,
    load_fixture,
    load_fixtures,
    validate_fixture_dict,
)
from cuecal.models import Message

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "eval"


def test_directory_structure_exists():
    assert FIXTURES_DIR.is_dir()
    for cat in VALID_CATEGORIES:
        cat_dir = FIXTURES_DIR / cat
        assert cat_dir.is_dir(), f"Expected directory {cat_dir} does not exist"


def test_all_fixtures_conform_to_schema():
    fixtures = load_fixtures(FIXTURES_DIR)
    assert len(fixtures) >= 15, f"Expected at least 15 fixtures, got {len(fixtures)}"

    seen_categories = {f.category for f in fixtures}
    assert (
        seen_categories == VALID_CATEGORIES
    ), f"Missing categories: {VALID_CATEGORIES - seen_categories}"

    seen_labels = {f.expected.label for f in fixtures}
    assert seen_labels == VALID_LABELS, f"Missing labels: {VALID_LABELS - seen_labels}"

    for fixture in fixtures:
        assert fixture.id
        assert fixture.category in VALID_CATEGORIES
        assert fixture.label in VALID_LABELS
        assert fixture.expected.label in VALID_LABELS
        assert fixture.input.text

        msg = fixture.input.to_message()
        assert isinstance(msg, Message)
        assert msg.text == fixture.input.text


def test_fixture_roundtrip():
    fixtures = load_fixtures(FIXTURES_DIR)
    fixture = fixtures[0]
    raw = fixture.to_dict()
    assert validate_fixture_dict(raw) == []
    reconstructed = EvalFixture.from_dict(raw)
    assert reconstructed.id == fixture.id
    assert reconstructed.category == fixture.category
    assert reconstructed.label == fixture.label


def test_validation_missing_required_fields():
    errors = validate_fixture_dict({})
    assert any("Missing required field: 'id'" in e for e in errors)
    assert any("Missing required field: 'category'" in e for e in errors)
    assert any("Missing required field: 'input'" in e for e in errors)
    assert any("Missing required field: 'expected'" in e for e in errors)


def test_validation_invalid_category_and_label():
    invalid = {
        "id": "bad-01",
        "category": "unknown_category",
        "label": "unknown_label",
        "input": {"text": "hello"},
        "expected": {"label": "unknown_label"},
    }
    errors = validate_fixture_dict(invalid)
    assert any("Invalid category 'unknown_category'" in e for e in errors)
    assert any("Invalid top-level label 'unknown_label'" in e for e in errors)
    assert any("Invalid 'expected.label' 'unknown_label'" in e for e in errors)


def test_validation_label_mismatch():
    mismatched = {
        "id": "mismatch-01",
        "category": "chat",
        "label": "new_invite",
        "input": {"text": "test"},
        "expected": {"label": "cancel"},
    }
    errors = validate_fixture_dict(mismatched)
    assert any("does not match expected.label" in e for e in errors)


def test_validation_invalid_datetime():
    invalid_dt = {
        "id": "dt-01",
        "category": "negatives",
        "label": "not_invite",
        "input": {
            "text": "sample text",
            "received_at": "not-a-datetime",
        },
        "expected": {"label": "not_invite", "candidate": None},
    }
    errors = validate_fixture_dict(invalid_dt)
    assert any("Invalid ISO 8601 datetime format" in e for e in errors)


def test_load_fixture_raises_on_invalid_file(tmp_path: Path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text('{"id": ""}', encoding="utf-8")
    with pytest.raises(FixtureValidationError):
        load_fixture(bad_file)


def test_load_fixture_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        load_fixture(FIXTURES_DIR / "non_existent.json")


def test_negative_fixtures_have_null_candidate():
    neg_fixtures = load_fixtures(FIXTURES_DIR / "negatives")
    for f in neg_fixtures:
        assert f.expected.candidate is None
        valid_neg_labels = {
            ClassificationLabel.NOT_INVITE,
            ClassificationLabel.MENTIONS_MEETING,
        }
        assert f.expected.label in valid_neg_labels
