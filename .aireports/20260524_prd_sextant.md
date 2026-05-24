# sextant — 产品需求文档 (PRD)

> **版本**: 1.2  
> **日期**: 2026-05-24  
> **状态**: Phase 1-3 已完成，Phase 4 进行中  
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

核心思路：用 Claude Code Agent SDK 管理所有 CC 会话，通过一个名为 `send_message` 的 MCP tool 实现 Agent 间的同步消息传递。用户通过 `sextant chat <project>` REPL 与任一项目的 Agent 交互，sextant 在后台处理 Agent 间的消息路由，且 Agent 不需要区分消息来自真人用户还是其他 Agent。

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
- 提供 `send_message` 工具，让 Agent 之间可以相互发送消息
- 当 Agent 需要用户决策时，在 REPL 中阻塞等待用户回答
- 持久化消息记录（mailbox），支持审计回溯

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
| P3 | **CC 不分人来人往** | 子项目 CC 不区分消息来源（用户 vs Agent），都视为"有人在跟我说话" | 简化 Agent prompt，统一交互模型 |
| P4 | **send_message 是同步的** | 发送消息后阻塞等待对方回复，回复作为 tool 返回值 | 符合"只有一个脑袋"的串行开发模式 |
| P5 | **`__user__` 是特殊收件人** | Agent 向 `__user__` 发消息时，sextant 在 REPL 中阻塞等待真人输入 | 用户成为消息路由图中的一个特殊节点 |

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
- FR2.3: Agent 调用 `send_message(to="__user__")` 时，REPL 切换为问答模式，阻塞等待用户输入
- FR2.4: `Ctrl+C` 退出当前 chat，会话保持，下次 resume 继续
- FR2.5: 支持 `/` 开头的内置命令（如 `/help`，未来可扩展）

---

### 6.3 FR3：Agent 间同步消息传递

**描述**: Agent 通过 `send_message` MCP tool 向其他 Agent 发送消息并同步等待回复。

**详细要求**:
- FR3.1: 参数 `to`（收件人 project_id）、`subject`（标题）、`body`（消息正文）
- FR3.2: 调用后系统阻塞等待目标 Agent 的完整回复，回复作为 tool 返回值
- FR3.3: 所有消息持久化到 mailbox（文件系统）供审计
- FR3.4: 目标 Agent 的回复是其在处理消息期间产生的全部文本输出

**约束**:
- FR3-C1: 只有 `send_message` 一个 MCP tool，没有 `check_inbox`、`list_projects` 等
- FR3-C2: 目标 Agent 的 prompt 中自然注入消息内容 + 回复指示，不需要 Agent 主动轮询

---

### 6.4 FR4：用户作为特殊收件人

**描述**: Agent 可以向 `__user__` 发送消息以获取真人决策。

**详细要求**:
- FR4.1: `send_message(to="__user__")` 触发 REPL 阻塞等待
- FR4.2: 在 REPL 中展示发送者身份、问题内容
- FR4.3: 用户的文本回复作为 tool 返回值传回调用方 Agent
- FR4.4: 用户回复也写入 mailbox 持久化记录
- FR4.5: 用户可以用 `Ctrl+C` 跳过（返回 `(用户未回复)`）

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
- NFR2.2: `send_message` 同步等待不增加额外延迟（仅取决于目标 Agent 的处理时间）
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
│  │   MCP Tool（唯一）    │    │    消息路由（同步）        │   │
│  │                      │    │                           │   │
│  │   send_message       │◄───│  to="ncp"  → 注入 ncp     │   │
│  │   (进程内 SDK 调用)   │    │  to="__user__" → REPL阻塞  │   │
│  └──────────────────────┘    └──────────┬────────────────┘   │
│                                         │                    │
│  ┌──────────────────────┐    ┌──────────┴────────────────┐   │
│  │   Mailbox             │    │   Session Manager        │   │
│  │   (文件 inbox)        │    │                          │   │
│  │   持久化消息记录       │    │   acp: ClaudeSDKClient   │   │
│  └──────────────────────┘    │   ncp: ClaudeSDKClient   │   │
│                              │   xcp: ClaudeSDKClient   │   │
│                              └──────────┬───────────────┘   │
│                                         │                   │
│  ┌──────────────────────────────────────┴────────────────┐  │
│  │   REPL（sextant chat <project>）                      │  │
│  │   readline 输入 → query → 流式输出                     │  │
│  │   send_message(to="__user__") → 阻塞等待用户输入       │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 模块职责

