"""Guardians page object (/module/guardians).

Creation runs the same three-step wizard the staff module uses
(``Basic Information → Contact Details → Admission Information``), rendered by
``smsfrontend/src/app/module/guardians/components`` and mounted at
``/module/guardians/add-guardians``. Each step's "Continue" stays disabled until
that step's starred fields are filled, so the flow below doubles as an assertion
that every value landed. The wizard has no password field — the frontend
hard-codes ``123456789`` for the new user, so guardian logins are known without
going through QA mode.

Wards (students) can only be attached while *creating* a guardian, hence
``create_guardian(ward_names=…)``; ``link_ward`` documents why there is no
after-the-fact linking action to drive. See its docstring.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

PAGE_HEADING = re.compile(r"^\s*Manage Guardians\s*$", re.I)

ADD_GUARDIAN_ROUTE = "/module/guardians/add-guardians"
ADD_GUARDIAN_TRIGGER = re.compile(r"^\s*Add Guardian\s*$", re.I)
CONTINUE_BUTTON = re.compile(r"^\s*Continue\s*$", re.I)
# The label flips to "Adding Guardian..." while the request is in flight.
SUBMIT_BUTTON = re.compile(r"^\s*Add(ing)? Guardian", re.I)
CREATED_TOAST = re.compile(r"guardian added successfully", re.I)

SEARCH_FIELD = re.compile(r"^\s*Search Guardian by name\b", re.I)

# ── the sidebar entry (components/common/SideNavigation/nav-config.tsx) ──────
# "Guardians" lives in the People Module section, which is ``branchOnly``: for a
# SchoolAdmin neither the section nor the entry is drawn until a branch has been
# selected (BranchesPage.select_branch).
NAV_PEOPLE_SECTION = re.compile(r"^\s*People Module\s*$", re.I)
NAV_GUARDIANS = re.compile(r"^\s*Guardians\s*$", re.I)

# The register's table, in the order page.tsx declares its <th>s. The first and
# last columns are the select-all checkbox and the per-row "View" link, both of
# which render no text.
GUARDIAN_COLUMN_HEADERS = (
    "", "Name", "Phone Number", "Address", "Marital Status", "Email", "",
)
GUARDIAN_COLUMNS = {
    "name": 1,
    "phone": 2,
    "address": 3,
    "marital_status": 4,
    "email": 5,
}
GUARDIANS_PANEL = re.compile(r"^\s*All Guardians\s*$", re.I)
# The panel PageError swaps in when the register's own fetch fails.
LOAD_FAILURE = re.compile(r"Failed to load guardians", re.I)

# ── the profile screen (/module/guardians/<id>) ──────────────────────────────
DETAIL_URL = re.compile(r"/module/guardians/(\d+)(?:[/?#]|$)")
BASIC_INFO_TAB = re.compile(r"^\s*Basic Info\s*$", re.I)
WARDS_TAB = re.compile(r"^\s*Wards\s*$", re.I)
NO_WARDS = re.compile(r"^\s*No Wards Found\s*$", re.I)
# Both rendered only for a role holding ("manage", "guardians") — page.tsx puts
# them behind the same ``isManage`` flag.
EDIT_PROFILE_BUTTON = re.compile(r"^\s*Edit Profile\s*$", re.I)
ASSIGN_WARD_BUTTON = re.compile(r"^\s*Assign Ward\s*$", re.I)
ASSIGN_WARD_MODAL = re.compile(r"^\s*Assign Existing Ward\s*$", re.I)
# The footer button flips to "Assigning..." while the POST is in flight.
ASSIGN_WARD_SUBMIT = re.compile(r"^\s*(Assign Ward|Assigning\.\.\.)\s*$", re.I)
WARD_ASSIGNED_TOAST = re.compile(r"ward assigned successfully", re.I)

# ── the edit wizard (/module/guardians/edit-guardian/<id>) ───────────────────
EDIT_URL = re.compile(r"/module/guardians/edit-guardian/\d+")
# The label flips to "Updating Guardian..." while the PUT is in flight; the same
# button reads "Add Guardian" when the wizard is in create mode.
UPDATE_BUTTON = re.compile(r"^\s*Updat(e|ing) Guardian", re.I)
UPDATED_TOAST = re.compile(r"guardian updated successfully", re.I)

EMPLOYER_FIELD = re.compile(
    r"^\s*Employer\s*$|^\s*Enter name of employer\s*$", re.I
)
WORK_ADDRESS_FIELD = re.compile(
    r"^\s*Work Address\s*$|^\s*Enter work address\s*$", re.I
)
DESCRIPTION_FIELD = re.compile(
    r"^\s*Description\s*$|^\s*Add additional remarks\s*$", re.I
)

# The wizard steps use bare <label> elements with no `for`, so get_by_label never
# binds and BasePage.fill_labeled falls through to the placeholder half of each
# alternation. The label half is kept for the day the association is added.
FIRST_NAME_FIELD = re.compile(r"^\s*First Name\s*\*?\s*$|^\s*Enter first name\s*$", re.I)
LAST_NAME_FIELD = re.compile(r"^\s*Last Name\s*\*?\s*$|^\s*Enter last name\s*$", re.I)
ADDRESS_FIELD = re.compile(
    r"^\s*Residential Address\s*\*?\s*$|^\s*Enter residential address\s*$", re.I
)
LOCATION_FIELD = re.compile(r"^\s*Location\s*\*?\s*$|^\s*Enter location\s*$", re.I)
# "Enter phone number" is also the secondary (optional) number's placeholder;
# fill_labeled takes the first match, which is the required primary phone.
PHONE_FIELD = re.compile(r"^\s*Phone Number\s*\*?\s*$|^\s*Enter phone number\s*$", re.I)
EMAIL_FIELD = re.compile(r"^\s*Email Address\s*\*?\s*$|^\s*Enter email address\s*$", re.I)
OCCUPATION_FIELD = re.compile(r"^\s*Occupation\s*\*?\s*$|^\s*Enter occupation\s*$", re.I)
RELATIONSHIP_FIELD = re.compile(
    r"^\s*Relationship With ward\(s\)\b|^\s*Enter your relationship\s*$", re.I
)

# Only one antd DatePicker is mounted per step, so the shared placeholder is safe.
# Built through as_pattern: the literal "dd/mm/yyyy" placeholder would
# otherwise close Playwright's /<source>/<flags> selector literal at its
# first slash.
DATE_PICKER_FIELD = as_pattern(r"^\s*dd/mm/yyyy\s*$")

GENDER_TRIGGER = re.compile(r"^\s*Select gender\s*$", re.I)

# Anchored so it cannot match the "Relationship With ward(s)" label above it.
WARDS_LABEL = re.compile(r"^\s*Ward\(s\)", re.I)
WARD_SEARCH_FIELD = re.compile(r"^\s*Search wards\b", re.I)
WARDS_SELECTED_NOTE = re.compile(r"\bward\(s\) selected\b", re.I)
ADMISSION_STEP_TAB = re.compile(r"^\s*Admission Information\s*$", re.I)

# The Contact and Admission steps star fields the caller has no opinion about,
# and "Continue"/"Add Guardian" stay disabled until they carry a value.
DEFAULT_GENDER = "Male"
DEFAULT_DATE_OF_BIRTH = "1990-01-01"
DEFAULT_LOCATION = "Accra"
DEFAULT_OCCUPATION = "Trader"


class GuardiansPage(BasePage):
    URL = "/module/guardians"

    def open(self) -> "GuardiansPage":
        super().open()
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        return self

    def open_from_nav(self) -> "GuardiansPage":
        """Reach the register the way a user does — the sidebar entry.

        A demo video has to show how someone gets to the module rather than
        teleport there, so recorded tests navigate with this; ``open`` stays the
        deep link for everything else. Falls back to the deep link when the
        sidebar is collapsed (narrow viewports), since the workspace is the
        point, not the way in.
        """
        link = self.page.get_by_role("navigation").get_by_role(
            "link", name=NAV_GUARDIANS
        ).first
        if link.count():
            link.click()
            self.page.wait_for_url(re.compile(r"/module/guardians"), timeout=25_000)
            expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
                timeout=25_000
            )
            return self
        return self.open()

    def expect_nav_entry(self) -> None:
        """The People section is on offer, and Guardians inside it.

        The section title is asserted too, so "the link is there" cannot pass off
        the back of a half-rendered sidebar. Scoped to the sidebar because
        /module/home's quick-action grid carries a card with the same label and
        href, and the profile screen's back link reads "Guardians" as well.
        """
        expect(self.page.get_by_text(NAV_PEOPLE_SECTION).first).to_be_visible(timeout=25_000)
        nav = self.page.get_by_role("navigation")
        expect(nav.get_by_role("link", name=NAV_GUARDIANS).first).to_be_visible(timeout=25_000)

    # ───────────────────────── the register ───────────────────────

    def expect_column_headers(self) -> None:
        """Assert the header row cell by cell, pinning the column order.

        ``cell()`` addresses columns positionally (``GUARDIAN_COLUMNS``), so a
        column that moved would otherwise make every later assertion read the
        wrong value rather than fail.
        """
        cells = self.page.locator("table thead tr").first.locator("th")
        expect(cells).to_have_count(len(GUARDIAN_COLUMN_HEADERS))
        for index, header in enumerate(GUARDIAN_COLUMN_HEADERS):
            expect(cells.nth(index)).to_have_text(header)

    def cell(self, email_or_name: str, column: str) -> Locator:
        """One cell of a guardian's row, addressed by column name."""
        if column not in GUARDIAN_COLUMNS:
            raise KeyError(f"unknown guardians column {column!r}; "
                           f"known: {sorted(GUARDIAN_COLUMNS)}")
        return self.find_row(email_or_name).get_by_role("cell").nth(
            GUARDIAN_COLUMNS[column]
        )

    def expect_no_load_failure(self) -> None:
        """The PageError panel the screen swaps in when its fetch fails."""
        expect(self.page.get_by_text(as_pattern(LOAD_FAILURE))).to_have_count(0)

    # ────────────────────────── creation ──────────────────────────

    def create_guardian(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        address: str,
        relationship: str = "Parent",
        gender: str = DEFAULT_GENDER,
        date_of_birth: str = DEFAULT_DATE_OF_BIRTH,
        location: str = DEFAULT_LOCATION,
        occupation: str = DEFAULT_OCCUPATION,
        ward_names: Sequence[str] = (),
    ) -> None:
        """Create a guardian through the three-step wizard.

        Call ``open()`` first; if the toolbar's "Add Guardian" trigger is not on
        screen (it renders only for users with "manage" on guardians) the route
        is opened directly instead.

        ``gender``/``date_of_birth``/``location``/``occupation`` are defaulted
        rather than required: they are starred in the form but carry no meaning
        for a guardian fixture. Dates are ISO "YYYY-MM-DD". ``relationship``
        fills the optional "Relationship With ward(s)" free-text field, which the
        backend stores as ``GuardianProfile.relationship_type``.

        ``ward_names`` selects existing students in the Ward(s) picker — full
        names as the students module renders them ("first_name other_names").
        This is the only guardian-side screen that actually persists the link
        (``POST /guardian/`` consumes ``student_ids``), so pass the wards here
        rather than reaching for ``link_ward``.
        """
        self._open_add_form()

        self.fill_labeled(FIRST_NAME_FIELD, _letters(first_name))
        self.fill_labeled(LAST_NAME_FIELD, _letters(last_name))
        self.select_option_in_combobox(GENDER_TRIGGER, _exact(gender))
        # Last on the step: the calendar overlay would sit on top of the select.
        self._fill_date(date_of_birth)
        self._continue(ADDRESS_FIELD)

        self.fill_labeled(ADDRESS_FIELD, address)
        self.fill_labeled(LOCATION_FIELD, _letters(location))
        self.fill_labeled(PHONE_FIELD, _digits(phone))
        self.fill_labeled(EMAIL_FIELD, email)
        self._continue(OCCUPATION_FIELD)

        self.fill_labeled(OCCUPATION_FIELD, _letters(occupation))
        self.fill_labeled(RELATIONSHIP_FIELD, _letters(relationship))
        self._select_wards(ward_names)

        button = self.page.get_by_role("button", name=SUBMIT_BUTTON).first
        expect(button).to_be_enabled(timeout=10_000)
        button.click()

        self.expect_toast(CREATED_TOAST, timeout_ms=20_000)

        # The wizard routes back to the list on success.
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        expect(self.find_row(email)).to_be_visible(timeout=20_000)

    def link_ward(self, *, guardian_name: str, student_name: str) -> None:
        """Not supported *through the edit wizard*; use ``assign_ward`` instead.

        The edit wizard renders the same Ward(s) picker the create wizard does,
        but its ``PUT /guardian/<id>`` is a dead end —
        ``GuardianService.update_guardian`` hands ``student_ids`` to a generic
        ``setattr`` loop and ``GuardianProfile`` has no such column (the link
        lives on the ``guardian_students`` association behind the ``students``
        relationship), so the request succeeds and changes nothing. Driving it
        would only produce a green test for a link that was never made.

        The three ways a ward link is actually written:

        * ``create_guardian(ward_names=[…])`` — ``POST /guardian/`` consumes
          ``student_ids``.
        * ``assign_ward(…)`` on the profile screen — the "Assign Ward" modal
          (``[guardianID]/components/AssignWardModal.tsx``) posting
          ``POST /guardian/<id>/wards/<student_id>``.
        * The Admit Student wizard's "Guardian's Name" picker, which sends
          ``guardian_id`` on ``POST /student/``
          (``tests/pages/people/students.py``).
        """
        raise NotImplementedError(
            "The guardians edit wizard silently drops student_ids on "
            "PUT /guardian/<id>. Pass ward_names to create_guardian, use "
            "assign_ward() on the profile screen, or select the guardian during "
            f"student admission ({student_name!r} → {guardian_name!r})."
        )

    # ───────────────────── the profile screen ─────────────────────

    def open_detail(self, email_or_name: str) -> int:
        """Open a guardian's profile from the register, returning its id.

        The id is read back off the URL rather than out of the create response:
        it is what every later API assertion addresses, and taking it from the
        screen proves the row really does link to the record it claims to.
        """
        row = self.find_row(email_or_name)
        expect(row).to_be_visible(timeout=20_000)
        row.get_by_role("link").first.click()
        self.page.wait_for_url(DETAIL_URL, timeout=25_000)
        expect(self.page.get_by_role("button", name=BASIC_INFO_TAB).first).to_be_visible(
            timeout=25_000
        )
        match = DETAIL_URL.search(self.page.url)
        assert match, (
            f"clicking the guardian's View link landed on {self.page.url!r}, "
            f"which carries no /module/guardians/<id>"
        )
        return int(match.group(1))

    def detail_value(self, label: str | re.Pattern) -> Locator:
        """The value the profile prints under ``label``.

        Every field on this screen is a caption element followed immediately by
        a ``<p>`` — ``<label>Occupation</label><p>…</p>`` in the Guardian Info
        and Basic Info panels, ``<p>Work Address</p><p>…</p>`` in More Info — so
        the caption's next ``<p>`` sibling is the value in both layouts.
        """
        caption = self.page.get_by_text(_exact(label)).first
        return caption.locator("xpath=following-sibling::p[1]")

    def open_wards_tab(self) -> None:
        self.page.get_by_role("button", name=WARDS_TAB).first.click()

    def expect_no_wards(self) -> None:
        expect(self.page.get_by_text(NO_WARDS).first).to_be_visible(timeout=20_000)

    def assign_ward(self, student_name: str) -> None:
        """Attach an existing student from the profile screen's "Assign Ward" modal.

        ``POST /guardian/<id>/wards/<student_id>``, which settles family
        membership first: a student who already belongs to a *different* family
        is refused 400 "Student already belongs to a family". That is deliberate
        (a student has at most one family), so a student admitted against
        another guardian cannot be assigned here.
        """
        self.page.get_by_role("button", name=ASSIGN_WARD_BUTTON).first.click()
        modal = self.page.locator(".ant-modal-content").last
        expect(modal.get_by_text(ASSIGN_WARD_MODAL).first).to_be_visible(timeout=10_000)

        # antd's Select puts role=combobox on the search input inside the modal.
        picker = modal.get_by_role("combobox").first
        picker.click()
        picker.fill(student_name)
        option = (
            self.page.locator(".ant-select-dropdown:visible .ant-select-item-option")
            .filter(has_text=re.compile(re.escape(student_name), re.I))
            .first
        )
        expect(option).to_be_visible(timeout=10_000)
        option.click()

        # The footer's own button, not the profile header's trigger of the same
        # name — hence the modal scope.
        modal.get_by_role("button", name=ASSIGN_WARD_SUBMIT).first.click()
        self.expect_toast(WARD_ASSIGNED_TOAST, timeout_ms=20_000)

    # ───────────────────────── the edit wizard ────────────────────

    def edit_profile(
        self,
        *,
        occupation: str | None = None,
        employer: str | None = None,
        work_address: str | None = None,
        relationship: str | None = None,
        description: str | None = None,
    ) -> None:
        """Correct a guardian from their profile screen's "Edit Profile" button.

        Call it while the profile is open. The editor is the same three-step
        wizard as the create form, prefilled from ``GET /guardian/<id>``, so the
        two Continue buttons only need clicking — every starred field already
        carries the value the guardian was created with.

        Only the Admission Information step's fields are offered here, and that
        is on purpose: ``edit-guardian/[guardianID]/page.tsx`` builds its
        ``PUT /guardian/<id>`` body from ``occupation``, ``additional_remarks``,
        ``relationship_type``, ``work_address``, ``employer_name``,
        ``student_ids`` and a ``user`` block of ``first_name``/``other_names``/
        ``profile_pic``/``religion`` only. The gender, date of birth, marital
        status, nationality, address, location, phone and email boxes the first
        two steps render are never sent, so a page object that offered them
        would be promising writes that cannot land.
        """
        self.page.get_by_role("button", name=EDIT_PROFILE_BUTTON).first.click()
        self.page.wait_for_url(EDIT_URL, timeout=25_000)

        # Step 1 and 2 are already complete; each Continue waits for its own
        # button to enable, which is what waits out the prefill fetch.
        self._await_step(FIRST_NAME_FIELD)
        self._continue(ADDRESS_FIELD)
        self._continue(OCCUPATION_FIELD)

        if occupation is not None:
            self.fill_labeled(OCCUPATION_FIELD, _letters(occupation))
        if employer is not None:
            self.fill_labeled(EMPLOYER_FIELD, _letters(employer))
        if work_address is not None:
            self.fill_labeled(WORK_ADDRESS_FIELD, work_address)
        if relationship is not None:
            self.fill_labeled(RELATIONSHIP_FIELD, _letters(relationship))
        if description is not None:
            self.fill_labeled(DESCRIPTION_FIELD, _letters(description))

        button = self.page.get_by_role("button", name=UPDATE_BUTTON).first
        expect(button).to_be_enabled(timeout=10_000)
        button.click()

        self.expect_toast(UPDATED_TOAST, timeout_ms=20_000)
        # The wizard routes back to the register on success.
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)

    # ──────────────────────────── lookup ──────────────────────────

    def find_row(self, email_or_name: str) -> Locator:
        """Row for ``email_or_name`` in the All Guardians table.

        Types the term into the toolbar search first: the table is
        server-paginated at 10 rows, and the backend's ``search`` matches first
        name, other names, full name, guardian id and email.

        The table only renders at the ``md`` breakpoint (below it the page
        switches to cards), so use a desktop viewport.
        """
        self.page.get_by_placeholder(SEARCH_FIELD).first.fill(email_or_name)
        return self.page.get_by_role("row").filter(
            has_text=re.compile(re.escape(email_or_name), re.I)
        ).first

    # ─────────────────────────── internals ────────────────────────

    def _open_add_form(self) -> None:
        trigger = self.page.get_by_role("button", name=ADD_GUARDIAN_TRIGGER)
        if trigger.count():
            trigger.first.click()
        else:
            self.page.goto(self.absolute(ADD_GUARDIAN_ROUTE))
        self._await_step(FIRST_NAME_FIELD)

    def _await_step(self, marker: re.Pattern[str]) -> None:
        expect(self.page.get_by_placeholder(marker).first).to_be_visible(timeout=20_000)

    def _continue(self, next_marker: re.Pattern[str]) -> None:
        button = self.page.get_by_role("button", name=CONTINUE_BUTTON).first
        expect(button).to_be_enabled(timeout=10_000)
        button.click()
        self._await_step(next_marker)

    def _fill_date(self, value: str) -> None:
        self.commit_date(self.page.get_by_placeholder(DATE_PICKER_FIELD).first,
                         value, display_format="%d/%m/%Y")

    def _select_wards(self, names: Sequence[str]) -> None:
        """Tick ``names`` in the Ward(s) dropdown on the Admission step.

        The picker loads the first 100 students of the branch once, on mount,
        and filters that snapshot client-side, so a ward beyond the hundredth
        student is simply not offerable here.
        """
        if not names:
            return

        trigger = self._wards_trigger()
        trigger.click()
        search = self.page.get_by_placeholder(WARD_SEARCH_FIELD).first
        expect(search).to_be_visible(timeout=10_000)

        for name in names:
            search.fill(name)
            option = self.page.get_by_role("listitem").filter(
                has_text=re.compile(re.escape(name), re.I)
            ).first
            expect(option).to_be_visible(timeout=10_000)
            option.click()

        # Dismiss by clicking outside rather than re-clicking the trigger: the
        # trigger is now covered by the selected wards' chips, each of which has
        # its own remove button.
        self.page.get_by_role("button", name=ADMISSION_STEP_TAB).first.click()
        expect(self.page.get_by_text(WARDS_SELECTED_NOTE).first).to_be_visible(timeout=10_000)

    def _wards_trigger(self) -> Locator:
        """The ward picker is a <div>, not a control, and its ``<label for="wards">``
        points at nothing, so anchor on the label and take the box after it."""
        label = self.page.locator("label").filter(has_text=WARDS_LABEL).first
        return label.locator("xpath=following-sibling::div[1]/div[1]")


def _exact(text: str | re.Pattern[str]) -> re.Pattern[str]:
    """Anchored matcher — an unanchored "Male" also matches "Female".

    A pattern is passed through untouched, so callers that already anchored
    their own (the profile screen's captions) can hand one straight in.
    """
    if isinstance(text, re.Pattern):
        return text
    return re.compile(rf"^\s*{re.escape(text)}\s*$", re.I)


def _picker_date(value: str) -> str:
    """The picker declares ``format="DD/MM/YYYY"``; the suite passes ISO dates."""
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def _letters(value: str) -> str:
    """Name-ish inputs silently drop anything outside /^[A-Za-z\\s]*$/."""
    return re.sub(r"[^A-Za-z\s]", "", value).strip()


def _digits(value: str) -> str:
    """The phone inputs strip non-digits and cap at 10 characters."""
    return re.sub(r"\D", "", value)[:10]
