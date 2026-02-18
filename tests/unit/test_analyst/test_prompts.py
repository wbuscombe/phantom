"""Tests for analyst prompt construction."""

from __future__ import annotations

from phantom.analyst.prompts import build_system_prompt, build_user_prompt


class TestBuildSystemPrompt:
    def test_includes_schema(self) -> None:
        prompt = build_system_prompt("tui")
        assert "project_type" in prompt
        assert "captures" in prompt
        assert "features" in prompt

    def test_tui_guidance(self) -> None:
        prompt = build_system_prompt("tui")
        assert "keystroke" in prompt
        assert "PTY" in prompt
        assert "terminal" in prompt.lower()

    def test_web_guidance(self) -> None:
        prompt = build_system_prompt("web")
        assert "Playwright" in prompt
        assert "CSS selectors" in prompt
        assert "viewport" in prompt.lower()

    def test_docker_guidance(self) -> None:
        prompt = build_system_prompt("docker-compose")
        assert "Docker" in prompt
        assert "reverse proxy" in prompt.lower() or "mapped port" in prompt.lower()

    def test_json_only_instruction(self) -> None:
        prompt = build_system_prompt("web")
        assert "Respond ONLY with the JSON object" in prompt

    def test_unknown_type_defaults_to_web(self) -> None:
        prompt = build_system_prompt("unknown")
        # Falls back to web guidance
        assert "Playwright" in prompt


class TestBuildUserPrompt:
    def test_includes_project_name(self) -> None:
        prompt = build_user_prompt("web", "my-app", [])
        assert "my-app" in prompt

    def test_includes_file_contents(self) -> None:
        files = [
            ("src/app.tsx", "export function App() {}"),
            ("package.json", '{"name": "test"}'),
        ]
        prompt = build_user_prompt("web", "test", files)
        assert "src/app.tsx" in prompt
        assert "export function App()" in prompt
        assert "package.json" in prompt

    def test_includes_existing_readme(self) -> None:
        prompt = build_user_prompt("web", "test", [], existing_readme="# My App\n\nDescription")
        assert "# My App" in prompt
        assert "existing README" in prompt

    def test_truncates_long_readme(self) -> None:
        long_readme = "x" * 5000
        prompt = build_user_prompt("web", "test", [], existing_readme=long_readme)
        assert "truncated" in prompt

    def test_no_readme_section_when_none(self) -> None:
        prompt = build_user_prompt("web", "test", [("f.ts", "code")])
        assert "existing README" not in prompt

    def test_includes_project_type(self) -> None:
        prompt = build_user_prompt("tui", "my-tui", [])
        assert "tui" in prompt
