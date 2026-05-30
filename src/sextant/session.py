"""CC Agent SDK session manager.

v2.0: mailbox-driven architecture.  Agents communicate via send_message →
mailbox; /chat command delivers pending messages as drafts.  No more
synchronous route_message, call_stack, or recursion protection.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from .mailbox import Mailbox

if TYPE_CHECKING:
    from .config import SextantConfig


# ------------------------------------------------------------------
# CLI-side helpers — kept module-level to avoid circular imports.
# ------------------------------------------------------------------

def _load_claude_env() -> dict[str, str]:
    """Load environment variables from ~/.claude/settings.json."""
    settings_path = Path.home() / ".claude" / "settings.json"
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        return settings.get("env", {})
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {}


# ═══════════════════════════════════════════════════════════════════
# SessionManager
# ═══════════════════════════════════════════════════════════════════

class SessionManager:
    """Manages all Claude Code agent sessions for sextant projects.

    Lifecycle
    ---------
    Use as an async context manager::

        async with SessionManager(config) as mgr:
            mgr.set_current_project("acp")
            async for msg in mgr.query("acp", "hello"):
                ...

    All agents are started and shut down together.  Each agent gets
    an in-process MCP server with the ``send_message`` tool.
    """

    def __init__(self, config: SextantConfig):
        self._config = config
        # project_id → ClaudeSDKClient
        self._clients: dict[str, ClaudeSDKClient] = {}
        # Currently active project (the one the user is chatting with).
        self._current_project: str | None = None
        # Set by the REPL to cancel a user prompt (Ctrl+C).
        self.cancel_event: asyncio.Event = asyncio.Event()
        # v2.0: Mailbox is the single source of truth for messages.
        self._mailbox = Mailbox()
        # Phase 9: per-project session metadata captured from ResultMessage.
        self._session_ids: dict[str, str] = {}
        self._total_costs: dict[str, float] = {}
        self._last_costs: dict[str, float] = {}

    # -- public ----------------------------------------------------

    @property
    def current_project(self) -> str | None:
        return self._current_project

    @property
    def project_ids(self) -> list[str]:
        return list(self._clients.keys())

    @property
    def mailbox(self) -> Mailbox:
        return self._mailbox

    def set_current_project(self, project_id: str) -> None:
        if project_id not in self._clients:
            raise KeyError(f"Unknown project: {project_id}")
        self._current_project = project_id

    # -- context manager -------------------------------------------

    async def __aenter__(self) -> "SessionManager":
        # 1. Build the send_message tool (import deferred to break circular dep)
        from .send_message import send_message_tool, set_mailbox

        mcp_server = create_sdk_mcp_server(
            name="sextant",
            version="0.2.0",
            tools=[send_message_tool],
        )

        # Wire the mailbox singleton
        set_mailbox(self._mailbox)

        # ── canUseTool: intercept ALL tool calls for user approval ──
        manager_ref = self  # closure capture

        async def can_use_tool(
            tool_name: str, input_data: dict, context: ToolPermissionContext
        ) -> PermissionResultAllow | PermissionResultDeny:
            # Always allow our own MCP tool
            if tool_name == "send_message":
                return PermissionResultAllow(updated_input=input_data)

            # Handle CC asking the user questions
            if tool_name == "AskUserQuestion":
                return await manager_ref._handle_ask_user_question(input_data)

            # All other tools → ask user
            desc = _format_tool_for_user(tool_name, input_data)
            reply = await manager_ref._prompt_user(
                from_id=manager_ref._current_project or "?",
                subject=f"允许 {tool_name}?",
                body=desc,
            )
            if reply in ("y", "yes", "是", "允许", "可以", "ok", "好"):
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(message=f"用户拒绝了 {tool_name}")

        # 2. Create one SDK client per project
        for project in self._config.projects:
            opts = ClaudeAgentOptions(
                cwd=str(project.directory),
                permission_mode=project.permission_mode or self._config.permission_mode or "default",
                setting_sources=["project"],
                continue_conversation=project.continue_conversation,
                resume=project.session_id,
                env=_load_claude_env(),
                mcp_servers={"sextant": mcp_server},
                can_use_tool=can_use_tool,
                system_prompt={
                    "type": "preset",
                    "preset": "claude_code",
                    "append": _build_system_prompt(project.id, self._config.projects),
                },
                **(dict(allowed_tools=project.allowed_tools) if project.allowed_tools else {}),
            )
            client = ClaudeSDKClient(options=opts)
            await client.__aenter__()
            self._clients[project.id] = client
            print(f"  ✓ {project.id:12s} → {project.directory}", file=sys.stderr)

        return self

    async def __aexit__(self, *args) -> None:
        errors: list[Exception] = []
        for pid, client in self._clients.items():
            try:
                await client.__aexit__(*args)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("SessionManager shutdown errors", errors)

    # -- agent interaction -----------------------------------------

    async def query(self, project_id: str, prompt: str):
        """Inject a prompt into an agent and yield response messages.

        Yields the same types as ``ClaudeSDKClient.receive_response()``:
        AssistantMessage, SystemMessage, ResultMessage.
        """
        client = self._clients[project_id]
        await client.query(prompt)
        async for msg in client.receive_response():
            yield msg

    def get_client(self, project_id: str) -> ClaudeSDKClient:
        return self._clients[project_id]

    # -- mailbox prompt assembly (v2.0) ----------------------------

    def build_mailbox_draft(self, project_id: str) -> str | None:
        """Build a draft prompt from pending mailbox messages for *project_id*.

        Returns None if there are no pending messages.
        """
        pending = self._mailbox.get_pending(to=project_id)
        if not pending:
            return None

        lines = [f"你有 {len(pending)} 条待处理消息：", ""]
        for msg in pending:
            lines.append(f"[来自 {msg['from']}] {msg['subject']}")
            lines.append("")
            lines.append(msg["body"])
            lines.append("")

        lines.append("─" * 40)
        return "\n".join(lines)

    def mark_mailbox_delivered(self, project_id: str) -> None:
        """Mark all pending messages for *project_id* as delivered."""
        pending = self._mailbox.get_pending(to=project_id)
        if pending:
            self._mailbox.mark_delivered([m["msg_id"] for m in pending])

    # -- user prompt (used by canUseTool) ---------------------------

    async def _prompt_user(self, from_id: str, subject: str, body: str) -> str:
        """Display a prompt to the human user and wait for their reply.

        Races ``cancel_event`` against the input future so Ctrl+C skips
        gracefully.
        """
        print(flush=True)
        print("─" * 40, flush=True)
        print(f"🤔 **{from_id}**：{subject}", flush=True)
        print(f"   {body}", flush=True)
        print("─" * 40, flush=True)

        self.cancel_event.clear()
        loop = asyncio.get_running_loop()
        input_future = loop.run_in_executor(None, lambda: input("> "))

        done, _pending = await asyncio.wait(
            [input_future, loop.create_task(self.cancel_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if input_future in done and not self.cancel_event.is_set():
            try:
                return input_future.result().strip()
            except EOFError:
                return "n"
        else:
            input_future.cancel()
            print("\n  ⏸ (已取消)", flush=True)
            return "n"

    # -- AskUserQuestion handler (for canUseTool) --------------------

    async def _handle_ask_user_question(
        self, input_data: dict
    ) -> PermissionResultAllow:
        """Handle CC's AskUserQuestion tool via canUseTool."""
        questions = input_data.get("questions", [])
        answers: dict[str, str] = {}

        for q in questions:
            header = q.get("header", "?")
            question = q.get("question", "?")
            options = q.get("options", [])

            lines = [f"{header}: {question}", ""]
            for i, opt in enumerate(options, 1):
                desc = opt.get("description", "")
                lines.append(f"  {i}. {opt['label']}" + (f" — {desc}" if desc else ""))

            reply = await self._prompt_user(
                from_id=self._current_project or "?",
                subject=header,
                body="\n".join(lines),
            )
            # Try numeric selection first, fall back to free-text
            try:
                idx = int(reply) - 1
                if 0 <= idx < len(options):
                    answers[question] = options[idx]["label"]
                else:
                    answers[question] = reply
            except ValueError:
                answers[question] = reply

        return PermissionResultAllow(
            updated_input={"questions": questions, "answers": answers}
        )


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _format_tool_for_user(tool_name: str, input_data: dict) -> str:
    """Format a tool call for user-facing permission prompt."""
    if tool_name == "Bash":
        cmd = input_data.get("command", "?")
        desc = input_data.get("description", "")
        return f"$ {cmd}" + (f"\n  {desc}" if desc else "")
    if tool_name == "Write":
        content = str(input_data.get("content", ""))[:200]
        return f"📄 {input_data.get('file_path', '?')}\n  {content}"
    if tool_name == "Edit":
        old_s = str(input_data.get("old_string", ""))[:100]
        new_s = str(input_data.get("new_string", ""))[:100]
        return f"✏️ {input_data.get('file_path', '?')}\n  -{old_s}\n  +{new_s}"
    if tool_name == "Read":
        return f"📖 {input_data.get('file_path', '?')}"
    if tool_name == "Grep":
        return f"🔍 {input_data.get('pattern', '?')}"
    if tool_name == "Glob":
        return f"🔎 {input_data.get('pattern', '?')}"
    if tool_name == "WebSearch":
        return f"🌐 {input_data.get('query', '?')}"
    if tool_name == "WebFetch":
        return f"📄 {input_data.get('url', '?')}"
    import json as _json
    return f"{tool_name}: {_json.dumps(input_data, ensure_ascii=False)[:200]}"


def _build_system_prompt(project_id: str, projects) -> str:
    """Build the appended system prompt for a project's agent.

    v2.0: no __user__ concept, no "please reply with send_message" instructions.
    Agents just need to know send_message exists for outgoing messages.
    """
    other = [p.id for p in projects if p.id != project_id]
    lines = [
        f"你的项目是 **{project_id}**。",
        "",
    ]
    if other:
        other_list = "、".join(f"`{o}`" for o in other)
        lines.append(
            f"你可以通过 `send_message(to, subject, body)` 向以下合作项目发送消息："
            f"{other_list}。消息发送后对方会在下次查看时收到。"
        )
    lines.extend([
        "",
        "仅在用户明确要求时使用 send_message 发送消息给其他项目。",
        "用户会通过弹窗审批你的操作和回答问题。",
    ])
    return "\n".join(lines)
