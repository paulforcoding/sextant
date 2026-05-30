"""Pure-function tests for session.py helpers that don't need a live CC agent."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest


# ------------------------------------------------------------------
# _load_claude_env
# ------------------------------------------------------------------

class TestLoadClaudeEnv:
    def test_loads_env_from_valid_json(self, monkeypatch, tmp_path):
        """Valid settings.json with env key returns env dict."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_file = settings_dir / "settings.json"
        settings_file.write_text(json.dumps({
            "env": {"ANTHROPIC_API_KEY": "test-key", "DEBUG": "1"}
        }))

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        from sextant.session import _load_claude_env
        env = _load_claude_env()
        assert env == {"ANTHROPIC_API_KEY": "test-key", "DEBUG": "1"}

    def test_returns_empty_when_file_missing(self, monkeypatch, tmp_path):
        """Missing settings.json returns empty dict."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        from sextant.session import _load_claude_env
        env = _load_claude_env()
        assert env == {}

    def test_returns_empty_when_json_invalid(self, monkeypatch, tmp_path):
        """Corrupted JSON returns empty dict."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_file = settings_dir / "settings.json"
        settings_file.write_text("{invalid json")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        from sextant.session import _load_claude_env
        env = _load_claude_env()
        assert env == {}

    def test_returns_empty_when_env_key_missing(self, monkeypatch, tmp_path):
        """settings.json without 'env' key returns empty dict."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_file = settings_dir / "settings.json"
        settings_file.write_text(json.dumps({"other": "data"}))

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        from sextant.session import _load_claude_env
        env = _load_claude_env()
        assert env == {}


# ------------------------------------------------------------------
# _format_tool_for_user
# ------------------------------------------------------------------

class TestFormatToolForUser:
    def test_bash_with_command_and_description(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("Bash", {
            "command": "pytest --cov",
            "description": "Run tests with coverage",
        })
        assert "$ pytest --cov" in result
        assert "Run tests with coverage" in result

    def test_bash_without_description(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("Bash", {
            "command": "ls -la",
        })
        assert "$ ls -la" in result

    def test_write(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("Write", {
            "file_path": "/tmp/test.py",
            "content": "print('hello')",
        })
        assert "📄" in result
        assert "/tmp/test.py" in result
        assert "print('hello')" in result

    def test_edit(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("Edit", {
            "file_path": "/tmp/test.py",
            "old_string": "old code",
            "new_string": "new code",
        })
        assert "✏️" in result
        assert "old code" in result
        assert "new code" in result

    def test_read(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("Read", {
            "file_path": "/tmp/doc.md",
        })
        assert "📖" in result
        assert "/tmp/doc.md" in result

    def test_grep(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("Grep", {
            "pattern": "TODO",
        })
        assert "🔍" in result
        assert "TODO" in result

    def test_glob(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("Glob", {
            "pattern": "*.py",
        })
        assert "🔎" in result
        assert "*.py" in result

    def test_websearch(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("WebSearch", {
            "query": "python pytest",
        })
        assert "🌐" in result
        assert "python pytest" in result

    def test_webfetch(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("WebFetch", {
            "url": "https://example.com",
        })
        assert "📄" in result
        assert "https://example.com" in result

    def test_unknown_tool_fallback(self):
        from sextant.session import _format_tool_for_user

        result = _format_tool_for_user("CustomTool", {
            "key": "value",
        })
        assert "CustomTool" in result
        assert "key" in result


# ------------------------------------------------------------------
# _build_system_prompt
# ------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_includes_project_name(self):
        from sextant.session import _build_system_prompt

        prompt = _build_system_prompt("acp", [])
        assert "**acp**" in prompt

    def test_lists_other_projects(self):
        from sextant.session import _build_system_prompt

        p1 = SimpleNamespace(id="ncp")
        p2 = SimpleNamespace(id="xcp")
        prompt = _build_system_prompt("acp", [p1, p2])
        assert "`ncp`" in prompt
        assert "`xcp`" in prompt

    def test_excludes_own_project_from_list(self):
        from sextant.session import _build_system_prompt

        p1 = SimpleNamespace(id="acp")
        p2 = SimpleNamespace(id="ncp")
        prompt = _build_system_prompt("acp", [p1, p2])
        # Should only mention ncp, not acp itself
        assert "`ncp`" in prompt
        assert prompt.count("`acp`") == 0  # own project not in "other" list
        assert "send_message" in prompt

    def test_no_other_projects(self):
        from sextant.session import _build_system_prompt

        prompt = _build_system_prompt("solo", [])
        assert "send_message" in prompt
        assert "仅在用户明确要求时" in prompt


# ------------------------------------------------------------------
# SessionManager properties (pure, no CC SDK needed)
# ------------------------------------------------------------------

class TestSessionManagerProperties:
    @pytest.fixture
    def mgr(self):
        from sextant.config import ProjectConfig, SextantConfig
        from sextant.session import SessionManager

        p1 = ProjectConfig(directory=Path("/tmp/test-proj"))
        cfg = SextantConfig(projects=[p1])
        mgr = SessionManager(cfg)
        return mgr

    def test_init_stores_config(self, mgr):
        assert mgr._config is not None
        assert len(mgr._config.projects) == 1

    def test_init_creates_mailbox(self, mgr):
        assert mgr._mailbox is not None

    def test_init_empty_clients(self, mgr):
        assert mgr._clients == {}

    def test_current_project_initial_none(self, mgr):
        assert mgr.current_project is None

    def test_project_ids_empty_initially(self, mgr):
        assert mgr.project_ids == []

    def test_mailbox_property(self, mgr):
        assert mgr.mailbox is mgr._mailbox

    def test_set_current_project_unknown_raises(self, mgr):
        with pytest.raises(KeyError, match="Unknown project"):
            mgr.set_current_project("nonexistent")

    def test_cancel_event_created(self, mgr):
        import asyncio
        assert isinstance(mgr.cancel_event, asyncio.Event)


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    sys.exit(exit_code)
