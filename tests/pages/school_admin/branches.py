"""SchoolAdmin → Branches page object (/module/school_admin_dashboard).

There is no ``/module/branches`` route. The branch list, the "Add Branch"
dialog and the branch-admin dialog all live on ``/module/school_admin_dashboard``
— the page renders an h1 of "Branches" and is where the frontend lands a
SchoolAdmin straight after login (``smsfrontend/src/middleware.ts``).

Cross-references for the admin-creation screens, so the wrong one is not used:

* ``create_branch_admin`` drives the "Create New Admin" dialog on *this* page
  ("Create Admin" toolbar button → ``POST /users/add_admin/{branch_id}``). It
  is the only screen that creates a user scoped to a single branch.
* The "New School Admin" button next to it opens a different dialog that adds a
  *school*-level admin (``POST /school_profile/{school_id}/admins``) and has no
  branch selector — not modelled here.
* ``/module/access_roles`` never creates an admin. It only re-roles users that
  already exist ("Make School Admin"), so branch-admin provisioning must not be
  routed through ``tests/pages/school_admin/access_roles.py``.

The new admin's password is not knowable from the UI: ``UserService.add_admin``
throws away whatever the form submits and generates its own. Wrap the call to
read the real credential out of QA mode::

    creds = capture_credentials(
        page,
        lambda: branches.create_branch_admin(branch_name="Main Campus", ...),
        url_substring="/add_admin/",
        email=admin_email,
    )
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, Response, TimeoutError as PlaywrightTimeoutError, expect

from tests.pages.base import BasePage

PAGE_HEADING = re.compile(r"^\s*Branches\s*$", re.I)

ADD_BRANCH_TRIGGER = re.compile(r"^\s*Add Branch\s*$", re.I)
SAVE_BUTTON = re.compile(r"^\s*Sav(e|ing)", re.I)
BRANCH_CREATED_TOAST = re.compile(r"successfully created a branch", re.I)

CREATE_ADMIN_TRIGGER = re.compile(r"^\s*Create Admin\s*$", re.I)
CREATE_ADMIN_SUBMIT = re.compile(r"^\s*Creat(e Admin|ing)", re.I)
ADMIN_CREATED_TOAST = re.compile(r"admin created successfully", re.I)

# Sets the SchoolAdmin's active branch in the frontend's branch store — see
# select_branch() for why that is mandatory before creating any person.
VIEW_BRANCH = re.compile(r"^\s*View\s*$", re.I)

# Both fields are label-associated; the alternation keeps the placeholder
# fallback in BasePage.fill_labeled working if the <label for=…> ever drops.
BRANCH_NAME_FIELD = re.compile(r"^\s*Name\s*$|^\s*Enter branch name", re.I)
BRANCH_LOCATION_FIELD = re.compile(r"^\s*Location\s*$|^\s*Enter branch location", re.I)

BRANCH_SELECT_PLACEHOLDER = re.compile(r"^\s*Select a branch\s*$", re.I)
GENDER_SELECT_PLACEHOLDER = re.compile(r"^\s*Select gender\s*$", re.I)
DATE_OF_BIRTH_FIELD = re.compile(r"^\s*Date of Birth\s*$", re.I)

# The Create New Admin form submits far more than the four arguments callers
# pass, and the backend rejects the frontend's empty-string defaults for
# date_of_birth (Optional[date], but required to be present). These fill the
# gap; the password only has to clear the client-side strength meter (8+ chars,
# uppercase, digit, symbol) because the server overwrites it anyway.
DEFAULT_ADMIN_GENDER = "Male"
DEFAULT_ADMIN_DATE_OF_BIRTH = "1990-01-01"
DEFAULT_ADMIN_PHONE = "0200000000"
DEFAULT_ADMIN_PASSWORD = "QaTest#2026"


class BranchesPage(BasePage):
    URL = "/module/school_admin_dashboard"

    def open(self) -> "BranchesPage":
        super().open()
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        return self

    # ───────────────────────── branches ─────────────────────────

    def create_branch(self, *, name: str, address: str, phone: str) -> int:
        """Create a branch through the "Add New Branch" dialog.

        The dialog has exactly two fields, Name and Location, so ``address``
        fills Location and ``phone`` is accepted only to keep the signature
        aligned with the other ``create_*`` page objects — a branch carries no
        phone number anywhere in the frontend or in ``SchoolBranchBase``.

        Returns the new branch id read from the ``POST /branch/`` response, or
        -1 if that response could not be captured: the table renders the id
        nowhere and rows link to /module/community rather than a branch route.
        """
        self.click_button(ADD_BRANCH_TRIGGER)
        dialog = self.dialog()
        expect(dialog).to_be_visible(timeout=10_000)

        self.fill_labeled(BRANCH_NAME_FIELD, name, in_dialog=True)
        self.fill_labeled(BRANCH_LOCATION_FIELD, address, in_dialog=True)

        response: Response | None = None
        try:
            with self.page.expect_response(_is_create_branch_response, timeout=30_000) as info:
                self._click_in_dialog(SAVE_BUTTON)
            response = info.value
        except PlaywrightTimeoutError:
            pass

        self.expect_toast(BRANCH_CREATED_TOAST, timeout_ms=15_000)
        expect(dialog).to_be_hidden(timeout=10_000)
        expect(self.find_row(name)).to_be_visible(timeout=15_000)

        return _branch_id_from(response)

    def find_row(self, name: str) -> Locator:
        """Row in the Branches table. The table is 1200px wide — use a desktop viewport."""
        return self.page.get_by_role("row").filter(
            has_text=re.compile(re.escape(name), re.I)
        ).first

    # ─────────────────────── branch admins ──────────────────────

    def select_branch(self, name: str) -> None:
        """Make ``name`` the SchoolAdmin's active branch.

        A SchoolAdmin belongs to no single branch, so the frontend resolves
        ``school_branch_id`` from a zustand store (``useBranchStore``) that is
        only populated by clicking "View" on a branch row here. Until that
        happens the store is null and every create sends ``school_branch_id: 0``,
        which the backend rejects with 404 "The Branch does not exist".

        So this is a prerequisite for creating staff, students or guardians as a
        SchoolAdmin — not an optional convenience. The store is persisted to
        localStorage, so one call covers the rest of the browser context.

        "View" navigates away as a side effect (see below); callers are expected
        to navigate on to wherever they were going *by route*, never by coming
        back through this page — its mount effect calls ``clearBranch()``.
        """
        self.open()
        row = self.find_row(name)
        expect(row).to_be_visible(timeout=20_000)
        row.get_by_role("button", name=VIEW_BRANCH).first.click()

        # The handler is `setBranch(branch); router.push("/module/community")`
        # (school_admin_dashboard/page.tsx) — the destination is hardcoded and
        # takes no account of the school's feature pack. On a pack without
        # `community` the community page's own 403 becomes a hard
        # `window.location` redirect to /auth/no-access
        # (smsfrontend/src/utils/handleErrorMessage.ts). Either landing means the
        # click was handled; the store write happens before the push in both, so
        # neither is a failure of *this* method.
        self.page.wait_for_url(
            re.compile(r"/module/community|/auth/no-access"), timeout=20_000
        )
        # What the method actually promises: the branch is in the persisted
        # store. It is written encrypted (lib/customStorage.ts), so its presence
        # under the persist key is as far as a test can read it.
        self.page.wait_for_function(
            "() => !!window.localStorage.getItem('branch-storage')", timeout=10_000
        )
        # Deliberately no navigation of our own from here. This page's mount
        # effect is `fetchBranches(); clearBranch();` — coming *back* to the
        # branches list wipes the selection this method just made — and
        # /auth/no-access renders no sidebar, so there is nothing to click from
        # either landing. Callers must reach their module by route
        # (``PageObject.open()``) and take the sidebar from there.

    def create_branch_admin(
        self,
        *,
        branch_name: str,
        email: str,
        first_name: str,
        last_name: str,
    ) -> None:
        """Create an Admin assigned to ``branch_name`` via the Create New Admin dialog.

        ``branch_name`` must already exist — the branch dropdown is populated
        from the same list the table renders, so call ``create_branch`` first.
        The role is fixed: the backend forces role "Admin" regardless of the
        ``role_id`` the form sends.
        """
        self.click_button(CREATE_ADMIN_TRIGGER)
        dialog = self.dialog()
        expect(dialog).to_be_visible(timeout=10_000)

        # Options read "<name> - <location>"; the submit button stays disabled
        # until a branch is picked, so this has to happen first.
        self.select_option_in_combobox(
            BRANCH_SELECT_PLACEHOLDER,
            re.compile(rf"^\s*{re.escape(branch_name)}\s*(-|$)", re.I),
        )

        self.fill_labeled(r"^First Name", _letters(first_name), in_dialog=True)
        self.fill_labeled(r"^Last Names?", _letters(last_name), in_dialog=True)
        self.fill_labeled(r"^Email", email, in_dialog=True)
        self.fill_labeled(r"^Primary Phone", DEFAULT_ADMIN_PHONE, in_dialog=True)
        self.fill_labeled(r"^Password", DEFAULT_ADMIN_PASSWORD, in_dialog=True)
        self.fill_labeled(r"^Confirm Password", DEFAULT_ADMIN_PASSWORD, in_dialog=True)

        self.select_option_in_combobox(
            GENDER_SELECT_PLACEHOLDER, re.compile(rf"^{DEFAULT_ADMIN_GENDER}$", re.I)
        )
        self._fill_date_of_birth(DEFAULT_ADMIN_DATE_OF_BIRTH)

        self._click_in_dialog(CREATE_ADMIN_SUBMIT)
        self.expect_toast(ADMIN_CREATED_TOAST, timeout_ms=20_000)
        expect(dialog).to_be_hidden(timeout=10_000)

    # ───────────────────────── internals ────────────────────────

    def _click_in_dialog(self, name: re.Pattern) -> None:
        """Scoped click: "Create Admin" names both the toolbar trigger and the
        dialog's submit, and the portalled dialog is never the first match."""
        self.dialog().get_by_role("button", name=name).first.click()

    def _fill_date_of_birth(self, value: str) -> None:
        self.commit_date(
            self.dialog().get_by_placeholder(DATE_OF_BIRTH_FIELD).first, value
        )


def _letters(value: str) -> str:
    """Name inputs silently drop anything outside /^[A-Za-z\\s]*$/."""
    return re.sub(r"[^A-Za-z\s]", "", value).strip()


def _is_create_branch_response(response: Response) -> bool:
    return (
        response.request.method == "POST"
        and re.search(r"/branch/?(\?|$)", response.url) is not None
    )


def _branch_id_from(response: Response | None) -> int:
    if response is None or not response.ok:
        return -1
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        return -1
    branch_id = payload.get("id") if isinstance(payload, dict) else None
    return int(branch_id) if isinstance(branch_id, (int, str)) and str(branch_id).isdigit() else -1
