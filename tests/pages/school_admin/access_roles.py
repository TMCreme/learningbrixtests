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
ROLE_SEARCH = re.compile(r"search role by name", re.I)
PAGINATION = re.compile(r"page\s+\d+\s+of\s+\d+", re.I)

CHANGE_ROLE = re.compile(r"^\s*change role\s*$", re.I)
ROLE_CHANGED_TOAST = re.compile(r"role successfully changed", re.I)

# The sidebar entry (SideNavigation/nav-config.tsx, "Governance Module" group).
# That whole group is ``noBranchOnly``, so it is offered to a SchoolAdmin only
# while no branch is active — activating one from /module/school_admin_dashboard
# hides it. Nothing on this screen needs a branch (GET /roles/ takes none and
# GET /users/all derives the school from the caller), so a governance test must
# simply not select one.
NAV_ACCESS_ROLES = re.compile(r"^\s*Access Roles\s*$", re.I)

# The breadcrumb every editor screen puts back to the register. Singular, so it
# can never be confused with the sidebar entry above.
BREADCRUMB_BACK = re.compile(r"^\s*Access role\s*$", re.I)

# ── the role editor: /add-access-role, /edit-access-role/{id}, /preview-role/{id}
ADD_ROLE_BUTTON = re.compile(r"^\s*add access role\s*$", re.I)
ADD_ROLE_HEADING = re.compile(r"^\s*add access role\s*$", re.I)
EDIT_ROLE_HEADING = re.compile(r"^\s*edit access role\s*$", re.I)
PREVIEW_ROLE_HEADING = re.compile(r"^\s*preview access role\s*$", re.I)

# Bare <label>Role Name *</label> with no `for`, so the placeholder is what
# actually binds — it is given as an alternation branch (see BasePage.fill_labeled).
ROLE_NAME_FIELD = re.compile(r"^\s*(role name\s*\*?|enter role name)\s*$", re.I)

SAVE_AND_EXIT = re.compile(r"^\s*save and exit\s*$", re.I)
SAVE_CHANGES = re.compile(r"^\s*save changes\s*$", re.I)
FORM_READY = re.compile(r"Form is ready to be saved", re.I)
NEEDS_A_PERMISSION = re.compile(r"select at least one permission", re.I)

PREVIEW_ROLE_ITEM = re.compile(r"^\s*preview role\s*$", re.I)
EDIT_ROLE_ITEM = re.compile(r"^\s*edit role\s*$", re.I)
DELETE_ROLE_ITEM = re.compile(r"^\s*delete role\s*$", re.I)

DELETE_ROLE_MODAL = re.compile(r"^\s*delete access role\s*$", re.I)
DELETE_ROLE_CONFIRM = re.compile(r"^\s*delete role\s*$", re.I)

ROLE_CREATED_TOAST = re.compile(r"role successfully created", re.I)
ROLE_UPDATED_TOAST = re.compile(r"role updated successfully", re.I)
ROLE_DELETED_TOAST = re.compile(r"role successfully deleted", re.I)

# The three permission levels, keyed by the backend's own vocabulary. The radio
# groups are *not* labelled the same on the two screens: add-access-role posts
# the permission name verbatim ("no-access"/"read"/"manage") while
# edit-access-role and preview-role speak in levels ("no-access"/"read-only"/
# "can-manage"). Both render ``value.replace("-", " ")`` as the visible text.
CREATE_LEVELS: dict[str, re.Pattern[str]] = {
    "no-access": re.compile(r"^\s*no access\s*$", re.I),
    "read": re.compile(r"^\s*read\s*$", re.I),
    "manage": re.compile(r"^\s*manage\s*$", re.I),
}
EDIT_LEVELS: dict[str, re.Pattern[str]] = {
    "no-access": re.compile(r"^\s*no access\s*$", re.I),
    "read": re.compile(r"^\s*read only\s*$", re.I),
    "manage": re.compile(r"^\s*can manage\s*$", re.I),
}

