# sextant — 最终设计 v4：SDK 会话管理 + 同步消息模型

> 2026-05-24 | 基于 CC Agent SDK + 五大设计原则

## 五大设计原则

| # | 原则 | 含义 |
|---|------|------|
| 1 | **project_id = basename(cwd)** | 项目标识 = 工作目录的最后一个目录名 |
| 2 | **全局串行** | 所有 CC 会话 + 用户交互在一个事件循环中串行执行 |
| 3 | **CC 不分人来人往** | 子项目 CC 只知道自己在和人对话，不区分消息来自用户还是其他 agent |
| 4 | **send_message 是同步的** | 发送消息后阻塞等待对方回复，回复作为 tool 的返回值 |
| 5 | **`__user__` 是特殊收件人** | 当 CC 向 `__user__` 发消息时，sextant 在 REPL 中阻塞等待用户输入 |

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│  sextant（Python 进程）                                  │
│                                                         │
│  ┌──────────────────┐   ┌──────────────────┐           │
│  │  MCP Tool（唯一） │   │  Router          │           │
│  │                   │   │                  │           │
│  │  send_message     │←──│  to="ncp" → 注入  │           │
│  │  (进程内 SDK)     │   │  to="__user__" →  │           │
│  │                   │   │  阻塞等用户输入    │           │
│  └──────────────────┘   └────────┬─────────┘           │
│                                  │                     │
│  ┌──────────────────┐   ┌────────┴─────────┐           │
│  │  Mailbox          │   │  Session Manager  │          │
│  │  (文件 inbox)     │   │                   │           │
│  │  持久化消息记录    │   │  acp: CCSDKClient │           │
│  └──────────────────┘   │  ncp: CCSDKClient │           │
│                         │  xcp: CCSDKClient │           │
│                         └────────┬──────────┘           │
│                                  │                       │
│  ┌───────────────────────────────┴───────────────────┐  │
│  │  REPL（sextant chat <project>）                    │  │
│  │  readline 风格输入 → send_message 路由 → 输出      │  │
│  │  CC 调用 send_message(to="__user__") 时阻塞提示用户  │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 核心简化

**没有 HTTP、没有 middleware、没有 connection registry、没有 check_inbox、没有 list_projects、没有 notification 推送。** 只有一个 MCP tool：`send_message`。

---

## Session 生命周期

```
sextant start
  │
  ├── for each project in config.yaml:
  │     client = ClaudeSDKClient(
  │       options=ClaudeAgentOptions(
  │         cwd=project.directory,
  │         mcp_servers={"sextant": sdk_mcp_server},  # 进程内
  │         permission_mode="bypassPermissions",
  │         setting_sources=["project"],  # 加载 CLAUDE.md
  │         continue_conversation=True,   # 恢复最近会话
  │       )
  │     )
  │     await client.__aenter__()
  │     sessions[project_id] = client
  │     print(f"{project_id}: session {client.session_id}")
  │
  └── 就绪，等待用户连接

sextant chat acp
  │
  ├── 连接到 sessions["acp"]
  ├── while True:
  │     ├── 等待用户输入
  │     ├── client.query(user_input)
  │     └── while 流式输出 agent 回复:
  │           ├── 文本 → print
  │           ├── send_message(to="ncp") → sextant 阻塞注入 ncp
  │           │     → 等待 ncp 回复 → 作为 tool 返回值继续
  │           └── send_message(to="__user__") → REPL 询问用户
  │                 → 用户回复 → 作为 tool 返回值继续
  │
  └── Ctrl+C → 会话保持，下次 resume 继续
```

### `continue_conversation=True` 的含义

首次 `sextant start`：
- CC SDK 在 cwd 下查找最近的会话文件
- 如果有 → 恢复，agent 可以「记得」上次做了什么
- 如果没有 → 创建新会话

sextant 重启后：
- 所有项目的会话自动恢复
- 对话历史完整保留
- agent 知道「sextant 重启前正在进行的工作」

---

## 唯一 MCP Tool：`send_message`（同步）

