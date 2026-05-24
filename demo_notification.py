"""
MCP notification 路径验证 demo — v3

修复：
  1. Identity: 解析 request body 取 JSON-RPC id，用 id → project 映射桥接 middleware 和 tool handler
  2. Notification: 用 JSONRPCNotification（而非受限的 ClientNotification）发送自定义通知

启动：
  cd /Users/zp001/Documents/MyGitHub/sextant
  source .venv/bin/activate
  python demo_notification.py
"""

import json as _json, logging, sys
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import LoggingMessageNotification
from starlette.requests import Request
from starlette.types import Scope, Receive, Send

_log = logging.getLogger("sextant")
logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)


# ── Session 注册表 ──
# project_name → list[(session_id, ServerSession)]
_sessions: dict[str, list[tuple[str, object]]] = {}
# session_id → project_name
_session_project: dict[str, str] = {}
# id(ServerSession) → project_name (cache)
_session_object_to_project: dict[int, str] = {}
# JSON-RPC request id → project_name (桥接 middleware ↔ tool handler)
_rpc_id_to_project: dict[str, str] = {}


async def _send_sextant_notification(session, params: dict):
    """通过 LoggingMessageNotification.data 携带 sextant 消息"""
    await session.send_notification(
        LoggingMessageNotification(
            method="notifications/message",
            params={
                "level": "error",
                "logger": "sextant",
                "data": params,
            },
        )
    )


