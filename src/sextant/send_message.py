"""The single MCP tool that powers all agent-to-agent communication.

``send_message`` is the only MCP tool exposed by sextant.  When an agent
calls it, sextant injects the message into the target agent's conversation
and blocks until the target finishes processing, then returns the target's
full text output as the tool result.

Recursion protection (``_call_stack``): if the target is currently blocked
waiting for a reply from the sender, the message is treated as that reply
and returned immediately (no re-injection).
"""

from __future__ import annotations

import sys as _sys
from typing import Optional

from claude_agent_sdk import tool

# Module-level reference set during session creation.
# Avoids a hard circular import with session.py.
_manager: "SessionManager | None" = None  # noqa: F821


def set_manager(manager: "SessionManager") -> None:  # noqa: F821
    """Wire the SessionManager singleton so the tool handler can route."""
    global _manager
    _manager = manager


# ------------------------------------------------------------------
# Tool definition
# ------------------------------------------------------------------

@tool(
    name="send_message",
    description=(
        "通用消息/权限网关。\n"
        "发送消息: to='项目ID'|'__user__', subject, body。\n"
        "权限审批: tool_name, input。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "目标项目ID 或 __user__"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "tool_name": {"type": "string"},
            "input": {"type": "object"},
        },
    },
)
async def send_message_handler(args: dict) -> dict:
    """MCP tool handler.  Delegates to SessionManager.route_message().

    Also handles CC permission requests (routed via
    ``permission_prompt_tool_name``).
    """
    global _manager

    # P5: debug log
    import json as _json
    print("[DEBUG] send_message_handler ENTERED", file=_sys.stderr, flush=True)
    print(
        f"[DEBUG] send_message args: {_json.dumps(args, ensure_ascii=False)}",
        file=_sys.stderr, flush=True,
    )

    # ── detect permission request ──────────────────────────────────
    if "tool_name" in args and "to" not in args:
        return await _handle_permission_request(args)

    # ── normal send_message ────────────────────────────────────────
    to = args.get("to", "__user__")
    subject = args.get("subject", "?")
    body = args.get("body", "")

    if _manager is None:
        return {
            "reply": "(sextant 内部错误: SessionManager 未初始化)",
            "from": "system",
        }

    from_id = _manager.current_project
    if from_id is None:
        return {
            "reply": "(sextant 内部错误: 未设置 current_project)",
            "from": "system",
        }

    result = await _manager.route_message(
        from_id=from_id, to=to, subject=subject, body=body
    )

    return {
        "content": [{"type": "text", "text": f"{result['reply']}"}],
        "reply": result["reply"],
        "from": result["from"],
    }


# ------------------------------------------------------------------
# Permission request handler (P5)
# ------------------------------------------------------------------


async def _handle_permission_request(args: dict) -> dict:
    """Handle a CC permission request routed through our tool.

    CC calls this tool (via ``--permission-prompt-tool``) with:
        {"tool_name": "Bash", "input": {"command": "rm ..."}, ...}

    We block and ask the human user for approval.
    """
    global _manager

    if _manager is None:
        return {"reply": "(无法处理: SessionManager 未初始化)", "from": "system"}

    tool_name = args.get("tool_name", "?")
    tool_input = args.get("input", {})

    # Format the permission prompt for the user
    import json as _json
    subject = f"允许 {tool_name}?"
    body = f"{tool_name}: {_json.dumps(tool_input, ensure_ascii=False)[:300]}"

    from_id = _manager.current_project or "?"
    result = await _manager.route_message(
        from_id=from_id, to="__user__", subject=subject, body=body
    )

    # Interpret user response
    reply = result.get("reply", "").strip().lower()
    if reply in ("y", "yes", "是", "允许", "可以", "ok", "好"):
        # CC expects a clean MCP response to proceed
        return {"content": [{"type": "text", "text": "ok"}]}
    return {
        "content": [{"type": "text", "text": "用户拒绝"}],
        "isError": True,
    }


# ------------------------------------------------------------------
# Public API for chat.py
# ------------------------------------------------------------------

send_message_tool = send_message_handler  # alias for SDK registration
