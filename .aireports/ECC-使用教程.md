# ECC 使用教程 —— 辅助 sextant 开发

## 概述

ECC (Everything Claude Code) 已安装到 sextant 项目的 `.claude/` 目录下，包含 **63 个 agent**、**79 个命令**、**108 个 skill**。本文档只介绍对 sextant 开发**直接有用**的部分，跳过无关内容（Java、Kotlin、Swift、医疗、营销等）。

---

## 一、日常高频命令（必学）

以下命令在 Claude Code 中直接输入 `/` 前缀即可使用。

### 代码质量

| 命令 | 用途 | 适用场景 |
|------|------|---------|
| `/python-review` | Python 代码审查（PEP 8、类型标注、并发安全） | 每次改完 Python 代码后 |
| `/code-review` | 通用代码审查 | 改完前端 JS/HTML 后 |
| `/refactor-clean` | 安全删除死代码 | 重构后清理 |
| `/quality-gate` | 文件/项目级质量管道 | 提交前检查 |
| `/security-scan` | 安全扫描（AgentShield） | 涉及权限、MCP、密钥时 |
| `/test-coverage` | 分析覆盖率缺口 | 补测试时 |

### 规划与实现

| 命令 | 用途 | 适用场景 |
|------|------|---------|
| `/plan` | 需求重述 → 风险评估 → 分步计划 | 新功能开发前（需用户确认后才动手） |
| `/build-fix` | 增量修复构建/类型错误 | CI 挂了、pip install -e . 报错时 |
| `/checkpoint` | 创建验证检查点 | 阶段性成果保存 |
| `/pr` | 自动分析变更、创建 PR | 准备提交代码时 |

### 会话管理

| 命令 | 用途 | 适用场景 |
|------|------|---------|
| `/save-session` | 保存当前会话状态 | 长时间任务中途存档 |
| `/resume-session` | 恢复上次保存的会话 | 第二天继续工作 |
| `/cost-report` | 生成本地成本报告 | 查看 API 花费 |
| `/model-route` | 推荐适合当前任务的模型 | 不确定用哪个模型时 |

### 自主循环（高级）

| 命令 | 用途 |
|------|------|
| `/loop-start` | 启动带安全默认值的自主循环 |
| `/loop-status` | 查看循环状态、进度、异常信号 |

---

## 二、Agent 选择指南

Agent 通过 `Agent` 工具调用。以下是开发 sextant 时最可能用到的：

### 🔴 每次必用

| Agent | 用途 | 调用时机 |
|-------|------|---------|
| `python-reviewer` | Python 专项审查：并发安全（threading/async）、类型标注、安全漏洞（SQL 注入、命令注入、路径遍历）、Pythonic 写法 | 每次 Python 代码改动后 |
| `code-reviewer` | 通用审查，关注正确性、边界情况、安全性 | 前端改动、跨语言改动 |

### 🟡 架构/设计时用

| Agent | 用途 |
|-------|------|
| `code-explorer` | 深度探索代码库，追踪执行路径、理解架构层次 |
| `architect` | 系统架构设计 |
| `code-architect` | 代码级架构设计，分析现有模式后给出实现蓝图 |
| `planner` | 将需求分解为可执行的实现步骤 |

### 🟢 sextant 专属（agent 系统相关）

| Agent | 用途 | 为什么重要 |
|-------|------|-----------|
| `harness-optimizer` | 优化 agent harness 设计 | sextant 本身就是一个 agent harness！优化 SDK client 管理、hook 配置、权限策略 |
| `loop-operator` | 管理自主 agent 循环 | sextant 的 CLI REPL 和 Web 模式都是长时运行的 agent 循环 |
| `silent-failure-hunter` | 追查静默失败 | 异步代码中的 silent bug（asyncio 异常被吞、线程间通信丢失）是 sextant 最棘手的 bug |

### 🔵 质量保障

| Agent | 用途 |
|-------|------|
| `security-reviewer` | 安全审查：认证、授权、密钥管理、注入攻击 |
| `performance-optimizer` | 性能优化 |
| `e2e-runner` | 生成和运行 E2E 测试 |
| `tdd-guide` | TDD 工作流指导 |
| `build-error-resolver` | 构建错误修复 |
| `refactor-cleaner` | 重构清理 |

### ⚪ 辅助

| Agent | 用途 |
|-------|------|
| `code-simplifier` | 简化代码，消除不必要的复杂度 |
| `doc-updater` | 根据代码变更同步更新文档 |
| `pr-test-analyzer` | 分析 PR 中的测试覆盖情况 |
| `type-design-analyzer` | 类型设计分析（Python type hints、dataclass 设计） |
| `conversation-analyzer` | 分析 agent 对话历史，发现模式 |
| `chief-of-staff` | 多任务编排协调 |

