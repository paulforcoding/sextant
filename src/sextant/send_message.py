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
        "向其他项目的 Agent 发送消息并同步等待回复。"
        "调用后会阻塞直到目标 Agent 处理完毕，返回其文本回复。"
        "to='__user__' 可以向真人用户提问（阻塞等待）。"
    ),
    input_schema={
        "to": str,
        "subject": str,
        "body": str,
    },
)
async def send_message_handler(args: dict) -> dict:
    """MCP tool handler.  Delegates to SessionManager.route_message()."""
    global _manager

    # P5: unconditional entry log to stderr
    import sys as _sys
    print("[DEBUG] send_message_handler ENTERED", file=_sys.stderr, flush=True)

    # P5: debug log for permission_prompt_tool_name format discovery
    import json as _json
    print(
        f"[DEBUG] send_message args: {_json.dumps(args, ensure_ascii=False)}",
        file=_sys.stderr, flush=True,
    )

    to = args.get("to", "__user__")  # fallback: permission prompts may omit 'to'
    subject = args.get("subject", args.get("tool_name", "?"))
    body = args.get("body", _json.dumps(args.get("input", args), ensure_ascii=False))

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
# Public API for chat.py
# ------------------------------------------------------------------

send_message_tool = send_message_handler  # alias for SDK registration
