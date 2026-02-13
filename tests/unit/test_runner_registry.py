"""Tests for the runner plugin registry."""

from __future__ import annotations

import pytest

from phantom.exceptions import ConductorError
from phantom.runners import available_runners, get_runner, register_runner
from phantom.runners.base import BaseRunner


class TestBuiltinRegistration:
    def test_web_runner_registered(self) -> None:
        assert "web" in available_runners()

    def test_tui_runner_registered(self) -> None:
        assert "tui" in available_runners()

    def test_docker_compose_runner_registered(self) -> None:
        assert "docker-compose" in available_runners()

    def test_available_runners_sorted(self) -> None:
        runners = available_runners()
        assert runners == sorted(runners)


class TestGetRunner:
    def test_get_web_runner(self) -> None:
        from phantom.runners.web import WebRunner

        runner = get_runner("web")
        assert isinstance(runner, WebRunner)

    def test_get_tui_runner(self) -> None:
        from phantom.runners.terminal import TerminalRunner

        runner = get_runner("tui")
        assert isinstance(runner, TerminalRunner)

    def test_get_docker_runner(self) -> None:
        from phantom.runners.docker import DockerRunner

        runner = get_runner("docker-compose")
        assert isinstance(runner, DockerRunner)

    def test_unknown_type_raises_conductor_error(self) -> None:
        with pytest.raises(ConductorError, match="Unknown runner type 'nonexistent'"):
            get_runner("nonexistent")

    def test_error_lists_available_types(self) -> None:
        with pytest.raises(ConductorError, match="Available types:"):
            get_runner("nonexistent")

    def test_returns_fresh_instance_each_call(self) -> None:
        r1 = get_runner("web")
        r2 = get_runner("web")
        assert r1 is not r2


class TestCustomRegistration:
    def test_register_custom_runner(self) -> None:
        class FakeRunner(BaseRunner):
            async def setup(self, ctx):  # type: ignore[override]
                pass

            async def launch(self, ctx):  # type: ignore[override]
                pass

            async def capture(self, ctx, capture_def):  # type: ignore[override]
                pass

            async def teardown(self, ctx):  # type: ignore[override]
                pass

        register_runner("fake-test", FakeRunner)
        try:
            assert "fake-test" in available_runners()
            runner = get_runner("fake-test")
            assert isinstance(runner, FakeRunner)
        finally:
            # Clean up to avoid polluting other tests
            from phantom.runners import _registry

            _registry.pop("fake-test", None)
