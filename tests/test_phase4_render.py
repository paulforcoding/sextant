"""Phase 4 rendering tests — using real SDK types for isinstance matching."""

from __future__ import annotations

import io
import re
import sys
import time

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


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _capture(fn, *args, **kwargs):
    """Capture stdout while calling fn."""
    old = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    try:
        fn(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue()


def test_thinking_block():
    from sextant.chat import _display_message

    out = _capture(
        _display_message,
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="我需要先查看当前 proto 文件", signature="sig")
            ],
            model="test",
        ),
    )
    plain = _strip_ansi(out)
    assert "💭" in plain, f"Expected 💭 in: {plain!r}"
    assert "proto" in plain
    assert "\033[2m" in out, f"DIM code missing: {out!r}"
    assert "\033[37m" in out, f"GREY code missing: {out!r}"
    # ✅ ThinkingBlock


def test_thinking_multiline():
    from sextant.chat import _display_message

    out = _capture(
        _display_message,
        AssistantMessage(
            content=[
                ThinkingBlock(
                    thinking="第一行思考\n第二行思考\n第三行思考", signature="sig"
                )
            ],
            model="test",
        ),
    )
    plain = _strip_ansi(out)
    assert plain.count("💭") == 3, f"Expected 3 💭, got {plain.count('💭')}: {plain!r}"
    # ✅ ThinkingBlock 多行


def test_empty_thinking():
    from sextant.chat import _display_message

    out = _capture(
        _display_message,
        AssistantMessage(
            content=[ThinkingBlock(thinking="   ", signature="sig")], model="test"
        ),
    )
    plain = _strip_ansi(out)
    assert "💭" not in plain, f"Expected no 💭: {plain!r}"
    # ✅ 空 ThinkingBlock


def test_tool_use_and_result():
    from sextant.chat import _display_message, _tool_start_times

    _tool_start_times.clear()
    tool_id = "tool_001"

    # Use: display tool call
    out_use = _capture(
        _display_message,
        AssistantMessage(
            content=[
                ToolUseBlock(
                    id=tool_id, name="Read", input={"file_path": "/proto/auth.proto"}
                )
            ],
            model="test",
        ),
    )
    plain_use = _strip_ansi(out_use)
    assert "⚙" in plain_use, f"Expected ⚙: {plain_use!r}"
    # Record a fake start time manually (simulating prior ToolUseBlock having
    # been processed).  _display_message for ToolUseBlock records time.time(),
    # but then _tool_start_times[tool_id] has been updated.  We overwrite it.
    _tool_start_times[tool_id] = time.time() - 1.234

    # Result: should show duration
    out_res = _capture(
        _display_message,
        AssistantMessage(
            content=[ToolResultBlock(tool_use_id=tool_id, is_error=False)],
            model="test",
        ),
    )
    plain_res = _strip_ansi(out_res)
    assert "✓" in plain_res, f"Expected ✓: {plain_res!r}"
    assert (
        "1.2s" in plain_res or "1.3s" in plain_res
    ), f"Expected ~1.2s: {plain_res!r}"
    # ✅ ToolUse + ToolResult 耗时


def test_tool_error():
    from sextant.chat import _display_message, _tool_start_times

    _tool_start_times.clear()
    tid = "tool_err"
    _tool_start_times[tid] = time.time() - 0.543

    out = _capture(
        _display_message,
        AssistantMessage(
            content=[ToolResultBlock(tool_use_id=tid, is_error=True)], model="test"
        ),
    )
    plain = _strip_ansi(out)
    assert "❌" in plain, f"Expected ❌: {plain!r}"
    assert "0.5s" in plain or "0.6s" in plain, f"Expected ~0.5s: {plain!r}"
    # ✅ Tool 错误


def test_server_tool_use():
    from sextant.chat import _display_message

    out = _capture(
        _display_message,
        AssistantMessage(
            content=[
                ServerToolUseBlock(
                    id="srv_1",
                    name="web_search",
                    input={"searchTerm": "Python asyncio patterns"},
                )
            ],
            model="test",
        ),
    )
    plain = _strip_ansi(out)
    assert "🔧" in plain, f"Expected 🔧: {plain!r}"
    assert "Python asyncio" in plain, f"Expected 'Python asyncio': {plain!r}"
    # ✅ ServerToolUseBlock


