"""Central configuration for the multi-agent pipeline.

All LLM adapter instances are built here from environment variables and
cached as module-level singletons. Import ``get_adapter(role)`` to get
the adapter for a given agent role.

Environment variables
---------------------
General (apply to all agents unless overridden):
    LLM_PROVIDER            openai | anthropic | ollama | openai_compatible
                            Default: openai
    OPENAI_API_KEY          Required for openai / openai_compatible
    ANTHROPIC_API_KEY       Required for anthropic
    LLM_BASE_URL            Base URL for openai_compatible or ollama
                            Default for ollama: http://localhost:11434/v1
    LLM_MAX_TOKENS          Max output tokens per call. Default: 4096
    FORCE_JSON_MODE         true|false — bypass native struct output. Default: false

Per-agent model overrides (all fall back to their defaults below):
    OPENAI_MODEL            Drafting model (note + reply agents). Default: gpt-4.1
    OPENAI_CLASSIFIER_MODEL Classifier model. Default: gpt-4.1-mini
    OPENAI_SAFETY_MODEL     Safety agent model. Default: OPENAI_CLASSIFIER_MODEL
    OPENAI_STEPS_MODEL      Steps agent model.  Default: OPENAI_CLASSIFIER_MODEL
    OPENAI_QA_MODEL         QA agent model.     Default: OPENAI_MODEL
    OPENAI_VISION_MODEL     Vision model.       Default: gpt-4.1-mini

Per-agent provider overrides (rarely needed — useful if you want, e.g.,
safety on Ollama but drafting on OpenAI):
    SAFETY_LLM_PROVIDER     Override LLM_PROVIDER for the safety agent
    NOTE_LLM_PROVIDER       Override for the note agent
    REPLY_LLM_PROVIDER      Override for the reply agent
    STEPS_LLM_PROVIDER      Override for the steps agent
    QA_LLM_PROVIDER         Override for the QA agent
    CLASSIFIER_LLM_PROVIDER Override for the classifier

Per-agent JSON-mode override:
    SAFETY_FORCE_JSON_MODE, NOTE_FORCE_JSON_MODE, REPLY_FORCE_JSON_MODE,
    STEPS_FORCE_JSON_MODE, QA_FORCE_JSON_MODE, CLASSIFIER_FORCE_JSON_MODE

Examples
--------
Full OpenAI (default):
    LLM_PROVIDER=openai
    OPENAI_API_KEY=sk-...

Anthropic for all agents:
    LLM_PROVIDER=anthropic
    ANTHROPIC_API_KEY=sk-ant-...
    OPENAI_MODEL=claude-opus-4-5
    OPENAI_CLASSIFIER_MODEL=claude-haiku-4-5

Ollama (local, free):
    LLM_PROVIDER=ollama
    OPENAI_MODEL=llama3.1:70b
    OPENAI_CLASSIFIER_MODEL=llama3.1:8b
    FORCE_JSON_MODE=true           # most local models need this

Mixed — OpenAI for drafting, Ollama for cheap classification:
    LLM_PROVIDER=openai
    OPENAI_API_KEY=sk-...
    CLASSIFIER_LLM_PROVIDER=ollama
    OPENAI_CLASSIFIER_MODEL=llama3.1:8b
    CLASSIFIER_FORCE_JSON_MODE=true
    SAFETY_LLM_PROVIDER=ollama
    OPENAI_SAFETY_MODEL=llama3.1:8b
    SAFETY_FORCE_JSON_MODE=true
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from .llm import LLMAdapter, LLMConfig, LLMProvider

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _bool_env(key: str, default: bool = False) -> bool:
    return _env(key, "true" if default else "false").lower() in ("1", "true", "yes")


def _provider(env_key: str) -> LLMProvider:
    val = _env(env_key) or _env("LLM_PROVIDER", "openai")
    try:
        return LLMProvider(val.lower())
    except ValueError:
        raise ValueError(
            f"Unknown LLM provider {val!r} in {env_key}. "
            f"Valid options: {[p.value for p in LLMProvider]}"
        )


def _api_key(provider: LLMProvider) -> str:
    if provider == LLMProvider.ANTHROPIC:
        return _env("ANTHROPIC_API_KEY")
    return _env("OPENAI_API_KEY")


def _base_url(provider: LLMProvider, override: str = "") -> str:
    if override:
        return override
    if provider == LLMProvider.OLLAMA:
        return _env("LLM_BASE_URL", "http://localhost:11434/v1")
    return _env("LLM_BASE_URL", "")


def _build(
    role_prefix: str,
    model_env: str,
    model_default: str,
    default_temperature: float = 0.0,
) -> LLMConfig:
    """Build one LLMConfig for a named agent role."""
    provider = _provider(f"{role_prefix}_LLM_PROVIDER")
    model = _env(model_env, model_default)
    force_json = _bool_env(f"{role_prefix}_FORCE_JSON_MODE") or _bool_env("FORCE_JSON_MODE")
    max_tokens = int(_env("LLM_MAX_TOKENS", "4096"))
    return LLMConfig(
        provider=provider,
        model=model,
        api_key=_api_key(provider),
        base_url=_base_url(provider),
        default_temperature=default_temperature,
        max_tokens=max_tokens,
        force_json_mode=force_json,
    )


# ---------------------------------------------------------------------------
# Per-role adapter accessors (cached singletons)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def get_classifier_adapter() -> LLMAdapter:
    classifier_model = _env("OPENAI_CLASSIFIER_MODEL", "gpt-4.1-mini")
    return LLMAdapter(_build("CLASSIFIER", "OPENAI_CLASSIFIER_MODEL", classifier_model, 0.0))


@lru_cache(maxsize=None)
def get_safety_adapter() -> LLMAdapter:
    fallback = _env("OPENAI_CLASSIFIER_MODEL", "gpt-4.1-mini")
    return LLMAdapter(_build("SAFETY", "OPENAI_SAFETY_MODEL", fallback, 0.0))


@lru_cache(maxsize=None)
def get_note_adapter() -> LLMAdapter:
    return LLMAdapter(_build("NOTE", "OPENAI_MODEL", "gpt-4.1", 0.1))


@lru_cache(maxsize=None)
def get_reply_adapter() -> LLMAdapter:
    return LLMAdapter(_build("REPLY", "OPENAI_MODEL", "gpt-4.1", 0.2))


@lru_cache(maxsize=None)
def get_steps_adapter() -> LLMAdapter:
    fallback = _env("OPENAI_CLASSIFIER_MODEL", "gpt-4.1-mini")
    return LLMAdapter(_build("STEPS", "OPENAI_STEPS_MODEL", fallback, 0.0))


@lru_cache(maxsize=None)
def get_qa_adapter() -> LLMAdapter:
    fallback = _env("OPENAI_MODEL", "gpt-4.1")
    return LLMAdapter(_build("QA", "OPENAI_QA_MODEL", fallback, 0.0))


def config_summary() -> dict[str, str]:
    """Return a human-readable summary of active model config for UI display."""
    adapters = {
        "Classifier": get_classifier_adapter(),
        "Safety": get_safety_adapter(),
        "Note": get_note_adapter(),
        "Reply": get_reply_adapter(),
        "Steps": get_steps_adapter(),
        "QA": get_qa_adapter(),
    }
    return {
        role: f"{a.config.provider.value}:{a.config.model}"
        for role, a in adapters.items()
    }
