"""REPL for interacting with sextant-managed Claude Code agents.

v2.0: mailbox-driven architecture.  /chat <project> switches projects
and shows pending mailbox messages as drafts.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from typing import TYPE_CHECKING

# Ensure line-editing (readline/libedit) is initialized, even when
# input() runs in a background thread via run_in_executor.
try:
    import readline  # noqa: F401
except ImportError:
    pass

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


async def chat(config: "SextantConfig", project_id: str) -> None:
    """Start an interactive REPL session.

    All agents start when SessionManager enters context.  The user interacts
    with one project at a time.  /chat <project> switches the active project
    and shows pending mailbox messages as drafts.

    Session continuation is controlled per-project via sextant.yaml:
    ``continue`` (bool) and ``session_id`` (str).
    """
    import time as _time

    project = config.get_project(project_id)
    t_start = _time.time()
    model = "—"

    print(f"sextant · {project.id}")
    print(f"项目目录: {project.directory}")
    if project.allowed_tools:
        print(f"限制工具: {', '.join(project.allowed_tools)}")
    print("输入消息开始对话 · /chat <项目> 切换 · Ctrl+C 退出\n")

    loop = asyncio.get_running_loop()
    interrupted = asyncio.Event()
    force_quit = False
    mgr_ref: list[SessionManager | None] = [None]

    def _on_sigint() -> None:
        nonlocal force_quit
        if force_quit:
            print("\n强制退出")
            os._exit(1)
        force_quit = True
        interrupted.set()
        if mgr_ref[0] is not None:
            mgr_ref[0].cancel_event.set()

    loop.add_signal_handler(signal.SIGINT, _on_sigint)

    try:
        async with SessionManager(config) as mgr:
            mgr_ref[0] = mgr
            set_manager(mgr)
            mgr.set_current_project(project.id)
            cur_project = project.id  # mutable in closure

            while True:
                streaming = False
                force_quit = False
                interrupted.clear()

                # ---- STATUS BAR (v2.0: + pending counts) ----
                _render_status(cur_project, mgr, model, int(_time.time() - t_start))

                # ---- INPUT PHASE ----
                try:
                    user_input = await _read_line(interrupted)
                except InterruptedError:
                    print(f"\n会话保持中。下次 `sextant chat {cur_project}` 继续。")
                    break
                except EOFError:
                    print(f"\n会话保持中。下次 `sextant chat {cur_project}` 继续。")
                    break

                if not user_input.strip():
                    continue

                # ---- COMMAND HANDLING ----
                if user_input.startswith("/"):
                    result = await _handle_command(user_input, mgr, config, cur_project)
                    if result == "exit":
                        break
                    if result and result != cur_project:
                        # Project switched — update cur_project
                        cur_project = result
                    continue

                # ---- STREAMING PHASE ----
                streaming = True
                try:
                    async for msg in mgr.query(cur_project, user_input):
                        if interrupted.is_set():
                            try:
                                mgr.get_client(cur_project).interrupt()
                            except Exception:
                                pass
                            print("\n  ⏸ 已中断")
                            break

                        if hasattr(msg, "model") and msg.model:
                            model = msg.model

                        _display_message(msg, mgr, cur_project)
                    _render_status(cur_project, mgr, model, int(_time.time() - t_start))
                except Exception as e:
                    print(f"\n[错误] {e}", file=sys.stderr)
                finally:
                    streaming = False
    finally:
        loop.remove_signal_handler(signal.SIGINT)

    os._exit(0)


# ------------------------------------------------------------------
# /chat command: project switching + mailbox draft display
# ------------------------------------------------------------------

async def _do_chat_switch(
    target: str, mgr: SessionManager, config: "SextantConfig", cur_project: str
) -> str | None:
    """Switch to *target* project, show mailbox draft, and wait for user input.

    Returns the new project_id on successful switch, None if cancelled.
    """
    # Validate target project
    if target not in mgr.project_ids:
        print(f"未知项目: {target}。可用项目: {', '.join(mgr.project_ids)}")
        return None

    if target == cur_project:
        print(f"已在 {target} 中。")
        return cur_project

    # Switch active project
    mgr.set_current_project(target)

    # Show pending mailbox messages as draft
    draft = mgr.build_mailbox_draft(target)
    if draft:
        print(f"\n{'─' * 42}")
        print(f"切换到 {target}。{draft}")
        print(f"{'─' * 42}")
        print("> █  ← 按回车发送上述消息，或输入新内容覆盖", end="", flush=True)
    else:
        print(f"\n{'─' * 42}")
        print(f"切换到 {target}。（无待处理消息）")
        print(f"{'─' * 42}")
        # Still need to read input — user might want to say something
        # Return target so caller can continue with empty input handling

    return target


async def _handle_chat_draft_input(mgr: SessionManager, target: str) -> str | None:
    """Read user input for the /chat draft.  Returns the prompt to send, or None to skip."""
    # Capture pending messages BEFORE we mark anything delivered
    pending = mgr.mailbox.get_pending(to=target)

    loop = asyncio.get_running_loop()
    try:
        user_input = await loop.run_in_executor(None, lambda: input())
    except EOFError:
        return None

    user_input = user_input.strip()

    if user_input == "":
        # User pressed Enter — send the drafts as the prompt
        if pending:
            prompt = _build_mailbox_prompt(pending)
            mgr.mark_mailbox_delivered(target)
            return prompt
        return None  # No draft, just switched projects
    else:
        # User typed something — mark delivered, use typed input as prompt
        if pending:
            mgr.mark_mailbox_delivered(target)
        return user_input


def _build_mailbox_prompt(pending_msgs: list[dict]) -> str:
    """Build a clean agent prompt from pending mailbox messages."""
    lines = []
    for msg in pending_msgs:
        lines.append(f"[来自 {msg['from']}] {msg['subject']}")
        lines.append("")
        lines.append(msg['body'])
        lines.append("")
    return "\n".join(lines).strip()


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

async def _read_line(interrupted: asyncio.Event) -> str:
    loop = asyncio.get_running_loop()
    input_future = loop.run_in_executor(None, lambda: input("> "))
    while not input_future.done():
        if interrupted.is_set():
            raise InterruptedError()
        await asyncio.sleep(0.1)
    return input_future.result()


def _display_message(msg, mgr=None, cur_project=None) -> None:
    """Render a single response message to stdout.

    When *mgr* and *cur_project* are provided, captures session_id and
    accumulates cost from ResultMessage for /rename, /fork, /usage.
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
        if _tool_start_times:
            print(
                f"  ⚠ {len(_tool_start_times)} tool(s) without result",
                file=sys.stderr,
            )
            _tool_start_times.clear()
        # Phase 9: capture session metadata
        if msg.session_id and mgr is not None and cur_project:
            mgr._session_ids[cur_project] = msg.session_id
        if msg.total_cost_usd is not None:
            print(f"  ── ${msg.total_cost_usd:.4f} · {msg.stop_reason or 'done'} ──")
            if mgr is not None and cur_project:
                mgr._total_costs[cur_project] = (
                    mgr._total_costs.get(cur_project, 0.0) + msg.total_cost_usd
                )


