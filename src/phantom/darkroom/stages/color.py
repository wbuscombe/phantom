"""Color space normalization stage.

Converts images to sRGB color space for consistent rendering across browsers.
Images already in sRGB (or with no embedded profile) pass through unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from PIL import Image, ImageCms

from phantom.darkroom.base import DarkroomStage, StageResult

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()

# Create sRGB profile once
_SRGB_PROFILE = ImageCms.createProfile("sRGB")


class ColorNormalizeStage(DarkroomStage):
    @property
    def name(self) -> str:
        return "color_normalize"

    async def process(self, image_path: Path, config: dict[str, object]) -> StageResult:
        try:
            img = Image.open(image_path)
            icc_profile = img.info.get("icc_profile")

            if icc_profile:
                try:
                    src_profile = ImageCms.ImageCmsProfile(
                        ImageCms.getOpenProfile(__import__("io").BytesIO(icc_profile))
                    )
                    dst_profile = ImageCms.ImageCmsProfile(_SRGB_PROFILE)

                    # Check if already sRGB
                    src_desc = ImageCms.getProfileDescription(src_profile)
                    if "srgb" in src_desc.lower():
                        logger.debug("color_already_srgb", path=str(image_path))
                        return StageResult(output_path=image_path, changed=False)

                    # Convert to sRGB
                    converted = ImageCms.profileToProfile(
                        img,
                        src_profile,
                        dst_profile,
                        outputMode="RGBA" if img.mode == "RGBA" else "RGB",
                    )
                    if converted is not None:
                        converted.save(image_path)
                    logger.info("color_converted", path=str(image_path), from_profile=src_desc)
                    return StageResult(output_path=image_path)

                except (ImageCms.PyCMSError, OSError) as e:
                    logger.warning("color_profile_error", error=str(e))
                    return StageResult(output_path=image_path, changed=False)

            return StageResult(output_path=image_path, changed=False)

        except Exception as e:
            logger.warning("color_normalize_failed", error=str(e))
            return StageResult(output_path=image_path, changed=False)
