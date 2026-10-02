import json as _json

import pytest
import requests as _requests

from multicat.llm.openrouter_client import (
    OpenRouterClient,
    QuotaExhaustedError,
    RateLimitError,
    parse_json_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_post(responses: list):
    """Return a fake requests.post that pops from `responses` on each call.

    Each item in `responses` is either:
      - a dict with keys: status_code (int), json_body (dict | None), text (str | None)
      - an exception instance to raise
    """
    call_count = {"n": 0}

    def fake_post(url, *, json=None, headers=None, timeout=None):
        idx = call_count["n"]
        call_count["n"] += 1
        item = responses[min(idx, len(responses) - 1)]
        if isinstance(item, BaseException):
            raise item
        status = item.get("status_code", 200)
        body = item.get("json_body")
        text = item.get("text", _json.dumps(body) if body else "")

        class FakeResp:
            status_code = status

            def json(self_):
                if body is None:
                    raise _requests.exceptions.JSONDecodeError("", "", 0)
                return body

            @property
            def text(self_):
                return text

        return FakeResp()

    return fake_post, call_count


def _ok_body(content: str, usage: dict | None = None) -> dict:
    body = {"choices": [{"message": {"content": content}}]}
    if usage:
        body["usage"] = usage
    return body


# ---------------------------------------------------------------------------
# parse_json_response
# ---------------------------------------------------------------------------

def test_parse_json_response_accepts_plain_json():
    assert parse_json_response('{"decision": "keep", "reason": "fits"}') == {
        "decision": "keep",
        "reason": "fits",
    }


def test_parse_json_response_accepts_markdown_json_block():
    text = """Here is the result:\n\n```json\n{"decision": "skip", "reason": "review"}\n```\n"""
    assert parse_json_response(text) == {"decision": "skip", "reason": "review"}


# ---------------------------------------------------------------------------
# Non-JSON API response
# ---------------------------------------------------------------------------

def test_openrouter_client_reports_non_json_api_response(monkeypatch):
    fake_post, _ = _make_fake_post([{"status_code": 200, "json_body": None, "text": "<html>bad gateway</html>"}])
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    client = OpenRouterClient(api_key="test", model="test-model", retries=0)

    with pytest.raises(RuntimeError, match="non-JSON"):
        client.chat_json(system_prompt="system", user_prompt="user")


# ---------------------------------------------------------------------------
# max_tokens in payload
# ---------------------------------------------------------------------------

def test_openrouter_client_sends_max_tokens_to_avoid_truncated_json(monkeypatch):
    """Regression: extraction JSON was truncated when no max_tokens was set."""
    captured_payloads = []

    def fake_post(url, *, json=None, headers=None, timeout=None):
        captured_payloads.append(json)

        class FakeResp:
            status_code = 200

            def json(self_):
                return _ok_body('{"decision": "keep", "reason": "ok"}')

            @property
            def text(self_):
                return ""

        return FakeResp()

    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    client = OpenRouterClient(api_key="test", model="test-model")
    client.chat_json(system_prompt="system", user_prompt="user")

    assert captured_payloads[0]["max_tokens"] == client.max_tokens
    assert captured_payloads[0]["max_tokens"] >= 8000


# ---------------------------------------------------------------------------
# Retry on malformed JSON
# ---------------------------------------------------------------------------

def test_openrouter_client_retries_once_after_malformed_json_then_succeeds(monkeypatch):
    """Regression: P000003 hit occasional malformed JSON; one retry should recover."""
    responses = [
        {"status_code": 200, "json_body": _ok_body('{"decision": "keep", "reason": unterminated')},
        {"status_code": 200, "json_body": _ok_body('{"decision": "keep", "reason": "ok"}')},
    ]
    fake_post, call_count = _make_fake_post(responses)
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = OpenRouterClient(api_key="test", model="test-model", retries=1)

    result = client.chat_json(system_prompt="system", user_prompt="user")

    assert call_count["n"] == 2
    assert result == {"decision": "keep", "reason": "ok"}


def test_openrouter_client_raises_after_exhausting_retries(monkeypatch):
    responses = [{"status_code": 200, "json_body": _ok_body('{"decision": unterminated')}]
    fake_post, call_count = _make_fake_post(responses)
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = OpenRouterClient(api_key="test", model="test-model", retries=1)

    with pytest.raises(_json.JSONDecodeError):
        client.chat_json(system_prompt="system", user_prompt="user")

    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Rate limit (429) retry
# ---------------------------------------------------------------------------

def test_openrouter_client_retries_rate_limit_with_backoff_then_succeeds(monkeypatch):
    """Regression: transient 429 must retry with backoff, not immediately fail."""
    sleep_calls = []
    responses = [
        {"status_code": 429, "json_body": None, "text": "rate limited"},
        {"status_code": 200, "json_body": _ok_body('{"decision": "keep", "reason": "ok"}')},
    ]
    fake_post, call_count = _make_fake_post(responses)
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    client = OpenRouterClient(api_key="test", model="test-model", retries=1)

    result = client.chat_json(system_prompt="system", user_prompt="user")

    assert call_count["n"] == 2
    assert result == {"decision": "keep", "reason": "ok"}
    assert sleep_calls == [client.retry_backoff_seconds]


def test_openrouter_client_raises_rate_limit_error_after_exhausting_retries(monkeypatch):
    responses = [{"status_code": 429, "json_body": None, "text": "rate limited"}]
    fake_post, call_count = _make_fake_post(responses)
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = OpenRouterClient(api_key="test", model="test-model", retries=1)

    with pytest.raises(RateLimitError):
        client.chat_json(system_prompt="system", user_prompt="user")

    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Quota exhausted (401/402/403) — must NOT retry
# ---------------------------------------------------------------------------

def test_openrouter_client_does_not_retry_quota_exhausted_error(monkeypatch):
    """Regression: 401/402/403 must raise immediately without retrying."""
    responses = [{"status_code": 402, "json_body": None, "text": "insufficient credits"}]
    fake_post, call_count = _make_fake_post(responses)
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    client = OpenRouterClient(api_key="test", model="test-model", retries=2)

    with pytest.raises(QuotaExhaustedError):
        client.chat_json(system_prompt="system", user_prompt="user")

    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Timeout retry
# ---------------------------------------------------------------------------

def test_openrouter_client_retries_on_timeout_then_succeeds(monkeypatch):
    """Regression: LLM read timeout must retry, not immediately fail the paper."""
    sleep_calls = []
    responses = [
        _requests.exceptions.Timeout("read timed out"),
        {"status_code": 200, "json_body": _ok_body('{"decision": "keep", "reason": "ok"}')},
    ]
    fake_post, call_count = _make_fake_post(responses)
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    client = OpenRouterClient(api_key="test", model="test-model", retries=1)

    result = client.chat_json(system_prompt="system", user_prompt="user")

    assert call_count["n"] == 2
    assert result == {"decision": "keep", "reason": "ok"}
    assert len(sleep_calls) == 1


def test_openrouter_client_raises_after_exhausting_timeout_retries(monkeypatch):
    responses = [_requests.exceptions.Timeout("read timed out")]
    fake_post, call_count = _make_fake_post(responses)
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = OpenRouterClient(api_key="test", model="test-model", retries=1)

    with pytest.raises(RuntimeError, match="timed out"):
        client.chat_json(system_prompt="system", user_prompt="user")

    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Call metrics
# ---------------------------------------------------------------------------

def test_openrouter_client_emits_call_metrics_with_token_usage_on_success(monkeypatch):
    """Regression: every successful call must report token usage via on_call_metrics."""
    captured = []
    usage = {"prompt_tokens": 1200, "completion_tokens": 340, "total_tokens": 1540}
    responses = [{"status_code": 200, "json_body": _ok_body('{"decision": "keep", "reason": "ok"}', usage)}]
    fake_post, _ = _make_fake_post(responses)
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    client = OpenRouterClient(api_key="test", model="test-model", on_call_metrics=captured.append)

    client.chat_json(system_prompt="system", user_prompt="user")

    assert len(captured) == 1
    m = captured[0]
    assert m.model == "test-model"
    assert m.prompt_tokens == 1200
    assert m.completion_tokens == 340
    assert m.total_tokens == 1540
    assert m.attempts == 1
    assert m.succeeded is True
    assert m.duration_seconds >= 0


def test_openrouter_client_emits_call_metrics_on_final_failure(monkeypatch):
    """Regression: failed calls must still emit metrics with succeeded=False."""
    captured = []
    responses = [{"status_code": 200, "json_body": _ok_body('{"decision": unterminated')}]
    fake_post, _ = _make_fake_post(responses)
    monkeypatch.setattr("multicat.llm.openrouter_client._requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = OpenRouterClient(
        api_key="test", model="test-model", retries=1, on_call_metrics=captured.append
    )

    with pytest.raises(_json.JSONDecodeError):
        client.chat_json(system_prompt="system", user_prompt="user")

    assert len(captured) == 1
    m = captured[0]
    assert m.succeeded is False
    assert m.attempts == 2
    assert m.error is not None