| 模块 | 职责 | 关键技术 |
|------|------|----------|
| `config.py` | 解析 `sextant.yaml`，提供项目列表和路径 | PyYAML |
| `mailbox.py` | 消息持久化：写 JSON 文件，读历史消息 | 文件 I/O |
| `session.py` | 管理 ClaudeSDKClient 生命周期：创建、恢复、关闭 | CC Agent SDK |
| `send_message.py` | 唯一 MCP tool 实现 + 同步路由 + 递归防护 | CC SDK `create_sdk_mcp_server` |
| `chat.py` | REPL 交互：输入、流式输出、`__user__` 阻塞等待 | asyncio + readline |
| `cli.py` | CLI 入口：`sextant start`、`sextant chat` | argparse |

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

### 9.2 Agent 询问用户

当 Agent 调用 `send_message(to="__user__", subject="确认变更", body="是要同步第2个还是第3个变更？")`：

```
[acp] 我需要确认一下……
──────────────────────────────────────────
🤔 acp 想知道：
确认变更

是要同步第2个还是第3个变更？
──────────────────────────────────────────
> 第2个

[acp 收到回复] 好的，只同步第2个变更
```

用户输入被返回给 `send_message` 的调用方（acp Agent），Agent 继续处理。

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

## 10. 消息路由模型

### 10.1 路由规则

| `to` 参数 | sextant 行为 |
|-----------|-------------|
| `"ncp"`（普通 project_id） | 注入目标 CC 会话 → 阻塞等待 → 返回目标 Agent 的全部文本输出 |
| `"__user__"`（特殊收件人） | REPL 展示问题 → 阻塞等待用户输入 → 返回用户回复文本 |
| 等于 `_call_stack[-1]` | 检测到递归回复 → 直接返回，不注入（递归防护） |
| 其他 project_id | 同第一条 |

### 10.2 完整消息流

```
Step 1: 用户对 acp 输入"通知 ncp 修改 XXX"
        → acp 调用 send_message(to="ncp", subject="修改 XXX", body="...")

Step 2: sextant 处理 send_message
        → 写 mailbox 记录: acp → ncp
        → _call_stack.append("acp")
        → ncp_client.query("📬 来自 acp 的消息：修改 XXX\n\n请处理。\n处理完调用 send_message(to='acp', ...) 回复。")

Step 3: ncp 处理消息
        → ncp 分析后不确定，调用 send_message(to="acp", subject="Re: 修改 XXX", body="是要改 XXX-1 吗？")
        
Step 4: sextant 检测到 _call_stack[-1] == "acp"
        → 递归防护：直接返回 {"reply": "是要改 XXX-1 吗？"} 给 ncp
        → ncp 的 send_message 调用完成

Step 5: ncp 继续处理，输出"已修改 XXX-1"
        → ncp 的 query 完成，receive_response() 返回完整的文本输出
        
Step 6: sextant 将 ncp 的输出作为 send_message 返回值
        → _call_stack.pop()
        → return {"from": "ncp", "reply": "已修改 XXX-1"}

Step 7: acp 收到 return value，继续处理
        → 向用户汇报"ncp 已完成修改"
```

---

## 11. 端到端协作场景

> 以下场景完整演示三个 Agent（acp、ncp、xcp）在真实开发任务中的协作流程，覆盖消息同步、递归防护、`__user__` 介入等所有关键机制。

### 11.1 初始条件

```
项目：
  acp — 协议仓库（用户当前 REPL：sextant chat acp）
  ncp — 服务端仓库（Python，headless）
  xcp — 客户端仓库（Rust，headless）

每个 Agent 的 system prompt 注入：
  - 你的项目是 {project_id}
  - 其他项目：[acp, ncp, xcp]（除自己外）
  - 可以用 send_message(to="...", subject="...", body="...") 向其他项目发消息并等待回复
  - __user__ 是真人用户，需要判断时可以询问
  - 收到消息时内容直接可见，不需要查收件箱
  - 如果你连续两次无法从当前对话方获得有效回复，可以向 __user__ 发起升级询问
```

