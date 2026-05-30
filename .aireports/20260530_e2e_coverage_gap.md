# E2E 测试覆盖度差距分析

**日期**：2026-05-30  
**分析范围**：sextant Web UI（src/sextant/web/）  
**现有测试**：tests/test_v2_e2e.py（12 个类，41 个测试用例）

---

## 1. 现状总览

### 1.1 现有测试的真实性质

`tests/test_v2_e2e.py` **不是浏览器 E2E 测试**。它是纯 Python 后端集成测试：

| 测试类 | 覆盖内容 | 类型 | 测试数 |
|--------|----------|------|--------|
| `TestMailbox` | Mailbox 写入/读取/标记 | 单元→集成 | 5 |
| `TestSendMessage` | send_message 工具逻辑 | 单元→集成 | 3 |
| `TestSessionManagerMailbox` | SessionManager 草稿构建 | 单元→集成 | 3 |
| `TestFullWorkflow` | 完整业务流程 | 集成 | 1 |
| `TestMailboxEdgeCases` | JSONL 损坏/空操作 | 单元 | 8 |
| `TestSendMessageErrors` | send_message 错误分支 | 单元 | 3 |

**关键发现**：项目中**没有** Playwright/浏览器自动化测试。没有 `playwright.config.*`、没有浏览器 fixture、没有 `page.goto()` 调用。

### 1.2 现有基础设施缺失

| 项目 | 状态 |
|------|------|
| Playwright 依赖 | ❌ 未安装 |
| playwright.config | ❌ 不存在 |
| 浏览器 fixture | ❌ 不存在 |
| Flask 测试客户端 | ❌ 未用于 E2E |
| CI Playwright runner | ❌ 不存在 |

---

## 2. 前端用户流程全景图

从 `app.js` 中提取了 **37 个函数**，归纳为以下关键用户流程：

### 2.1 初始化流程

| ID | 流程 | 描述 | 涉及函数 | 覆盖 |
|----|------|------|----------|------|
| UF-01 | 页面加载初始化 | localStorage 读取设置、GET /api/projects、渲染侧边栏 | `init()`, `renderAgentList()` | ❌ |
| UF-02 | 初始化失败处理 | API 连接失败显示错误提示 | `init()` catch 分支 | ❌ |

### 2.2 Agent 选择与切换

| ID | 流程 | 描述 | 涉及函数 | 覆盖 |
|----|------|------|----------|------|
| UF-03 | 首次选择 Agent | 中止旧流、缓存旧会话、调 pending/history API、渲染聊天 UI | `selectAgent()` | ❌ |
| UF-04 | 再次切换回 Agent | 从 chatCache 恢复历史、静默刷新获取 CLI 消息 | `selectAgent()` cache 分支 | ❌ |
| UF-05 | Agent 选中高亮 | 侧边栏 .active 类切换 | `selectAgent()` | ❌ |

### 2.3 Mailbox 草稿展示

| ID | 流程 | 描述 | 涉及函数 | 覆盖 |
|----|------|------|----------|------|
| UF-06 | 展示待处理消息 | GET /api/chat/{id}/pending → 系统气泡 + 填入 textarea | `fetchMailboxDraft()` | ❌ |
| UF-07 | 标记已投递 | POST /api/chat/{id}/consume-pending | `fetchMailboxDraft()` | ❌ |
| UF-08 | 去重（同会话不重复展示） | shownMsgIds Set 去重 | `fetchMailboxDraft()` | ❌ |
| UF-09 | 空待处理消息 | 无 pending 时静默跳过 | `fetchMailboxDraft()` | ❌ |

### 2.4 消息发送与 SSE 流式渲染