```python
from claude_agent_sdk import create_sdk_mcp_server, tool

@tool("send_message", "向其他项目或用户发送消息，并等待回复",
    {"to": str, "subject": str, "body": str})
async def send_message(args):
    from_id = current_project_id()
    to_id = args["to"]
    subject = args["subject"]
    body = args["body"]

    # 1. 持久化到 mailbox
    msg = Message.create(from_id=from_id, to_id=to_id,
                         subject=subject, body=body)
    mailbox.save(msg)

    # 2. 根据收件人路由
    if to_id == "__user__":
        # 特殊收件人：阻塞等待用户回复
        reply = await repl.ask_user(
            from_=from_id,
            question=f"{subject}\n\n{body}"
        )
        mailbox.save(Message.create(
            from_id="__user__", to_id=from_id,
            subject="Re: " + subject, body=reply
        ))
        return {"from": "__user__", "reply": reply}

    else:
        # 注入目标 CC 会话并同步等待回复
        target_client = sessions[to_id]
        prompt = (
            f"📬 来自 {from_id} 的消息：{subject}\n\n{body}\n\n"
            f"请处理此消息。处理完毕后，"
            f"调用 send_message(to='{from_id}', subject='Re: {subject}', body='你的完整回复')。"
        )
        await target_client.query(prompt)

        # 捕获目标 agent 的完整回复
        reply_text = ""
        async for msg in target_client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        reply_text += block.text
                        # 如果是给命令行的，可以回显
            elif isinstance(msg, ResultMessage):
                pass  # 完成

        # 如果目标 agent 没有调用 send_message 而是直接输出文本，
        # 我们把它的输出作为回复
        reply_text = reply_text.strip()
        if not reply_text:
            reply_text = "(目标 agent 未产生文本输出)"

        mailbox.save(Message.create(
            from_id=to_id, to_id=from_id,
            subject="Re: " + subject, body=reply_text
        ))
        return {"from": to_id, "reply": reply_text}


sextant_mcp = create_sdk_mcp_server(
    name="sextant",
    tools=[send_message],
)
```

### 同步模型的关键行为

| 场景 | sextant 的行为 |
|------|---------------|
| `send_message(to="ncp")` | 注入 ncp → 等待 ncp 处理完成 → 返回 ncp 的输出 |
| `send_message(to="__user__")` | REPL 中展示问题 → 阻塞等待用户输入 → 返回用户回复 |
| ncp 内部调用 `send_message(to="acp")` | sextant 检测到「ncp 正在回复 acp」→ 不递归注入 |
| ncp 内部调用 `send_message(to="__user__")` | REPL 中展示 → 用户回复 → ncp 继续 |

### 递归防护

ncp 在处理 acp 的消息时，可能调用 `send_message(to="acp")` 回复。但此时 acp 正在**阻塞等待** ncp 的回复（它的 `send_message` 还没返回）。

sextant 需要检测这个嵌套：

```python
# 全局调用栈
_call_stack: list[str] = []  # 当前正在等待回复的 project_id

async def send_message_handler(args):
    from_id = current_project_id()
    to_id = args["to"]

    # 如果目标正在等待当前调用方的回复，直接投递
    if _call_stack and _call_stack[-1] == to_id:
        # 这就是对方在等的回复，当作 return value
        return {"reply": args["body"], "from": from_id}
    
    # 否则正常处理
    _call_stack.append(from_id)
    try:
        # ... 注入目标 + 等待
    finally:
        _call_stack.pop()
```

ncp 调用 `send_message(to="acp")` → sextant 检测到 acp 正在 call_stack 顶端等 ncp → 直接返回给 acp 的 `send_message` 调用。**不递归注入。**

### `current_project_id()` 的实现

不再需要 HTTP middleware + ContextVar。sextant 在创建每个 CC 会话时，通过系统提示词注入 project_id：

```python
options = ClaudeAgentOptions(
    system_prompt={
        "type": "preset",
        "preset": "claude_code",
        "append": (
            f"你当前的项目是 {project_id}。\n"
            f"你可以调用 send_message 向其他项目发送消息并等待回复。\n"
            f"其他项目有：{', '.join(other_projects)}。\n"
            f"向 __user__ 发送消息可以询问用户。\n"
            f"收到消息时你会直接看到内容，不需要查收件箱。"
        )
    },
    ...
)
```
工具调用时 agent 自然知道自己的 project_id，会正确传递 `to` 参数。不需要程序化推断调用者身份。

---

## 消息路由机制（同步模型）

### 路由时序

```
时刻 1：用户通过 sextant chat acp 对 acp agent 说："通知 ncp 修改 XXX"
        acp agent 调用 send_message(to="ncp", subject="修改 XXX", body="...")
          │
          ▼
时刻 2：sextant send_message handler
          ├── 写 mailbox：acp → ncp
          ├── _call_stack.append("acp")
          ├── ncp_client.query("📬 来自 acp 的消息：修改 XXX\n\n请处理。处理完调用 send_message(to='acp', ...) 回复。")
          │     │
          │     ▼
          │   时刻 3：ncp agent 处理消息
          │          ncp agent 分析 → 不确定 → 调用 send_message(to="acp", subject="Re: 修改 XXX", body="是要改 XXX-1 吗？")
          │            │
          │            ▼
          │           sextant 检测到 _call_stack[-1] == "acp"
          │           → 直接返回 {"reply": "是要改 XXX-1 吗？", "from": "ncp"}
          │           → ncp agent 收到返回值，继续处理（或结束 turn）
          │
          ├── _call_stack.pop()
          └── 返回 {"from": "ncp", "reply": "是要改 XXX-1 吗？"}

时刻 4：acp agent 收到 send_message 的返回值 "是要改 XXX-1 吗？"
        acp agent 继续思考 → 调用 send_message(to="ncp", subject="Re: 修改 XXX", body="不是 XXX-1，是 XXX-2")
          │
          ▼
        ……同步等待 ncp 回复（同上流程）

时刻 5：acp agent 收到 "明白了，已完成修改"
        输出给用户："ncp 已完成修改"
```

