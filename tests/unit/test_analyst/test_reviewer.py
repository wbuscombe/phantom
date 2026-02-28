"""Unit tests for the screenshot visual reviewer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from phantom.analyst.reviewer import ReviewReport, ScreenshotReview, ScreenshotReviewer


class TestScreenshotReview:
    def test_valid_review(self) -> None:
        review = ScreenshotReview(
            capture_id="dashboard",
            score=0.9,
            shows_intended_content=True,
            issues=[],
            suggestions=["Increase contrast"],
        )
        assert review.capture_id == "dashboard"
        assert review.score == 0.9
        assert len(review.suggestions) == 1

    def test_score_bounds(self) -> None:
        # Score must be 0.0-1.0
        with pytest.raises(ValueError):
            ScreenshotReview(capture_id="x", score=1.5)
        with pytest.raises(ValueError):
            ScreenshotReview(capture_id="x", score=-0.1)


class TestReviewReport:
    def test_empty_report(self) -> None:
        report = ReviewReport()
        assert report.reviews == []
        assert report.overall_score == 0.0
        assert report.summary == ""
        assert report.cost_usd == 0.0

    def test_report_with_reviews(self) -> None:
        report = ReviewReport(
            reviews=[
                ScreenshotReview(capture_id="a", score=0.8),
                ScreenshotReview(capture_id="b", score=0.6),
            ],
            overall_score=0.7,
            summary="Mixed quality",
            cost_usd=0.05,
        )
        assert len(report.reviews) == 2
        assert report.cost_usd == 0.05


class TestScreenshotReviewer:
    def test_review_empty_screenshots(self) -> None:
        reviewer = ScreenshotReviewer(provider=MagicMock())
        import asyncio

        report = asyncio.get_event_loop().run_until_complete(reviewer.review({}))
        assert "No screenshots" in report.summary

    def test_review_missing_files(self, tmp_path: Path) -> None:
        reviewer = ScreenshotReviewer(provider=MagicMock())
        import asyncio

        report = asyncio.get_event_loop().run_until_complete(
            reviewer.review({"missing": tmp_path / "nonexistent.png"})
        )
        assert "No valid screenshots" in report.summary

    def test_parse_review_valid_json(self) -> None:
        reviewer = ScreenshotReviewer(provider=MagicMock())
        result = reviewer._parse_review(
            '{"reviews": [{"capture_id": "test", "score": 0.9}], '
            '"overall_score": 0.9, "summary": "Good"}',
            ["test"],
            0.05,
        )
        assert len(result.reviews) == 1
        assert result.reviews[0].capture_id == "test"
        assert result.overall_score == 0.9
        assert result.cost_usd == 0.05

    def test_parse_review_with_code_fences(self) -> None:
        reviewer = ScreenshotReviewer(provider=MagicMock())
        result = reviewer._parse_review(
            '```json\n{"reviews": [{"capture_id": "x", "score": 0.5}], '
            '"overall_score": 0.5, "summary": "OK"}\n```',
            ["x"],
            0.02,
        )
        assert len(result.reviews) == 1

    def test_parse_review_invalid_json(self) -> None:
        reviewer = ScreenshotReviewer(provider=MagicMock())
        result = reviewer._parse_review("not json at all", ["test"], 0.01)
        assert "Failed to parse" in result.summary
        assert len(result.reviews) == 1
        assert result.reviews[0].score == 0.5
