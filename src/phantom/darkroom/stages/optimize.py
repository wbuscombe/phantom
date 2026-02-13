"""Image optimization stage — lossy and lossless compression.

Pipeline:
1. pngquant (lossy, ~40-70% size reduction, preserves visual quality)
2. oxipng (lossless recompression of the pngquant output)
3. Optional WebP conversion

Both tools are invoked as subprocesses. If unavailable, the stage
logs a warning and passes through unchanged.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import structlog

from phantom.darkroom.base import DarkroomStage, StageResult
from phantom.utils.process import run_command

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()


class OptimizeStage(DarkroomStage):
    @property
    def name(self) -> str:
        return "optimize"

    async def process(self, image_path: Path, config: dict[str, object]) -> StageResult:
        if not config.get("optimize", True):
            return StageResult(output_path=image_path, changed=False)

        target_format = str(config.get("format", "png"))
        original_size = image_path.stat().st_size
        optimized = False

        try:
            if target_format == "png":
                optimized = await self._optimize_png(image_path)
            elif target_format == "webp":
                new_path = await self._convert_webp(image_path)
                if new_path:
                    return StageResult(
                        output_path=new_path,
                        metadata={
                            "original_size": original_size,
                            "optimized_size": new_path.stat().st_size,
                            "format": "webp",
                        },
                    )

            final_size = image_path.stat().st_size
            reduction = (
                ((original_size - final_size) / original_size * 100) if original_size > 0 else 0
            )

            if optimized:
                logger.debug(
                    "optimize_complete",
                    original_bytes=original_size,
                    optimized_bytes=final_size,
                    reduction_pct=round(reduction, 1),
                )

            return StageResult(
                output_path=image_path,
                changed=optimized,
                metadata={
                    "original_size": original_size,
                    "optimized_size": final_size,
                    "reduction_pct": round(reduction, 1),
                },
            )

        except Exception as e:
            logger.warning("optimize_failed", error=str(e))
            return StageResult(output_path=image_path, changed=False)

    async def _optimize_png(self, image_path: Path) -> bool:
        """Run pngquant (lossy) then oxipng (lossless) on a PNG."""
        optimized = False

        # pngquant: lossy compression
        if shutil.which("pngquant"):
            result = await run_command(
                "pngquant",
                "--force",
                "--strip",
                "--quality",
                "65-90",
                "--speed",
                "3",
                "--output",
                str(image_path),
                str(image_path),
                timeout=30,
            )
            if result.returncode == 0:
                optimized = True
            elif result.returncode == 99:
                # pngquant returns 99 when quality target can't be met
                # (image already small enough). Not an error.
                logger.debug("pngquant_quality_skip", path=str(image_path))
            else:
                logger.warning("pngquant_failed", stderr=result.stderr[:200])
        else:
            logger.debug("pngquant_not_found")

        # oxipng: lossless recompression
        if shutil.which("oxipng"):
            result = await run_command(
                "oxipng",
                "--opt",
                "3",
                "--strip",
                "safe",
                "--quiet",
                str(image_path),
                timeout=30,
            )
            if result.returncode == 0:
                optimized = True
            else:
                logger.warning("oxipng_failed", stderr=result.stderr[:200])
        else:
            logger.debug("oxipng_not_found")

        return optimized

    async def _convert_webp(self, image_path: Path) -> Path | None:
        """Convert PNG to WebP using Pillow."""
        from PIL import Image

        try:
            img = Image.open(image_path)
            webp_path = image_path.with_suffix(".webp")
            img.save(webp_path, "WEBP", quality=85, method=6)
            logger.debug(
                "webp_converted",
                original=str(image_path),
                webp=str(webp_path),
            )
            return webp_path
        except Exception as e:
            logger.warning("webp_conversion_failed", error=str(e))
            return None