### 11.2 场景：协议变更跨项目同步

任务：用户修改了 proto 协议定义（Token 字段从 `string` 改为 `TokenStruct`），需要 ncp 和 xcp 同步修改并确认编译通过。

#### Step 1：用户发起

```
$ sextant chat acp

sextant · acp
> 我刚改了协议，Token 字段从 string 改成 TokenStruct{token:string, expiry:int64, issuer:string}。
> 通知 ncp 和 xcp 同步修改，确认编译通过后汇报。
```

用户**没有**显式说"通知 ncp"、"通知 xcp"。acp Agent 根据 prompt 中的项目列表和任务语义，自己判断出需要通知两个项目。

#### Step 2：acp → ncp（第一轮注入）

acp Agent 理解任务后，调用 `send_message`：

```
send_message(
  to="ncp",
  subject="同步协议变更：Token string → TokenStruct",
  body="协议定义已变更，/proto/auth.proto 中 Token 字段从 string 改为 TokenStruct{
      token:string, expiry:int64, issuer:string
  }。请修改服务端的序列化/反序列化代码，确认编译通过后回复。"
)
```

sextant 处理：写 mailbox，`_call_stack.append("acp")`，注入 ncp：

```
ncp_client.query(
  "📬 来自 acp 的消息：同步协议变更：Token string → TokenStruct\n\n"
  "协议定义已变更……\n\n"
  "请处理此消息。处理完毕后，"
  "调用 send_message(to='acp', subject='Re: 同步协议变更', body='你的完整回复')。"
)
```

#### Step 3：ncp 处理 + 内部疑问

ncp Agent 收到注入，开始分析：

```
收到来自 acp 的消息。他们改了 proto，我需要改 src/auth/ 下的序列化代码。
Token 字段从 string 改成 TokenStruct……

但是，src/auth/ 下有两个地方用了 Token：
  • token_serializer.py — 纯粹序列化/反序列化
  • auth_middleware.py — 序列化 + 业务逻辑，Token 被用作 map key

改 token_serializer.py 是明确的。
auth_middleware.py 里 Token 改成 TokenStruct 后，map 逻辑需要重写。
这次也需要一起改吗？
```

ncp 不确定范围，根据 prompt 指令回复 acp：

```
send_message(
  to="acp",
  subject="Re: 同步协议变更",
  body="token_serializer.py 改完了。但 auth_middleware.py 用 Token 做 map key，
      改成 TokenStruct 后 map 逻辑需要重写。这次也需要改吗？还是只改序列化层？"
)
```

#### Step 4：递归防护触发

sextant 检测到 `_call_stack[-1] == "acp"`（acp 正在等 ncp 的回复）。ncp 的 `send_message` 被**直接短路返回**：

```
→ {"reply": "token_serializer.py 改完了。但 auth_middleware.py……这次也需要改吗？", "from": "ncp"}
```

ncp Agent 收到返回值，不知道也不用知道这是"短路"还是"真的注入了 acp"。它的 `send_message` 调用正常完成。

同时 sextant 继续：`ncp_client.receive_response()` 返回 ncp 的全部文本输出 → `_call_stack.pop()` → acp 的 `send_message` 返回：

```
→ {"from": "ncp", "reply": "token_serializer.py 改完了。但 auth_middleware.py……这次也需要改吗？"}
```

#### Step 5：acp 触发第一次 `__user__` 介入

acp Agent 收到返回值：

```
ncp 说：token_serializer.py 改完了。但 auth_middleware.py 用 Token 做 map key，
改成 TokenStruct 后需要重写。这次也需要改吗？还是只改序列化层？
```

acp Agent 分析：

```
ncp 在问我一个设计决策问题：auth_middleware 的 map 逻辑要不要改。
这个问题影响业务逻辑，不是简单的技术判断。我需要问用户。
```

acp Agent 调用：

```
send_message(
  to="__user__",
  subject="ncp 的疑问：auth_middleware 改不改？",
  body="ncp 已改完 token_serializer.py，但发现 auth_middleware.py 用了 Token 做 map key，
      改成 TokenStruct 后 map 逻辑需要重写。\n\n"
      "选项：\n"
      "1. 这次只改序列化层\n"
      "2. 序列化 + map 逻辑一起改\n"
      "3. 暂不改 auth_middleware，单独排查"
)
```

