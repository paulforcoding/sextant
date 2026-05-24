"""CLI entry point for sextant.

Phase 1 commands:
    sextant chat <project>  — start interactive REPL with a project's CC agent
"""

import argparse
import asyncio
import sys

from .config import load_config
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
    """Handle `sextant chat <project>`."""
    config = load_config(args.config)

    try:
        project = config.get_project(args.project)
    except KeyError:
        # Allow direct path as fallback: sextant chat /path/to/project
        from pathlib import Path
        from .config import ProjectConfig
        path = Path(args.project).expanduser().resolve()
        if path.is_dir():
            project = ProjectConfig(
                id=path.name,
                directory=path,
            )
            print(f"使用目录作为项目: {project.id}")
        else:
            print(f"错误: 项目 '{args.project}' 不存在，且路径 '{path}' 不是目录。")
            sys.exit(1)

    await chat(project)