# ------------------------------------------------------------------
# Rendering helpers
# ------------------------------------------------------------------

_tool_start_times: dict[str, float] = {}
_DIM = "\033[2m"
_GREY = "\033[37m"
_RESET = "\033[0m"


def _render_status(project_id: str, mgr: SessionManager, model: str, uptime_s: int) -> None:
    """Render a one-line status bar with pending message counts for all projects."""
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

    # Phase 7: pending message counts
    pending_info = ""
    try:
        counts = mgr.mailbox.all_pending_counts()
        badges = []
        for pid, count in counts.items():
            if count > 0:
                badges.append(f"{pid}:{count}")
        if badges:
            pending_info = " 📬 " + " ".join(badges)
    except Exception:
        pass

    print(
        f"\n  {_DIM}[{project_id}] {perm} · {model} · {uptime}{pending_info}{_RESET}",
        flush=True,
    )


def _render_thinking(block) -> None:
    text = block.thinking.strip()
    if not text:
        return
    for line in text.split("\n"):
        print(f"\n  {_DIM}{_GREY}💭 {line}{_RESET}", end="", flush=True)
    print()


def _pop_duration(tool_use_id: str) -> str:
    start = _tool_start_times.pop(tool_use_id, None)
    if start is None and _tool_start_times:
        _key, start = _tool_start_times.popitem()
    if start is not None:
        return f" [{time.time() - start:.1f}s]"
    return ""


def _server_tool_description(name: str, inp: dict) -> str:
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


# ------------------------------------------------------------------
# Phase 9: /context helper
# ------------------------------------------------------------------

def _progress_bar(pct: float, width: int = 20) -> str:
    """Draw a Unicode progress bar for context usage."""
    filled = int(round(pct / 100 * width))
    empty = width - filled
    bar = "█" * filled + "░" * empty
    if pct > 90:
        return f"\033[31m{bar}\033[0m"   # red
    if pct > 70:
        return f"\033[33m{bar}\033[0m"   # yellow
    return f"\033[32m{bar}\033[0m"        # green


