"""sextant Web UI — Flask server with SSE streaming.

Single-process: Flask starts immediately, CC agents boot in background thread.
Left sidebar: agent list + mailbox.  Right panel: chat with streaming.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template_string, request

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_TEMPLATE = _HERE / "web" / "templates" / "index.html"

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder=str(_HERE / "web" / "templates"))

_mgr: Any = None           # SessionManager — None until agents are ready
_streams: dict[str, "queue.Queue[dict]"] = {}
_config: Any = None
_project_ids: list[str] = []
_ready: threading.Event = threading.Event()  # set when all agents are up
_startup_error: str | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Health / Status
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/health")
def api_health():
    return jsonify({
        "ready": _ready.is_set(),
        "agents": _project_ids,
        "error": _startup_error,
    })


# ═══════════════════════════════════════════════════════════════════════════
# Projects
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/projects")
def api_projects():
    """List all agents and their pending mailbox counts."""
    result = []
    counts = {}
    try:
        if _mgr and _ready.is_set():
            counts = _mgr.mailbox.all_pending_counts()
    except Exception:
        pass
    for pid in _project_ids:
        result.append({
            "id": pid,
            "pending": counts.get(pid, 0),
            "ready": _ready.is_set(),
        })
    if not _project_ids and _startup_error:
        result.append({"id": "error", "pending": 0, "ready": False, "error": _startup_error})
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════
# Chat
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/chat/<project_id>", methods=["POST"])
def api_chat(project_id: str):
    """Send a prompt to an agent.  Response streams via SSE."""
    if not _ready.is_set():
        return jsonify({"error": "Agent 尚未就绪，请稍候..."}), 503

    if project_id not in _project_ids:
        return jsonify({"error": f"未知项目: {project_id}"}), 404

    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "prompt 不能为空"}), 400

    # Create SSE queue and launch background query
    q: queue.Queue[dict] = queue.Queue()
    _streams[project_id] = q

    def _run():
        asyncio.run(_agent_query_safe(project_id, prompt, q))

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "ok"})


@app.route("/api/chat/<project_id>/stream")
def api_stream(project_id: str):
    """SSE endpoint — yields agent response events."""
    q = _streams.get(project_id)

    def generate():
        nonlocal q
        if q is None:
            yield _sse({"type": "error", "message": "no active stream"})
            return
        # Yield connection event IMMEDIATELY so Flask sends headers
        yield _sse({"type": "connected"})
        while True:
            try:
                msg = q.get(timeout=60)
                yield _sse(msg)
                if msg.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                yield _sse({"type": "heartbeat"})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.route("/api/chat/<project_id>/history")
def api_history(project_id: str):
    """Read CC session history from JSONL files."""
    if not _ready.is_set():
        return jsonify([])

    if project_id not in _project_ids:
        return jsonify({"error": f"未知项目: {project_id}"}), 404

    messages: list[dict] = []
    try:
        proj = _config.get_project(project_id)
        proj_dir = Path(proj.directory).expanduser().resolve()
        slug = _workspace_slug(str(proj_dir))
        sessions_dir = Path.home() / ".claude" / "projects" / slug

        if sessions_dir.is_dir():
            files = sorted(
                sessions_dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for f in files[:3]:
                try:
                    with open(f) as fh:
                        for line in fh:
                            try:
                                entry = json.loads(line)
                                msg = entry.get("message", {})
                                role = msg.get("role", "")
                                content = msg.get("content", "")
                                if role in ("user", "assistant") and content:
                                    text = _extract_text(content)
                                    if text.strip():
                                        messages.append({
                                            "role": role,
                                            "content": text,
                                        })
                            except json.JSONDecodeError:
                                continue
                except (OSError, PermissionError):
                    continue
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(messages[-200:])


# ═══════════════════════════════════════════════════════════════════════════
# Slash commands
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/agents")
def api_agents():
    """List all configured agents with status info."""
    result = []
    for proj in _config.projects if _config else []:
        info = {
            "id": proj.id,
            "directory": str(proj.directory),
            "continue": proj.continue_conversation,
            "session_id": proj.session_id,
            "ready": _ready.is_set(),
        }
        result.append(info)
    return jsonify({
        "agents": result,
        "current": None,  # web UI tracks this client-side
        "total": len(result),
    })


@app.route("/api/chat/<project_id>/mcp")
def api_mcp(project_id: str):
    """List MCP servers and tools for a project."""
    if project_id not in _project_ids:
        return jsonify({"error": f"未知项目: {project_id}"}), 404

    servers = []

    # 1. sextant built-in MCP server (always present)
    sextant_tools = [{
        "name": "send_message",
        "description": (
            "向其他项目发送消息。消息会投递到对方的收件箱，"
            "对方下次查看时会收到。"
        ),
        "parameters": ["to (目标项目ID)", "subject", "body"],
    }]
    servers.append({
        "name": "sextant",
        "source": "built-in",
        "status": "connected" if _ready.is_set() else "starting",
        "tools": sextant_tools,
        "tool_count": len(sextant_tools),
    })

    # 2. Project-level MCP servers from .mcp.json
    try:
        proj = _config.get_project(project_id)
        proj_dir = Path(proj.directory).expanduser().resolve()
        mcp_json = proj_dir / ".mcp.json"
        if mcp_json.is_file():
            with open(mcp_json) as f:
                mcp_config = json.load(f)
            mcp_servers = mcp_config.get("mcpServers", {})
            for name, cfg in mcp_servers.items():
                tools_info = _describe_mcp_server_tools(name, cfg)
                servers.append({
                    "name": name,
                    "source": "project (.mcp.json)",
                    "status": "configured",
                    "command": cfg.get("command", ""),
                    "args": cfg.get("args", []),
                    "tools": tools_info,
                    "tool_count": len(tools_info),
                })
    except Exception:
        pass

    # 3. Global MCP servers from ~/.claude/settings.json
    try:
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.is_file():
            with open(settings_path) as f:
                settings = json.load(f)
            global_mcp = settings.get("mcpServers", {})
            for name, cfg in global_mcp.items():
                # Skip if already seen from project config
                if any(s["name"] == name for s in servers):
                    continue
                tools_info = _describe_mcp_server_tools(name, cfg)
                servers.append({
                    "name": name,
                    "source": "global (~/.claude/settings.json)",
                    "status": "configured",
                    "command": cfg.get("command", ""),
                    "args": cfg.get("args", []),
                    "tools": tools_info,
                    "tool_count": len(tools_info),
                })
    except Exception:
        pass

    return jsonify({
        "project": project_id,
        "servers": servers,
        "total_servers": len(servers),
        "total_tools": sum(s["tool_count"] for s in servers),
    })


def _describe_mcp_server_tools(server_name: str, config: dict) -> list[dict]:
    """Extract tool descriptions from an MCP server config."""
    tools = []
    # Try tools whitelist if present
    tool_names = config.get("tools", [])
    if tool_names:
        for t in tool_names:
            tools.append({"name": t, "description": "", "from_whitelist": True})
        return tools

    # Try tools in env vars
    env = config.get("env", {})
    tool_list_env = env.get("MCP_TOOLS", "")
    if tool_list_env:
        for t in tool_list_env.split(","):
            t = t.strip()
            if t:
                tools.append({"name": t, "description": ""})
        return tools

    # If no explicit tool list, return a placeholder
    if tools:
        return tools
    return [{"name": "(tools discovered at runtime)", "description": ""}]


# ═══════════════════════════════════════════════════════════════════════════
# Mailbox
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/mailbox")
def api_mailbox():
    """List all mailbox entries (read-only)."""
    if not _ready.is_set():
        return jsonify([])
    project = request.args.get("project", "")
    try:
        entries = _mgr.mailbox.query(project=project or None, limit=100)
    except Exception:
        entries = []
    return jsonify(entries)


# ═══════════════════════════════════════════════════════════════════════════
# SPA
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if _TEMPLATE.exists():
        return render_template_string(_TEMPLATE.read_text(encoding="utf-8"))
    return "<h1>index.html not found</h1>", 500


# ═══════════════════════════════════════════════════════════════════════════
# Internals
# ═══════════════════════════════════════════════════════════════════════════

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _agent_query_safe(project_id: str, prompt: str, q: queue.Queue):
    """Wrapper with error handling."""
    try:
        await _agent_query(project_id, prompt, q)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[web] agent query error: {e}\n{tb}", file=sys.stderr, flush=True)
        try:
            q.put({"type": "error", "message": str(e)})
        except Exception:
            pass


async def _agent_query(project_id: str, prompt: str, q: queue.Queue):
    """Run agent query with a fresh CC client (avoids cross-loop issues)."""

    try:
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        import json as _json

        # Get project config
        proj = _config.get_project(project_id)
        cwd = str(proj.directory)

        # Load env
        env = {}
        try:
            with open(Path.home() / ".claude" / "settings.json") as f:
                env = _json.load(f).get("env", {})
        except Exception:
            pass

        opts = ClaudeAgentOptions(
            cwd=cwd,
            permission_mode=proj.permission_mode or _config.permission_mode or "acceptEdits",
            setting_sources=["project"],
            continue_conversation=proj.continue_conversation,
            resume=proj.session_id,
            env=env,
            mcp_servers={"sextant": _get_mcp_server()},
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": (
                    f"你的项目是 **{project_id}**。\n\n"
                    f"可以通过 `send_message(to, subject, body)` 向其他项目发送消息。\n"
                    f"可用项目: {', '.join(p for p in _project_ids if p != project_id)}。\n"
                    f"消息发送后对方会在下次查看时收到。仅在用户明确要求时使用。"
                ),
            },
        )

        async with ClaudeSDKClient(options=opts) as client:
            # Set sender identity for send_message tool
            if _mgr:
                _mgr.set_current_project(project_id)

            # Build prompt with mailbox messages
            full_prompt = _build_full_prompt(project_id, prompt)

            t0 = time.time()
            await client.query(full_prompt)

            async for msg in client.receive_response():
                _serialize_and_push(msg, q)

            elapsed = time.time() - t0
            q.put({"type": "done", "elapsed": round(elapsed, 1)})

    except Exception as e:
        q.put({"type": "error", "message": str(e)})


def _get_mcp_server():
    """Create an MCP server with the send_message tool (cached)."""
    if _get_mcp_server._cached is not None:
        return _get_mcp_server._cached
    from claude_agent_sdk import create_sdk_mcp_server
    from .send_message import send_message_tool
    server = create_sdk_mcp_server(
        name="sextant",
        version="0.2.0",
        tools=[send_message_tool],
    )
    _get_mcp_server._cached = server
    return server

_get_mcp_server._cached = None


def _build_full_prompt(project_id: str, user_prompt: str) -> str:
    """Prepend pending mailbox messages if any."""
    try:
        if _mgr:
            pending = _mgr.mailbox.get_pending(to=project_id)
            if pending:
                msgs = []
                for m in pending:
                    msgs.append(f"[来自 {m['from']}] {m['subject']}\n\n{m['body']}")
                _mgr.mark_mailbox_delivered(project_id)
                return "\n\n".join(msgs) + f"\n\n---\n\n{user_prompt}"
    except Exception:
        pass
    return user_prompt


def _serialize_and_push(msg: Any, q: queue.Queue) -> None:
    """Convert an SDK message to JSON and push to SSE queue."""
    from claude_agent_sdk import (
        AssistantMessage, ResultMessage,
        TextBlock, ThinkingBlock,
        ToolUseBlock, ToolResultBlock,
        ServerToolUseBlock, ServerToolResultBlock,
    )

    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, ThinkingBlock):
                q.put({"type": "thinking", "content": block.thinking.strip()})
            elif isinstance(block, TextBlock) and block.text:
                q.put({"type": "text", "content": block.text})
            elif isinstance(block, ToolUseBlock):
                q.put({"type": "tool_use", "name": block.name,
                       "input": _safe_dict(block.input)})
            elif isinstance(block, ToolResultBlock):
                q.put({"type": "tool_result",
                       "content": _safe_str(block.content),
                       "is_error": block.is_error})
            elif isinstance(block, ServerToolUseBlock):
                q.put({"type": "server_tool", "name": block.name,
                       "input": _safe_dict(block.input)})
            elif isinstance(block, ServerToolResultBlock):
                q.put({"type": "server_tool_result",
                       "content": _safe_dict(block.content)})

    elif isinstance(msg, ResultMessage):
        q.put({"type": "done",
               "cost": msg.total_cost_usd,
               "stop_reason": msg.stop_reason})


def _safe_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return {k: _safe_val(v) for k, v in obj.items()}
    return {"_raw": str(obj)[:500]}


def _safe_val(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, (list, tuple)):
        return [_safe_val(x) for x in v][:20]
    if isinstance(v, dict):
        return {k: _safe_val(vv) for k, vv in list(v.items())[:10]}
    return str(v)[:200]


def _safe_str(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:2000]
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)[:2000]
    return str(content)[:2000]


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    return str(content)


def _workspace_slug(project_dir: str) -> str:
    return "-" + str(Path(project_dir).expanduser().resolve()).replace("/", "-")


# ═══════════════════════════════════════════════════════════════════════════
# Startup
# ═══════════════════════════════════════════════════════════════════════════

def create_app(config_path: str = "sextant.yaml") -> Flask:
    """Initialize the Flask app.  Agents boot in background."""
    global _config, _project_ids

    from .config import load_config
    _config = load_config(config_path)
    _project_ids = [p.id for p in _config.projects]

    print(f"sextant web · {len(_project_ids)} project(s) configured", file=sys.stderr)
    for pid in _project_ids:
        print(f"  {pid}", file=sys.stderr)
    print("  starting agents in background...", file=sys.stderr)

    # Boot agents in background thread — Flask starts immediately
    threading.Thread(target=_boot_agents, daemon=True).start()

    # Register shutdown
    import atexit
    @atexit.register
    def _shutdown():
        global _mgr
        if _mgr:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_mgr.__aexit__(None, None, None))
            loop.close()

    return app


def _boot_agents() -> None:
    """Start all CC agents in a background event loop.

    Forces acceptEdits mode — web UI has no terminal for canUseTool prompts.
    """
    global _mgr, _startup_error

    from .session import SessionManager
    from .send_message import set_manager

    # Force acceptEdits: web workers have no terminal for input()
    for proj in _config.projects:
        if not proj.permission_mode:
            proj.permission_mode = "acceptEdits"
    if not _config.permission_mode:
        _config.permission_mode = "acceptEdits"

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        async def _start():
            global _mgr, _startup_error
            mgr = SessionManager(_config)
            _mgr = await mgr.__aenter__()
            set_manager(_mgr)

        loop.run_until_complete(_start())
        print(f"  ✓ all agents ready", file=sys.stderr)
        _ready.set()

        # Keep the event loop alive for agent operations
        # (Flask request threads will create their own loops)
    except Exception as e:
        _startup_error = str(e)
        print(f"  ✗ agent startup failed: {e}", file=sys.stderr)
    finally:
        loop.close()


def run_web(
    config_path: str = "sextant.yaml",
    host: str = "127.0.0.1",
    port: int = 5008,
    debug: bool = False,
) -> None:
    """Entry point for `sextant web`."""
    os.environ["FLASK_ENV"] = "development" if debug else "production"
    create_app(config_path)
    app.run(host=host, port=port, debug=debug, threaded=True)
