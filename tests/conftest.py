"""Per-test fixtures for the browser layer.

Session-scoped fixtures (settings, scenarios, superadmin, backend_api) live in
the root conftest.py.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

from config.settings import Settings


@pytest.fixture(autouse=True)
def _apply_default_timeouts(page: Page, settings: Settings) -> None:
    """Push our default action/navigation timeouts onto every page."""
    page.set_default_timeout(settings.default_timeout_ms)
    page.set_default_navigation_timeout(settings.navigation_timeout_ms)


@pytest.fixture
def frontend_base_url(settings: Settings) -> str:
    return settings.frontend_base_url
