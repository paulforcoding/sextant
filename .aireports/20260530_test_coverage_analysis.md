# 测试覆盖度分析报告

**日期**: 2026-05-30
**工具**: pytest-cov 7.1.0
**当前覆盖**: **16%**（1,455 条语句，覆盖 228 条，遗漏 1,227 条）

---

## 一、逐文件分析

| 文件 | 语句 | 遗漏 | 覆盖率 | 优先级 | 分析 |
|------|------|------|--------|--------|------|
| `__init__.py` | 1 | 0 | **100%** | - | 空模块 ✅ |
| `__main__.py` | 2 | 2 | **0%** | 低 | 2 行入口，trivial |
| `config.py` | 41 | 41 | **0%** | 🔴 高 | 纯函数，无外部依赖，**极易测试** |
| `mailbox.py` | 98 | 14 | **86%** | 🟡 中 | 14 行边缘路径（JSONDecodeError、空 msg_ids、异常文件） |
| `send_message.py` | 26 | 3 | **88%** | 🟡 中 | 3 行错误分支（manager/current_project/mailbox 为 None） |
| `session.py` | 167 | 123 | **26%** | 🔴 高 | 大部分是 async context manager 和 agent 交互，需 SDK mock |
| `chat.py` | 451 | 375 | **17%** | 🟠 中 | CLI REPL，依赖真实 SDK client，需大量 mock |
| `cli.py` | 159 | 159 | **0%** | 🟠 中 | argparse + asyncio 入口 |
| `web_server.py` | 510 | 510 | **0%** | 🟠 低 | Flask + SSE，需 Flask test client + mock agents |
| **合计** | **1,455** | **1,227** | **16%** | | |

---

## 二、80% 覆盖可行性分析

### 结构性问题

三个大文件占总代码的 **77%**：
- `web_server.py`（510 条，35%）
- `chat.py`（451 条，31%）
- `session.py`（167 条，11%）

这三者高度依赖 `ClaudeSDKClient`（需要真实 CC agent 进程），纯单元测试无法覆盖其核心路径。**在不启动真实 CC agent 的前提下，80% 覆盖不可行。**

### 可达目标

| 阶段 | 文件 | 当前 | 目标 | 新增覆盖 | 难度 |
|------|------|------|------|---------|------|
| 1 | `config.py` | 0% | **90%** | +37 | 易 · 纯函数 |
| 2 | `mailbox.py` | 86% | **95%** | +7 | 易 · 边缘路径 |
| 3 | `send_message.py` | 88% | **100%** | +3 | 易 · 错误分支 |
| 4 | `session.py` helpers | 26% | **55%** | +48 | 中 · 纯函数+mock |
| 5 | `web_server.py` REST | 0% | **15%** | +77 | 中 · Flask test client |
| **累计** | | **16%** | **~28%** | **+172** | |

---

## 三、各文件遗漏详情

### config.py（0%，41 条遗漏）

| 函数/方法 | 遗漏行 | 说明 |
|-----------|--------|------|
| `ProjectConfig.id` | 24-25 | property，trivial |
| `SextantConfig.get_project()` | 36-39 | 查找逻辑 + KeyError 分支 |
| `load_config()` | 50-66 | 文件搜索 + 解析 + FileNotFoundError |
| `_parse_raw()` | 74-84 | YAML dict → dataclass 转换 |

**测试方案**：创建临时 YAML 文件，测试每个路径。

### mailbox.py（86%，14 条遗漏）

| 遗漏行 | 场景 |
|--------|------|
| 29 | `base_dir=None` 时使用默认路径 |
| 71-72, 89-90, 106 | `json.JSONDecodeError` 异常处理 |
| 117-119 | `mark_delivered` 中 JSON 损坏行保留 |
| 146-147 | `query` 中 JSON 损坏行跳过 |
| 156 | `all_files` 排序 |
| 177-178 | `all_pending_counts` 中 JSON 损坏行跳过 |

**测试方案**：创建损坏的 JSONL 行，验证优雅降级。

### send_message.py（88%，3 条遗漏）

| 遗漏行 | 场景 |
|--------|------|
| 61 | `_manager is None` 错误分支 |
| 68 | `current_project is None` 错误分支 |
| 82 | `_mailbox is None` 错误分支 |

**测试方案**：分别 set_manager/set_mailbox 为 None，验证错误返回。

### session.py（26%，123 条遗漏）

| 区域 | 遗漏行 | 可测性 |
|------|--------|--------|
| `_load_claude_env()` | 41-47 | ✅ 纯函数，mock 文件系统 |
| `__init__` | 71-83 | ✅ 验证属性初始化 |
| `current_project` / `project_ids` | 88-97 | ✅ property 测试 |
| `set_current_project` | 99-102 | ✅ KeyError 分支 |
| `__aenter__` | 108-171 | ❌ 需要真实 CC SDK |
| `__aexit__` | 174-181 | ❌ 需要真实 client |
| `query` | 191-194 | ❌ 需要真实 client |
| `build_mailbox_draft` | 206-218 | ✅ 已有测试 |
| `mark_mailbox_delivered` | 222-224 | ✅ 已有测试 |
| `_prompt_user` | 234-257 | ❌ 需要 asyncio input |
| `_handle_ask_user_question` | 261-295 | ❌ 同上 |
| `_format_tool_for_user` | 302-326 | ✅ 纯函数！ |
| `_build_system_prompt` | 330-351 | ✅ 纯函数！ |

---

## 四、实施计划

### 阶段 1：立即执行（本次）

创建 2 个新测试文件，增强 1 个已有文件：

| 文件 | 动作 | 新增测试数 | 预计覆盖提升 |
|------|------|-----------|-------------|
| `tests/test_config.py` | **新建** | 8-10 个 | +37 条 |
| `tests/test_session_helpers.py` | **新建** | 10-12 个 | +48 条 |
| `tests/test_v2_e2e.py` | **增强** | 5-8 个 | +10 条 |

**预期总覆盖**: 16% → **22-24%**

### 阶段 2：后续执行

| 文件 | 动作 | 预计新增覆盖 |
|------|------|-------------|
| `web_server.py` REST 端点 | Flask test client | +77 条 |
| `chat.py` 渲染函数 | 提取可测函数 | +36 条 |
| `cli.py` arg 解析 | argparse 测试 | +48 条 |

**预期累计覆盖**: ~42%

### 达到 80% 的条件

需要重构以下文件，将核心逻辑从 `ClaudeSDKClient` 依赖中解耦：
1. `session.py`：提取 agent 创建逻辑到可 mock 的工厂
2. `chat.py`：提取 slash 命令 dispatch 到纯函数
3. `web_server.py`：提取 API handler 逻辑到可测函数

这是较大的重构工作，建议作为独立任务执行。

---

## 五、边界说明

**本项目不适用"前端 80% 覆盖"标准**：`index.html` 是纯 HTML/CSS/JS，无构建工具，JavaScript 逻辑以 DOM 操作为主，当前无前端测试框架。前端测试需要引入 Playwright 或 jsdom，与项目"零构建工具"理念冲突。建议通过手动视觉回归测试保证前端质量。

**CLI REPL（chat.py）不适合单元测试**：其设计围绕 `ClaudeSDKClient` 的流式交互，测试需要 mock 整个 SDK 的 async generator 行为，投入产出比低。建议通过 E2E 测试覆盖。
