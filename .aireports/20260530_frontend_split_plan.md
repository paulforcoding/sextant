# 前端文件拆分重构计划

**日期**: 2026-05-30
**目标**: 将 1,825 行单文件 `index.html` 拆分为 HTML/CSS/JS 三个独立文件，不引入任何构建工具

---

## 一、现状分析

| 指标 | 数值 |
|------|------|
| 文件路径 | `src/sextant/web/templates/index.html` |
| 总行数 | **1,825 行** |
| 文件大小 | **60KB** |
| CSS（行 7-630） | 624 行 / 34% |
| HTML 结构（行 632-699） | 67 行 / 4% |
| JavaScript（行 700-1823） | 1,124 行 / 62% |
| 超出项目规范上限（800 行） | **2.3 倍** |
| JS 逻辑模块数 | 11 个分段 |
| 函数/处理器数量 | ~30 个 |

## 二、设计决策

### 决策 1：不引入构建工具

**理由**：sextant 是 Python CLI 工具，Web UI 是辅助管理界面。引入 Node/npm 构建链会增加安装复杂度、贡献者门槛和部署故障点，而带来的收益（打包优化、HMR、类型检查）在当前 1,124 行 JS 规模下几乎为零。

### 决策 2：拆分为 3 个文件，而非更细粒度

**理由**：
- `index.html`（~70 行）：HTML 结构
- `style.css`（~624 行）：所有样式
- `app.js`（~1,124 行）：所有 JavaScript

JS 不再细分为多个模块文件，原因：
- 使用普通 `<script src>` 加载（非 ES modules），多文件需要管理加载顺序
- 当前所有函数定义在全局作用域，依赖关系隐含但清晰
- 拆分 JS 收益有限（1,124 行在 IDE 中导航不成问题）
- 保持最小变更原则，降低引入 bug 的风险

**未来扩展**：如需进一步拆分 JS，可用 `<script type="module">` + ES import/export，浏览器原生支持，仍不需要构建工具。

### 决策 3：使用 Flask 原生 `static_folder` 配置

**理由**：Flask 自带静态文件服务能力，只需在 `Flask()` 初始化时指定 `static_folder`。无需额外依赖。

### 决策 4：保留所有 inline 事件处理器

**理由**：`onclick="showMailbox()"`、`onchange="updateThinkingSetting()"` 等 inline handler 依赖全局函数。外部 JS 文件中的函数声明仍是全局的，无需修改 HTML。

## 三、文件变更清单

| 文件 | 动作 | 内容 | 行数变化 |
|------|------|------|---------|
| `web/templates/index.html` | 缩减 | 仅保留 HTML 结构 + `<link>` + `<script src>` | 1,825 → ~75 |
| `web/static/style.css` | **新建** | 624 行 CSS（从 `<style>` 标签移出） | 0 → 624 |
| `web/static/app.js` | **新建** | 1,124 行 JS（从 `<script>` 标签移出） | 0 → 1,124 |
| `web_server.py` | 修改 | 添加 `static_folder` 配置；简化 template 加载 | 改 2 处 |

## 四、数据流不变

```
浏览器 → HTTP GET / → Flask index() → render_template_string(index.html)
                                          ↓ (HTML 中包含)
                                     <link href="/static/style.css">
                                     <script src="/static/app.js">
                                          ↓ (浏览器自动请求)
浏览器 → HTTP GET /static/style.css → Flask send_static_file → style.css
浏览器 → HTTP GET /static/app.js    → Flask send_static_file → app.js
```

Flask 的 `static_folder` 配置会自动注册 `/static/<path:filename>` 路由。

## 五、实测验证清单

- [ ] `sextant web` 正常启动
- [ ] 浏览器访问 `http://127.0.0.1:5008` 页面完整加载
- [ ] CSS 样式正确渲染（侧边栏、聊天区、消息气泡）
- [ ] JS 功能正常：Agent 列表加载、选择 Agent、发送消息
- [ ] SSE 流式渲染正常（text、thinking、tool_use、tool_result、done）
- [ ] Slash 命令正常（/help、/agents、/mcp、/context 等）
- [ ] Mailbox 功能正常（查看待处理消息、自动填入输入框）
- [ ] 设置面板正常（显示思考过程、权限模式切换）
- [ ] 输入历史（ArrowUp/ArrowDown 导航）
- [ ] curl 验证静态文件可访问（`curl http://127.0.0.1:5008/static/style.css`）
- [ ] 无浏览器控制台错误

## 六、回滚方案

如需回滚：`git revert` 单次提交，恢复到单文件架构。CSS 和 JS 内容一字不改，只是从独立文件合并回 `<style>` 和 `<script>` 标签。

---

## 七、更细粒度 JS 拆分（备用方案，本次不执行）

如果未来 JS 继续增长，可在不引入构建工具的前提下拆分为多个文件：

```
web/static/
├── app.js          # 主入口，加载顺序第一
├── state.js        # 全局状态声明
├── chat.js         # selectAgent, sendMessage, streamResponse, appendMessage
├── mailbox.js      # fetchMailboxDraft, showMailbox
├── commands.js     # 所有 slash command handlers
├── markdown.js     # renderMarkdown, esc, escHtml, formatToolInput
└── settings.js     # toggleSettings, updateThinkingSetting, applyPermMode
```

加载方式：
```html
<script src="/static/state.js"></script>
<script src="/static/helpers.js"></script>
<script src="/static/chat.js"></script>
...
```

或使用 ES modules（需将函数声明改为 export/import）：
```html
<script type="module" src="/static/app.js"></script>
```
