from __future__ import annotations

import base64
import json
import re
import time
import threading
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests as _requests


class RateLimitError(RuntimeError):
    """Raised on HTTP 429: transient, the caller may retry after backing off."""


class QuotaExhaustedError(RuntimeError):
    """Raised on HTTP 401/402/403: account-level failure that will not
    resolve itself by retrying. Callers should stop the whole batch instead
    of burning time retrying every remaining paper.
    """


@dataclass(frozen=True)
class CallMetrics:
    """Per-request metrics, for cost/runtime reporting (e.g. methods section
    of a paper: total tokens consumed, average call duration, retry counts).
    """

    model: str
    duration_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    attempts: int
    succeeded: bool
    error: str | None = None


@dataclass(frozen=True)
class OpenRouterClient:
    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    timeout: int = 300  # per-read timeout in seconds (connect timeout is fixed at 30s)
    max_tokens: int = 65536
    retries: int = 2
    retry_backoff_seconds: float = 5.0
    on_call_metrics: Callable[[CallMetrics], None] | None = field(default=None)

    def chat_json_with_images(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_paths: list[Path],
    ) -> dict:
        """Like chat_json but includes images encoded as base64 in the user message."""
        last_error: Exception | None = None
        started_at = time.monotonic()
        attempts = 0
        last_usage: dict | None = None
        for attempt in range(self.retries + 1):
            attempts += 1
            try:
                content, usage = self._do_request_with_images(
                    system_prompt=system_prompt,
                    user_text=user_text,
                    image_paths=image_paths,
                )
                last_usage = usage
                self._emit_metrics(started_at, attempts, usage, succeeded=True, error=None)
                return content
            except QuotaExhaustedError as exc:
                self._emit_metrics(started_at, attempts, None, succeeded=False, error=str(exc))
                raise
            except RateLimitError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
            except json.JSONDecodeError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_seconds)
            except (TimeoutError, OSError, _requests.exceptions.Timeout) as exc:
                last_error = RuntimeError(f"LLM request timed out after {self.timeout}s: {exc}")
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_seconds)
            except RuntimeError as exc:
                last_error = exc
        assert last_error is not None
        self._emit_metrics(started_at, attempts, last_usage, succeeded=False, error=str(last_error))
        raise last_error

    def _do_request_with_images(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_paths: list[Path],
    ) -> tuple[dict, dict | None]:
        user_content: list[dict] = [{"type": "text", "text": user_text}]
        for img_path in image_paths:
            raw = img_path.read_bytes()
            b64 = base64.b64encode(raw).decode("ascii")
            suffix = img_path.suffix.lower().lstrip(".")
            media_type = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{b64}"},
            })
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
        }
        return self._post_payload(payload)

    def chat_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        last_error: Exception | None = None
        started_at = time.monotonic()
        attempts = 0
        last_usage: dict | None = None
        for attempt in range(self.retries + 1):
            attempts += 1
            try:
                content, usage = self._do_request(
                    system_prompt=system_prompt, user_prompt=user_prompt
                )
                last_usage = usage
                self._emit_metrics(started_at, attempts, usage, succeeded=True, error=None)
                return content
            except QuotaExhaustedError as exc:
                self._emit_metrics(started_at, attempts, None, succeeded=False, error=str(exc))
                raise  # not retryable, propagate immediately so the batch can stop
            except RateLimitError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
            except json.JSONDecodeError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_seconds)
            except (TimeoutError, OSError, _requests.exceptions.Timeout) as exc:
                last_error = RuntimeError(f"LLM request timed out after {self.timeout}s: {exc}")
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_seconds)
            except RuntimeError as exc:
                last_error = exc
        assert last_error is not None
        self._emit_metrics(started_at, attempts, last_usage, succeeded=False, error=str(last_error))
        raise last_error

    def _emit_metrics(
        self,
        started_at: float,
        attempts: int,
        usage: dict | None,
        *,
        succeeded: bool,
        error: str | None,
    ) -> None:
        if self.on_call_metrics is None:
            return
        usage = usage or {}
        metrics = CallMetrics(
            model=self.model,
            duration_seconds=time.monotonic() - started_at,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            attempts=attempts,
            succeeded=succeeded,
            error=error,
        )
        self.on_call_metrics(metrics)

    def _do_request(self, *, system_prompt: str, user_prompt: str) -> tuple[dict, dict | None]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
        }
        return self._post_payload(payload)

    def _post_payload(self, payload: dict) -> tuple[dict, dict | None]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://local/multicat",
            "X-Title": "MultiCat",
        }
        # Use a daemon thread with an absolute wall-clock deadline to guard
        # against drip-slow responses that reset the per-chunk read timeout
        # indefinitely. The thread is abandoned (daemon=True) if it exceeds
        # self.timeout seconds total, so the caller is never blocked forever.
        connect_timeout = 30
        result_box: list = []
        error_box: list = []

        def _do_post() -> None:
            try:
                r = _requests.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=(connect_timeout, self.timeout),
                )
                result_box.append(r)
            except Exception as exc:  # noqa: BLE001
                error_box.append(exc)

        done = threading.Event()

        def _do_post_and_signal() -> None:
            _do_post()
            done.set()

        t = threading.Thread(target=_do_post_and_signal, daemon=True)
        t.start()
        deadline = self.timeout + connect_timeout + 10
        if not done.wait(timeout=deadline):
            raise TimeoutError(f"LLM request timed out after {self.timeout}s (absolute wall-clock)")
        if error_box:
            exc = error_box[0]
            if isinstance(exc, _requests.exceptions.Timeout):
                raise TimeoutError(f"LLM request timed out (read>{self.timeout}s)") from exc
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        resp = result_box[0]

        if resp.status_code == 429:
            raise RateLimitError(f"OpenRouter HTTP 429 (rate limited): {resp.text[:500]}")
        if resp.status_code in (401, 402, 403):
            raise QuotaExhaustedError(
                f"OpenRouter HTTP {resp.status_code} (quota/auth failure): {resp.text[:500]}"
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:500]}")

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenRouter returned non-JSON response: {resp.text[:500]}") from exc

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        return parse_json_response(content), usage


def parse_json_response(text: str) -> dict:
    stripped = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if match:
        stripped = match.group(1).strip()
    return json.loads(stripped)