async def _handle_context(mgr: SessionManager, cur_project: str, show_all: bool = False) -> None:
    """Render context window usage from get_context_usage()."""
    try:
        client = mgr.get_client(cur_project)
        usage = await client.get_context_usage()
    except Exception as e:
        print(f"(无法获取 context 数据: {e})")
        return

    pct = usage.get("percentage", 0)
    bar = _progress_bar(pct)
    print(f"\n  {bar} {pct:.0f}%  {usage['totalTokens']:,d} / {usage['maxTokens']:,d} tokens")
    print(f"  模型: {usage.get('model', '?')}  "
          f"原始窗口: {usage.get('rawMaxTokens', '?'):,d}  "
          f"自动压缩: {'✓' if usage.get('isAutoCompactEnabled') else '✗'}")

    # Category breakdown
    cats = sorted(usage.get("categories", []), key=lambda c: -c["tokens"])
    if cats:
        print()
        for cat in cats:
            if cat["tokens"] > 0:
                pct_cat = cat["tokens"] / max(usage["totalTokens"], 1) * 100
                print(f"  {cat['name']:<22s} {cat['tokens']:>10,d}  ({pct_cat:5.1f}%)")

    if show_all:
        # Memory files
        mem = usage.get("memoryFiles", [])
        if mem:
            print(f"\n  ── 记忆文件 ({len(mem)}) ──")
            for f in mem:
                print(f"  {f.get('path', '?'):<40s} {f.get('tokens', 0):>6,d} tokens  [{f.get('type', '?')}]")

        # MCP tools
        mcp = usage.get("mcpTools", [])
        if mcp:
            print(f"\n  ── MCP 工具 ({len(mcp)}) ──")
            for t in mcp:
                loaded = "✓" if t.get("isLoaded") else "✗"
                print(f"  {t.get('serverName', '?')}:{t.get('name', '?')}  {t.get('tokens', 0):>6,d} tokens  [{loaded}]")

        # Agents
        agents = usage.get("agents", [])
        if agents:
            print(f"\n  ── Agent 定义 ({len(agents)}) ──")
            for a in agents:
                print(f"  {a.get('agentType', '?'):<25s} {a.get('tokens', 0):>6,d} tokens  [{a.get('source', '?')}]")


# ------------------------------------------------------------------
# Command handler
# ------------------------------------------------------------------

async def _handle_command(
    cmd: str, mgr: SessionManager, config: "SextantConfig", cur_project: str
) -> str | None:
    """Handle a slash command.  Returns:
    - "exit" to quit
    - new project_id if project was switched
    - None otherwise
    """
    parts = cmd.strip().split()
    command = parts[0].lower()

    if command == "/help":
        print("命令:")
        print("  /help          — 显示帮助")
        print("  /chat <项目>   — 切换到指定项目（显示待处理消息）")
        print("  /context [all] — 上下文窗口用量")
        print("  /info          — 显示当前 session 信息")
        print("  /perm <模式>   — 切换权限模式 (default|acceptEdits|plan)")
        print("  /model <名称>  — 切换模型")
        print("  /status        — 显示各项目 mailbox 状态")
        print("  /exit          — 退出")
        print("  /clear         — 清屏")
    elif command == "/context":
        show_all = len(parts) > 1 and parts[1] == "all"
        await _handle_context(mgr, cur_project, show_all=show_all)
    elif command == "/chat":
        if len(parts) < 2:
            print("用法: /chat <项目ID>")
            print(f"可用项目: {', '.join(mgr.project_ids)}")
            return None
        target = parts[1]
        result = await _do_chat_switch(target, mgr, config, cur_project)
        if result is None:
            return None
        # Now read user input for the draft
        prompt = await _handle_chat_draft_input(mgr, target)
        if prompt:
            # Send the prompt to the agent
            print()  # newline after input
            try:
                async for msg in mgr.query(target, prompt):
                    _display_message(msg, mgr, target)
            except Exception as e:
                print(f"\n[错误] {e}", file=sys.stderr)
        return target  # switched successfully
    elif command == "/perm":
        mode = parts[1] if len(parts) > 1 else None
        valid = {"default", "acceptEdits", "plan"}
        if mode not in valid:
            print(f"用法: /perm {{{'|'.join(valid)}}}")
            return None
        client = mgr.get_client(cur_project)
        await client.set_permission_mode(mode)
        print(f"权限模式 → {mode}")
    elif command == "/model":
        model_name = parts[1] if len(parts) > 1 else None
        if not model_name:
            print("用法: /model <名称>")
            return None
        client = mgr.get_client(cur_project)
        await client.set_model(model_name)
        print(f"模型 → {model_name}")
    elif command == "/info":
        try:
            client = mgr.get_client(cur_project)
            info = await client.get_server_info()
            print(f"project:  {cur_project}")
            print(f"pid:      {info.get('pid', '?')}")
            print(f"cwd:      {client.options.cwd}")
        except Exception as e:
            print(f"(无法获取 session 信息: {e})")
    elif command == "/status":
        # Show mailbox pending counts for all projects
        try:
            counts = mgr.mailbox.all_pending_counts()
            if not counts:
                print("所有项目均无待处理消息。")
            else:
                print(f"{'项目':<12s} {'待处理':>6s}")
                print("-" * 20)
                for pid, count in sorted(counts.items()):
                    marker = " ← 当前" if pid == cur_project else ""
                    print(f"{pid:<12s} {count:>6d}{marker}")
        except Exception as e:
            print(f"(无法读取 mailbox: {e})")
    elif command == "/clear":
        print("\033[2J\033[H", end="")
    elif command == "/exit":
        return "exit"
    else:
        print(f"未知命令: {command}。输入 /help 查看可用命令。")

    return None
