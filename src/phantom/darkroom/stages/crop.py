"""Crop stage — trim or region-crop screenshots.

Supports:
- Manual region crop (x, y, width, height)
- No-op (when crop config is absent or "none")

Auto-crop (detect and trim uniform borders) is deferred to Phase 2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from PIL import Image

from phantom.darkroom.base import DarkroomStage, StageResult

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()


class CropStage(DarkroomStage):
    @property
    def name(self) -> str:
        return "crop"

    async def process(self, image_path: Path, config: dict[str, object]) -> StageResult:
        crop_config = config.get("crop")
        if not crop_config:
            return StageResult(output_path=image_path, changed=False)

        try:
            if isinstance(crop_config, dict):
                x = int(crop_config.get("x", 0))
                y = int(crop_config.get("y", 0))
                width = int(crop_config.get("width", 0))
                height = int(crop_config.get("height", 0))

                if width <= 0 or height <= 0:
                    return StageResult(output_path=image_path, changed=False)

                img = Image.open(image_path)
                original_size = img.size

                # PIL crop box is (left, upper, right, lower)
                box = (x, y, x + width, y + height)

                # Clamp to image bounds
                box = (
                    max(0, box[0]),
                    max(0, box[1]),
                    min(img.width, box[2]),
                    min(img.height, box[3]),
                )

                cropped = img.crop(box)
                cropped.save(image_path)

                logger.debug(
                    "crop_applied",
                    original=f"{original_size[0]}x{original_size[1]}",
                    cropped=f"{cropped.width}x{cropped.height}",
                )
                return StageResult(
                    output_path=image_path,
                    metadata={
                        "original_size": original_size,
                        "cropped_size": (cropped.width, cropped.height),
                    },
                )

            return StageResult(output_path=image_path, changed=False)

        except Exception as e:
            logger.warning("crop_failed", error=str(e))
            return StageResult(output_path=image_path, changed=False)
