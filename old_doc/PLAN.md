# Sextant — 项目规划

> 项目代号：Sextant（六分仪）
> 
> 定位：**上下文治理优先的多 Agent 编码协作框架**
> 
> 一句话：你不写 prompt，你定义 Agent 的职责边界和协作规则。

---

## 一、为什么做

### 1.1 战略定位：「先获名，再获利」

当前副业四条线：

| 线路 | 性质 | 引流能力 |
|------|------|----------|
| acp | 技术深度名片 | ❌ 弱 — 赛道冷门（系统编程/C++/io_uring） |
| ncp | 技术广度名片 | ❌ 弱 — 运维/SRE 受众窄 |
| 小红书 | 自媒体获客 | ⚠️ 中等 — 需要内容素材 |
| **Sextant** | **引流引擎** | ✅ 强 — AI Coding 是 2026 最热话题，所有程序员都是受众 |

Sextant 的使命：**把流量带进来。** 每天用它写代码 → 每天有素材 → 小红书/博客持续输出 → 顺便把 acp/ncp 的人带过去。

### 1.2 主线串联

```
         acp / ncp                    Sextant
        (技术深度名片)            (引流引擎 + 日常工具)
              │                          │
              └────────┬─────────────────┘
                       ▼
              同一个编排框架核心
         （Agent 定义是可插拔的）
                       ▼
              今天是 Coding Agent
              明天是 Data Migration Agent
```

Sextant v0.1 只做 Coding Agent。架构上 Agent 定义做成可插拔的，将来接入 acp/ncp 的调度只需加 Agent 类型。

---

## 二、核心架构设计：重 Leader + 轻 Worker

### 2.1 设计原则

**现有工具的共性问题是"Agent 太重"。** 每个 Agent 都试图理解全局、自己做决策、自己执行——导致上下文爆炸、记忆污染、token 浪费。

**Sextant 的设计：Leader 是通用 Agent + 一个 spawn_worker 工具。**

```
┌─────────────────────────────────────────────┐
│              Leader Agent                    │
│  - 标准 Agent Loop（抄 Pi Agent / Helixent）  │
│  - 跟 Claude Code 一样：读代码、搜文件、       │
│    跑命令、写代码……                            │
│  - 多一个工具：spawn_worker(type, task_spec)  │
│  - LLM 自己决定什么时候用 spawn_worker、        │
│    什么时候自己干                               │
└──────┬──────────────┬──────────────┬──────────┘
       │ task_spec    │ task_spec    │ task_spec
       ▼              ▼              ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│  Coder   │   │ Reviewer │   │  Tester  │
│  (轻)    │   │  (轻)    │   │  (轻)    │
│  - 只收   │   │  - 只收   │   │  - 只收   │
│   任务规格 │   │   代码变更 │   │   编译产物 │
│  - 不看    │   │  - 不看    │   │  - 不看    │
│   全局上下文│   │   全局上下文│   │   全局上下文│
│           │   │           │   │           │
│  Loop:    │   │  Loop:    │   │  Loop:    │
│  Read →   │   │  Read →   │   │  Write →  │
│  Implement│   │  Analyze  │   │  Build →  │
│  → Build  │   │  → Report │   │  Run →    │
│           │   │           │   │  Report   │
└──────────┘   └──────────┘   └──────────┘
```

### 2.2 Leader Agent Loop（就是通用 Agent，不搞特殊）

Leader 不需要专门的"决策型 loop"。它就是标准 ReAct 循环：

```
while not done:
    response = LLM.generate(context)
    if response has tool_calls:
        execute tools (read_file, search_code, terminal, spawn_worker, ...)
        add results to context
    else:
        done → 回复用户
```

**跟 Claude Code 的唯一区别：多了一个 `spawn_worker` 工具。**

Leader 不需要被编程成"先分析、再规划、再委派"。它就是一个普通的 coding agent——它可以自己读代码、自己写代码、自己跑命令。当 LLM 判断"这个子任务适合交给专门的 Worker"时，它调用 `spawn_worker`。什么时候用、用哪个 Worker、怎么处理 Worker 的返回，全部由 LLM 自己决定。

