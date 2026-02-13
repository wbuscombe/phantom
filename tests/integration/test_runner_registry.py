"""Integration tests for the runner plugin registry."""

from __future__ import annotations

import pytest

from phantom.runners import available_runners, get_runner
from phantom.runners.base import BaseRunner


@pytest.mark.integration
class TestRegistryIntegration:
    def test_registry_includes_all_builtins(self) -> None:
        runners = available_runners()
        assert "web" in runners
        assert "tui" in runners
        assert "docker-compose" in runners

    def test_get_runner_returns_base_runner_instances(self) -> None:
        for type_name in available_runners():
            runner = get_runner(type_name)
            assert isinstance(runner, BaseRunner)

    def test_get_runner_returns_fresh_instances(self) -> None:
        r1 = get_runner("web")
        r2 = get_runner("web")
        assert r1 is not r2
        assert type(r1) is type(r2)