sextant 检测 `to == "__user__"` → 进入 REPL 阻塞模式。

#### Step 6：用户回复

```
──────────────────────────────────────────
🤔 acp 想知道：
ncp 的疑问：auth_middleware 改不改？

ncp 已改完 token_serializer.py，但发现 auth_middleware.py 用了 Token 做 map key，
改成 TokenStruct 后 map 逻辑需要重写。

选项：
1. 这次只改序列化层
2. 序列化 + map 逻辑一起改
3. 暂不改 auth_middleware，单独排查
──────────────────────────────────────────
> 2，一起改了，别留技术债
```

用户输入 `"2，一起改了，别留技术债"` 被返回给 acp 的 `send_message(to="__user__")` 调用。mailbox 记录：`__user__ → acp`。

#### Step 7：acp 将用户决策转发给 ncp

acp Agent 收到用户回复后继续处理：

```
用户说一起改。我需要把这个决定传给 ncp。
```

```
send_message(
  to="ncp",
  subject="Re: 同步协议变更",
  body="确认：auth_middleware.py 的 map 逻辑也一起改。不要留技术债，完整迁移到 TokenStruct。"
)
```

ncp 处理：

```
"明白了，一起改。正在修改 auth_middleware.py……"
"已修改。编译中……"
"编译通过，所有测试通过。"
```

sextant 返回给 acp：

```
→ {"reply": "auth_middleware.py 已修改，编译通过，所有测试通过。", "from": "ncp"}
```

#### Step 8：acp → xcp（第二轮注入）

acp Agent 汇总：

```
ncp 搞定了。现在轮到 xcp。
```

```
send_message(
  to="xcp",
  subject="同步协议变更：Token string → TokenStruct",
  body="Token 字段从 string 改为 TokenStruct{token,expiry,issuer}。
      请修改 Rust 客户端的反序列化代码。ncp 端已完成。"
)
```

xcp Agent 处理：

```
"收到。让我看看客户端的 proto 生成代码……"
"客户端的 token.rs 和 config.rs 用了 Token 字段。"
"正在修改……"

// xcp 内部也遇到疑问
send_message(
  to="acp",
  subject="Re: 同步协议变更",
  body="token.rs 改完了。但 config.rs 中 Token 被用作连接池的 key，
      改成 TokenStruct 后 Hash trait 需要重新 derive。加 #[derive(Hash)] 吗？
      还是改用 token 字符串做 key？"
)
```

递归防护再次短路（`_call_stack[-1] == "acp"`），直接返回给 acp。

#### Step 9：acp 第二次触发 `__user__` 介入

acp Agent：

```
xcp 又有一个 Rust 设计问题。TokenStruct 的 Hash trait……

我对 Rust 的最佳实践不确定。再问用户。
```

```
send_message(
  to="__user__",
  subject="xcp 的疑问：TokenStruct 的 Hash trait",
  body="xcp 在 Rust 客户端发现：Token 改成 TokenStruct 后，被用作连接池 key 的地方
      需要 Hash trait。\n\n选项：\n1. 给 TokenStruct 加 #[derive(Hash)]\n2. 改用 token 字符串做 key"
)
```

```
──────────────────────────────────────────
🤔 acp 想知道：
xcp 的疑问：TokenStruct 的 Hash trait

xcp 在 Rust 客户端发现：Token 改成 TokenStruct 后，被用作连接池 key 的地方
需要 Hash trait。

选项：
1. 给 TokenStruct 加 #[derive(Hash)]
2. 改用 token 字符串做 key
──────────────────────────────────────────
> 1
```

#### Step 10：acp 将决策转发 xcp

```
send_message(
  to="xcp",
  subject="Re: 同步协议变更",
  body="用 #[derive(Hash)]。"
)
```

xcp 处理：

```
"收到。已修改。编译中……"
"编译通过，测试通过。"
```

#### Step 11：acp 汇总汇报

acp Agent 收集完所有回复后，向用户汇报：

