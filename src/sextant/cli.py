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
from .mailbox import Mailbox


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

    # sextant mailbox
    mailbox_parser = subparsers.add_parser("mailbox", help="View message history")
    mailbox_parser.add_argument(
        "--project", "-p",
        help="Filter by project ID (from or to)",
    )
    mailbox_parser.add_argument(
        "--tail", "-n",
        type=int, default=20,
        help="Number of recent messages (default: 20)",
    )

    # sextant status
    subparsers.add_parser("status", help="Show project session status")

    args = parser.parse_args()

    if args.command == "chat":
        asyncio.run(_cmd_chat(args))
    elif args.command == "mailbox":
        _cmd_mailbox(args)
    elif args.command == "status":
        _cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


def _cmd_mailbox(args) -> None:
    """Print message history from the mailbox."""
    mbox = Mailbox()
    entries = mbox.query(project=args.project, limit=args.tail)
    if not entries:
        filter_str = f" (filter: {args.project})" if args.project else ""
        print(f"(暂无消息{filter_str})")
        return

    for e in entries:
        ts = e["timestamp"].replace("T", " ").split("+")[0].split(".")[0]
        direction = f"{e['from']} → {e['to']}"
        dur = f"{e['elapsed_ms']}ms" if e.get("elapsed_ms") else "—"
        print(f"{ts}  {direction:20s}  {dur:>8s}  {e['subject']}")


def _cmd_status(args) -> None:
    """Show project session status by inspecting session files."""
    try:
        config = load_config("sextant.yaml")
    except (FileNotFoundError, Exception) as e:
        print(f"无法读取配置: {e}")
        sys.exit(1)

    print(f"{'项目':<12s} {'目录':<40s} {'会话':<8s} {'最后活跃'}")
    print("-" * 80)

    for proj in config.projects:
        proj_dir = Path(proj.directory).expanduser().resolve()
        session_dir = proj_dir / ".claude"

        session_exists = session_dir.is_dir()
        status = "✓" if session_exists else "✗"

        last_active = "—"
        if session_exists:
            # Find most recently modified file in .claude/
            try:
                files = sorted(
                    session_dir.rglob("*"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if files:
                    mtime = files[0].stat().st_mtime
                    from datetime import datetime
                    last_active = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
            except (OSError, PermissionError):
                last_active = "?"

        print(f"{proj.id:<12s} {str(proj_dir):<40s} {status:<8s} {last_active}")


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
