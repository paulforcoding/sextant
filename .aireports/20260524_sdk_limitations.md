# MCP Python SDK 限制调研报告

> 2026-05-24 | 通过 demo 代码实测发现

## 调研背景

sextant 的核心通信机制依赖 MCP notification——server 向 agent client 推送 `sextant/new_message` 通知。在 demo 验证阶段发现两个 SDK 层面的限制。

## 限制 1：HTTP 层参数无法直接传递到 Tool Handler

**现象**：middleware 中提取的 `?project=<name>` query param，通过 `contextvars.ContextVar` 设置后，在 tool handler 中读取为空字符串。

**根因**：MCP Streamable HTTP transport 使用生产者-消费者模式。HTTP 请求处理（middleware 所在）和 MCP 协议处理（tool handler 所在）运行在**不同的 asyncio Task** 中，通过 `anyio.memory_object_stream` 队列通信。`ContextVar` 跨 Task 不传播是 Python asyncio 的特性。

```
Task A (HTTP Handler)           Task B (MCP Protocol Loop)
────────────────────            ──────────────────────────
middleware 设置 ContextVar      
  ↓                             
解析 JSON-RPC body              
  ↓                             
write_stream.send(msg)  ──→     read_stream.receive()
                                  ↓
                                tool handler 运行 ← ContextVar 为空
```

**解决方案**：通过 JSON-RPC `request_id` 桥接。middleware 解析 POST body 提取 `id` → 存入 `{request_id → project_name}` 映射 → tool handler 通过 `ctx.request_context.request_id` 查表。已在 demo 中验证可行。

## 限制 2：SDK 不支持自定义 MCP Notification

**现象**：调用 `ServerSession.send_notification()` 发送 `notifications/sextant/new_message` 时报 Pydantic 校验错误。改用 `JSONRPCNotification` + `_write_stream.send()` 直接发送，服务端不报错，但客户端收到后校验失败并丢弃。

**根因**：MCP Python SDK (v1.27.1) 使用 Pydantic `RootModel` + discriminated union 定义 `ServerNotification` 类型，只接受以下内置通知类型：

```python
ServerNotificationType = (
    CancelledNotification
    | ProgressNotification
    | LoggingMessageNotification
    | ResourceUpdatedNotification
    | ResourceListChangedNotification
    | ToolListChangedNotification
    | PromptListChangedNotification
    | ElicitCompleteNotification
    | TaskStatusNotification
)
```

处理流程（`mcp/shared/session.py:397-432`）：

```python
notification = self._receive_notification_type.model_validate(
    message.message.root.model_dump(...)
)
# ↑ 对自定义 method，Pydantic discriminated union 校验失败

except Exception as e:
    logging.warning(f"Failed to validate notification: {e}...")
    # ↑ 消息被丢弃，不会调用 _received_notification / _handle_incoming
```

**结论**：SDK 的类型系统和处理逻辑**双重封堵**了自定义 notification——既无法通过类型校验，校验失败后也没有透传机制。

## 影响评估

| 影响 | 说明 |
|------|------|
| `sextant/new_message` 推送通道 | **完全不可用**，除非修改 SDK 源码或等待官方支持 |
| `check_inbox()` 轮询方案 | token 消耗不可接受（多项目、高频场景） |
| MCP 协议合规性 | MCP 规范本身**允许**任意 notification method，**限制来自 SDK 而非协议** |
| 其他 MCP SDK | 未调研（TypeScript SDK 可能有不同行为） |

## 可能的解决方向

1. **给 MCP SDK 提 PR**：在 `ServerNotificationType` 中添加一个 catch-all variant（如 `GenericNotification`），代价是开发周期长
2. **Fork SDK**：直接修改本地 SDK 源码，维护成本高
3. **利用现有通道**：将消息嵌入 `LoggingMessageNotification.data`（SDK 允许的任意类型字段），需验证 CC 是否展示
4. **不走 MCP notification**：sextant 完全依赖 `check_inbox()` 作为通信路径，accept 其局限性