| ID | 流程 | 描述 | 涉及函数 | 覆盖 |
|----|------|------|----------|------|
| UF-10 | 发送普通消息 | 清空输入、追加 user bubble、调 streamResponse | `sendMessage()` | ❌ |
| UF-11 | SSE text 流式渲染 | 逐字符 append → rAF 批量渲染 markdown | `streamResponse()`, `scheduleRender()` | ❌ |
| UF-12 | SSE thinking 块展示 | showThinking=true 时显示思考内容 | `streamResponse()` (thinking case) | ❌ |
| UF-13 | SSE tool_use 展示 | 工具调用渲染（含 send_message 特殊格式） | `streamResponse()`, `appendMessage()` | ❌ |
| UF-14 | SSE tool_result 展示 | 工具结果渲染（含错误标记） | `streamResponse()` | ❌ |
| UF-15 | SSE server_tool/server_tool_result | 服务器工具渲染 | `streamResponse()` | ❌ |
| UF-16 | SSE done 事件 | 刷新渲染、显示耗时/费用、追加 cost bar | `streamResponse()` (done case) | ❌ |
| UF-17 | SSE error 事件 | 错误消息展示 | `streamResponse()` (error case) | ❌ |
| UF-18 | SSE 连接错误 | AbortError 外的网络异常 | `streamResponse()` catch 分支 | ❌ |
| UF-19 | 流式中断 (AbortError) | 切换 Agent 时 AbortController 取消 | `streamResponse()`, `selectAgent()` | ❌ |

### 2.5 Slash 命令

| ID | 流程 | 描述 | 端点 | 覆盖 |
|----|------|------|------|------|
| UF-20 | `/help` | 显示帮助文本 | 纯前端 | ❌ |
| UF-21 | `/agents` | GET /api/agents，表格渲染 | `/api/agents` | ❌ |
| UF-22 | `/mcp` | GET /api/chat/{id}/mcp，MCP 服务器列表 | `/api/chat/{id}/mcp` | ❌ |
| UF-23 | `/context` | GET /api/chat/{id}/context，进度条 + 分类 | `/api/chat/{id}/context` | ❌ |
| UF-24 | `/context all` | 同上，all=true 参数 | `/api/chat/{id}/context?all=true` | ❌ |
| UF-25 | `/usage` / `/cost` | GET /api/chat/{id}/usage，费用概览 | `/api/chat/{id}/usage` | ❌ |
| UF-26 | `/info` | GET /api/chat/{id}/info，PID/CWD/Session | `/api/chat/{id}/info` | ❌ |
| UF-27 | `/rename <标题>` | POST /api/chat/{id}/rename | `/api/chat/{id}/rename` | ❌ |
| UF-28 | `/fork` / `/branch` | POST /api/chat/{id}/fork | `/api/chat/{id}/fork` | ❌ |
| UF-29 | `/plan` | POST /api/chat/{id}/perm → plan | `/api/chat/{id}/perm` | ❌ |
| UF-30 | `/perm <模式>` | POST /api/chat/{id}/perm → 指定模式 | `/api/chat/{id}/perm` | ❌ |
| UF-31 | `/model <名称>` | POST /api/chat/{id}/model | `/api/chat/{id}/model` | ❌ |
| UF-32 | `/status` | GET /api/projects，待处理计数表 | `/api/projects` | ❌ |
| UF-33 | `/clear` | 清空聊天区 | 纯前端 | ❌ |
| UF-34 | `/compact` | 透传 agent，触发 SSE 流 | POST + SSE | ❌ |
| UF-35 | `/skills` | 同上 | POST + SSE | ❌ |
| UF-36 | 未知命令 | 纯前端错误提示 | 纯前端 | ❌ |

### 2.6 Mailbox 视图

| ID | 流程 | 描述 | 端点 | 覆盖 |
|----|------|------|------|------|
| UF-37 | 打开 Mailbox 视图 | GET /api/mailbox，卡片列表 | `/api/mailbox` | ❌ |
| UF-38 | Mailbox 项目过滤 | GET /api/mailbox?project=X | `/api/mailbox?project=` | ❌ |
| UF-39 | 空 Mailbox | 0 条消息时显示空状态 | `/api/mailbox` | ❌ |
| UF-40 | Mailbox 加载失败 | API 错误处理 | `/api/mailbox` | ❌ |