**这意味着 Leader 的系统 prompt 只需要加一段：**

> You have a spawn_worker tool. Use it when a subtask would benefit from a dedicated agent with a specific loop (e.g., coder, reviewer, tester). Each worker receives a focused task_spec and runs independently. You decide when to delegate vs. do it yourself.

### 2.3 各 Worker 的 Agent Loop

**Worker 之间 loop 不同，因为它们做的事不同——但它们都是轻量的。**

#### Coder Loop（实现型——只到编译成功）

```
Receive task_spec
    │
    ▼
Read — 从 task_spec 中获取上下文（文件路径、相关代码片段）
    │
    ▼
Implement — 写代码
    │
    ▼
Build — 编译 / lint（不做测试）
    │
    ├─ 编译通过 → Report success + 变更摘要（触发 Tester）
    └─ 编译失败 → 看编译错误，尝试修复（最多 N 次）
         │
         ├─ 修复成功 → Report success
         └─ 超过重试 → Report failure + 编译错误
```

**Coder 不管测试。** 它的完成条件是"产物能编译"。测试交给 Tester。这个边界的意义：Coder 不需要知道测试框架的细节，它的世界只有语法和类型系统。

#### Reviewer Loop（审查型——它是"只读"的）

```
Receive diff + review_rules
    │
    ▼
Analyze — 逐文件审查代码变更
    │  检查项：
    │  - 逻辑正确性
    │  - 安全隐患（SQL注入、硬编码密钥、输入校验）
    │  - 代码风格 / 可读性
    │  - 与现有代码的一致性
    │
    ▼
Report — 结构化审查结果
    │  - 阻塞问题（必须改）
    │  - 建议（可改可不改）
    │  - 没问题
```

#### Tester Loop（验证型——从编译产物开始）

```
Receive task_spec（Coder 已编译通过 + 变更摘要）
    │
    ▼
Write — 生成测试代码（单元测试 / 集成测试）
    │
    ▼
Build — 编译测试代码（验证测试本身能编译）
    │
    ├─ 测试编译失败 → 修正测试代码，重试（最多 N 次）
    └─ 测试编译通过 →
         │
         ▼
    Run — 执行测试
         │
         ├─ 全部通过 → Report success + 覆盖率
         └─ 有失败 → 分析：是测试写错了还是被测代码有 bug
              │
              ├─ 测试写错 → 修正重试
              └─ 代码有 bug → Report failure（不回传代码给 Coder，由 Leader 决定下一步）
```

**Tester 在 Coder 之后执行。** Coder 输出"编译通过的产物"→ Tester 接管。Tester 不修改被测代码，只写测试和运行测试。如果发现代码 bug，它报告给 Leader，由 Leader 决定是让 Coder 修还是标记为已知问题。

### 2.4 为什么这个设计好

| 维度 | 传统单 Agent | Sextant 重 Leader + 轻 Worker |
|------|-------------|-------------------------------|
| **上下文污染** | 严重——所有历史都在一个窗口 | 隔离——Worker 只看 task_spec |
| **Token 消耗** | 高——上下文窗口越来越大 | 低——Worker 上下文固定且小 |
| **并行能力** | 无——单 Agent 串行 | 天然支持——多个 Worker 可并行 |
| **故障隔离** | 差——一处卡住全停 | 好——Worker 卡住 Leader 换人 |
| **可调试性** | 差——黑盒 | 好——每个 Worker 输入/输出都结构化 |
| **loop 定制** | 一种 loop 应对所有 | 每种角色有自己的 loop |

---

## 三、差异化定位（护城河）

### 3.1 竞争地图

```
全自动黑盒 ←―――――――― Sextant ―――――――――→ 单 Agent 对话
(Devin)              (你在这)              (Cursor/Claude Code)
```

