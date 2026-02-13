"""Border and shadow stage — publication-quality visual treatments.

Implements ADR-007: macOS-style drop shadow as the default.

Pipeline:
1. Round corners on source image (via alpha mask)
2. Create canvas with padding for shadow
3. Draw shadow layer (gaussian blur of offset rectangle)
4. Composite: canvas <- shadow <- rounded source
5. Save with alpha channel (transparent background)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog
from PIL import Image, ImageDraw, ImageFilter

from phantom.darkroom.base import DarkroomStage, StageResult

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()


def _parse_rgba(color_str: str) -> tuple[int, int, int, int]:
    """Parse an rgba() CSS string or hex color into (R, G, B, A) tuple."""
    # rgba(0,0,0,0.3)
    match = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)",
        color_str,
    )
    if match:
        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
        a = float(match.group(4)) if match.group(4) else 1.0
        return (r, g, b, int(a * 255))

    # Hex colors
    if color_str.startswith("#"):
        hex_str = color_str.lstrip("#")
        if len(hex_str) == 6:
            return (
                int(hex_str[0:2], 16),
                int(hex_str[2:4], 16),
                int(hex_str[4:6], 16),
                255,
            )
        if len(hex_str) == 8:
            return (
                int(hex_str[0:2], 16),
                int(hex_str[2:4], 16),
                int(hex_str[4:6], 16),
                int(hex_str[6:8], 16),
            )

    # Named colors
    if color_str == "transparent":
        return (0, 0, 0, 0)
    if color_str == "black":
        return (0, 0, 0, 255)
    if color_str == "white":
        return (255, 255, 255, 255)

    # Fallback
    return (0, 0, 0, 77)  # ~0.3 alpha black


def _round_corners(img: Image.Image, radius: int) -> Image.Image:
    """Apply rounded corners to an image using an alpha mask."""
    if radius <= 0:
        return img.convert("RGBA") if img.mode != "RGBA" else img

    img = img.convert("RGBA")
    w, h = img.size

    # Create rounded rectangle mask
    mask = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(mask)

    # Draw black (transparent) corners using filled rectangles
    # then draw white rounded rectangle
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)

    # Apply mask to alpha channel
    img.putalpha(mask)
    return img


class BorderStage(DarkroomStage):
    @property
    def name(self) -> str:
        return "border"

    async def process(self, image_path: Path, config: dict[str, object]) -> StageResult:
        border_config = config.get("border", {})
        if not isinstance(border_config, dict):
            return StageResult(output_path=image_path, changed=False)

        style = str(border_config.get("style", "drop-shadow"))

        if style == "none":
            return StageResult(output_path=image_path, changed=False)

        try:
            img = Image.open(image_path)

            if style == "drop-shadow":
                result_img = _apply_drop_shadow(img, border_config)
            elif style == "rounded":
                radius = int(border_config.get("corner_radius", 8))
                result_img = _round_corners(img, radius)
            elif style == "outline":
                result_img = _apply_outline(img, border_config)
            else:
                logger.warning("border_unknown_style", style=style)
                return StageResult(output_path=image_path, changed=False)

            result_img.save(image_path, "PNG")

            logger.debug(
                "border_applied",
                style=style,
                original=f"{img.width}x{img.height}",
                result=f"{result_img.width}x{result_img.height}",
            )
            return StageResult(
                output_path=image_path,
                metadata={
                    "style": style,
                    "original_size": (img.width, img.height),
                    "result_size": (result_img.width, result_img.height),
                },
            )

        except Exception as e:
            logger.warning("border_failed", error=str(e))
            return StageResult(output_path=image_path, changed=False)


def _apply_drop_shadow(img: Image.Image, config: dict[str, object]) -> Image.Image:
    """Apply macOS-style drop shadow to an image."""
    # Parse config
    shadow_color = _parse_rgba(str(config.get("shadow_color", "rgba(0,0,0,0.3)")))
    offset_cfg = config.get("shadow_offset", {})
    if isinstance(offset_cfg, dict):
        offset_x = int(offset_cfg.get("x", 0))
        offset_y = int(offset_cfg.get("y", 8))
    else:
        offset_x, offset_y = 0, 8
    blur_radius = int(config.get("shadow_blur", 24))  # type: ignore[call-overload]
    padding = int(config.get("padding", 32))  # type: ignore[call-overload]
    corner_radius = int(config.get("corner_radius", 8))  # type: ignore[call-overload]
    bg_color_str = str(config.get("background", "transparent"))
    bg_color = _parse_rgba(bg_color_str) if bg_color_str != "transparent" else (0, 0, 0, 0)

    # Round corners on source image
    src = _round_corners(img, corner_radius)
    src_w, src_h = src.size

    # Calculate canvas size (source + padding on all sides + shadow extent)
    shadow_extent = blur_radius * 2  # Blur spreads the shadow
    canvas_w = src_w + padding * 2 + shadow_extent
    canvas_h = src_h + padding * 2 + shadow_extent

    # Create canvas
    canvas = Image.new("RGBA", (canvas_w, canvas_h), bg_color)

    # Create shadow layer
    # The shadow is a solid rectangle at the shadow color, offset, then blurred
    shadow = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)

    # Shadow position = source position + offset
    src_x = padding + shadow_extent // 2
    src_y = padding + shadow_extent // 2
    shadow_x = src_x + offset_x
    shadow_y = src_y + offset_y

    # Draw shadow rectangle with rounded corners
    shadow_draw.rounded_rectangle(
        [shadow_x, shadow_y, shadow_x + src_w - 1, shadow_y + src_h - 1],
        radius=corner_radius,
        fill=shadow_color,
    )

    # Apply gaussian blur to shadow
    # PIL's GaussianBlur radius is approximately blur_radius / 2
    if blur_radius > 0:
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    # Composite: canvas <- shadow <- source
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(src, (src_x, src_y), src)

    return canvas


def _apply_outline(img: Image.Image, config: dict[str, object]) -> Image.Image:
    """Apply a thin outline border to an image."""
    corner_radius = int(config.get("corner_radius", 8))  # type: ignore[call-overload]
    padding = int(config.get("padding", 4))  # type: ignore[call-overload]
    outline_color = _parse_rgba(str(config.get("shadow_color", "rgba(128,128,128,0.5)")))

    src = _round_corners(img, corner_radius)
    src_w, src_h = src.size

    canvas_w = src_w + padding * 2
    canvas_h = src_h + padding * 2

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Draw outline rectangle
    draw.rounded_rectangle(
        [padding - 1, padding - 1, padding + src_w, padding + src_h],
        radius=corner_radius,
        outline=outline_color,
        width=1,
    )

    canvas.paste(src, (padding, padding), src)
    return canvas
