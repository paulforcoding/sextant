"""CLI entry point for sextant.

Phase 2 commands:
    sextant chat <project>  — start interactive REPL (all agents start in background)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import ProjectConfig, load_config
from .chat import chat


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sextant",
        description="Multi-project agent collaboration tool",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # sextant chat <project>
    chat_parser = subparsers.add_parser("chat", help="Start interactive session with a project")
    chat_parser.add_argument(
        "project",
        help="Project ID (from sextant.yaml) or path to project directory",
    )
    chat_parser.add_argument(
        "-c", "--config",
        default="sextant.yaml",
        help="Path to sextant.yaml (default: ./sextant.yaml)",
    )

    args = parser.parse_args()

    if args.command == "chat":
        asyncio.run(_cmd_chat(args))
    else:
        parser.print_help()
        sys.exit(1)


async def _cmd_chat(args) -> None:
    config = load_config(args.config)

    # Look up the project by ID or fall back to direct path
    project_id: str
    try:
        config.get_project(args.project)
        project_id = args.project
    except KeyError:
        path = Path(args.project).expanduser().resolve()
        if path.is_dir():
            project_id = path.name
            # Synthesize a one-shot config entry so SessionManager sees it
            config.projects.append(ProjectConfig(
                id=project_id,
                directory=path,
            ))
            print(f"使用目录作为项目: {project_id}")
        else:
            print(f"错误: 项目 '{args.project}' 不存在，且路径 '{path}' 不是目录。")
            sys.exit(1)

    await chat(config, project_id)