---

## 三、Skill 精选

Skill 被 Claude Code 按需自动加载（不像 agent 需要显式调用）。以下是和 sextant 开发直接相关的：

### Agent 系统专项（sextant 核心领域）

| Skill | 解决什么问题 |
|-------|-------------|
| `agent-architecture-audit` | **12 层 agent 栈审计**：系统提示 → 会话历史 → 长期记忆 → 工具选择 → 工具执行 → 答案渲染 → 隐藏修复循环 → 持久化。覆盖 sextant 全部架构层 |
| `agent-introspection-debugging` | agent 行为异常的 4 阶段结构化调试：捕获失败 → 根因诊断 → 可控恢复 → 生成报告 |
| `agent-harness-construction` | 设计 agent 的 action space、observation 格式、错误恢复契约、上下文预算管理 |
| `agentic-engineering` | Eval-first 工程方法：定义评估标准 → 基线 → 实现 → 回归对比；15 分钟任务单元拆分；模型路由策略 |
| `autonomous-loops` | 自主 agent 循环模式：cron 调度、内存持久化、任务队列 |
| `mcp-server-patterns` | MCP server 开发模式（sextant 的 `send_message.py` 就是 MCP server） |

### Python 开发

| Skill | 内容 |
|-------|------|
| `python-patterns` | Python 惯用模式、设计模式 |
| `python-testing` | pytest 最佳实践、fixture、mock、参数化 |
| `coding-standards` | 通用编码规范 |
| `error-handling` | 错误处理模式（sextant 的 asyncio + 多线程场景特别需要） |

### 前端开发

| Skill | 内容 |
|-------|------|
| `frontend-patterns` | 前端通用模式 |
| `frontend-design-direction` | 前端设计指导 |
| `make-interfaces-feel-better` | UI 体验优化（sextant Web UI 是纯 HTML/CSS/JS SPA） |

### 测试与验证

| Skill | 内容 |
|-------|------|
| `tdd-workflow` | TDD 工作流 |
| `e2e-testing` | E2E 测试策略 |
| `verification-loop` | 验证循环——确保改动真正生效 |
| `ai-regression-testing` | AI 系统的回归测试 |

### 工程效率

| Skill | 内容 |
|-------|------|
| `strategic-compact` | 在阶段边界（而非任意 token 阈值）压缩对话——sextant 的长对话管理 |
| `token-budget-advisor` | 上下文预算优化 |
| `search-first` | 先搜索再行动——减少盲目操作 |
| `code-tour` | 为新成员生成代码库导览 |
| `cost-aware-llm-pipeline` | 成本感知的 LLM 管道设计 |
| `context-budget` | 上下文预算管理 |

> **注意**：上面没列出的 skill（如 `django-*`、`laravel-*`、`springboot-*`、`kotlin-*`、`golang-*`、`healthcare-*` 等）对 sextant 开发无用，但它们只是磁盘上的文件，不主动使用就不会加载到上下文。

---

## 四、核心 Skill 详解：agent-architecture-audit

这是 ECC 中对 sextant 最有价值的 skill。它提供一套系统化的 **12 层 agent 栈诊断框架**，能逐层排查 agent 系统中的隐藏问题。

### 为什么它对 sextant 至关重要

sextant 本身就是一个 agent 系统 —— 它管理多个 `ClaudeSDKClient`，通过 mailbox 让 agent 互相通信，用 SSE 将输出推送到浏览器。这意味着 sextant 的每一层都可能引入 bug，而且 bug 往往不是出在模型本身，而是出在 **wrapper 层**（SessionManager、mailbox、SSE transport、can_use_tool 回调等）。

这个 skill 的核心洞察是：**"模型在 playground 里正常工作，到你系统里就坏了"——问题 90% 不在模型，在 wrapper。**

### 12 层栈 → sextant 映射

