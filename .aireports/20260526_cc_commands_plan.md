# sextant CC 命令完整实现计划

> 2026-05-26 · 对 CC CLI 全部 ~55 个 slash command 的分类与实现路径

## 方法论

命令分为两大类：
1. **SDK 直接支持**：SDK 有对应的 Python API（如 `get_context_usage()`, `rename_session()`）
2. **Slash 命令透传**：通过 SDK 把 `/command` 作为 prompt 发给 CC CLI 处理（SDK 文档明确支持此方式）

参考：https://code.claude.com/docs/en/agent-sdk/slash-commands

---

## 一、已有命令 ✅ (8个)

| sextant 命令 | 对应 CC 命令 | 实现方式 |
|-------------|-------------|---------|
| `/model <name>` | `/model` | `client.set_model()` |
| `/perm <mode>` | `/permissions` | `client.set_permission_mode()` |
| `/status` | (sextant 特有) | `mailbox.all_pending_counts()` |
| `/help` | `/help` | 内置 |
| `/clear` | `/clear` | `print("\033[2J\033[H")` |
| `/exit` | `/exit` | `return "exit"` |
| `/chat <p>` | (sextant 特有) | mailbox 切换 |
| `/info` | (部分) | `client.get_server_info()` |

---

## 二、高优先级：Phase 9 实施 (6个) 🔴

这些是用户最常用、SDK 直接支持的核心命令。

### 2.1 `/context [all]` — 上下文用量可视化

**SDK API**：`client.get_context_usage()` → `ContextUsageResponse`

**实现**：
```python
async def _handle_context(mgr, cur_project, show_all=False):
    client = mgr.get_client(cur_project)
    usage = await client.get_context_usage()
    # 渲染
    pct = usage["percentage"]
    bar = _progress_bar(pct)
    print(f"\n  {bar} {pct:.0f}%  {usage['totalTokens']:,}/{usage['maxTokens']:,} tokens")
    print(f"  模型: {usage['model']}")
    print(f"  自动压缩: {'✓' if usage['isAutoCompactEnabled'] else '✗'}")
    print()
    for cat in sorted(usage["categories"], key=lambda c: -c["tokens"]):
        if cat["tokens"] > 0:
            print(f"  {cat['name']:<20s} {cat['tokens']:>10,d} tokens")
    if show_all:
        # 展开 memoryFiles, mcpTools, agents 详情
        ...
```

**关键数据字段**：
| 字段 | 说明 |
|------|------|
| `categories` | `[{name, tokens, color, isDeferred?}]` — 分类统计 |
| `totalTokens` | 总 token 数 |
| `maxTokens` | 有效上限（自动压缩后会下调） |
| `rawMaxTokens` | 原始模型上下文窗口 |
| `percentage` | 使用百分比 (0-100) |
| `memoryFiles` | CLAUDE.md 等文件的 token 占用 |
| `mcpTools` | MCP 工具 token 占用 |
| `agents` | Agent 定义 token 占用 |
| `apiUsage` | 累计 API 使用量 |
| `isAutoCompactEnabled` | 是否开启自动压缩 |

**命令格式**：
- `/context` — 摘要视图
- `/context all` — 完整展开

---

### 2.2 `/rename [title]` — 重命名当前会话

**SDK API**：`rename_session(session_id, title, directory)`

**实现**：
```python
async def _handle_rename(mgr, cur_project, title=None):
    sid = mgr._session_ids.get(cur_project)
    if not sid:
        print("错误：未捕获到 session_id。请先发起一次对话。")
        return
    if not title:
        title = input("新标题: ").strip()
    if not title:
        return
    from claude_agent_sdk import rename_session
    proj = mgr._config.get_project(cur_project)
    rename_session(sid, title, directory=str(proj.directory))
    print(f"会话 → {title}")
```

**前置条件**：需要在 `chat.py` 的 `_display_message` 中捕获 `ResultMessage.session_id`

```python
# chat.py _display_message 中:
elif isinstance(msg, ResultMessage):
    mgr._session_ids[cur_project] = msg.session_id  # ← 新增
    ...
```

---

### 2.3 `/compact [instructions]` — 压缩对话历史

**SDK 支持**：✅ 通过 slash 命令透传。CC SDK 文档明确支持 `query(prompt="/compact")`

**CC CLI 行为**：
- CC CLI 拦截 `/compact`（不发给模型）
- 内部用 LLM 生成对话摘要
- 在 JSONL 追加 `compact_boundary` 系统消息
- 之后 API payload 缩减 ~87%（14K → 1.8K tokens）
- 本地 JSONL 不缩小（增加 boundary 行）

