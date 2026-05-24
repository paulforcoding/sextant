"""Configuration parsing for sextant."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ProjectConfig:
    """A single project configuration."""
    id: str
    directory: Path
    allowed_tools: Optional[list[str]] = None


@dataclass
class SextantConfig:
    """Top-level sextant configuration."""
    projects: list[ProjectConfig] = field(default_factory=list)

    def get_project(self, project_id: str) -> ProjectConfig:
        """Look up a project by ID. Raises KeyError if not found."""
        for p in self.projects:
            if p.id == project_id:
                return p
        raise KeyError(f"Project '{project_id}' not found in config. Available: {[p.id for p in self.projects]}")


def load_config(path: str | Path = "sextant.yaml") -> SextantConfig:
    """Load sextant configuration from a YAML file.

    Searches for sextant.yaml in these locations (in order):
    1. The given path (default: ./sextant.yaml)
    2. ~/.config/sextant/sextant.yaml
    3. XDG_CONFIG_HOME/sextant/sextant.yaml
    """
    search_paths = [
        Path(path),
        Path.home() / ".config" / "sextant" / "sextant.yaml",
    ]
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        search_paths.insert(2, Path(xdg) / "sextant" / "sextant.yaml")

    for p in search_paths:
        if p.exists():
            with open(p) as f:
                raw = yaml.safe_load(f)
            return _parse_raw(raw)

    raise FileNotFoundError(
        f"sextant.yaml not found. Looked in: {[str(p) for p in search_paths]}"
    )


def _parse_raw(raw: dict) -> SextantConfig:
    """Parse raw YAML dict into SextantConfig, deriving project_id from directory if needed."""
    projects = []
    for entry in raw.get("projects", []):
        dir_path = Path(entry["directory"]).expanduser().resolve()
        project_id = entry.get("id") or dir_path.name
        projects.append(ProjectConfig(
            id=project_id,
            directory=dir_path,
            allowed_tools=entry.get("allowed_tools"),
        ))
    return SextantConfig(projects=projects)