### 2.7 设置面板

| ID | 流程 | 描述 | 涉及函数 | 覆盖 |
|----|------|------|----------|------|
| UF-41 | 切换设置面板 | .visible 类切换 | `toggleSettings()` | ❌ |
| UF-42 | 思考过程开关 | localStorage 持久化 | `updateThinkingSetting()` | ❌ |
| UF-43 | 权限模式选择 | localStorage + 远程下发 | `updatePermSetting()`, `applyPermMode()` | ❌ |
| UF-44 | 点击外部关闭 | document click listener | 事件监听器 | ❌ |

### 2.8 输入框交互

| ID | 流程 | 描述 | 涉及函数 | 覆盖 |
|----|------|------|----------|------|
| UF-45 | Enter 发送 | Enter 键提交（不含 Shift） | keydown listener | ❌ |
| UF-46 | Shift+Enter 换行 | 不提交，插入换行 | keydown listener | ❌ |
| UF-47 | ↑↓ 历史导航 | 按项目过滤的历史记录 | ArrowUp/ArrowDown listener | ❌ |
| UF-48 | 输入框自适应高度 | 自动 resize（max 120px） | input listener | ❌ |
| UF-49 | 空输入拒绝 | trim 后为空不发送 | `sendMessage()` | ❌ |

### 2.9 背景轮询与缓存

| ID | 流程 | 描述 | 涉及函数 | 覆盖 |
|----|------|------|----------|------|
| UF-50 | 侧边栏定时刷新 | 5s 间隔 GET /api/projects 更新 badge | setInterval | ❌ |
| UF-51 | 历史静默刷新 | 检测 CLI 产生的新消息 | `refreshHistory()` | ❌ |
| UF-52 | 消息缓存机制 | chatCache 按 project 存储/恢复 | `selectAgent()` | ❌ |

### 2.10 Markdown 渲染

| ID | 流程 | 描述 | 涉及函数 | 覆盖 |
|----|------|------|----------|------|
| UF-53 | 基础 Markdown | 标题、粗体、代码块、列表、引用 | `renderMarkdown()` | ❌ |
| UF-54 | XSS 防护 | HTML 实体转义 | `esc()`, `escHtml()` | ❌ |

### 2.11 其他前端功能

| ID | 流程 | 描述 | 涉及函数 | 覆盖 |
|----|------|------|----------|------|
| UF-55 | 滚动到底部 | rAF 延迟滚动 | `scrollToBottom()` | ❌ |
| UF-56 | 时间格式化 | ISO → 可读格式 | `fmtTime()` | ❌ |
| UF-57 | 进度条渲染 | █░ 字符进度条 | `progressBar()` | ❌ |
| UF-58 | 工具输入格式化 | 单字段简化 / JSON 截断 | `formatToolInput()` | ❌ |
| UF-59 | 系统气泡 append | 支持 HTML/纯文本 | `appendSystem()` | ❌ |
| UF-60 | 费用条 append | cost bar 显示 | `appendCost()` | ❌ |

---

## 3. 覆盖度汇总

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
E2E 覆盖度现状
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
流程总数:           60
已有 Playwright 测试:  0
覆盖百分比:          0%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**根本原因**：现有 `test_v2_e2e.py` 虽然文件名含 "e2e"，但全部是 Python 后端集成测试。真正的浏览器 E2E 测试（Playwright）尚未引入。

---

## 4. 新增测试优先级排序

### P0 — Golden Path（必须覆盖，6 个场景）

这些是用户的核心操作路径，任何回归都会直接导致产品不可用：

