"""P0/P1 — Slash command handling (UF-20~UF-36).

Tests cover: /help, /agents, /context, /usage, /info, /rename, /fork,
/plan, /perm, /model, /status, /clear, /mcp, unknown command.
"""

from __future__ import annotations


def _select_agent_and_wait(page, base_url, agent_id="acp"):
    """Helper: load page, select an agent, wait for chat UI."""
    page.goto(base_url)
    page.wait_for_selector(f'.sidebar-item[data-project="{agent_id}"]', timeout=5000)
    page.locator(f'.sidebar-item[data-project="{agent_id}"]').click()
    page.wait_for_selector('#prompt-input', timeout=5000)


def _send_slash_command(page, command):
    """Helper: type a slash command and send it."""
    page.locator('#prompt-input').fill(command)
    page.locator('#send-btn').click()
    page.wait_for_timeout(500)


def test_help_shows_command_list(page, base_url):
    """UF-20: /help displays available commands."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/help')

    # System bubble should appear with help text
    content = page.locator('#messages').text_content()
    assert "可用命令" in content  # "available commands"
    assert "/agents" in content
    assert "/context" in content
    assert "/fork" in content


def test_agents_shows_agent_table(page, base_url):
    """UF-21: /agents lists all agents in a table."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/agents')

    content = page.locator('#messages').text_content()
    assert "acp" in content
    assert "ncp" in content
    assert "xcp" in content
    assert "3 个 Agent" in content  # "3 agents"


def test_context_shows_usage_bar(page, base_url):
    """UF-23: /context shows token usage percentage."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/context')

    content = page.locator('#messages').text_content()
    assert "45" in content  # percentage value
    assert "100,000" in content  # max tokens


def test_usage_shows_cost(page, base_url):
    """UF-25: /usage shows cost summary."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/usage')

    content = page.locator('#messages').text_content()
    assert "acp" in content
    assert "0.02345" in content


def test_info_shows_session_info(page, base_url):
    """UF-26: /info shows PID, CWD, session_id."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/info')

    content = page.locator('#messages').text_content()
    assert "acp" in content
    assert "12345" in content  # PID
    assert "sess-acp" in content  # session_id


def test_rename_shows_confirmation(page, base_url):
    """UF-27: /rename <title> renames session and shows confirmation."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/rename 新会话标题')

    content = page.locator('#messages').text_content()
    assert "重命名" in content  # "renamed"
    assert "新会话标题" in content


def test_rename_without_title_shows_usage(page, base_url):
    """UF-27: /rename without title shows usage hint."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/rename')

    content = page.locator('#messages').text_content()
    assert "用法" in content  # "usage"


def test_fork_shows_new_session(page, base_url):
    """UF-28: /fork creates branch and shows new session ID."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/fork')

    content = page.locator('#messages').text_content()
    assert "分支" in content or "fork" in content.lower()  # "branched"


def test_plan_switches_to_plan_mode(page, base_url):
    """UF-29: /plan switches permission mode to plan."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/plan')

    content = page.locator('#messages').text_content()
    assert "plan" in content.lower() or "权限" in content


def test_perm_accept_edits(page, base_url):
    """UF-30: /perm acceptEdits switches mode."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/perm acceptEdits')

    content = page.locator('#messages').text_content()
    assert "acceptEdits" in content or "权限模式" in content


def test_perm_invalid_mode_shows_error(page, base_url):
    """UF-30: /perm with invalid mode shows error."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/perm invalidmode')

    content = page.locator('#messages').text_content()
    # Should show some kind of error or hint
    assert "无效" in content or "可选" in content


def test_model_switch_shows_confirmation(page, base_url):
    """UF-31: /model <name> switches model and shows confirmation."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/model claude-opus-4-20250514')

    content = page.locator('#messages').text_content()
    assert "claude-opus" in content or "模型" in content


def test_status_shows_pending_counts(page, base_url):
    """UF-32: /status shows pending counts for all projects."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/status')

    content = page.locator('#messages').text_content()
    assert "acp" in content
    assert "ncp" in content
    assert "xcp" in content
    assert "2" in content  # acp has 2 pending


def test_clear_empties_messages(page, base_url):
    """UF-33: /clear removes all message bubbles."""
    _select_agent_and_wait(page, base_url)
    # First send something so there are messages to clear
    _send_slash_command(page, '/help')
    page.wait_for_timeout(300)

    # Now clear
    _send_slash_command(page, '/clear')

    # Messages container should be empty (no .msg children)
    page.wait_for_timeout(300)
    msg_count = page.locator('#messages .msg').count()
    assert msg_count == 0


def test_mcp_shows_servers(page, base_url):
    """UF-22: /mcp lists MCP servers and tools."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/mcp')

    content = page.locator('#messages').text_content()
    assert "sextant" in content
    assert "send_message" in content


def test_unknown_command_shows_error(page, base_url):
    """UF-36: Unknown slash command shows error hint."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/boguscommand')

    content = page.locator('#messages').text_content()
    assert "未知" in content or "可用" in content  # "unknown" or "available"


def test_cost_alias_works_same_as_usage(page, base_url):
    """UF-25: /cost works as an alias for /usage."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/cost')

    content = page.locator('#messages').text_content()
    assert "acp" in content
    assert "0.02345" in content


def test_branch_alias_works_same_as_fork(page, base_url):
    """UF-28: /branch works as an alias for /fork."""
    _select_agent_and_wait(page, base_url)
    _send_slash_command(page, '/branch')

    content = page.locator('#messages').text_content()
    assert "分支" in content or "fork" in content.lower()
