"""Integration tests for the full Darkroom pipeline."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from PIL import Image, ImageDraw

from phantom.darkroom.pipeline import DarkroomPipeline
from phantom.models import ProcessingConfig

if TYPE_CHECKING:
    from pathlib import Path


def create_test_screenshot(path: Path, width: int = 1280, height: int = 800) -> Path:
    """Create a realistic-looking test screenshot."""
    img = Image.new("RGB", (width, height), (26, 26, 46))
    draw = ImageDraw.Draw(img)
    # Header bar
    draw.rectangle([0, 0, width, 60], fill=(22, 33, 62))
    # Cards
    for i in range(3):
        x = 24 + i * (width // 3)
        draw.rectangle([x, 80, x + width // 3 - 32, 200], fill=(22, 33, 62))
    # Content area
    draw.rectangle([24, 220, width - 24, height - 24], fill=(22, 33, 62))
    # Accent elements
    draw.rectangle([40, 100, 200, 140], fill=(228, 69, 96))
    draw.ellipse([width - 200, 240, width - 100, 340], fill=(78, 204, 163))
    img.save(path, "PNG")
    return path


class TestFullPipeline:
    """Test the complete pipeline with default settings."""

    @pytest.mark.integration
    def test_pipeline_default_config(self, tmp_path: Path) -> None:
        """Full pipeline with default ProcessingConfig."""
        raw_dir = tmp_path / "raw"
        output_dir = tmp_path / "processed"
        raw_dir.mkdir()
        output_dir.mkdir()

        raw_path = create_test_screenshot(raw_dir / "dashboard.png")
        config = ProcessingConfig()

        pipeline = DarkroomPipeline()
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.process(
                capture_id="dashboard",
                raw_path=raw_path,
                output_dir=output_dir,
                processing_config=config,
            )
        )

        assert result.output_path.exists()
        assert result.changed  # No previous version = changed
        assert result.error is None

        # Output should be larger than input due to shadow padding
        output_img = Image.open(result.output_path)
        assert output_img.width > 1280  # Shadow adds padding
        assert output_img.height > 800
        # pngquant may convert RGBA to palette mode (P) on Linux
        assert output_img.mode in ("RGBA", "P")

    @pytest.mark.integration
    def test_pipeline_no_shadow(self, tmp_path: Path) -> None:
        """Pipeline with border style 'none' preserves original dimensions."""
        raw_dir = tmp_path / "raw"
        output_dir = tmp_path / "processed"
        raw_dir.mkdir()
        output_dir.mkdir()

        raw_path = create_test_screenshot(raw_dir / "clean.png", 800, 600)
        config = ProcessingConfig()
        config.border.style = "none"

        pipeline = DarkroomPipeline()
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.process(
                capture_id="clean",
                raw_path=raw_path,
                output_dir=output_dir,
                processing_config=config,
            )
        )

        output_img = Image.open(result.output_path)
        assert output_img.size == (800, 600)

    @pytest.mark.integration
    def test_pipeline_with_resize(self, tmp_path: Path) -> None:
        """Pipeline resizes images exceeding max_width."""
        raw_dir = tmp_path / "raw"
        output_dir = tmp_path / "processed"
        raw_dir.mkdir()
        output_dir.mkdir()

        # Create a 2x retina capture (2560x1600)
        raw_path = create_test_screenshot(raw_dir / "retina.png", 2560, 1600)
        config = ProcessingConfig()
        config.max_width = 2000
        config.border.style = "none"  # Skip shadow for cleaner size assertion

        pipeline = DarkroomPipeline()
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.process(
                capture_id="retina",
                raw_path=raw_path,
                output_dir=output_dir,
                processing_config=config,
            )
        )

        output_img = Image.open(result.output_path)
        assert output_img.width == 2000
        assert output_img.height == 1250  # 1600 * (2000/2560)

    @pytest.mark.integration
    def test_pipeline_diff_unchanged(self, tmp_path: Path) -> None:
        """Pipeline marks identical images as unchanged."""
        raw_dir = tmp_path / "raw"
        output_dir = tmp_path / "processed"
        prev_dir = tmp_path / "previous"
        raw_dir.mkdir()
        output_dir.mkdir()
        prev_dir.mkdir()

        # Create identical current and previous images
        raw_path = create_test_screenshot(raw_dir / "same.png", 400, 300)
        prev_path = prev_dir / "same.png"
        Image.open(raw_path).save(prev_path)

        config = ProcessingConfig()
        config.border.style = "none"

        pipeline = DarkroomPipeline()
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.process(
                capture_id="same",
                raw_path=raw_path,
                output_dir=output_dir,
                processing_config=config,
                previous_path=prev_path,
            )
        )

        assert not result.changed
        diff_result = result.stage_results.get("diff")
        assert diff_result is not None
        assert diff_result.metadata is not None
        assert diff_result.metadata["similarity"] > 0.99

    @pytest.mark.integration
    def test_pipeline_diff_changed(self, tmp_path: Path) -> None:
        """Pipeline marks significantly different images as changed."""
        raw_dir = tmp_path / "raw"
        output_dir = tmp_path / "processed"
        prev_dir = tmp_path / "previous"
        raw_dir.mkdir()
        output_dir.mkdir()
        prev_dir.mkdir()

        create_test_screenshot(raw_dir / "new.png", 400, 300)
        # Create a very different previous image
        prev_img = Image.new("RGB", (400, 300), (200, 200, 220))
        prev_img.save(prev_dir / "new.png")

        config = ProcessingConfig()
        config.border.style = "none"

        pipeline = DarkroomPipeline()
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.process(
                capture_id="new",
                raw_path=raw_dir / "new.png",
                output_dir=output_dir,
                processing_config=config,
                previous_path=prev_dir / "new.png",
            )
        )

        assert result.changed

    @pytest.mark.integration
    def test_pipeline_raw_not_modified(self, tmp_path: Path) -> None:
        """The raw input file should not be modified by the pipeline."""
        raw_dir = tmp_path / "raw"
        output_dir = tmp_path / "processed"
        raw_dir.mkdir()
        output_dir.mkdir()

        raw_path = create_test_screenshot(raw_dir / "original.png", 400, 300)
        raw_bytes = raw_path.read_bytes()

        config = ProcessingConfig()
        pipeline = DarkroomPipeline()
        asyncio.get_event_loop().run_until_complete(
            pipeline.process(
                capture_id="original",
                raw_path=raw_path,
                output_dir=output_dir,
                processing_config=config,
            )
        )

        # Raw file should be untouched
        assert raw_path.read_bytes() == raw_bytes

    @pytest.mark.integration
    def test_pipeline_batch(self, tmp_path: Path) -> None:
        """process_batch handles multiple captures."""
        raw_dir = tmp_path / "raw"
        output_dir = tmp_path / "processed"
        raw_dir.mkdir()
        output_dir.mkdir()

        captures = []
        for name in ["dashboard", "settings", "mobile"]:
            raw_path = create_test_screenshot(raw_dir / f"{name}.png", 400, 300)
            captures.append({"capture_id": name, "raw_path": raw_path})

        config = ProcessingConfig()
        config.border.style = "none"

        pipeline = DarkroomPipeline()
        results = asyncio.get_event_loop().run_until_complete(
            pipeline.process_batch(captures, output_dir, config)
        )

        assert len(results) == 3
        assert all(r.output_path.exists() for r in results)
        assert all(r.changed for r in results)  # All new = all changed

    @pytest.mark.integration
    def test_shadow_visual_quality(self, tmp_path: Path) -> None:
        """Shadow output should look reasonable (corners transparent, center opaque)."""
        raw_dir = tmp_path / "raw"
        output_dir = tmp_path / "processed"
        raw_dir.mkdir()
        output_dir.mkdir()

        raw_path = create_test_screenshot(raw_dir / "shadow.png", 600, 400)
        config = ProcessingConfig()

        pipeline = DarkroomPipeline()
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.process(
                capture_id="shadow",
                raw_path=raw_path,
                output_dir=output_dir,
                processing_config=config,
            )
        )

        img = Image.open(result.output_path)
        # pngquant may convert RGBA to palette mode (P) on Linux
        img = img.convert("RGBA")

        # Corner should be nearly transparent
        corner = img.getpixel((0, 0))
        assert corner[3] < 30, f"Corner alpha too high: {corner[3]}"

        # Center should be fully opaque (the screenshot content)
        cx, cy = img.width // 2, img.height // 2
        center = img.getpixel((cx, cy))
        assert center[3] == 255, f"Center alpha should be 255: {center[3]}"
