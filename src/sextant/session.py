"""CC Agent SDK session manager.

Phase 2: manages multiple ClaudeSDKClient instances, each with an
in-process MCP server that provides the ``send_message`` tool.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    create_sdk_mcp_server,
)

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
            async for msg in mgr.query("hello"):
                ...

    All agents are started and shut down together.  Each agent gets
    an in-process MCP server with the ``send_message`` tool.
    """

    def __init__(self, config: SextantConfig):
        self._config = config
        # project_id → ClaudeSDKClient
        self._clients: dict[str, ClaudeSDKClient] = {}
        # Stack of project_ids currently blocked on send_message.
        # Top-of-stack is the project that will receive the next direct
        # reply.  Used for recursion protection (P4).
        self._call_stack: list[str] = []
        # Currently active project (for send_message to know its caller).
        self._current_project: str | None = None

    # -- public ----------------------------------------------------

    @property
    def current_project(self) -> str | None:
        return self._current_project

    def set_current_project(self, project_id: str) -> None:
        if project_id not in self._clients:
            raise KeyError(f"Unknown project: {project_id}")
        self._current_project = project_id

    @property
    def call_stack(self) -> list[str]:
        return list(self._call_stack)

    # -- context manager -------------------------------------------

    async def __aenter__(self) -> "SessionManager":
        # 1. Build the send_message tool (import deferred to break circular dep)
        from .send_message import send_message_tool

        mcp_server = create_sdk_mcp_server(
            name="sextant",
            version="0.1.0",
            tools=[send_message_tool],
        )

        # 2. Create one SDK client per project
        for project in self._config.projects:
            opts = ClaudeAgentOptions(
                cwd=str(project.directory),
                permission_mode="bypassPermissions",
                setting_sources=["project"],
                continue_conversation=True,
                env=_load_claude_env(),
                mcp_servers={"sextant": mcp_server},
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

    # -- send_message routing (called by the MCP tool handler) ----

    async def route_message(
        self, from_id: str, to: str, subject: str, body: str
    ) -> dict:
        """Inject a message into the target agent and wait for the reply.

        Returns a dict suitable as an MCP tool result, e.g.::

            {"reply": "...", "from": "ncp"}

        Handles:
        - Recursion protection: if **to** is anywhere in the call stack,
          treat the message as the awaited reply and return immediately.
        - ``__user__``: defers to Phase 3 (returns a placeholder for now).
        """
        if to == "__user__":
            return {"reply": "(用户未回复 — __user__ 待 Phase 3)", "from": "__user__"}

        if to not in self._clients:
            return {"reply": f"错误: 项目 '{to}' 不存在", "from": "system"}

        # --- recursion protection ---
        if to in self._call_stack:
            # The target is currently blocked waiting for a reply.
            # This message IS the reply — return it directly.
            return {"reply": body, "from": from_id}

        # --- normal injection ---
        self._call_stack.append(from_id)
        try:
            prompt = (
                f"📬 来自 **{from_id}** 的消息\n\n"
                f"**主题**: {subject}\n\n"
                f"{body}\n\n"
                f"---\n"
                f"请处理此消息。完成后，调用 "
                f"`send_message(to='{from_id}', subject='Re: {subject}', body='你的完整回复')`。"
            )

            target = self._clients[to]
            await target.query(prompt)

            # Collect the full output
            parts: list[str] = []
            async for msg in target.receive_response():
                if hasattr(msg, "content"):
                    for block in msg.content:
                        if hasattr(block, "text") and block.text:
                            parts.append(block.text)
                elif isinstance(msg, ResultMessage):
                    pass  # end of stream

            reply_text = "".join(parts).strip() or "(目标 Agent 无文本输出)"
            return {"reply": reply_text, "from": to}

        except Exception as exc:
            return {"reply": f"(错误: {exc})", "from": "system"}
        finally:
            self._call_stack.pop()


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _build_system_prompt(project_id: str, projects) -> str:
    """Build the appended system prompt for a project's agent."""
    other = [p.id for p in projects if p.id != project_id]
    lines = [
        f"你的项目是 **{project_id}**。",
        "",
    ]
    if other:
        other_list = "、".join(f"`{o}`" for o in other)
        lines.append(
            f"你可以通过 `send_message(to, subject, body)` 向以下合作项目发送消息并等待回复："
            f"{other_list}。"
        )
    else:
        lines.append("当前没有其他合作项目。")

    lines.extend([
        "",
        "向 `__user__` 发送消息可以询问真人用户。",
        "收到的消息会直接显示在对话中。",
        "如果连续两次无法从当前对话方获得有效回复，请向 `__user__` 发起升级询问。",
    ])
    return "\n".join(lines)
