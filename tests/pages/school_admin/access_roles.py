"""SchoolAdmin → Access Roles page object (/module/access_roles)."""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage

HEADING = re.compile(r"^\s*manage access roles\s*$", re.I)

# Tab labels carry a trailing count badge, so the accessible name is e.g.
# "Access Roles 8".
ROLES_TAB = re.compile(r"^\s*access roles\s*\d*\s*$", re.I)
USERS_TAB = re.compile(r"^\s*users\s*&\s*roles\s*\d*\s*$", re.I)

USER_SEARCH = re.compile(r"search users by name, email, or role", re.I)
PAGINATION = re.compile(r"page\s+\d+\s+of\s+\d+", re.I)

CHANGE_ROLE = re.compile(r"^\s*change role\s*$", re.I)
ROLE_CHANGED_TOAST = re.compile(r"role successfully changed", re.I)

# /module/access_roles only *lists* users and re-assigns their role — the one
# place the app creates a generic (non-domain) user is the SchoolAdmin
# dashboard's "Create Admin" dialog, which posts to /users/add_admin/{branch}.
DASHBOARD_URL = "/module/school_admin_dashboard"
CREATE_ADMIN = re.compile(r"^\s*create admin\s*$", re.I)
BRANCH_TRIGGER = re.compile(r"select a branch", re.I)
PASSWORD_FIELD = re.compile(r"^\s*password", re.I)
CONFIRM_PASSWORD_FIELD = re.compile(r"^\s*confirm password", re.I)
ADMIN_CREATED_TOAST = re.compile(r"admin created successfully", re.I)

SUPPORTED_ROLES = ("Admin", "Accountant")

# The dialog only accepts a password scoring 3/4 on its own strength meter:
# 8+ chars, an uppercase letter, a digit and a symbol.
DEFAULT_PASSWORD = "Playwright#Admin1"

TEXT_FIELDS: dict[str, re.Pattern[str]] = {
    "first_name": re.compile(r"^\s*first name", re.I),
    "other_names": re.compile(r"^\s*last name", re.I),
    "email": re.compile(r"^\s*email", re.I),
    "nationality": re.compile(r"^\s*nationality", re.I),
    "residential_address": re.compile(r"^\s*residential address", re.I),
    "primary_phone": re.compile(r"^\s*primary phone", re.I),
    "secondary_phone": re.compile(r"^\s*secondary phone", re.I),
    "religion": re.compile(r"^\s*religion", re.I),
    "zip_code": re.compile(r"^\s*zip code", re.I),
    "local_dialect": re.compile(r"^\s*local dialect", re.I),
    "date_of_birth": re.compile(r"^\s*date of birth", re.I),
}

SELECT_FIELDS: dict[str, re.Pattern[str]] = {
    "gender": re.compile(r"select gender", re.I),
    "marital_status": re.compile(r"select marital status", re.I),
}

FIELD_ALIASES: dict[str, str] = {
    "last_name": "other_names",
    "address": "residential_address",
    "phone": "primary_phone",
    "dob": "date_of_birth",
}

# These inputs drop any value containing a non-letter, and the phone inputs any
# value that isn't 0-10 digits — a single fill() sets the whole string at once,
# so an unsanitised value silently leaves the field empty.
LETTERS_ONLY = frozenset(
    {"first_name", "other_names", "nationality", "residential_address",
     "religion", "local_dialect"}
)
DIGITS_ONLY = frozenset({"zip_code"})
PHONE_FIELDS = frozenset({"primary_phone", "secondary_phone"})

# UserSignup declares gender/date_of_birth/nationality/residential_address/
# primary_phone as required, and the dialog posts "" for anything untouched —
# which fails date parsing outright. Defaults keep the happy path a one-liner.
ADMIN_DEFAULTS: dict[str, str] = {
    "gender": "Male",
    "marital_status": "Single",
    "date_of_birth": "1990-01-15",
    "nationality": "Ghanaian",
    "residential_address": "Accra Central",
    "primary_phone": "0201234567",
}


