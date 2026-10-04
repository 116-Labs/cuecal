"""Schema and validation utilities for evaluation fixtures."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from dateutil import parser as dt_parser

from cuecal.models import Message


class ClassificationLabel(StrEnum):
    NEW_INVITE = "new_invite"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    MENTIONS_MEETING = "mentions_meeting"
    NOT_INVITE = "not_invite"


VALID_LABELS: set[str] = {label.value for label in ClassificationLabel}
VALID_CATEGORIES: set[str] = {"invites", "negatives", "linkless", "chat"}


class FixtureValidationError(ValueError):
    """Raised when an evaluation fixture fails schema validation."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class EvalFixtureInput:
    text: str
    received_at: str | None = None
    recipient_tz: str | None = None
    sender: str | None = None
    permalink: str | None = None
    attachments: list[str] = field(default_factory=list)

    def to_message(self, message_id: str = "eval-msg", source: str = "eval") -> Message:
        """Convert fixture input to a cuecal Message."""
        if self.received_at:
            ts = dt_parser.isoparse(self.received_at)
        else:
            ts = datetime.now()
        return Message(
            id=message_id,
            source=source,
            sender=self.sender or "sender@example.com",
            ts=ts,
            text=self.text,
            permalink=self.permalink,
            attachments=tuple(self.attachments),
        )


@dataclass
class ExpectedCandidate:
    title: str | None = None
    start: str | None = None
    end: str | None = None
    tz: str | None = None
    join_url: str | None = None
    meeting_id: str | None = None
    passcode: str | None = None
    attendees: list[str] = field(default_factory=list)
    confidence: float | None = None
    tier: str | None = None
    method: str | None = None


@dataclass
class ExpectedOutput:
    label: str
    candidate: ExpectedCandidate | None = None


