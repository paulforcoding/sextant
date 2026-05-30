"""E2E test fixtures — mock Flask server + Playwright browser.

Architecture:
  A standalone Flask app (mock_server) serves the real frontend HTML/JS/CSS
  plus mocked /api/* endpoints that return controlled test data.
  No ClaudeSDKClient or real agents required.
"""

from __future__ import annotations

import json
import queue
import random
import threading
import time
import urllib.request
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
_STATIC_DIR = _PROJECT_ROOT / "src" / "sextant" / "web" / "static"
_TEMPLATE_PATH = _PROJECT_ROOT / "src" / "sextant" / "web" / "templates" / "index.html"

# ── Mock test data ──────────────────────────────────────────────────────────

MOCK_PROJECTS = [
    {"id": "acp", "pending": 2, "ready": True},
    {"id": "ncp", "pending": 1, "ready": True},
    {"id": "xcp", "pending": 0, "ready": True},
]

MOCK_PENDING_MSGS = [
    {
        "msg_id": "m_test_001",
        "from": "acp",
        "to": "ncp",
        "subject": "同步协议变更",
        "body": "Token 字段从 string 改为 TokenStruct。请修改服务端代码。",
        "status": "pending",
        "timestamp": "2026-05-30T10:00:00",
    },
    {
        "msg_id": "m_test_002",
        "from": "acp",
        "to": "ncp",
        "subject": "依赖更新",
        "body": "请更新 requirements.txt 中的依赖版本。",
        "status": "pending",
        "timestamp": "2026-05-30T11:00:00",
    },
]

MOCK_MAILBOX_ENTRIES = [
    {
        "msg_id": "m_mb_001",
        "from": "acp",
        "to": "ncp",
        "subject": "同步协议变更",
        "body": "Token 字段从 string 改为 TokenStruct。请修改服务端代码。",
        "status": "delivered",
        "timestamp": "2026-05-30T10:00:00",
    },
    {
        "msg_id": "m_mb_002",
        "from": "ncp",
        "to": "acp",
        "subject": "Re: 同步协议变更",
        "body": "已完成修改，编译通过。",
        "status": "delivered",
        "timestamp": "2026-05-30T11:30:00",
    },
    {
        "msg_id": "m_mb_003",
        "from": "xcp",
        "to": "ncp",
        "subject": "依赖更新",
        "body": "请更新 Rust 客户端代码。",
        "status": "pending",
        "timestamp": "2026-05-30T12:00:00",
    },
]

MOCK_HISTORY_MSGS = [
    {"role": "user", "content": "你好，请问项目进度如何？"},
    {"role": "assistant", "content": "项目进展顺利，已经完成了核心模块的开发。"},
    {"role": "user", "content": "有什么需要我协助的吗？"},
    {"role": "assistant", "content": "目前不需要，我们在按计划推进。"},
]

MOCK_AGENTS = {
    "agents": [
        {
            "id": "acp",
            "directory": "/tmp/acp",
            "continue": False,
            "session_id": "sess-acp-abc123def456",
            "ready": True,
        },
        {
            "id": "ncp",
            "directory": "/tmp/ncp",
            "continue": True,
            "session_id": "sess-ncp-ghi789jkl012",
            "ready": True,
        },
        {
            "id": "xcp",
            "directory": "/tmp/xcp",
            "continue": False,
            "session_id": None,
            "ready": True,
        },
    ],
    "current": None,
    "total": 3,
}

MOCK_CONTEXT = {
    "percentage": 45.2,
    "totalTokens": 45200,
    "maxTokens": 100000,
    "model": "claude-sonnet-4-20250514",
}

MOCK_USAGE = {
    "project": "acp",
    "total_cost": 0.02345,
    "last_cost": 0.01234,
    "context_pct": 45.2,
    "context_tokens": 45200,
    "context_max": 100000,
}

MOCK_INFO = {
    "project": "acp",
    "pid": 12345,
    "cwd": "/tmp/acp",
    "session_id": "sess-acp-abc123def456",
}

MOCK_MCP = {
    "project": "acp",
    "servers": [
        {
            "name": "sextant",
            "source": "built-in",
            "status": "connected",
            "tools": [{"name": "send_message", "description": "向其他项目发送消息。"}],
            "tool_count": 1,
        },
    ],
    "total_servers": 1,
    "total_tools": 1,
}


# ── Mock Flask server ───────────────────────────────────────────────────────