| 优先级 | ID | 测试场景 | 理由 |
|--------|----|----------|------|
| **P0-1** | UF-01+UF-10+UF-11+UF-16 | **完整对话流程**：页面加载 → 选 Agent → 输入消息 → 查看 SSE 流 → done | 核心价值路径 |
| **P0-2** | UF-03+UF-04 | **Agent 切换 + 缓存恢复**：切换 Agent 后回切，历史保留 | 多项目核心交互 |
| **P0-3** | UF-06+UF-07 | **Mailbox 草稿 → 发送**：pending 消息自动填入 → 发送 → 标记 delivered | 跨 Agent 通信核心 |
| **P0-4** | UF-37 | **Mailbox 视图**：打开 Mailbox 查看所有消息 | 消息监控入口 |
| **P0-5** | UF-20~21 | **Slash 命令**：/help + /agents（最基本的发现性命令） | 功能发现 |
| **P0-6** | UF-45+UF-49 | **输入框基本交互**：Enter 发送、空输入拒绝 | 输入基础 |

### P1 — 重要路径（应覆盖，12 个场景）

| 优先级 | ID | 测试场景 | 理由 |
|--------|----|----------|------|
| **P1-1** | UF-13+UF-14 | **工具调用展示**：tool_use → tool_result 流式渲染 | SSE 渲染核心 |
| **P1-2** | UF-12 | **thinking 块**：开关控制显示/隐藏 | 调试常用 |
| **P1-3** | UF-17+UF-18 | **SSE 错误处理**：后端 error 事件 + 网络异常 | 容错 |
| **P1-4** | UF-23+UF-25+UF-26 | **信息查询命令**：/context、/usage、/info | 运维常用 |
| **P1-5** | UF-27+UF-28 | **会话管理**：/rename、/fork | 会话生命周期 |
| **P1-6** | UF-29+UF-30 | **权限模式切换**：/plan、/perm acceptEdits | 安全边界 |
| **P1-7** | UF-31 | **模型切换**：/model 命令 | 运行时配置 |
| **P1-8** | UF-32 | **/status 命令**：显示各项目 pending 计数 | 全局视图 |
| **P1-9** | UF-41+UF-42+UF-43 | **设置面板**：思考开关、权限模式选择、localStorage 持久化 | 个性化 |
| **P1-10** | UF-47 | **输入历史导航**：↑↓ 跨项目历史 | 效率交互 |
| **P1-11** | UF-50 | **侧边栏定时刷新**：5s 更新 badge 计数 | 实时状态 |
| **P1-12** | UF-08 | **Mailbox 去重**：同一会话不重复展示 | 数据一致性 |

### P2 — 边缘与加固（建议覆盖，8 个场景）

| 优先级 | ID | 测试场景 | 理由 |
|--------|----|----------|------|
| **P2-1** | UF-02 | **页面加载失败**：API 不可达 | 容错 |
| **P2-2** | UF-34+UF-35 | **透传命令**：/compact、/skills → SSE | 命令完整性 |
| **P2-3** | UF-36 | **未知命令提示** | UX 完整性 |
| **P2-4** | UF-19 | **流式中断**：切换 Agent 中止 SSE | 并发安全 |
| **P2-5** | UF-33 | **/clear 清屏** | 基础功能 |
| **P2-6** | UF-38+UF-39 | **Mailbox 过滤 + 空状态** | 数据视图 |
| **P2-7** | UF-44 | **设置面板点击外部关闭** | 交互完整性 |
| **P2-8** | UF-48 | **输入框自适应高度** | 输入体验 |

### P3 — 纯函数单元测试（可用 Jest/Vitest 做，4 个场景）

这些不需要浏览器，可以用 JS 测试框架在 Node 环境跑：

| 优先级 | ID | 测试目标 | 理由 |
|--------|----|----------|------|
| **P3-1** | UF-53 | `renderMarkdown()` 各种输入 | 纯计算函数 |
| **P3-2** | UF-54 | `esc()` / `escHtml()` XSS 防护 | 安全函数 |
| **P3-3** | UF-57 | `progressBar()` | 纯计算函数 |
| **P3-4** | UF-58 | `formatToolInput()` | 边界 case |

