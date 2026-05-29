"""Base page object — shared helpers all pages can rely on."""
from __future__ import annotations

import re
from typing import ClassVar

from playwright.sync_api import Page, expect


class BasePage:
    URL: ClassVar[str | None] = None

    def __init__(self, page: Page, frontend_base_url: str):
        self.page = page
        self.frontend_base_url = frontend_base_url.rstrip("/")

    # ─────────────────────── navigation ──────────────────────────

    def open(self) -> "BasePage":
        if not self.URL:
            raise RuntimeError(f"{type(self).__name__} has no URL set.")
        self.page.goto(self.frontend_base_url + self.URL)
        return self

    def absolute(self, route: str) -> str:
        if route.startswith("http"):
            return route
        return self.frontend_base_url + ("" if route.startswith("/") else "/") + route

    # ───────────────────── common locators ───────────────────────

    def toast(self, pattern: str | re.Pattern):
        """Match react-hot-toast text. Tolerant to surrounding markup."""
        return self.page.get_by_text(pattern if isinstance(pattern, re.Pattern)
                                     else re.compile(pattern, re.I))

    def expect_toast(self, pattern: str | re.Pattern, timeout_ms: int = 8_000) -> None:
        expect(self.toast(pattern)).to_be_visible(timeout=timeout_ms)

    def dialog(self):
        return self.page.get_by_role("dialog")

    def click_button(self, name: str | re.Pattern) -> None:
        pattern = name if isinstance(name, re.Pattern) else re.compile(name, re.I)
        self.page.get_by_role("button", name=pattern).first.click()

    def fill_labeled(self, label: str | re.Pattern, value: str, *, in_dialog: bool = False) -> None:
        pattern = label if isinstance(label, re.Pattern) else re.compile(label, re.I)
        scope = self.dialog() if in_dialog else self.page
        # Try label first (proper <label for=...> association), fall back to placeholder.
        loc = scope.get_by_label(pattern).first
        if loc.count() == 0:
            loc = scope.get_by_placeholder(pattern).first
        loc.fill(value)

    def select_option_in_combobox(self, trigger_text: str | re.Pattern,
                                  option_text: str | re.Pattern) -> None:
        """Radix combobox pattern used everywhere in the app."""
        t_pattern = trigger_text if isinstance(trigger_text, re.Pattern) else re.compile(trigger_text, re.I)
        o_pattern = option_text if isinstance(option_text, re.Pattern) else re.compile(option_text, re.I)
        self.page.get_by_role("combobox").filter(has_text=t_pattern).first.click()
        self.page.get_by_role("option", name=o_pattern).first.click()


def goto_module(page: Page, frontend_base_url: str, route: str) -> None:
    """Navigate directly to /module/<route>."""
    url = frontend_base_url.rstrip("/") + "/module/" + route.lstrip("/")
    page.goto(url)