# What marks the chosen level on all three editor screens: the <label> turns
# indigo. The radio inside it is `hidden`, and every radio on the page shares
# name="permission", so the DOM `checked` flag is not a reliable read — only one
# radio in a same-named group can carry it however many React thinks are set.
SELECTED_LEVEL_CLASS = re.compile(r"\btext-indigo-600\b")

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

    def open_from_nav(self) -> "AccessRolesPage":
        """Reach the workspace the way a SchoolAdmin does — from the sidebar.

        Falls back to a direct navigation when the entry is not on screen (the
        sidebar collapses on narrow viewports), because how the user got here is
        never what a test is asserting.
        """
        link = self.page.get_by_role("link", name=NAV_ACCESS_ROLES).first
        if link.count() == 0:
            return self.open()
        link.click()
        self.page.wait_for_url(re.compile(r"/module/access_roles"), timeout=20_000)
        expect(self.page.get_by_role("heading", name=HEADING)).to_be_visible(timeout=20_000)
        return self

    def back_to_register(self) -> "AccessRolesPage":
        """Leave an editor screen the way its own breadcrumb offers."""
        crumb = self.page.get_by_role("link", name=BREADCRUMB_BACK).first
        if crumb.count() == 0:
            return self.open()
        crumb.click()
        self.page.wait_for_url(re.compile(r"/module/access_roles(?:$|[?#])"), timeout=20_000)
        expect(self.page.get_by_role("heading", name=HEADING)).to_be_visible(timeout=20_000)
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

    def search_roles(self, query: str) -> None:
        """Filter the Access Roles tab by name (client-side, on the loaded list)."""
        self._ensure_open()
        self._open_tab(ROLES_TAB)
        self.fill_labeled(ROLE_SEARCH, query)

    def role_row(self, name: str) -> Locator:
        """The Access Roles rows matching `name`, with the table filtered to it.

        Returned unresolved so a caller can assert either presence or absence —
        a deleted role has to be provably *gone*, not merely off the first page.
        """
        self.search_roles(name)
        return self.page.get_by_role("row").filter(has_text=name)

    def create_role(self, *, name: str, permissions: dict[str, str]) -> None:
        """Add an access role from /module/access_roles/add-access-role.

        ``permissions`` maps a row's heading on the editor — "Fee Management",
        "Students", … as listed in access_roles/role_module.ts — to one of
        "no-access" / "read" / "manage". The screen keeps "Save and Exit"
        disabled until the name is valid *and* at least one row is above
        no-access, so the caller gets a real create or a visible failure.
        """
        self._ensure_open()
        self.click_button(ADD_ROLE_BUTTON)
        self.page.wait_for_url(re.compile(r"/access_roles/add-access-role"), timeout=20_000)
        expect(self.page.get_by_role("heading", name=ADD_ROLE_HEADING)).to_be_visible(
            timeout=20_000
        )

        self.fill_labeled(ROLE_NAME_FIELD, name)
        for item, level in permissions.items():
            self.set_permission(item, level, levels=CREATE_LEVELS)

        expect(self.page.get_by_text(FORM_READY)).to_be_visible(timeout=10_000)
        self.click_button(SAVE_AND_EXIT)
        self.expect_toast(ROLE_CREATED_TOAST, timeout_ms=20_000)
        self.page.wait_for_url(re.compile(r"/module/access_roles(?:$|[?#])"), timeout=20_000)

    def edit_role(self, *, name: str, permissions: dict[str, str]) -> None:
        """Change what an existing role may do.

        Only the permissions are changed — deliberately not the name. The Edit
        screen offers a Role Name box and posts it, but ``RoleUpdate``
        (newschoolapp/api/api_models/roles.py) carries ``permissions`` alone, so
        the backend applies the grid and drops the name. See the note in
        tests/modules/governance/test_access_roles.py.
        """
        self.open_role_menu(name, EDIT_ROLE_ITEM)
        self.page.wait_for_url(re.compile(r"/access_roles/edit-access-role/\d+"), timeout=20_000)
        expect(self.page.get_by_role("heading", name=EDIT_ROLE_HEADING)).to_be_visible(
            timeout=20_000
        )
        expect(self.page.get_by_placeholder(ROLE_NAME_FIELD).first).to_have_value(name)

        for item, level in permissions.items():
            self.set_permission(item, level, levels=EDIT_LEVELS)

        expect(self.page.get_by_text(FORM_READY)).to_be_visible(timeout=10_000)
        self.click_button(SAVE_CHANGES)
        self.expect_toast(ROLE_UPDATED_TOAST, timeout_ms=20_000)
        self.page.wait_for_url(re.compile(r"/module/access_roles(?:$|[?#])"), timeout=20_000)

    def preview_role(self, name: str) -> None:
        """Open the read-only view of a role from its row menu."""
        self.open_role_menu(name, PREVIEW_ROLE_ITEM)
        self.page.wait_for_url(re.compile(r"/access_roles/preview-role/\d+"), timeout=20_000)
        expect(self.page.get_by_role("heading", name=PREVIEW_ROLE_HEADING)).to_be_visible(
            timeout=20_000
        )
        expect(self.page.get_by_placeholder(ROLE_NAME_FIELD).first).to_have_value(name)

    def delete_role(self, name: str) -> None:
        """Retire a role, confirming the modal names the one that was picked."""
        self.open_role_menu(name, DELETE_ROLE_ITEM)
        expect(self.page.get_by_text(DELETE_ROLE_MODAL)).to_be_visible(timeout=15_000)
        expect(self.page.get_by_text(re.compile(re.escape(name), re.I)).last).to_be_visible()
        self.click_button(DELETE_ROLE_CONFIRM)
        self.expect_toast(ROLE_DELETED_TOAST, timeout_ms=20_000)
        expect(self.role_row(name)).to_have_count(0, timeout=15_000)

    def open_role_menu(self, name: str, item: re.Pattern[str]) -> None:
        """Pick `item` from a role row's kebab menu.

        The kebab is the row's only button, and the menu it opens carries
        "Preview Role" for every role but "Edit role"/"Delete role" only for the
        ones this school added — page.tsx hides both for the seeded roles
        (admin, schooladmin, staff, guardian, teacher, non_teaching_staff,
        student), which is why those two are only ever asked of a custom role.
        """
        row = self.role_row(name).first
        expect(row).to_be_visible(timeout=15_000)
        row.get_by_role("button").last.click()
        self.page.get_by_role("menuitem", name=item).first.click()

    # ─────────────────── the role editor's permission grid ────────────────────

    def permission_row(self, item_name: str) -> Locator:
        """One module's row on the add/edit/preview role editor.

        Anchored on the row's own heading, because the three permission labels
        repeat once per module down the whole page.
        """
        heading = self.page.get_by_role(
            "heading", name=re.compile(rf"^\s*{re.escape(item_name)}\s*$", re.I)
        ).first
        return heading.locator(
            "xpath=ancestor::div[contains(@class,'border-gray-200')"
            " and contains(@class,'rounded-lg')][1]"
        )

    def set_permission(self, item_name: str, level: str,
                       *, levels: dict[str, re.Pattern[str]]) -> None:
        """Click a module row's permission level ("no-access"/"read"/"manage")."""
        if level not in levels:
            raise ValueError(f"Unknown permission level {level!r}; expected {sorted(levels)}.")
        row = self.permission_row(item_name)
        row.locator("label").filter(has_text=levels[level]).first.click()
        self.expect_permission(item_name, level, levels=levels)

    def expect_permission(self, item_name: str, level: str,
                          *, levels: dict[str, re.Pattern[str]]) -> None:
        """Assert which level a module row is showing as chosen."""
        row = self.permission_row(item_name)
        expect(
            row.locator("label").filter(has_text=levels[level]).first
        ).to_have_class(SELECTED_LEVEL_CLASS, timeout=10_000)

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

    def open_users_tab(self) -> "AccessRolesPage":
        """Bring the "Users & Roles" tab to the front.

        Both tabs share ONE search box — page.tsx renders a single input and
        swaps only its placeholder on ``activeTab`` ("Search role by name" ⇄
        "Search users by name, email, or role") — so nothing belonging to the
        users tab, the placeholder included, exists in the DOM until this runs.
        """
        self._ensure_open()
        self._open_tab(USERS_TAB)
        return self

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
        # Matched at the *end* of the path rather than anywhere in it: the role
        # editor screens (/add-access-role, /edit-access-role/{id},
        # /preview-role/{id}) all live under this route, so a plain substring
        # test would call the register open while it is nowhere on screen.
        if re.search(rf"{re.escape(self.URL)}/?(?:[?#].*)?$", self.page.url) is None:
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