| # | 审计层 | 在 sextant 中的对应 | 可能出问题的方式 |
|---|--------|-------------------|----------------|
| 1 | System prompt | `system_prompt` 配置、CLAUDE.md | 指令冲突、指令膨胀 |
| 2 | Session history | `SessionManager` 的 session 管理 | 旧会话上下文污染新对话 |
| 3 | Long-term memory | mailbox JSONL 文件 | 过期消息重复显示、delivery status 丢失 |
| 4 | Distillation | compaction 后的压缩内容 | 压缩失真重新进入对话 |
| 5 | Active recall | `/context` 命令、`get_context_usage()` | 冗余的摘要层浪费上下文 |
| 6 | Tool selection | `can_use_tool` 回调 | 模型跳过 send_message 直接用 Bash 通信 |
| 7 | Tool execution | `send_message.py` MCP 工具 | 声称调用了但实际没写入 JSONL |
| 8 | Tool interpretation | agent 对 send_message 返回值的理解 | 误读 ack 返回值，以为消息发送失败 |
| 9 | Answer shaping | agent 输出格式化 | 输出格式在不同模式下不一致 |
| 10 | Platform rendering | Web UI SSE → 浏览器、CLI REPL 渲染 | SSE 事件丢失/乱序、浏览器缓存过期 JS |
| 11 | Hidden repair loops | `chat.py` 双重 SIGINT、`interrupt()` | 隐藏的修复/重试逻辑静默改变输出 |
| 12 | Persistence | mailbox delivery status（内存 `_delivered` set） | 重启后状态丢失、重复投递消息 |

### 什么时候用它

**必用场景：**
- 发版前做整体架构健康检查
- 改了 `send_message.py`、`mailbox.py`、`session.py`、`web_server.py` 等核心模块
- agent 行为异常但排查 15 分钟找不到根因
- 用户反馈"agent 越来越笨"、"工具调用不稳定"
- 新增了 prompt 层、工具定义或记忆系统后

**不要用它的场景：**
- 普通代码 bug → 用 `agent-introspection-debugging`
- 代码风格审查 → 用 `/python-review`
- 安全漏洞扫描 → 用 `/security-scan`

### 审计工作流（4 阶段）

**Phase 1 — 界定范围：** 告诉 Claude Code 你要审计什么：
```
请用 agent-architecture-audit skill 审计 sextant 的 mailbox 消息传递链路，
从 send_message 工具执行 → JSONL 写入 → /chat 读取 pending → delivery status 更新，
关注第 3、7、8、12 层（长期记忆、工具执行、工具解释、持久化）。
```

**Phase 2 — 证据收集：** skill 会自动在代码库中搜索反模式：
- 只在 prompt 文本中声明但代码未强制执行的工具要求
- 未经验证的工具调用
- 主 agent 循环外的隐藏 LLM 调用
- 没有用户纠正优先级的记忆准入逻辑
- 静默输出变异

**Phase 3 — 故障映射：** 每个发现会标注：症状、机制、来源层、根因、证据（`文件:行号`）、置信度

**Phase 4 — 修复策略：** 默认 code-first 而非 prompt-first：
1. 在代码中强制工具要求，而非仅在 prompt 中声明
2. 移除或缩小隐藏修复 agent 的范围
3. 减少上下文重复（同一信息出现在 prompt + history + memory + distillation 四层）
4. 收紧记忆准入：用户纠正 > agent 断言
5. 减少渲染变异：透传而非转换

### 严重度模型

| 级别 | 含义 | 行动 |
|------|------|------|
| `critical` | agent 可能自信地产生错误操作行为 | 发版前必须修复 |
| `high` | agent 频繁降低正确性或稳定性 | 当前迭代修复 |
| `medium` | 正确性通常保持，但输出脆弱或浪费 | 下个迭代计划 |
| `low` | 主要是美观性或可维护性问题 | 放入 backlog |

### 实操示例

**示例 1：审计 mailbox 消息传递**
```
请用 agent-architecture-audit 审计 sextant 的消息生命周期：
agent A send_message → mailbox JSONL → agent B /chat 读取 → mark_delivered。
关注：delivery status 是否只存在于内存（重启丢失）、
是否有隐藏的重试/修复逻辑改变消息内容、
SSE 推送是否可能丢失事件。
```

**示例 2：发版前全栈审计**
```
请用 agent-architecture-audit 对 sextant 做发版前全栈审计，
重点检查：
- SessionManager 的跨线程 client 调用（web_server.py vs chat.py）
- mailbox JSONL 的读写并发安全
- Web UI SSE 推送的完整性和顺序
- can_use_tool 回调是否可能被绕过
```

**示例 3：排查"模型在 playground 正常但 sextant 里不对"**
```
在 Claude Code playground 中 send_message 工具能正确投递，
但在 sextant 的 SessionManager 中运行时，agent 有时跳过 send_message。
请用 agent-architecture-audit 审计第 6 层（工具选择）和第 7 层（工具执行），
定位是 prompt 问题还是 can_use_tool 回调问题。
```

### 快速诊断 7 问

使用这个 skill 时，它会自动检查以下 7 个问题。你可以把这 7 问当作 sextant 开发的日常自查清单：

