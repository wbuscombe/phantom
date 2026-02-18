"""Tests for project type detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from phantom.analyst.analyzer import ProjectAnalyzer

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def analyzer() -> ProjectAnalyzer:
    return ProjectAnalyzer(api_key="test-key")


class TestProjectTypeDetection:
    async def test_package_json_is_web(self, tmp_path: Path, analyzer: ProjectAnalyzer) -> None:
        (tmp_path / "package.json").write_text('{"name":"app"}')
        assert await analyzer.detect_project_type(tmp_path) == "web"

    async def test_cargo_toml_is_tui(self, tmp_path: Path, analyzer: ProjectAnalyzer) -> None:
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "app"')
        assert await analyzer.detect_project_type(tmp_path) == "tui"

    async def test_go_mod_is_tui(self, tmp_path: Path, analyzer: ProjectAnalyzer) -> None:
        (tmp_path / "go.mod").write_text("module github.com/user/app")
        assert await analyzer.detect_project_type(tmp_path) == "tui"

    async def test_docker_compose_yml(self, tmp_path: Path, analyzer: ProjectAnalyzer) -> None:
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        assert await analyzer.detect_project_type(tmp_path) == "docker-compose"

    async def test_docker_compose_yaml(self, tmp_path: Path, analyzer: ProjectAnalyzer) -> None:
        (tmp_path / "docker-compose.yaml").write_text("version: '3'")
        assert await analyzer.detect_project_type(tmp_path) == "docker-compose"

    async def test_compose_yml(self, tmp_path: Path, analyzer: ProjectAnalyzer) -> None:
        (tmp_path / "compose.yml").write_text("version: '3'")
        assert await analyzer.detect_project_type(tmp_path) == "docker-compose"

    async def test_pyproject_with_textual(self, tmp_path: Path, analyzer: ProjectAnalyzer) -> None:
        (tmp_path / "pyproject.toml").write_text('dependencies = ["textual>=0.40"]')
        assert await analyzer.detect_project_type(tmp_path) == "tui"

    async def test_pyproject_with_rich(self, tmp_path: Path, analyzer: ProjectAnalyzer) -> None:
        (tmp_path / "pyproject.toml").write_text('dependencies = ["rich>=13.0"]')
        assert await analyzer.detect_project_type(tmp_path) == "tui"

    async def test_pyproject_without_tui_indicator(
        self, tmp_path: Path, analyzer: ProjectAnalyzer
    ) -> None:
        (tmp_path / "pyproject.toml").write_text('dependencies = ["flask"]')
        # Falls through to web default
        assert await analyzer.detect_project_type(tmp_path) == "web"

    async def test_empty_dir_defaults_to_web(
        self, tmp_path: Path, analyzer: ProjectAnalyzer
    ) -> None:
        assert await analyzer.detect_project_type(tmp_path) == "web"

    async def test_docker_over_package_json(
        self, tmp_path: Path, analyzer: ProjectAnalyzer
    ) -> None:
        (tmp_path / "docker-compose.yml").write_text("services:")
        (tmp_path / "package.json").write_text("{}")
        assert await analyzer.detect_project_type(tmp_path) == "docker-compose"

    async def test_tauri_cargo_is_web(self, tmp_path: Path, analyzer: ProjectAnalyzer) -> None:
        (tmp_path / "Cargo.toml").write_text('[dependencies.tauri]\nversion = "1.0"')
        assert await analyzer.detect_project_type(tmp_path) == "web"