# ── ASGI Middleware ──
class DemoMiddleware:
    def __init__(self, config: dict[str, str]):
        self.config = config

    async def __call__(self, app, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        request = Request(scope, receive)
        project_name = request.query_params.get("project", "")

        print(f"[middleware] method={request.method} "
              f"query_string={scope.get('query_string', b'').decode()} "
              f"project={project_name!r}")

        # 校验 project
        if project_name and project_name not in self.config:
            from starlette.responses import JSONResponse
            resp = JSONResponse({"error": f"Unknown project: {project_name}"}, status_code=400)
            await resp(scope, receive, send)
            return

        # ── 解析 POST body 取 JSON-RPC id ──
        body = b""
        more_body = True
        while more_body:
            msg = await receive()
            body += msg.get("body", b"")
            more_body = msg.get("more_body", False)

        rpc_id = None
        if request.method == "POST" and body:
            try:
                rpc = _json.loads(body)
                rpc_id = rpc.get("id")
            except Exception:
                pass

        if rpc_id and project_name:
            _rpc_id_to_project[str(rpc_id)] = project_name

        # 捕获响应 header
        response_headers: dict[str, str] = {}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                for key, value in message.get("headers", []):
                    response_headers[key.decode("latin-1").lower()] = value.decode("latin-1")
            await send(message)

        # ── 构造带 body 重放的 receive ──
        body_sent = False

        async def receive_replay():
            nonlocal body_sent
            if body_sent:
                return await receive()
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await app(scope, receive_replay, send_wrapper)

        # 新 session 建立
        new_sid = response_headers.get("mcp-session-id", "")
        if new_sid and project_name:
            _session_project[new_sid] = project_name
            print(f"[middleware] NEW SESSION: {new_sid[:12]}... → {project_name}")


# ── MCP Server ──
mcp = FastMCP(
    "sextant-demo",
    host="127.0.0.1",
    port=19876,
    streamable_http_path="/mcp",
    retry_interval=30_000,
)


def _resolve_caller(ctx: Context | None) -> tuple[str, str]:
    """识别调用者：返回 (project_name, session_id)"""
    if ctx is None or ctx.session is None:
        return ("", "")

    obj_id = id(ctx.session)

    # 缓存命中
    if obj_id in _session_object_to_project:
        proj = _session_object_to_project[obj_id]
        for sid, p in _session_project.items():
            if p == proj:
                return (proj, sid)
        return (proj, "")

    # 通过 JSON-RPC request_id 查找
    req_id = str(ctx.request_context.request_id) if ctx.request_context.request_id else ""
    _log.warning("_resolve_caller: obj_id=%s, req_id=%r, rpc_id_to_project keys=%s, session_project=%s",
                 obj_id, req_id, list(_rpc_id_to_project.keys()), _session_project)
    if req_id and req_id in _rpc_id_to_project:
        proj = _rpc_id_to_project.pop(req_id)
        _session_object_to_project[obj_id] = proj
        sid = ""
        for s, p in _session_project.items():
            if p == proj:
                sid = s
                break
        if proj not in _sessions:
            _sessions[proj] = []
        _sessions[proj].append((sid, ctx.session))
        _log.warning("IDENTIFIED: %s (via rpc_id=%s, sid=%s)", proj, req_id, sid[:12] if sid else '?')
        return (proj, sid)

    _log.warning("_resolve_caller FAILED: req_id=%r not in %s", req_id, list(_rpc_id_to_project.keys()))
    return ("", "")


@mcp.tool(name="send_message", description="向目标项目发送一条 sextant/new_message 通知")
async def send_message(
    to: str,
    subject: str = "测试通知",
    body: str = "这是一条跨项目测试消息",
    ctx: Context = None,
) -> dict:
    from_proj, from_sid = _resolve_caller(ctx)
    if not from_proj:
        return {"error": "无法识别发送方身份（请先调用 ping 注册 session）"}

    # 更新 session 绑定
    if ctx and ctx.session and from_sid:
        _sessions[from_proj] = [(s, sess) for s, sess in _sessions.get(from_proj, []) if s != from_sid]
        _sessions[from_proj].append((from_sid, ctx.session))

    # 查找目标 session
    target_sessions = _sessions.get(to, [])
    if not target_sessions:
        return {
            "status": "queued",
            "message": f"目标项目 {to} 不在线，通知无法实时推送",
            "from": from_proj,
            "to": to,
            "online_projects": list(_sessions.keys()),
        }

    delivered = 0
    for tsid, tsession in target_sessions:
        try:
            await _send_sextant_notification(
                tsession,
                {
                    "message_id": f"demo_{from_proj}_to_{to}",
                    "from": from_proj,
                    "to": to,
                    "subject": subject,
                    "priority": "normal",
                    "body": body,
                },
            )
            delivered += 1
        except Exception as e:
            print(f"[demo] 推送通知到 {to}/{tsid} 失败: {e}")

    return {
        "status": "delivered" if delivered > 0 else "queued",
        "from": from_proj,
        "to": to,
        "delivered_to_sessions": delivered,
        "total_sessions": len(target_sessions),
        "online_projects": list(_sessions.keys()),
    }


@mcp.tool(name="list_projects", description="列出当前在线的项目")
async def list_projects(ctx: Context = None) -> dict:
    from_proj, _ = _resolve_caller(ctx)
    return {"online_projects": list(_sessions.keys()), "your_project": from_proj}


@mcp.tool(name="ping", description="连通性测试")
async def ping(ctx: Context = None) -> str:
    proj, sid = _resolve_caller(ctx)
    return f"pong — 你来自 {proj}, session {sid[:12] if sid else 'unknown'}..."


KNOWN_PROJECTS = {"sextant": "sextant", "ncp": "ncp", "acp": "acp"}


if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("sextant notification 跨项目验证 demo v3")
    print("=" * 60)
    print(f"监听: http://127.0.0.1:19876/mcp")
    print(f"已知项目: {list(KNOWN_PROJECTS.keys())}")
    print()

    starlette_app = mcp.streamable_http_app()
    middleware = DemoMiddleware(KNOWN_PROJECTS)

    async def wrapped_app(scope, receive, send):
        await middleware(starlette_app, scope, receive, send)

    uvicorn.run(wrapped_app, host="127.0.0.1", port=19876)
