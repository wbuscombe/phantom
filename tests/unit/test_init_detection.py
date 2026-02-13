"""Tests for phantom init project type auto-detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phantom.cli import _detect_project_type

if TYPE_CHECKING:
    from pathlib import Path


class TestDetectProjectType:
    def test_detect_web_from_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        assert _detect_project_type(tmp_path) == "web"

    def test_detect_web_from_bun_lockb(self, tmp_path: Path) -> None:
        (tmp_path / "bun.lockb").write_bytes(b"")
        assert _detect_project_type(tmp_path) == "web"

    def test_detect_web_from_yarn_lock(self, tmp_path: Path) -> None:
        (tmp_path / "yarn.lock").write_text("")
        assert _detect_project_type(tmp_path) == "web"

    def test_detect_tui_from_cargo_toml(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]")
        assert _detect_project_type(tmp_path) == "tui"

    def test_detect_tui_from_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/foo")
        assert _detect_project_type(tmp_path) == "tui"

    def test_detect_docker_compose_yml(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        assert _detect_project_type(tmp_path) == "docker-compose"

    def test_detect_compose_yml(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yml").write_text("version: '3'")
        assert _detect_project_type(tmp_path) == "docker-compose"

    def test_none_for_empty_directory(self, tmp_path: Path) -> None:
        assert _detect_project_type(tmp_path) is None

    def test_docker_compose_takes_precedence_over_web(self, tmp_path: Path) -> None:
        """If both docker-compose.yml and package.json exist, docker-compose wins."""
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        (tmp_path / "package.json").write_text("{}")
        assert _detect_project_type(tmp_path) == "docker-compose"

    def test_detect_docker_compose_yaml_extension(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yaml").write_text("version: '3'")
        assert _detect_project_type(tmp_path) == "docker-compose"

    def test_detect_compose_yaml_extension(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text("version: '3'")
        assert _detect_project_type(tmp_path) == "docker-compose"


class TestInitCommand:
    def test_init_command_exists(self) -> None:
        from click.testing import CliRunner

        from phantom.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "--dir" in result.output

    def test_init_creates_manifest(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from phantom.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["init", "--dir", str(tmp_path)],
            input="web\nmy-project\nMy Project\nnpm run dev\n3000\n2\n",
        )
        assert result.exit_code == 0
        manifest = tmp_path / ".phantom.yml"
        assert manifest.exists()
        content = manifest.read_text()
        assert 'project: "my-project"' in content
        assert "type: web" in content