def _create_mock_app():
    """Build a Flask app that serves the real frontend + mock API endpoints."""
    from flask import Flask, Response, jsonify, render_template_string, request

    app = Flask(
        __name__,
        static_folder=str(_STATIC_DIR),
        static_url_path="/static",
    )

    # Track consumed pending messages for tests
    app.config["consumed_ids"] = set()
    # Track permission mode changes
    app.config["perm_mode"] = "bypassPermissions"
    # Track model changes
    app.config["model"] = "claude-sonnet-4-20250514"
    # Track rename calls
    app.config["renamed_title"] = None
    # Track SSE streams
    app.config["streams"]: dict[str, queue.Queue[dict]] = {}

    # ── Health ──
    @app.route("/api/health")
    def api_health():
        return jsonify({"ready": True, "agents": ["acp", "ncp", "xcp"], "error": None})

    # ── Projects ──
    @app.route("/api/projects")
    def api_projects():
        return jsonify(MOCK_PROJECTS)

    # ── Chat POST (initiate stream) ──
    @app.route("/api/chat/<project_id>", methods=["POST"])
    def api_chat(project_id: str):
        data = request.get_json(silent=True) or {}
        prompt = data.get("prompt", "").strip()
        if not prompt:
            return jsonify({"error": "prompt 不能为空"}), 400

        q: queue.Queue[dict] = queue.Queue()
        app.config["streams"][project_id] = q

        # Simulate a brief SSE stream in background thread
        def _simulate_stream():
            time.sleep(0.1)
            for chunk in ["好的", "，", "我已收到", "你的消息", "。"]:
                q.put({"type": "text", "content": chunk})
                time.sleep(0.01)
            q.put({
                "type": "done",
                "cost": 0.00123,
                "elapsed": 0.5,
            })

        threading.Thread(target=_simulate_stream, daemon=True).start()
        return jsonify({"status": "ok"})

    # ── SSE stream ──
    @app.route("/api/chat/<project_id>/stream")
    def api_stream(project_id: str):
        q = app.config["streams"].get(project_id)

        def generate():
            if q is None:
                yield f"data: {json.dumps({'type': 'error', 'message': 'no active stream'})}\n\n"
                return
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    if msg.get("type") in ("done", "error"):
                        break
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    # ── History ──
    @app.route("/api/chat/<project_id>/history")
    def api_history(project_id: str):
        return jsonify(MOCK_HISTORY_MSGS)

    # ── Pending ──
    @app.route("/api/chat/<project_id>/pending")
    def api_pending(project_id: str):
        if project_id == "ncp":
            return jsonify(MOCK_PENDING_MSGS)
        return jsonify([])

    # ── Consume pending ──
    @app.route("/api/chat/<project_id>/consume-pending", methods=["POST"])
    def api_consume_pending(project_id: str):
        data = request.get_json(silent=True) or {}
        ids = data.get("msg_ids", [])
        for mid in ids:
            app.config["consumed_ids"].add(mid)
        return jsonify({"status": "ok", "consumed": len(ids)})

    # ── Slash command endpoints ──
    @app.route("/api/agents")
    def api_agents():
        return jsonify(MOCK_AGENTS)

    @app.route("/api/chat/<project_id>/mcp")
    def api_mcp(project_id: str):
        return jsonify(MOCK_MCP)

    @app.route("/api/chat/<project_id>/context")
    def api_context(project_id: str):
        return jsonify(MOCK_CONTEXT)

    @app.route("/api/chat/<project_id>/usage")
    def api_usage(project_id: str):
        return jsonify(MOCK_USAGE)

    @app.route("/api/chat/<project_id>/info")
    def api_info(project_id: str):
        return jsonify(MOCK_INFO)

    @app.route("/api/chat/<project_id>/rename", methods=["POST"])
    def api_rename(project_id: str):
        data = request.get_json(silent=True) or {}
        title = data.get("title", "").strip()
        if not title:
            return jsonify({"error": "title 不能为空"}), 400
        app.config["renamed_title"] = title
        return jsonify({"status": "ok", "title": title, "session_id": "sess-test-123"})

    @app.route("/api/chat/<project_id>/fork", methods=["POST"])
    def api_fork(project_id: str):
        return jsonify({
            "status": "ok",
            "original_session": "sess-orig-abc",
            "new_session": "sess-new-def456",
        })

    @app.route("/api/chat/<project_id>/perm", methods=["POST"])
    def api_perm(project_id: str):
        data = request.get_json(silent=True) or {}
        mode = data.get("mode", "").strip()
        valid = {"default", "acceptEdits", "bypassPermissions", "plan"}
        if mode not in valid:
            return jsonify({"error": f"无效模式。可选: {', '.join(sorted(valid))}"}), 400
        app.config["perm_mode"] = mode
        return jsonify({"status": "ok", "mode": mode})

    @app.route("/api/chat/<project_id>/model", methods=["POST"])
    def api_model(project_id: str):
        data = request.get_json(silent=True) or {}
        model_name = data.get("model", "").strip()
        if not model_name:
            return jsonify({"error": "model 不能为空"}), 400
        app.config["model"] = model_name
        return jsonify({"status": "ok", "model": model_name})

    # ── Mailbox ──
    @app.route("/api/mailbox")
    def api_mailbox():
        project = request.args.get("project", "")
        entries = MOCK_MAILBOX_ENTRIES
        if project:
            entries = [e for e in entries if e["from"] == project or e["to"] == project]
        return jsonify(entries)

    # ── SPA ──
    @app.route("/")
    def index():
        if _TEMPLATE_PATH.exists():
            resp = app.make_response(
                render_template_string(_TEMPLATE_PATH.read_text(encoding="utf-8"))
            )
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            return resp
        return "<h1>index.html not found</h1>", 500

    return app


# ── Pytest fixtures ─────────────────────────────────────────────────────────

_server_info = None  # module-level cache for session-scoped fixture


@pytest.fixture(scope="session")
def mock_server():
    """Start a mock Flask server in a background thread (session-scoped)."""
    global _server_info
    if _server_info is not None:
        return _server_info

    app = _create_mock_app()
    port = random.randint(5100, 5200)
    thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False),
        daemon=True,
    )
    thread.start()
    # Wait for server to be ready
    url = f"http://127.0.0.1:{port}/api/health"
    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    _server_info = {"url": f"http://127.0.0.1:{port}", "port": port, "app": app}
    return _server_info


@pytest.fixture(scope="session")
def base_url(mock_server):
    """Return the mock server base URL (session-scoped for pytest-base-url)."""
    return mock_server["url"]


@pytest.fixture
def page(browser, base_url):
    """Create a new browser page for each test (function-scoped)."""
    context = browser.new_context(base_url=base_url)
    page = context.new_page()
    yield page
    context.close()
