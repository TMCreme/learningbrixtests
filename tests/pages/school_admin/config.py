"""SchoolAdmin → School Configuration page object (/module/config)."""
from __future__ import annotations

import re
from typing import Literal

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage

HEADING = re.compile(r"^\s*school configuration\s*$", re.I)

NAME_FIELD = re.compile(r"enter school name", re.I)
ADDRESS_FIELD = re.compile(r"enter school address", re.I)
PHONE_FIELD = re.compile(r"enter school phone number", re.I)
EMAIL_FIELD = re.compile(r"enter school email", re.I)

CURRENCY_TRIGGER = re.compile(r"select currency|ghc|euro|usd", re.I)
# The Select only offers GHC (not the ISO "GHS") — callers may pass either.
CURRENCY_ALIASES = {"GHS": "GHC", "GH₵": "GHC", "EUR": "Euro"}

# Both preferences are rendered as checkboxes wrapped in a <label>; the
# accessible name is the whole label, so match on its description sentence.
PREFERENCE_NAMES: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"notifications via email", re.I),
    "sms": re.compile(r"notifications via sms", re.I),
}

SAVE_BUTTON = re.compile(r"^\s*(save|update)\s*$", re.I)
SAVED_TOAST = re.compile(r"school profile successfully (created|updated)", re.I)

NotificationPreference = Literal["email", "sms", "push"]


class ConfigPage(BasePage):
    URL = "/module/config"

    def open(self) -> "ConfigPage":
        super().open()
        expect(self.page.get_by_role("heading", name=HEADING)).to_be_visible(timeout=15_000)
        return self

    # ─────────────────────── school profile ───────────────────────

    def set_basic_info(self, *, name: str, address: str, phone: str, email: str) -> None:
        """Fill the School profile block.

        The inputs carry no <label for=...>, so these resolve by placeholder.
        Each one filters its own keystrokes: the name accepts letters/spaces
        only, the phone digits (optionally "+"-prefixed, max 15) and the email
        is dropped entirely unless it is already a complete address — so values
        are normalised here rather than silently disappearing.
        """
        self.fill_labeled(NAME_FIELD, name)
        self.fill_labeled(ADDRESS_FIELD, address)
        self.fill_labeled(PHONE_FIELD, _phone(phone))
        self.fill_labeled(EMAIL_FIELD, email)

    def set_currency(self, currency: str) -> None:
        code = currency.strip()
        code = CURRENCY_ALIASES.get(code.upper(), code)
        self.select_option_in_combobox(
            CURRENCY_TRIGGER, re.compile(rf"^\s*{re.escape(code)}\s*$", re.I)
        )

    # ───────────────────── notification preference ────────────────

    def set_notification_preference(self, pref: NotificationPreference) -> None:
        key = pref.strip().lower()
        if key not in PREFERENCE_NAMES:
            raise ValueError(
                f"{pref!r} is not selectable: /module/config only renders Email and SMS."
            )
        self._preference_checkbox(PREFERENCE_NAMES[key]).check()

    # ──────────────────────────── save ────────────────────────────

    def save(self) -> None:
        """Submit the form.

        The button reads "Save" for a school with no profile yet and "Update"
        once one exists; the toast differs the same way.
        """
        self.click_button(SAVE_BUTTON)
        self.expect_toast(SAVED_TOAST, timeout_ms=15_000)

    # ────────────────────────── internals ─────────────────────────

    def _preference_checkbox(self, name: re.Pattern[str]) -> Locator:
        box = self.page.get_by_role("checkbox", name=name).first
        if box.count() == 0:
            box = self.page.locator("label").filter(has_text=name).get_by_role("checkbox").first
        return box


def _phone(phone: str) -> str:
    plus = "+" if phone.strip().startswith("+") else ""
    return plus + re.sub(r"\D", "", phone)[:15]
