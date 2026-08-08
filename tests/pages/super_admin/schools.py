"""SuperAdmin → Manage Schools page object (/module/schools)."""
from __future__ import annotations

import re

from playwright.sync_api import Locator, Response, TimeoutError as PlaywrightTimeoutError, expect

from tests.pages.base import BasePage

CREATE_TRIGGER = re.compile(r"^\s*create new school\s*$", re.I)
SUBMIT_BUTTON = re.compile(r"^\s*create(ing)? school", re.I)
CREATED_TOAST = re.compile(r"school created successfully", re.I)

# The Create dialog offers GHC (not the ISO "GHS") — callers pass either.
CURRENCY_ALIASES = {"GHS": "GHC", "GH₵": "GHC"}
NOTIFICATION_LABELS = {"email": "Email", "sms": "SMS"}


class SchoolsPage(BasePage):
    URL = "/module/schools"

    def open(self) -> "SchoolsPage":
        super().open()
        expect(self.page.get_by_role("heading", name=re.compile(r"manage schools", re.I))).to_be_visible(
            timeout=15_000
        )
        return self

    # ───────────────────────── create ─────────────────────────

    def create_school(
        self,
        *,
        name: str,
        admin_email: str,
        admin_first_name: str,
        admin_last_name: str,
        address: str,
        phone: str,
        currency: str = "GHS",
        notification_preference: str = "email",
        school_email: str | None = None,
    ) -> int:
        """Create a school + its SchoolAdmin through the Create New School dialog.

        The form has a single "Admin Name" field, so first/last name are joined.
        It also requires a "School Email" that the backend enforces as unique
        across schools; when the caller does not supply one we reuse
        ``admin_email`` (schools and users live in different tables, so this is
        safe and keeps the school unique whenever the admin email is unique).

        Returns the new school id, read from the POST /school_profile/ response.
        Falls back to -1 if that response could not be captured — the table
        renders no id, and the page never navigates to a school detail route, so
        there is no other UI source for it.
        """
        self.click_button(CREATE_TRIGGER)
        dialog = self.dialog()
        expect(dialog).to_be_visible(timeout=10_000)

        self.fill_labeled(r"^School Name", name, in_dialog=True)
        self.fill_labeled(r"^Address", address, in_dialog=True)
        self.fill_labeled(r"^Phone Number", _digits(phone), in_dialog=True)
        self.fill_labeled(r"^School Email", school_email or admin_email, in_dialog=True)
        self.fill_labeled(r"^Admin Name", f"{admin_first_name} {admin_last_name}".strip(), in_dialog=True)
        self.fill_labeled(r"^Admin Email", admin_email, in_dialog=True)

        self._select_notification_preference(notification_preference)
        self._select_currency(currency)

        response: Response | None = None
        try:
            with self.page.expect_response(_is_create_response, timeout=30_000) as info:
                self.click_button(SUBMIT_BUTTON)
            response = info.value
        except PlaywrightTimeoutError:
            pass

        self.expect_toast(CREATED_TOAST, timeout_ms=15_000)
        expect(dialog).to_be_hidden(timeout=10_000)
        expect(self.find_row(name)).to_be_visible(timeout=15_000)

        return _school_id_from(response)

    # ────────────────────────── table ─────────────────────────

    def search(self, term: str) -> None:
        self.page.get_by_placeholder(re.compile(r"search school by name", re.I)).fill(term)

    def find_row(self, name: str) -> Locator:
        """Row in the All Schools table (desktop table; needs a ≥1024px viewport)."""
        return self.page.get_by_role("row").filter(
            has_text=re.compile(re.escape(name), re.I)
        ).first

    def delete_school(self, name: str) -> None:
        """Not reachable through the UI.

        /module/schools renders a read-only table: rows carry no action menu, no
        delete control and no detail route, and no other frontend screen deletes
        a school. Teardown must use the backend instead —
        ``BackendAPI.delete(f"/school_profile/{school_id}", token=...)``.
        """
        raise NotImplementedError(
            f"The Manage Schools page exposes no delete control for {name!r}; "
            "delete via BackendAPI DELETE /school_profile/{id} instead."
        )

    # ───────────────────────── internals ──────────────────────

    def _select_notification_preference(self, preference: str) -> None:
        label = NOTIFICATION_LABELS.get(preference.strip().lower(), preference.strip())
        self.select_option_in_combobox(
            re.compile(r"^(email|sms)$", re.I), re.compile(rf"^{re.escape(label)}$", re.I)
        )

    def _select_currency(self, currency: str) -> None:
        code = currency.strip().upper()
        code = CURRENCY_ALIASES.get(code, code)
        self.select_option_in_combobox(
            re.compile(r"^(GHC|USD|EUR|GBP)$"), re.compile(rf"^{re.escape(code)}$")
        )


def _digits(phone: str) -> str:
    """The form silently rejects any value that is not ≤10 digits."""
    return re.sub(r"\D", "", phone)[:10]


def _is_create_response(response: Response) -> bool:
    return (
        response.request.method == "POST"
        and re.search(r"/school_profile/?(\?|$)", response.url) is not None
    )


def _school_id_from(response: Response | None) -> int:
    if response is None or not response.ok:
        return -1
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        return -1
    school_id = payload.get("id") if isinstance(payload, dict) else None
    return int(school_id) if isinstance(school_id, (int, str)) and str(school_id).isdigit() else -1
