"""The single MCP tool that powers agent-to-agent communication.

v2.0: ``send_message`` writes to the recipient's mailbox and returns immediately.
No blocking, no route_message, no recursion protection needed.

The recipient sees the message as a draft when the user runs ``/chat <project>``.
"""

from __future__ import annotations

from claude_agent_sdk import tool

from .mailbox import Mailbox

# Module-level references set during session creation.
_manager: "SessionManager | None" = None  # noqa: F821
_mailbox: Mailbox | None = None


def set_manager(manager: "SessionManager") -> None:  # noqa: F821
    """Wire the SessionManager singleton so the tool handler can access config."""
    global _manager
    _manager = manager


def set_mailbox(mbox: Mailbox) -> None:
    """Wire the Mailbox singleton."""
    global _mailbox
    _mailbox = mbox


# ------------------------------------------------------------------
# Tool definition
# ------------------------------------------------------------------

@tool(
    name="send_message",
    description=(
        "向其他项目发送消息。消息会投递到对方的收件箱，对方下次查看时会看到。\n"
        "用法: to='项目ID', subject, body。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "目标项目ID"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    },
)
async def send_message_handler(args: dict) -> dict:
    """MCP tool handler.  Writes to mailbox and returns ack immediately."""
    global _manager, _mailbox

    to = args["to"]
    subject = args["subject"]
    body = args["body"]

    if _manager is None:
        return {
            "status": "error",
            "message": "sextant 内部错误: SessionManager 未初始化",
        }

    from_id = _manager.current_project
    if from_id is None:
        return {
            "status": "error",
            "message": "sextant 内部错误: 未设置 current_project",
        }

    # Validate recipient
    if to not in _manager.project_ids:
        return {
            "status": "error",
            "message": f"项目 '{to}' 不存在。可用项目: {', '.join(_manager.project_ids)}",
        }

    # Write to mailbox
    if _mailbox is None:
        return {
            "status": "error",
            "message": "sextant 内部错误: Mailbox 未初始化",
        }

    msg_id = _mailbox.record(from_id=from_id, to=to, subject=subject, body=body)

    return {
        "content": [{"type": "text", "text": f"消息已发送给 {to}（msg_id: {msg_id}）"}],
        "status": "sent",
        "msg_id": msg_id,
        "to": to,
    }


# ------------------------------------------------------------------
# Public API for chat.py / session.py
# ------------------------------------------------------------------

send_message_tool = send_message_handler  # alias for SDK registration
