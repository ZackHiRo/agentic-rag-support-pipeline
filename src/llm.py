"""Provider-agnostic LLM adapter.

Supported providers
-------------------
- ``openai``            — OpenAI API (api.openai.com)
- ``anthropic``         — Anthropic API (api.anthropic.com)
- ``ollama``            — Ollama local server (OpenAI-compat at localhost:11434)
- ``openai_compatible`` — Any OpenAI-compatible endpoint (Together, Groq, Fireworks…)

Structured output strategy
--------------------------
All agents expect a Pydantic model back from the LLM.

OpenAI / openai_compatible with json_schema support:
    Uses ``beta.chat.completions.parse()`` with Pydantic ``response_format``.
    Falls back to JSON-mode + manual parse if the provider doesn't support it.

Anthropic:
    Uses tool_use with the Pydantic model's JSON schema as the input_schema.
    This is Anthropic's official way to get structured output.

Ollama (openai_compatible):
    Uses the OpenAI client pointed at ``http://localhost:11434/v1``.
    Prefers ``response_format={"type": "json_schema", ...}`` for models that
    support it; falls back to JSON-mode with the schema injected in the system
    prompt for older/smaller models.

Configuration
-------------
Each agent is configured via an ``LLMConfig`` object assembled in ``src/config.py``
from environment variables. The adapter is instantiated once per process and
shared across all calls to that agent.

Usage
-----
    adapter = LLMAdapter(config)
    result: MyModel = adapter.parse(
        messages=[{"role": "user", "content": "..."}],
        response_format=MyModel,
        temperature=0.0,
    )
"""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# The SDK default read timeout is 10 minutes, so one stalled request would freeze
# a ticket. Fail fast and let the SDK retry instead.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# Optional heavy imports — only loaded when the relevant provider is used.
_openai_client_cache: dict[str, Any] = {}
_anthropic_client_cache: dict[str, Any] = {}


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"


class LLMConfig(BaseModel):
    """All settings needed to talk to one LLM endpoint for one role."""

    provider: LLMProvider = LLMProvider.OPENAI
    model: str = "gpt-4.1-mini"
    api_key: str = ""
    base_url: str = ""          # for openai_compatible / ollama
    default_temperature: float = 0.0
    max_tokens: int = 4096      # max output tokens (not context)

    # If True, fall back to JSON-mode + schema-in-prompt instead of native
    # structured output. Useful for models that don't support json_schema.
    force_json_mode: bool = False


# ---------------------------------------------------------------------------
# Schema injection (fallback for providers/models without native struct output)
# ---------------------------------------------------------------------------

_SCHEMA_SYSTEM_SUFFIX = """

---

## Output format

You MUST respond with a single valid JSON object that conforms exactly to this
JSON schema. Output ONLY the JSON object — no markdown fences, no prose, no
explanation before or after.

Schema:
```json
{schema}
```
"""


def _inject_schema(system: str, model_class: type[BaseModel]) -> str:
    schema_str = json.dumps(model_class.model_json_schema(), indent=2)
    return system + _SCHEMA_SYSTEM_SUFFIX.format(schema=schema_str)


def _extract_json(text: str) -> str:
    """Strip markdown fences and extract the first JSON object/array."""
    text = text.strip()
    # Strip ```json ... ``` fences
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # Find first { or [
    for i, ch in enumerate(text):
        if ch in "{[":
            return text[i:]
    return text


# ---------------------------------------------------------------------------
# OpenAI / OpenAI-compatible adapter
# ---------------------------------------------------------------------------


def _get_openai_client(config: LLMConfig):
    from openai import OpenAI

    key = f"{config.provider}:{config.base_url}:{config.api_key[:8] if config.api_key else ''}"
    if key not in _openai_client_cache:
        kwargs: dict[str, Any] = {}
        if config.api_key:
            kwargs["api_key"] = config.api_key
        if config.base_url:
            kwargs["base_url"] = config.base_url
        _openai_client_cache[key] = OpenAI(timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES, **kwargs)
    return _openai_client_cache[key]


