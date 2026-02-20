"""Tests for screenshot quality checker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phantom.analyst.models import QualityReport
from phantom.analyst.quality import QualityChecker

if TYPE_CHECKING:
    from pathlib import Path


def _save_image(img: object, path: Path) -> Path:
    """Save a PIL image to path and return it."""
    from PIL import Image

    assert isinstance(img, Image.Image)
    img.save(path)
    return path


class TestBlankDetection:
    def test_solid_white_image(self, tmp_path: Path) -> None:
        from PIL import Image

        img = Image.new("RGB", (200, 200), color=(255, 255, 255))
        path = _save_image(img, tmp_path / "blank.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "blank-test")
        assert not report.passed
        assert any(i.check == "blank_detection" for i in report.issues)

    def test_solid_black_image(self, tmp_path: Path) -> None:
        from PIL import Image

        img = Image.new("RGB", (200, 200), color=(0, 0, 0))
        path = _save_image(img, tmp_path / "black.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "black-test")
        assert not report.passed
        assert any(i.check == "blank_detection" for i in report.issues)


class TestEntropy:
    def test_low_entropy_image(self, tmp_path: Path) -> None:
        from PIL import Image

        # Two-color image with very little variation
        img = Image.new("RGB", (200, 200), color=(128, 128, 128))
        # Add one different pixel
        img.putpixel((0, 0), (129, 128, 128))
        path = _save_image(img, tmp_path / "low_entropy.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "entropy-test")
        assert any(i.check == "entropy" for i in report.issues)

    def test_high_entropy_image(self, tmp_path: Path) -> None:
        import numpy as np
        from PIL import Image

        # Random noise image — high entropy
        arr = np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8)
        img = Image.fromarray(arr)
        path = _save_image(img, tmp_path / "noisy.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "noise-test")
        assert not any(i.check == "entropy" for i in report.issues)


class TestFileSize:
    def test_tiny_file(self, tmp_path: Path) -> None:
        from PIL import Image

        # Very tiny image = small file
        img = Image.new("RGB", (2, 2), color=(128, 128, 128))
        path = _save_image(img, tmp_path / "tiny.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "tiny-test")
        assert any(i.check == "file_size" for i in report.issues)


class TestTransparency:
    def test_mostly_transparent(self, tmp_path: Path) -> None:
        from PIL import Image

        # RGBA image with all pixels transparent
        img = Image.new("RGBA", (200, 200), color=(0, 0, 0, 0))
        path = _save_image(img, tmp_path / "transparent.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "transparent-test")
        assert any(i.check == "transparency" for i in report.issues)

    def test_opaque_rgba(self, tmp_path: Path) -> None:
        import numpy as np
        from PIL import Image

        arr = np.random.randint(0, 256, (200, 200, 4), dtype=np.uint8)
        arr[:, :, 3] = 255  # Fully opaque
        img = Image.fromarray(arr, "RGBA")
        path = _save_image(img, tmp_path / "opaque_rgba.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "opaque-test")
        assert not any(i.check == "transparency" for i in report.issues)


class TestColorVariety:
    def test_low_color_count(self, tmp_path: Path) -> None:
        from PIL import Image

        # Two-color image
        img = Image.new("RGB", (200, 200), color=(128, 128, 128))
        for x in range(100):
            img.putpixel((x, 0), (255, 0, 0))
        path = _save_image(img, tmp_path / "few_colors.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "color-test")
        assert any(i.check == "color_variety" for i in report.issues)


class TestDimensions:
    def test_too_small(self, tmp_path: Path) -> None:
        from PIL import Image

        img = Image.new("RGB", (50, 50), color=(128, 128, 128))
        path = _save_image(img, tmp_path / "small.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "small-test")
        assert any(i.check == "dimensions" for i in report.issues)

    def test_adequate_size(self, tmp_path: Path) -> None:
        import numpy as np
        from PIL import Image

        arr = np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8)
        img = Image.fromarray(arr)
        path = _save_image(img, tmp_path / "good.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "good-test")
        assert not any(i.check == "dimensions" for i in report.issues)


class TestAspectRatio:
    def test_extreme_aspect_ratio(self, tmp_path: Path) -> None:
        import numpy as np
        from PIL import Image

        arr = np.random.randint(0, 256, (100, 500, 3), dtype=np.uint8)
        img = Image.fromarray(arr)
        path = _save_image(img, tmp_path / "wide.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "wide-test")
        assert any(i.check == "aspect_ratio" for i in report.issues)


class TestNormalScreenshot:
    def test_normal_screenshot_passes(self, tmp_path: Path) -> None:
        """A realistic screenshot should pass all checks."""
        from PIL import Image, ImageDraw

        # Create a realistic-looking screenshot
        img = Image.new("RGB", (1440, 900), color=(30, 30, 30))
        draw = ImageDraw.Draw(img)
        # Add some content
        draw.rectangle([0, 0, 1440, 60], fill=(50, 50, 50))
        draw.rectangle([20, 80, 300, 880], fill=(40, 40, 45))
        draw.rectangle([320, 80, 1420, 880], fill=(35, 35, 40))
        # Add some color variety
        for i in range(50):
            color = (i * 5 % 256, (i * 3 + 100) % 256, (i * 7 + 50) % 256)
            draw.rectangle([330 + i * 20, 100, 340 + i * 20, 120], fill=color)

        path = _save_image(img, tmp_path / "screenshot.png")

        checker = QualityChecker()
        report = checker.check_screenshot(path, "normal-test")
        assert report.passed
        assert report.width == 1440
        assert report.height == 900
        assert report.entropy > 1.0


class TestConsistency:
    def test_consistent_reports(self) -> None:
        checker = QualityChecker()
        reports = [
            QualityReport(
                capture_id="a",
                passed=True,
                file_size_kb=100.0,
                width=1440,
                height=900,
                entropy=5.0,
                color_count=1000,
            ),
            QualityReport(
                capture_id="b",
                passed=True,
                file_size_kb=120.0,
                width=1440,
                height=900,
                entropy=5.5,
                color_count=1200,
            ),
        ]
        result = checker.check_consistency(reports)
        assert result.passed
        assert result.screenshot_count == 2
        assert result.aspect_ratio_consistent

    def test_inconsistent_aspect_ratios(self) -> None:
        checker = QualityChecker()
        reports = [
            QualityReport(
                capture_id="a",
                passed=True,
                file_size_kb=100.0,
                width=1440,
                height=900,
            ),
            QualityReport(
                capture_id="b",
                passed=True,
                file_size_kb=100.0,
                width=390,
                height=844,
            ),
        ]
        result = checker.check_consistency(reports)
        assert not result.aspect_ratio_consistent

    def test_empty_reports(self) -> None:
        checker = QualityChecker()
        result = checker.check_consistency([])
        assert result.passed
        assert result.screenshot_count == 0
