"""People → Students page object (/module/students).

Admission runs through the wizard at ``/module/students/admit-student``. The
StepIndicator advertises four steps (Basic Information, Contact Details,
Admission Information, Extra Fees) but only three have to be driven: the
Admission Information "Continue" button is also the implicit submit of a
``<form onSubmit={… handleSubmit()}>``, so clicking it both advances the wizard
*and* POSTs the student. ``admit_student`` therefore only falls back to the
Extra Fees step's "Add Student" button when that POST did not already fire.

Worth knowing when a step transition times out: the Basic Information and
Contact Details forms carry no ``onSubmit`` handler and their "Continue"
buttons carry no ``type``, so each is the implicit submit of a handler-less
``<form>`` — a native GET submission reloads the page and resets the wizard to
step 1. Every step change is asserted here rather than assumed, so that surfaces
as a clear "next step never appeared" failure instead of a confusing one.
"""
from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError, expect

from tests.pages.base import BasePage, as_pattern

PAGE_HEADING = re.compile(r"^\s*Manage Students\s*$", re.I)

# "Students" lives in the People Module section of nav-config.tsx, which is
# ``branchOnly``: for a SchoolAdmin neither the section nor the entry is drawn
# until a branch has been picked (BranchesPage.select_branch). A teacher belongs
# to a branch already, so both are there as soon as the sidebar mounts.
NAV_PEOPLE_SECTION = re.compile(r"^\s*People Module\s*$", re.I)
NAV_STUDENTS = re.compile(r"^\s*Students\s*$", re.I)

# The roster's table, in the order StudentsTable declares its <th>s. The first
# column is the select-all checkbox, which renders no text.
STUDENT_COLUMN_HEADERS = ("", "Name", "Class", "Fee Group", "Status", "Gender", "Actions")
STUDENT_COLUMNS = {
    "name": 1,
    "class": 2,
    "fee_group": 3,
    "status": 4,
    "gender": 5,
    "actions": 6,
}
STUDENTS_PANEL = re.compile(r"^\s*All Students\s*$", re.I)
# The badge beside that heading, fed by the list response's ``total_count``.
STUDENT_TOTAL_BADGE = re.compile(r"^\s*(\d+)\s+students?\s+total\s*$", re.I)
SEARCH_PLACEHOLDER = re.compile(r"^\s*Search student by name\s*$", re.I)
# StudentsTableRow renders "Not Provided" for a student with no class, and the
# EmptyState the table swaps in when the branch has nobody to show.
NOT_PROVIDED = "Not Provided"
EMPTY_STATE = re.compile(r"^\s*No students found\s*$", re.I)
# The two PageError panels this screen can render instead of its content.
STATS_LOAD_FAILURE = re.compile(r"Failed to load statistics", re.I)
LOAD_FAILURE = re.compile(r"Failed to load students", re.I)

# ModuleHeader's three tiles (students/page.tsx builds them from
# GET /statistics/student).
STAT_TOTAL = re.compile(r"^\s*Total Students\s*$", re.I)
STAT_MALE = re.compile(r"^\s*Male Count\s*$", re.I)
STAT_FEMALE = re.compile(r"^\s*Female Count\s*$", re.I)

# Everything StudentsTableToolbar puts behind ``isManage`` — a role holding only
# ("read", "students") is offered none of them.
MANAGE_CONTROLS = (
    re.compile(r"^\s*Admit Student\s*$", re.I),
    re.compile(r"^\s*Bulk Admission\s*$", re.I),
    re.compile(r"^\s*Promote Selected", re.I),
    re.compile(r"^\s*Promote Entire Class\s*$", re.I),
)

ADMIT_TRIGGER = re.compile(r"^\s*Admit Student\s*$", re.I)
CONTINUE_BUTTON = re.compile(r"^\s*Continue\s*$", re.I)
# The Extra Fees step swaps its label to "Adding Student..." while in flight.
ADD_STUDENT_BUTTON = re.compile(r"^\s*Add(ing)? Student", re.I)

