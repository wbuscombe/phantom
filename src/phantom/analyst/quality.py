"""Post-capture screenshot quality validation.

Uses PIL and numpy only — no API calls. Validates screenshots for common
issues: blank images, low entropy, bad dimensions, transparency, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

from phantom.analyst.models import ConsistencyReport, QualityIssue, QualityReport

logger = structlog.get_logger()

# Thresholds
MIN_FILE_SIZE_KB = 5
MAX_FILE_SIZE_KB = 5_000
MIN_ENTROPY = 1.0
MIN_DIMENSIONS = 100
MAX_ASPECT_RATIO = 4.0
MIN_COLOR_COUNT = 10
MAX_TRANSPARENCY_PCT = 50.0
UNIFORMITY_THRESHOLD = 0.99
MAX_SIZE_VARIANCE_PCT = 200.0


class QualityChecker:
    """Validates screenshot quality using PIL and numpy."""

    def check_screenshot(self, path: Path, capture_id: str) -> QualityReport:
        """Run all quality checks on a single screenshot.

        Returns a QualityReport with issues found.
        """
        from PIL import Image

        issues: list[QualityIssue] = []

        # File size check
        file_size_kb = path.stat().st_size / 1024

        if file_size_kb < MIN_FILE_SIZE_KB:
            issues.append(
                QualityIssue(
                    check="file_size",
                    severity="error",
                    message=f"File too small ({file_size_kb:.1f} KB < {MIN_FILE_SIZE_KB} KB)",
                    value=file_size_kb,
                    threshold=MIN_FILE_SIZE_KB,
                )
            )
        elif file_size_kb > MAX_FILE_SIZE_KB:
            issues.append(
                QualityIssue(
                    check="file_size",
                    severity="warning",
                    message=f"File very large ({file_size_kb:.1f} KB > {MAX_FILE_SIZE_KB} KB)",
                    value=file_size_kb,
                    threshold=MAX_FILE_SIZE_KB,
                )
            )

        # Open image
        img = Image.open(path)
        width, height = img.size

        # Dimensions check
        if width < MIN_DIMENSIONS or height < MIN_DIMENSIONS:
            issues.append(
                QualityIssue(
                    check="dimensions",
                    severity="error",
                    message=f"Image too small ({width}x{height}, min {MIN_DIMENSIONS}x{MIN_DIMENSIONS})",
                    value=float(min(width, height)),
                    threshold=float(MIN_DIMENSIONS),
                )
            )

        # Aspect ratio check
        if width > 0 and height > 0:
            ratio = max(width / height, height / width)
            if ratio > MAX_ASPECT_RATIO:
                issues.append(
                    QualityIssue(
                        check="aspect_ratio",
                        severity="warning",
                        message=f"Extreme aspect ratio ({ratio:.1f}:1, max {MAX_ASPECT_RATIO}:1)",
                        value=ratio,
                        threshold=MAX_ASPECT_RATIO,
                    )
                )

        # Blank detection (pixel uniformity)
        uniformity = self._check_uniformity(img)
        if uniformity > UNIFORMITY_THRESHOLD:
            issues.append(
                QualityIssue(
                    check="blank_detection",
                    severity="error",
                    message=f"Image appears blank (uniformity {uniformity:.2%} > {UNIFORMITY_THRESHOLD:.0%})",
                    value=uniformity,
                    threshold=UNIFORMITY_THRESHOLD,
                )
            )

        # Entropy check
        entropy = self._compute_entropy(img)
        if entropy < MIN_ENTROPY:
            issues.append(
                QualityIssue(
                    check="entropy",
                    severity="warning",
                    message=f"Low entropy ({entropy:.2f} < {MIN_ENTROPY})",
                    value=entropy,
                    threshold=MIN_ENTROPY,
                )
            )

        # Color variety check
        color_count = self._count_colors(img)
        if color_count < MIN_COLOR_COUNT:
            issues.append(
                QualityIssue(
                    check="color_variety",
                    severity="warning",
                    message=f"Low color variety ({color_count} < {MIN_COLOR_COUNT} distinct colors)",
                    value=float(color_count),
                    threshold=float(MIN_COLOR_COUNT),
                )
            )

        # Transparency check
        if img.mode == "RGBA":
            transparency_pct = self._check_transparency(img)
            if transparency_pct > MAX_TRANSPARENCY_PCT:
                issues.append(
                    QualityIssue(
                        check="transparency",
                        severity="warning",
                        message=f"High transparency ({transparency_pct:.1f}% > {MAX_TRANSPARENCY_PCT}%)",
                        value=transparency_pct,
                        threshold=MAX_TRANSPARENCY_PCT,
                    )
                )

        passed = not any(i.severity == "error" for i in issues)

        return QualityReport(
            capture_id=capture_id,
            passed=passed,
            issues=issues,
            file_size_kb=file_size_kb,
            width=width,
            height=height,
            entropy=entropy,
            color_count=color_count,
        )

    def check_consistency(self, reports: list[QualityReport]) -> ConsistencyReport:
        """Check consistency across multiple screenshot reports."""
        if not reports:
            return ConsistencyReport(passed=True, screenshot_count=0)

        issues: list[QualityIssue] = []
        sizes = [r.file_size_kb for r in reports]
        avg_size = sum(sizes) / len(sizes)
        ratios = [r.width / r.height for r in reports if r.height > 0]

        # Size variance
        if avg_size > 0:
            max_deviation = max(abs(s - avg_size) for s in sizes)
            size_variance_pct = (max_deviation / avg_size) * 100
        else:
            size_variance_pct = 0.0

        if size_variance_pct > MAX_SIZE_VARIANCE_PCT:
            issues.append(
                QualityIssue(
                    check="size_variance",
                    severity="warning",
                    message=f"Large file size variance ({size_variance_pct:.0f}% > {MAX_SIZE_VARIANCE_PCT:.0f}%)",
                    value=size_variance_pct,
                    threshold=MAX_SIZE_VARIANCE_PCT,
                )
            )

        # Aspect ratio consistency
        aspect_consistent = True
        if len(ratios) >= 2:
            min_ratio = min(ratios)
            max_ratio = max(ratios)
            if max_ratio > 0 and (max_ratio - min_ratio) / max_ratio > 0.5:
                aspect_consistent = False
                issues.append(
                    QualityIssue(
                        check="aspect_ratio_consistency",
                        severity="warning",
                        message=f"Inconsistent aspect ratios (range {min_ratio:.2f} to {max_ratio:.2f})",
                        value=max_ratio - min_ratio,
                        threshold=0.5,
                    )
                )

        passed = not any(i.severity == "error" for i in issues)

        return ConsistencyReport(
            passed=passed,
            issues=issues,
            screenshot_count=len(reports),
            avg_file_size_kb=avg_size,
            size_variance_pct=size_variance_pct,
            aspect_ratio_consistent=aspect_consistent,
        )

    @staticmethod
    def _check_uniformity(img: object) -> float:
        """Check pixel uniformity — returns fraction of pixels matching the mode."""
        import numpy as np
        from PIL import Image

        assert isinstance(img, Image.Image)
        arr = np.array(img.convert("L"))  # Convert to grayscale
        total = arr.size
        if total == 0:
            return 1.0
        # Count most common pixel value
        _values, counts = np.unique(arr, return_counts=True)
        max_count = int(counts.max())
        return max_count / total

    @staticmethod
    def _compute_entropy(img: object) -> float:
        """Compute Shannon entropy of the grayscale histogram."""
        import numpy as np
        from PIL import Image

        assert isinstance(img, Image.Image)
        arr = np.array(img.convert("L"))
        hist, _ = np.histogram(arr.flatten(), bins=256, range=(0, 256))
        total = hist.sum()
        if total == 0:
            return 0.0

        probs = hist[hist > 0] / total
        return float(-np.sum(probs * np.log2(probs)))

    @staticmethod
    def _count_colors(img: object) -> int:
        """Count distinct colors in the image."""
        from PIL import Image

        assert isinstance(img, Image.Image)
        # Use getcolors with a reasonable limit; returns None if exceeded
        rgb = img.convert("RGB")
        colors = rgb.getcolors(maxcolors=10000)
        if colors is None:
            return 10000  # More than our max — plenty of variety
        return len(colors)

    @staticmethod
    def _check_transparency(img: object) -> float:
        """Check percentage of fully transparent pixels in an RGBA image."""
        import numpy as np
        from PIL import Image

        assert isinstance(img, Image.Image)
        if img.mode != "RGBA":
            return 0.0
        arr = np.array(img)
        alpha = arr[:, :, 3]
        total = alpha.size
        if total == 0:
            return 0.0
        transparent = int(np.sum(alpha == 0))
        return (transparent / total) * 100
