"""Root test configuration — ensures async backend tests run before E2E browser tests.

Without this ordering, pytest-playwright leaves a running event loop after E2E
tests, which causes ``RuntimeError: asyncio.run() cannot be called from a
running event loop`` when the async backend tests subsequently try to use
``asyncio.run()`` or pytest-asyncio's Runner.
"""

from __future__ import annotations


def pytest_collection_modifyitems(config, items):
    """Move E2E browser tests to the end so async backend tests run first."""
    e2e_items = [it for it in items if "tests/e2e/" in str(it.fspath)]
    other_items = [it for it in items if it not in e2e_items]

    items[:] = other_items + e2e_items