---

## 5. 推荐实施方案

### 5.1 测试架构

```
tests/
├── e2e/                          # 新增 Playwright E2E
│   ├── conftest.py               # Flask 测试服务器 fixture
│   ├── test_init.spec.py         # UF-01, UF-02
│   ├── test_agent_select.spec.py # UF-03, UF-04, UF-05
│   ├── test_chat.spec.py         # UF-10~19
│   ├── test_mailbox.spec.py      # UF-06~09, UF-37~40
│   ├── test_slash_commands.spec.py # UF-20~36
│   ├── test_settings.spec.py     # UF-41~44
│   ├── test_input.spec.py        # UF-45~49
│   └── test_rendering.spec.py    # UF-53~60
├── unit/                         # JS 函数单元测试（可选）
│   └── app.test.js               # P3 tests
└── (existing)                    # 保留现有 Python 测试
    ├── test_v2_e2e.py
    ├── test_config.py
    └── test_session_helpers.py
```

### 5.2 技术选型：Playwright + pytest-playwright

选择理由：
1. **Python 生态统一**：项目是 Python 项目，pytest-playwright 与现有 pytest 基础设施无缝集成
2. **跨浏览器**：Chrome/Firefox/Safari 自动管理
3. **无构建工具**：与项目"零构建工具"哲学一致
4. **Flask 集成**：通过 `conftest.py` 启动 Flask 测试服务器

### 5.3 conftest.py 设计

```python
# tests/e2e/conftest.py
import pytest
import subprocess
import time
from playwright.sync_api import sync_playwright

@pytest.fixture(scope="session")
def flask_server():
    """启动 sextant web 测试实例"""
    proc = subprocess.Popen(
        ["python", "-m", "sextant", "web", "--port", "15008"],
        env={**os.environ, "SEXTANT_CONFIG": "tests/fixtures/sextant_test.yaml"},
    )
    time.sleep(3)  # 等待 agent 就绪
    yield "http://127.0.0.1:15008"
    proc.terminate()

@pytest.fixture(scope="function")
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
```

### 5.4 依赖添加

```toml
# pyproject.toml [project.optional-dependencies]
dev = [
    "pytest-playwright",
]
```

```bash
uv pip install pytest-playwright
playwright install chromium
```

### 5.5 分阶段实施建议

| 阶段 | 内容 | 预估工作量 | 覆盖率目标 |
|------|------|-----------|-----------|
| Phase 1 | 基础设施 + P0-1（完整对话流程） | 2-3h | 验证可行性 |
| Phase 2 | P0 全部 6 个场景 | 4-6h | Golden path 100% |
| Phase 3 | P1 全部 12 个场景 | 6-8h | 核心 + 重要路径覆盖 |
| Phase 4 | P2 边缘 + P3 纯函数 | 3-4h | 全面覆盖 |
| **总计** | | **15-21h** | **约 50% 用户流程覆盖** |

---

## 6. 关键风险与注意事项

### 6.1 测试难度分级

| 难度 | 场景 | 说明 |
|------|------|------|
| 🟢 低 | UF-01, UF-02, UF-20~21, UF-33, UF-36, UF-37~40, UF-41~44, UF-49 | 纯前端交互，通过 mock API 即可测试 |
| 🟡 中 | UF-03~05, UF-06~09, UF-23~32, UF-45~48, UF-50~52 | 需要部分后端状态，可通过测试用 sextant.yaml + 模拟 mailbox 数据测试 |
| 🔴 高 | UF-10~19, UF-34, UF-35 | 需要真实 ClaudeSDKClient 启动并产生 SSE 流，或 mock SSE 端点 |

### 6.2 SSE 测试策略

由于 SSE 流依赖 ClaudeSDKClient（需要真实 API Key），有以下替代方案：

