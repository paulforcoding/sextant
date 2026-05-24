"""P4-6: Three-project E2E test.

Simulates a complete multi-agent collaboration session:
- acp, ncp, third — all connected via SessionManager
- acp → ncp (normal), ncp → third (normal)
- Tests recursion protection: third → acp while acp is in call_stack
- Verifies mailbox records everything
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from claude_agent_sdk import ResultMessage


# ------------------------------------------------------------------
# Mock SDK types
# ------------------------------------------------------------------


@dataclass
class MockBlock:
    text: str


@dataclass
class MockAssistantMessage:
    content: list[Any] = field(default_factory=list)


def _msg(text: str) -> MockAssistantMessage:
    """Shorthand: create an AssistantMessage with one text block."""
    return MockAssistantMessage(content=[MockBlock(text=text)])


# ------------------------------------------------------------------
# Mock ClaudeSDKClient
# ------------------------------------------------------------------


class MockClient:
    """Simulates a ClaudeSDKClient with canned responses."""

    def __init__(self, name: str, responses: list | None = None) -> None:
        self.name = name
        self._queue: list = list(responses) if responses else []
        self._queries: list[str] = []
        self.options = SimpleNamespace(cwd=f"/tmp/{name}")

    async def query(self, prompt: str) -> None:
        self._queries.append(prompt)

    async def receive_response(self):
        """Yield canned responses, then a ResultMessage."""
        for item in self._queue:
            yield item
        yield ResultMessage(
            subtype="success",
            duration_ms=100,
            duration_api_ms=50,
            is_error=False,
            num_turns=1,
            session_id="mock",
            total_cost_usd=0.001,
            stop_reason="end_turn",
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def interrupt(self) -> None:
        pass

    async def get_server_info(self) -> dict:
        return {"pid": 99999, "agents": 1}


# ------------------------------------------------------------------
# Test helpers
# ------------------------------------------------------------------


def _build_mock_manager():
    """Create a SessionManager with mock clients instead of real CC instances.

    We bypass ``__aenter__`` (which creates real SDK clients) and
    directly populate ``_clients``.
    """
    from sextant.session import SessionManager

    # Minimal config-like object
    cfg = SimpleNamespace(projects=[])

    mgr = SessionManager.__new__(SessionManager)
    mgr._config = cfg
    mgr._call_stack = []
    mgr._current_project = None
    mgr.cancel_event = asyncio.Event()
    mgr._mailbox = _mk_mailbox()

    # Create mock agents
    ncp_client = MockClient("ncp", responses=[_msg("ncp 已完成协议同步")])
    third_client = MockClient(
        "third", responses=[_msg("third 已收到通知并更新")]
    )
    acp_client = MockClient("acp")  # won't be queried directly in tests

    mgr._clients = {
        "acp": acp_client,
        "ncp": ncp_client,
        "third": third_client,
    }
    mgr._current_project = "acp"

    # Wire the singleton for send_message tool handler
    from sextant.send_message import set_manager

    set_manager(mgr)

    return mgr


def _mk_mailbox():
    """Create a Mailbox pointed at a temp directory."""
    import tempfile
    from sextant.mailbox import Mailbox

    tmp = Path(tempfile.mkdtemp(prefix="sextant-e2e-"))
    return Mailbox(base_dir=tmp / "mailbox")


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestE2EThreeProjects:
    """End-to-end tests with three simulated projects."""

    async def test_normal_message_acp_to_ncp(self):
        """acp sends a message to ncp and gets a reply."""
        mgr = _build_mock_manager()

        result = await mgr.route_message(
            from_id="acp",
            to="ncp",
            subject="同步协议变更",
            body="proto/auth.proto 已更新，请同步",
        )

        assert result["reply"] == "ncp 已完成协议同步"
        assert result["from"] == "ncp"
        # call stack should be clean
        assert mgr.call_stack == []

    async def test_normal_message_ncp_to_third(self):
        """ncp sends a message to third and gets a reply."""
        mgr = _build_mock_manager()

        # Switch current project to ncp
        mgr._current_project = "ncp"

        result = await mgr.route_message(
            from_id="ncp",
            to="third",
            subject="协议已同步",
            body="请更新你的依赖",
        )

        assert result["reply"] == "third 已收到通知并更新"
        assert result["from"] == "third"

    async def test_recursion_protection(self):
        """If acp → ncp and ncp → acp while acp is in call_stack → recursion resolved."""
        mgr = _build_mock_manager()

        # Simulate: acp is in call_stack (waiting for ncp)
        mgr._call_stack.append("acp")

        result = await mgr.route_message(
            from_id="ncp",
            to="acp",
            subject="Re: 同步协议变更",
            body="协议已同步完成",
        )

        # Should return immediately (recursion protection)
        assert result["reply"] == "协议已同步完成"
        assert result["from"] == "ncp"

    async def test_unknown_project(self):
        """Sending to a non-existent project returns error."""
        mgr = _build_mock_manager()

        result = await mgr.route_message(
            from_id="acp",
            to="nonexistent",
            subject="test",
            body="hello",
        )

        assert "错误" in result["reply"]
        assert result["from"] == "system"

    async def test_mailbox_records_all(self):
        """After multiple exchanges, mailbox has all records."""
        mgr = _build_mock_manager()

        # Exchange 1: acp → ncp
        await mgr.route_message(
            from_id="acp", to="ncp",
            subject="同步协议", body="请同步 proto 变更",
        )

        # Exchange 2: acp → third (ncp simulated as caller since
        # ncp is in _clients and has canned responses)
        mgr._current_project = "acp"
        await mgr.route_message(
            from_id="acp", to="third",
            subject="通知三方", body="协议已更新",
        )

        # Check mailbox
        entries = mgr._mailbox.query()
        assert len(entries) >= 2, f"Expected ≥2 entries, got {len(entries)}"

        # First entry should be acp → ncp
        assert entries[1]["from"] == "acp"
        assert entries[1]["to"] == "ncp"
        assert entries[1]["subject"] == "同步协议"

        # Second entry should be acp → third
        assert entries[0]["from"] == "acp"
        assert entries[0]["to"] == "third"

    async def test_recursion_also_recorded(self):
        """Recursion-protected messages are also recorded in mailbox."""
        mgr = _build_mock_manager()

        mgr._call_stack.append("acp")

        await mgr.route_message(
            from_id="ncp", to="acp",
            subject="Re: 同步", body="已完成",
        )

        entries = mgr._mailbox.query()
        assert len(entries) == 1
        assert entries[0]["from"] == "ncp"
        assert entries[0]["to"] == "acp"
        assert entries[0]["elapsed_ms"] == 0  # instant recursion resolution

    async def test_call_stack_cleanup(self):
        """After route_message completes (or fails), call_stack is cleaned."""
        mgr = _build_mock_manager()

        # Normal message — should clean up
        await mgr.route_message(
            from_id="acp", to="ncp",
            subject="test", body="hello",
        )
        assert mgr.call_stack == []

        # Unknown project — should also clean up
        await mgr.route_message(
            from_id="acp", to="nope",
            subject="test", body="hello",
        )
        assert mgr.call_stack == [], f"call_stack not empty: {mgr.call_stack}"

        # Test that __user__ path works (mock the input)
        # Skip for now — requires mocking input()

    async def test_full_workflow_simulation(self):
        """Simulate a complete multi-agent workflow.

        Scenario:
        1. acp → ncp: "I updated the proto, please sync"
           ncp replies: "ncp 已完成协议同步"
        2. ncp → third: "Protocol synced, update your deps"
           third replies: "third 已收到通知并更新"
        3. Verify call_stack is empty after all exchanges
        4. Verify mailbox has 2 entries
        """
        mgr = _build_mock_manager()

        # Step 1: acp → ncp
        r1 = await mgr.route_message(
            from_id="acp", to="ncp",
            subject="同步协议变更",
            body="proto/auth.proto 已更新",
        )
        assert r1["reply"] == "ncp 已完成协议同步"
        assert r1["from"] == "ncp"

        # Step 2: ncp → third (switch current)
        mgr._current_project = "ncp"
        r2 = await mgr.route_message(
            from_id="ncp", to="third",
            subject="协议已同步",
            body="请更新你的依赖",
        )
        assert r2["reply"] == "third 已收到通知并更新"
        assert r2["from"] == "third"

        # Verify clean state
        assert mgr.call_stack == []

        # Verify mailbox
        entries = mgr._mailbox.query()
        assert len(entries) == 2
        assert entries[1]["from"] == "acp" and entries[1]["to"] == "ncp"
        assert entries[0]["from"] == "ncp" and entries[0]["to"] == "third"


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("P4-6 三项目 E2E 测试")
    print("=" * 60)

    async def _run():
        test = TestE2EThreeProjects()
        cases = [
            ("acp → ncp 正常通信", test.test_normal_message_acp_to_ncp),
            ("ncp → third 正常通信", test.test_normal_message_ncp_to_third),
            ("递归防护", test.test_recursion_protection),
            ("未知项目错误", test.test_unknown_project),
            ("Mailbox 记录全部", test.test_mailbox_records_all),
            ("递归也记录", test.test_recursion_also_recorded),
            ("Call stack 清理", test.test_call_stack_cleanup),
            ("完整工作流模拟", test.test_full_workflow_simulation),
        ]

        failed = 0
        for name, fn in cases:
            try:
                await fn()
                print(f"  ✅ {name}")
            except AssertionError as e:
                failed += 1
                print(f"  ❌ {name}: {e}")
            except Exception as e:
                failed += 1
                print(f"  💥 {name}: {e}")

        print("=" * 60)
        if failed:
            print(f"❌ {failed}/{len(cases)} 失败")
            sys.exit(1)
        else:
            print(f"✅ 全部 {len(cases)} 测试通过")

    asyncio.run(_run())
