"""LLM provider abstraction layer.

Decouples the Analyst from any specific LLM vendor. Currently ships with
``AnthropicProvider``; additional providers can be added by implementing
the ``LLMProvider`` protocol.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from phantom.exceptions import AnalystDependencyError, PhantomError

# Per-million-token pricing: (input, output)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-opus-4-5-20251101": (5.0, 25.0),
    # Legacy
    "claude-3-5-sonnet-20241022": (3.0, 15.0),
    "claude-3-5-haiku-20241022": (1.0, 5.0),
}

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class LLMResponse(BaseModel):
    """Standardised response from any LLM provider."""

    content: str
    input_tokens: int
    output_tokens: int
    model: str
    cost_usd: float


@runtime_checkable
class LLMProvider(Protocol):
    """Abstract interface for LLM providers."""

    async def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> LLMResponse:
        """Send a completion request and return the response."""
        ...

    @property
    def model(self) -> str:
        """Return the model identifier."""
        ...


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost from token counts using ``MODEL_PRICING``."""
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        # Fall back to Sonnet pricing for unknown models
        pricing = MODEL_PRICING[DEFAULT_MODEL]
    input_cost = (input_tokens / 1_000_000) * pricing[0]
    output_cost = (output_tokens / 1_000_000) * pricing[1]
    return input_cost + output_cost


class AnthropicProvider:
    """Anthropic Claude provider."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    @property
    def model(self) -> str:
        return self._model

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import anthropic
        except ImportError:
            raise AnalystDependencyError from None

        key = self._api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise PhantomError(
                "No API key provided. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key to AnthropicProvider."
            )
        self._client = anthropic.Anthropic(api_key=key)
        return self._client

    async def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> LLMResponse:
        """Call Claude and return a standardised ``LLMResponse``."""
        client = self._ensure_client()

        response = client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = compute_cost(self._model, input_tokens, output_tokens)

        return LLMResponse(
            content=response.content[0].text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._model,
            cost_usd=cost,
        )


def get_provider(
    provider_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> AnthropicProvider:
    """Factory: return the appropriate provider based on name or env vars.

    Currently only ``"anthropic"`` is supported. The ``PHANTOM_LLM_PROVIDER``
    and ``PHANTOM_LLM_MODEL`` environment variables override arguments.
    """
    provider_name = os.environ.get("PHANTOM_LLM_PROVIDER", provider_name or "anthropic")
    model = os.environ.get("PHANTOM_LLM_MODEL", model or DEFAULT_MODEL)

    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)

    raise PhantomError(f"Unknown LLM provider '{provider_name}'. Supported: anthropic")
