"""Login page object."""
from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.fixtures.api_client import Credentials
from tests.pages.base import BasePage


class LoginPage(BasePage):
    URL = "/auth/login"

    def login(self, email: str, password: str, *, wait_for_post_login: bool = True) -> None:
        self.page.fill("input[name='email']", email)
        self.page.fill("input[name='password']", password)
        self.page.locator("button[type='submit']").click()
        if wait_for_post_login:
            # Frontend redirects away from /auth/login on success.
            self.page.wait_for_url(re.compile(r"/module/"), timeout=15_000)

    def expect_error(self, pattern: str | re.Pattern) -> None:
        pat = pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, re.I)
        expect(self.page.get_by_text(pat)).to_be_visible(timeout=8_000)


def login_as(page: Page, frontend_base_url: str, creds: Credentials) -> None:
    """Convenience: open the login page and submit credentials."""
    LoginPage(page, frontend_base_url).open().login(creds.email, creds.password)


def logout(page: Page) -> None:
    """Click whatever logout control is currently exposed.

    The frontend exposes logout from a profile menu; selector is intentionally
    permissive until we lock the page object down in Phase 2.
    """
    candidates = [
        page.get_by_role("button", name=re.compile(r"^log[\s-]?out$", re.I)),
        page.get_by_role("menuitem", name=re.compile(r"^log[\s-]?out$", re.I)),
        page.get_by_text(re.compile(r"^log[\s-]?out$", re.I)),
    ]
    for loc in candidates:
        if loc.count() > 0:
            loc.first.click()
            page.wait_for_url(re.compile(r"/auth/login"), timeout=10_000)
            return
    raise AssertionError("Could not find a logout control on the current page.")
