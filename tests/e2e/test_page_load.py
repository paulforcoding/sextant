"""P0 — Page load and init (UF-01, UF-02).

Tests:
  UF-01: Page loads, sidebar renders agent list, footer shows count
  UF-02: API connection state visible after load
"""

from __future__ import annotations

import re


def test_page_loads_with_correct_title(page, base_url):
    """UF-01: Page loads with correct <title> and header text."""
    page.goto(base_url)
    assert page.title() == "sextant"


def test_sidebar_renders_agent_list(page, base_url):
    """UF-01: Sidebar loads agent names from /api/projects after init()."""
    page.goto(base_url)
    # Wait for the async init() to complete — agent list should be populated
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)
    page.wait_for_selector('.sidebar-item[data-project="ncp"]', timeout=5000)
    page.wait_for_selector('.sidebar-item[data-project="xcp"]', timeout=5000)


def test_sidebar_shows_pending_badges(page, base_url):
    """UF-01: Agents with pending messages show badge count."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)

    # acp has 2 pending
    acp_item = page.locator('.sidebar-item[data-project="acp"]')
    badge = acp_item.locator('.badge')
    assert badge.is_visible()
    assert badge.text_content() == "2"

    # ncp has 1 pending
    ncp_item = page.locator('.sidebar-item[data-project="ncp"]')
    badge = ncp_item.locator('.badge')
    assert badge.is_visible()
    assert badge.text_content() == "1"

    # xcp has 0 pending — no badge
    xcp_item = page.locator('.sidebar-item[data-project="xcp"]')
    assert xcp_item.locator('.badge').count() == 0


def test_footer_shows_agent_count(page, base_url):
    """UF-01: Sidebar footer shows 'N agents ready' after init."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)

    footer = page.locator('#sidebar-footer .status-text')
    text = footer.text_content()
    assert "3 agent" in text


def test_empty_state_before_selecting_agent(page, base_url):
    """UF-01: Main area shows empty/placeholder state before any agent is selected."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-project="acp"]', timeout=5000)

    content = page.locator('#content')
    assert content.is_visible()
    # Should show the "choose an agent" empty state
    assert "选择一个 Agent" in content.text_content() or "empty" in content.inner_html()


def test_mailbox_sidebar_entry_exists(page, base_url):
    """UF-01: Sidebar has a Mailbox entry for viewing all messages."""
    page.goto(base_url)
    mailbox_item = page.locator('.sidebar-item[data-view="mailbox"]')
    assert mailbox_item.is_visible()
    assert "Mailbox" in mailbox_item.text_content()
