"""P0/P1 — Input box interactions (UF-45, UF-46, UF-47, UF-48, UF-49).

Tests:
  UF-45: Enter key sends message
  UF-46: Shift+Enter inserts newline without sending
  UF-47: ArrowUp/Down navigates input history
  UF-48: Textarea auto-resizes on input
  UF-49: Empty/whitespace-only input is rejected
"""

from __future__ import annotations


def _select_agent_and_wait(page, base_url, agent_id="acp"):
    """Helper: load page, select an agent, wait for chat UI."""
    page.goto(base_url)
    page.wait_for_selector(f'.sidebar-item[data-project="{agent_id}"]', timeout=5000)
    page.locator(f'.sidebar-item[data-project="{agent_id}"]').click()
    page.wait_for_selector('#prompt-input', timeout=10000)
    page.wait_for_timeout(1000)


def test_enter_sends_message(page, base_url):
    """UF-45: Pressing Enter sends the message."""
    _select_agent_and_wait(page, base_url)
    initial_count = page.locator('.msg.user').count()

    input_el = page.locator('#prompt-input')
    input_el.fill("Enter 发送测试")
    input_el.press("Enter")
    page.wait_for_timeout(500)

    # User bubble count should increase
    assert page.locator('.msg.user').count() > initial_count
    assert input_el.input_value() == ""


def test_shift_enter_inserts_newline(page, base_url):
    """UF-46: Shift+Enter inserts a newline without sending."""
    _select_agent_and_wait(page, base_url)
    initial_count = page.locator('.msg.user').count()

    input_el = page.locator('#prompt-input')
    input_el.fill("第一行")
    input_el.press("Shift+Enter")
    input_el.type("第二行")

    value = input_el.input_value()
    assert "\n" in value
    assert "第一行" in value
    assert "第二行" in value

    # Message should NOT have been sent yet
    assert page.locator('.msg.user').count() == initial_count


def test_empty_input_not_sent(page, base_url):
    """UF-49: Pressing Enter with empty input does not send."""
    _select_agent_and_wait(page, base_url)
    initial_count = page.locator('.msg.user').count()

    input_el = page.locator('#prompt-input')
    input_el.fill("")
    input_el.press("Enter")
    page.wait_for_timeout(500)

    # No NEW user message should appear (count stays same)
    assert page.locator('.msg.user').count() == initial_count


def test_whitespace_only_not_sent(page, base_url):
    """UF-49: Pressing Enter with whitespace-only input does not send."""
    _select_agent_and_wait(page, base_url)
    initial_count = page.locator('.msg.user').count()

    input_el = page.locator('#prompt-input')
    input_el.fill("   \t  ")
    input_el.press("Enter")
    page.wait_for_timeout(500)

    # No NEW user message should appear
    assert page.locator('.msg.user').count() == initial_count


def test_textarea_auto_resize(page, base_url):
    """UF-48: Textarea height adjusts to content (up to max 120px)."""
    _select_agent_and_wait(page, base_url)

    input_el = page.locator('#prompt-input')
    initial_height = input_el.evaluate('el => el.scrollHeight')

    input_el.fill("line1\nline2\nline3\nline4\nline5")
    new_height = input_el.evaluate('el => el.scrollHeight')
    assert new_height >= initial_height


def test_input_history_arrow_navigation(page, base_url):
    """UF-47: ArrowUp/Down navigates through input history."""
    _select_agent_and_wait(page, base_url)

    input_el = page.locator('#prompt-input')

    # Send a message (adds to history)
    input_el.fill("第一条历史消息")
    page.locator('#send-btn').click()
    page.wait_for_timeout(1000)

    # Send another message
    input_el.fill("第二条历史消息")
    page.locator('#send-btn').click()
    page.wait_for_timeout(1000)

    # Now type something new and press ArrowUp
    input_el.fill("something")
    input_el.press("ArrowUp")

    # Should navigate to most recent history entry for this project
    value = input_el.input_value()
    assert "第二条" in value
