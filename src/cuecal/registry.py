"""Plugin registry for sources, extractor providers and sinks.

Plugins register in-process via `register` or are discovered from entry points in the
groups `cuecal.sources`, `cuecal.extractors` and `cuecal.sinks`.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

KINDS = ("sources", "extractors", "sinks")

_registry: dict[str, dict[str, Any]] = {kind: {} for kind in KINDS}


def _check(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown plugin kind {kind!r}; expected one of {KINDS}")


def register(kind: str, name: str, plugin: Any) -> None:
    _check(kind)
    if name in _registry[kind]:
        raise ValueError(f"{kind} plugin {name!r} is already registered")
    _registry[kind][name] = plugin


def get(kind: str, name: str) -> Any:
    _check(kind)
    try:
        return _registry[kind][name]
    except KeyError:
        raise KeyError(f"no {kind} plugin named {name!r}") from None


def load_entry_points() -> list[tuple[str, str, Exception]]:
    """Register plugins advertised through entry points; already-registered names are skipped.

    Returns (kind, name, error) for each entry point that failed to load.
    """
    broken: list[tuple[str, str, Exception]] = []
    for kind in KINDS:
        for ep in entry_points(group=f"cuecal.{kind}"):
            if ep.name not in _registry[kind]:
                try:
                    _registry[kind][ep.name] = ep.load()
                except Exception as exc:  # noqa: BLE001 - a broken plugin must not crash callers
                    broken.append((kind, ep.name, exc))
    return broken


def registered() -> dict[str, list[str]]:
    return {kind: sorted(_registry[kind]) for kind in KINDS}