1. **方案 A（推荐）**：在测试环境中 mock `/api/chat/{id}/stream` 端点，返回预设的 SSE 事件序列
2. **方案 B**：使用 Flask 测试客户端 + `test_request_context`，直接注入 SSE 队列
3. **方案 C**：在测试配置中创建一个真实但无害的 agent（如空目录 + minimal prompt）

### 6.3 去重注意

- 现有 `test_v2_e2e.py` 中的后端测试**应保留**，它们覆盖了 Mailbox/SessionManager/send_message 的后端逻辑
- 新的 Playwright 测试**不要重复**后端逻辑验证，聚焦于 UI 交互和集成行为
- 建议将现有 `test_v2_e2e.py` 重命名为 `test_backend_integration.py` 或 `test_mailbox.py` 以避免混淆

---

## 7. 总结

| 指标 | 当前 | 目标 |
|------|------|------|
| 浏览器 E2E 测试 | 0 个 | ≥30 个 |
| Golden Path 覆盖 | 0% | 100% |
| Slash 命令覆盖 | 0% | 100% |
| SSE 流式渲染覆盖 | 0% | ≥80% |
| 关键用户流程覆盖 | 0% | ≥50% |

**优先级最高的事项**：
1. ⬜ 安装 Playwright + 创建 conftest.py 基础设施
2. ⬜ 实现 P0-1（完整对话流程）作为 smoke test
3. ⬜ 将现有 `test_v2_e2e.py` 重命名为更准确的文件名
4. ⬜ 按 P0 → P1 → P2 → P3 顺序渐进补充


---

## 8. 实施结果（2026-05-30）

### 已创建文件

```
tests/e2e/
├── __init__.py                  # 包声明
├── conftest.py                  # Mock Flask 服务器 + Playwright fixtures (402 行)
├── test_page_load.py            # P0: 页面加载初始化 (6 tests)
├── test_agent_select.py         # P0: Agent 选择与切换 (7 tests)
├── test_mailbox_draft.py        # P0: Mailbox 草稿展示 (5 tests)
├── test_chat_stream.py          # P0/P1: SSE 流式渲染 (8 tests)
├── test_slash_commands.py       # P0/P1: Slash 命令 (19 tests)
├── test_mailbox_view.py         # P0: Mailbox 视图 (5 tests)
├── test_settings.py             # P1: 设置面板 (6 tests)
└── test_input.py                # P0/P1: 输入框交互 (6 tests)
```

### 测试架构

- **Mock Flask 服务器**：serve 真实前端 + mock `/api/*` 端点，无需 ClaudeSDKClient
- **Playwright + pytest-playwright**：Chromium 浏览器自动化
- **数据隔离**：每个测试使用独立的 browser context

### 最终结果

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
测试汇总
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
后端测试（Python）:                    65 passed
浏览器 E2E 测试（Playwright/Chromium）:  61 passed
─────────────────────────────────────────────
总计:                                 126 passed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 用户流程覆盖度变化

| 指标 | Before | After |
|------|--------|-------|
| 浏览器 E2E 测试数 | 0 | 61 |
| 页面初始化覆盖 | 0% | 6/6 ✓ |
| Agent 选择/切换覆盖 | 0% | 7/7 ✓ |
| Mailbox 草稿覆盖 | 0% | 5/5 ✓ |
| SSE 流式渲染覆盖 | 0% | 8/10 (80%) |
| Slash 命令覆盖 | 0% | 19/19 ✓ |
| Mailbox 视图覆盖 | 0% | 5/5 ✓ |
| 设置面板覆盖 | 0% | 6/6 ✓ |
| 输入交互覆盖 | 0% | 6/6 ✓ |
| **Golden Path 总覆盖** | **0%** | **100%** |

### 运行命令

```bash
# 运行所有 E2E 测试
.venv/bin/python -m pytest tests/e2e/ -v

# 运行所有测试（含后端）
.venv/bin/python -m pytest tests/ -v

# 运行单个文件
.venv/bin/python -m pytest tests/e2e/test_slash_commands.py -v
```