**实现**：
```python
async def _handle_compact(mgr, cur_project, instructions=None):
    prompt = "/compact"
    if instructions:
        prompt += f" {instructions}"
    # 发送 slash 命令给 CC CLI 处理
    try:
        async for msg in mgr.query(cur_project, prompt):
            _display_message(msg)
    except Exception as e:
        print(f"\n[错误] {e}", file=sys.stderr)
```

**Caveat**：需要验证 DeepSeek 后端（sextant 默认用 deepseek-v4-pro）是否支持 `/compact` slash command。如果 CC CLI 识别并处理，与后端无关；否则可能需要 Anthropic 后端。

---

### 2.4 `/usage` 或 `/cost` — 费用/用量统计

**数据来源**：
1. `ResultMessage.total_cost_usd` — 最近一次查询费用
2. `get_context_usage().apiUsage` — 会话累计 API 使用

**实现**：
```python
async def _handle_usage(mgr, cur_project):
    # 累计费用（需要在 SessionManager 中跟踪）
    total = mgr._total_costs.get(cur_project, 0.0)
    # 最近一次
    last = mgr._last_costs.get(cur_project)
    print(f"  累计费用: ${total:.4f}")
    if last is not None:
        print(f"  最近调用: ${last:.4f}")
    # Context 用量
    usage = await mgr.get_client(cur_project).get_context_usage()
    print(f"  上下文: {usage['percentage']:.0f}% ({usage['totalTokens']:,} tokens)")
```

**前置条件**：在 `chat.py` 中累积 `ResultMessage.total_cost_usd`

---

### 2.5 `/plan` — 进入 Plan 模式

**实现**：
```python
async def _handle_plan(mgr, cur_project):
    await mgr.get_client(cur_project).set_permission_mode("plan")
    print("进入 Plan 模式 — Agent 只读分析，不修改文件。")
    print("用 /perm default 退出。")
```

实际上 `/perm plan` 已经支持，只需要加别名。

---

### 2.6 `/fork` 或 `/branch` — 分支会话

**SDK API**：`fork_session(session_id, directory)`

**CC CLI 行为**：
- 复制当前 session JSONL 到新 UUID
- 新 session 有独立标题（`原标题 (fork)`）
- 两个 session 独立演进

**实现**：
```python
async def _handle_fork(mgr, cur_project):
    sid = mgr._session_ids.get(cur_project)
    if not sid:
        print("错误：未捕获到 session_id")
        return
    from claude_agent_sdk import fork_session
    proj = mgr._config.get_project(cur_project)
    result = fork_session(sid, directory=str(proj.directory))
    print(f"已分支。新会话 ID: {result.session_id}")
    # 可选：切换到新 session
    # sextant 的 session 管理方式不同，分支创建新的 project 或保存 session_id
```

---

## 三、中优先级：Phase 10 (5个) 🟡

### 3.1 `/diff` — 查看改动

**实现**：`git diff` 在项目目录运行
```python
async def _handle_diff(mgr, cur_project):
    proj = mgr._config.get_project(cur_project)
    result = subprocess.run(["git", "diff", "--stat"], cwd=proj.directory, 
                           capture_output=True, text=True)
    print(result.stdout)
```
注意：sextant 每个 project 目录需要是 git repo。不做交互式 viewer。

---

### 3.2 `/rewind` — 回退

**SDK API**：`client.rewind_files(user_message_id)` — 需要 file checkpointing 开启

**实现思路**：
- sextant 可以做个简化版：在 session JSONL 中找到某条用户消息的 UUID
- 调用 `rewind_files(message_uuid)` 回退文件
- 或者用 `/rewind` 作为 slash 命令发给 CC

---

### 3.3 `/btw <question>` — 旁问题

**CC CLI 行为**：问一个问题但不加入主对话历史

**sextant 实现思路**：
- Agent 已经在上下文里了，sending 一个"不要记入历史"的 prompt 在 SDK 层面不好做
- 简单处理：就当普通 prompt 发，但在 sextant 侧标记为 ephemeral
- 或者直接当普通 prompt 发，告知用户"这和普通 prompt 一样"

---

### 3.4 `/effort [level]` — 设置思考深度

**CC CLI**：`/effort low|medium|high|xhigh|max|auto`

**SDK**：未找到 `set_effort()` 方法。需要验证 slash 命令是否可透传。

```python
async def _handle_effort(mgr, cur_project, level):
    prompt = f"/effort {level}"
    await mgr.query(cur_project, prompt)  # 尝试透传
```

