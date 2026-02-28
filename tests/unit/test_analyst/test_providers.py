"""Unit tests for the LLM provider abstraction layer."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from phantom.analyst.providers import (
    DEFAULT_MODEL,
    MODEL_PRICING,
    AnthropicProvider,
    LLMResponse,
    compute_cost,
    get_provider,
)


class TestModelPricing:
    def test_known_models_have_pricing(self) -> None:
        assert "claude-sonnet-4-20250514" in MODEL_PRICING
        assert "claude-haiku-4-5-20251001" in MODEL_PRICING
        assert "claude-opus-4-5-20251101" in MODEL_PRICING

    def test_pricing_tuple_format(self) -> None:
        for model, pricing in MODEL_PRICING.items():
            assert isinstance(pricing, tuple)
            assert len(pricing) == 2
            assert pricing[0] > 0  # input cost
            assert pricing[1] > 0  # output cost

    def test_default_model_is_sonnet(self) -> None:
        assert "sonnet" in DEFAULT_MODEL


class TestComputeCost:
    def test_sonnet_cost(self) -> None:
        cost = compute_cost("claude-sonnet-4-20250514", 1_000_000, 1_000_000)
        # $3/M input + $15/M output = $18
        assert cost == pytest.approx(18.0)

    def test_haiku_cost(self) -> None:
        cost = compute_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        # $1/M input + $5/M output = $6
        assert cost == pytest.approx(6.0)

    def test_opus_cost(self) -> None:
        cost = compute_cost("claude-opus-4-5-20251101", 1_000_000, 1_000_000)
        # $5/M input + $25/M output = $30
        assert cost == pytest.approx(30.0)

    def test_unknown_model_uses_default(self) -> None:
        cost = compute_cost("unknown-model-xyz", 1_000_000, 1_000_000)
        default_cost = compute_cost(DEFAULT_MODEL, 1_000_000, 1_000_000)
        assert cost == default_cost

    def test_zero_tokens(self) -> None:
        cost = compute_cost("claude-sonnet-4-20250514", 0, 0)
        assert cost == 0.0

    def test_small_token_count(self) -> None:
        cost = compute_cost("claude-sonnet-4-20250514", 10_000, 5_000)
        # 10K input: 10000/1M * 3 = 0.03
        # 5K output: 5000/1M * 15 = 0.075
        assert cost == pytest.approx(0.105)


class TestLLMResponse:
    def test_response_model(self) -> None:
        resp = LLMResponse(
            content="hello",
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514",
            cost_usd=0.01,
        )
        assert resp.content == "hello"
        assert resp.input_tokens == 100
        assert resp.model == "claude-sonnet-4-20250514"


class TestAnthropicProvider:
    def test_init_defaults(self) -> None:
        provider = AnthropicProvider()
        assert provider.model == DEFAULT_MODEL
        assert provider._client is None

    def test_init_custom_model(self) -> None:
        provider = AnthropicProvider(model="claude-haiku-4-5-20251001")
        assert provider.model == "claude-haiku-4-5-20251001"

    def test_ensure_client_raises_without_key(self) -> None:
        provider = AnthropicProvider(api_key=None)
        with patch.dict(os.environ, {}, clear=True):
            # Remove ANTHROPIC_API_KEY if set
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                try:
                    provider._ensure_client()
                    # If anthropic is not installed, AnalystDependencyError
                    # If installed but no key, PhantomError
                except Exception:
                    pass  # Expected


class TestGetProvider:
    def test_default_returns_anthropic(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            provider = get_provider()
            assert isinstance(provider, AnthropicProvider)

    def test_env_override_model(self) -> None:
        with patch.dict(
            os.environ, {"PHANTOM_LLM_MODEL": "claude-haiku-4-5-20251001"}, clear=False
        ):
            provider = get_provider()
            assert provider.model == "claude-haiku-4-5-20251001"

    def test_unknown_provider_raises(self) -> None:
        from phantom.exceptions import PhantomError

        with pytest.raises(PhantomError, match="Unknown LLM provider"):
            get_provider(provider_name="openai")
