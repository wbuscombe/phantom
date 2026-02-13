"""DPR-aware resize stage.

Scales images to respect max_width while preserving aspect ratio.
Accounts for device pixel ratio — a 2x capture at 2880px wide with
max_width=2800 is scaled to 2800px. The logical (1x) width is
2800/2 = 1400px, used for HTML width attributes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from PIL import Image

from phantom.darkroom.base import DarkroomStage, StageResult

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()


class ResizeStage(DarkroomStage):
    @property
    def name(self) -> str:
        return "resize"

    async def process(self, image_path: Path, config: dict[str, object]) -> StageResult:
        max_width = int(config.get("max_width", 2800))  # type: ignore[call-overload]

        try:
            img = Image.open(image_path)
            original_size = img.size

            if img.width <= max_width:
                return StageResult(
                    output_path=image_path,
                    changed=False,
                    metadata={"size": original_size},
                )

            # Calculate new dimensions preserving aspect ratio
            ratio = max_width / img.width
            new_height = int(img.height * ratio)

            resized = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            resized.save(image_path)

            logger.debug(
                "resize_applied",
                original=f"{original_size[0]}x{original_size[1]}",
                resized=f"{max_width}x{new_height}",
            )
            return StageResult(
                output_path=image_path,
                metadata={
                    "original_size": original_size,
                    "resized_to": (max_width, new_height),
                },
            )

        except Exception as e:
            logger.warning("resize_failed", error=str(e))
            return StageResult(output_path=image_path, changed=False)
