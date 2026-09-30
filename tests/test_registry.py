import pytest

from cuecal import registry


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(registry, "_registry", {kind: {} for kind in registry.KINDS})


def test_register_and_get():
    plugin = object()
    registry.register("sources", "slack", plugin)
    assert registry.get("sources", "slack") is plugin
    assert registry.registered()["sources"] == ["slack"]


def test_duplicate_and_unknown():
    registry.register("sinks", "ics", object())
    with pytest.raises(ValueError, match="already registered"):
        registry.register("sinks", "ics", object())
    with pytest.raises(KeyError):
        registry.get("sinks", "nope")
    with pytest.raises(ValueError, match="unknown plugin kind"):
        registry.register("bogus", "x", object())
