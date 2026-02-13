"""Tests for phantom doctor and dependency checking."""

from __future__ import annotations

import platform

import pytest

from phantom.conductor.requirements import (
    RUNNER_REQUIREMENTS,
    TOOL_HINTS,
    DoctorCheckResult,
    check_all_dependencies,
    get_install_hint,
)


class TestInstallHints:
    def test_known_tool_returns_hint(self) -> None:
        hint = get_install_hint("git")
        assert hint  # non-empty string
        assert isinstance(hint, str)

    def test_unknown_tool_returns_generic_hint(self) -> None:
        hint = get_install_hint("nonexistent-tool-xyz")
        assert "nonexistent-tool-xyz" in hint

    def test_hint_is_os_specific(self) -> None:
        system = platform.system()
        if system in ("Darwin", "Linux"):
            hint = get_install_hint("git")
            assert hint == TOOL_HINTS["git"][system]

    def test_all_runner_requirements_have_entries(self) -> None:
        """Every runner type should be in RUNNER_REQUIREMENTS."""
        assert "common" in RUNNER_REQUIREMENTS
        assert "web" in RUNNER_REQUIREMENTS
        assert "tui" in RUNNER_REQUIREMENTS
        assert "docker-compose" in RUNNER_REQUIREMENTS


class TestCheckAllDependencies:
    @pytest.mark.asyncio
    async def test_returns_list_of_results(self) -> None:
        results = await check_all_dependencies()
        assert isinstance(results, list)
        assert all(isinstance(r, DoctorCheckResult) for r in results)

    @pytest.mark.asyncio
    async def test_git_is_found(self) -> None:
        """Git should be available in any dev environment."""
        results = await check_all_dependencies()
        git_result = next((r for r in results if r.tool == "git"), None)
        assert git_result is not None
        assert git_result.found is True
        assert git_result.version is not None

    @pytest.mark.asyncio
    async def test_results_have_install_hints(self) -> None:
        results = await check_all_dependencies()
        for r in results:
            assert r.install_hint  # non-empty

    @pytest.mark.asyncio
    async def test_no_duplicate_tools(self) -> None:
        results = await check_all_dependencies()
        tools = [r.tool for r in results]
        assert len(tools) == len(set(tools))


class TestDoctorCLI:
    def test_doctor_command_exists(self) -> None:
        from click.testing import CliRunner

        from phantom.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0

    def test_doctor_verbose_flag(self) -> None:
        from click.testing import CliRunner

        from phantom.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--verbose"])
        assert result.exit_code == 0
        # Verbose mode should show OK entries
        assert "OK" in result.output or "MISSING" in result.output
