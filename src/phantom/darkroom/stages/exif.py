"""EXIF and metadata stripping stage.

Removes all metadata (EXIF, XMP, IPTC, comments) from screenshots.
Reduces file size by 1-5 KB and prevents information leakage
(software version, timestamps, GPS data).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from PIL import Image

from phantom.darkroom.base import DarkroomStage, StageResult

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()


class ExifStripStage(DarkroomStage):
    @property
    def name(self) -> str:
        return "exif_strip"

    async def process(self, image_path: Path, config: dict[str, object]) -> StageResult:
        try:
            img = Image.open(image_path)

            # Check if there's any metadata to strip
            has_exif = "exif" in img.info
            has_icc = "icc_profile" in img.info
            has_other = bool(set(img.info.keys()) - {"exif", "icc_profile"})

            if not has_exif and not has_other:
                return StageResult(output_path=image_path, changed=False)

            # Create a clean copy with no metadata
            clean = Image.new(img.mode, img.size)
            clean.putdata(list(img.getdata()))

            # Preserve only the sRGB ICC profile if present
            if has_icc:
                clean.save(image_path, icc_profile=img.info["icc_profile"])
            else:
                clean.save(image_path)

            stripped = []
            if has_exif:
                stripped.append("exif")
            if has_other:
                stripped.append("other_metadata")

            logger.debug("exif_stripped", path=str(image_path), stripped=stripped)
            return StageResult(
                output_path=image_path,
                metadata={"stripped": stripped},
            )

        except Exception as e:
            logger.warning("exif_strip_failed", error=str(e))
            return StageResult(output_path=image_path, changed=False)
