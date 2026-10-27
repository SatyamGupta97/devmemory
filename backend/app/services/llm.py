"""Language model access for the AI-assisted inspector.

One interface, one implementation (any OpenAI-compatible chat completions
endpoint), and an explicit "not configured" state. There is deliberately no
offline fallback that pretends to be a model: a fabricated analysis is worse
than an absent one, because a user cannot tell the difference.

The key never appears in an exception message, and request bodies are never
echoed back — both would leak memories and credentials into logs and API
responses.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import (
    llm_api_key,
    llm_base_url,
    llm_model,
    llm_provider_name,
    llm_retries,
    llm_retry_backoff_seconds,
    llm_timeout_seconds,
)

#: Statuses worth another attempt. 429 is rate limiting, 5xx is the provider
#: having a bad moment. Retrying a 400 or 401 would just waste time: the request
#: itself is wrong.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class LLMError(RuntimeError):
    """The model could not be called. Message is safe to show a user."""


class LLMNotConfigured(LLMError):
    """No key or model is configured, so AI analysis cannot run."""


class _RetryableError(Exception):
    """Internal: a failure worth trying again. Never escapes this module."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user"
    content: str


@dataclass(frozen=True)
class ChatCompletion:
    text: str
    model: str


class LLMClient:
    """Minimal chat-completions client.

    ``temperature=0`` and a JSON response format are requested because this is an
    extraction task: variation is noise, not creativity.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 45.0,
        retries: int = 1,
        retry_backoff_seconds: float = 1.5,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = base_url
        self._timeout = timeout
        self._retries = max(0, retries)
        self._retry_backoff = retry_backoff_seconds

    def complete(self, messages: list[ChatMessage]) -> ChatCompletion:
        """Call the provider, retrying a transient failure a bounded number of times.

        Observed in practice: providers return 503 while shedding load. Failing
        the whole analysis on one such response loses a working feature for a
        temporary reason, so a small number of retries is worth the delay.
        """
        attempt = 0
        while True:
            try:
                return self._complete_once(messages)
            except _RetryableError as error:
                attempt += 1
                if attempt > self._retries:
                    raise LLMError(error.message) from error
                time.sleep(self._retry_backoff * attempt)

    def _complete_once(self, messages: list[ChatMessage]) -> ChatCompletion:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
                "temperature": 0,
                # Well supported by OpenAI-compatible servers. If a provider
                # rejects it, the request fails loudly rather than silently
                # returning prose we would have to guess at.
                "response_format": {"type": "json_object"},
            }
        ).encode()

        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as error:
            message = (
                f"The model provider returned HTTP {error.code}."
                + self._safe_reason(error)
            )
            if error.code in RETRYABLE_STATUS:
                raise _RetryableError(message) from error
            raise LLMError(message) from error
        except urllib.error.URLError as error:
            raise LLMError(f"Could not reach the model provider: {error.reason}") from error
        except TimeoutError as error:
            raise LLMError(
                f"The model provider did not respond within {self._timeout:.0f}s."
            ) from error
        except json.JSONDecodeError as error:
            raise LLMError("The model provider returned invalid JSON.") from error

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError("The model provider returned no choices.")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("The model provider returned an empty response.")

        return ChatCompletion(text=content, model=str(body.get("model", self.model)))

    @staticmethod
    def _safe_reason(error: urllib.error.HTTPError) -> str:
        """Read a short error message from the body, without echoing the request.

        The request body contains the user's memories and the Authorization
        header contains the key, so neither is ever included.
        """
        try:
            body = json.loads(error.read())
            message = body.get("error", {})
            if isinstance(message, dict):
                text = message.get("message", "")
                if isinstance(text, str) and text:
                    return f" {text[:200]}"
        except Exception:  # noqa: BLE001 - provider may return non-JSON
            pass
        return ""


def is_configured() -> bool:
    return bool(llm_api_key() and llm_model())


def unavailable_reason() -> str:
    """Why AI analysis cannot run, in terms a user can act on.

    Empty string when it can run: callers should not have to interpret a reason
    for a non-problem.
    """
    if is_configured():
        return ""

    configured = llm_provider_name()
    if configured == "local":
        return (
            "DEVMEMORY_LLM_PROVIDER=local is not supported: this project has no "
            "on-device language model. Set DEVMEMORY_LLM_API_KEY and "
            "DEVMEMORY_LLM_MODEL to enable AI-assisted analysis."
        )
    if not llm_api_key() and not llm_model():
        return (
            "AI-assisted analysis is not configured. Set DEVMEMORY_LLM_API_KEY and "
            "DEVMEMORY_LLM_MODEL. The deterministic health check works without it."
        )
    if not llm_api_key():
        return "DEVMEMORY_LLM_API_KEY is not set."
    return "DEVMEMORY_LLM_MODEL is not set."


def get_client() -> LLMClient:
    """Build a client, or raise ``LLMNotConfigured`` with an actionable reason."""
    if not is_configured():
        raise LLMNotConfigured(unavailable_reason())

    return LLMClient(
        api_key=llm_api_key(),
        model=llm_model(),
        base_url=llm_base_url(),
        timeout=llm_timeout_seconds(),
        retries=llm_retries(),
        retry_backoff_seconds=llm_retry_backoff_seconds(),
    )