def test_server_tool_result():
    from sextant.chat import _display_message, _tool_start_times

    _tool_start_times.clear()
    _tool_start_times["srv_sr_1"] = time.time() - 2.01

    out = _capture(
        _display_message,
        AssistantMessage(
            content=[
                ServerToolResultBlock(
                    tool_use_id="sr_1", content={"type": "text", "text": "done"}
                )
            ],
            model="test",
        ),
    )
    plain = _strip_ansi(out)
    assert "✓" in plain, f"Expected ✓: {plain!r}"
    # ✅ ServerToolResultBlock


def test_result_message():
    from sextant.chat import _display_message, _tool_start_times

    _tool_start_times.clear()

    out = _capture(
        _display_message,
        ResultMessage(
            subtype="success",
            duration_ms=1234,
            duration_api_ms=800,
            is_error=False,
            num_turns=3,
            session_id="test-session",
            total_cost_usd=0.0456,
            stop_reason="end_turn",
        ),
    )
    plain = _strip_ansi(out)
    assert "$0.0456" in plain, f"Expected cost: {plain!r}"
    assert "end_turn" in plain, f"Expected stop_reason: {plain!r}"
    # ✅ ResultMessage


def test_orphaned_timer_warning():
    from sextant.chat import _display_message, _tool_start_times

    _tool_start_times.clear()
    _tool_start_times["orphan"] = time.time()

    _capture(
        _display_message,
        ResultMessage(
            subtype="success",
            duration_ms=100,
            duration_api_ms=50,
            is_error=False,
            num_turns=1,
            session_id="x",
        ),
    )
    assert _tool_start_times == {}, f"Expected cleared: {_tool_start_times}"
    # ✅ 孤立 timer 清理


def test_full_stream():
    """Simulate a complete agent response — all block types."""
    from sextant.chat import _display_message, _tool_start_times

    _tool_start_times.clear()
    tid = "stream_tool"
    sid = "stream_srv"

    _tool_start_times[tid] = time.time() - 0.854
    _tool_start_times[f"srv_{sid}"] = time.time() - 1.520

    stream = [
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="我会帮你改 proto 协议", signature="s")
            ],
            model="test",
        ),
        AssistantMessage(
            content=[
                TextBlock(text="让我先查看当前文件。\n\n"),
                ToolUseBlock(
                    id=tid, name="Read", input={"file_path": "/proto/auth.proto"}
                ),
            ],
            model="test",
        ),
        AssistantMessage(
            content=[ToolResultBlock(tool_use_id=tid)],
            model="test",
        ),
        AssistantMessage(
            content=[
                ServerToolUseBlock(
                    id=sid,
                    name="web_search",
                    input={"searchTerm": "protobuf best practices"},
                )
            ],
            model="test",
        ),
        AssistantMessage(
            content=[ServerToolResultBlock(tool_use_id=sid, content={"type": "text", "text": "ok"})],
            model="test",
        ),
        ResultMessage(
            subtype="success",
            duration_ms=500,
            duration_api_ms=300,
            is_error=False,
            num_turns=2,
            session_id="stream-session",
            total_cost_usd=0.0123,
            stop_reason="end_turn",
        ),
    ]

    out = _capture(lambda: [_display_message(m) for m in stream])
    plain = _strip_ansi(out)

    assert "💭" in plain, "Missing thinking block"
    assert "⚙" in plain, "Missing tool call"
    assert "✓" in plain, "Missing tool result"
    assert "🔧" in plain, "Missing server tool"
    assert "$0.0123" in plain, "Missing cost"
    # ✅ 完整流模拟


# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    print("Phase 4 渲染测试")
    print("=" * 50)

    tests = [
        test_thinking_block,
        test_thinking_multiline,
        test_empty_thinking,
        test_tool_use_and_result,
        test_tool_error,
        test_server_tool_use,
        test_server_tool_result,
        test_result_message,
        test_orphaned_timer_warning,
        test_full_stream,
    ]

    failed = 0
    for fn in tests:
        try:
            result = fn()
            print(f"  {result}")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  💥 {fn.__name__}: {e}")

    print("=" * 50)
    if failed:
        print(f"❌ {failed}/{len(tests)} 失败")
        sys.exit(1)
    else:
        print(f"✅ 全部 {len(tests)} 测试通过")