# None of the wizard's <label>s are associated with their control (no htmlFor,
# no wrapping), so every pattern also spells the placeholder that
# BasePage.fill_labeled falls back to.
FIRST_NAME_FIELD = re.compile(r"^\s*First Name\s*\*?\s*$|^\s*Enter first name\s*$", re.I)
LAST_NAME_FIELD = re.compile(r"^\s*Last Name\s*\*?\s*$|^\s*Enter last name\s*$", re.I)
EMAIL_FIELD = re.compile(r"^\s*Email\s*\*?\s*$|^\s*Enter email\s*$", re.I)
ADDRESS_FIELD = re.compile(r"^\s*Residential Address\b|^\s*Enter residential address\s*$", re.I)
LOCATION_FIELD = re.compile(r"^\s*Location\b|^\s*Enter location\s*$", re.I)
PREVIOUS_SCHOOL_FIELD = re.compile(r"^\s*Previous School\s*$|^\s*Enter previous school\s*$", re.I)

# Built through as_pattern: the literal "dd/mm/yyyy" placeholder would
# otherwise close Playwright's /<source>/<flags> selector literal at its
# first slash.
DATE_OF_BIRTH_PLACEHOLDER = as_pattern(r"^\s*dd/mm/yyyy\s*$")
BASIC_STEP_MARKER = re.compile(r"^\s*Enter first name\s*$", re.I)
CONTACT_STEP_MARKER = re.compile(r"^\s*Enter residential address\s*$", re.I)

GENDER_PLACEHOLDER = re.compile(r"^\s*Select gender\s*$", re.I)
CLASS_PLACEHOLDER = re.compile(r"^\s*Select class\s*$", re.I)
BLOOD_TYPE_PLACEHOLDER = re.compile(r"^\s*Select blood type\s*$", re.I)
BLOOD_TYPE_LABEL = re.compile(r"^\s*Student Blood Type\s*$", re.I)
DESCRIPTION_FIELD = re.compile(
    r"^\s*Description\s*$|^\s*Add additional remarks\s*$", re.I
)
# The Admission Information step's own textarea placeholder — the one marker of
# that step that is there whether or not its selects already carry a value.
ADMISSION_STEP_MARKER = re.compile(r"^\s*Add additional remarks\s*$", re.I)

STUDENT_ADMITTED_TOAST = re.compile(r"student admitted successfully", re.I)
STUDENT_UPDATED_TOAST = re.compile(r"student updated successfully", re.I)

# ── the profile screen (/module/students/<id>) ──────────────────────────────
DETAIL_URL = re.compile(r"/module/students/(\d+)(?:[/?#]|$)")
BASIC_INFO_TAB = re.compile(r"^\s*Basic Info\s*$", re.I)
GUARDIAN_TAB = re.compile(r"^\s*Guardian\s*$", re.I)
# Rendered only for a role holding ("manage", "students") — page.tsx puts the
# whole action cluster behind its ``isManage`` flag.
EDIT_BUTTON = re.compile(r"^\s*Edit\s*$", re.I)

# ── the edit wizard (/module/students/edit-student/<id>) ────────────────────
EDIT_URL = re.compile(r"/module/students/edit-student/(\d+)")
# The final step's submit reads "Update Student" once the prefill has landed
# (AdmissionInformation renders it in place of "Continue" when the record
# already carries a student_id), and flips to "Updating Student..." in flight.
UPDATE_BUTTON = re.compile(r"^\s*Updat(e|ing) Student", re.I)