def _parse_openai(
    config: LLMConfig,
    messages: list[dict],
    response_format: type[T],
    temperature: float,
) -> T:
    client = _get_openai_client(config)

    if config.force_json_mode:
        # Inject schema into last system message and use json_object mode.
        msgs = list(messages)
        for i, m in enumerate(msgs):
            if m["role"] == "system":
                msgs[i] = {**m, "content": _inject_schema(m["content"], response_format)}
                break
        resp = client.chat.completions.create(
            model=config.model,
            temperature=temperature,
            max_tokens=config.max_tokens,
            messages=msgs,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        return response_format.model_validate(json.loads(_extract_json(raw)))
    else:
        # Native structured output (OpenAI's Pydantic parse).
        resp = client.beta.chat.completions.parse(
            model=config.model,
            temperature=temperature,
            max_tokens=config.max_tokens,
            messages=messages,
            response_format=response_format,
        )
        parsed = resp.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError(
                f"OpenAI model {config.model!r} returned no structured output. "
                "Try setting FORCE_JSON_MODE=true for this agent."
            )
        return parsed  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Anthropic adapter
# ---------------------------------------------------------------------------


def _get_anthropic_client(config: LLMConfig):
    import anthropic as ant

    key = f"anthropic:{config.api_key[:8] if config.api_key else ''}"
    if key not in _anthropic_client_cache:
        kwargs: dict[str, Any] = {}
        if config.api_key:
            kwargs["api_key"] = config.api_key
        _anthropic_client_cache[key] = ant.Anthropic(timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES, **kwargs)
    return _anthropic_client_cache[key]


def _parse_anthropic(
    config: LLMConfig,
    messages: list[dict],
    response_format: type[T],
    temperature: float,
) -> T:
    client = _get_anthropic_client(config)

    # Split out system message (Anthropic takes it separately).
    system_parts: list[str] = []
    user_messages: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        else:
            user_messages.append(m)

    system = "\n\n".join(system_parts)

    # Use tool_use for structured output — Anthropic's official approach.
    schema = response_format.model_json_schema()
    # Anthropic requires additionalProperties: false for strict schemas.
    schema.setdefault("additionalProperties", False)

    resp = client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        temperature=temperature,
        system=system,
        messages=user_messages,
        tools=[
            {
                "name": "structured_output",
                "description": "Return the structured response matching the required schema.",
                "input_schema": schema,
            }
        ],
        tool_choice={"type": "tool", "name": "structured_output"},
    )

    # Extract tool_use block.
    for block in resp.content:
        if block.type == "tool_use" and block.name == "structured_output":
            return response_format.model_validate(block.input)

    # Fallback: parse text content as JSON.
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    return response_format.model_validate(json.loads(_extract_json(text)))


# ---------------------------------------------------------------------------
# Public adapter class
# ---------------------------------------------------------------------------


class LLMAdapter:
    """Provider-agnostic structured-output LLM wrapper.

    Instantiate once per agent role; share the instance across all calls in
    the same process (clients are cached internally).
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def parse(
        self,
        messages: list[dict],
        response_format: type[T],
        temperature: float | None = None,
    ) -> T:
        """Run a chat completion and return a parsed Pydantic model.

        Parameters
        ----------
        messages:
            Standard OpenAI-style message list
            ``[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]``.
        response_format:
            The Pydantic model class to parse into.
        temperature:
            Overrides ``config.default_temperature`` when provided.
        """
        t = temperature if temperature is not None else self.config.default_temperature
        provider = self.config.provider

        if provider == LLMProvider.ANTHROPIC:
            return _parse_anthropic(self.config, messages, response_format, t)

        # OpenAI, Ollama, openai_compatible all use the OpenAI client.
        return _parse_openai(self.config, messages, response_format, t)
