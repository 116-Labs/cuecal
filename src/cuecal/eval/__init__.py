"""Evaluation and dataset staging schemas for CueCal."""

from __future__ import annotations

from cuecal.eval.schema import (
    VALID_CATEGORIES,
    VALID_LABELS,
    ClassificationLabel,
    EvalFixture,
    EvalFixtureInput,
    ExpectedCandidate,
    ExpectedOutput,
    FixtureValidationError,
    load_fixture,
    load_fixtures,
    validate_fixture_dict,
)

__all__ = [
    "VALID_CATEGORIES",
    "VALID_LABELS",
    "ClassificationLabel",
    "EvalFixture",
    "EvalFixtureInput",
    "ExpectedCandidate",
    "ExpectedOutput",
    "FixtureValidationError",
    "load_fixture",
    "load_fixtures",
    "validate_fixture_dict",
]
