"""Configuration parsing tests — load_config, ProjectConfig, SextantConfig."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml


# ------------------------------------------------------------------
# ProjectConfig
# ------------------------------------------------------------------

class TestProjectConfig:
    def test_id_derived_from_directory_name(self):
        from sextant.config import ProjectConfig

        pc = ProjectConfig(directory=Path("/tmp/my-project"))
        assert pc.id == "my-project"

    def test_id_with_deep_path(self):
        from sextant.config import ProjectConfig

        pc = ProjectConfig(directory=Path("/a/b/c/nested-project"))
        assert pc.id == "nested-project"

    def test_default_values(self):
        from sextant.config import ProjectConfig

        pc = ProjectConfig(directory=Path("/tmp/test"))
        assert pc.allowed_tools is None
        assert pc.permission_mode is None
        assert pc.continue_conversation is True
        assert pc.session_id is None

    def test_explicit_values(self):
        from sextant.config import ProjectConfig

        pc = ProjectConfig(
            directory=Path("/tmp/test"),
            allowed_tools=["Bash", "Read"],
            permission_mode="acceptEdits",
            continue_conversation=False,
            session_id="sess-123",
        )
        assert pc.allowed_tools == ["Bash", "Read"]
        assert pc.permission_mode == "acceptEdits"
        assert pc.continue_conversation is False
        assert pc.session_id == "sess-123"


# ------------------------------------------------------------------
# SextantConfig
# ------------------------------------------------------------------

class TestSextantConfig:
    def test_empty_projects_list(self):
        from sextant.config import SextantConfig

        cfg = SextantConfig()
        assert cfg.projects == []
        assert cfg.permission_mode is None

    def test_get_project_found(self):
        from sextant.config import ProjectConfig, SextantConfig

        p1 = ProjectConfig(directory=Path("/tmp/proj-a"))
        p2 = ProjectConfig(directory=Path("/tmp/proj-b"))
        cfg = SextantConfig(projects=[p1, p2])

        found = cfg.get_project("proj-b")
        assert found is p2
        assert found.id == "proj-b"

    def test_get_project_not_found_raises_keyerror(self):
        from sextant.config import ProjectConfig, SextantConfig

        p1 = ProjectConfig(directory=Path("/tmp/proj-a"))
        cfg = SextantConfig(projects=[p1])

        with pytest.raises(KeyError, match="not found in config"):
            cfg.get_project("nonexistent")

    def test_get_project_keyerror_message_lists_available(self):
        from sextant.config import ProjectConfig, SextantConfig

        p1 = ProjectConfig(directory=Path("/tmp/proj-a"))
        p2 = ProjectConfig(directory=Path("/tmp/proj-b"))
        cfg = SextantConfig(projects=[p1, p2])

        with pytest.raises(KeyError) as exc_info:
            cfg.get_project("proj-c")
        assert "proj-a" in str(exc_info.value)
        assert "proj-b" in str(exc_info.value)


# ------------------------------------------------------------------
# _parse_raw
# ------------------------------------------------------------------

class TestParseRaw:
    def test_single_project_minimal(self):
        from sextant.config import _parse_raw

        raw = {
            "projects": [
                {"directory": "/tmp/my-project"},
            ],
        }
        cfg = _parse_raw(raw)
        assert len(cfg.projects) == 1
        p = cfg.projects[0]
        assert p.id == "my-project"
        assert p.continue_conversation is True  # default
        assert p.allowed_tools is None
        assert p.permission_mode is None

    def test_multiple_projects(self):
        from sextant.config import _parse_raw

        raw = {
            "projects": [
                {"directory": "/tmp/proj-a"},
                {"directory": "/tmp/proj-b"},
            ],
        }
        cfg = _parse_raw(raw)
        assert len(cfg.projects) == 2
        assert [p.id for p in cfg.projects] == ["proj-a", "proj-b"]

    def test_project_with_all_fields(self):
        from sextant.config import _parse_raw

        raw = {
            "projects": [
                {
                    "directory": "/tmp/full-project",
                    "allowed_tools": ["Bash", "Read", "Write"],
                    "permission_mode": "bypassPermissions",
                    "continue": False,
                    "session_id": "abc123",
                },
            ],
            "permission_mode": "default",
        }
        cfg = _parse_raw(raw)
        assert cfg.permission_mode == "default"
        p = cfg.projects[0]
        assert p.allowed_tools == ["Bash", "Read", "Write"]
        assert p.permission_mode == "bypassPermissions"
        assert p.continue_conversation is False
        assert p.session_id == "abc123"

    def test_expands_home_directory(self):
        from sextant.config import _parse_raw

        raw = {
            "projects": [
                {"directory": "~/projects/test-project"},
            ],
        }
        cfg = _parse_raw(raw)
        p = cfg.projects[0]
        assert str(p.directory) == str(Path.home() / "projects" / "test-project")

    def test_no_projects_key(self):
        from sextant.config import _parse_raw

        cfg = _parse_raw({})
        assert cfg.projects == []


# ------------------------------------------------------------------
# load_config
# ------------------------------------------------------------------

class TestLoadConfig:
    def make_yaml(self, content: dict) -> Path:
        """Write a temporary sextant.yaml and return its path."""
        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        yaml_path = tmp / "sextant.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(content, f)
        return yaml_path

    def test_loads_from_given_path(self):
        from sextant.config import load_config

        yaml_path = self.make_yaml({
            "projects": [{"directory": "/tmp/some-project"}],
        })

        cfg = load_config(yaml_path)
        assert len(cfg.projects) == 1
        assert cfg.projects[0].id == "some-project"

    def test_raises_filenotfound_when_no_file(self):
        from sextant.config import load_config

        with pytest.raises(FileNotFoundError, match="sextant.yaml not found"):
            load_config("/nonexistent/path/sextant.yaml")

    def test_permission_mode_top_level(self):
        from sextant.config import load_config

        yaml_path = self.make_yaml({
            "permission_mode": "plan",
            "projects": [{"directory": "/tmp/p"}],
        })

        cfg = load_config(yaml_path)
        assert cfg.permission_mode == "plan"
