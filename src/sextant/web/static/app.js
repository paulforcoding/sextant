// ══════════════════════════════════════════════════════════════
// State
// ══════════════════════════════════════════════════════════════
let activeProject = null;
let activeView = null;        // 'chat' | 'mailbox'
let streamingAbort = null;
const chatCache = {};         // projectId → messages.innerHTML (preserved across switches)
let showThinking = true;      // settings: show LLM thinking blocks
let permMode = 'bypassPermissions';  // settings: permission mode
const shownMsgIds = {};        // projectId → Set of msg_ids already shown in textarea
let chatInputHistory = [];    // input history for up/down arrow navigation
let historyIndex = -1;        // current position in history (-1 = not navigating)
let historyDraft = '';        // saved draft before navigating history

// ══════════════════════════════════════════════════════════════
// Init
// ══════════════════════════════════════════════════════════════
async function init() {
  // Load saved settings
  try {
    const saved = localStorage.getItem('sextant_showThinking');
    if (saved !== null) {
      showThinking = saved === 'true';
      document.getElementById('toggle-thinking').checked = showThinking;
    }
    const savedPerm = localStorage.getItem('sextant_permMode');
    if (savedPerm) {
      permMode = savedPerm;
      document.getElementById('perm-mode-select').value = savedPerm;
    }
  } catch (_) {}

  try {
    const res = await fetch('/api/projects');
    const projects = await res.json();
    renderAgentList(projects);
    const footerText = document.querySelector('#sidebar-footer .status-text');
    if (footerText) {
      footerText.textContent = `${projects.length} agent${projects.length>1?'s':''} ready`;
    }
  } catch (e) {
    document.getElementById('agent-list').innerHTML =
      '<li class="sidebar-item" style="color:var(--error)">连接失败</li>';
  }
}

function renderAgentList(projects) {
  const list = document.getElementById('agent-list');
  list.innerHTML = projects.map(p => `
    <li class="sidebar-item" data-view="chat" data-project="${p.id}" onclick="selectAgent('${p.id}')">
      <span class="dot"></span>
      ${p.id}
      ${p.pending > 0 ? `<span class="badge">${p.pending}</span>` : ''}
    </li>
  `).join('');
}

// ══════════════════════════════════════════════════════════════
// Agent selection
// ══════════════════════════════════════════════════════════════
async function selectAgent(projectId) {
  // Abort any active stream
  if (streamingAbort) { streamingAbort.abort(); streamingAbort = null; }
  // Reset render batching state
  _renderScheduled = false; _renderMsg = null; _renderText = '';

  // Save current chat HTML to cache before switching away
  // (exclude ephemeral system bubbles — they are re-fetched on re-entry)
  if (activeProject && activeView === 'chat') {
    const msgs = document.getElementById('messages');
    if (msgs && msgs.children.length > 0) {
      const clone = msgs.cloneNode(true);
      clone.querySelectorAll('.msg.system').forEach(el => el.remove());
      if (clone.children.length > 0) {
        chatCache[activeProject] = clone.innerHTML;
      }
    }
  }

  activeProject = projectId;
  activeView = 'chat';

  // Highlight sidebar
  document.querySelectorAll('.sidebar-item').forEach(el => el.classList.remove('active'));
  document.querySelector(`[data-project="${projectId}"]`)?.classList.add('active');

  // Header
  document.getElementById('header-title').textContent = projectId;
  document.getElementById('header-status').textContent = '';

  // Apply saved permission mode to this agent
  applyPermMode(projectId);

  // Build chat UI
  const content = document.getElementById('content');
  content.innerHTML = `
    <div class="chat-area" id="messages"></div>
    <div class="input-area" id="input-row">
      <textarea id="prompt-input" rows="1"
        placeholder="输入消息..."></textarea>
      <button id="send-btn" onclick="sendMessage()">发送</button>
    </div>
  `;

  const container = document.getElementById('messages');

  // Check for pending mailbox messages (always, even with cache)
  await fetchMailboxDraft(projectId, container);

  // Restore from cache if we've visited this agent before
  if (chatCache[projectId]) {
    container.innerHTML = chatCache[projectId] + container.innerHTML;
    document.getElementById('header-status').textContent = '已恢复';
    scrollToBottom();
    // Silently refresh history to catch CLI-originated messages
    refreshHistory(projectId);
    return;
  }

  // First visit: load history from disk
  document.getElementById('header-status').textContent = '加载历史...';
  try {
    const res = await fetch(`/api/chat/${projectId}/history`);
    const msgs = await res.json();
    if (msgs.length === 0) {
      // Only show "新对话" if no pending messages were added
      if (!container.querySelector('.msg.system')) {
        container.innerHTML = '<div class="empty"><p>新对话 — 输入消息开始</p></div>';
      }
    } else {
      msgs.forEach(m => appendMessage(m.role, m.content));
    }
    document.getElementById('header-status').textContent =
      `${msgs.length} 条历史消息`;
  } catch (e) {
    document.getElementById('header-status').textContent = '加载失败';
  }

  scrollToBottom();
}