| # | 问题 | 如果答案为"是" → |
|---|------|-----------------|
| 1 | 模型能否跳过必需工具（send_message）但仍然完成对话？ | 工具未被代码强制 |
| 2 | 旧的对话内容是否出现在新的 session 中？ | 记忆污染 |
| 3 | 同一信息是否同时出现在 system prompt、memory 和 history 中？ | 上下文重复 |
| 4 | 平台是否在投递前运行了第二次 LLM 处理？ | 隐藏修复循环 |
| 5 | 内部生成和用户收到的输出是否不同？ | 渲染层损坏 |
| 6 | "必须使用 tool X"的规则是否只存在于 prompt 文本中？ | 工具纪律失败 |
| 7 | agent 自己的独白能否变成持久记忆？ | 记忆中毒 |

---

## 五、实操工作流示例

### 工作流 1：日常改代码（含 agent-architecture-audit）

```
1. 改完 Python 代码
2. /python-review          → python-reviewer agent 审查变更
3. 根据审查意见修改
4. pip install -e . && python -m pytest tests/ -v
5. /checkpoint             → 保存检查点
```

### 工作流 2：新功能开发

```
1. /plan "给 mailbox 添加消息优先级功能"
   → planner agent 分析需求，给出实现计划
2. 审查计划，确认后开始实现
3. 每完成一个步骤：
   - /python-review        → 审查新代码
   - python -m pytest tests/ -v  → 跑测试
   - /checkpoint           → 保存进度
4. 全部完成后：
   - /quality-gate         → 整体质量检查
   - /security-scan        → 安全扫描
   - /pr                   → 创建 PR
```

### 工作流 3：调试 Agent 行为异常

```
1. 描述问题："agent A 发消息给 agent B，但 B 收不到"
2. Claude Code 自动激活 agent-introspection-debugging skill
   → 捕获失败状态 → 诊断根因 → 尝试修复 → 生成报告
3. 如果涉及架构层面：
   → Agent(agent-architecture-audit) 审计 12 层栈
4. 如果怀疑是静默失败：
   → Agent(silent-failure-hunter) 追查
```

### 工作流 4：重构 SessionManager

```
1. /plan "重构 SessionManager，将 client 生命周期管理改为惰性初始化"
2. Agent(code-architect) 分析现有 SessionManager 代码
   → 给出重构蓝图：哪些文件改、数据流如何变化
3. 实现
4. Agent(python-reviewer) 审查 —— 特别关注：
   - 线程安全（web_server.py 的跨线程调用）
   - async context manager 的 enter/exit 逻辑
   - 资源泄漏（client 是否正确关闭）
5. python -m pytest tests/ -v
6. /checkpoint
```

### 工作流 5：Web UI 改动

```
1. 修改 index.html 或 web_server.py
2. /code-review             → 审查前端和后端改动
3. 启动服务器：sextant web
4. curl 测试关键 API
5. 浏览器验证
6. /quality-gate
```

### 工作流 7：agent-architecture-audit 专项审计

```
1. 确定审计范围（如 mailbox 链路、SessionManager 生命周期、SSE 推送）
2. 向 Claude Code 描述审计目标，skill 自动激活
3. skill 执行 4 阶段审计：界定范围 → 证据收集 → 故障映射 → 修复策略
4. 产出严重度排序的报告（critical/high/medium/low）
5. 按报告中的 ordered_fix_plan 逐项修复
6. /checkpoint create "audit-fixes-done"
```

### 工作流 8：发版前检查

```
1. /security-scan           → AgentShield 扫描
2. /test-coverage           → 覆盖率分析
3. /quality-gate            → 质量管道
4. Agent(silent-failure-hunter) → 最后一次静默失败排查
5. /pr                      → 创建 PR
```

---

## 六、Agent 辨析：易混淆对照表

ECC 安装到项目后，**同名的 agent 会自动覆盖 Claude Code 内置版本**（project > built-in），你不需要手动选择。

### 层级不同、名字相似

