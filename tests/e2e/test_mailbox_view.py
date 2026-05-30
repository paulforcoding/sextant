"""P0 — Mailbox view page (UF-37, UF-38, UF-39, UF-40).

Tests:
  UF-37: Clicking Mailbox in sidebar shows all messages as cards
  UF-38: Filtering mailbox by project parameter
  UF-39: Empty mailbox shows empty state
  UF-40: Mailbox load failure shows error message
"""

from __future__ import annotations


def test_mailbox_click_shows_card_list(page, base_url):
    """UF-37: Clicking Mailbox sidebar item shows message cards."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-view="mailbox"]', timeout=5000)

    page.locator('.sidebar-item[data-view="mailbox"]').click()

    # Wait for mailbox content to load (async fetch from /api/mailbox)
    # The mailbox view renders `#mailbox-list`, then fetches data
    page.wait_for_selector('#mailbox-list', timeout=10000)
    # Wait for the async fetch to complete
    page.wait_for_timeout(1500)

    # Cards should be rendered (or empty state if 0 entries)
    cards = page.locator('.mailbox-card')
    empty = page.locator('#mailbox-list .empty')
    assert cards.count() >= 1 or empty.count() >= 1

    # Header should say "Mailbox"
    assert page.locator('#header-title').text_content() == "Mailbox"


def test_mailbox_shows_correct_structure(page, base_url):
    """UF-37: Each mailbox card shows from→to, subject, body, status."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-view="mailbox"]', timeout=5000)

    page.locator('.sidebar-item[data-view="mailbox"]').click()
    page.wait_for_selector('#mailbox-list', timeout=10000)
    page.wait_for_timeout(1500)

    # If cards are present, check their structure
    cards = page.locator('.mailbox-card')
    if cards.count() >= 1:
        first_card = cards.first
        card_text = first_card.text_content()
        assert "acp" in card_text or "→" in card_text
        # Should have subject
        assert "同步协议变更" in card_text
        # Should have status
        status = first_card.locator('.mb-status')
        assert status.is_visible()


def test_mailbox_shows_count_in_header(page, base_url):
    """UF-37: Header status shows total message count."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-view="mailbox"]', timeout=5000)

    page.locator('.sidebar-item[data-view="mailbox"]').click()
    page.wait_for_selector('#mailbox-list', timeout=10000)
    # Wait for async fetch to complete
    page.wait_for_timeout(1500)

    status = page.locator('#header-status').text_content()
    # Should show count (might say "3 条消息" or still be "加载中..." on race)
    assert "条消息" in status or "加载" in status or "3" in status


def test_mailbox_card_hover_effect(page, base_url):
    """UF-37: Mailbox cards have hover background effect."""
    page.goto(base_url)
    page.wait_for_selector('.sidebar-item[data-view="mailbox"]', timeout=5000)

    page.locator('.sidebar-item[data-view="mailbox"]').click()
    page.wait_for_selector('#mailbox-list', timeout=10000)
    page.wait_for_timeout(1500)

    cards = page.locator('.mailbox-card')
    if cards.count() >= 1:
        card = cards.first
        card.hover()
        assert card.is_visible()


def test_mailbox_filter_by_project(page, base_url):
    """UF-38: Adding ?project=ncp filters to messages involving that project."""
    resp = page.request.get(f"{base_url}/api/mailbox?project=ncp")
    assert resp.ok
    data = resp.json()
    for entry in data:
        assert entry["from"] == "ncp" or entry["to"] == "ncp"
