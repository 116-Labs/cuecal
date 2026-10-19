from __future__ import annotations

import io
import json
import urllib.error

import pytest

from cuecal.extract import providers
from cuecal.extract.providers import (
    AnthropicProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderError,
    ProviderUnreachable,
    UnusableAnswer,
)

SCHEMA = {"type": "object"}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capture(monkeypatch, body: bytes | Exception):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(
            {
                "url": req.full_url,
                "headers": {k.lower(): v for k, v in req.header_items()},
                "payload": json.loads(req.data),
                "timeout": timeout,
            }
        )
        if isinstance(body, Exception):
            raise body
        return FakeResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return calls


def _ollama(**kw):
    args = {"host": "http://localhost:11434", "model": "m", "keep_alive": "30s", "timeout": 5}
    return OllamaProvider(**{**args, **kw})


def test_ollama_sends_keep_alive_schema_and_returns_tokens(monkeypatch):
    body = {"message": {"content": '{"a": 1}'}, "prompt_eval_count": 90, "eval_count": 12}
    calls = _capture(monkeypatch, json.dumps(body).encode())
    result = _ollama().complete("sys", "prompt", SCHEMA)
    [call] = calls
    assert call["url"] == "http://localhost:11434/api/chat"
    assert call["payload"]["keep_alive"] == "30s"
    assert call["payload"]["format"] == SCHEMA
    assert call["payload"]["stream"] is False
    assert call["payload"]["messages"][1] == {"role": "user", "content": "prompt"}
    assert call["timeout"] == 5
    assert (result.text, result.input_tokens, result.output_tokens) == ('{"a": 1}', 90, 12)


def test_ollama_keep_alive_is_overridable(monkeypatch):
    calls = _capture(monkeypatch, b'{"message": {"content": "{}"}}')
    _ollama(keep_alive="5m").complete("s", "p", SCHEMA)
    assert calls[0]["payload"]["keep_alive"] == "5m"


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError(ConnectionRefusedError("refused")),
        urllib.error.URLError(TimeoutError("timed out")),
        TimeoutError("timed out"),
        urllib.error.HTTPError("http://x", 500, "boom", {}, None),
    ],
    ids=["host-down", "connect-timeout", "read-timeout", "http-500"],
)
def test_transport_failures_raise_provider_error(monkeypatch, failure):
    _capture(monkeypatch, failure)
    with pytest.raises(ProviderError):
        _ollama().complete("s", "p", SCHEMA)


@pytest.mark.parametrize(
    "failure",
    [urllib.error.URLError(ConnectionRefusedError("refused")), TimeoutError("timed out")],
    ids=["host-down", "timeout"],
)
def test_connection_and_timeout_failures_are_unreachable(monkeypatch, failure):
    _capture(monkeypatch, failure)
    with pytest.raises(ProviderUnreachable):
        _ollama().complete("s", "p", SCHEMA)


def test_http_error_is_not_unreachable(monkeypatch):
    _capture(monkeypatch, urllib.error.HTTPError("http://x", 500, "boom", {}, None))
    with pytest.raises(ProviderError) as info:
        _ollama().complete("s", "p", SCHEMA)
    assert not isinstance(info.value, ProviderUnreachable)


@pytest.mark.parametrize("body", [b"<html>", b"[1, 2]", b'{"message": {}}'])
def test_unusable_ollama_body_raises_provider_error(monkeypatch, body):
    _capture(monkeypatch, body)
    with pytest.raises(ProviderError):
        _ollama().complete("s", "p", SCHEMA)


def test_anthropic_forces_a_tool_call_and_reads_its_input(monkeypatch):
    body = {
        "content": [
            {"type": "text", "text": "ignored"},
            {"type": "tool_use", "name": "record_meeting", "input": {"title": "T"}},
        ],
        "usage": {"input_tokens": 300, "output_tokens": 40},
    }
    calls = _capture(monkeypatch, json.dumps(body).encode())
    result = AnthropicProvider(model="claude-x", api_key=lambda: "sk-test").complete(
        "sys", "p", SCHEMA
    )
    [call] = calls
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "sk-test"
    assert call["headers"]["anthropic-version"] == providers.ANTHROPIC_VERSION
    assert call["payload"]["tool_choice"] == {"type": "tool", "name": "record_meeting"}
    assert call["payload"]["tools"][0]["input_schema"] == SCHEMA
    assert json.loads(result.text) == {"title": "T"}
    assert (result.input_tokens, result.output_tokens, result.usage_known) == (300, 40, True)


TOOL_USE = [{"type": "tool_use", "name": "record_meeting", "input": {"title": "T"}}]
BAD_USAGE = [
    None,
    "lots",
    {"input_tokens": 300},
    {"input_tokens": True, "output_tokens": 40},
    {"input_tokens": "300", "output_tokens": 40},
    {"input_tokens": -1, "output_tokens": 40},
]
BAD_USAGE_IDS = ["absent", "not-a-dict", "missing-count", "boolean", "string", "negative"]