| Agent 对 | 核心区别 | 各用于什么 |
|----------|---------|-----------|
| `architect` vs `code-architect` | 系统架构 vs 代码架构 | architect：技术选型、可扩展性、架构决策（Opus）；code-architect：具体文件、接口、数据流、实现顺序（Sonnet） |
| `code-reviewer` vs `code-simplifier` | 找 bug vs 去冗余 | reviewer：全面审查（安全、正确性、性能）；simplifier：只做简化和去冗余，不找 bug |
| `code-reviewer` vs `python-reviewer` | 通用 vs Python 专项 | reviewer：任何语言/文件都可以；python-reviewer：Python 专项，检查并发安全、类型标注、PEP 8 |
| `code-reviewer` vs `comment-analyzer` | 审查代码 vs 审查注释 | reviewer：审查全部代码；comment-analyzer：只分析注释的准确性和完整性 |
| `code-reviewer` vs `type-design-analyzer` | 通用审查 vs 类型设计 | reviewer：通用；type-design-analyzer：只审类型系统（封装、不变式、可用性） |
| `code-explorer` vs `code-architect` | 理解现有 vs 设计新 | explorer：追踪现有代码路径、理解架构；architect：设计新功能的具体实现方案 |
| `planner` vs `code-architect` | 任务分解 vs 代码蓝图 | planner：将需求分解为可执行的步骤列表；code-architect：给出具体的文件、接口、数据流 |
| `refactor-cleaner` vs `code-simplifier` | 删死代码 vs 简化逻辑 | cleaner：识别并删除未使用的代码/文件；simplifier：简化复杂逻辑但不删文件 |

### 功能相近但侧重不同

| Agent 对 | 核心区别 |
|----------|---------|
| `silent-failure-hunter` vs `code-reviewer` | hunter 只追查静默失败（异常被吞、fallback 隐藏问题）；reviewer 做全面审查 |
| `security-reviewer` vs `code-reviewer` | security-reviewer 专注 OWASP Top 10、认证授权、密钥管理；reviewer 也查安全但不那么深入 |
| `harness-optimizer` vs `network-architect` | harness-optimizer 优化 agent harness 设计（sextant 的核心）；network-architect 设计企业网络架构（跟 sextant 无关） |
| `loop-operator` vs `chief-of-staff` | loop-operator 管理自主 agent 循环；chief-of-staff 编排多任务工作流 |

### 对 sextant 开发：推荐选择

| 场景 | 用这个 | 别用那个 |
|------|--------|---------|
| 改完 Python 代码 | `python-reviewer` | `code-reviewer`（太泛） |
| 改完前端 HTML/JS | `code-reviewer` | `python-reviewer`（不对口） |
| 设计新功能架构 | `code-architect` | `architect`（太高层，不给具体文件） |
| 做重大技术选型 | `architect` | `code-architect`（太细节，不做技术选型） |
| 排查"agent 行为异常" | `silent-failure-hunter` | `code-reviewer`（不关注静默失败模式） |
| 删除无用代码 | `refactor-cleaner` | `code-simplifier`（不做死代码检测） |
| 代码太复杂难读 | `code-simplifier` | `refactor-cleaner`（不简化逻辑） |

---

## 七、注意事项

1. **Agent 覆盖关系**：ECC 安装在项目级 `.claude/`，同名的 agent/command/skill 会覆盖 Claude Code 内置版本。ECC 版本通常更详细（指定了 model、更完整的 instructions），这是升级而非冲突。

2. **Hook 性能开销**：ECC 的 hooks 在每次工具调用（PreToolUse）时启动 Node.js 脚本。在低配机器上可能有可感知的延迟。如果觉得慢，可在 `.claude/settings.local.json` 中禁用部分 hook。

2. **上下文预算**：108 个 skill 的描述会被加载到 system prompt，占用一定 token。如果发现上下文不够用，可以用 `/strategic-compact` 或手动 compaction 释放空间。

3. **无关 Agent/Command 占用命名空间**：虽然装了 63 个 agent 和 79 个命令，但只有你主动调用的才会执行。不相关的（如 `/flutter-build`、`/go-review`）忽略即可。

4. **与 sextant 自身配置的兼容**：ECC 的 `settings.json` 目前是空的 `{}`，不会覆盖 sextant 的现有配置。所有 ECC 文件在 `.claude/` 下的独立子目录中（`skills/ecc/`、`rules/ecc/` 等）。

5. **卸载**：如需卸载，删除 sextant 项目下的 `.claude/ecc/` 目录及相关文件即可。

---

## 八、速查表

### 最常用的 5 个命令

```
/python-review     ← 最常用，每次改 Python 必跑
/plan              ← 新功能第一步
/code-review       ← 前端改动或通用审查
/checkpoint        ← 阶段性保存
/pr                ← 准备提交
```

### 最常用的 5 个 Agent

```
python-reviewer      ← Python 代码审查
code-explorer        ← 理解代码库
silent-failure-hunter ← 追查异步/线程 bug
harness-optimizer    ← 优化 agent harness
code-architect       ← 新功能架构设计
```

### 最常用的 5 个 Skill（自动激活）

```
agent-architecture-audit    ← sextant 架构审计
agent-introspection-debugging ← agent 异常调试
python-patterns             ← Python 惯用模式
verification-loop           ← 验证改动生效
error-handling              ← 错误处理
```