@dataclass
class EvalFixture:
    id: str
    category: str
    label: str
    input: EvalFixtureInput
    expected: ExpectedOutput
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalFixture:
        errors = validate_fixture_dict(data)
        if errors:
            err_msg = "; ".join(errors)
            fixture_id = data.get("id", "<unknown>")
            raise FixtureValidationError(f"Invalid fixture {fixture_id}: {err_msg}", errors)

        inp_data = data["input"]
        inp = EvalFixtureInput(
            text=inp_data["text"],
            received_at=inp_data.get("received_at"),
            recipient_tz=inp_data.get("recipient_tz"),
            sender=inp_data.get("sender"),
            permalink=inp_data.get("permalink"),
            attachments=inp_data.get("attachments", []),
        )

        exp_data = data["expected"]
        cand_data = exp_data.get("candidate")
        cand = ExpectedCandidate(**cand_data) if cand_data is not None else None
        exp = ExpectedOutput(
            label=exp_data["label"],
            candidate=cand,
        )

        return cls(
            id=data["id"],
            category=data["category"],
            label=data.get("label", exp_data["label"]),
            input=inp,
            expected=exp,
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        return result


def validate_fixture_dict(data: Any) -> list[str]:
    """Validate a raw fixture dictionary against the schema."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Fixture root must be a JSON object/dict"]

    # Top-level required fields
    for required in ("id", "category", "input", "expected"):
        if required not in data:
            errors.append(f"Missing required field: '{required}'")

    if "id" in data and not isinstance(data["id"], str):
        errors.append("Field 'id' must be a non-empty string")
    elif "id" in data and not data["id"].strip():
        errors.append("Field 'id' cannot be blank")

    category = data.get("category")
    if category is not None:
        if not isinstance(category, str):
            errors.append("Field 'category' must be a string")
        elif category not in VALID_CATEGORIES:
            valid_cats = sorted(VALID_CATEGORIES)
            errors.append(f"Invalid category '{category}'. Must be one of: {valid_cats}")

    # Label validation
    label = data.get("label")
    if label is not None:
        if label not in VALID_LABELS:
            valid_lbls = sorted(VALID_LABELS)
            errors.append(f"Invalid top-level label '{label}'. Must be one of: {valid_lbls}")

    # Input validation
    inp = data.get("input")
    if inp is not None:
        if not isinstance(inp, dict):
            errors.append("Field 'input' must be a dictionary")
        else:
            if "text" not in inp:
                errors.append("Field 'input.text' is required")
            elif not isinstance(inp["text"], str):
                errors.append("Field 'input.text' must be a string")

            received_at = inp.get("received_at")
            if received_at is not None:
                if not isinstance(received_at, str):
                    errors.append("Field 'input.received_at' must be an ISO 8601 string or null")
                else:
                    try:
                        dt_parser.isoparse(received_at)
                    except (ValueError, TypeError):
                        errors.append(
                            "Invalid ISO 8601 datetime format for 'input.received_at': "
                            f"'{received_at}'"
                        )

            recipient_tz = inp.get("recipient_tz")
            if recipient_tz is not None and not isinstance(recipient_tz, str):
                errors.append("Field 'input.recipient_tz' must be a string or null")

            sender = inp.get("sender")
            if sender is not None and not isinstance(sender, str):
                errors.append("Field 'input.sender' must be a string or null")

            permalink = inp.get("permalink")
            if permalink is not None and not isinstance(permalink, str):
                errors.append("Field 'input.permalink' must be a string or null")

            attachments = inp.get("attachments")
            if attachments is not None:
                if not isinstance(attachments, list) or not all(
                    isinstance(a, str) for a in attachments
                ):
                    errors.append("Field 'input.attachments' must be a list of strings")

    # Expected validation
    exp = data.get("expected")
    if exp is not None:
        if not isinstance(exp, dict):
            errors.append("Field 'expected' must be a dictionary")
        else:
            if "label" not in exp:
                errors.append("Field 'expected.label' is required")
            elif exp["label"] not in VALID_LABELS:
                valid_lbls = sorted(VALID_LABELS)
                errors.append(
                    f"Invalid 'expected.label' '{exp['label']}'. Must be one of: {valid_lbls}"
                )

            if label is not None and "label" in exp and label != exp["label"]:
                errors.append(
                    f"Top-level label '{label}' does not match expected.label '{exp['label']}'"
                )

            candidate = exp.get("candidate")
            if candidate is not None:
                if not isinstance(candidate, dict):
                    errors.append("Field 'expected.candidate' must be a dictionary or null")
                else:
                    str_fields = (
                        "title",
                        "start",
                        "end",
                        "tz",
                        "join_url",
                        "meeting_id",
                        "passcode",
                        "tier",
                        "method",
                    )
                    for str_field in str_fields:
                        val = candidate.get(str_field)
                        if val is not None and not isinstance(val, str):
                            errors.append(
                                f"Field 'expected.candidate.{str_field}' must be a string or null"
                            )

                    if "attendees" in candidate:
                        attendees = candidate["attendees"]
                        if not isinstance(attendees, list) or not all(
                            isinstance(a, str) for a in attendees
                        ):
                            errors.append(
                                "Field 'expected.candidate.attendees' must be a list of strings"
                            )

                    if "confidence" in candidate:
                        conf = candidate["confidence"]
                        if conf is not None and not isinstance(conf, (int, float)):
                            errors.append(
                                "Field 'expected.candidate.confidence' must be a number or null"
                            )

    metadata = data.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("Field 'metadata' must be a dictionary")

    return errors


def load_fixture(path: Path | str) -> EvalFixture:
    """Load a fixture JSON file and validate it."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Fixture file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return EvalFixture.from_dict(data)


def load_fixtures(base_dir: Path | str) -> list[EvalFixture]:
    """Recursively discover and load all .json fixtures under base_dir."""
    directory = Path(base_dir)
    if not directory.is_dir():
        raise NotADirectoryError(f"Directory not found: {directory}")

    fixtures: list[EvalFixture] = []
    for json_file in sorted(directory.rglob("*.json")):
        fixtures.append(load_fixture(json_file))
    return fixtures