@pytest.mark.parametrize("usage", BAD_USAGE, ids=BAD_USAGE_IDS)
def test_anthropic_unusable_usage_is_unknown_not_zero(monkeypatch, usage):
    body = {"content": TOOL_USE, **({} if usage is None else {"usage": usage})}
    _capture(monkeypatch, json.dumps(body).encode())
    result = AnthropicProvider(model="m", api_key=lambda: "k").complete("s", "p", SCHEMA)
    assert json.loads(result.text) == {"title": "T"}
    assert result.usage_known is False


@pytest.mark.parametrize("usage", BAD_USAGE, ids=BAD_USAGE_IDS)
def test_openai_unusable_usage_is_unknown_not_zero(monkeypatch, usage):
    if isinstance(usage, dict):
        usage = {
            {"input_tokens": "prompt_tokens", "output_tokens": "completion_tokens"}[k]: v
            for k, v in usage.items()
        }
    body = {
        "choices": [{"message": {"content": "{}"}}],
        **({} if usage is None else {"usage": usage}),
    }
    _capture(monkeypatch, json.dumps(body).encode())
    result = OpenAIProvider(model="m").complete("s", "p", SCHEMA)
    assert result.usage_known is False


def test_anthropic_without_tool_use_raises(monkeypatch):
    _capture(monkeypatch, b'{"content": [{"type": "text", "text": "hi"}]}')
    with pytest.raises(ProviderError, match="tool_use"):
        AnthropicProvider(model="m", api_key=lambda: "k").complete("s", "p", SCHEMA)


def test_anthropic_without_tool_use_still_reports_the_billed_usage(monkeypatch):
    body = {
        "content": [{"type": "text", "text": "hi"}],
        "usage": {"input_tokens": 300, "output_tokens": 40},
    }
    _capture(monkeypatch, json.dumps(body).encode())
    with pytest.raises(UnusableAnswer) as info:
        AnthropicProvider(model="m", api_key=lambda: "k").complete("s", "p", SCHEMA)
    usage = info.value.usage
    assert (usage.input_tokens, usage.output_tokens, usage.usage_known) == (300, 40, True)


def test_anthropic_without_tool_use_or_usage_reports_usage_unknown(monkeypatch):
    _capture(monkeypatch, b'{"content": [{"type": "text", "text": "hi"}]}')
    with pytest.raises(UnusableAnswer) as info:
        AnthropicProvider(model="m", api_key=lambda: "k").complete("s", "p", SCHEMA)
    assert info.value.usage.usage_known is False


@pytest.mark.parametrize(
    "getter",
    [lambda: None, lambda: (_ for _ in ()).throw(RuntimeError("locked"))],
    ids=["missing", "backend-error"],
)
def test_paid_provider_keyring_failure_raises_before_any_request(monkeypatch, getter):
    calls = _capture(monkeypatch, b"{}")
    with pytest.raises(ProviderError, match="keyring|API key"):
        AnthropicProvider(model="m", api_key=getter).complete("s", "p", SCHEMA)
    assert calls == []


def test_openai_compatible_posts_json_schema_to_base_url(monkeypatch):
    body = {
        "choices": [{"message": {"content": '{"title": "T"}'}}],
        "usage": {"prompt_tokens": 70, "completion_tokens": 9},
    }
    calls = _capture(monkeypatch, json.dumps(body).encode())
    result = OpenAIProvider(
        model="local-model", api_key=lambda: "k", base_url="http://127.0.0.1:8080/v1/"
    ).complete("s", "p", SCHEMA)
    [call] = calls
    assert call["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert call["headers"]["authorization"] == "Bearer k"
    assert call["payload"]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert (result.text, result.input_tokens, result.output_tokens) == ('{"title": "T"}', 70, 9)


def test_openai_compatible_without_key_sends_no_authorization(monkeypatch):
    calls = _capture(monkeypatch, b'{"choices": [{"message": {"content": "{}"}}]}')
    OpenAIProvider(model="m", base_url="http://127.0.0.1:1234/v1").complete("s", "p", SCHEMA)
    assert "authorization" not in calls[0]["headers"]


def test_openai_default_base_url_is_openai(monkeypatch):
    calls = _capture(monkeypatch, b'{"choices": [{"message": {"content": "{}"}}]}')
    OpenAIProvider(model="m", api_key=lambda: "k").complete("s", "p", SCHEMA)
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"


def test_openai_response_without_choices_raises(monkeypatch):
    _capture(monkeypatch, b'{"choices": []}')
    with pytest.raises(ProviderError):
        OpenAIProvider(model="m").complete("s", "p", SCHEMA)


def test_openai_null_content_still_reports_the_billed_usage(monkeypatch):
    body = {
        "choices": [{"message": {"content": None, "refusal": "no"}}],
        "usage": {"prompt_tokens": 70, "completion_tokens": 9},
    }
    _capture(monkeypatch, json.dumps(body).encode())
    with pytest.raises(UnusableAnswer) as info:
        OpenAIProvider(model="m").complete("s", "p", SCHEMA)
    usage = info.value.usage
    assert (usage.input_tokens, usage.output_tokens, usage.usage_known) == (70, 9, True)


def test_openai_without_choices_or_usage_reports_usage_unknown(monkeypatch):
    _capture(monkeypatch, b'{"choices": []}')
    with pytest.raises(UnusableAnswer) as info:
        OpenAIProvider(model="m").complete("s", "p", SCHEMA)
    assert info.value.usage.usage_known is False
