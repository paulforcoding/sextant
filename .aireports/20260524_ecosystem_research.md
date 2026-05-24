# sextant — 生态调研：CC 作为 MCP/A2A Server

> 2026-05-24 | 调研 CC 是否能直接作为 MCP server 或 A2A server

## 调研动机

如果 CC 自身就能作为 MCP/A2A server，sextant 可能不需要自己做 MCP server——直接编排多个 CC 实例即可。

## 发现 1：`claude mcp serve` — CC 原生 MCP Server 模式

### 基本信息

- **来源**：CC 内置命令，非社区 hack
- **命令**：`claude mcp serve`
- **原理**：CC 以 headless 模式运行，通过 stdio transport 暴露其工具集
- **暴露的工具**：Bash、Read/View、Write/Edit、Grep、Glob、Replace、dispatch_agent
- **传输层**：JSON-RPC 2.0 over stdio（无网络暴露）

### 配置示例

```json
{
  "mcpServers": {
    "claude-code": {
      "command": "claude",
      "args": ["mcp", "serve"]
    }
  }
}
```

其他 MCP 客户端（Claude Desktop、Cursor、Windsurf）可以连接此 server，远程调用 CC 的工具。

### 关键限制：无状态

**每次 `claude mcp serve` 调用都是独立的 CC 实例。** 处理完一个请求后进程退出。没有 session 持久化，没有跨调用的记忆。

这意味着：
- ✅ 可以「让 CC 帮忙改个文件、跑个命令」——一次性任务
- ❌ 不能「和 CC 持续对话，让它记住上下文」——没有 session
- ❌ 不能「CC A 发消息给 CC B，CC B 下次还记得」——sextant 的核心场景不支持

### 对 sextant 的影响

不能直接用 `claude mcp serve` 替代 sextant 的 MCP server 部分。它是一个 **one-shot agent as a tool**，不是 **persistent agent as a peer**。

但它的存在证明：Anthropic 已经在往「CC 作为 server 被其他 agent 调用」方向走。未来可能支持持久化 session。

### 参考

- 完整教程：https://www.ksred.com/claude-code-as-an-mcp-server-an-interesting-capability-worth-understanding
- steipete 的 one-shot 包装：https://github.com/steipete/claude-code-mcp（对 `claude mcp serve` 的易用性封装，增加自动 `--dangerously-skip-permissions`）

## 发现 2：`claude-a2a` — 社区用 CC SDK 包装的 A2A Server

### 基本信息

- **项目**：https://github.com/ericabouaf/claude-a2a
- **作者**：ericabouaf
- **状态**：5 commits，明确标注 "not production ready"
- **协议**：ISC

### 原理

用 CC Agent SDK 的 `ClaudeSDKClient` 管理一个持久化 session，通过 A2A 协议暴露为 agent endpoint。

```
外部 A2A 客户端
     │
     ▼
┌─────────────┐
│ claude-a2a   │  ← A2A HTTP server (port 3008)
│              │
│ 收到 task ──→ ClaudeSDKClient.query()
│              │
│              │  session 持久化到磁盘
│              │  下次 task 可以 resume
└─────────────┘
```

关键能力：
- Session 持久化（`ClaudeSDKClient` 内置）
- Agent card 暴露（`/.well-known/agent-card`）
- Task 生命周期管理（A2A 协议层）

### 和 sextant 混合架构的对比

| | claude-a2a | sextant 混合架构 |
|---|---|---|
| 底层技术 | CC Agent SDK `ClaudeSDKClient` | CC Agent SDK `query()` + `resume` |
| 暴露协议 | A2A（Google 标准） | MCP（Anthropic 标准） |
| 管理范围 | 单个 CC 实例 | 多个项目 × 多个 CC 实例 |
| 消息模型 | Task-based（创建任务，获取结果） | Message-based（send_message / check_inbox） |
| 适用场景 | 跨网络 agent 互调 | 本地多项目 agent 通信 |

**本质上是同一技术栈在不同问题上的应用。**

### 对 sextant 的启示

1. **CC SDK 管理 headless session 这条路是走通的。** 社区已经有人验证了相同技术栈。
2. **A2A 协议层对 sextant 是多余的。** sextant 的场景是本地、同机器的多项目通信，不需要跨网络、不需要 agent card 发现机制。
3. **sextant 应该保持 MCP 协议。** 因为目标用户（交互式 CC CLI）本身就是 MCP client，用 MCP tools（send_message / check_inbox）是最自然的交互方式。

## 发现 3：`A2A-MCP-Server` — 协议桥接

- **项目**：https://github.com/GongRzhe/A2A-MCP-Server
- **类型**：MCP ↔ A2A 协议桥接
- **作用**：让 MCP 客户端可以调用 A2A agent，反之亦然

对 sextant 的关联：如果将来需要让 sextant 管理的 CC 实例和外部 A2A agent 通信，可以用这个桥接。当前不需要。

## 总结

```
生态位地图：

  CC 能力暴露方向
  ┌─────────────────────────────────────────────────────┐
  │                                                     │
  │  one-shot                   persistent               │
  │  ┌──────────────┐          ┌──────────────────┐     │
  │  │ claude mcp    │          │ CC Agent SDK      │     │
  │  │ serve         │          │ ClaudeSDKClient   │     │
  │  │ (CC 内置)      │          │ (Anthropic 提供)   │     │
  │  └──────────────┘          └────────┬─────────┘     │
  │                                     │               │
  │                          ┌──────────┼──────────┐    │
  │                          │          │          │    │
  │                     claude-a2a   sextant    (未来)  │
  │                     (A2A 包装)  (MCP 包装)         │
  │                     社区项目     我们要做的         │
  │                                                     │
  └─────────────────────────────────────────────────────┘
```

sextant 的定位没有因为这两个发现而改变：
- `claude mcp serve` 太简单（无状态），不能直接用
- `claude-a2a` 验证了技术栈的可行性，但协议和场景不同
- sextant 在生态中占据的生态位是：**用 CC SDK 管理多项目 session + MCP 协议做 agent 间通信**
