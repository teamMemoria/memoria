"""A small, provider-neutral interface to a language model.

The team has not picked an LLM provider yet (see the repo README), so the
pipeline depends only on :class:`ModelClient`. Two implementations ship here:

* :class:`OpenAICompatibleClient` talks to any server with an OpenAI-style
  ``/chat/completions`` endpoint (hosted providers, or a local Ollama /
  llama.cpp server). It uses the standard library only.
* :class:`FakeModelClient` replays fixed responses, for tests and offline runs.

Any failure inside a client (network, timeout, HTTP error, non-JSON reply)
surfaces as a ``PipelineError`` with code ``model_failure`` so a caller can
never mistake it for "the model found nothing".
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .errors import MODEL_FAILURE, PipelineError


@dataclass
class ModelUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


class ModelClient(Protocol):
    name: str
    usage: ModelUsage

    def complete_json(
        self, *, system: str, prompt: str, max_output_tokens: int
    ) -> Mapping[str, Any]:
        """Return the model's reply parsed as a JSON object, or raise PipelineError."""
        ...


def _failure(message: str, **details: Any) -> PipelineError:
    return PipelineError(MODEL_FAILURE, message, "model", dict(details))


@dataclass
class OpenAICompatibleClient:
    """Chat-completions client. Configure with LLM_BASE_URL, LLM_MODEL and LLM_API_KEY."""

    base_url: str
    model: str
    api_key: str = ""
    timeout_s: float = 60.0
    usage: ModelUsage = field(default_factory=ModelUsage)

    @property
    def name(self) -> str:
        return f"openai-compatible:{self.model}"

    @classmethod
    def from_env(cls) -> OpenAICompatibleClient:
        base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        model = os.environ.get("LLM_MODEL", "")
        if not base_url or not model:
            raise _failure(
                "LLM_BASE_URL and LLM_MODEL must be set to use a model extractor"
            )
        return cls(
            base_url=base_url, model=model, api_key=os.environ.get("LLM_API_KEY", "")
        )

    def complete_json(
        self, *, system: str, prompt: str, max_output_tokens: int
    ) -> Mapping[str, Any]:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": max_output_tokens,
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise _failure(
                f"model server returned HTTP {error.code}", status=error.code
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise _failure(f"could not reach the model server: {error}") from error
        except json.JSONDecodeError as error:
            raise _failure("model server reply was not JSON") from error
        self.usage.calls += 1
        usage = payload.get("usage") or {}
        self.usage.input_tokens += int(usage.get("prompt_tokens") or 0)
        self.usage.output_tokens += int(usage.get("completion_tokens") or 0)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise _failure("model reply had no message content") from error
        return parse_json_object(content)


def parse_json_object(content: Any) -> Mapping[str, Any]:
    if not isinstance(content, str):
        raise _failure("model reply content was not text")
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :] if "{" in text else text
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise _failure("model reply was not valid JSON") from error
    if not isinstance(value, Mapping):
        raise _failure("model reply was not a JSON object")
    return value


@dataclass
class FakeModelClient:
    """Replays responses in order. A response may be a dict, a JSON string or an exception."""

    responses: Sequence[Any] = ()
    responder: Callable[[str, str], Any] | None = None
    name: str = "fake-model"
    usage: ModelUsage = field(default_factory=ModelUsage)
    prompts: list[str] = field(default_factory=list)

    def complete_json(
        self, *, system: str, prompt: str, max_output_tokens: int
    ) -> Mapping[str, Any]:
        self.prompts.append(prompt)
        if self.responder is not None:
            response = self.responder(system, prompt)
        else:
            index = self.usage.calls
            if index >= len(self.responses):
                raise _failure("fake model has no response left")
            response = self.responses[index]
        self.usage.calls += 1
        if isinstance(response, BaseException):
            if isinstance(response, PipelineError):
                raise response
            raise _failure(f"model call failed: {response}") from response
        if isinstance(response, str):
            return parse_json_object(response)
        if not isinstance(response, Mapping):
            raise _failure("fake model response was not a JSON object")
        return response
