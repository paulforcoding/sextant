"""REPL for interacting with a single Claude Code agent.

Phase 1: simple input → query → stream output loop.
"""

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

from .session import create_client

if TYPE_CHECKING:
    from .config import ProjectConfig


async def chat(config: "ProjectConfig") -> None:
    """Start an interactive REPL session with a project's CC agent.

    Ctrl+C behavior:
    - During input (idle): exits gracefully, session preserved
    - During agent response: interrupts the agent, stays in REPL
    - During response, double Ctrl+C: force exits

    Ctrl+D behavior:
    - Exits gracefully, same as Ctrl+C during idle.

    Why os._exit(0)?  The ``input()`` call runs in a non-daemon thread.
    When Ctrl+C fires, the signal handler sets a flag and the main loop
    exits, but the orphaned input thread blocks Python's clean shutdown.
    ``os._exit(0)`` bypasses the thread-cleanup deadlock.
    """
    client = create_client(
        project_dir=str(config.directory),
        allowed_tools=config.allowed_tools,
    )

    print(f"sextant · {config.id}")
    print(f"项目目录: {config.directory}")
    if config.allowed_tools:
        print(f"限制工具: {', '.join(config.allowed_tools)}")
    print("输入消息开始对话 · Ctrl+C 退出 · 响应中 Ctrl+C 中断\n")

    loop = asyncio.get_running_loop()
    interrupted = asyncio.Event()
    force_quit = False

    def _on_sigint():
        nonlocal force_quit
        if force_quit:
            print("\n强制退出")
            os._exit(1)
        force_quit = True
        interrupted.set()

    loop.add_signal_handler(signal.SIGINT, _on_sigint)

    try:
        async with client:
            while True:
                streaming = False
                force_quit = False
                interrupted.clear()

                # ---- INPUT PHASE ----
                try:
                    user_input = await _read_line(interrupted)
                except InterruptedError:
                    print(f"\n会话保持中。下次 `sextant chat {config.id}` 继续。")
                    break
                except EOFError:
                    print(f"\n会话保持中。下次 `sextant chat {config.id}` 继续。")
                    break

                if not user_input.strip():
                    continue

                if user_input.startswith("/"):
                    await _handle_command(user_input, client)
                    continue

                # ---- STREAMING PHASE ----
                streaming = True
                try:
                    await client.query(user_input)
                    await _stream_response(client, interrupted)
                    if interrupted.is_set():
                        interrupted.clear()
                        force_quit = False
                        continue
                except Exception as e:
                    print(f"\n[错误] {e}", file=sys.stderr)
                finally:
                    streaming = False
    finally:
        loop.remove_signal_handler(signal.SIGINT)

    # Kill orphaned input thread — non-daemon, blocks clean exit
    os._exit(0)


async def _read_line(interrupted: asyncio.Event) -> str:
    """Read a line of input asynchronously, respecting the interrupted flag.

    Polls every 100ms.  If ``interrupted`` is set, raises InterruptedError.
    On Ctrl+D (EOF), raises EOFError.

    Raises:
        InterruptedError: User pressed Ctrl+C.
        EOFError: User pressed Ctrl+D.
    """
    loop = asyncio.get_running_loop()
    input_future = loop.run_in_executor(None, lambda: input("> "))

    while not input_future.done():
        if interrupted.is_set():
            raise InterruptedError()
        await asyncio.sleep(0.1)

    # input() returned normally or raised EOFError
    return input_future.result()


async def _stream_response(client, interrupted: asyncio.Event) -> None:
    """Receive and display agent response.

    Checks ``interrupted`` on each message.  On interrupt, calls
    ``client.interrupt()`` and returns early.
    """
    has_output = False

    async for msg in client.receive_response():
        if interrupted.is_set():
            try:
                client.interrupt()
            except Exception:
                pass
            print("\n  ⏸ 已中断")
            return

        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text:
                    print(block.text, end="", flush=True)
                    has_output = True
                elif isinstance(block, ToolUseBlock):
                    tool_name = block.name
                    tool_input = block.input or {}
                    desc = _tool_description(tool_name, tool_input)
                    print(f"\n  ⚙ {desc}", end="", flush=True)

        elif isinstance(msg, ResultMessage):
            if has_output:
                print()
            if msg.total_cost_usd is not None:
                print(f"  ── ${msg.total_cost_usd:.4f} · {msg.stop_reason or 'done'} ──")
            else:
                print()
            break


def _tool_description(name: str, inp: dict) -> str:
    """Get a human-readable description of a tool call."""
    if name == "Read":
        fp = inp.get("file_path", "?")
        return f"Reading {fp}"
    elif name == "Write":
        fp = inp.get("file_path", "?")
        return f"Writing {fp}"
    elif name == "Edit":
        fp = inp.get("file_path", "?")
        return f"Editing {fp}"
    elif name == "Bash":
        cmd = str(inp.get("command", ""))[:60]
        return f"$ {cmd}"
    elif name == "Grep":
        return f"Searching: {inp.get('pattern', '?')}"
    elif name == "Glob":
        return f"Finding: {inp.get('pattern', '?')}"
    elif name == "WebSearch":
        return f"Web search: {inp.get('query', '?')}"
    elif name == "WebFetch":
        return f"Fetching: {inp.get('url', '?')}"
    else:
        return f"{name}: {str(inp)[:60]}"


async def _handle_command(cmd: str, client) -> None:
    """Handle built-in slash commands."""
    parts = cmd.strip().split()
    command = parts[0].lower()

    if command == "/help":
        print("命令:")
        print("  /help     — 显示帮助")
        print("  /info     — 显示当前 session 信息")
        print("  /exit     — 退出")
        print("  /clear    — 清屏")
    elif command == "/info":
        try:
            info = client.get_server_info()
            print(f"session_id: {info.session_id}")
            print(f"cwd: {client.options.cwd}")
        except Exception as e:
            print(f"(无法获取 session 信息: {e})")
    elif command == "/clear":
        print("\033[2J\033[H", end="")
    elif command == "/exit":
        os._exit(0)
    else:
        print(f"未知命令: {command}。输入 /help 查看可用命令。")
