# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

sextant 让你在同一个终端 / Web UI 中同时管理多个 Claude Code 实例（每个项目目录一个），并使它们之间能通过 mailbox 机制互相发送消息。

## 技术栈

- **Python >= 3.10**，无异步框架依赖（CLI 用纯 asyncio，Web 用 Flask）
- **claude-agent-sdk >= 0.2.0**：每个项目创建一个 `ClaudeSDKClient`，通过 SDK 的 query/receive_response 进行流式对话
- **pyyaml**：解析 `sextant.yaml` 配置文件
- **Flask + SSE**：Web UI 通过 Server-Sent Events 将 agent 输出流式推送到浏览器

## Agent SDK 文档

**写代码时优先参考官方文档**：[Agent SDK 文档](https://code.claude.com/docs/zh-CN/agent-sdk/overview)

完整文档索引：<https://code.claude.com/docs/llms.txt>

核心子页面：
- [Python SDK 参考](https://code.claude.com/docs/zh-CN/agent-sdk/python) — 所有函数、类、类型的定义
- [使用 hooks 拦截和控制代理行为](https://code.claude.com/docs/zh-CN/agent-sdk/hooks)
- [配置权限](https://code.claude.com/docs/zh-CN/agent-sdk/permissions)
- [使用 MCP 连接外部工具](https://code.claude.com/docs/zh-CN/agent-sdk/mcp)
- [SDK 中的 Agent Skills](https://code.claude.com/docs/zh-CN/agent-sdk/skills)
- [使用会话](https://code.claude.com/docs/zh-CN/agent-sdk/sessions)
- [SDK 中的子代理](https://code.claude.com/docs/zh-CN/agent-sdk/subagents)

### sextant 使用的核心 SDK API

**两种使用模式：**
- `query()` — 一次性任务，便捷函数，传 prompt + options，async for 迭代消息
- `ClaudeSDKClient` — 持续对话，async context manager，`await client.query(prompt)` 后 `async for msg in client.receive_response()`

**ClaudeAgentOptions 关键字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `cwd` | `str \| Path` | agent 工作目录 |
| `permission_mode` | `str` | default / acceptEdits / bypassPermissions / plan / dontAsk |
| `setting_sources` | `list[str]` | 加载配置的来源：user / project / local |
| `continue_conversation` | `bool` | 是否恢复最近的 CC session |
| `resume` | `str \| None` | 指定恢复的 session_id |
| `env` | `dict[str,str]` | 环境变量 |
| `mcp_servers` | `dict` | MCP 服务器配置（stdio / SSE / HTTP / SDK MCP server） |
| `can_use_tool` | `Callable` | 工具权限回调，返回 `PermissionResultAllow` 或 `PermissionResultDeny` |
| `hooks` | `dict[str, list[HookMatcher]]` | 事件钩子，key 为 HookEvent 名称 |
| `system_prompt` | `dict \| str` | 系统提示词，`{"type": "preset", "preset": "claude_code", "append": "..."}` |
| `allowed_tools` | `list[str]` | 自动批准的工具白名单 |
| `disallowed_tools` | `list[str]` | 禁止的工具（`Bash(rm *)` 支持模式匹配） |
| `agents` | `dict[str, AgentDefinition]` | 子代理定义 |
| `skills` | `list[str] \| "all"` | 启用的技能列表 |


**消息类型**（`receive_response()` 的 yield 类型）：

| 类型 | 关键属性 |
|------|---------|
| `AssistantMessage` | `content: list[TextBlock \| ThinkingBlock \| ToolUseBlock \| ToolResultBlock \| ServerToolUseBlock \| ServerToolResultBlock]`、`model`、`parent_tool_use_id` |
| `ResultMessage` | `session_id`、`total_cost_usd`、`stop_reason`、`result` |
| `SystemMessage` | `subtype` ("init")、`data`（含 `session_id`、`mcp_servers` 等） |
| `StreamEvent` | `event`（partial text/thinking/tool_use 流事件） |
| `RateLimitEvent` | `rate_limit_info` |

**ClaudeSDKClient 关键方法：**

| 方法 | 说明 |
|------|------|
| `query(prompt, session_id=None)` | 发送 prompt（非流式），返回后即可 `receive_response()` |
| `receive_response()` | async generator，yield 上述消息类型 |
| `interrupt()` | 中断当前生成 |
| `set_permission_mode(mode)` | 动态切换权限模式 |
| `set_model(model)` | 动态切换模型 |
| `get_context_usage()` | 返回 `{"percentage", "totalTokens", "maxTokens"}` |
| `get_server_info()` | 返回 agent 进程信息（pid 等） |

**可用的 Hook 事件（Python SDK）：**

| HookEvent | 触发时机 |
|-----------|---------|
| `PreToolUse` | 工具调用前（可 deny / 修改 input） |
| `PostToolUse` | 工具调用后 |
| `PostToolUseFailure` | 工具执行失败 |
| `UserPromptSubmit` | 用户提交 prompt |
| `Stop` | agent 执行停止 |
| `SubagentStart` / `SubagentStop` | 子代理启停 |
| `PreCompact` | 对话压缩前 |
| `PermissionRequest` | 权限对话框显示前 |
| `Notification` | agent 状态消息 |

**常用工具函数：**

- `create_sdk_mcp_server(name, version, tools)` — 创建进程内 SDK MCP server
- `@tool(name, description, input_schema)` — 定义 MCP 工具
- `rename_session(session_id, title, directory)` — 重命名会话
- `fork_session(session_id, directory)` — 分支会话，返回 `{"session_id"}`
- `list_sessions(directory)` — 列出会话
- `get_session_messages(session_id, directory)` — 读取会话消息

## 构建 / 运行

```bash
# 安装（开发模式）
pip install -e .

# CLI 交互式对话
sextant chat <项目ID>

# 支持从任意目录启动项目
python -m sextant chat <项目ID>

# 查看 mailbox 消息历史
sextant mailbox

# 查看各项目状态
sextant status

# 启动 Web UI（默认 http://127.0.0.1:5008）
sextant web

# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试
python -m pytest tests/test_v2_e2e.py::TestMailbox -v
```

## 架构概览

```
cli.py          入口：subcommand 路由 (chat / web / mailbox / status)
config.py       从 sextant.yaml 解析项目列表和权限配置
session.py      SessionManager — 管理所有 CC agent 生命周期，内嵌 MCP server
chat.py         CLI REPL — 流式渲染、slash 命令处理、mailbox 草稿展示
mailbox.py      JSONL 持久化消息日志 — 跨项目通信的唯一数据源
send_message.py 唯一的 MCP 工具 — agent 调用它将消息投递到目标 mailbox
web_server.py   Flask Web UI — SSE 流式输出、REST API 封装所有 slash 命令
web/templates/index.html  单文件 SPA 前端（55KB），纯 HTML/CSS/JS，无构建工具
```

### 关键架构细节

**send_message.py 的模块级单例**：`_manager` 和 `_mailbox` 是模块级全局变量，通过 `set_manager()` / `set_mailbox()` 在 session 创建时注入。`send_message_handler` 工具函数通过闭包引用这些全局变量来获取当前 project ID 和 mailbox 实例。

**Web 模式创建独立 client**：`web_server.py` 的 `_agent_query()` 不重用 SessionManager 中的 client，而是每次请求创建一个新的 `ClaudeSDKClient`。原因是 CC SDK client 绑定到创建它的 event loop，而 Web 请求线程各自拥有独立的临时 event loop，无法安全共享 SessionManager 中 boot 线程的 client。SessionManager 的 client 仅用于跨线程调用（如 `get_context_usage`、`set_permission_mode`），通过 `_run_agent_async()` + `run_coroutine_threadsafe` 实现。

**REPL 中的双重 SIGINT**：`chat.py` 使用 `add_signal_handler` 注册 SIGINT 处理——第一次 Ctrl+C 通过 `cancel_event` 中断当前 agent query，第二次 Ctrl+C 调用 `os._exit(1)` 强制退出。

**SSE 事件类型**（前端据此渲染）：`thinking`、`text`、`tool_use`、`tool_result`、`server_tool`、`server_tool_result`、`done`、`error`、`heartbeat`。

## v2.0 核心通信模型（mailbox 驱动）

```
Agent A                    Mailbox (JSONL)                Agent B
  │                            │                             │
  ├─ send_message(to=B, …) ──→│ (写入 pending)              │
  │                            │                             │
  │                            │←── /chat B 时读取 pending ──┤
  │                            │                             │
  │                            │── mark_delivered() ────────→│
```

- `send_message` 写入 mailbox 后立即返回 ack，**不阻塞等待回复**
- 用户通过 `/chat <项目>` 切换项目时，自动展示该项目的待处理消息作为草稿
- 按 Enter 将草稿发送给 agent，或输入新内容覆盖草稿
- 消息状态仅存在于内存中（`_delivered` set），重启后可能重复显示 — 这是可接受的权衡

## 关键设计决策

1. **CLI REPL 中所有 agent 同时启动**：`SessionManager.__aenter__` 时为每个项目创建 `ClaudeSDKClient`，并在 `__aexit__` 时批量关闭。
2. **工具权限拦截**：`can_use_tool` 回调拦截所有非 `send_message` 的工具调用，通过终端提示用户审批（y/n）。`AskUserQuestion` 也被拦截并转为终端交互。Web 模式下使用 `bypassPermissions` 跳过。
3. **Web UI 跨线程 agent 调用**：agent 在后台线程的事件循环中运行（`_boot_agents` → `loop.run_forever()`）；Flask 请求线程通过 `_run_agent_async()` 使用 `run_coroutine_threadsafe` 调度到 boot 线程的 event loop 来调用 agent 方法。
4. **Web SSE 流**：每个 `/api/chat/<id>/stream` 通过 `queue.Queue` 连接后台 asyncio streaming 和 Flask SSE generator。
5. **项目 ID 即为目录名**：`ProjectConfig.id` 从 `directory` 路径的最后一段自动派生。
6. **CLI 中 `--resume` 参数**：扫描 `~/.claude/projects/<slug>/` 下的 JSONL 文件，展示会话列表供用户选择恢复。

## slash 命令（CLI + Web 均支持）

| 命令 | 功能 |
|------|------|
| `/chat <项目>` | 切换活跃项目，展示 pending mailbox 消息 |
| `/context [all]` | 上下文窗口用量 + 进度条（all 显示详细信息） |
| `/usage` 或 `/cost` | 费用 / 用量统计 |
| `/rename [标题]` | 重命名当前会话 |
| `/compact [焦点]` | 压缩对话历史 |
| `/plan` | 进入 Plan 模式（只读） |
| `/fork` 或 `/branch` | 分支当前会话 |
| `/skills` | 列出可用技能 |
| `/perm <模式>` | 切换权限模式（default / acceptEdits / plan） |
| `/model <名称>` | 切换模型 |
| `/status` | 各项目 mailbox 待处理计数 |
| `/info` | 当前 session 信息 |

## 配置文件

- `sextant.yaml`：项目列表，每个项目可配置 `directory`、`allowed_tools`、`permission_mode`、`continue`、`session_id`
- 搜索路径：`./sextant.yaml` → `~/.config/sextant/sextant.yaml` → `$XDG_CONFIG_HOME/sextant/sextant.yaml`
- `~/.claude/settings.json`：读取 `env` 字段作为 agent 环境变量

## 测试

- `tests/test_v2_e2e.py`：Mailbox、send_message 工具、SessionManager mailbox 集成、完整工作流测试
- `tests/test_phase4_render.py`：CLI 渲染测试（使用真实 SDK 类型验证 isinstance 匹配、ANSI 转义、图标显示等）
- `demo_notification.py` / `test_notification.py`：早期 MCP notification 路径验证代码，非核心功能

## 注意事项

- **不准偷懒！不准降低工作质量！** 代码改完必须实测验证，web UI 改动必须启动服务器用 curl 或浏览器端到端测试，不得只看 diff 就声称完成。测试覆盖 golden path 和 edge case。每个改动都要对自己的输出负责——不是"看起来应该对了"，而是"测过了，确实对了"。
- **修改前端代码后必须实测**：改完 `index.html` 或任何影响 Web UI 的代码后，必须启动 `sextant web`，用 curl 或浏览器验证改动生效、无回归。不能只看 diff 就声称修好了。至少抓取页面验证关键元素存在，并对涉及的 slash 命令/API 做端到端测试。
- **不要**在 agent 的 system prompt 中引入 `__user__` 概念或 `route_message` 模型 — 那是 v1.x 的旧架构，已废弃
- `send_message` 工具是 agent 间通信的**唯一**方式，不要再添加其他 IPC 机制
- Web UI 的 `permission_mode` 强制为 `bypassPermissions`，因为没有终端可供用户交互式审批工具调用
- Mailbox 数据存储在 `~/.sextant/mailbox/`，按日期分文件（`YYYY-MM-DD.jsonl`）
