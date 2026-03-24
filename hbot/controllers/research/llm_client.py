"""Provider-agnostic LLM client for the strategy exploration agent.

This is the ONLY module that imports LLM provider SDKs (anthropic, openai).
All other exploration modules depend on the ``LlmClient`` protocol.
"""
from __future__ import annotations

import os
import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_KEY_TIERS_ANTHROPIC = ("ANTHROPIC_API_KEY", "RESEARCH_LLM_API_KEY", "LLM_API_KEY")
_KEY_TIERS_OPENAI = ("OPENAI_API_KEY", "RESEARCH_LLM_API_KEY", "LLM_API_KEY")
_MODEL_TIERS_ANTHROPIC = ("ANTHROPIC_MODEL", "RESEARCH_LLM_MODEL")
_MODEL_TIERS_OPENAI = ("OPENAI_MODEL", "RESEARCH_LLM_MODEL")

_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
_DEFAULT_OPENAI_MODEL = "gpt-4o"


def _resolve_env(tiers: tuple[str, ...], default: str | None = None) -> str | None:
    """Return the first non-empty env var from *tiers*, or *default*."""
    for var in tiers:
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return default


@runtime_checkable
class LlmClient(Protocol):
    """Structural protocol for LLM provider clients."""

    tokens_used: int

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str: ...

    def count_tokens(self, text: str) -> int: ...


class AnthropicClient:
    """Wraps the ``anthropic`` SDK behind the ``LlmClient`` protocol."""

    def __init__(self) -> None:
        api_key = _resolve_env(_KEY_TIERS_ANTHROPIC)
        if not api_key:
            raise EnvironmentError(
                f"No Anthropic API key found. Set one of: {', '.join(_KEY_TIERS_ANTHROPIC)}"
            )
        self._model = _resolve_env(_MODEL_TIERS_ANTHROPIC, _DEFAULT_ANTHROPIC_MODEL) or _DEFAULT_ANTHROPIC_MODEL
        self.tokens_used: int = 0

        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str:
        system_msg = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                chat_messages.append({"role": m["role"], "content": m["content"]})

        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": chat_messages,
        }
        if system_msg:
            kwargs["system"] = system_msg

        response = self._client.messages.create(**kwargs)

        input_tokens = getattr(response.usage, "input_tokens", 0)
        output_tokens = getattr(response.usage, "output_tokens", 0)
        self.tokens_used += input_tokens + output_tokens

        return response.content[0].text

    def count_tokens(self, text: str) -> int:
        return len(text) // 4


class OpenAIClient:
    """Wraps the ``openai`` SDK behind the ``LlmClient`` protocol."""

    def __init__(self) -> None:
        api_key = _resolve_env(_KEY_TIERS_OPENAI)
        if not api_key:
            raise EnvironmentError(
                f"No OpenAI API key found. Set one of: {', '.join(_KEY_TIERS_OPENAI)}"
            )
        self._model = _resolve_env(_MODEL_TIERS_OPENAI, _DEFAULT_OPENAI_MODEL) or _DEFAULT_OPENAI_MODEL
        self.tokens_used: int = 0

        import openai
        self._client = openai.OpenAI(api_key=api_key)

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            messages=messages,  # type: ignore[arg-type]
        )
        usage = response.usage
        if usage:
            self.tokens_used += usage.total_tokens

        choice = response.choices[0]
        return choice.message.content or ""

    def count_tokens(self, text: str) -> int:
        return len(text) // 4


_PROVIDERS: dict[str, type] = {
    "anthropic": AnthropicClient,
    "openai": OpenAIClient,
}


def build_client(provider: str) -> LlmClient:
    """Factory: build an LLM client for the given provider name."""
    cls = _PROVIDERS.get(provider)
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. Supported: {', '.join(sorted(_PROVIDERS))}"
        )
    return cls()