### 关键简化

没有 `check_inbox`、没有异步队列、没有 `asyncio.Lock`、没有 `_flush` 后台任务。**send_message 就是同步函数调用——注入 prompt → 等待 agent 处理 → 返回结果。**

---

## REPL：`sextant chat`

```python
async def chat(project_id: str):
    client = sessions[project_id]

    print(f"sextant · {project_id}")
    print(f"输入消息，Ctrl+C 退出\n")

    while True:
        # 1. 等待用户输入
        try:
            user_input = await read_input("> ")
        except (KeyboardInterrupt, EOFError):
            break

        if user_input.startswith("/"):
            await handle_command(user_input)
            continue

        # 2. 发送到 agent + 流式输出
        #    agent 调用 send_message 时 sextant 会阻塞处理
        await client.query(user_input)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        print(block.text, end="", flush=True)
            elif isinstance(msg, ResultMessage):
                print()  # 换行

    print(f"\n会话保持中。下次 `sextant chat {project_id}` 继续。")


async def repl_ask_user(from_: str, question: str) -> str:
    """处理 send_message(to="__user__")：阻塞等待用户回复"""
    print(f"\n{'─'*40}")
    print(f"🤔 {from_} 想知道：")
    print(question)
    print(f"{'─'*40}")
    try:
        answer = await read_input("> ")
        return answer
    except (KeyboardInterrupt, EOFError):
        return "(用户未回复)"
```

### 用户看到的效果

```
sextant chat acp

> 通知 ncp 和 xcp 需要改的内容

[acp] 让我整理一下……ncp 要改 XXX-2，xcp 要改 YYY-3。

[acp 调用 send_message(to="ncp", ...)]

┌─ ncp 处理中 ─┐
│ [ncp 分析中]  │
│ [ncp 调用 send_message(to="acp", "是要改 XXX-1 吗？")]  │
└──────────────┘

[acp 收到回复] 不是 XXX-1，是 XXX-2。
[acp 调用 send_message(to="ncp", ...)]

┌─ ncp 处理中 ─┐
│ [ncp] 明白了 │
└──────────────┘

[acp] ncp 已确认修改 XXX-2。

[acp 调用 send_message(to="xcp", ...)]

┌─ xcp 处理中 ─┐
│ [xcp 调用 send_message(to="acp", "是要改 YYY-1 吗？")]  │
└──────────────┘

[acp 收到回复] 嗯……xcp 问是要改 YYY-1。
[acp 调用 send_message(to="__user__", "xcp 问：是要修改 YYY-1 还是 YYY-3？")]

──────────────────────────────────────────
🤔 acp 想知道：
xcp 问：是要修改 YYY-1 还是 YYY-3？
──────────────────────────────────────────
> YYY-3

[acp 收到回复] YYY-3
[acp 调用 send_message(to="xcp", "确认，修改 YYY-3")]

┌─ xcp 处理中（编译、测试，可能很久）━━━━━┓
┃ [xcp] 开始修改 YYY-3...                  ┃
┃ [xcp] 编译 23/45 模块...                  ┃
┃ [xcp] 发现类型错误，修复中...              ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

……用户可能需要等，或者 Ctrl+C 切到 xcp 去看
```

**和 CC CLI 的区别：**
- 没有 `Bash`、`Read` 等工具调用的实时展示（agent 在后台处理）
- 没有权限弹窗（`bypassPermissions` 模式）
- agent 调用 `send_message` 时会有「处理中」的视觉提示
- `send_message(to="__user__")` 时 REPL 切换为「回答问题」模式

---

## 用户多 session 交互

### 扫描模式：`sextant chat xcp`

用户随时可以 Ctrl+C 退出当前 chat，然后 `sextant chat xcp` 切入任何项目。

**因为全局串行（原则 2）**，当用户切到 xcp 时，acp 和 ncp 都处于空闲状态——没有正在进行的 `send_message` 调用。所有 session 的状态都已落盘。

```
$ sextant chat xcp

sextant · xcp
> 进度怎么样？

[xcp] 正在编译 23/45 模块，遇到一个类型错误正在修复……
[xcp] 预计还需要 2-3 分钟。

> 好的，继续

Ctrl+C
$ sextant chat acp

[回到 acp，会话保持完整]
```

