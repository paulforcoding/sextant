"""REPL for interacting with a sextant-managed Claude Code agent.

Phase 2: uses SessionManager for multi-agent support.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from typing import TYPE_CHECKING

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from .session import SessionManager
from .send_message import set_manager

if TYPE_CHECKING:
    from .config import ProjectConfig, SextantConfig


async def chat(config: "SextantConfig", project_id: str) -> None:
    """Start an interactive REPL session with a project's CC agent.

    All agents are started when SessionManager enters context.  The user
    interacts with one project at a time; other agents wait in the
    background and respond to ``send_message`` calls.

    Ctrl+C behavior:
    - During input (idle): exits gracefully, all sessions preserved
    - During agent response: interrupts the agent, stays in REPL
    - During response, double Ctrl+C: force exits
    """
    project = config.get_project(project_id)

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
        async with SessionManager(config) as mgr:
            mgr_ref[0] = mgr
            set_manager(mgr)  # wire singleton for tool handler
            mgr.set_current_project(project.id)

            while True:
                streaming = False
                force_quit = False
                interrupted.clear()

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

                        _display_message(msg)
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
    """Render a single response message to stdout."""
    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, TextBlock) and block.text:
                print(block.text, end="", flush=True)
            elif isinstance(block, ToolUseBlock):
                desc = _tool_description(block.name, block.input or {})
                print(f"\n  ⚙ {desc}", end="", flush=True)
    elif isinstance(msg, ResultMessage):
        print()
        if msg.total_cost_usd is not None:
            print(f"  ── ${msg.total_cost_usd:.4f} · {msg.stop_reason or 'done'} ──")


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
        print("  /exit     — 退出")
        print("  /clear    — 清屏")
        print("  /stack    — 显示 call_stack")
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