// ══════════════════════════════════════════════════════════════
// Mailbox draft display
// ══════════════════════════════════════════════════════════════
async function fetchMailboxDraft(projectId, container) {
  try {
    const res = await fetch(`/api/chat/${projectId}/pending`);
    const pending = await res.json();
    if (!Array.isArray(pending) || pending.length === 0) return;

    // Filter out messages already shown this session
    const seen = shownMsgIds[projectId] || new Set();
    const fresh = pending.filter(m => m.msg_id && !seen.has(m.msg_id));
    if (fresh.length === 0) return;

    // Track newly shown msg_ids
    if (!shownMsgIds[projectId]) shownMsgIds[projectId] = new Set();
    fresh.forEach(m => { if (m.msg_id) shownMsgIds[projectId].add(m.msg_id); });

    // Build formatted message text (same format as server-side _build_full_prompt)
    const msgs = fresh.map(m => `[来自 ${m.from}] ${m.subject}\n\n${m.body}`);
    const formatted = msgs.join('\n\n');

    // Show system bubble
    const div = document.createElement('div');
    div.className = 'msg system';
    div.innerHTML = `<div class="role-label">📬 Mailbox</div>
      <div class="msg-content">你有 <b>${fresh.length}</b> 条待处理消息，已填入输入框，可直接编辑发送：
        ${fresh.map((m, i) => `
          <div class="draft-card">
            <div class="draft-card-header">${i + 1}. 来自 <b>${esc(m.from)}</b> · ${esc(m.subject)}</div>
            <div class="draft-card-body">${esc(m.body)}</div>
          </div>
        `).join('')}
      </div>`;
    container.prepend(div);

    // Pre-fill textarea with formatted messages
    const input = document.getElementById('prompt-input');
    if (input) {
      input.value = formatted;
      // Trigger auto-resize
      input.style.height = 'auto';
      input.style.height = (input.scrollHeight) + 'px';
    }

    // Mark messages as delivered so they won't reappear on next visit
    const ids = fresh.map(m => m.msg_id).filter(Boolean);
    if (ids.length > 0) {
      fetch(`/api/chat/${projectId}/consume-pending`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({msg_ids: ids}),
      }).catch(() => {});
    }
  } catch (_) {}
}

