"""Darkroom pipeline orchestrator.

Runs raw screenshots through a sequence of processing stages:
    Color Normalize → EXIF Strip → Crop → Resize → Border/Shadow → Optimize → Diff

Each stage is independently testable and gracefully degrades (no stage
failure halts the pipeline — the image passes through unchanged).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from phantom.darkroom.stages.border import BorderStage
from phantom.darkroom.stages.color import ColorNormalizeStage
from phantom.darkroom.stages.crop import CropStage
from phantom.darkroom.stages.diff import DiffStage
from phantom.darkroom.stages.exif import ExifStripStage
from phantom.darkroom.stages.optimize import OptimizeStage
from phantom.darkroom.stages.resize import ResizeStage

if TYPE_CHECKING:
    from pathlib import Path

    from phantom.darkroom.base import StageResult
    from phantom.models import ProcessingConfig

logger = structlog.get_logger()


@dataclass
class PipelineResult:
    """Result of processing a single screenshot through the full pipeline."""

    capture_id: str
    input_path: Path
    output_path: Path
    changed: bool  # From diff stage — should this be published?
    stage_results: dict[str, StageResult] = field(default_factory=dict)
    error: str | None = None


class DarkroomPipeline:
    """Orchestrates the image processing pipeline for captured screenshots."""

    def __init__(self) -> None:
        self._stages = [
            ColorNormalizeStage(),
            ExifStripStage(),
            CropStage(),
            ResizeStage(),
            BorderStage(),
            OptimizeStage(),
            DiffStage(),
        ]

    async def process(
        self,
        capture_id: str,
        raw_path: Path,
        output_dir: Path,
        processing_config: ProcessingConfig,
        previous_path: Path | None = None,
    ) -> PipelineResult:
        """Process a single raw screenshot through all pipeline stages.

        Args:
            capture_id: Identifier for the capture (used in filenames).
            raw_path: Path to the raw screenshot from the runner.
            output_dir: Directory to write the processed result.
            processing_config: Processing configuration from the manifest.
            previous_path: Path to the previous version for diff comparison.

        Returns:
            PipelineResult with the output path and diff status.
        """
        # Copy raw to output dir for processing (don't modify the raw file)
        working_path = output_dir / raw_path.name
        shutil.copy2(raw_path, working_path)

        logger.info("pipeline_start", capture_id=capture_id)

        # Build config dict for stages
        config = self._build_config(processing_config, previous_path)

        stage_results: dict[str, StageResult] = {}
        changed = True  # Default: publish unless diff says otherwise

        for stage in self._stages:
            result = await stage.process(working_path, config)
            stage_results[stage.name] = result

            # Track the working path (some stages may change it, e.g., WebP conversion)
            working_path = result.output_path

            # The diff stage determines the final changed status
            if stage.name == "diff":
                changed = result.changed

            logger.debug(
                "stage_complete",
                stage=stage.name,
                changed=result.changed,
                capture_id=capture_id,
            )

        logger.info(
            "pipeline_complete",
            capture_id=capture_id,
            changed=changed,
            output=str(working_path),
        )

        return PipelineResult(
            capture_id=capture_id,
            input_path=raw_path,
            output_path=working_path,
            changed=changed,
            stage_results=stage_results,
        )

    async def process_batch(
        self,
        captures: list[dict[str, object]],
        output_dir: Path,
        processing_config: ProcessingConfig,
    ) -> list[PipelineResult]:
        """Process multiple screenshots through the pipeline.

        Args:
            captures: List of dicts with "capture_id", "raw_path",
                      and optional "previous_path".
            output_dir: Directory to write processed results.
            processing_config: Processing configuration from the manifest.

        Returns:
            List of PipelineResult for each capture.
        """
        from pathlib import Path as PathCls

        results: list[PipelineResult] = []

        for capture_info in captures:
            capture_id = str(capture_info["capture_id"])
            raw_path = PathCls(str(capture_info["raw_path"]))
            raw_previous_path = capture_info.get("previous_path")
            prev_path: Path | None = PathCls(str(raw_previous_path)) if raw_previous_path else None

            result = await self.process(
                capture_id=capture_id,
                raw_path=raw_path,
                output_dir=output_dir,
                processing_config=processing_config,
                previous_path=prev_path,
            )
            results.append(result)

        return results

    @staticmethod
    def _build_config(
        processing_config: ProcessingConfig,
        previous_path: Path | None,
    ) -> dict[str, object]:
        """Build the config dict passed to each stage."""
        border_dict: dict[str, object] = {
            "style": processing_config.border.style,
            "shadow_color": processing_config.border.shadow_color,
            "shadow_offset": {
                "x": processing_config.border.shadow_offset.x,
                "y": processing_config.border.shadow_offset.y,
            },
            "shadow_blur": processing_config.border.shadow_blur,
            "padding": processing_config.border.padding,
            "background": processing_config.border.background,
            "corner_radius": processing_config.border.corner_radius,
        }

        diff_dict: dict[str, object] = {
            "enabled": processing_config.diff.enabled,
            "threshold": processing_config.diff.threshold,
            "algorithm": processing_config.diff.algorithm,
            "ignore_regions": [
                {"x": r.x, "y": r.y, "width": r.width, "height": r.height}
                for r in processing_config.diff.ignore_regions
            ],
        }

        return {
            "format": processing_config.format,
            "optimize": processing_config.optimize,
            "max_width": processing_config.max_width,
            "border": border_dict,
            "diff": diff_dict,
            "_previous_path": str(previous_path) if previous_path else None,
        }
