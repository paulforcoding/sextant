"""v2.0 E2E tests: mailbox-driven architecture.

Key changes from v1.x:
- No route_message / call_stack / recursion protection
- send_message writes to mailbox, returns ack
- get_pending / mark_delivered manage message lifecycle
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest


# ------------------------------------------------------------------
# Mailbox tests
# ------------------------------------------------------------------


class TestMailbox:
    """Mailbox: write, get_pending, mark_delivered, query."""

    def test_record_and_get_pending(self):
        from sextant.mailbox import Mailbox

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        # Record a message
        msg_id = mbox.record(
            from_id="acp", to="ncp",
            subject="同步协议", body="请修改服务端代码",
        )
        assert msg_id.startswith("m_")

        # get_pending should return it
        pending = mbox.get_pending(to="ncp")
        assert len(pending) == 1
        assert pending[0]["from"] == "acp"
        assert pending[0]["subject"] == "同步协议"
        assert pending[0]["body"] == "请修改服务端代码"
        assert pending[0]["status"] == "pending"

        # Other projects have no pending messages
        assert mbox.get_pending(to="xcp") == []

    def test_mark_delivered(self):
        from sextant.mailbox import Mailbox

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        msg_id = mbox.record(from_id="acp", to="ncp", subject="test", body="hello")
        assert len(mbox.get_pending(to="ncp")) == 1

        mbox.mark_delivered([msg_id])
        assert mbox.get_pending(to="ncp") == []

    def test_get_pending_count(self):
        from sextant.mailbox import Mailbox

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        mbox.record(from_id="acp", to="ncp", subject="a", body="1")
        mbox.record(from_id="xcp", to="ncp", subject="b", body="2")
        mbox.record(from_id="acp", to="xcp", subject="c", body="3")

        assert mbox.get_pending_count(to="ncp") == 2
        assert mbox.get_pending_count(to="xcp") == 1
        assert mbox.get_pending_count(to="acp") == 0

    def test_all_pending_counts(self):
        from sextant.mailbox import Mailbox

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        mbox.record(from_id="acp", to="ncp", subject="a", body="1")
        mbox.record(from_id="acp", to="ncp", subject="b", body="2")
        mbox.record(from_id="ncp", to="xcp", subject="c", body="3")

        counts = mbox.all_pending_counts()
        assert counts == {"ncp": 2, "xcp": 1}

    def test_query(self):
        from sextant.mailbox import Mailbox

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        mbox.record(from_id="acp", to="ncp", subject="a", body="1")
        mbox.record(from_id="ncp", to="xcp", subject="b", body="2")

        entries = mbox.query()
        assert len(entries) == 2

        entries = mbox.query(project="acp")
        assert len(entries) == 1
        assert entries[0]["from"] == "acp"


# ------------------------------------------------------------------
# send_message tool tests
# ------------------------------------------------------------------


class TestSendMessage:
    """send_message: writes to mailbox, returns ack, validates recipients."""

    @pytest.fixture
    def mock_mgr(self):
        """Create a minimal mock SessionManager for testing send_message."""
        from sextant.mailbox import Mailbox
        from sextant.send_message import set_manager, set_mailbox

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")
        set_mailbox(mbox)

        # Build a mock manager with project_ids
        mgr = SimpleNamespace()
        mgr.current_project = "acp"
        mgr.project_ids = ["acp", "ncp", "xcp"]
        set_manager(mgr)

        return mgr, mbox

    @pytest.mark.asyncio
    async def test_send_message_success(self, mock_mgr):
        from sextant.send_message import send_message_handler

        mgr, mbox = mock_mgr
        # SdkMcpTool wraps the handler; access via .handler
        fn = send_message_handler.handler
        result = await fn({
            "to": "ncp",
            "subject": "同步协议",
            "body": "请修改服务端代码",
        })

        assert result["status"] == "sent"
        assert result["to"] == "ncp"
        assert result["msg_id"].startswith("m_")

        # Verify in mailbox
        pending = mbox.get_pending(to="ncp")
        assert len(pending) == 1
        assert pending[0]["from"] == "acp"

    @pytest.mark.asyncio
    async def test_send_message_unknown_project(self, mock_mgr):
        from sextant.send_message import send_message_handler

        mgr, mbox = mock_mgr
        fn = send_message_handler.handler
        result = await fn({
            "to": "nonexistent",
            "subject": "test",
            "body": "hello",
        })

        assert result["status"] == "error"
        assert "不存在" in result["message"]

    @pytest.mark.asyncio
    async def test_send_message_multiple_recipients(self, mock_mgr):
        from sextant.send_message import send_message_handler

        mgr, mbox = mock_mgr
        fn = send_message_handler.handler

        await fn({"to": "ncp", "subject": "a", "body": "1"})
        await fn({"to": "xcp", "subject": "b", "body": "2"})

        assert mbox.get_pending_count(to="ncp") == 1
        assert mbox.get_pending_count(to="xcp") == 1


# ------------------------------------------------------------------
# SessionManager mailbox integration tests
# ------------------------------------------------------------------


class TestSessionManagerMailbox:
    """SessionManager: build_mailbox_draft, mark_mailbox_delivered."""

    def test_build_mailbox_draft(self):
        from sextant.mailbox import Mailbox
        from sextant.session import SessionManager

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        mbox.record(from_id="acp", to="ncp",
                     subject="同步协议", body="请修改服务端代码")
        mbox.record(from_id="xcp", to="ncp",
                     subject="依赖更新", body="请更新 Cargo.toml")

        # Minimal mock mgr
        cfg = SimpleNamespace(projects=[])
        mgr = SessionManager.__new__(SessionManager)
        mgr._config = cfg
        mgr._clients = {}
        mgr._current_project = "acp"
        mgr._mailbox = mbox

        draft = mgr.build_mailbox_draft("ncp")
        assert draft is not None
        assert "同步协议" in draft
        assert "依赖更新" in draft
        assert "请修改服务端代码" in draft

    def test_build_mailbox_draft_empty(self):
        from sextant.mailbox import Mailbox
        from sextant.session import SessionManager

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        cfg = SimpleNamespace(projects=[])
        mgr = SessionManager.__new__(SessionManager)
        mgr._config = cfg
        mgr._clients = {}
        mgr._current_project = "acp"
        mgr._mailbox = mbox

        draft = mgr.build_mailbox_draft("ncp")
        assert draft is None

    def test_mark_mailbox_delivered(self):
        from sextant.mailbox import Mailbox
        from sextant.session import SessionManager

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        mbox.record(from_id="acp", to="ncp", subject="a", body="1")
        mbox.record(from_id="xcp", to="ncp", subject="b", body="2")

        cfg = SimpleNamespace(projects=[])
        mgr = SessionManager.__new__(SessionManager)
        mgr._config = cfg
        mgr._clients = {}
        mgr._current_project = "acp"
        mgr._mailbox = mbox

        assert mbox.get_pending_count(to="ncp") == 2
        mgr.mark_mailbox_delivered("ncp")
        assert mbox.get_pending_count(to="ncp") == 0


# ------------------------------------------------------------------
# Full workflow test
# ------------------------------------------------------------------


class TestFullWorkflow:
    """End-to-end: send_message → get_pending → mark_delivered."""

    def test_full_workflow(self):
        from sextant.mailbox import Mailbox

        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        # Step 1: acp sends messages to ncp and xcp
        m1 = mbox.record(from_id="acp", to="ncp",
                          subject="同步协议变更：Token → TokenStruct",
                          body="Token 字段从 string 改为 TokenStruct。请修改服务端序列化代码。")
        m2 = mbox.record(from_id="acp", to="xcp",
                          subject="同步协议变更：Token → TokenStruct",
                          body="Token 字段从 string 改为 TokenStruct。请修改 Rust 客户端代码。")

        # Step 2: ncp has 1 pending message
        ncp_pending = mbox.get_pending(to="ncp")
        assert len(ncp_pending) == 1
        assert ncp_pending[0]["from"] == "acp"

        # xcp has 1 pending message
        xcp_pending = mbox.get_pending(to="xcp")
        assert len(xcp_pending) == 1

        # acp has no pending messages
        assert mbox.get_pending(to="acp") == []

        # Step 3: User switches to ncp, marks delivered
        mbox.mark_delivered([m["msg_id"] for m in ncp_pending])
        assert mbox.get_pending(to="ncp") == []

        # Step 4: ncp finishes, user switches to xcp
        xcp_pending = mbox.get_pending(to="xcp")
        mbox.mark_delivered([m["msg_id"] for m in xcp_pending])
        assert mbox.get_pending(to="xcp") == []

        # Step 5: ncp sends reply to acp
        mbox.record(from_id="ncp", to="acp",
                     subject="Re: 同步协议变更",
                     body="已完成。token_serializer.py 和 auth_middleware.py 已修改，编译通过。")

        # Step 6: User switches to acp, sees reply
        acp_pending = mbox.get_pending(to="acp")
        assert len(acp_pending) == 1
        assert acp_pending[0]["from"] == "ncp"
        assert "编译通过" in acp_pending[0]["body"]

        mbox.mark_delivered([acp_pending[0]["msg_id"]])
        assert mbox.get_pending(to="acp") == []

        # All counts should be 0
        assert mbox.all_pending_counts() == {}


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("v2.0 E2E 测试 — Mailbox 驱动架构")
    print("=" * 60)

    # Run with pytest if available, otherwise manual
    try:
        exit_code = pytest.main([__file__, "-v", "--tb=short"])
        sys.exit(exit_code)
    except SystemExit:
        raise

# ------------------------------------------------------------------
# Mailbox edge cases
# ------------------------------------------------------------------


class TestMailboxEdgeCases:
    """Mailbox: JSONDecodeError handling, empty operations, corrupted files."""

    def test_empty_mark_delivered_noop(self):
        from sextant.mailbox import Mailbox
        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")
        # Should not raise
        mbox.mark_delivered([])
        mbox.mark_delivered(None)

    def test_get_pending_skips_corrupted_json_lines(self):
        from sextant.mailbox import Mailbox
        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        # Write a valid message
        mbox.record(from_id="acp", to="ncp", subject="good", body="valid")

        # Append a corrupted line directly
        with open(mbox._today_file(), "a") as f:
            f.write("{broken json!!!\n")

        # Write another valid message
        mbox.record(from_id="xcp", to="ncp", subject="also good", body="ok")

        pending = mbox.get_pending(to="ncp")
        assert len(pending) == 2  # corrupted line skipped
        subjects = [m["subject"] for m in pending]
        assert "good" in subjects
        assert "also good" in subjects

    def test_get_pending_count_skips_corrupted_lines(self):
        from sextant.mailbox import Mailbox
        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        mbox.record(from_id="acp", to="ncp", subject="a", body="1")
        with open(mbox._today_file(), "a") as f:
            f.write("{corrupted\n")
        mbox.record(from_id="acp", to="ncp", subject="b", body="2")

        assert mbox.get_pending_count(to="ncp") == 2

    def test_query_skips_corrupted_lines(self):
        from sextant.mailbox import Mailbox
        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        mbox.record(from_id="acp", to="ncp", subject="a", body="1")
        with open(mbox._today_file(), "a") as f:
            f.write("{bad\n")
        mbox.record(from_id="ncp", to="xcp", subject="b", body="2")

        entries = mbox.query()
        assert len(entries) == 2

    def test_all_pending_counts_skips_corrupted_lines(self):
        from sextant.mailbox import Mailbox
        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        mbox.record(from_id="acp", to="ncp", subject="a", body="1")
        with open(mbox._today_file(), "a") as f:
            f.write("{bad\n")

        counts = mbox.all_pending_counts()
        assert counts == {"ncp": 1}

    def test_mark_delivered_preserves_corrupted_lines(self):
        from sextant.mailbox import Mailbox
        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        msg_id = mbox.record(from_id="acp", to="ncp", subject="deliver me", body="x")
        with open(mbox._today_file(), "a") as f:
            f.write("{corrupted\n")

        mbox.mark_delivered([msg_id])
        assert mbox.get_pending(to="ncp") == []

        # Verify corrupted line survived the rewrite
        with open(mbox._today_file()) as f:
            content = f.read()
        assert "{corrupted" in content

    def test_all_files_sorted_newest_first(self):
        from sextant.mailbox import Mailbox
        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        mbox.record(from_id="acp", to="ncp", subject="test", body="ok")
        files = mbox.all_files()
        assert len(files) >= 1
        # all_files is sorted reverse by name (newest first)
        names = [f.name for f in files]
        assert names == sorted(names, reverse=True)

    def test_mark_delivered_persists_to_jsonl(self):
        """mark_delivered writes status to JSONL so it survives restarts."""
        from sextant.mailbox import Mailbox
        tmp = Path(tempfile.mkdtemp(prefix="sextant-test-"))
        mbox = Mailbox(base_dir=tmp / "mailbox")

        msg_id = mbox.record(from_id="acp", to="ncp", subject="persist", body="test")

        # Mark delivered
        mbox.mark_delivered([msg_id])

        # Verify on-disk status
        with open(mbox._today_file()) as f:
            content = f.read()
        assert '"status": "delivered"' in content

        # Create a new Mailbox instance (simulate restart)
        mbox2 = Mailbox(base_dir=tmp / "mailbox")
        assert mbox2.get_pending(to="ncp") == []


# ------------------------------------------------------------------
# send_message error branch tests
# ------------------------------------------------------------------


class TestSendMessageErrors:
    """send_message: error branches for uninitialized state."""

    @pytest.mark.asyncio
    async def test_manager_none_returns_error(self):
        from sextant.send_message import send_message_handler, set_manager

        set_manager(None)
        fn = send_message_handler.handler
        result = await fn({
            "to": "ncp", "subject": "test", "body": "hello",
        })
        assert result["status"] == "error"
        assert "SessionManager" in result["message"]

    @pytest.mark.asyncio
    async def test_current_project_none_returns_error(self):
        from sextant.send_message import send_message_handler, set_manager
        from types import SimpleNamespace

        mgr = SimpleNamespace()
        mgr.current_project = None
        mgr.project_ids = ["ncp"]
        set_manager(mgr)

        fn = send_message_handler.handler
        result = await fn({
            "to": "ncp", "subject": "test", "body": "hello",
        })
        assert result["status"] == "error"
        assert "current_project" in result["message"]

    @pytest.mark.asyncio
    async def test_mailbox_none_returns_error(self):
        from sextant.send_message import send_message_handler, set_manager, set_mailbox
        from types import SimpleNamespace

        mgr = SimpleNamespace()
        mgr.current_project = "acp"
        mgr.project_ids = ["acp", "ncp"]
        set_manager(mgr)
        set_mailbox(None)

        fn = send_message_handler.handler
        result = await fn({
            "to": "ncp", "subject": "test", "body": "hello",
        })
        assert result["status"] == "error"
        assert "Mailbox" in result["message"]