---

### 3.5 `/export [filename]` — 导出对话

**实现**：读取 session JSONL → 格式化 → 写入文件
```python
async def _handle_export(mgr, cur_project, filename=None):
    sid = mgr._session_ids.get(cur_project)
    if not sid:
        print("错误：未捕获到 session_id")
        return
    from claude_agent_sdk import get_session_messages
    proj = mgr._config.get_project(cur_project)
    msgs = get_session_messages(sid, directory=str(proj.directory))
    # 格式化并写入
```
低优先级，但技术上可行。

---

## 四、sextant TUI 增强 (Phase 11) 🟢

这些命令增加 sextant 的"终端感"，让 CC 老用户更顺手。

### 4.1 `/resume [filter]` — 列出/恢复会话

sextant v2.0 已支持 `continue_conversation` 和 `session_id`，但没有交互式 session picker。

**实现**：
- 列出 `~/.claude/projects/<slug>/` 下所有 session
- 用 `get_session_info()` 获取标题
- 用户选择后更新 `session_id` 并重连

### 4.2 状态栏增强：显示 session_id + context%

```
[acp] acceptEdits · deepseek-v4-pro · 3m12s · ctx:78% · s:abc123 📬 ncp:2
```

---

## 五、不可用/不适用命令 ❌

这些是 CC CLI TUI 或平台特定功能，sextant 不需要或无法支持：

| 命令 | 原因 |
|------|------|
| `/color` | TUI 提示栏颜色 |
| `/config` `/settings` | Settings UI |
| `/copy` | 剪贴板操作 |
| `/desktop` `/app` | Desktop 应用 |
| `/mobile` `/ios` `/android` | 移动端 |
| `/fast` | Fast mode toggle (模型特定) |
| `/ide` | IDE 集成 |
| `/login` `/logout` | 认证流程 |
| `/doctor` | 安装诊断 |
| `/terminal-setup` | 终端配置 |
| `/theme` | 主题 |
| `/vim` | Vim 模式 |
| `/add-dir` | 动态加目录 (sextant 用 config) |
| `/chrome` | Chrome 集成 |
| `/remote-control` `/rc` | 远程控制 |
| `/teleport` | Web→终端 |
| `/upgrade` | 升级套餐 |
| `/passes` `/stickers` | 营销功能 |
| `/privacy-settings` | 隐私设置 |
| `/extra-usage` | 用量配置 |
| `/sandbox` | 沙盒模式 |
| `/agents` | 子代理配置 UI |
| `/hooks` | Hook 管理 UI |
| `/mcp` | MCP 配置 UI |
| `/memory` | 记忆文件编辑 UI |
| `/permissions` | 权限规则 UI |
| `/plugins` | 插件管理 |
| `/autofix-pr` | 需要 GitHub CI + web |
| `/background` `/bg` | 后台会话 (sextant 不同模型) |
| `/stop` | 停止后台会话 |
| `/tasks` | 后台任务列表 |
| `/insights` `/stats` | 分析报告 (Anthropic 后端) |
| `/release-notes` | 版本日志 |
| `/feedback` `/bug` | 反馈 |

---

## 六、实施优先级总览

```
Phase 9 (立即)           Phase 10 (之后)        Phase 11 (远期)
─────────────────────    ──────────────────     ──────────────────
🔴 /context [all]        🟡 /diff               🟢 /resume picker
🔴 /rename [title]       🟡 /rewind             🟢 状态栏增强
🔴 /compact [instr]      🟡 /effort [level]     🟢 /export
🔴 /usage (别名 /cost)    🟡 /btw <question>     🟢 /init (生成 CLAUDE.md)
🔴 /plan (别名)           🟡 /export [file]
🔴 /fork /branch
```

### 预估工作量

| Phase | 命令数 | 核心代码改动 | 预估时间 |
|-------|--------|------------|---------|
| Phase 9 | 6 | `chat.py` +100行, `session.py` +20行 | 2-3h |
| Phase 10 | 5 | `chat.py` +60行, `session.py` +10行 | 1-2h |
| Phase 11 | 3-4 | `chat.py` +80行, `session.py` +30行 | 2-3h |

### 前置依赖

Phase 9 必须先做：**捕获 `session_id`**。需要：
1. `chat.py` 中 `_display_message` 处理 `ResultMessage` 时记录 `msg.session_id` 到 `SessionManager._session_ids`
2. `SessionManager` 加 `_session_ids: dict[str, str]` 和 `_total_costs: dict[str, float]`

所有重命名、分支、导出、回退功能都依赖这个 session_id。
