"""Unit tests for individual Darkroom pipeline stages."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from pathlib import Path

# ── Test image helpers ────────────────────────────────


def create_test_image(
    path: Path,
    width: int = 400,
    height: int = 300,
    color: tuple[int, int, int] = (30, 30, 50),
) -> Path:
    """Create a simple test PNG image."""
    img = Image.new("RGB", (width, height), color)
    # Add some visual content so it's not uniform
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 180, 80], fill=(228, 69, 96))
    draw.rectangle([20, 100, 280, 160], fill=(78, 204, 163))
    draw.rectangle([200, 20, 380, 280], fill=(15, 52, 96))
    draw.ellipse([100, 180, 200, 260], fill=(233, 196, 106))
    img.save(path, "PNG")
    return path


def create_test_image_with_exif(path: Path) -> Path:
    """Create a test image with EXIF metadata."""
    import piexif  # noqa: F401 — only if available

    img = Image.new("RGB", (200, 200), (50, 50, 80))
    # Add a dummy EXIF block
    img.info["exif"] = b"Exif\x00\x00" + b"\x00" * 50
    img.save(path, "PNG", exif=img.info.get("exif", b""))
    return path


def create_rgba_test_image(path: Path, width: int = 400, height: int = 300) -> Path:
    """Create an RGBA test image."""
    img = Image.new("RGBA", (width, height), (30, 30, 50, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 180, 80], fill=(228, 69, 96, 255))
    draw.rectangle([20, 100, 280, 160], fill=(78, 204, 163, 200))
    img.save(path, "PNG")
    return path


# ── Color Normalize ───────────────────────────────────


class TestColorNormalize:
    def test_passthrough_no_profile(self, tmp_path: Path) -> None:
        """Images without ICC profiles pass through unchanged."""
        from phantom.darkroom.stages.color import ColorNormalizeStage

        img_path = create_test_image(tmp_path / "test.png")
        stage = ColorNormalizeStage()
        result = asyncio.run(stage.process(img_path, {}))
        assert result.output_path == img_path
        assert not result.changed

    def test_name(self) -> None:
        from phantom.darkroom.stages.color import ColorNormalizeStage

        assert ColorNormalizeStage().name == "color_normalize"


# ── EXIF Strip ────────────────────────────────────────


class TestExifStrip:
    def test_strip_no_metadata(self, tmp_path: Path) -> None:
        """Images without metadata pass through unchanged."""
        from phantom.darkroom.stages.exif import ExifStripStage

        img_path = create_test_image(tmp_path / "clean.png")
        stage = ExifStripStage()
        result = asyncio.run(stage.process(img_path, {}))
        assert result.output_path == img_path
        # PNG from Pillow may or may not have metadata, so just verify it doesn't crash

    def test_name(self) -> None:
        from phantom.darkroom.stages.exif import ExifStripStage

        assert ExifStripStage().name == "exif_strip"


# ── Crop ──────────────────────────────────────────────


class TestCrop:
    def test_no_crop_config(self, tmp_path: Path) -> None:
        """No crop config = pass through."""
        from phantom.darkroom.stages.crop import CropStage

        img_path = create_test_image(tmp_path / "test.png", 400, 300)
        stage = CropStage()
        result = asyncio.run(stage.process(img_path, {}))
        assert not result.changed
        img = Image.open(result.output_path)
        assert img.size == (400, 300)

    def test_manual_crop(self, tmp_path: Path) -> None:
        """Manual crop extracts the specified region."""
        from phantom.darkroom.stages.crop import CropStage

        img_path = create_test_image(tmp_path / "test.png", 400, 300)
        stage = CropStage()
        result = asyncio.run(
            stage.process(img_path, {"crop": {"x": 50, "y": 50, "width": 200, "height": 150}})
        )
        assert result.changed is True
        img = Image.open(result.output_path)
        assert img.size == (200, 150)

    def test_crop_clamped_to_bounds(self, tmp_path: Path) -> None:
        """Crop region exceeding image bounds is clamped."""
        from phantom.darkroom.stages.crop import CropStage

        img_path = create_test_image(tmp_path / "test.png", 400, 300)
        stage = CropStage()
        result = asyncio.run(
            stage.process(img_path, {"crop": {"x": 300, "y": 200, "width": 200, "height": 200}})
        )
        img = Image.open(result.output_path)
        # Clamped: right edge = min(500, 400) = 400, bottom = min(400, 300) = 300
        assert img.width == 100  # 400 - 300
        assert img.height == 100  # 300 - 200


# ── Resize ────────────────────────────────────────────


class TestResize:
    def test_no_resize_needed(self, tmp_path: Path) -> None:
        """Image below max_width passes through unchanged."""
        from phantom.darkroom.stages.resize import ResizeStage

        img_path = create_test_image(tmp_path / "test.png", 400, 300)
        stage = ResizeStage()
        result = asyncio.run(stage.process(img_path, {"max_width": 2800}))
        assert not result.changed
        img = Image.open(result.output_path)
        assert img.size == (400, 300)

    def test_resize_to_max_width(self, tmp_path: Path) -> None:
        """Image exceeding max_width is scaled down preserving aspect ratio."""
        from phantom.darkroom.stages.resize import ResizeStage

        img_path = create_test_image(tmp_path / "test.png", 3000, 2000)
        stage = ResizeStage()
        result = asyncio.run(stage.process(img_path, {"max_width": 1500}))
        assert result.changed is True
        img = Image.open(result.output_path)
        assert img.width == 1500
        assert img.height == 1000  # 2000 * (1500/3000)

    def test_resize_preserves_aspect_ratio(self, tmp_path: Path) -> None:
        """Aspect ratio is maintained during resize."""
        from phantom.darkroom.stages.resize import ResizeStage

        img_path = create_test_image(tmp_path / "test.png", 2880, 1800)
        stage = ResizeStage()
        result = asyncio.run(stage.process(img_path, {"max_width": 2800}))
        img = Image.open(result.output_path)
        assert img.width == 2800
        expected_height = int(1800 * (2800 / 2880))
        assert img.height == expected_height


# ── Border / Shadow ───────────────────────────────────


class TestBorder:
    def test_drop_shadow_increases_canvas(self, tmp_path: Path) -> None:
        """Drop shadow adds padding and shadow extent to the canvas."""
        from phantom.darkroom.stages.border import BorderStage

        img_path = create_test_image(tmp_path / "test.png", 400, 300)
        stage = BorderStage()
        config = {
            "border": {
                "style": "drop-shadow",
                "shadow_color": "rgba(0,0,0,0.3)",
                "shadow_offset": {"x": 0, "y": 8},
                "shadow_blur": 24,
                "padding": 32,
                "background": "transparent",
                "corner_radius": 8,
            }
        }
        result = asyncio.run(stage.process(img_path, config))
        assert result.changed is True
        img = Image.open(result.output_path)
        # Canvas = source + padding*2 + shadow_extent(blur*2)
        expected_w = 400 + 32 * 2 + 24 * 2
        expected_h = 300 + 32 * 2 + 24 * 2
        assert img.width == expected_w
        assert img.height == expected_h

    def test_drop_shadow_has_transparency(self, tmp_path: Path) -> None:
        """Drop shadow output has RGBA mode with transparent background."""
        from phantom.darkroom.stages.border import BorderStage

        img_path = create_test_image(tmp_path / "test.png", 200, 150)
        stage = BorderStage()
        config = {
            "border": {
                "style": "drop-shadow",
                "padding": 20,
                "shadow_blur": 16,
                "corner_radius": 4,
            }
        }
        result = asyncio.run(stage.process(img_path, config))
        img = Image.open(result.output_path)
        assert img.mode == "RGBA"
        # Top-left corner should be transparent (or nearly so)
        corner_pixel = img.getpixel((0, 0))
        assert corner_pixel[3] < 50  # Alpha should be low in the corner

    def test_border_none(self, tmp_path: Path) -> None:
        """style: none passes through unchanged."""
        from phantom.darkroom.stages.border import BorderStage

        img_path = create_test_image(tmp_path / "test.png", 200, 150)
        original_size = Image.open(img_path).size
        stage = BorderStage()
        result = asyncio.run(stage.process(img_path, {"border": {"style": "none"}}))
        assert not result.changed
        assert Image.open(result.output_path).size == original_size

    def test_outline_border(self, tmp_path: Path) -> None:
        """Outline border adds minimal padding."""
        from phantom.darkroom.stages.border import BorderStage

        img_path = create_test_image(tmp_path / "test.png", 200, 150)
        stage = BorderStage()
        config = {
            "border": {
                "style": "outline",
                "padding": 4,
                "corner_radius": 4,
            }
        }
        result = asyncio.run(stage.process(img_path, config))
        img = Image.open(result.output_path)
        assert img.width == 200 + 4 * 2
        assert img.height == 150 + 4 * 2

    def test_rounded_corners(self, tmp_path: Path) -> None:
        """Rounded style applies corner rounding without extra padding."""
        from phantom.darkroom.stages.border import BorderStage

        img_path = create_test_image(tmp_path / "test.png", 200, 150)
        stage = BorderStage()
        config = {"border": {"style": "rounded", "corner_radius": 12}}
        result = asyncio.run(stage.process(img_path, config))
        img = Image.open(result.output_path)
        assert img.mode == "RGBA"
        assert img.size == (200, 150)  # No size change
        # Top-left corner should be transparent due to rounding
        corner_pixel = img.getpixel((0, 0))
        assert corner_pixel[3] == 0

    def test_rgba_input_preserved(self, tmp_path: Path) -> None:
        """RGBA input images are handled correctly."""
        from phantom.darkroom.stages.border import BorderStage

        img_path = create_rgba_test_image(tmp_path / "test.png", 200, 150)
        stage = BorderStage()
        config = {
            "border": {
                "style": "drop-shadow",
                "padding": 16,
                "shadow_blur": 12,
                "corner_radius": 4,
            }
        }
        result = asyncio.run(stage.process(img_path, config))
        img = Image.open(result.output_path)
        assert img.mode == "RGBA"


# ── Optimize ──────────────────────────────────────────


class TestOptimize:
    def test_optimize_disabled(self, tmp_path: Path) -> None:
        """optimize: false passes through unchanged."""
        from phantom.darkroom.stages.optimize import OptimizeStage

        img_path = create_test_image(tmp_path / "test.png")
        stage = OptimizeStage()
        result = asyncio.run(stage.process(img_path, {"optimize": False}))
        assert not result.changed

    def test_optimize_png(self, tmp_path: Path) -> None:
        """PNG optimization runs without error (tools may or may not be installed)."""
        from phantom.darkroom.stages.optimize import OptimizeStage

        img_path = create_test_image(tmp_path / "test.png", 800, 600)
        stage = OptimizeStage()
        result = asyncio.run(stage.process(img_path, {"optimize": True, "format": "png"}))
        # Should not error regardless of whether pngquant/oxipng are installed
        assert result.output_path.exists()
        assert result.metadata is not None
        assert "original_size" in result.metadata

    def test_webp_conversion(self, tmp_path: Path) -> None:
        """WebP conversion produces a .webp file."""
        from phantom.darkroom.stages.optimize import OptimizeStage

        img_path = create_test_image(tmp_path / "test.png", 400, 300)
        stage = OptimizeStage()
        result = asyncio.run(stage.process(img_path, {"optimize": True, "format": "webp"}))
        assert result.output_path.suffix == ".webp"
        assert result.output_path.exists()


# ── Diff (SSIM) ──────────────────────────────────────


class TestDiff:
    def test_identical_images(self, tmp_path: Path) -> None:
        """Identical images should have similarity ~1.0 and not be changed."""
        from phantom.darkroom.stages.diff import compute_ssim_diff

        img_path = create_test_image(tmp_path / "current.png", 400, 300)
        prev_path = tmp_path / "previous.png"
        Image.open(img_path).save(prev_path)

        result = compute_ssim_diff(img_path, prev_path, threshold=0.95)
        assert not result.changed
        assert result.similarity > 0.99
        assert result.diff_pct < 1.0

    def test_different_images(self, tmp_path: Path) -> None:
        """Significantly different images should be marked as changed."""
        from phantom.darkroom.stages.diff import compute_ssim_diff

        create_test_image(tmp_path / "current.png", 400, 300, (30, 30, 50))
        create_test_image(tmp_path / "previous.png", 400, 300, (200, 200, 220))

        result = compute_ssim_diff(
            tmp_path / "current.png",
            tmp_path / "previous.png",
            threshold=0.95,
        )
        assert result.changed
        assert result.similarity < 0.95

    def test_slightly_different(self, tmp_path: Path) -> None:
        """Slightly modified images with high threshold should be detected."""
        from phantom.darkroom.stages.diff import compute_ssim_diff

        img = Image.new("RGB", (400, 300), (30, 30, 50))
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 380, 280], fill=(15, 52, 96))
        img.save(tmp_path / "current.png")

        # Make a copy with a small modification
        img2 = img.copy()
        draw2 = ImageDraw.Draw(img2)
        draw2.rectangle([100, 100, 120, 120], fill=(255, 0, 0))  # Small red square
        img2.save(tmp_path / "previous.png")

        result = compute_ssim_diff(
            tmp_path / "current.png",
            tmp_path / "previous.png",
            threshold=0.95,
        )
        # Small change should still be detected
        assert result.similarity < 1.0
        assert result.similarity > 0.5  # But not wildly different

    def test_different_dimensions(self, tmp_path: Path) -> None:
        """Images with different dimensions are handled via resize."""
        from phantom.darkroom.stages.diff import compute_ssim_diff

        create_test_image(tmp_path / "current.png", 400, 300)
        create_test_image(tmp_path / "previous.png", 200, 150)

        # Should not crash — previous is resized to match current
        result = compute_ssim_diff(
            tmp_path / "current.png",
            tmp_path / "previous.png",
            threshold=0.95,
        )
        assert isinstance(result.similarity, float)

    def test_no_previous_always_changed(self, tmp_path: Path) -> None:
        """No previous version means the image is always 'changed'."""
        from phantom.darkroom.stages.diff import DiffStage

        img_path = create_test_image(tmp_path / "test.png")
        stage = DiffStage()
        result = asyncio.run(stage.process(img_path, {"diff": {"enabled": True}}))
        assert result.changed

    def test_diff_disabled(self, tmp_path: Path) -> None:
        """Disabled diff always returns changed=True."""
        from phantom.darkroom.stages.diff import DiffStage

        img_path = create_test_image(tmp_path / "test.png")
        stage = DiffStage()
        result = asyncio.run(stage.process(img_path, {"diff": {"enabled": False}}))
        assert result.changed

    def test_ignore_regions(self, tmp_path: Path) -> None:
        """Ignore regions mask volatile areas from comparison."""
        from phantom.darkroom.stages.diff import compute_ssim_diff

        # Create two images identical except in a specific region
        img = Image.new("RGB", (400, 300), (30, 30, 50))
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 380, 280], fill=(15, 52, 96))
        img.save(tmp_path / "current.png")

        img2 = img.copy()
        draw2 = ImageDraw.Draw(img2)
        # Difference only in the ignored region
        draw2.rectangle([50, 50, 100, 80], fill=(255, 0, 0))
        img2.save(tmp_path / "previous.png")

        from phantom.models import Region

        # Without ignore: should detect change
        result_no_ignore = compute_ssim_diff(
            tmp_path / "current.png",
            tmp_path / "previous.png",
            threshold=0.999,
        )

        # With ignore covering the changed area: should be more similar
        result_with_ignore = compute_ssim_diff(
            tmp_path / "current.png",
            tmp_path / "previous.png",
            threshold=0.999,
            ignore_regions=[Region(x=40, y=40, width=70, height=50)],
        )

        assert result_with_ignore.similarity > result_no_ignore.similarity
