"""Perceptual diff stage — compare current screenshot against previous version.

Uses SSIM (Structural Similarity Index) from scikit-image by default (ADR-013).
Returns whether the image has changed meaningfully based on a configurable threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import structlog
from PIL import Image
from skimage.metrics import structural_similarity as ssim

from phantom.darkroom.base import DarkroomStage, StageResult

if TYPE_CHECKING:
    from pathlib import Path

    from phantom.models import Region

logger = structlog.get_logger()


@dataclass
class DiffResult:
    """Result of a perceptual diff comparison."""

    changed: bool
    similarity: float
    diff_pct: float


def compute_ssim_diff(
    current_path: Path,
    previous_path: Path,
    threshold: float = 0.95,
    ignore_regions: list[Region] | None = None,
) -> DiffResult:
    """Compare two images using SSIM.

    Args:
        current_path: Path to the current screenshot.
        previous_path: Path to the previous screenshot.
        threshold: Minimum SSIM similarity to consider unchanged (0-1).
                   Default 0.95 means <5% structural difference = unchanged.
        ignore_regions: Regions to mask before comparison (for volatile content).

    Returns:
        DiffResult with changed flag, similarity score, and diff percentage.
    """
    img_a = np.array(Image.open(current_path).convert("RGB"))
    img_b = np.array(Image.open(previous_path).convert("RGB"))

    # Resize previous to match current if dimensions changed
    if img_a.shape != img_b.shape:
        img_b_pil = Image.open(previous_path).convert("RGB")
        img_b_pil = img_b_pil.resize((img_a.shape[1], img_a.shape[0]), Image.Resampling.LANCZOS)
        img_b = np.array(img_b_pil)

    # Apply ignore region masks
    if ignore_regions:
        for region in ignore_regions:
            y1, y2 = region.y, region.y + region.height
            x1, x2 = region.x, region.x + region.width
            # Set both images to black in the ignored region
            img_a[y1:y2, x1:x2] = 0
            img_b[y1:y2, x1:x2] = 0

    # Determine appropriate win_size (must be odd and <= smallest image dimension)
    min_dim = min(img_a.shape[0], img_a.shape[1])
    win_size = min(7, min_dim)
    if win_size % 2 == 0:
        win_size -= 1
    if win_size < 3:
        win_size = 3

    similarity = ssim(  # type: ignore[no-untyped-call]
        img_a,
        img_b,
        channel_axis=2,
        win_size=win_size,
    )

    return DiffResult(
        changed=similarity < threshold,
        similarity=float(similarity),
        diff_pct=round((1.0 - similarity) * 100, 2),
    )


class DiffStage(DarkroomStage):
    """Pipeline stage wrapper around compute_ssim_diff.

    Unlike other stages, this stage doesn't modify the image.
    It compares against a previous version and reports whether
    the image has changed. The pipeline uses this to decide
    whether to publish the screenshot.
    """

    @property
    def name(self) -> str:
        return "diff"

    async def process(self, image_path: Path, config: dict[str, object]) -> StageResult:
        diff_config = config.get("diff", {})
        if not isinstance(diff_config, dict):
            return StageResult(output_path=image_path, changed=True)

        if not diff_config.get("enabled", True):
            return StageResult(output_path=image_path, changed=True)

        previous_path = config.get("_previous_path")
        if not previous_path:
            # No previous version — image is new, always "changed"
            logger.debug("diff_no_previous", path=str(image_path))
            return StageResult(
                output_path=image_path,
                changed=True,
                metadata={"reason": "no_previous_version"},
            )

        from pathlib import Path as PathCls

        prev = PathCls(str(previous_path))
        if not prev.exists():
            return StageResult(
                output_path=image_path,
                changed=True,
                metadata={"reason": "previous_not_found"},
            )

        try:
            threshold = float(diff_config.get("threshold", 0.95))

            # Parse ignore regions
            ignore_regions = None
            raw_regions = diff_config.get("ignore_regions")
            if raw_regions:
                from phantom.models import Region

                ignore_regions = [Region(**r) if isinstance(r, dict) else r for r in raw_regions]

            result = compute_ssim_diff(image_path, prev, threshold, ignore_regions)

            logger.info(
                "diff_result",
                capture=image_path.stem,
                similarity=round(result.similarity, 4),
                diff_pct=result.diff_pct,
                changed=result.changed,
                threshold=threshold,
            )

            return StageResult(
                output_path=image_path,
                changed=result.changed,
                metadata={
                    "similarity": result.similarity,
                    "diff_pct": result.diff_pct,
                    "threshold": threshold,
                },
            )

        except Exception as e:
            logger.warning("diff_failed", error=str(e))
            # On diff failure, treat as changed (safe default)
            return StageResult(output_path=image_path, changed=True)