class AccessRolesPage(BasePage):
    URL = "/module/access_roles"

    def open(self) -> "AccessRolesPage":
        super().open()
        expect(self.page.get_by_role("heading", name=HEADING)).to_be_visible(timeout=15_000)
        return self

    # ──────────────────────────── roles ───────────────────────────

    def list_roles(self) -> list[str]:
        """Every role name in the "Access Roles" tab, across all pages."""
        self._open_tab(ROLES_TAB)
        names: list[str] = []
        while True:
            names.extend(self._first_column_values())
            if not self._go_to_next_page():
                return names

    # ──────────────────────────── users ───────────────────────────

    def create_user(
        self,
        *,
        role: str,
        email: str,
        first_name: str,
        last_name: str,
        password: str | None = None,
        **extra: str,
    ) -> None:
        """Create a generic user and land them on `role`.

        Teachers, students and guardians are domain records with their own
        multi-step wizards — only the role-only users belong here. The app has
        no "create user with role X" form, so this creates an Admin and then
        re-assigns the role through the Users & Roles tab.

        `extra` accepts any other field of the Create Admin dialog
        (nationality, residential_address, primary_phone, gender,
        marital_status, date_of_birth, …) plus `branch` to pick the branch to
        assign to; without it the first branch in the list is used.
        """
        wanted = role.strip()
        if wanted.lower() not in {name.lower() for name in SUPPORTED_ROLES}:
            raise ValueError(
                f"create_user() only handles {SUPPORTED_ROLES}; {role!r} is a domain "
                "record created from its own page object."
            )

        self._create_admin(
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password or DEFAULT_PASSWORD,
            extra=dict(extra),
        )
        if wanted.lower() != "admin":
            self.change_user_role(email=email, role=wanted)

    def find_user_row(self, email: str) -> Locator:
        """The Users & Roles row for `email`, with the table filtered to it."""
        self._ensure_open()
        self._open_tab(USERS_TAB)
        self.fill_labeled(USER_SEARCH, email)
        row = self.page.get_by_role("row").filter(has_text=email).first
        expect(row).to_be_visible(timeout=15_000)
        return row

    def change_user_role(self, *, email: str, role: str) -> None:
        row = self.find_user_row(email)
        row.get_by_role("button").last.click()
        self.page.get_by_role("menuitem", name=CHANGE_ROLE).first.click()

        dialog = self.dialog().filter(has_text=CHANGE_ROLE).first
        dialog.get_by_role("combobox").first.click()
        # The Select renders its options in a body-level portal, not in the modal.
        self.page.get_by_role(
            "option", name=re.compile(rf"^\s*{re.escape(role)}\s*$", re.I)
        ).first.click()
        dialog.get_by_role("button", name=CHANGE_ROLE).first.click()
        self.expect_toast(ROLE_CHANGED_TOAST, timeout_ms=15_000)

    # ────────────────────────── internals ─────────────────────────

    def _ensure_open(self) -> None:
        if self.URL not in self.page.url:
            self.open()

    def _open_tab(self, name: re.Pattern[str]) -> None:
        self.click_button(name)
        expect(self.page.get_by_text(PAGINATION).first).to_be_visible(timeout=20_000)

    def _first_column_values(self) -> list[str]:
        rows = self.page.get_by_role("row")
        values: list[str] = []
        for index in range(rows.count()):
            cells = rows.nth(index).get_by_role("cell")
            if cells.count() == 0:
                continue
            values.append(cells.first.inner_text().strip())
        return values

    def _page_numbers(self) -> tuple[int, int]:
        label = self.page.get_by_text(PAGINATION).first.inner_text()
        match = re.search(r"page\s+(\d+)\s+of\s+(\d+)", label, re.I)
        if not match:
            raise AssertionError(f"Unreadable pagination label: {label!r}")
        return int(match.group(1)), int(match.group(2))

    def _go_to_next_page(self) -> bool:
        current, total = self._page_numbers()
        if current >= total:
            return False
        # Both pager controls are icon-only, so anchor on the "Page x of y"
        # label and take the trailing (next) button of its row.
        pager = self.page.get_by_text(PAGINATION).first.locator("xpath=..")
        pager.get_by_role("button").last.click()
        expect(
            self.page.get_by_text(re.compile(rf"page\s+{current + 1}\s+of", re.I)).first
        ).to_be_visible(timeout=15_000)
        return True

    def _create_admin(
        self,
        *,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        extra: dict[str, str],
    ) -> None:
        branch = extra.pop("branch", None)
        values = {FIELD_ALIASES.get(key, key): value for key, value in extra.items()}
        unknown = set(values) - set(TEXT_FIELDS) - set(SELECT_FIELDS)
        if unknown:
            raise ValueError(f"Create Admin has no field(s) named {sorted(unknown)}.")

        values = {
            **ADMIN_DEFAULTS,
            **values,
            "first_name": first_name,
            "other_names": last_name,
            "email": email,
        }

        self.page.goto(self.absolute(DASHBOARD_URL))
        self.click_button(CREATE_ADMIN)
        expect(self.dialog()).to_be_visible(timeout=15_000)
        self._select_branch(branch)

        for key, value in values.items():
            if key in SELECT_FIELDS:
                self.select_option_in_combobox(
                    SELECT_FIELDS[key], re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
                )
                continue
            if key == "date_of_birth":
                self.commit_date(
                    self.dialog().get_by_placeholder(TEXT_FIELDS[key]).first, value
                )
                continue
            self.fill_labeled(TEXT_FIELDS[key], _sanitize(key, value), in_dialog=True)

        self.fill_labeled(PASSWORD_FIELD, password, in_dialog=True)
        self.fill_labeled(CONFIRM_PASSWORD_FIELD, password, in_dialog=True)
        self.dialog().get_by_role("button", name=CREATE_ADMIN).first.click()
        self.expect_toast(ADMIN_CREATED_TOAST, timeout_ms=20_000)

    def _select_branch(self, branch: str | None) -> None:
        if branch:
            self.select_option_in_combobox(BRANCH_TRIGGER, re.compile(re.escape(branch), re.I))
            return
        self.page.get_by_role("combobox").filter(has_text=BRANCH_TRIGGER).first.click()
        self.page.get_by_role("option").first.click()


def _sanitize(field: str, value: str) -> str:
    if field in LETTERS_ONLY:
        return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", value)).strip()
    if field in PHONE_FIELDS:
        return re.sub(r"\D", "", value)[:10]
    if field in DIGITS_ONLY:
        return re.sub(r"\D", "", value)
    return value
