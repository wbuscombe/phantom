"""Cost tracking and budget enforcement for Analyst API calls."""

from __future__ import annotations

from dataclasses import dataclass, field

from phantom.exceptions import PhantomError

# Claude Sonnet pricing (per million tokens)
_INPUT_COST_PER_MTOK = 3.0
_OUTPUT_COST_PER_MTOK = 15.0


class AnalystBudgetExceeded(PhantomError):  # noqa: N818
    """Raised when an API call would exceed the configured budget."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Analyst budget exceeded: {detail}")


@dataclass
class CostTracker:
    """Tracks API token usage and enforces budget limits."""

    max_input_tokens: int = 50_000
    max_output_tokens: int = 10_000
    max_cost_usd: float = 0.50

    total_input_tokens: int = field(default=0, init=False)
    total_output_tokens: int = field(default=0, init=False)
    call_count: int = field(default=0, init=False)

    @property
    def estimated_cost_usd(self) -> float:
        """Calculate the estimated cost so far."""
        input_cost = (self.total_input_tokens / 1_000_000) * _INPUT_COST_PER_MTOK
        output_cost = (self.total_output_tokens / 1_000_000) * _OUTPUT_COST_PER_MTOK
        return input_cost + output_cost

    @property
    def remaining_input_tokens(self) -> int:
        return max(0, self.max_input_tokens - self.total_input_tokens)

    @property
    def remaining_output_tokens(self) -> int:
        return max(0, self.max_output_tokens - self.total_output_tokens)

    @property
    def remaining_budget_usd(self) -> float:
        return max(0.0, self.max_cost_usd - self.estimated_cost_usd)

    def check_budget(self, estimated_input: int = 0, estimated_output: int = 0) -> bool:
        """Check whether a call with the given token estimates would stay within budget.

        Returns True if the call is within budget, False otherwise.
        """
        if self.total_input_tokens + estimated_input > self.max_input_tokens:
            return False
        if self.total_output_tokens + estimated_output > self.max_output_tokens:
            return False
        # Estimate cost of the new call
        new_input_cost = (
            (self.total_input_tokens + estimated_input) / 1_000_000
        ) * _INPUT_COST_PER_MTOK
        new_output_cost = (
            (self.total_output_tokens + estimated_output) / 1_000_000
        ) * _OUTPUT_COST_PER_MTOK
        return not new_input_cost + new_output_cost > self.max_cost_usd

    def require_budget(self, estimated_input: int = 0, estimated_output: int = 0) -> None:
        """Raise AnalystBudgetExceeded if the call would exceed budget."""
        if self.total_input_tokens + estimated_input > self.max_input_tokens:
            raise AnalystBudgetExceeded(
                f"Input tokens would reach {self.total_input_tokens + estimated_input}, "
                f"limit is {self.max_input_tokens}"
            )
        if self.total_output_tokens + estimated_output > self.max_output_tokens:
            raise AnalystBudgetExceeded(
                f"Output tokens would reach {self.total_output_tokens + estimated_output}, "
                f"limit is {self.max_output_tokens}"
            )
        new_input_cost = (
            (self.total_input_tokens + estimated_input) / 1_000_000
        ) * _INPUT_COST_PER_MTOK
        new_output_cost = (
            (self.total_output_tokens + estimated_output) / 1_000_000
        ) * _OUTPUT_COST_PER_MTOK
        total_cost = new_input_cost + new_output_cost
        if total_cost > self.max_cost_usd:
            raise AnalystBudgetExceeded(
                f"Estimated cost ${total_cost:.4f} would exceed limit ${self.max_cost_usd:.2f}"
            )

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Record token usage after an API call."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.call_count += 1

    def summary(self) -> dict[str, object]:
        """Return a summary of usage and remaining budget."""
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "call_count": self.call_count,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "remaining_input_tokens": self.remaining_input_tokens,
            "remaining_output_tokens": self.remaining_output_tokens,
            "remaining_budget_usd": round(self.remaining_budget_usd, 4),
        }