class StudentsPage(BasePage):
    URL = "/module/students"

    def open(self) -> "StudentsPage":
        super().open()
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        return self

    def open_from_nav(self) -> "StudentsPage":
        """Reach the roster the way a user does — the sidebar entry.

        A demo video has to show how someone gets to the module rather than
        teleport there, so recorded tests navigate with this; ``open`` stays the
        deep link for everything else. Falls back to the deep link when the
        sidebar is collapsed (narrow viewports), since the workspace is the
        point, not the way in.
        """
        link = self.page.get_by_role("navigation").get_by_role(
            "link", name=NAV_STUDENTS
        ).first
        if link.count():
            link.click()
            self.page.wait_for_url(re.compile(r"/module/students"), timeout=25_000)
            expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
                timeout=25_000
            )
            return self
        return self.open()

    def expect_nav_entry(self) -> None:
        """The People section is on offer, and Students inside it.

        The section title is asserted too, so "the link is there" cannot pass off
        the back of a half-rendered sidebar. Scoped to the sidebar because
        /module/home's quick-action grid carries a card with the same label.
        """
        expect(self.page.get_by_text(NAV_PEOPLE_SECTION).first).to_be_visible(timeout=25_000)
        nav = self.page.get_by_role("navigation")
        expect(nav.get_by_role("link", name=NAV_STUDENTS).first).to_be_visible(timeout=25_000)

    # ───────────────────────── the roster ─────────────────────────

    def stat(self, name: str | re.Pattern) -> Locator:
        """The value of one ModuleHeader tile, addressed by its caption.

        ModuleHeader lays each tile out as ``<dt>caption</dt><dd>value</dd>``, so
        the caption's sibling is the number on screen.
        """
        caption = self.page.locator("dt").filter(has_text=as_pattern(name)).first
        return caption.locator("xpath=following-sibling::dd").first

    def expect_column_headers(self) -> None:
        """Assert the header row cell by cell, pinning the column order.

        ``cell()`` addresses columns positionally (``STUDENT_COLUMNS``), so a
        column that moved would otherwise make every later assertion read the
        wrong value rather than fail.
        """
        cells = self.page.locator("table thead tr").first.locator("th")
        expect(cells).to_have_count(len(STUDENT_COLUMN_HEADERS))
        for index, header in enumerate(STUDENT_COLUMN_HEADERS):
            expect(cells.nth(index)).to_have_text(header)

    def cell(self, name: str, column: str) -> Locator:
        """One cell of a student's row, addressed by column name."""
        if column not in STUDENT_COLUMNS:
            raise KeyError(f"unknown students column {column!r}; "
                           f"known: {sorted(STUDENT_COLUMNS)}")
        return self.find_row(name).get_by_role("cell").nth(STUDENT_COLUMNS[column])

    def search(self, term: str) -> None:
        """Type into "Search student by name".

        The box is server-side: every change re-issues ``GET /student/`` with a
        ``search`` parameter, so the caller must wait on the rows rather than
        assume the table has already caught up.
        """
        self.page.get_by_placeholder(SEARCH_PLACEHOLDER).first.fill(term)

    def expect_no_load_failure(self) -> None:
        """Neither PageError panel is on screen.

        Both are what this page renders in place of its content when a fetch
        fails, and either one would make an assertion about an empty table pass
        for entirely the wrong reason.
        """
        expect(self.page.get_by_text(STATS_LOAD_FAILURE)).to_have_count(0)
        expect(self.page.get_by_text(LOAD_FAILURE)).to_have_count(0)

    # ───────────────────────── admission ──────────────────────────

    def admit_student(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        gender: str,
        date_of_birth: str,
        address: str,
        location: str,
        guardian_name: str,
        class_name: str,
        previous_school: str = "",
        blood_type: str = "O+",
    ) -> None:
        """Admit a student through the multi-step wizard.

        ``gender`` is "Male" or "Female"; ``date_of_birth`` is "YYYY-MM-DD"
        (converted to the picker's DD/MM/YYYY on the way in). Whatever is passed
        for ``class_name`` and ``guardian_name`` must already exist — both
        dropdowns are populated from the branch's own records, so create the
        class and the guardian first. The admission date is left at the form's
        default (today).

        Both are optional in the form and may be passed as ``""`` to skip that
        picker entirely. That is not a shortcut: the fields are labelled
        "(Optional)" and neither is in the step's ``requiredFields``, and a
        school whose feature pack omits ``guardians`` or
        ``classes_and_timetables`` has no such record to offer — the admission
        wizard is still theirs to use.

        Ends on ``/module/students`` with the toast asserted, so ``find_row``
        can be called straight after.
        """
        self.click_button(ADMIT_TRIGGER)
        expect(self.page.get_by_placeholder(BASIC_STEP_MARKER).first).to_be_visible(timeout=20_000)

        self._fill_basic_information(
            first_name=first_name,
            last_name=last_name,
            email=email,
            gender=gender,
            date_of_birth=date_of_birth,
        )
        self._continue(self.page.get_by_placeholder(CONTACT_STEP_MARKER).first)

        self._fill_contact_details(
            address=address,
            location=location,
            guardian_name=guardian_name,
            previous_school=previous_school,
        )
        self._continue(
            self.page.get_by_role("combobox").filter(has_text=BLOOD_TYPE_PLACEHOLDER).first
        )

        self._fill_admission_information(class_name=class_name, blood_type=blood_type)
        self._submit()

        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)

    def find_row(self, name: str) -> Locator:
        """Row in the Students table.

        The list is server-paginated at 25 rows and filtered server-side by the
        "Search student by name" box, so a student outside the first page will
        not be matched by this locator alone.
        """
        return self.page.get_by_role("row").filter(
            has_text=re.compile(re.escape(name), re.I)
        ).first

    # ───────────────────── the profile screen ─────────────────────

    def open_detail(self, name: str) -> int:
        """Open a student's record from the roster, returning its id.

        The id is read back off the URL rather than out of the create response:
        it is what every later API assertion addresses, and taking it from the
        screen proves the row really does link to the record it claims to.

        The row's last cell carries the only link in it ("View"), and
        StudentsTableRow renders that link only while the student is active.
        """
        row = self.find_row(name)
        expect(row).to_be_visible(timeout=20_000)
        row.get_by_role("link").first.click()
        self.page.wait_for_url(DETAIL_URL, timeout=25_000)
        expect(self.page.get_by_role("button", name=BASIC_INFO_TAB).first).to_be_visible(
            timeout=25_000
        )
        match = DETAIL_URL.search(self.page.url)
        assert match, (
            f"clicking the student's View link landed on {self.page.url!r}, "
            f"which carries no /module/students/<id>"
        )
        return int(match.group(1))

    def detail_value(self, label: str | re.Pattern) -> Locator:
        """The value the profile prints under ``label``.

        Every field of every tab is one ``InfoField``:
        ``<div><p>Caption</p><p>value</p></div>`` (the caption is upper-cased in
        CSS only, so it is still matched by the text the source spells). A field
        that was never filled prints "Not Provided".
        """
        caption = self.page.get_by_text(_exact(label)).first
        return caption.locator("xpath=following-sibling::p[1]")

    def open_tab(self, name: str | re.Pattern) -> None:
        self.page.get_by_role("button", name=_exact(name)).first.click()

    # ─────────────────────── the edit wizard ──────────────────────

    def edit_student(
        self,
        *,
        address: str | None = None,
        location: str | None = None,
        previous_school: str | None = None,
        blood_type: str | None = None,
        description: str | None = None,
    ) -> int:
        """Correct a student from their profile screen's "Edit" button.

        Call it while the profile is open; returns the id in the wizard's URL so
        the caller can prove the edit amended the record it opened rather than
        creating a second one.

        The wizard is the same three steps as admission (there is no Extra Fees
        step here), prefilled from ``GET /student/<id>``, so the two Continue
        buttons only need clicking — every starred field already carries the
        value the student was admitted with.

        Only the fields ``edit-student/[editstudentId]/page.tsx`` actually sends
        are offered. Its ``PUT /student/<id>`` body carries
        ``date_of_admission``, ``previous_school``, ``blood_type``,
        ``additional_remarks``, ``guardian_id``, ``class_id`` and a ``user``
        block of name/gender/date of birth/nationality/religion/address/
        location/phones — but *not* the email box step 1 renders, so a page
        object that offered an email change would be promising a write that
        cannot land.
        """
        self.page.get_by_role("button", name=EDIT_BUTTON).first.click()
        self.page.wait_for_url(EDIT_URL, timeout=25_000)
        match = EDIT_URL.search(self.page.url)
        assert match, (
            f"the profile's Edit button landed on {self.page.url!r}, which "
            f"carries no /module/students/edit-student/<id>"
        )

        # Waiting for the first step's own input is what waits out the prefill
        # fetch: until it answers the page renders a "Loading Student" spinner.
        expect(self.page.get_by_placeholder(BASIC_STEP_MARKER).first).to_be_visible(
            timeout=25_000
        )
        self._continue_when_enabled(self.page.get_by_placeholder(CONTACT_STEP_MARKER).first)

        if address is not None:
            self.fill_labeled(ADDRESS_FIELD, address)
        if location is not None:
            self.fill_labeled(LOCATION_FIELD, _letters(location))
        if previous_school is not None:
            self.fill_labeled(PREVIOUS_SCHOOL_FIELD, _letters(previous_school))
        # Not the blood-type trigger the admission flow waits on: this record
        # already has a blood type, so that trigger renders the value rather
        # than its placeholder. The remarks box is on this step and no other.
        self._continue_when_enabled(
            self.page.get_by_placeholder(ADMISSION_STEP_MARKER).first
        )

        if blood_type is not None:
            # Anchored on the <label>, for the same reason: a Radix trigger that
            # already carries a value cannot be found by its placeholder text.
            self.select_option_by_label(BLOOD_TYPE_LABEL, _exact(blood_type))
        if description is not None:
            self.fill_labeled(DESCRIPTION_FIELD, _letters(description))

        button = self.page.get_by_role("button", name=UPDATE_BUTTON).first
        expect(button).to_be_enabled(timeout=10_000)
        button.click()

        self.expect_toast(STUDENT_UPDATED_TOAST, timeout_ms=30_000)
        # The wizard routes back to the roster on success.
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        return int(match.group(1))

    # ──────────────────────── wizard steps ────────────────────────

    def _fill_basic_information(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        gender: str,
        date_of_birth: str,
    ) -> None:
        self.fill_labeled(FIRST_NAME_FIELD, _letters(first_name))
        self.fill_labeled(LAST_NAME_FIELD, _letters(last_name))
        # Date of birth goes in before gender and email on purpose: the antd
        # picker commits a typed value on Enter without preventing the default,
        # which would implicitly submit this handler-less <form>. The browser
        # skips implicit submission while the form's default button ("Continue")
        # is disabled, and it stays disabled until every required field is set.
        self._fill_date_of_birth(date_of_birth)
        self.select_option_in_combobox(GENDER_PLACEHOLDER, _exact(gender))
        self.fill_labeled(EMAIL_FIELD, email)

    def _fill_contact_details(
        self,
        *,
        address: str,
        location: str,
        guardian_name: str,
        previous_school: str,
    ) -> None:
        self.fill_labeled(ADDRESS_FIELD, address)
        self.fill_labeled(LOCATION_FIELD, _letters(location))
        if guardian_name:
            self._select_guardian(guardian_name)
        if previous_school:
            self.fill_labeled(PREVIOUS_SCHOOL_FIELD, _letters(previous_school))

    def _fill_admission_information(self, *, class_name: str, blood_type: str) -> None:
        # The class trigger reads "Loading classes..." until /classes/ answers,
        # so filtering on "Select class" doubles as the wait for that fetch.
        if class_name:
            self.select_option_in_combobox(CLASS_PLACEHOLDER, _exact(class_name))
        self.select_option_in_combobox(BLOOD_TYPE_PLACEHOLDER, _exact(blood_type))

    # ───────────────────────── internals ──────────────────────────

    def _continue(self, next_marker: Locator) -> None:
        self.click_button(CONTINUE_BUTTON)
        expect(next_marker).to_be_visible(timeout=20_000)

    def _continue_when_enabled(self, next_marker: Locator) -> None:
        """``_continue``, but waits for the button to enable first.

        The edit wizard's steps are prefilled by a fetch, and every "Continue"
        stays disabled until that step's required fields carry a value — so a
        click issued too early lands on a disabled button and the step never
        changes.
        """
        button = self.page.get_by_role("button", name=CONTINUE_BUTTON).first
        expect(button).to_be_enabled(timeout=20_000)
        button.click()
        expect(next_marker).to_be_visible(timeout=20_000)

    def _submit(self) -> None:
        """Finish the wizard from the Admission Information step.

        Its "Continue" is the form's implicit submit, so the POST fires here
        while the wizard also moves on to Extra Fees. Waiting on the toast
        rather than on that step is deliberate: Extra Fees renders immediately
        and the POST only answers a round trip later, so keying off the button
        would press "Add Student" on top of an admission already in flight.
        """
        self.click_button(CONTINUE_BUTTON)
        try:
            expect(self.toast(STUDENT_ADMITTED_TOAST).first).to_be_visible(timeout=30_000)
            return
        except AssertionError:
            pass

        # No POST came out of Admission Information — submit from Extra Fees.
        self.page.get_by_role("button", name=ADD_STUDENT_BUTTON).first.click()
        self.expect_toast(STUDENT_ADMITTED_TOAST, timeout_ms=30_000)

    def _fill_date_of_birth(self, value: str) -> None:
        self.commit_date(
            self.page.get_by_placeholder(DATE_OF_BIRTH_PLACEHOLDER).first,
            value, display_format="%d/%m/%Y",
        )

    def _select_guardian(self, name: str) -> None:
        """Pick an existing guardian out of the antd "Select a guardian" select.

        antd renders its trigger as a searchable ``role=combobox`` input whose
        placeholder is a sibling node, so it cannot be reached through
        ``BasePage.select_option_in_combobox`` (which filters triggers by their
        own text). It is the only combobox on the Contact Details step.

        The options are matched on ``.ant-select-item-option`` rather than
        ``role=option`` on purpose. antd v5 mirrors the list twice: an
        accessibility-only ``role=listbox`` rendered at ``height:0;width:0;
        overflow:hidden`` (whose children carry ``role=option``) and the real
        rc-virtual-list rows, which carry no role at all. So ``get_by_role
        ("option")`` finds only the 0x0 mirror and any wait for it to become
        visible times out — the accessible node is never visible and the
        visible node is never accessible.
        """
        combobox = self.page.get_by_role("combobox").first
        combobox.click()
        # Typing drives the component's onSearch, which filters the branch's
        # guardians client-side (filterOption is false).
        combobox.fill(name)

        # Options read "<first> <other> (ID: <guardian_id>)"; the "(ID:" tail
        # also keeps the empty "Select a guardian" entry out of the match, which
        # the frontend's onChange cannot parse.
        option = self.page.locator(".ant-select-item-option").filter(
            has_text=re.compile(rf"^\s*{re.escape(name)}\s*\(ID:", re.I)
        ).first
        try:
            option.wait_for(state="visible", timeout=15_000)
        except PlaywrightTimeoutError as exc:
            raise AssertionError(
                f"No guardian matching {name!r} in the 'Select a guardian' dropdown — "
                "it only lists guardians that already exist for this branch."
            ) from exc

        option.click()
        expect(combobox).to_have_attribute("aria-expanded", "false", timeout=10_000)


def _exact(value: str | re.Pattern[str]) -> re.Pattern[str]:
    """Anchored matcher — an unanchored "Male" also matches "Female".

    A pattern is passed through untouched, so callers that already anchored
    their own (the profile screen's captions) can hand one straight in.
    """
    if isinstance(value, re.Pattern):
        return value
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)


def _letters(value: str) -> str:
    """The name, location and previous-school inputs drop anything outside /[A-Za-z\\s]/."""
    return re.sub(r"[^A-Za-z\s]", "", value).strip()


def _picker_date(value: str) -> str:
    """The date-of-birth picker is formatted DD/MM/YYYY; callers pass ISO."""
    text = value.strip()
    try:
        return date.fromisoformat(text).strftime("%d/%m/%Y")
    except ValueError:
        return text