```
好的，协议变更同步完成。汇总如下：

📊 Token string → TokenStruct 跨项目同步
  ✓ ncp（服务端）
    • token_serializer.py — 已修改
    • auth_middleware.py — 已修改（含 map 逻辑重写）
    • 编译通过，所有测试通过
  ✓ xcp（客户端）
    • token.rs — 已修改
    • config.rs — 已修改（新增 #[derive(Hash)]）
    • 编译通过，所有测试通过

两次设计决策已由用户确认：
  1. auth_middleware 一并修改（选2：不留技术债）
  2. TokenStruct 使用 #[derive(Hash)]（选1：标准做法）
```

### 11.3 场景关键洞察

#### `__user__` 何时被调用？

**只有一种情况**：用户当前 REPL 中的 Agent（本例中的 acp）收到其他 Agent 的疑问，且**自己无法判断**时，调用 `send_message(to="__user__")`。

#### 为什么 ncp/xcp 不直接调 `__user__`？

因为它们的每条注入消息都以 `"请处理此消息。处理完调用 send_message(to='acp', ...) 回复。"` 结尾——回复目标固定在 `acp`。ncp/xcp 没有动机绕过 acp 直接找 `__user__`。

#### 如果 ncp 真的绕过 acp 调了 `__user__`？

这不是 bug，是**合理的升级行为**。system prompt 中已加入升级约束：

> 如果你连续两次无法从当前对话方获得有效回复，可以向 __user__ 发起升级询问。

这个约束提供了"至少试两次"的门槛，防止 Agent 过早绕过中间层直接找用户。

#### 是否违反 P3（Agent 不区分人来人往）？

**不违反。** P3 针对的是 Agent **接收**消息时的行为——Agent 不区分消息来源是真人还是其他 Agent。但 Agent 在**发送**消息时，知道 `__user__` 是一个特殊的收件人选项（和知道"ncp"、"xcp"一样）。这是"知道有谁可以发"而非"分得清谁在发"。

类比：你打电话时知道老板的号码和同事的号码 —— 这是"知道目标"。但接电话时不看来电显示分不清是谁 —— 这是"不区分来源"。两者不矛盾。

---

## 12. API 规范：唯一 MCP Tool

### 12.1 `send_message`

**描述**: 向其他项目或用户发送消息，并同步等待回复。

**参数**:

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `to` | string | 是 | 收件人标识。有效值：`__user__` 或任意 project_id |
| `subject` | string | 是 | 消息主题（简短描述） |
| `body` | string | 是 | 消息正文（完整内容） |

**返回值**:

```json
{
  "from": "ncp",
  "reply": "已修改 XXX-1，编译通过，12/12 测试通过 ✓"
}
```

| 字段 | 类型 | 描述 |
|------|------|------|
| `from` | string | 实际回复方的 project_id（或 `__user__`） |
| `reply` | string | 回复的完整文本内容 |

**行为契约**:

1. **同步阻塞**: 调用此 tool 后，CC Agent 会阻塞直到收到回复。回复作为 tool 的返回值。
2. **持久化**: 每次调用都会在 mailbox 中创建一条消息记录。
3. **死信处理**: 如果目标 project_id 不存在或目标 Agent 出错，返回错误信息（不抛异常）。
4. **递归防护**: 如果调用方正在等待目标方的回复，目标方反调 `send_message` 给调用方时，直接返回而不注入。

### 12.2 示例

```
// acp Agent 调用:
send_message(to="ncp", subject="同步协议变更", body="Token 字段从 string 改为 TokenStruct")

// sextant 注入 ncp → ncp 处理 → ncp 输出文本

// 返回值:
{
  "from": "ncp",
  "reply": "已更新 auth.py 和 token.py，新增 TokenStruct 类型。\n所有测试通过。"
}
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
                    f"可以通过 send_message 向以下项目发消息：{other_projects}。\n"
                    f"向 __user__ 发消息可以询问用户。\n"
                    f"收到消息时会直接显示在对话中。"
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

## 14. 并发与递归控制

### 14.1 串行保证

**原则 P2** 要求全局串行。sextant 通过以下方式保证：

1. 单线程事件循环
2. `send_message` 内部 `await target_client.query()` → `await receive_response()` —— 整个流程是阻塞的
3. 用户切换项目前必须 `Ctrl+C` 退出当前 chat → 此时没有活跃的 `send_message` 调用
4. 没有后台任务、没有 `asyncio.create_task`、没有消息队列

### 14.2 递归防护

当 ncp 正在处理 acp 的消息时，ncp 可能调用 `send_message(to="acp")` 作为回复。但 acp 此时正在阻塞等待 ncp 的 `send_message` 返回——如果再注入 acp，会形成死锁。

**解决方案**：`_call_stack` 机制。

```python
_call_stack: list[str] = []  # 当前正在等待回复的 project_id 栈

