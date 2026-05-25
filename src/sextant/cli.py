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
    chat_parser.add_argument(
        "--continue", dest="continue_session",
        action="store_true",
        help="Continue the most recent session (default: True)",
    )
    chat_parser.add_argument(
        "--resume", dest="resume",
        nargs="?", const="__picker__",
        help="Resume a specific session by ID, or show picker if no ID given",
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

    # sextant web
    web_parser = subparsers.add_parser("web", help="Start web UI")
    web_parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    web_parser.add_argument(
        "--port", type=int, default=5008,
        help="Port (default: 5008)",
    )
    web_parser.add_argument(
        "-c", "--config",
        default="sextant.yaml",
        help="Path to sextant.yaml (default: ./sextant.yaml)",
    )
    web_parser.add_argument(
        "--debug", action="store_true",
        help="Enable Flask debug mode",
    )

    args = parser.parse_args()

    if args.command == "chat":
        asyncio.run(_cmd_chat(args))
    elif args.command == "mailbox":
        _cmd_mailbox(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "web":
        _cmd_web(args)
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
    """Show project session status and mailbox pending counts."""
    try:
        config = load_config("sextant.yaml")
    except (FileNotFoundError, Exception) as e:
        print(f"无法读取配置: {e}")
        sys.exit(1)

    # Also check mailbox for pending counts
    try:
        mbox = Mailbox()
        counts = mbox.all_pending_counts()
    except Exception:
        counts = {}

    print(f"{'项目':<12s} {'待处理':>6s} {'会话':<6s} {'最后活跃'}")
    print("-" * 62)

    for proj in config.projects:
        proj_dir = Path(proj.directory).expanduser().resolve()
        session_dir = proj_dir / ".claude"

        session_exists = session_dir.is_dir()
        status = "✓" if session_exists else "✗"
        pending = counts.get(proj.id, 0)
        pending_str = str(pending) if pending > 0 else "—"

        last_active = "—"
        if session_exists:
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

        print(f"{proj.id:<12s} {pending_str:>6s} {status:<6s} {last_active}")


def _cmd_web(args) -> None:
    """Start the sextant web UI."""
    from .web_server import run_web
    print(f"sextant web · http://{args.host}:{args.port}")
    run_web(config_path=args.config, host=args.host, port=args.port, debug=args.debug)


async def _cmd_chat(args) -> None:
    config = load_config(args.config)

    # Resolve resume target
    resume_id: str | None = None
    if args.resume:
        if args.resume == "__picker__":
            resume_id = _pick_session(args.project)
            if resume_id is None:
                return
        else:
            resume_id = args.resume

    # Look up the project by ID or fall back to direct path
    project_id: str
    try:
        config.get_project(args.project)
        project_id = args.project
    except KeyError:
        path = Path(args.project).expanduser().resolve()
        if path.is_dir():
            project_id = path.name
            config.projects.append(ProjectConfig(
                directory=path,
            ))
            print(f"使用目录作为项目: {project_id}")
        else:
            print(f"错误: 项目 '{args.project}' 不存在，且路径 '{path}' 不是目录。")
            sys.exit(1)

    # --resume overrides the target project's session settings
    if resume_id:
        proj = config.get_project(project_id)
        proj.session_id = resume_id
        proj.continue_conversation = True

    await chat(config, project_id)


def _workspace_slug(project_dir: str | Path) -> str:
    """Derive CC workspace slug from a project directory path."""
    return "-" + str(Path(project_dir).expanduser().resolve()).replace("/", "-")


def _pick_session(project_arg: str) -> str | None:
    """Scan CC session store for a project and let user pick."""
    from datetime import datetime

    # Resolve project directory
    proj_path = Path(project_arg).expanduser().resolve()
    if not proj_path.is_dir():
        try:
            config = load_config("sextant.yaml")
            proj = config.get_project(project_arg)
            proj_path = Path(proj.directory).expanduser().resolve()
        except (FileNotFoundError, KeyError):
            print(f"找不到项目: {project_arg}")
            return None

    slug = _workspace_slug(proj_path)
    sessions_dir = Path.home() / ".claude" / "projects" / slug
    if not sessions_dir.is_dir():
        print(f"没有找到会话记录: {sessions_dir}")
        return None

    # Collect sessions from JSONL files
    sessions: list[dict] = []
    for f in sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        sid = f.stem
        try:
            with open(f) as fh:
                first = fh.readline()
                data = {"id": sid, "mtime": f.stat().st_mtime}
                import json as _json
                try:
                    entry = _json.loads(first)
                    data["first_prompt"] = str(entry.get("message", {}).get("content", ""))[:60]
                except _json.JSONDecodeError:
                    pass
                sessions.append(data)
        except (OSError, PermissionError):
            pass

    if not sessions:
        print("没有找到会话记录")
        return None

    print(f"\n{'#':<4s} {'时间':<20s} {'开头':<62s}")
    print("-" * 88)
    for i, s in enumerate(sessions[:20], 1):
        ts = datetime.fromtimestamp(s["mtime"]).strftime("%m-%d %H:%M:%S")
        preview = s.get("first_prompt", "—")
        print(f"{i:<4d} {ts:<20s} {preview:<62s}")

    try:
        choice = input(f"\n选择会话 (1-{min(len(sessions), 20)}, Enter=取消): ").strip()
        if not choice:
            return None
        idx = int(choice) - 1
        return sessions[idx]["id"]
    except (ValueError, IndexError):
        return None
