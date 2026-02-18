"""Tests for analyst cost tracking."""

from __future__ import annotations

import pytest

from phantom.analyst.costs import AnalystBudgetExceeded, CostTracker


class TestCostTracker:
    def test_initial_state(self) -> None:
        ct = CostTracker()
        assert ct.total_input_tokens == 0
        assert ct.total_output_tokens == 0
        assert ct.call_count == 0
        assert ct.estimated_cost_usd == 0.0

    def test_record_usage(self) -> None:
        ct = CostTracker()
        ct.record_usage(1000, 500)
        assert ct.total_input_tokens == 1000
        assert ct.total_output_tokens == 500
        assert ct.call_count == 1

    def test_multiple_records(self) -> None:
        ct = CostTracker()
        ct.record_usage(1000, 500)
        ct.record_usage(2000, 300)
        assert ct.total_input_tokens == 3000
        assert ct.total_output_tokens == 800
        assert ct.call_count == 2

    def test_cost_calculation(self) -> None:
        ct = CostTracker()
        ct.record_usage(1_000_000, 0)  # 1M input tokens
        assert ct.estimated_cost_usd == pytest.approx(3.0, rel=0.01)

        ct2 = CostTracker()
        ct2.record_usage(0, 1_000_000)  # 1M output tokens
        assert ct2.estimated_cost_usd == pytest.approx(15.0, rel=0.01)

    def test_check_budget_within_limits(self) -> None:
        ct = CostTracker(max_input_tokens=10_000, max_output_tokens=5_000)
        assert ct.check_budget(5_000, 2_000) is True

    def test_check_budget_input_exceeded(self) -> None:
        ct = CostTracker(max_input_tokens=10_000)
        ct.record_usage(8_000, 0)
        assert ct.check_budget(3_000, 0) is False

    def test_check_budget_output_exceeded(self) -> None:
        ct = CostTracker(max_output_tokens=5_000)
        ct.record_usage(0, 4_000)
        assert ct.check_budget(0, 2_000) is False

    def test_check_budget_cost_exceeded(self) -> None:
        ct = CostTracker(max_cost_usd=0.01)
        # Even small tokens can exceed a tiny budget
        assert ct.check_budget(1_000_000, 1_000_000) is False

    def test_require_budget_passes(self) -> None:
        ct = CostTracker()
        ct.require_budget(1000, 500)  # Should not raise

    def test_require_budget_input_exceeded(self) -> None:
        ct = CostTracker(max_input_tokens=1000)
        with pytest.raises(AnalystBudgetExceeded, match="Input tokens"):
            ct.require_budget(2000, 0)

    def test_require_budget_output_exceeded(self) -> None:
        ct = CostTracker(max_output_tokens=1000)
        with pytest.raises(AnalystBudgetExceeded, match="Output tokens"):
            ct.require_budget(0, 2000)

    def test_require_budget_cost_exceeded(self) -> None:
        ct = CostTracker(
            max_cost_usd=0.001, max_input_tokens=10_000_000, max_output_tokens=10_000_000
        )
        with pytest.raises(AnalystBudgetExceeded, match="cost"):
            ct.require_budget(1_000_000, 1_000_000)

    def test_remaining_tokens(self) -> None:
        ct = CostTracker(max_input_tokens=10_000, max_output_tokens=5_000)
        ct.record_usage(3_000, 1_000)
        assert ct.remaining_input_tokens == 7_000
        assert ct.remaining_output_tokens == 4_000

    def test_remaining_budget(self) -> None:
        ct = CostTracker(max_cost_usd=1.00)
        ct.record_usage(100_000, 10_000)  # Small usage
        assert ct.remaining_budget_usd > 0
        assert ct.remaining_budget_usd < 1.00

    def test_summary(self) -> None:
        ct = CostTracker(max_input_tokens=50_000, max_output_tokens=10_000, max_cost_usd=0.50)
        ct.record_usage(20_000, 3_000)
        s = ct.summary()
        assert s["total_input_tokens"] == 20_000
        assert s["total_output_tokens"] == 3_000
        assert s["call_count"] == 1
        assert isinstance(s["estimated_cost_usd"], float)
        assert s["remaining_input_tokens"] == 30_000
        assert s["remaining_output_tokens"] == 7_000
