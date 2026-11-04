"""LLM providers over raw HTTP: Ollama (Tier 2), Anthropic and OpenAI-compatible (Tier 3)."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

ANTHROPIC_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1"
PAID_TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_TOKENS = 1024
_TOOL = "record_meeting"


class ProviderError(RuntimeError):
    """Raised when a provider call fails: host down, timeout, HTTP error or unusable body."""


class ProviderUnreachable(ProviderError):
    """Raised when the host cannot be reached or the call times out."""


@dataclass(frozen=True)
class ProviderResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    usage_known: bool = True


class UnusableAnswer(ProviderError):
    """Raised when a paid call returned 200 but no usable answer; ``usage`` is what it billed."""

    def __init__(self, message: str, usage: ProviderResult) -> None:
        super().__init__(message)
        self.usage = usage


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> ProviderResult:
        """Return the model's JSON answer as text; raise ProviderError on any failure."""
        ...


def _post_json(
    url: str, payload: dict[str, Any], *, headers: dict[str, str], timeout: float
) -> dict[str, Any]:
    req = urllib.request.Request(  # noqa: S310 - scheme validated in config
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"HTTP {exc.code} from {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
        raise ProviderUnreachable(f"cannot reach {url}: {exc}") from exc
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProviderError(f"non-JSON response from {url}") from exc
    if not isinstance(body, dict):
        raise ProviderError(f"unexpected response shape from {url}")
    return body


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _int(value: Any) -> int:
    return value if _is_count(value) else 0


def _paid_result(
    text: str, body: dict[str, Any], input_key: str, output_key: str
) -> ProviderResult:
    """Unusable usage counts are reported as unknown, never as zero, so the spend cap holds."""
    usage = body.get("usage")
    counts = [usage.get(input_key), usage.get(output_key)] if isinstance(usage, dict) else []
    if len(counts) == 2 and all(_is_count(c) for c in counts):
        return ProviderResult(text, counts[0], counts[1])
    return ProviderResult(text, usage_known=False)


class OllamaProvider:
    name = "ollama"

    def __init__(self, *, host: str, model: str, keep_alive: str, timeout: float) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.keep_alive = keep_alive
        self.timeout = timeout

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> ProviderResult:
        body = _post_json(
            f"{self.host}/api/chat",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "format": schema,
                "stream": False,
                "keep_alive": self.keep_alive,
                "options": {"temperature": 0},
            },
            headers={},
            timeout=self.timeout,
        )
        message = body.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderError("ollama response has no message content")
        return ProviderResult(
            content, _int(body.get("prompt_eval_count")), _int(body.get("eval_count"))
        )


def _api_key(get_key: Callable[[], str | None] | None) -> str:
    if get_key is None:
        raise ProviderError("no API key configured (llm.paid.api_key_secret)")
    try:
        key = get_key()
    except Exception as exc:  # noqa: BLE001 - any keyring backend failure ends this call
        raise ProviderError(f"keyring read failed: {exc}") from exc
    if not key:
        raise ProviderError("API key missing from the keyring")
    return key


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: Callable[[], str | None] | None,
        base_url: str = "",
        timeout: float = PAID_TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or ANTHROPIC_URL).rstrip("/")
        self.timeout = timeout

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> ProviderResult:
        key = _api_key(self.api_key)
        # A forced tool call makes the model answer with arguments matching the schema.
        body = _post_json(
            f"{self.base_url}/v1/messages",
            {
                "model": self.model,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
                "tools": [
                    {"name": _TOOL, "description": "Record the meeting.", "input_schema": schema}
                ],
                "tool_choice": {"type": "tool", "name": _TOOL},
            },
            headers={"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION},
            timeout=self.timeout,
        )
        blocks = body.get("content")
        tool_input = next(
            (
                b.get("input")
                for b in blocks or []
                if isinstance(b, dict) and b.get("type") == "tool_use"
            ),
            None,
        )
        if not isinstance(tool_input, dict):
            raise UnusableAnswer(
                "anthropic response has no tool_use block",
                _paid_result("", body, "input_tokens", "output_tokens"),
            )
        return _paid_result(json.dumps(tool_input), body, "input_tokens", "output_tokens")


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key: Callable[[], str | None] | None = None,
        base_url: str = "",
        timeout: float = PAID_TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or OPENAI_URL).rstrip("/")
        self.timeout = timeout

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> ProviderResult:
        headers = {}
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {_api_key(self.api_key)}"
        body = _post_json(
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "meeting", "schema": schema},
                },
            },
            headers=headers,
            timeout=self.timeout,
        )
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str):
            raise UnusableAnswer(
                "openai response has no message content",
                _paid_result("", body, "prompt_tokens", "completion_tokens"),
            )
        return _paid_result(content, body, "prompt_tokens", "completion_tokens")