async def send_message_handler(args):
    from_id = current_project_id()
    to_id = args["to"]

    # 递归检测：如果目标正在等待调用方回复
    if _call_stack and _call_stack[-1] == to_id:
        # 这就是对方在等的回复，直接作为 return value
        return {"reply": args["body"], "from": from_id}

    # 正常处理
    _call_stack.append(from_id)
    try:
        # ... 注入目标 + 等待回复
    finally:
        _call_stack.pop()
```

**逻辑含义**：当 A 在等 B 的回话时，B 调用 `send_message(to="A")` —— 此时 B 不需要再注入 A，"B 的这句话"本身就是 A 在等的回复。

---

## 15. 错误处理

### 15.1 错误场景及处理

| 场景 | 处理策略 |
|------|----------|
| `send_message` 目标 project_id 不存在 | 返回 `{"from": "system", "reply": "错误: 项目 'xxx' 不存在"}` |
| 目标 Agent 的 `query()` 抛出异常 | 捕获异常，返回 `{"reply": f"(错误: {e})"}` |
| 会话恢复失败 | 创建新会话（降级），日志警告 |
| CC SDK 子进程异常退出 | 尝试重启子进程，失败则将该 project 标记为不可用 |
| 用户 `Ctrl+C` 中断 `repl_ask_user` | 返回 `"(用户未回复)"`，不破坏调用链 |
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

### 16.4 Phase 4：TUI 思考可见化（进行中）

详见 [第 17.4 节](#174-phase-4tui-思考可见化--打磨预估8-小时)。

---

## 17. 实现计划

### 17.1 阶段划分

**Phase 1：单 session + REPL** ✅
Commits: `c6aaebf`。详见 [第 16.1 节](#161-phase-1单-session--repl-)。

**Phase 2：同步 send_message** ✅
Commits: `ad07c0e`。详见 [第 16.2 节](#162-phase-2多-agent--send_message-)。

**Phase 3：__user__ 特殊收件人** ✅
Commits: `3f09c63`（⚠️ 本地未 push）。详见 [第 16.3 节](#163-phase-3__user__-真人交互-)。

**Phase 4：TUI 思考可见化 + 打磨**（预估：8 小时）

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

测试场景（按 PRD 第 11 章）：
1. acp 改协议 → 通知 ncp → ncp 有疑问 → 问 xcp → xcp 回复 → ncp 完成 → acp 汇报
2. Agent 间递归防护：A→B→C→A 场景
3. `__user__` 升级：C 拿不到有效回答时向用户求助

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
| Q5 | 长时间 `send_message` 时用户能否 Ctrl+C？ | 高 | ⚠️ 待验证 | Phase 4 通过耗时显示提供反馈；interrupt 机制待验证 |
| Q6 | Agent 会不会填错 `to` 参数？ | 低 | ✅ 已验证 | system_prompt 注入 + 项目列表，E2E 测试中从未填错 |
| Q7 | `send_message` 等待时 SDK 是否有超时？ | 中 | ⚠️ 待验证 | 实测未见超时。Phase 4 建议加超时保护 |

**Phase 4 新增风险**：

| # | 问题 | 风险等级 | 缓解措施 |
|---|------|----------|----------|
| Q8 | `ThinkingBlock` 在 DeepSeek v4（非推理模型）下不出现 | 低 | 实现上不做假设，有则渲染、无则跳过 |
| Q9 | `ToolResultBlock` 的 `tool_use_id` 能否可靠关联到 `ToolUseBlock` | 低 | SDK 类型已包含此字段，待实测确认 |

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
| **mailbox** | 消息持久化存储（文件系统） |
| **`__user__`** | 特殊收件人标识，代表真人用户 |
| **send_message** | 唯一的 MCP tool，用于 Agent 间同步消息传递 |

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
