"""CC Agent SDK session management.

Creates and manages ClaudeSDKClient instances for each project.
For Phase 1: single project only.
"""

import json
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
)


def _load_claude_env() -> dict[str, str]:
    """Load environment variables from ~/.claude/settings.json if available."""
    settings_path = Path.home() / ".claude" / "settings.json"
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        return settings.get("env", {})
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {}


def create_client(project_dir: str, allowed_tools: list[str] | None = None) -> ClaudeSDKClient:
    """Create a ClaudeSDKClient for a single project.

    Args:
        project_dir: Absolute path to the project's working directory.
        allowed_tools: Optional list of tool names to allow (e.g. ['Read', 'Write']).
                       If None, all tools are allowed (permission_mode bypass).

    Returns:
        A ClaudeSDKClient ready to be used as an async context manager.
    """
    opts = ClaudeAgentOptions(
        cwd=project_dir,
        permission_mode="bypassPermissions",
        setting_sources=["project"],  # Load CLAUDE.md from project dir
        continue_conversation=True,
        env=_load_claude_env(),
        # Only restrict tools if explicitly configured
        **(dict(allowed_tools=allowed_tools) if allowed_tools else {}),
    )
    return ClaudeSDKClient(options=opts)
