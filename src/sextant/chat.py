"""REPL for interacting with a sextant-managed Claude Code agent.

Phase 2: uses SessionManager for multi-agent support.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from typing import TYPE_CHECKING

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

from .session import SessionManager
from .send_message import set_manager

if TYPE_CHECKING:
    from .config import ProjectConfig, SextantConfig


async def chat(config: "SextantConfig", project_id: str, *, resume: str | None = None) -> None:
    """Start an interactive REPL session with a project's CC agent.

    All agents are started when SessionManager enters context.  The user
    interacts with one project at a time; other agents wait in the
    background and respond to ``send_message`` calls.

    Args:
        config: Parsed sextant configuration.
        project_id: Which project to interact with.
        resume: Optional session UUID to resume.
    """
    import time as _time

    project = config.get_project(project_id)
    t_start = _time.time()
    model = "—"

    print(f"sextant · {project.id}")
    print(f"项目目录: {project.directory}")
    if project.allowed_tools:
        print(f"限制工具: {', '.join(project.allowed_tools)}")
    print("输入消息开始对话 · Ctrl+C 退出 · 响应中 Ctrl+C 中断\n")

    loop = asyncio.get_running_loop()
    interrupted = asyncio.Event()
    force_quit = False
    mgr_ref: list[SessionManager | None] = [None]  # mutable ref for signal handler

    def _on_sigint() -> None:
        nonlocal force_quit
        if force_quit:
            print("\n强制退出")
            os._exit(1)
        force_quit = True
        interrupted.set()
        # Also cancel any pending __user__ prompt
        if mgr_ref[0] is not None:
            mgr_ref[0].cancel_event.set()

    loop.add_signal_handler(signal.SIGINT, _on_sigint)

    try:
        async with SessionManager(config, resume=resume) as mgr:
            mgr_ref[0] = mgr
            set_manager(mgr)  # wire singleton for tool handler
            mgr.set_current_project(project.id)

            while True:
                streaming = False
                force_quit = False
                interrupted.clear()

                # ---- STATUS BAR ----
                _render_status(project.id, mgr, model, int(_time.time() - t_start))

                # ---- INPUT PHASE ----
                try:
                    user_input = await _read_line(interrupted)
                except InterruptedError:
                    print(f"\n会话保持中。下次 `sextant chat {project.id}` 继续。")
                    break
                except EOFError:
                    print(f"\n会话保持中。下次 `sextant chat {project.id}` 继续。")
                    break

                if not user_input.strip():
                    continue

                if user_input.startswith("/"):
                    await _handle_command(user_input, mgr)
                    continue

                # ---- STREAMING PHASE ----
                streaming = True
                try:
                    async for msg in mgr.query(project.id, user_input):
                        if interrupted.is_set():
                            try:
                                mgr.get_client(project.id).interrupt()
                            except Exception:
                                pass
                            print("\n  ⏸ 已中断")
                            break

                        # Track model for status bar
                        if hasattr(msg, "model") and msg.model:
                            model = msg.model

                        _display_message(msg)
                    # Post-response status update
                    _render_status(project.id, mgr, model, int(_time.time() - t_start))
                except Exception as e:
                    print(f"\n[错误] {e}", file=sys.stderr)
                finally:
                    streaming = False
    finally:
        loop.remove_signal_handler(signal.SIGINT)

    # Kill orphaned input thread — non-daemon, blocks clean exit
    os._exit(0)


# ------------------------------------------------------------------
# Internal helpers (unchanged from Phase 1)
# ------------------------------------------------------------------

async def _read_line(interrupted: asyncio.Event) -> str:
    loop = asyncio.get_running_loop()
    input_future = loop.run_in_executor(None, lambda: input("> "))
    while not input_future.done():
        if interrupted.is_set():
            raise InterruptedError()
        await asyncio.sleep(0.1)
    return input_future.result()


def _display_message(msg) -> None:
    """Render a single response message to stdout.

    Handles all ``AssistantMessage.content`` block types:
    - TextBlock          → inline text
    - ThinkingBlock      → 💭 grey indented
    - ToolUseBlock       → ⚙ tool call (records start time)
    - ToolResultBlock    → ✓/❌ with duration (matched by tool_use_id)
    - ServerToolUseBlock → 🔧 MCP tool call
    - ServerToolResultBlock → ✓ with duration
    """
    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, ThinkingBlock):
                _render_thinking(block)
            elif isinstance(block, TextBlock) and block.text:
                print(block.text, end="", flush=True)
            elif isinstance(block, ToolUseBlock):
                _tool_start_times[block.id] = time.time()
                desc = _tool_description(block.name, block.input or {})
                print(f"\n  ⚙ {desc}", end="", flush=True)
            elif isinstance(block, ToolResultBlock):
                duration = _pop_duration(block.tool_use_id)
                if block.is_error:
                    print(f"\n     ❌{duration}")
                else:
                    print(f"\n     ✓{duration}")
            elif isinstance(block, ServerToolUseBlock):
                _tool_start_times[f"srv_{block.id}"] = time.time()
                desc = _server_tool_description(block.name, block.input or {})
                print(f"\n  🔧 {desc}", end="", flush=True)
            elif isinstance(block, ServerToolResultBlock):
                duration = _pop_duration(f"srv_{block.tool_use_id}")
                print(f"\n     ✓{duration}")
    elif isinstance(msg, ResultMessage):
        print()
        # Warn about orphaned tool timers
        if _tool_start_times:
            print(
                f"  ⚠ {len(_tool_start_times)} tool(s) without result",
                file=sys.stderr,
            )
            _tool_start_times.clear()
        if msg.total_cost_usd is not None:
            print(f"  ── ${msg.total_cost_usd:.4f} · {msg.stop_reason or 'done'} ──")


# ------------------------------------------------------------------
# Rendering helpers (P4-1 / P4-2)
# ------------------------------------------------------------------

# tool_use_id → wall-clock start (for duration display)
_tool_start_times: dict[str, float] = {}

# ANSI escape
_DIM = "\033[2m"
_GREY = "\033[37m"
_RESET = "\033[0m"


def _render_status(project_id: str, mgr, model: str, uptime_s: int) -> None:
    """Render a one-line status bar at the bottom of the TUI."""
    try:
        client = mgr.get_client(project_id)
        perm = client.options.permission_mode if hasattr(client.options, "permission_mode") else "?"
    except Exception:
        perm = "?"
    mm, ss = divmod(uptime_s, 60)
    hh, mm = divmod(mm, 60)
    if hh:
        uptime = f"{hh}h{mm:02d}m"
    else:
        uptime = f"{mm}m{ss:02d}s"
    print(
        f"\n  {_DIM}[{project_id}] {perm} · {model} · {uptime}{_RESET}",
        flush=True,
    )


def _render_thinking(block) -> None:
    """Render a ThinkingBlock as dim grey indented lines."""
    text = block.thinking.strip()
    if not text:
        return
    for line in text.split("\n"):
        print(f"\n  {_DIM}{_GREY}💭 {line}{_RESET}", end="", flush=True)
    print()


def _pop_duration(tool_use_id: str) -> str:
    """Pop the start time for *tool_use_id* and return a formatted duration string."""
    start = _tool_start_times.pop(tool_use_id, None)
    if start is not None:
        return f" [{time.time() - start:.1f}s]"
    return ""


def _server_tool_description(name: str, inp: dict) -> str:
    """Human-readable description for a server-side (MCP) tool call."""
    if name == "web_search":
        return f"🔍 {inp.get('searchTerm', inp.get('query', '?'))}"
    if name == "web_fetch":
        return f"📄 {inp.get('url', '?')}"
    if name == "bash_code_execution":
        return f"$ {str(inp.get('command', ''))[:60]}"
    if name == "code_execution":
        return f"💻 {str(inp.get('code', ''))[:40]}…"
    if name == "text_editor_code_execution":
        return f"✏️ {str(inp.get('command', ''))[:60]}"
    if name == "tool_search_tool_regex":
        return f"🔎 regex: {inp.get('pattern', '?')}"
    if name == "tool_search_tool_bm25":
        return f"🔎 bm25: {inp.get('pattern', '?')}"
    if name == "advisor":
        return "🤔 advisor"
    # Generic fallback
    return f"{name}: {str(inp)[:60]}"


def _tool_description(name: str, inp: dict) -> str:
    if name == "send_message":
        to = inp.get("to", "?")
        subj = str(inp.get("subject", ""))[:50]
        return f"📬 → {to}: {subj}"
    if name == "Read":
        return f"Reading {inp.get('file_path', '?')}"
    if name == "Write":
        return f"Writing {inp.get('file_path', '?')}"
    if name == "Edit":
        return f"Editing {inp.get('file_path', '?')}"
    if name == "Bash":
        return f"$ {str(inp.get('command', ''))[:60]}"
    if name == "Grep":
        return f"Searching: {inp.get('pattern', '?')}"
    if name == "Glob":
        return f"Finding: {inp.get('pattern', '?')}"
    if name == "WebSearch":
        return f"Web search: {inp.get('query', '?')}"
    if name == "WebFetch":
        return f"Fetching: {inp.get('url', '?')}"
    return f"{name}: {str(inp)[:60]}"


async def _handle_command(cmd: str, mgr: SessionManager) -> None:
    parts = cmd.strip().split()
    command = parts[0].lower()

    if command == "/help":
        print("命令:")
        print("  /help     — 显示帮助")
        print("  /info     — 显示当前 session 信息")
        print("  /perm     — 切换权限模式 (default|acceptEdits|plan)")
        print("  /model    — 切换模型")
        print("  /exit     — 退出")
        print("  /clear    — 清屏")
        print("  /stack    — 显示 call_stack")
    elif command == "/perm":
        mode = parts[1] if len(parts) > 1 else None
        valid = {"default", "acceptEdits", "plan"}
        if mode not in valid:
            print(f"用法: /perm {{{'|'.join(valid)}}}")
            return
        client = mgr.get_client(mgr.current_project)
        await client.set_permission_mode(mode)
        print(f"权限模式 → {mode}")
    elif command == "/model":
        model_name = parts[1] if len(parts) > 1 else None
        if not model_name:
            print("用法: /model <名称>")
            return
        client = mgr.get_client(mgr.current_project)
        await client.set_model(model_name)
        print(f"模型 → {model_name}")
    elif command == "/info":
        pid = mgr.current_project
        try:
            client = mgr.get_client(pid)
            info = await client.get_server_info()
            print(f"project:  {pid}")
            print(f"pid:      {info.get('pid', '?')}")
            print(f"cwd:      {client.options.cwd}")
        except Exception as e:
            print(f"(无法获取 session 信息: {e})")
    elif command == "/stack":
        print(f"call_stack: {mgr.call_stack}")
    elif command == "/clear":
        print("\033[2J\033[H", end="")
    elif command == "/exit":
        os._exit(0)
    else:
        print(f"未知命令: {command}。输入 /help 查看可用命令。")
