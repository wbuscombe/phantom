"""Screenshot visual review via vision API.

After captures complete, optionally sends screenshots to Claude's vision API
for automated quality review.  Off by default — enabled via ``--review`` flag
or ``analyst.review: true`` in the manifest.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

from phantom.analyst.providers import AnthropicProvider, get_provider

if TYPE_CHECKING:
    from pathlib import Path

    from phantom.analyst.costs import CostTracker

logger = structlog.get_logger()

# Hard budget ceiling for a review call
_REVIEW_BUDGET_USD = 0.30


class ScreenshotReview(BaseModel):
    """Per-screenshot quality assessment."""

    capture_id: str
    score: float = Field(ge=0.0, le=1.0)
    shows_intended_content: bool = True
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ReviewReport(BaseModel):
    """Aggregated review report across all screenshots."""

    reviews: list[ScreenshotReview] = Field(default_factory=list)
    overall_score: float = 0.0
    summary: str = ""
    cost_usd: float = 0.0


class ScreenshotReviewer:
    """Reviews captured screenshots via vision API."""

    def __init__(
        self,
        provider: AnthropicProvider | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self._provider = provider or get_provider()
        self._cost_tracker = cost_tracker

    async def review(
        self,
        screenshots: dict[str, Path],
        capture_descriptions: dict[str, str] | None = None,
    ) -> ReviewReport:
        """Review screenshots by sending them as images to the vision API.

        Args:
            screenshots: Mapping of capture_id → screenshot file path.
            capture_descriptions: Optional mapping of capture_id → what the
                capture is supposed to show.

        Returns:
            ``ReviewReport`` with per-screenshot scores and aggregate summary.
        """
        if not screenshots:
            return ReviewReport(summary="No screenshots to review.")

        # Build image content blocks
        image_blocks: list[dict[str, Any]] = []
        capture_ids: list[str] = []

        for capture_id, path in screenshots.items():
            if not path.exists():
                continue

            data = path.read_bytes()
            b64 = base64.standard_b64encode(data).decode("ascii")
            image_blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                }
            )
            desc = ""
            if capture_descriptions and capture_id in capture_descriptions:
                desc = f" — intended to show: {capture_descriptions[capture_id]}"
            image_blocks.append(
                {
                    "type": "text",
                    "text": f"Screenshot: {capture_id}{desc}",
                }
            )
            capture_ids.append(capture_id)

        if not capture_ids:
            return ReviewReport(summary="No valid screenshots found to review.")

        # Build the prompt
        system_prompt = (
            "You are a documentation screenshot quality reviewer. "
            "For each screenshot, evaluate:\n"
            "1. Is the content visible and readable?\n"
            "2. Are there UI artifacts (loading spinners, error messages, blank areas)?\n"
            "3. Is this a good documentation screenshot?\n"
            "4. What score (0.0-1.0) would you give it?\n\n"
            "Respond with a JSON object:\n"
            '{"reviews": [{"capture_id": "...", "score": 0.9, '
            '"shows_intended_content": true, '
            '"issues": ["..."], "suggestions": ["..."]}, ...], '
            '"overall_score": 0.85, '
            '"summary": "Brief summary of all screenshots"}'
        )

        messages = [{"role": "user", "content": image_blocks}]

        try:
            # Use the provider's underlying client directly for vision
            # since the protocol doesn't support multimodal content
            client = self._provider._ensure_client()

            response = client.messages.create(
                model=self._provider.model,
                max_tokens=2048,
                system=system_prompt,
                messages=messages,
            )

            if self._cost_tracker:
                self._cost_tracker.record_usage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )

            from phantom.analyst.providers import compute_cost

            cost = compute_cost(
                self._provider.model,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )

            raw_text = response.content[0].text
            return self._parse_review(raw_text, capture_ids, cost)

        except Exception as e:
            logger.warning("review_failed", error=str(e))
            return ReviewReport(
                summary=f"Review failed: {e}",
                reviews=[ScreenshotReview(capture_id=cid, score=0.5) for cid in capture_ids],
            )

    def _parse_review(self, text: str, capture_ids: list[str], cost: float) -> ReviewReport:
        """Parse the vision API response into a ReviewReport."""
        import json

        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.index("\n")
            cleaned = cleaned[first_nl + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("review_parse_failed", text_preview=cleaned[:200])
            return ReviewReport(
                summary="Failed to parse review response.",
                cost_usd=cost,
                reviews=[ScreenshotReview(capture_id=cid, score=0.5) for cid in capture_ids],
            )

        reviews = []
        for rev_data in data.get("reviews", []):
            try:
                reviews.append(ScreenshotReview.model_validate(rev_data))
            except Exception:
                continue

        overall = data.get("overall_score", 0.0)
        summary = data.get("summary", "")

        return ReviewReport(
            reviews=reviews,
            overall_score=float(overall),
            summary=str(summary),
            cost_usd=cost,
        )
