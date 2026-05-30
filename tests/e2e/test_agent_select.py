"""P0 — Agent selection and switching (UF-03, UF-04, UF-05).

Tests:
  UF-03: First-time agent selection loads chat UI + history
  UF-04: Switching back to a previously visited agent restores from cache
  UF-05: Sidebar highlight follows active agent
"""

from __future__ import annotations


def _select_agent(page, agent_id="acp"):
    """Helper: click an agent and wait for chat UI."""
    page.locator(f'.sidebar-item[data-project="{agent_id}"]').click()
    page.wait_for_selector('#messages', timeout=10000)
    page.wait_for_selector('#prompt-input', timeout=5000)


def test_select_agent_shows_chat_ui(page, base_url):
    """UF-03: Clicking an agent in sidebar builds chat UI (input + messages area)."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)
    _select_agent(page, "acp")

    page.wait_for_selector('#send-btn', timeout=5000)
    header = page.locator('#header-title')
    assert header.text_content() == "acp"


def test_select_agent_highlights_sidebar(page, base_url):
    """UF-05: Selected agent gets .active class in sidebar."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)

    _select_agent(page, "acp")
    assert page.locator('.sidebar-item[data-project="acp"].active').count() == 1

    _select_agent(page, "ncp")
    assert page.locator('.sidebar-item[data-project="acp"].active').count() == 0
    assert page.locator('.sidebar-item[data-project="ncp"].active').count() == 1


def test_select_agent_loads_history(page, base_url):
    """UF-03: First-time visit loads history from /api/chat/{id}/history."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)
    _select_agent(page, "acp")
    page.wait_for_timeout(1000)

    text = page.locator('#messages').text_content()
    assert "项目进度" in text or "项目进展顺利" in text


def test_select_agent_shows_header_status(page, base_url):
    """UF-03: Header status shows history message count after loading."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)
    _select_agent(page, "acp")
    page.wait_for_timeout(500)

    status = page.locator('#header-status')
    assert status.is_visible()
    assert len(status.text_content()) > 0


def test_switch_between_agents_preserves_cache(page, base_url):
    """UF-04: Switching away and back restores previous chat from cache."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)

    # Visit acp first
    _select_agent(page, "acp")
    page.wait_for_timeout(500)

    # Send a message to populate chatCache
    page.locator('#prompt-input').fill("测试缓存")
    page.locator('#send-btn').click()
    page.wait_for_timeout(2500)

    # Switch to ncp
    _select_agent(page, "ncp")
    page.wait_for_timeout(500)

    # Switch back to acp — should restore from cache
    _select_agent(page, "acp")
    page.wait_for_timeout(1000)

    # The cached user message should be visible in messages area
    content = page.locator('#messages').text_content()
    assert "测试缓存" in content


def test_select_agent_aborts_previous_stream(page, base_url):
    """UF-03: Selecting a new agent while streaming aborts the previous stream."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)
    _select_agent(page, "acp")

    page.locator('#prompt-input').fill("test message")
    page.locator('#send-btn').click()

    page.locator('.sidebar-item[data-project="ncp"]').click()
    page.wait_for_selector('#messages', timeout=10000)

    assert page.locator('#prompt-input').is_visible()
    assert page.locator('#header-title').text_content() == "ncp"


def test_select_without_pending_works(page, base_url):
    """UF-03: Selecting agent with no pending messages works normally."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="xcp"]', timeout=5000)
    _select_agent(page, "xcp")

    assert page.locator('#prompt-input').is_visible()
    mailbox_bubbles = page.locator('.msg.system')
    assert mailbox_bubbles.count() <= 1
