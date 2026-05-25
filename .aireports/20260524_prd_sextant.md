# sextant — 产品需求文档 (PRD)

> **版本**: 1.3  
> **日期**: 2026-05-25  
> **状态**: Phase 1-5 已完成，Phase 6 待开发  
> **作者**: ZP & 墨鱼  

---

## 目录

1. [摘要](#1-摘要)
2. [问题陈述](#2-问题陈述)
3. [产品愿景](#3-产品愿景)
4. [目标用户与使用场景](#4-目标用户与使用场景)
5. [核心设计原则](#5-核心设计原则)
6. [功能需求](#6-功能需求)
7. [非功能需求](#7-非功能需求)
8. [系统架构](#8-系统架构)
9. [用户交互模型](#9-用户交互模型)
10. [消息路由模型](#10-消息路由模型)
11. [端到端协作场景](#11-端到端协作场景)
12. [API 规范：唯一 MCP Tool](#12-api-规范唯一-mcp-tool)
13. [会话管理](#13-会话管理)
14. [并发与递归控制](#14-并发与递归控制)
15. [错误处理](#15-错误处理)
16. [开发进度](#16-开发进度)
17. [实现计划](#17-实现计划)
18. [开放问题与风险](#18-开放问题与风险)
19. [附录](#19-附录)

---

## 1. 摘要

**sextant** 是一个多项目 Agent 协同开发工具。它让开发者在**一个终端界面**中管理多个 Claude Code 实例，实现 Agent 间的跨项目通信、消息路由与协作。

核心思路：用 Claude Code Agent SDK 管理所有 CC 会话，通过一个名为 `send_message` 的 MCP tool 实现 Agent 间的**异步**消息传递。消息全部流经 mailbox（JSONL 持久化），Agent 不区分 prompt 来源（人/Agent）。用户通过 `sextant chat <project>` REPL 与任一项目的 Agent 交互，用户审批和提问通过 CC SDK 的 `canUseTool` 回调统一处理。

**一句话定位**：一个终端，多个 CC Agent，互相协作完成跨项目开发任务。

---

## 2. 问题陈述

### 2.1 当前痛点

在大型项目的多仓库（multi-repo）或多模块开发中，开发者经常面临以下问题：

| 痛点 | 描述 |
|------|------|
| **多窗口管理** | 需要为每个子项目打开独立的 CC 终端窗口，在 3-4 个窗口间反复切换 |
| **消息传递依赖人工** | Agent A 想通知 Agent B 做某件事，只能靠用户口头转述或在 A 的终端里手动切换后重复命令 |
| **Agent 之间零协作** | 每个 CC 实例是完全隔离的，不知道其他 Agent 的存在 |
| **编译等待的碎片时间** | 在等待 Agent A 编译/测试时切到 Agent B，但切回来后 A 的上下文已中断 |
| **用户是瓶颈** | 所有跨项目协作都经过用户，用户变成"人工消息总线"，体验极差 |

### 2.2 核心矛盾

> 开发者只有**一个脑袋**和**一个终端**，却要同时管理多个 CC Agent。现有的 CC CLI 是为单项目设计的，不支持多会话路由。

### 2.3 为什么现有方案不够

- **`claude mcp serve`**：CC 原生支持作为 MCP server，但无状态——每次工具调用是独立的 CC 实例，不记得上次对话。无法实现持续的多轮 Agent 协作。
- **多终端 + tmux**：只解决了窗口切换，没有解决 Agent 间通信。用户仍是消息中转站。
- **A2A 协议（Agent-to-Agent）**：引入了不必要的协议层。sextant 需要的是消息路由，不是语义协商。

---

## 3. 产品愿景

### 3.1 核心体验

```
一个终端，一个 REPL，所有项目。
Agent 间能直接对话，用户无需当中转站。

$ sextant chat acp

> 通知 ncp 修改 XXX，让 xcp 同步更新 YYY

[acp 理解意图 → 自动通知 ncp 和 xcp → 收集他们的回复 → 汇报给用户]

整个过程用户在同一个终端完成，不需要切换窗口。
```

### 3.2 产品边界

**sextant 做什么**：
- 管理多个 CC Agent 会话（启动、恢复、关闭）
- 提供统一的 REPL 界面，让用户与任一 Agent 交互
- 提供 `send_message` 工具，让 Agent 之间可以**异步**发送消息（mailbox 驱动）
- 通过 `canUseTool` 回调统一处理所有 Agent 的用户交互（工具审批、问题询问）
- 持久化所有消息到 mailbox（JSONL），支持审计回溯

**sextant 不做什么**：
- 不实现 A2A 协议或语义路由
- 不做 Agent 能力发现或任务分发
- 不介入 Agent 的权限管理（使用 CC 的 `bypassPermissions`）
- 不做并发多用户支持（单人使用）

---

## 4. 目标用户与使用场景

### 4.1 目标用户

- **角色**: 全栈开发者 / 系统程序员
- **特征**: 同时维护 2-5 个相关联的代码仓库，日常需要跨项目协作开发
- **技能水平**: 熟悉 Claude Code CLI，习惯终端操作
- **工作模式**: 串行思考，一次关注一件事，但需要在多个项目上下文间快速切换

### 4.2 核心使用场景

**场景 A：跨项目功能开发**

> 用户在 `acp` 项目中修改协议定义，需要通知 `ncp` 修改服务端实现，`xcp` 修改客户端实现。

理想流程：用户在 `acp` 中对 Agent 说"通知 ncp 和 xcp 需要改的内容"，Agent 自动发送消息给两个项目，收集回复，确认后汇报给用户。

**场景 B：Agent 发出澄清请求**

> `xcp` Agent 在处理 `ncp` 发来的修改请求时不确定具体改哪个文件，向 `ncp` 提问。`ncp` 也不知道，需要问用户。

理想流程：`xcp` → `ncp` → 用户，用户做出选择后，答案沿原路返回给 `xcp`。

**场景 C：跨项目编译等待**

> `xcp` 正在编译（耗时 2-3 分钟），用户在此期间切到 `acp` 继续工作。编译完成后切回 `xcp` 查看结果。

理想流程：`Ctrl+C` 退出 `acp chat`，`sextant chat xcp` 切入，查看进度。两个会话独立保持。

---

## 5. 核心设计原则

sextant 的设计由以下五条原则驱动。所有架构决策都必须与这些原则一致：

| # | 原则 | 含义 | 设计影响 |
|---|------|------|----------|
| P1 | **project_id = basename(cwd)** | 项目标识等同于工作目录的最后一个目录名 | 无需额外配置，从文件路径直接推导 |
| P2 | **全局串行** | 所有 CC 会话 + 用户交互在单个事件循环中串行执行 | 消除并发竞争，无需锁机制 |
|| P3 | **CC 无言者之分** | Agent 收到的所有 prompt 统一来源于 mailbox，不区分"人发的"还是"Agent 发的" | 消除 Agent 端的区别对待，无需 system prompt 教回复 |
|| P4 | **send_message 投递即忘** | `send_message` 写入 mailbox 后立即返回 ack，不阻塞、不等回复 | 消除同步等待、递归防护、call_stack 全部作废 |
|| P5 | **mailbox 是唯一真相源** | 所有人→Agent、Agent→Agent、Agent→人的消息全走 mailbox；Agent 的下一轮 prompt 由 mailbox 拼装 | 消息流单一入口，可审计、可回溯、可重放 |
|| P6 | **`__user__` 通过 canUseTool 交互** | Agent 需要用户决策时通过 `canUseTool` 回调弹窗，前台/后台 Agent 统一使用同一机制 | 用户交互不再靠 MCP tool，不受 Agent 间消息流影响 |

---

## 6. 功能需求

### 6.1 FR1：多项目 Agent 会话管理

**描述**: 系统管理多个 CC Agent 会话，支持启动、恢复、关闭。

**详细要求**:
- FR1.1: `sextant start` 命令启动所有配置中定义的项目 Agent
- FR1.2: 通过 `ClaudeSDKClient` 管理每个 Agent 的生命周期
- FR1.3: 启动时自动恢复最近的会话（`continue_conversation=True`）
- FR1.4: 会话文件持久化在对应项目的 `cwd` 下，由 CC SDK 管理
- FR1.5: 每个 Agent 通过进程内 MCP server 获得 `send_message` 工具

**输入**: `sextant.yaml` 配置文件，其中列出所有项目及其工作目录

**输出**: 所有 Agent 就绪，日志输出各 session_id

---

### 6.2 FR2：统一 REPL 交互界面

**描述**: 用户通过 `sextant chat <project>` 与任一项目 Agent 交互。

**详细要求**:
- FR2.1: 提供 readline 风格的输入提示（`> `）
- FR2.2: 流式输出 Agent 的文本回复
- FR2.3: Agent 调用需要审批的工具或 `AskUserQuestion` 时，`canUseTool` 回调在 REPL 中弹窗等待用户决策
- FR2.4: `Ctrl+C` 退出当前 chat，会话保持，下次 resume 继续
- FR2.5: 支持 `/` 开头的内置命令（如 `/help`，未来可扩展）

---

### 6.3 FR3：Agent 间异步消息传递

**描述**: Agent 通过 `send_message` MCP tool 向其他 Agent 投递消息。消息写入 mailbox 后立即返回，目标 Agent 在下一次获得 prompt 时从 mailbox 拉取并处理。

**详细要求**:
- FR3.1: 参数 `to`（收件人 project_id）、`subject`（标题）、`body`（消息正文）
- FR3.2: 调用后**立即返回** ack（`{"status": "sent", "msg_id": "..."}`），不阻塞
- FR3.3: 所有消息持久化到 mailbox（JSONL 文件），按收件人分组
- FR3.4: 目标 Agent 下一次获得 prompt 时，sextant 将 mailbox 中的待处理消息拼入上下文
- FR3.5: 目标 Agent 处理完消息后的文本输出，自动写回发送方 mailbox 作为回复
- FR3.6: Agent **不需要**主动调用 `send_message` 来"回复"——它的自然输出就是回复

**约束**:
- FR3-C1: 只有 `send_message` 一个 MCP tool，没有 `check_inbox`、`list_projects` 等
- FR3-C2: Agent 收到的 prompt 由 `[mailbox 待处理消息] + [用户输入]` 拼接而成，不区分来源

---

### 6.4 FR4：用户交互（canUseTool）

**描述**: Agent 需要用户决策时通过 CC SDK 的 `canUseTool` 回调触发交互。不再使用 `send_message(to="__user__")`。

**详细要求**:
- FR4.1: Agent 调任何需要审批的工具（Bash/Write/Edit 等）→ `canUseTool` 拦截 → 展示给用户审批
- FR4.2: Agent 调 `AskUserQuestion` → `canUseTool` 拦截 → 格式化选项展示给用户
- FR4.3: 前台 Agent（当前 REPL 中的项目）：直接在 REPL 内弹窗交互
- FR4.4: 后台 Agent（非当前 REPL 项目）：审批请求入队，用户切到该项目时处理，或通过状态栏提示
- FR4.5: 用户可用 `y/n` 批准/拒绝工具调用，或选择 AskUserQuestion 的选项
- FR4.6: 用户回复写入 mailbox 持久化记录

**设计意图**: `canUseTool` 是 CC SDK 的标准用户交互机制。所有 Agent（前台/后台）**统一使用同一套机制**，不再通过 MCP tool 绕路。

---

### 6.5 FR5：消息持久化与审计

**描述**: 所有 Agent 间消息记录到文件系统，支持回溯。

**详细要求**:
- FR5.1: 每条消息包含 `from_id`、`to_id`、`subject`、`body`、`timestamp`
- FR5.2: 存储为 JSON 格式，按项目分目录
- FR5.3: 提供 `sextant mailbox <project>` 命令查看历史消息

---

## 7. 非功能需求

### 7.1 NFR1：可靠性

- NFR1.1: sextant 进程重启后，所有 Agent 会话自动恢复
- NFR1.2: 会话恢复失败时，自动创建新会话（降级策略）
- NFR1.3: `send_message` 调用如果目标 Agent 出错，返回错误信息给调用方而非崩溃

### 7.2 NFR2：性能

- NFR2.1: sextant 启动时间 < 10 秒（含所有 Agent 初始化）
- NFR2.2: `send_message` 写入 mailbox 的延迟 < 10ms（同步文件 I/O）
- NFR2.3: 3-4 个 CC Agent 的内存开销控制在 1GB 以内

### 7.3 NFR3：可维护性

- NFR3.1: 核心代码量 < 1000 行
- NFR3.2: 仅依赖 CC Agent SDK + Python 标准库
- NFR3.3: 模块间耦合最小化：session、send_message、chat、cli 各司其职

### 7.4 NFR4：安全

- NFR4.1: `bypassPermissions` 模式下运行，初期限制 `allowed_tools` 为只读
- NFR4.2: 不做网络暴露（本地进程内 MCP，无 HTTP endpoint）
- NFR4.3: mailbox 文件权限 0600

---

## 8. 系统架构

### 8.1 架构图

```
┌──────────────────────────────────────────────────────────────┐
│                    sextant（Python 进程）                      │
│                                                              │
│  ┌──────────────────────┐    ┌───────────────────────────┐   │
│  │   MCP Tool（唯一）    │    │     Mailbox（唯一真相源）   │   │
│  │                      │    │                           │   │
│  │   send_message       │◄───│  写入: agent调send_message │   │
│  │   (投递即忘)          │    │  读取: 组装agent prompt    │   │
│  └──────────────────────┘    │  持久化: JSONL 按日分片    │   │
│                              └──────────┬────────────────┘   │
│                                         │                    │
│  ┌──────────────────────┐    ┌──────────┴────────────────┐   │
│  │   canUseTool 回调     │    │   Session Manager        │   │
│  │                      │    │                          │   │
│  │   工具审批 (Bash/..)  │◄───│   acp: ClaudeSDKClient   │   │
│  │   AskUserQuestion    │    │   ncp: ClaudeSDKClient   │   │
│  │   统一前台/后台弹窗   │    │   xcp: ClaudeSDKClient   │   │
│  └──────────────────────┘    └──────────┬───────────────┘   │
│                                         │                   │
│  ┌──────────────────────────────────────┴────────────────┐  │
│  │   REPL（sextant chat <project>）                      │  │
│  │   readline 输入 → mailbox拼装 → query → 流式输出       │  │
│  │   输出自动写回 mailbox 作为回复                        │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 模块职责

| 模块 | 职责 | 关键技术 |
|------|------|----------|
| `config.py` | 解析 `sextant.yaml`，提供项目列表和路径 | PyYAML |
| `mailbox.py` | **核心模块**：消息写入、读取、组装 prompt、回复回写 | JSONL 文件 I/O |
| `session.py` | 管理 ClaudeSDKClient 生命周期 + `canUseTool` 回调 + mailbox 注入 | CC Agent SDK |
| `send_message.py` | 唯一 MCP tool：接收 Agent 调用 → 写入 mailbox → 立即返回 ack | CC SDK `create_sdk_mcp_server` |
| `chat.py` | REPL 交互：输入 → 从 mailbox 组装 prompt → query → 流式输出 → 输出回写 mailbox | asyncio + readline |
| `cli.py` | CLI 入口：`sextant chat`、`sextant mailbox`、`sextant status` | argparse |

### 8.3 技术选型

| 技术 | 用途 | 理由 |
|------|------|------|
| CC Agent SDK (`claude_agent_sdk`) | 管理 CC 会话、注入 prompt、接收回复 | CC 官方 SDK，`create_sdk_mcp_server` 支持进程内 MCP |
| `ClaudeSDKClient.query()` | 向 Agent 注入消息 | 不需要 HTTP transport，直接 Python API 调用 |
| `create_sdk_mcp_server()` | 为每个 CC 实例注册 `send_message` tool | 进程内调用，无网络开销 |
| `bypassPermissions` | 禁止权限弹窗 | headless 模式下弹窗会让 Agent 卡住 |
| `continue_conversation=True` | 恢复历史会话 | CC SDK 自动管理会话持久化 |

---

## 9. 用户交互模型

### 9.1 正常对话

```
$ sextant chat acp

sextant · acp
> 帮我分析 ncp 的最新提交，整理出需要同步的变更

[acp] 让我查看 ncp 的提交记录……
[acp] 发现 3 个需要同步的变更：……

> 好的，记下来
```

用户输入 → `client.query(input)` → 流式输出 Agent 回复 → 等待下次输入。循环。

### 9.2 Agent 请求用户审批

当 Agent 调用需要审批的工具（如 Bash/Write）时，`canUseTool` 回调拦截并展示：

```
[ncp] 我需要修改 auth_middleware.py...
──────────────────────────────────────────
🤔 ncp 想执行：
允许 Edit?
  ✏️ /src/auth/auth_middleware.py
  -Token = field["token"]
  +Token = TokenStruct(**field["token"])
──────────────────────────────────────────
> y

[ncp] 已修改。
```

Agent 也可以通过 `AskUserQuestion` 直接提问：

```
[ncp] src/auth/ 下有两个文件用了 Token，不确定改哪些...
──────────────────────────────────────────
🤔 ncp 想知道：
修改范围？

  1. 只改 token_serializer.py（序列化层）
  2. 序列化 + auth_middleware 的 map 逻辑一起改
  3. 暂改序列化，auth_middleware 单独排查
──────────────────────────────────────────
> 2

[ncp] 收到，一起改。
```

**关键**：`canUseTool` 是 CC SDK 的标准机制。所有 Agent（无论前台/后台）都通过同一个回调处理用户交互。不再有特殊的 `send_message(to="__user__")` 路径。

### 9.3 切换项目

```
Ctrl+C                          # 退出 acp chat

$ sextant chat ncp              # 切入 ncp

sextant · ncp
> 刚才 acp 让你改的东西改完了吗？

[ncp] 已完成，正在编译测试……
[ncp] 编译通过，12/12 测试通过 ✓

Ctrl+C                          # 退出 ncp chat

$ sextant chat acp              # 回到 acp

[acp 会话从刚才的状态继续]
```

### 9.4 会话恢复

```
$ sextant start                 # 启动
acp: session sid_v1_abc123
ncp: session sid_v1_def456
xcp: session sid_v1_ghi789
所有 Agent 就绪 ✓

$ sextant chat acp              # 打开

sextant · acp
> 继续之前的工作……
[acp 记得之前的上下文，从上次中断的地方继续]
```

---

## 10. 消息模型：mailbox 驱动

### 10.1 核心思想

**mailbox 是 sextant 的唯一真相源。** 所有人→Agent、Agent→Agent、Agent→人的消息全部流经 mailbox。Agent 不区分 prompt 来源——无论来自人还是其他 Agent，对 Agent 来说都是"我收到了新消息需要处理"。

```
发送方 → send_message() 写入 mailbox → 立即返回 ack
接收方 → 下一轮 prompt = [mailbox待处理消息] + [用户输入] → 正常处理
接收方输出 → 自动写回发送方 mailbox 作为回复
```

### 10.2 消息生命周期

```
Step 1: Agent A 调用 send_message(to="B", subject="...", body="...")
        → mailbox.record(from="A", to="B", subject, body, status="pending")
        → 立即返回 {"status": "sent", "msg_id": "xxx"} 给 Agent A
        → Agent A 继续工作，不阻塞

Step 2: Agent B 获得新 prompt（用户输入 或 系统触发）
        → sextant 查询 mailbox: "B 有哪些 pending 消息？"
        → 拼装 prompt:
            "📬 你有 1 条新消息:
             
             [来自 A] 主题: ...
             正文: ...
             
             ---
             用户输入: <用户刚输入的内容>"

Step 3: Agent B 处理 prompt（自然处理，不需要区分消息来源）
        → 可能调用工具、思考、输出文本
        → 全程 canUseTool 处理用户审批（Bash/Write 等）

Step 4: Agent B 的文本输出被收集
        → mailbox.record_reply(msg_id="xxx", reply="B 的完整输出", from="B")
        → msg 状态: pending → replied

Step 5: Agent A 下一次获得 prompt 时
        → mailbox 中有 B 的回复 → 拼入 prompt 上下文
        → Agent A 看到 "📬 B 回复了你的消息「主题」: ..."
```

### 10.3 send_message 的新语义

| 项目 | 旧模型 (Phase 1-5) | 新模型 (Phase 6+) |
|------|-------------------|-------------------|
| **调用行为** | 同步阻塞，等对方回复 | 写入 mailbox，立即返回 |
| **返回值** | `{"reply": "...", "from": "ncp"}` | `{"status": "sent", "msg_id": "xxx"}` |
| **递归防护** | 需要 `_call_stack` | 不需要（异步解耦） |
| **System prompt** | 教 Agent "处理完请用 send_message 回复" | 不需要（回复由 sextant 自动处理） |
| **Agent 是否区分来源** | 名义上不区分，实际上 prompt 带发送者标注 | prompt 统一拼装，真正不区分 |

### 10.4 `__user__` 的新位置

`__user__` 不再是 `send_message` 的特殊收件人。用户交互移入 `canUseTool` 回调：

```
Agent 需要审批工具（Bash/Write/Edit）
  → canUseTool 拦截
  → 展示给用户：工具名 + 参数
  → 用户 y/n
  → PermissionResultAllow / PermissionResultDeny

Agent 需要问用户问题（AskUserQuestion）
  → canUseTool 拦截（tool_name == "AskUserQuestion"）
  → 格式化选项 → 用户选择
  → PermissionResultAllow(updated_input={answers})
```

**前台 vs 后台**:
- 前台 Agent（当前 REPL 项目）：直接在终端内弹窗，用户即时响应
- 后台 Agent（非当前项目）：prompt 暂存到 mailbox，切到该项目时处理；状态栏提示 "ncp 等待审批 (Bash)"

---

## 11. 端到端协作场景

> 以下场景演示 mailbox 驱动模型下的三 Agent 协作。核心变化：send_message 不再阻塞，Agent 间通信变成"发消息 → 切项目 → 收消息 → 回复自动回写"的异步流程。

### 11.1 初始条件

```
项目：
  acp — 协议仓库（用户当前 REPL：sextant chat acp）
  ncp — 服务端仓库（Python）
  xcp — 客户端仓库（Rust）

每个 Agent 的 system prompt：
  - 你的项目是 {project_id}
  - 可以通过 send_message(to, subject, body) 向其他项目发消息
  - 收到的消息会自然出现在 prompt 中，不需要查收件箱
  - 用户交互通过 canUseTool 弹窗（工具审批、问题询问）
```

### 11.2 场景：协议变更跨项目同步

任务：用户修改了 proto 协议，Token 字段从 `string` 改为 `TokenStruct`，需要 ncp 和 xcp 同步修改。

#### Step 1：用户对 acp 发起

```
$ sextant chat acp

sextant · acp
> 我刚改了协议，Token 字段从 string 改成 TokenStruct{token:string, expiry:int64, issuer:string}。
> 通知 ncp 和 xcp 同步修改，确认编译通过后汇总给我。
```

#### Step 2：acp 发送消息（不阻塞）

acp 理解任务后，调用 send_message：

```
send_message(to="ncp", subject="同步协议变更：Token → TokenStruct",
  body="Token 字段从 string 改为 TokenStruct{token,expiry,issuer}。请修改服务端序列化代码。")
→ {"status": "sent", "msg_id": "m1"}   ← 立即返回！

send_message(to="xcp", subject="同步协议变更：Token → TokenStruct",  
  body="Token 字段从 string 改为 TokenStruct{token,expiry,issuer}。请修改 Rust 客户端代码。")
→ {"status": "sent", "msg_id": "m2"}   ← 立即返回！
```

acp 汇报：

```
[acp] 已通知 ncp 和 xcp。ncp 需要改序列化代码，xcp 需要改 Rust 客户端。
      消息已发送，等他们处理完我会汇总。
```

#### Step 3：用户切换到 ncp

```
Ctrl+C                          # 退出 acp

$ sextant chat ncp

sextant · ncp
📬 你有 1 条新消息:

[来自 acp] 同步协议变更：Token → TokenStruct

Token 字段从 string 改为 TokenStruct{token,expiry,issuer}。请修改服务端序列化代码。

---
```

ncp 开始处理：

```
[ncp] 收到 acp 的协议变更通知。让我查看当前代码...

[ncp] src/auth/token_serializer.py 中 Token 需要从 string 改成 TokenStruct。
      src/auth/auth_middleware.py 也用了 Token 做 map key，这里需要一起改吗？

  ── canUseTool 弹窗 ──
  🤔 ncp 想知道：
  
  1. 只改 token_serializer.py（序列化层）
  2. 序列化 + auth_middleware 的 map 逻辑一起改
  
  > 2，一起改，别留技术债
  ──────────────────────

[ncp] 收到。正在修改...
[ncp] token_serializer.py ✓  auth_middleware.py ✓
[ncp] 编译中...
[ncp] 编译通过，所有测试通过 ✓
```

ncp 的输出自动写回 acp 的 mailbox。

#### Step 4：用户切换到 xcp

```
Ctrl+C

$ sextant chat xcp

sextant · xcp
📬 你有 1 条新消息:

[来自 acp] 同步协议变更：Token → TokenStruct

Token 字段从 string 改为 TokenStruct{token,expiry,issuer}。请修改 Rust 客户端代码。

---
```

xcp 处理：

```
[xcp] 收到协议变更。查看 Rust 端的 Token 使用...
[xcp] src/token.rs 需要改反序列化。
      src/config.rs 中 Token 被用作连接池 key，改成 TokenStruct 后需要 Hash trait。

  ── canUseTool 弹窗 ──
  🤔 xcp 想知道：
  
  1. 给 TokenStruct 加 #[derive(Hash)]
  2. 改用 token 字符串做 key
  
  > 1
  ──────────────────────

[xcp] #[derive(Hash)] 已添加。
[xcp] cargo build... 编译通过 ✓
[xcp] cargo test... 测试全部通过 ✓
```

xcp 的输出自动写回 acp 的 mailbox。

#### Step 5：用户切回 acp，查看汇总

```
Ctrl+C

$ sextant chat acp

sextant · acp
📬 你有 2 条回复:

1. [来自 ncp] Re: 同步协议变更：Token → TokenStruct
   token_serializer.py 已修改。auth_middleware.py 的 map 逻辑也一起改了。编译通过，测试通过 ✓

2. [来自 xcp] Re: 同步协议变更：Token → TokenStruct
   token.rs 反序列化已更新。config.rs 添加了 #[derive(Hash)]。编译通过，测试通过 ✓

---
```

acp 自动汇总：

```
[acp] 协议变更同步完成。汇总：

📊 Token string → TokenStruct 跨项目同步
  ✓ ncp（服务端）
    • token_serializer.py — 已修改
    • auth_middleware.py — 已修改（含 map 逻辑）
    • 编译通过，测试通过
  ✓ xcp（客户端）
    • token.rs — 已修改
    • config.rs — 已修改（#[derive(Hash)]）
    • 编译通过，测试通过
```

### 11.3 新模型关键洞察

#### 为什么 ncp/xcp 不需要"回复"指令？

在旧模型中，sextant 必须教 Agent "处理完请用 send_message 回复"。新模型中，**Agent 的输出就是回复**——sextant 自动收集 ncp/xcp 的完整文本输出，写回 acp 的 mailbox。Agent 完全不需要知道"有人在等我回复"。

#### Agent 消息与用户输入如何统一？

```
sextant 拼装 prompt 时：

  [如果有 mailbox 待处理消息]
    📬 你有 N 条新消息:
    [消息1 内容]
    [消息2 内容]
    ---

  [如果有用户输入]
    <用户输入>

  [如果都没有 — 后台 agent 空闲，等待下次触发]
```

Agent 收到的永远是一个完整的 prompt，内容来自 mailbox + 用户输入。Agent 不需要解析消息来源。

#### canUseTool 如何统一前台/后台审批？

- **前台（当前 REPL 项目）**: `canUseTool` 直接在终端弹窗 → 用户即时响应
- **后台（非当前项目）**: `canUseTool` 将审批请求入队 → 用户切到该项目时展示；状态栏提示例如 `[ncp] 等待审批 · Bash`

---

## 12. API 规范：唯一 MCP Tool

### 12.1 `send_message`

**描述**: 向其他项目发送消息。消息写入 mailbox 后立即返回，不等待回复。

**参数**:

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `to` | string | 是 | 收件人标识（project_id） |
| `subject` | string | 是 | 消息主题（简短描述） |
| `body` | string | 是 | 消息正文（完整内容） |

**返回值**:

```json
{
  "status": "sent",
  "msg_id": "m_20260525_001",
  "to": "ncp"
}
```

| 字段 | 类型 | 描述 |
|------|------|------|
| `status` | string | `"sent"` 或 `"error"` |
| `msg_id` | string | 消息唯一标识，用于 mailbox 关联回复 |
| `to` | string | 收件人 project_id（回显） |

**行为契约**:

1. **投递即忘**: 调用后立即返回，不阻塞等待对方处理。Agent 应理解为"已送达"，而非"已回复"。
2. **持久化**: 每次调用在 mailbox 中创建一条 `status=pending` 的消息记录。收件人下次获得 prompt 时自动注入。
3. **死信处理**: 如果目标 project_id 不存在，返回 `{"status": "error", "message": "项目 'xxx' 不存在"}`。
4. **无递归防护**: 异步模型不存在递归调用问题，不再需要 `_call_stack`。

### 12.2 示例

```
// acp Agent 调用:
send_message(to="ncp", subject="同步协议变更", body="Token 字段从 string 改为 TokenStruct")

// sextant 写入 mailbox，立即返回:
{
  "status": "sent",
  "msg_id": "m_20260525_001",
  "to": "ncp"
}

// acp 继续工作，不阻塞
// ncp 的下一个 prompt 会自动包含此消息
```

---

## 13. 会话管理

### 13.1 会话创建

```python
# session.py 伪代码
for project in config.projects:
    client = ClaudeSDKClient(
        options=ClaudeAgentOptions(
            cwd=project.directory,
            mcp_servers={"sextant": sdk_mcp_server},  # 进程内
            permission_mode="bypassPermissions",
            setting_sources=["project"],  # 加载 CLAUDE.md
            continue_conversation=True,   # 恢复最近会话
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": (
                    f"你的项目是 {project_id}。\n"
                    f"可以通过 send_message(to, subject, body) 向以下项目发消息：{other_projects}。\n"
                    f"发送消息后立即返回，对方会在下次处理时收到。\n"
                    f"收到的消息会自然出现在对话中，不需要查收件箱。"
                )
            }
        )
    )
    await client.__aenter__()
    sessions[project_id] = client
```

### 13.2 会话恢复

`continue_conversation=True` 时，CC SDK 在 `cwd` 下查找最近的会话文件并自动恢复。这意味着：

- sextant 重启后，所有 Agent 的对话历史完整保留
- Agent 知道"sextant 重启前正在进行的工作"
- 不需要 sextant 自己管理会话持久化（CC SDK 负责）

### 13.3 项目配置 (sextant.yaml)

```yaml
projects:
  - id: acp
    directory: /Users/zp/Projects/acp
    allowed_tools: [Read, Write, Edit, Bash]  # 可选，初期可为空
  - id: ncp
    directory: /Users/zp/Projects/ncp
  - id: xcp
    directory: /Users/zp/Projects/xcp
```

`project_id` 可从 `directory` 自动推导（`basename`），但手动指定提供了一致性保证。

---

## 14. 并发与消息流控制

### 14.1 串行保证

**原则 P2** 要求全局串行。sextant 通过以下方式保证：

1. 单线程事件循环
2. 只有一个 Agent 处于"活跃"状态（用户当前 REPL 项目）
3. Agent 间通信通过 mailbox 异步解耦——不需要并发处理
4. 用户切换项目用 `Ctrl+C`，每次只有一个 Agent 在处理 prompt

### 14.2 Mailbox 轮询（替代递归防护）

旧模型依赖 `_call_stack` 防止 A→B→A 的递归死锁。新模型中：

```
send_message 不再阻塞 → 不存在"A 等 B，B 又调 A"的死锁场景

Agent 的每次 prompt 由 mailbox 拼装：
  prompt = [mailbox 待处理消息] + [用户输入]
  
Agent 处理完 prompt 后：
  - 如果调了 send_message → 写入对方 mailbox
  - 输出文本 → 自动写回相关消息的发送方 mailbox
```

**核心变化**：从一个"同步调用树"变成"消息驱动的状态机"。Agent 的每次 turn 是独立的，不需要维护跨 turn 的调用栈。

### 14.3 后台 Agent 的触发时机

| 事件 | sextant 行为 |
|------|-------------|
| 用户输入 prompt（当前项目） | mailbox 待处理消息 + 用户输入 → 注入当前项目 Agent |
| 用户切换到某项目（Ctrl+C → `sextant chat X`） | 查询 X 的 mailbox → 有消息则注入 |
| 某项目 Agent 的输出写回 mailbox | 更新消息状态，不做额外动作（不自动触发 Agent） |

**设计意图**：Agent 只在获得 prompt 时处理消息。不需要轮询、不需要后台唤醒、不需要定时器。用户操作（输入/切项目）是唯一的触发源。

### 14.4 Mailbox 数据结构

```python
# 消息记录 (JSONL)
{
  "msg_id": "m_20260525_001",
  "timestamp": "2026-05-25T15:30:00+08:00",
  "from": "acp",
  "to": "ncp",
  "subject": "同步协议变更",
  "body": "...",
  "status": "replied",       # pending | replied | error
  "reply": "ncp 的完整输出",  # None when pending
  "reply_timestamp": "..."   # None when pending
}
```

---

## 15. 错误处理

### 15.1 错误场景及处理

| 场景 | 处理策略 |
|------|----------|
| `send_message` 目标 project_id 不存在 | 返回 `{"from": "system", "reply": "错误: 项目 'xxx' 不存在"}` |
| 目标 Agent 的 `query()` 抛出异常 | 捕获异常，返回 `{"reply": f"(错误: {e})"}` |
| 会话恢复失败 | 创建新会话（降级），日志警告 |
| CC SDK 子进程异常退出 | 尝试重启子进程，失败则将该 project 标记为不可用 |
| 用户 `Ctrl+C` 中断 `canUseTool` 审批 | 返回拒绝（`PermissionResultDeny`），不破坏调用链 |
| mailbox 写入失败 | 日志错误，不阻塞主流程（消息路由优先于持久化） |

### 15.2 降级策略

```
sextant 的设计目标：Agent 间消息传递不能丢。
持久化（mailbox）是辅助功能，不应该成为瓶颈。

优先级：消息路由 > 持久化 > 日志
```

---

## 16. 开发进度

### 16.1 Phase 1：单 session + REPL ✅

**完成日期**: 2026-05-24  
**Commit**: `c6aaebf`

交付：
- `session.py`：`ClaudeSDKClient` 生命周期管理
- `chat.py`：REPL 交互循环（输入 → query → 流式输出）
- `cli.py`：`sextant chat <project>` 入口
- Ctrl+C 退出方案：`signal handler + os._exit(0)` 绕过 `input()` 的非 daemon 线程卡死问题

关键踩坑：
- `PermissionMode` / `SettingSource` 是 `Literal` 非枚举
- `query()` 是 async 方法
- `StreamEvent` 在 DeepSeek 后端下**不触发**
- SDK 不自动读取 settings.json 的 `env`

### 16.2 Phase 2：多 Agent + send_message ✅

**完成日期**: 2026-05-24  
**Commit**: `ad07c0e`

交付：
- `SessionManager`：管理多个 `ClaudeSDKClient`，生命周期统一
- `send_message.py`：唯一 MCP tool（`@tool` 装饰器），进程内 SDK server
- 同步路由：`route_message()` → 注入目标 → 收集文本输出 → 返回
- `_call_stack` 递归防护：`to in _call_stack` 时直接返回
- System prompt 自动注入项目列表

E2E 验证通过：acp → send_message(to="ncp") → ncp 回复 → acp 收到。

### 16.3 Phase 3：__user__ 真人交互 ✅

**完成日期**: 2026-05-24  
**Commit**: `3f09c63`（⚠️ 未 push，GitHub 超时）

交付：
- `_prompt_user()`：显示提示 → `asyncio.wait()` race `input()` vs `cancel_event` → 返回回复
- `cancel_event`：Ctrl+C 跳过 `__user__` 提问，返回 "(用户未回复)"
- `chat.py` 信号处理器改造：`mgr_ref` 可变容器传递 manager 引用

E2E 验证通过：acp → send_message(to="__user__") → mock 用户输入 → acp 继续。

### 16.4 Phase 4：TUI 思考可见化 ✅

详见 [第 17.4 节](#174-phase-4tui-思考可见化--打磨)。Phase 4 全部 6 个 task 已完成。

### 16.5 Phase 5：权限审批 + 状态栏 + 会话恢复 ✅

**完成日期**: 2026-05-24

交付：
- `canUseTool` 回调替代废弃的 `permission_prompt_tool_name`
- `send_message` 硬编码放行，不触发审批
- `AskUserQuestion` 格式化选项展示
- 状态栏 `[acp] acceptEdits · deepseek-v4-pro · 3m12s`
- `/perm` 和 `/model` 运行时命令
- `--resume` 会话恢复

### 16.6 Phase 6：Mailbox 驱动架构重构（待开发）

**目标**: 将 send_message 从同步阻塞改为 mailbox 驱动异步模型。

**变更范围**:

| 模块 | 变更 |
|------|------|
| `send_message.py` | 去掉 `route_message` 调用；只写 mailbox + 返回 ack |
| `session.py` | 去掉 `route_message`、`_call_stack`、`_prompt_user`（迁移到 canUseTool）；新增 `_build_prompt_with_mailbox()` |
| `mailbox.py` | 扩展：`record_reply()`、`get_pending()`、`get_replies_for()` |
| `chat.py` | prompt 组装改为 `mailbox.get_pending() + user_input`；输出自动回写 mailbox |
| system prompt | 去掉"请用 send_message 回复"指令；去掉 `__user__` 相关内容 |

**开发顺序**:
1. Mailbox 扩展（`record_reply`、`get_pending`）— 1h
2. `send_message.py` 改为投递即忘 — 0.5h
3. `session.py` 去掉 `route_message`/`_call_stack`，新增 prompt 组装 — 1.5h
4. `chat.py` prompt 组装 + 输出回写 — 1h
5. System prompt 精简 — 0.5h
6. E2E 测试适配 + 三项目验证 — 1h
7. 清理旧代码（`route_message`、`_prompt_user` 中 `__user__` 相关）— 0.5h

**预估**: 6 小时

---

## 17. 实现计划

### 17.1 阶段划分

**Phase 1：单 session + REPL** ✅
Commits: `c6aaebf`。详见 [第 16.1 节](#161-phase-1单-session--repl-)。

**Phase 2：同步 send_message** ✅
Commits: `ad07c0e`。详见 [第 16.2 节](#162-phase-2多-agent--send_message-)。

**Phase 3：__user__ 特殊收件人** ✅
Commits: `3f09c63`（⚠️ 本地未 push）。详见 [第 16.3 节](#163-phase-3__user__-真人交互-)。

**Phase 6：Mailbox 驱动架构重构**（预估：6 小时）

详见 [第 16.6 节](#166-phase-6mailbox-驱动架构重构待开发)。

### 17.2 技术验证点（已全部验证）

在进入编码前需先验证：

1. **CC Agent SDK 是否在当前 Python 环境中可用**？
2. **`create_sdk_mcp_server()` + `tool` 装饰器是否能注册到 CC 会话中**？
3. **`query()` + `receive_response()` 是否能稳定接收流式输出**？
4. **`continue_conversation=True` 的会话文件路径和格式**？

全部已验证通过（Phase 1-3 开发中确认）。

### 17.3 新增踩坑记录（Phase 2-3）

| 假设 | 实际 |
|------|------|
| `get_server_info()` 返回对象（`.session_id`） | 返回 dict，无 `session_id` 字段 |
| `ThreadPoolExecutor` 线程随 asyncio 退出 | `input()` 的非 daemon 线程会导致进程挂死 → 需 `os._exit(0)` |
| 进程内 MCP server 的 tool handler 可同步调用 | handler 是 async，可 await 其他 client 的 query() |
| `asyncio.Event` 在 signal handler 中设置安全 | ✅ 安全，`loop.add_signal_handler` 将其作为回调调度 |

---

### 17.4 Phase 4：TUI 思考可见化 + 打磨

#### 17.4.1 问题陈述

**当前 TUI 是"黑盒"**：用户输入 prompt 后，看到的是：

```
sextant · acp
> 帮我改 proto 协议，通知 ncp

[空白等待 30+ 秒...]
[acp] 已完成修改。
```

这 30 秒里发生了什么？agent 在思考？在调工具？在等 ncp 回复？还是卡死了？用户只能干等。

**核心需求**：让 agent 的每一步思考/操作都**实时可见**，像 CC 原生 TUI 那样。

#### 17.4.2 目标体验

```
sextant · acp
> 帮我改 proto 协议，通知 ncp
  💭 用户要我改 proto 协议并通知 ncp。先看当前协议定义...         ← ThinkingBlock
  ⚙ Reading /proto/auth.proto                       [0.3s]
  💭 Token 需要改成 TokenStruct。确认改动范围...                ← ThinkingBlock
  ⚙ Editing /proto/auth.proto                        [1.2s]
  💭 改完了，现在通知 ncp。                                      ← ThinkingBlock
  📬 → ncp: 同步协议变更                              [等待中...]
  📬  ncp 已回复: 修改完成                            [3.8s]
  💭 ncp 确认修改完成，向用户汇报。                               ← ThinkingBlock
[acp] proto 协议已更新，ncp 已同步完成 ✓
  ── $0.0234 · end_turn ──
```

**关键改进**：
- `💭` 前缀显示推理过程（缩进、灰色）
- `⚙` 工具调用显示耗时
- `📬` agent 间通信显示状态 + 耗时
- 用户不再"盯空白屏幕"

#### 17.4.3 技术方案

**SDK 类型支持**（已查证）：

```python
# AssistantMessage.content 中的 block 类型：
TextBlock          # 普通文本
ThinkingBlock      # 推理过程 (thinking + signature 字段)
ToolUseBlock       # 工具调用
ToolResultBlock    # 工具结果
ServerToolUseBlock # MCP tool 调用
ServerToolResultBlock  # MCP tool 结果
```

**实现步骤**：

**Task P4-1：`ThinkingBlock` 渲染**（2h）

修改 `chat.py` 的 `_display_message`：

```python
def _display_message(msg):
    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, ThinkingBlock):
                # 灰色缩进显示推理过程
                for line in block.thinking.strip().split("\n"):
                    print(f"\x1b[90m  💭 {line}\x1b[0m", flush=True)
            elif isinstance(block, TextBlock):
                print(block.text, end="", flush=True)
            # ... 其他 block 处理
```

⚠️ `ThinkingBlock` 只在**推理模型**（如 Claude Opus extended thinking、DeepSeek-R1）下出现。普通模型跳过此渲染。

**Task P4-2：工具调用耗时显示**（1.5h）

当前 `_tool_description` 只显示工具名。改为带时间戳：

```python
_tool_starts: dict[str, float] = {}  # tool_use_id → start_time

# 在 ToolUseBlock 时记录起始时间
# 在 ToolResultBlock 时计算耗时显示
# 显示格式: ⚙ Reading /proto/auth.proto  [0.3s] ✓
```

**Task P4-3：Agent 间通信状态**（1h）

`send_message` 的 `route_message()` 中：
- 开始注入时：`print(f"  📬 → {to}: {subject}  [等待中...]", flush=True)`
- 收到回复时：`print(f"  📬  {to} 已回复  [{elapsed:.1f}s]", flush=True)`

同时在 `_display_message` 中对 `ServerToolUseBlock(name="send_message")` 做特殊渲染。

**Task P4-4：mailbox 持久化**（1.5h）

新建 `mailbox.py`：
- `save_message(from_id, to, subject, body, reply)` → 写 JSON 到 `~/.sextant/mailbox/{project_id}/`
- 每条消息包含：timestamp, from_id, to, subject, body, reply, elapsed_ms
- 文件按日期分片：`YYYY-MM-DD.jsonl`

新增 CLI 命令：`sextant mailbox <project>` — 展示历史消息。

**Task P4-5：错误处理增强**（1h）

- `route_message`: 目标 agent 异常时，不做崩溃处理，返回结构化错误
- `SessionManager.__aenter__`: 某个 agent 启动失败不影响其他 agent
- Agent 崩溃检测：`receive_response()` 异常时标记 agent 为 `unavailable`，`send_message` 返回友好错误
- 增加 `sextant status` 命令：显示各 agent 状态（running/unavailable/crashed）

**Task P4-6：完整 E2E 场景测试**（1h）

创建三项目测试环境：
```yaml
projects:
  - id: acp    # 协议仓库
  - id: ncp    # 服务端（Python）
  - id: xcp    # 客户端（Rust）
```

测试场景：
1. acp → ncp → 用户切到 ncp → 处理消息 → 问用户问题（canUseTool）→ 输出回写 acp mailbox
2. acp → ncp + acp → xcp → 用户切到各项目查看 → 汇总回复
3. 三项目消息往返：A→B→C→A 场景，验证 mailbox 正确关联回复

#### 17.4.4 Phase 4 优先级

| 优先级 | 任务 | 理由 |
|--------|------|------|
| 🔴 P0 | P4-1 ThinkingBlock 渲染 | ZP 核心痛点：看不到思考过程 |
| 🔴 P0 | P4-2 工具耗时 | 判断 agent 是否卡死的直接信号 |
| 🟡 P1 | P4-3 Agent 通信状态 | send_message 等待时最焦虑 |
| 🟢 P2 | P4-4 Mailbox | 辅助功能，不影响交互体验 |
| 🟢 P2 | P4-5 错误处理 | 早期阶段 agent crash 概率低 |
| 🟢 P2 | P4-6 E2E 测试 | 需要三项目环境，先做功能再做测试 |

**建议开发顺序**：P4-1 → P4-2 → P4-3 →（此时 ZP 可以开始实际使用）→ P4-4/5/6

---

## 18. 开放问题与风险

| # | 问题 | 风险等级 | 状态 | 结论 |
|---|------|----------|------|------|
| Q1 | `bypassPermissions` 下 Agent 是否执行危险操作？ | 中 | ⚠️ 部分缓解 | 进程在本地运行，不暴露网络。初期建议限制 `allowed_tools` |
| Q2 | `query()` 调用期间 SDK 内部是否有并发保护？ | 低 | ✅ 已验证 | 串行模型，不存在并发访问 |
| Q3 | 3-4 个 CC Agent 子进程的内存开销？ | 低 | ✅ 已验证 | 实测 2 agent ≈ 400MB，符合预期 |
| Q4 | `continue_conversation=True` 的持久化路径？ | 中 | ✅ 已验证 | SDK 自动管理，重启后恢复成功 |
| Q5 | Mailbox JSONL 文件在并发写入时的一致性？ | 低 | ⚠️ 待验证 | 单线程模型天然串行；同一文件多项目并发写入需确认 |
| Q6 | Agent 会不会填错 `to` 参数？ | 低 | ✅ 已验证 | system_prompt 注入 + 项目列表，E2E 测试中从未填错 |
| Q7 | 后台 Agent 的 canUseTool 审批请求如何排队？ | 中 | ⚠️ 待设计 | Phase 6 需设计：是入队到 mailbox 还是直接拒绝？ |

**Phase 6 新增风险**：

| # | 问题 | 风险等级 | 缓解措施 |
|---|------|----------|----------|
| Q8 | Agent 异步通信后用户忘记切回查看回复 | 中 | 状态栏提示"N 条新回复"；`sextant status` 显示各项目待处理消息数 |
| Q9 | 旧同步模型的 Agent 会话与新 mailbox 模型的兼容性 | 低 | 改 system prompt 即可；Agent 行为由 prompt 驱动，不依赖旧语义 |
| Q10 | send_message 返回值从 `{reply}` 变成 `{status:sent}` 后 Agent 行为变化 | 中 | Agent 由 system prompt 告知"发送即完成，不要等回复"；E2E 测试验证

---

## 19. 附录

### 19.1 术语表

| 术语 | 定义 |
|------|------|
| **sextant** | 本产品名称，多项目 Agent 协同工具 |
| **CC (Claude Code)** | Anthropic 的编码 Agent，有 CLI 和 SDK 两种形态 |
| **CC Agent SDK** | `claude_agent_sdk` Python 包，可编程管理 CC 会话 |
| **project_id** | 项目标识，等同于工作目录的 basename |
| **session** | 一个 CC Agent 的持续对话上下文 |
| **MCP (Model Context Protocol)** | Agent tool 的协议标准 |
| **MCP tool** | 注册到 Agent 的可调用工具 |
| **REPL** | Read-Eval-Print Loop，交互式命令行界面 |
| **mailbox** | 消息持久化存储（JSONL 文件），sextant 的唯一真相源。所有 Agent 间消息 + 回复全部流经 mailbox |
| **send_message** | 唯一的 MCP tool，用于 Agent 间异步消息传递。写入 mailbox 后立即返回，不阻塞 |
| **canUseTool** | CC SDK 的标准用户交互回调。sextant 用它统一处理工具审批 + AskUserQuestion |

### 19.2 相关文档

| 文档 | 路径 | 描述 |
|------|------|------|
| 实现计划 | `.aireports/impl_plan.md` | 总体项目规划 |
| 生态调研 | `.aireports/20260524_ecosystem_research.md` | CC MCP serve & claude-a2a 调研 |
| 混合架构 | `.aireports/20260524_hybrid_architecture.md` | 混合架构方案设计 |
| 代码设计 | `.aireports/20260524_code_design.md` | 早期纯 MCP server 设计（已过时） |
| SDK 限制 | `.aireports/20260524_sdk_limitations.md` | MCP SDK notification 限制（已绕过） |
| 最终设计 v4 | `.aireports/20260524_final_design_v4.md` | 最终架构设计（本文档的详细技术版） |

### 19.3 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-05-24 | 初始 PRD，基于 final_design_v4.md |
| 1.1 | 2026-05-24 | 新增第11章「端到端协作场景」；章节号全部后移 |
| 1.2 | 2026-05-24 | Phase 1-3 完成；新增第16章「开发进度」；Phase 4 详细规格（TUI 思考可见化 + 6 个 task）；开放问题更新（Q2-4,Q6 ✅，Q5,Q7 ⚠️，新增 Q8-9）；SDK 踩坑补充 |
| 1.3 | 2026-05-25 | **重大架构变更**：消息模型从同步阻塞改为 mailbox 驱动异步。P4 从"send_message 是同步的"改为"投递即忘"。去掉 `__user__` 特殊收件人，用户交互全部通过 `canUseTool`。去掉 `_call_stack` / 递归防护 / `route_message`。重写第5、8、10、11、12、14节；新增 Phase 6 实现计划 |

### 19.4 SDK 参考文档

| 来源 | 链接 | 内容 |
|------|------|------|
| Anthropic 官方 | https://docs.anthropic.com/en/docs/claude-code/sdk | Agent SDK 总览：能力列表、与 API SDK 的对比、Changelog |
| Anthropic 官方 | https://docs.anthropic.com/en/docs/claude-code/sdk/sdk-python | Python SDK API 参考：`ClaudeSDKClient`、`query()`、`@tool`、`create_sdk_mcp_server()` 完整签名 |
| GitHub | https://github.com/anthropics/claude-agent-sdk-python | 官方仓库：源码（`client.py`、`query.py`、`types.py`）、README |
| GitHub | https://github.com/anthropics/claude-agent-sdk-python/blob/main/examples/hooks.py | hooks 示例：`UserPromptSubmit`、`PreToolUse`、`PostToolUse` 等用法 |
| GitHub Issue | https://github.com/anthropics/claude-code/issues/20833 | `UserPromptSubmit` hook 的 `hookSpecificOutput` 字段文档不准确问题 |
| 社区教程 | https://www.augmentcode.com/guides/claude-agent-sdk-python | Claude Agent SDK 实战教程：`query()` vs `ClaudeSDKClient`、多 agent 并发 |

#### 实测踩坑记录

以下是在 Phase 1 编码过程中发现与文档/直觉不符的点：

| 假设 | 实际 |
|------|------|
| `PermissionMode` 是枚举类，用 `PermissionMode.bypassPermissions` | 是 `typing.Literal`，直接传字符串 `"bypassPermissions"` |
| `client.query()` 是同步方法 | **异步方法**，必须 `await client.query(prompt)` |
| `StreamEvent` 是主要流式载体 | **不触发**（DeepSeek 后端下），`AssistantMessage` + `TextBlock` 才是流式输出 |
| SDK 自动读取 `~/.claude/settings.json` 中的 `env` | **不会**，需要手动 `json.load` 后传给 `ClaudeAgentOptions(env=...)` |
| `SettingSource` 是枚举类 | 是 `Literal`，直接传字符串 `"project"` |