// ══════════════════════════════════════════════════════════════
// Background history refresh (catches CLI-originated messages)
// ══════════════════════════════════════════════════════════════
async function refreshHistory(projectId) {
  try {
    const res = await fetch(`/api/chat/${projectId}/history`);
    const msgs = await res.json();
    if (!Array.isArray(msgs) || msgs.length === 0) return;

    // Only update cache if API returns MORE messages than currently cached.
    // Otherwise we'd lose web-session messages not yet persisted to JSONL.
    const cached = chatCache[projectId] || '';
    const cachedMsgCount = (cached.match(/class="msg /g) || []).length;
    if (msgs.length <= cachedMsgCount) return;

    // Rebuild cache HTML from history data
    const tmp = document.createElement('div');
    msgs.forEach(m => {
      const div = document.createElement('div');
      div.className = `msg ${m.role}`;
      div.innerHTML = m.role === 'user'
        ? `<div class="role-label">YOU</div><div class="msg-content">${esc(m.content)}</div>`
        : `<div class="role-label">${esc(projectId)}</div><div class="msg-content">${esc(m.content)}</div>`;
      tmp.appendChild(div);
    });
    chatCache[projectId] = tmp.innerHTML;
  } catch (_) {}
}

// ══════════════════════════════════════════════════════════════
// Slash command dispatcher
// ══════════════════════════════════════════════════════════════
async function dispatchSlashCommand(prompt) {
  const spaceIdx = prompt.indexOf(' ');
  const cmd = spaceIdx > 0 ? prompt.slice(0, spaceIdx) : prompt;

  switch (cmd) {
    case '/help':
      handleHelp();
      break;
    case '/agents':
      await handleAgents();
      break;
    case '/mcp':
      await handleMcp();
      break;
    case '/context':
      await handleContext(prompt);
      break;
    case '/usage':
    case '/cost':
      await handleUsage();
      break;
    case '/info':
      await handleInfo();
      break;
    case '/rename':
      await handleRename(prompt);
      break;
    case '/fork':
    case '/branch':
      await handleFork();
      break;
    case '/plan':
      await handlePerm('plan');
      break;
    case '/perm':
      await handlePermCmd(prompt);
      break;
    case '/model':
      await handleModel(prompt);
      break;
    case '/status':
      await handleStatus();
      break;
    case '/clear':
      handleClear();
      break;
    case '/compact':
      // Pass through to agent — CC CLI intercepts this
      sendToAgent(prompt);
      break;
    case '/skills':
      // Pass through to agent — CC SDK handles skill discovery
      sendToAgent(prompt);
      break;
    default:
      appendSystem(`未知命令: ${cmd}

可用命令: /help, /agents, /mcp, /context, /usage, /info, /rename, /fork, /plan, /perm, /model, /status, /clear, /compact, /skills`);
  }
}

// ══════════════════════════════════════════════════════════════
// Send message
// ══════════════════════════════════════════════════════════════
async function sendMessage() {
  if (!activeProject) return;

  const input = document.getElementById('prompt-input');
  const btn = document.getElementById('send-btn');
  const prompt = input.value.trim();
  if (!prompt) return;

  // ── Slash commands ──
  if (prompt.startsWith('/')) {
    input.value = '';
    input.style.height = 'auto';
    appendMessage('user', prompt);
    await dispatchSlashCommand(prompt);
    return;
  }

  // Save to input history (before clearing)
  chatInputHistory.push({project: activeProject, text: prompt});
  historyIndex = -1;
  historyDraft = '';

  // Clear input
  input.value = '';
  input.style.height = 'auto';
  btn.disabled = true;

  // Append user message
  appendMessage('user', prompt);
  scrollToBottom();

  // Stream response
  await streamResponse(prompt, btn);
}

// Shared SSE streaming — used by both normal messages and passthrough commands.
async function streamResponse(prompt, btn) {
  // Clear shown msg tracking for this project (messages will be delivered server-side)
  delete shownMsgIds[activeProject];

  // Reset render state for new stream
  _renderScheduled = false;
  _renderMsg = null;
  _renderText = '';

  streamingAbort = new AbortController();
  document.getElementById('header-status').innerHTML =
    '<span class="streaming-indicator"></span>处理中...';

  try {
    await fetch(`/api/chat/${activeProject}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt}),
    });

    const res = await fetch(`/api/chat/${activeProject}/stream`, {
      signal: streamingAbort.signal,
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let agentMsg = null;
    let agentText = '';
    let cost = null;

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));

          switch (data.type) {
            case 'text':
              if (!agentMsg) {
                agentMsg = appendMessage('agent', '');
              }
              agentText += data.content;
              scheduleRender(agentMsg, agentText);
              break;

            case 'thinking':
              if (showThinking) {
                appendMessage('thinking', data.content);
              }
              break;

            case 'tool_use':
              appendMessage('tool', null, {
                name: data.name,
                input: data.input,
              });
              break;

            case 'tool_result':
              appendMessage('tool-result', data.content, {
                is_error: data.is_error,
              });
              break;

            case 'server_tool':
              appendMessage('tool', `🔧 ${data.name}`, {
                name: data.name,
                input: data.input,
              });
              break;

            case 'server_tool_result':
              appendMessage('tool-result', JSON.stringify(data.content).slice(0, 500));
              break;

            case 'done':
              cost = data.cost;
              // Flush any pending render before marking done
              if (_renderScheduled && _renderMsg) {
                _renderMsg.querySelector('.msg-content').innerHTML = renderMarkdown(_renderText);
                _renderScheduled = false;
                _renderMsg = null;
                _renderText = '';
              }
              document.getElementById('header-status').textContent =
                cost != null
                  ? `完成 · $${cost.toFixed(4)} · ${data.elapsed}s`
                  : `完成 · ${data.elapsed}s`;
              if (cost != null) {
                appendCost(cost, data.elapsed);
              }
              break;

            case 'error':
              appendMessage('agent', `❌ ${data.message}`);
              document.getElementById('header-status').textContent = '错误';
              break;
          }
        } catch (_) {}
      }
      scrollToBottom();
    }
  } catch (e) {
    if (e.name !== 'AbortError') {
      appendMessage('agent', `❌ 连接错误: ${e.message}`);
      document.getElementById('header-status').textContent = '连接错误';
    }
  } finally {
    btn.disabled = false;
    streamingAbort = null;
    document.getElementById('prompt-input')?.focus();
  }
}

// ══════════════════════════════════════════════════════════════
// Batched markdown rendering (rAF-throttled to prevent layout storms)
// ══════════════════════════════════════════════════════════════
let _renderScheduled = false;
let _renderMsg = null;
let _renderText = '';

function scheduleRender(msgEl, fullText) {
  _renderMsg = msgEl;
  _renderText = fullText;
  if (!_renderScheduled) {
    _renderScheduled = true;
    requestAnimationFrame(() => {
      _renderScheduled = false;
      if (_renderMsg) {
        _renderMsg.querySelector('.msg-content').innerHTML = renderMarkdown(_renderText);
        _renderMsg = null;
        _renderText = '';
      }
      scrollToBottom();
    });
  }
}

// ══════════════════════════════════════════════════════════════
// Append message to chat
// ══════════════════════════════════════════════════════════════
function appendMessage(type, content, extra) {
  const container = document.getElementById('messages');
  if (!container) return null;

  // Remove empty state
  const empty = container.querySelector('.empty');
  if (empty) empty.remove();

  const div = document.createElement('div');
  div.className = `msg ${type}`;

  switch (type) {
    case 'user':
      div.innerHTML = `<div class="role-label">YOU</div><div class="msg-content">${esc(content)}</div>`;
      break;
    case 'agent':
      div.innerHTML = `<div class="role-label">${activeProject||'agent'}</div><div class="msg-content">${content ? renderMarkdown(content) : ''}</div>`;
      break;
    case 'thinking':
      if (!showThinking) return null;
      div.innerHTML = `💭 ${esc(content)}`;
      break;
    case 'tool':
      const cmdLine = extra?.name === 'Bash' && extra?.input?.command
        ? extra.input.command
        : extra?.name === 'send_message'
        ? `📬 → ${extra?.input?.to}: ${extra?.input?.subject}`
        : formatToolInput(extra?.input);
      div.innerHTML = `
        <div class="tool-name">⚙ ${extra?.name || 'tool'}</div>
        ${cmdLine ? `<div class="tool-detail">${esc(cmdLine)}</div>` : ''}
      `;
      break;
    case 'tool-result':
      div.classList.add(type);
      if (extra?.is_error) div.classList.add('error');
      div.innerHTML = `<span>${extra?.is_error ? '❌' : '✓'} ${esc(String(content).slice(0, 300))}</span>`;
      break;
  }

  container.appendChild(div);
  return div;
}

function appendCost(cost, elapsed) {
  const container = document.getElementById('messages');
  if (!container) return;
  const div = document.createElement('div');
  div.className = 'cost-bar';
  div.textContent = `$${cost.toFixed(4)} · ${elapsed}s`;
  container.appendChild(div);
}

// ══════════════════════════════════════════════════════════════
// Mailbox view
// ══════════════════════════════════════════════════════════════
async function showMailbox() {
  if (streamingAbort) { streamingAbort.abort(); streamingAbort = null; }
  _renderScheduled = false; _renderMsg = null; _renderText = '';

  activeProject = null;
  activeView = 'mailbox';

  document.querySelectorAll('.sidebar-item').forEach(el => el.classList.remove('active'));
  document.querySelector('[data-view="mailbox"]')?.classList.add('active');

  document.getElementById('header-title').textContent = 'Mailbox';
  document.getElementById('header-status').textContent = '加载中...';

  const content = document.getElementById('content');
  content.innerHTML = '<div class="mailbox-view" id="mailbox-list">加载中...</div>';

  try {
    const res = await fetch('/api/mailbox');
    const entries = await res.json();
    const list = document.getElementById('mailbox-list');

    if (entries.length === 0) {
      list.innerHTML = '<div class="empty"><div class="icon">📭</div><h3>暂无消息</h3></div>';
    } else {
      list.innerHTML = entries.map(e => `
        <div class="mailbox-card">
          <div class="mb-header">
            <span class="mb-from-to">${esc(e.from)} <span class="mb-arrow">→</span> ${esc(e.to)}</span>
            <span class="mb-time">${fmtTime(e.timestamp)}</span>
          </div>
          <div class="mb-subject">${esc(e.subject)}</div>
          <div class="mb-body">${esc(e.body)}</div>
          <div style="margin-top:8px">
            <span class="mb-status ${e.status||'pending'}">${e.status||'pending'}</span>
            ${e.reply ? `<div style="margin-top:8px;font-size:13px;color:var(--text-dim)">↩ ${esc(e.reply).slice(0, 200)}</div>` : ''}
          </div>
        </div>
      `).join('');
    }
    document.getElementById('header-status').textContent = `${entries.length} 条消息`;
  } catch (e) {
    document.getElementById('mailbox-list').innerHTML = `<div class="empty"><p>加载失败: ${e.message}</p></div>`;
  }
}

// ══════════════════════════════════════════════════════════════
// Slash command handlers
// ══════════════════════════════════════════════════════════════

async function handleAgents() {
  try {
    const res = await fetch('/api/agents');
    const data = await res.json();
    const agents = data.agents || [];

    if (agents.length === 0) {
      appendSystem('没有配置任何 Agent。');
      return;
    }

    let html = `<table style="width:100%;border-collapse:collapse;font-size:13px">
      <tr style="color:var(--text-dim);border-bottom:1px solid var(--border)">
        <th style="text-align:left;padding:6px 8px">ID</th>
        <th style="text-align:left;padding:6px 8px">Directory</th>
        <th style="text-align:left;padding:6px 8px">Session</th>
        <th style="text-align:center;padding:6px 8px">状态</th>
      </tr>`;

    for (const a of agents) {
      const session = a.session_id
        ? `<span style="font-family:monospace;font-size:11px">${a.session_id.slice(0, 12)}...</span>`
        : (a.continue ? '<span style="color:var(--text-dim)">latest</span>'
                       : '<span style="color:var(--text-dim)">new each</span>');
      const status = a.ready
        ? '<span style="color:var(--success)">● ready</span>'
        : '<span style="color:var(--error)">○ starting</span>';

      html += `<tr style="border-bottom:1px solid rgba(37,37,58,0.5)">
        <td style="padding:6px 8px;font-weight:600;color:#fff">${esc(a.id)}</td>
        <td style="padding:6px 8px;color:var(--text-dim);font-family:monospace;font-size:12px">${esc(a.directory)}</td>
        <td style="padding:6px 8px">${session}</td>
        <td style="padding:6px 8px;text-align:center">${status}</td>
      </tr>`;
    }
    html += '</table>';
    html += `<div style="margin-top:8px;font-size:12px;color:var(--text-dim)">共 ${agents.length} 个 Agent</div>`;

    appendSystem(html, true);
  } catch (e) {
    appendSystem(`❌ 获取 Agent 列表失败: ${e.message}`);
  }
}

async function handleMcp() {
  if (!activeProject) {
    appendSystem('请先选择一个 Agent。');
    return;
  }

  try {
    const res = await fetch(`/api/chat/${activeProject}/mcp`);
    if (!res.ok) {
      appendSystem(`❌ ${res.status}: ${(await res.json()).error || '未知错误'}`);
      return;
    }
    const data = await res.json();
    const servers = data.servers || [];

    if (servers.length === 0) {
      appendSystem('没有配置任何 MCP 服务器。');
      return;
    }

    let html = '';
    for (const srv of servers) {
      const statusIcon = srv.status === 'connected'
        ? '<span style="color:var(--success)">●</span>'
        : srv.status === 'starting'
        ? '<span style="color:#facc15">○</span>'
        : '<span style="color:var(--text-dim)">○</span>';

      html += `<div style="margin-bottom:16px;padding:12px;background:var(--card);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          ${statusIcon}
          <span style="font-weight:600;color:#fff;font-size:14px">${esc(srv.name)}</span>
          <span style="font-size:11px;color:var(--text-dim);margin-left:auto">${esc(srv.source)}</span>
        </div>`;

      if (srv.command) {
        html += `<div style="font-family:monospace;font-size:12px;color:var(--text-dim);margin-bottom:6px">
          $ ${esc(srv.command)} ${(srv.args || []).map(esc).join(' ')}
        </div>`;
      }

      const tools = srv.tools || [];
      html += `<div style="font-size:12px;color:var(--text-dim);margin-bottom:4px">${tools.length} tool(s):</div>`;
      for (const t of tools) {
        html += `<div style="font-size:13px;padding:4px 8px;margin:2px 0;background:var(--tool-bg);border-radius:4px">
          <code style="color:var(--accent)">${esc(t.name)}</code>`;
        if (t.description) {
          html += ` <span style="color:var(--text-dim)">— ${esc(t.description)}</span>`;
        }
        if (t.parameters && t.parameters.length > 0) {
          html += ` <span style="color:var(--thinking);font-size:11px">(${esc(t.parameters.join(', '))})</span>`;
        }
        html += '</div>';
      }
      html += '</div>';
    }

    html += `<div style="font-size:12px;color:var(--text-dim);margin-top:4px">
      共 ${data.total_servers} 个服务器，${data.total_tools} 个工具
    </div>`;

    appendSystem(html, true);
  } catch (e) {
    appendSystem(`❌ 获取 MCP 信息失败: ${e.message}`);
  }
}

function handleHelp() {
  appendSystem(`<div style="line-height:1.8">
<b style="color:#fff">可用命令</b><br><br>
<b>/help</b> — 显示帮助<br>
<b>/agents</b> — 列出所有 Agent<br>
<b>/mcp</b> — 列出 MCP 服务器与工具<br>
<b>/context [all]</b> — 上下文窗口用量<br>
<b>/usage</b> — 费用/用量统计<br>
<b>/info</b> — 当前 session 信息<br>
<b>/rename &lt;标题&gt;</b> — 重命名当前会话<br>
<b>/fork</b> — 分支当前会话<br>
<b>/plan</b> — 进入 Plan 模式<br>
<b>/perm &lt;模式&gt;</b> — 切换权限模式<br>
<b>/model &lt;名称&gt;</b> — 切换模型<br>
<b>/status</b> — 各项目 mailbox 状态<br>
<b>/clear</b> — 清屏<br>
<b>/compact [焦点]</b> — 压缩对话<br>
<b>/skills</b> — 列出可用技能
</div>`, true);
}

// ── /context ──
async function handleContext(prompt) {
  if (!activeProject) { appendSystem('请先选择一个 Agent。'); return; }
  const showAll = prompt.includes(' all');
  try {
    const res = await fetch(`/api/chat/${activeProject}/context${showAll ? '?all=true' : ''}`);
    const data = await res.json();
    if (data.error) { appendSystem(`❌ ${data.error}`); return; }

    const pct = data.percentage || 0;
    const bar = progressBar(pct);
    let html = `<div>${bar} <b style="color:#fff">${pct.toFixed(0)}%</b> ${(data.totalTokens||0).toLocaleString()} / ${(data.maxTokens||0).toLocaleString()} tokens</div>`;
    html += `<div style="font-size:12px;color:var(--text-dim);margin-top:4px">模型: ${data.model||'?'} · 自动压缩: ${data.isAutoCompactEnabled ? '✓' : '✗'}</div>`;

    const cats = (data.categories || []).sort((a,b) => b.tokens - a.tokens);
    if (cats.length) {
      html += '<table style="width:100%;margin-top:8px;font-size:13px">';
      for (const c of cats) {
        if (c.tokens > 0) {
          const cpct = (c.tokens / Math.max(data.totalTokens, 1) * 100).toFixed(1);
          html += `<tr><td style="padding:2px 4px;color:var(--text-dim)">${esc(c.name)}</td><td style="padding:2px 4px;text-align:right">${c.tokens.toLocaleString()}</td><td style="padding:2px 4px;text-align:right;color:var(--text-dim)">${cpct}%</td></tr>`;
        }
      }
      html += '</table>';
    }
    appendSystem(html, true);
  } catch (e) {
    appendSystem(`❌ ${e.message}`);
  }
}

// ── /usage ──
async function handleUsage() {
  if (!activeProject) { appendSystem('请先选择一个 Agent。'); return; }
  try {
    const res = await fetch(`/api/chat/${activeProject}/usage`);
    const data = await res.json();
    if (data.error) { appendSystem(`❌ ${data.error}`); return; }
    let html = `<div><b style="color:#fff">${esc(data.project)}</b></div>`;
    html += `<div style="margin-top:4px">累计费用: <b style="color:var(--accent)">$${data.total_cost.toFixed(6)}</b></div>`;
    if (data.last_cost != null) {
      html += `<div>最近调用: $${data.last_cost.toFixed(6)}</div>`;
    }
    if (data.context_pct != null) {
      const bar = progressBar(data.context_pct);
      html += `<div style="margin-top:4px">上下文: ${bar} ${data.context_pct.toFixed(0)}% ${(data.context_tokens||0).toLocaleString()} / ${(data.context_max||0).toLocaleString()}</div>`;
    }
    appendSystem(html, true);
  } catch (e) { appendSystem(`❌ ${e.message}`); }
}

// ── /info ──
async function handleInfo() {
  if (!activeProject) { appendSystem('请先选择一个 Agent。'); return; }
  try {
    const res = await fetch(`/api/chat/${activeProject}/info`);
    const data = await res.json();
    if (data.error) { appendSystem(`❌ ${data.error}`); return; }
    let html = `<div><b style="color:#fff">${esc(data.project)}</b></div>`;
    html += `<div style="font-size:13px;margin-top:4px">PID: ${data.pid}</div>`;
    html += `<div style="font-size:13px">CWD: <code>${esc(data.cwd)}</code></div>`;
    if (data.session_id) {
      html += `<div style="font-size:13px">Session: <code style="font-size:11px">${esc(data.session_id)}</code></div>`;
    }
    appendSystem(html, true);
  } catch (e) { appendSystem(`❌ ${e.message}`); }
}

// ── /rename ──
async function handleRename(prompt) {
  if (!activeProject) { appendSystem('请先选择一个 Agent。'); return; }
  const title = prompt.replace(/^\/rename\s*/, '').trim();
  if (!title) { appendSystem('用法: /rename &lt;新标题&gt;'); return; }
  try {
    const res = await fetch(`/api/chat/${activeProject}/rename`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title}),
    });
    const data = await res.json();
    if (data.error) { appendSystem(`❌ ${data.error}`); return; }
    appendSystem(`✅ 会话重命名为: <b style="color:#fff">${esc(data.title)}</b>`);
  } catch (e) { appendSystem(`❌ ${e.message}`); }
}

// ── /fork ──
async function handleFork() {
  if (!activeProject) { appendSystem('请先选择一个 Agent。'); return; }
  try {
    const res = await fetch(`/api/chat/${activeProject}/fork`, {method: 'POST'});
    const data = await res.json();
    if (data.error) { appendSystem(`❌ ${data.error}`); return; }
    let html = `<div>✅ 会话已分支</div>`;
    html += `<div style="font-size:12px;color:var(--text-dim);margin-top:4px">原: <code>${esc(data.original_session)}</code></div>`;
    html += `<div style="font-size:12px;color:var(--text-dim)">新: <code>${esc(data.new_session)}</code></div>`;
    html += `<div style="font-size:12px;color:var(--thinking);margin-top:4px">用 <code>sextant chat ${esc(activeProject)} --resume ${esc(data.new_session.slice(0,12))}...</code> 进入</div>`;
    appendSystem(html, true);
  } catch (e) { appendSystem(`❌ ${e.message}`); }
}

// ── /plan (alias for /perm plan) ──
async function handlePerm(mode) {
  if (!activeProject) { appendSystem('请先选择一个 Agent。'); return; }
  try {
    const res = await fetch(`/api/chat/${activeProject}/perm`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode}),
    });
    const data = await res.json();
    if (data.error) { appendSystem(`❌ ${data.error}`); return; }
    appendSystem(`✅ 权限模式 → <b style="color:var(--accent)">${esc(data.mode)}</b>`);
  } catch (e) { appendSystem(`❌ ${e.message}`); }
}

// ── /perm <mode> ──
async function handlePermCmd(prompt) {
  const mode = prompt.replace(/^\/perm\s*/, '').trim();
  if (!mode) { appendSystem('用法: /perm &lt;default|acceptEdits|bypassPermissions|plan&gt;'); return; }
  await handlePerm(mode);
}

// ── /model ──
async function handleModel(prompt) {
  if (!activeProject) { appendSystem('请先选择一个 Agent。'); return; }
  const model = prompt.replace(/^\/model\s*/, '').trim();
  if (!model) { appendSystem('用法: /model &lt;模型名&gt;'); return; }
  try {
    const res = await fetch(`/api/chat/${activeProject}/model`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model}),
    });
    const data = await res.json();
    if (data.error) { appendSystem(`❌ ${data.error}`); return; }
    appendSystem(`✅ 模型 → <b style="color:var(--accent)">${esc(data.model)}</b>`);
  } catch (e) { appendSystem(`❌ ${e.message}`); }
}

// ── /status ──
async function handleStatus() {
  try {
    const res = await fetch('/api/projects');
    const projects = await res.json();
    let html = '<table style="width:100%;font-size:13px"><tr style="color:var(--text-dim)"><th style="text-align:left;padding:4px 8px">项目</th><th style="text-align:right;padding:4px 8px">待处理</th></tr>';
    for (const p of projects) {
      html += `<tr><td style="padding:4px 8px;font-weight:600;color:#fff">${esc(p.id)}</td><td style="text-align:right;padding:4px 8px;color:${p.pending>0?'var(--accent)':'var(--text-dim)'}">${p.pending}</td></tr>`;
    }
    html += '</table>';
    appendSystem(html, true);
  } catch (e) { appendSystem(`❌ ${e.message}`); }
}

// ── /clear ──
function handleClear() {
  const container = document.getElementById('messages');
  if (container) container.innerHTML = '';
}

// ── Send slash command through to agent (for /compact and /skills) ──
async function sendToAgent(prompt) {
  const btn = document.getElementById('send-btn');
  btn.disabled = true;
  await streamResponse(prompt, btn);
}

// ── Progress bar helper ──
function progressBar(pct, width = 20) {
  const filled = Math.round(pct / 100 * width);
  const empty = width - filled;
  const color = pct > 90 ? '#f87171' : pct > 70 ? '#facc15' : '#4ade80';
  return `<span style="font-family:monospace;color:${color}">${'█'.repeat(filled)}${'░'.repeat(empty)}</span>`;
}

function appendSystem(content, isHtml = false) {
  const container = document.getElementById('messages');
  if (!container) return;
  const empty = container.querySelector('.empty');
  if (empty) empty.remove();

  const div = document.createElement('div');
  div.className = 'msg system';
  div.style.cssText = 'align-self:flex-start;background:var(--tool-bg);'
    + 'border:1px solid rgba(124,140,248,0.3);padding:12px 16px;'
    + 'border-radius:var(--radius);max-width:100%;font-size:13px';
  if (isHtml) {
    div.innerHTML = content;
  } else {
    div.innerHTML = esc(content);
  }
  container.appendChild(div);
  scrollToBottom();
  return div;
}

// ══════════════════════════════════════════════════════════════
// Settings
// ══════════════════════════════════════════════════════════════
function toggleSettings() {
  const popup = document.getElementById('settings-popup');
  popup.classList.toggle('visible');
}

function updateThinkingSetting() {
  showThinking = document.getElementById('toggle-thinking').checked;
  try {
    localStorage.setItem('sextant_showThinking', String(showThinking));
  } catch (_) {}
}

function updatePermSetting() {
  permMode = document.getElementById('perm-mode-select').value;
  try {
    localStorage.setItem('sextant_permMode', permMode);
  } catch (_) {}
  if (activeProject) applyPermMode(activeProject);
}

async function applyPermMode(projectId) {
  // bypassPermissions can only be set at boot — skip runtime call
  if (permMode === 'bypassPermissions') return;
  try {
    await fetch(`/api/chat/${projectId}/perm`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode: permMode}),
    });
  } catch (_) { /* silent */ }
}

// Close popup when clicking outside
document.addEventListener('click', (e) => {
  const popup = document.getElementById('settings-popup');
  if (!popup || !popup.classList.contains('visible')) return;
  const btn = document.querySelector('.settings-btn');
  if (!popup.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
    popup.classList.remove('visible');
  }
});

// ══════════════════════════════════════════════════════════════
// Helpers
// ══════════════════════════════════════════════════════════════
function esc(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>');
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderMarkdown(text) {
  if (!text) return '';
  // Protect fenced code blocks first (may contain HTML-like chars)
  const codeBlocks = [];
  let html = text.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    codeBlocks.push(`<pre><code>${escHtml(code)}</code></pre>`);
    return `\0C${codeBlocks.length - 1}\0`;
  });
  // Escape HTML in remaining text
  html = escHtml(html);
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Headers
  html = html.replace(/^#### (.+)$/gm, '<h5>$1</h5>');
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  // Horizontal rules
  html = html.replace(/^---$/gm, '<hr>');
  // Unordered lists
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  // Ordered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  // Blockquotes
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  // Double newlines → paragraph breaks
  html = html.replace(/\n\n+/g, '</p><p>');
  // Single newlines → <br>
  html = html.replace(/\n/g, '<br>');
  // Wrap
  html = '<p>' + html + '</p>';
  // Group consecutive <li> into <ul>
  html = html.replace(/((?:<li>.*?<\/li>)+)/g, '<ul>$1</ul>');
  // Group consecutive <blockquote>
  html = html.replace(/((?:<blockquote>.*?<\/blockquote>)+)/g, '<div class="md-blockquote">$1</div>');
  // Clean empty paragraphs
  html = html.replace(/<p><\/p>/g, '');
  // Restore code blocks
  html = html.replace(/\0C(\d+)\0/g, (_, i) => codeBlocks[parseInt(i)]);
  return html;
}

function formatToolInput(input) {
  if (!input || typeof input !== 'object') return '';
  if (Object.keys(input).length === 0) return '';
  // Single key with string value — show it directly
  const keys = Object.keys(input);
  if (keys.length === 1 && typeof input[keys[0]] === 'string') {
    return `${keys[0]}: ${input[keys[0]]}`;
  }
  // Multiple keys or non-string values — compact JSON
  try {
    const s = JSON.stringify(input);
    return s.length > 300 ? s.slice(0, 297) + '...' : s;
  } catch (_) { return ''; }
}

function fmtTime(ts) {
  if (!ts) return '';
  return ts.replace('T', ' ').split('+')[0].split('.')[0];
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    const area = document.getElementById('messages');
    if (area) area.scrollTop = area.scrollHeight;
  });
}

// Auto-resize textarea + Enter to send + arrow key history
document.addEventListener('keydown', (e) => {
  if (e.target.id !== 'prompt-input') return;

  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sendMessage();
    return;
  }

  if (e.key === 'ArrowUp') {
    e.preventDefault();
    // Save current draft before navigating
    const input = e.target;
    if (historyIndex === -1) {
      historyDraft = input.value;
      // Find the most recent entry for this project
      historyIndex = chatInputHistory.length - 1;
      while (historyIndex >= 0 && chatInputHistory[historyIndex].project !== activeProject) {
        historyIndex--;
      }
    } else if (historyIndex > 0) {
      // Find previous entry for this project
      let idx = historyIndex - 1;
      while (idx >= 0 && chatInputHistory[idx].project !== activeProject) {
        idx--;
      }
      if (idx >= 0) historyIndex = idx;
    }
    if (historyIndex >= 0) {
      input.value = chatInputHistory[historyIndex].text;
    }
    return;
  }

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (historyIndex === -1) return;
    const input = e.target;
    // Find next entry for this project
    let idx = historyIndex + 1;
    while (idx < chatInputHistory.length && chatInputHistory[idx].project !== activeProject) {
      idx++;
    }
    if (idx < chatInputHistory.length) {
      historyIndex = idx;
      input.value = chatInputHistory[historyIndex].text;
    } else {
      // Past the end — restore draft
      historyIndex = -1;
      input.value = historyDraft;
      historyDraft = '';
    }
    return;
  }

  // Reset history navigation on any other key
  if (historyIndex !== -1) {
    historyIndex = -1;
    historyDraft = '';
  }
});
// Auto-resize textarea
document.addEventListener('input', (e) => {
  if (e.target.id === 'prompt-input') {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  }
});

// ══════════════════════════════════════════════════════════════
// Periodic refresh of agent list (pending counts)
// ══════════════════════════════════════════════════════════════
setInterval(async () => {
  try {
    const res = await fetch('/api/projects');
    const projects = await res.json();
    renderAgentList(projects);
    // Keep active highlight
    if (activeProject) {
      document.querySelector(`[data-project="${activeProject}"]`)?.classList.add('active');
    }
    if (activeView === 'mailbox') {
      document.querySelector('[data-view="mailbox"]')?.classList.add('active');
    }
  } catch (_) {}
}, 5000);

// Start
init();