### 直接给 xcp 发消息会搞复杂吗？

**不会。** xcp agent 看到的对话流：

1. `send_message` 注入："来自 acp：修改 YYY-3"
2. 用户 prompt："进度怎么样？"

xcp 不区分消息来源。它在同一个会话里顺序处理。

**潜在的一点**：如果用户通过 `sextant chat xcp` 直接和 xcp 说话时，acp 恰好在等待 xcp 的 `send_message` 回复，会怎样？

**不会发生**（原则 2：全局串行）。用户必须先 Ctrl+C 退出 `acp chat` 才能切到 `xcp chat`。退出 `acp chat` 时，acp 的 `send_message` 调用已经结束（要么 xcp 回复了，要么还没调用）。只要聊天循环还在处理 `send_message` 响应，用户就无法切出。所以不会有两边同时操作同一个 session 的情况。<｜end▁of▁thinking｜>## 项目结构（v4 终版）

```
sextant/
├── pyproject.toml
├── src/sextant/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py          # 配置（不变）
│   ├── mailbox.py         # 文件 inbox（不变）
│   ├── session.py         # 🆕 CC SDK 会话管理
│   ├── send_message.py    # 🆕 唯一 MCP tool + 同步路由逻辑
│   ├── chat.py            # 🆕 sextant chat REPL（含 __user__ 处理）
│   └── cli.py             # 🔧 sextant start / sextant chat
├── tests/
│   ├── test_config.py
│   ├── test_mailbox.py
│   └── test_send_message.py
└── .aireports/
    ├── impl_plan.md
    ├── 20260524_code_design.md
    ├── 20260524_sdk_limitations.md
    ├── 20260524_hybrid_architecture.md
    ├── 20260524_ecosystem_research.md
    └── 20260524_final_design_v4.md
```

## 和之前设计的 diff

| 删除 | 新增/修改 |
|------|----------|
| `server.py` — FastMCP + HTTP transport | `send_message.py` — 单一同步 tool |
| `connection.py` — ConnectionRegistry | `session.py` — `ClaudeSDKClient` 管理 |
| `middleware` — ContextVar 桥接 | 不需要 |
| `router.py` — 异步消息队列 + lock | 不需要（同步模型消除异步复杂性） |
| `mcp_tools.py` — 3 个 tools | 不需要（只剩 1 个 tool） |
| `templates/claude_md.md` | `chat.py` — REPL + `__user__` 处理 |
| `cli.py` — `sextant start`（HTTP 版） | `cli.py` — `sextant start`（SDK 版）+ `sextant chat` |

**净效果：代码量减半，模块从 6 个变 4 个核心模块。**

## 实现顺序

```
Phase 1：单 session + REPL（半天）
  ├── 1.1 session.py — 创建单个 ClaudeSDKClient
  ├── 1.2 chat.py — 最简 REPL（输入 → query → 输出）
  └── 验证：sextant chat acp → 和 CC agent 对话

Phase 2：同步 send_message（半天）
  ├── 2.1 send_message.py — 单一 tool + 同步路由
  ├── 2.2 递归防护（_call_stack）
  └── 验证：acp → send_message(to="ncp") → ncp 回复 → acp 收到

Phase 3：__user__ 特殊收件人（半天）
  ├── 3.1 chat.py — repl_ask_user() 阻塞等待
  ├── 3.2 send_message.py — to="__user__" 分支
  └── 验证：CC 调用 send_message(to="__user__") → REPL 阻塞 → 用户回复

Phase 4：打磨 + 三项目 E2E（半天）
  ├── 4.1 错误处理（query 失败 → 返回错误给调用方）
  ├── 4.2 日志 + mailbox 审计
  └── 4.3 acp/ncp/xcp 三个项目完整场景验证
```

## 开放问题

1. **`bypassPermissions` 的安全性**：headless 模式下 agent 是否会执行危险操作。初期可以限制 `allowed_tools` 为只读。

2. **CC Agent SDK session 的并发访问**：同步模型下不会有两个协程同时操作同一个 client。但 `query()` 调用期间，SDK 内部是否有并发保护？需要实测。

3. **CC SDK 子进程开销**：每个 `ClaudeSDKClient` 启动一个 CC CLI 子进程。3-4 个项目 = 3-4 个 Node 进程，内存 ~200MB/个，可接受。

4. **`continue_conversation=True` 的准确保留**：CC SDK 的会话持久化路径和文件格式需要确认。如果重启 sextant 后会话恢复失败，有没有降级方案（创建新会话）？

5. **长时间 send_message 的用户体验**：xcp 处理大任务时用户可能需要等几分钟。Ctrl+C 退出 sextant chat 后，acp 的 `send_message` 仍然在阻塞中——下次 resume 会是什么状态？需要验证 CC SDK 的 interrupt 支持。
