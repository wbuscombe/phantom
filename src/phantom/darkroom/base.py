"""Base interface for Darkroom pipeline stages.

Each stage takes an image path and config, processes the image,
and returns the path to the result (may be the same path for in-place ops).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class StageResult:
    """Result of a pipeline stage execution."""

    output_path: Path
    changed: bool = True
    metadata: dict[str, object] | None = None


class DarkroomStage(ABC):
    """Abstract base class for all Darkroom pipeline stages."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable stage name for logging."""

    @abstractmethod
    async def process(self, image_path: Path, config: dict[str, object]) -> StageResult:
        """Process an image and return the result.

        Args:
            image_path: Path to the input image.
            config: Stage-specific configuration from the manifest.

        Returns:
            StageResult with the output path and metadata.

        Implementations must not raise — return input unchanged on error
        with a warning log.
        """