| 类型 | 代表 | Sextant 的差异 |
|------|------|---------------|
| 全自动 | Devin、Codex CLI | Devin 不让你看它的决策过程。Sextant 每一步都可见、可干预 |
| 单 Agent | Cursor、Claude Code | 一个 Agent 干所有事，上下文爆炸。Sextant 职责分离，上下文隔离 |
| 多 Agent | CrewAI、AutoGen | 太重——每个 Agent 都是"完整的 AI"。Sextant 只有 Leader 是重的 |

### 3.2 护城河 = 设计主张，不是代码

别人能抄你的代码，抄不走你的**设计主张**：

1. **上下文治理优先** — 来自 nanobot 的 memory pollution 教训
2. **执行超时 + 降级** — 来自 DeerFlow ReAct 的生产环境教训  
3. **Agent 职责边界 > prompt 技巧** — 来自你自己的工程经验
4. **重 Leader + 轻 Worker** — 来自每天用 Agent 写代码的成本感受

这些不是"我看了篇论文"——是你真的踩过坑。

---

## 四、技术约束

- **LLM 后端**：OpenAI 兼容 API（公司内部 API + 可配置外部）
- **语言**：Python（与 nanobot 研究一致，生态最好）
- **配置格式**：TOML（`sextant.toml`）
- **输出**：结构化日志 + 终端 TUI
- **目标平台**：macOS / Linux（本地开发机）

---

## 五、v0.1 范围（最小可用）

### 包含
- [ ] `sextant.toml` 配置解析（Agent 定义 + 协作规则）
- [ ] Leader Agent — 任务分解 + 调度
- [ ] Coder Worker — 实现 + 自测 + 重试
- [ ] Reviewer Worker — 只读审查
- [ ] task_spec 协议 — Leader ↔ Worker 的交接格式
- [ ] OpenAI 兼容 API 适配层
- [ ] 结构化日志（NDJSON）

### 不包含（v0.2+）
- Tester Worker
- 并行 Worker 执行
- 多 LLM Provider 切换
- Web UI
- acp/ncp 调度集成

---

## 六、内容策略（小红书 + 技术博客）

### 核心叙事："我是踩过坑的人，所以我做了这个"

| 内容类型 | 标题示例 | 素材来源 |
|----------|---------|---------|
| 故事型 | 《用 AI 写代码半年，我踩了三个大坑》 | nanobot 分析 + 个人经验 |
| 对比型 | 《单 Agent vs 多 Agent：同一个任务两种方式》 | 自己跑对比实验 |
| 设计型 | 《为什么我的多 Agent 框架里 Leader 是重的、Worker 是轻的》 | Sextant 设计文档 |
| 实战型 | 《用 Sextant 给 acp 加了一个功能——过程实录》 | 日常开发 |
| 观点型 | 《context window 不是越大越好——上下文治理的工程视角》 | nanobot 教训 |

---

## 七、里程碑（按副业节奏，不设死线）

| 序号 | 里程碑 | 预估时间 | 产出 |
|------|--------|---------|------|
| M1 | sextant.toml 解析 + API 适配层 | 2-3 周 | 能连上 LLM |
| M2 | Coder Worker + task_spec 协议 | 2-3 周 | 单 Worker 能干活 |
| M3 | Leader Agent + 调度 | 2-3 周 | Leader 能拆任务 + 分派 |
| M4 | Reviewer Worker | 1-2 周 | 完整两角色协作 |
| M5 | 内部自用稳定 | 2 周 | 日常开发无重大问题 |
| M6 | 公开 GitHub + 第一篇内容 | — | 正式获名启动 |

---

## 八、关键判断记录

- 2026-05-20：确定方向——多 Agent Coding 团队，而非 acp/ncp 调度器（前者能引流，后者不能）
- 命名：Sextant（六分仪），替代"cp manager"等无创意的名字
- 核心设计：重 Leader + 轻 Worker，不同 Worker 不同 Agent Loop
- 定位：不是"又一个 AI Coding 工具"，是"上下文治理优先的多 Agent 协作框架"
- 策略：先获名（GitHub 开源 + 内容），再获利（以后再说）
