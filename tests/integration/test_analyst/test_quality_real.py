"""Integration tests for quality checker with generated images."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phantom.analyst.quality import QualityChecker

if TYPE_CHECKING:
    from pathlib import Path


class TestQualityCheckerReal:
    def test_realistic_screenshot(self, tmp_path: Path) -> None:
        """Generate a realistic screenshot and verify it passes."""
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (1440, 900), color=(30, 30, 30))
        draw = ImageDraw.Draw(img)

        # Header bar
        draw.rectangle([0, 0, 1440, 60], fill=(50, 50, 60))

        # Sidebar
        draw.rectangle([0, 60, 250, 900], fill=(40, 40, 50))

        # Main content area
        draw.rectangle([260, 70, 1430, 890], fill=(35, 35, 45))

        # Some colored elements
        colors = [
            (66, 133, 244),
            (234, 67, 53),
            (251, 188, 4),
            (52, 168, 83),
            (255, 109, 0),
            (171, 71, 188),
        ]
        for i, color in enumerate(colors):
            draw.rectangle([280 + i * 180, 100, 440 + i * 180, 200], fill=color)

        # Some text-like lines
        for y in range(250, 800, 30):
            width = 200 + (y % 400)
            draw.rectangle([280, y, 280 + width, y + 12], fill=(180, 180, 190))

        path = tmp_path / "screenshot.png"
        img.save(path)

        checker = QualityChecker()
        report = checker.check_screenshot(path, "realistic")
        assert report.passed, f"Failed checks: {[i.message for i in report.issues]}"
        assert report.width == 1440
        assert report.height == 900
        assert report.entropy > 1.0
        assert report.color_count >= 10

    def test_tui_screenshot(self, tmp_path: Path) -> None:
        """Generate a TUI-style screenshot."""
        import numpy as np
        from PIL import Image, ImageDraw

        # Start with a noisy dark background for realistic file size
        base = np.full((576, 1120, 3), [40, 42, 54], dtype=np.uint8)
        noise = np.random.randint(-3, 4, base.shape, dtype=np.int16)
        arr = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
        draw = ImageDraw.Draw(img)

        # Window title bar
        draw.rectangle([0, 0, 1120, 28], fill=(68, 71, 90))

        # Terminal text lines with varied colors
        text_colors = [
            (248, 248, 242),
            (139, 233, 253),
            (80, 250, 123),
            (255, 121, 198),
            (189, 147, 249),
            (241, 250, 140),
            (255, 184, 108),
            (98, 114, 164),
            (68, 71, 90),
            (255, 85, 85),
            (130, 170, 255),
        ]
        for y in range(35, 560, 14):
            color = text_colors[y % len(text_colors)]
            width = 100 + (y * 7) % 800
            draw.rectangle([10, y, 10 + width, y + 8], fill=color)

        path = tmp_path / "tui.png"
        img.save(path)

        checker = QualityChecker()
        report = checker.check_screenshot(path, "tui-view")
        assert report.passed, f"Failed: {[i.message for i in report.issues]}"

    def test_consistency_across_screenshots(self, tmp_path: Path) -> None:
        """Generate multiple screenshots and check consistency."""
        from PIL import Image, ImageDraw

        reports = []
        checker = QualityChecker()

        for i in range(3):
            img = Image.new("RGB", (1440, 900), color=(30 + i * 5, 30 + i * 5, 30 + i * 5))
            draw = ImageDraw.Draw(img)

            # Add varied content
            for x in range(0, 1440, 50):
                for y in range(0, 900, 50):
                    r = (x + i * 30) % 256
                    g = (y + i * 50) % 256
                    b = (x + y + i * 20) % 256
                    draw.rectangle([x, y, x + 40, y + 40], fill=(r, g, b))

            path = tmp_path / f"shot-{i}.png"
            img.save(path)

            report = checker.check_screenshot(path, f"shot-{i}")
            reports.append(report)

        consistency = checker.check_consistency(reports)
        assert consistency.screenshot_count == 3
        assert consistency.aspect_ratio_consistent
        # All same dimensions → low size variance expected
        assert consistency.passed

    def test_mixed_dimensions_consistency(self, tmp_path: Path) -> None:
        """Different dimensions should flag inconsistency."""
        import numpy as np
        from PIL import Image

        reports = []
        checker = QualityChecker()

        # Desktop screenshot
        arr = np.random.randint(0, 256, (900, 1440, 3), dtype=np.uint8)
        img = Image.fromarray(arr)
        path = tmp_path / "desktop.png"
        img.save(path)
        reports.append(checker.check_screenshot(path, "desktop"))

        # Mobile screenshot (very different aspect ratio)
        arr = np.random.randint(0, 256, (844, 390, 3), dtype=np.uint8)
        img = Image.fromarray(arr)
        path = tmp_path / "mobile.png"
        img.save(path)
        reports.append(checker.check_screenshot(path, "mobile"))

        consistency = checker.check_consistency(reports)
        assert not consistency.aspect_ratio_consistent

    def test_blank_image_detected(self, tmp_path: Path) -> None:
        """Solid-color image should be flagged as blank."""
        from PIL import Image

        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        path = tmp_path / "blank.png"
        img.save(path)

        checker = QualityChecker()
        report = checker.check_screenshot(path, "blank")
        assert not report.passed
        assert any(i.check == "blank_detection" and i.severity == "error" for i in report.issues)

    def test_gradient_image_passes(self, tmp_path: Path) -> None:
        """A gradient image should have decent entropy and pass."""
        import numpy as np
        from PIL import Image

        # Create a gradient
        arr = np.zeros((600, 800, 3), dtype=np.uint8)
        for x in range(800):
            for y in range(600):
                arr[y, x] = [x % 256, y % 256, (x + y) % 256]

        img = Image.fromarray(arr)
        path = tmp_path / "gradient.png"
        img.save(path)

        checker = QualityChecker()
        report = checker.check_screenshot(path, "gradient")
        assert report.passed
        assert report.entropy > 1.0
