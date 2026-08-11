"""Staff page object (/module/staff).

The list page carries two tabs — "Teaching Staff" (``GET /teacher/``) and
"Non-teaching Staff" (``GET /non-teaching/``) — and each tab's toolbar shows its
own "Add …" button, so the tab has to be selected before the trigger is clicked.

Both creation screens are the same three-step wizard
(``Basic Information → Contact Details → Admission Information``) rendered by
``smsfrontend/src/app/module/staff/components``; only the Admission step
differs. Every step's "Continue" stays disabled until the starred fields on it
are filled, so the flows below double as assertions that each value landed.

Neither wizard has a password field: the frontend hard-codes ``123456789`` for
the new user, so staff logins are known without going through QA mode.
"""
from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

PAGE_HEADING = re.compile(r"^\s*Manage Staff\s*$", re.I)

# Tab buttons carry a count badge ("Teaching Staff 3"), so never anchor the tail.
TEACHING_TAB = re.compile(r"^\s*Teaching Staff\b", re.I)
NON_TEACHING_TAB = re.compile(r"^\s*Non-teaching Staff\b", re.I)

SEARCH_FIELD = re.compile(r"^\s*Search staff by name\s*$", re.I)

# ── the sidebar entry (components/common/SideNavigation/nav-config.tsx) ──────
# "Staff" lives in the People Module section, which is ``branchOnly``: for a
# SchoolAdmin neither the section nor the entry is drawn until a branch has been
# selected (BranchesPage.select_branch).
NAV_PEOPLE_SECTION = re.compile(r"^\s*People Module\s*$", re.I)
NAV_STAFF = re.compile(r"^\s*Staff\s*$", re.I)

# The Teaching Staff tab's table, in the order page.tsx declares its <th>s. The
# last column is the per-row "View" link, whose header cell is empty. The
# Non-teaching tab inserts a "Role" column after Phone Number and swaps
# "Subject(s) Taught" for "Job Title", so this tuple is the teaching tab's only.
TEACHING_COLUMN_HEADERS = (
    "Name", "Email Address", "Phone Number", "Subject(s) Taught", "Status",
    "Date of Hire", "",
)
TEACHING_COLUMNS = {
    "name": 0,
    "email": 1,
    "phone": 2,
    "subjects": 3,
    "status": 4,
    "hire_date": 5,
}
# The PageError panel the list swaps in when its own fetch fails.
LOAD_FAILURE = re.compile(r"Failed to load staff data", re.I)
NO_TEACHING_STAFF = re.compile(r"^\s*No teaching staff found\s*$", re.I)

ADD_TEACHING_TRIGGER = re.compile(r"^\s*Add Teaching Staff\s*$", re.I)
ADD_NON_TEACHING_TRIGGER = re.compile(r"^\s*Add Non-teaching Staff\s*$", re.I)

CONTINUE_BUTTON = re.compile(r"^\s*Continue\s*$", re.I)
# The label flips to "Adding Staff..." while the request is in flight.
SUBMIT_TEACHING = re.compile(r"^\s*Add(ing)? Staff", re.I)
SUBMIT_NON_TEACHING = re.compile(r"^\s*Add(ing)? Non-teaching Staff", re.I)

# The steps use bare <label> elements with no `for`, so get_by_label never binds
# and BasePage.fill_labeled falls through to the placeholder half of each
# alternation. The label half is kept for the day the association is added.
FIRST_NAME_FIELD = re.compile(r"^\s*First Name\s*\*?\s*$|^\s*Enter first name\s*$", re.I)
LAST_NAME_FIELD = re.compile(r"^\s*Last Name\s*\*?\s*$|^\s*Enter last name\s*$", re.I)
NATIONALITY_FIELD = re.compile(r"^\s*Nationality\s*\*?\s*$|^\s*Enter your nationality\s*$", re.I)
DIALECT_FIELD = re.compile(r"^\s*Local Dialect\s*\*?\s*$|^\s*Enter your local dialect\s*$", re.I)
ADDRESS_FIELD = re.compile(
    r"^\s*Residential Address\s*\*?\s*$|^\s*Enter residential address\s*$", re.I
)
LOCATION_FIELD = re.compile(r"^\s*Location\s*\*?\s*$|^\s*Enter location\s*$", re.I)
# "Enter phone number" is also the secondary (optional) number's placeholder;
# fill_labeled takes the first match, which is the required primary phone.
PHONE_FIELD = re.compile(r"^\s*Phone Number\s*\*?\s*$|^\s*Enter phone number\s*$", re.I)
EMAIL_FIELD = re.compile(r"^\s*Email Address\s*\*?\s*$|^\s*Enter email address\s*$", re.I)
RELIGION_FIELD = re.compile(r"^\s*Religion\s*\*?\s*$|^\s*Enter your religion\s*$", re.I)
JOB_TITLE_FIELD = re.compile(r"^\s*Job Title\s*\*?\s*$|^\s*Enter title\s*$", re.I)
FIELD_OF_STUDY_FIELD = re.compile(
    r"^\s*Field of Study\s*\*?\s*$|^\s*Enter field of study\s*$", re.I
)

# Only one antd DatePicker is mounted per step, so the shared placeholder is safe.
# Built through as_pattern: the literal "dd/mm/yyyy" placeholder would otherwise
# close Playwright's `/<source>/<flags>` selector literal at its first slash.
DATE_PICKER_FIELD = as_pattern(r"^\s*dd/mm/yyyy\s*$")

GENDER_TRIGGER = re.compile(r"^\s*Select gender\s*$", re.I)
MARITAL_STATUS_TRIGGER = re.compile(r"^\s*Select status\s*$", re.I)
EMPLOYMENT_TYPE_TRIGGER = re.compile(r"^\s*Select employment type\s*$", re.I)
DEGREE_TRIGGER = re.compile(r"^\s*Select degree\s*$", re.I)
# The role Select initialises to role_id 0, which matches no option, so Radix
# renders an EMPTY trigger instead of this placeholder — match its label.
ROLE_LABEL = re.compile(r"^\s*Non teaching Staff Role\s*$", re.I)

# Anchored: "staff added successfully" alone also matches the non-teaching toast.
TEACHING_CREATED_TOAST = re.compile(r"^\s*Staff added successfully", re.I)
NON_TEACHING_CREATED_TOAST = re.compile(r"Non-teaching staff added successfully", re.I)

# ── the profile screen (/module/staff/<id>) ─────────────────────────────────
DETAIL_URL = re.compile(r"/module/staff/(\d+)(?:[/?#]|$)")
BASIC_INFO_TAB = re.compile(r"^\s*Basic Info\s*$", re.I)
ACADEMICS_TAB = re.compile(r"^\s*Academics\s*$", re.I)
NO_SUBJECTS_ASSIGNED = re.compile(r"^\s*No subjects assigned yet\.\s*$", re.I)
# Rendered only for a role holding ("manage", "staff") — page.tsx puts it behind
# its ``isManage`` flag. It is a <button> wrapped in a <Link>.
EDIT_PROFILE_BUTTON = re.compile(r"^\s*Edit Profile\s*$", re.I)
PROFILE_LOAD_FAILURE = re.compile(r"Failed to load staff profile", re.I)

# ── the edit wizard (/module/staff/edit-staff/<id>) ─────────────────────────
EDIT_URL = re.compile(r"/module/staff/edit-staff/\d+")
# The same button reads "Add Staff" in create mode, and flips to
# "Updating Staff..." while the PUT is in flight.
SUBMIT_UPDATE = re.compile(r"^\s*Updat(e|ing) Staff", re.I)
UPDATED_TOAST = re.compile(r"Staff updated successfully", re.I)
DESCRIPTION_FIELD = re.compile(
    r"^\s*Description\s*$|^\s*Add additional remarks\s*$", re.I
)
# The Radix Select trigger shows the *selected* label once the edit wizard has
# prefilled it ("Full-time"), never its placeholder, so the create flow's
# placeholder-anchored matcher finds nothing here — anchor on the <label>.
EMPLOYMENT_TYPE_LABEL = re.compile(r"^\s*Employment Type\s*\*?\s*$", re.I)
DEGREE_LABEL = re.compile(r"^\s*Highest Degree Earned\s*$", re.I)

_APOSTROPHES = "['’]"


class StaffPage(BasePage):
    URL = "/module/staff"

    def open(self) -> "StaffPage":
        super().open()
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        return self

    def open_from_nav(self) -> "StaffPage":
        """Reach the register the way a user does — the sidebar entry.

        A demo video has to show how someone gets to the module rather than
        teleport there, so recorded tests navigate with this; ``open`` stays the
        deep link for everything else. Falls back to the deep link when the
        sidebar is collapsed (narrow viewports), since the workspace is the
        point, not the way in.
        """
        link = self.page.get_by_role("navigation").get_by_role(
            "link", name=NAV_STAFF
        ).first
        if link.count():
            link.click()
            self.page.wait_for_url(re.compile(r"/module/staff"), timeout=25_000)
            expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
                timeout=25_000
            )
            return self
        return self.open()

    def expect_nav_entry(self) -> None:
        """The People section is on offer, and Staff inside it.

        The section title is asserted too, so "the link is there" cannot pass off
        the back of a half-rendered sidebar. Scoped to the sidebar because
        /module/home's quick-action grid carries a card with the same label and
        href, and the profile screen's back link reads "Staff" as well.
        """
        expect(self.page.get_by_text(NAV_PEOPLE_SECTION).first).to_be_visible(timeout=25_000)
        nav = self.page.get_by_role("navigation")
        expect(nav.get_by_role("link", name=NAV_STAFF).first).to_be_visible(timeout=25_000)

    # ──────────────────────────── tabs ────────────────────────────

    def show_teaching(self) -> None:
        self.click_button(TEACHING_TAB)

    def show_non_teaching(self) -> None:
        self.click_button(NON_TEACHING_TAB)

    # ────────────────────────── creation ──────────────────────────

    def create_teaching_staff(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        gender: str,
        date_of_birth: str,
        nationality: str,
        marital_status: str,
        dialect: str,
        address: str,
        location: str,
        phone: str,
        religion: str,
        job_title: str,
        employment_type: str,
        admission_date: str,
        degree: str,
        field_of_study: str,
    ) -> None:
        """Create a teaching staff member through the three-step wizard.

        Call ``open()`` first — the trigger lives in the list page's toolbar and
        only renders for users with "manage" permission on the staff module.

        Dates are ISO "YYYY-MM-DD". ``gender``/``marital_status`` take the
        option labels (Male, Female / Single, Married, Divorced, Widowed),
        ``employment_type`` one of Full-time, Part-time, Contract, Internship,
        and ``degree`` one of High School Diploma, Associate Degree,
        Bachelor's Degree, Master's Degree, Doctorate Degree, Other.

        Assigned classes and subjects are optional and are left empty, so this
        does not depend on classes existing yet.
        """
        self.show_teaching()
        self.click_button(ADD_TEACHING_TRIGGER)
        self._await_step(FIRST_NAME_FIELD)

        self._fill_basic_step(
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            date_of_birth=date_of_birth,
            nationality=nationality,
            marital_status=marital_status,
            dialect=dialect,
        )
        self._fill_contact_step(
            address=address,
            location=location,
            phone=phone,
            email=email,
            religion=religion,
        )

        self.fill_labeled(JOB_TITLE_FIELD, _letters(job_title))
        self.fill_labeled(FIELD_OF_STUDY_FIELD, _letters(field_of_study))
        self.select_option_in_combobox(EMPLOYMENT_TYPE_TRIGGER, _exact(employment_type))
        self.select_option_in_combobox(DEGREE_TRIGGER, _exact(degree))
        self._fill_date(admission_date)

        self._submit(SUBMIT_TEACHING)
        self.expect_toast(TEACHING_CREATED_TOAST, timeout_ms=20_000)

        # The wizard routes back to /module/staff, which opens on Teaching Staff.
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        expect(self.find_row(email)).to_be_visible(timeout=20_000)

    def create_non_teaching_staff(
        self,
        *,
        role: str,
        first_name: str,
        last_name: str,
        email: str,
        gender: str,
        date_of_birth: str,
        nationality: str,
        marital_status: str,
        dialect: str,
        address: str,
        location: str,
        phone: str,
        religion: str,
        job_title: str,
        employment_type: str,
        admission_date: str,
        degree: str,
    ) -> None:
        """Create a non-teaching staff member through the three-step wizard.

        Same wizard as the teaching flow, but stricter: nationality, marital
        status, dialect, religion and degree are all starred here, and the
        Admission step adds the role dropdown. ``role`` is the role name as
        listed by ``GET /roles/`` (Accountant, Librarian, …) — "SchoolAdmin" is
        filtered out of the options by the frontend.
        """
        self.show_non_teaching()
        self.click_button(ADD_NON_TEACHING_TRIGGER)
        self._await_step(FIRST_NAME_FIELD)

        self._fill_basic_step(
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            date_of_birth=date_of_birth,
            nationality=nationality,
            marital_status=marital_status,
            dialect=dialect,
        )
        self._fill_contact_step(
            address=address,
            location=location,
            phone=phone,
            email=email,
            religion=religion,
        )

        self.select_option_by_label(ROLE_LABEL, _exact(role))
        self.fill_labeled(JOB_TITLE_FIELD, _letters(job_title))
        self.select_option_in_combobox(EMPLOYMENT_TYPE_TRIGGER, _exact(employment_type))
        self.select_option_in_combobox(DEGREE_TRIGGER, _exact(degree))
        self._fill_date(admission_date)

        self._submit(SUBMIT_NON_TEACHING)
        self.expect_toast(NON_TEACHING_CREATED_TOAST, timeout_ms=20_000)

        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        self.show_non_teaching()
        expect(self.find_row(email)).to_be_visible(timeout=20_000)

    # ─────────────────────────── the register ─────────────────────

    def expect_column_headers(self) -> None:
        """Assert the Teaching Staff header row cell by cell, pinning the order.

        ``cell()`` addresses columns positionally (``TEACHING_COLUMNS``), so a
        column that moved would otherwise make every later assertion read the
        wrong value rather than fail. Select the teaching tab first — the
        non-teaching tab renders a different set.
        """
        cells = self.page.locator("table thead tr").first.locator("th")
        expect(cells).to_have_count(len(TEACHING_COLUMN_HEADERS))
        for index, header in enumerate(TEACHING_COLUMN_HEADERS):
            expect(cells.nth(index)).to_have_text(header)

    def cell(self, email_or_name: str, column: str) -> Locator:
        """One cell of a teaching-staff row, addressed by column name."""
        if column not in TEACHING_COLUMNS:
            raise KeyError(f"unknown staff column {column!r}; "
                           f"known: {sorted(TEACHING_COLUMNS)}")
        return self.find_row(email_or_name).get_by_role("cell").nth(
            TEACHING_COLUMNS[column]
        )

    def expect_no_load_failure(self) -> None:
        """The PageError panels the register and the profile swap in on a failed fetch."""
        expect(self.page.get_by_text(as_pattern(LOAD_FAILURE))).to_have_count(0)
        expect(self.page.get_by_text(as_pattern(PROFILE_LOAD_FAILURE))).to_have_count(0)

    # ───────────────────── the profile screen ─────────────────────

    def open_detail(self, email_or_name: str) -> int:
        """Open a teaching staff member's profile from the register, returning its id.

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
            f"clicking the staff member's View link landed on {self.page.url!r}, "
            f"which carries no /module/staff/<id>"
        )
        return int(match.group(1))

    def detail_value(self, label: str | re.Pattern) -> Locator:
        """The value the profile prints under ``label``.

        Every field on this screen is a caption ``<p>`` followed immediately by
        the value ``<p>`` — ``InfoField`` in the tab panels, and the same shape in
        the "Staff Info" side card — so the caption's next ``<p>`` sibling is the
        value in both layouts.
        """
        caption = self.page.get_by_text(_exact(label)).first
        return caption.locator("xpath=following-sibling::p[1]")

    def open_academics_tab(self) -> None:
        self.page.get_by_role("button", name=ACADEMICS_TAB).first.click()

    # ─────────────────────── the edit wizard ──────────────────────

    def edit_teaching_staff(
        self,
        *,
        address: str | None = None,
        location: str | None = None,
        phone: str | None = None,
        religion: str | None = None,
        job_title: str | None = None,
        employment_type: str | None = None,
        field_of_study: str | None = None,
        description: str | None = None,
    ) -> None:
        """Correct a teaching staff member from their profile's "Edit Profile" button.

        Call it while the profile is open. The editor is the same three-step
        wizard as the create form, prefilled from ``GET /teacher/<id>``, so the
        two Continue buttons only need clicking — every starred field already
        carries the value the staff member was created with.

        Only the fields ``edit-staff/[staffID]/page.tsx`` actually sends are
        offered. Its ``PUT /teacher/<id>`` body carries ``job_title``,
        ``employment_type``, ``admission_date``, ``field_of_study``,
        ``highest_degree_earned``, ``additional_remarks`` and a ``user`` block —
        of which the backend's ``UserUpdate`` model declares only ``first_name``,
        ``other_names``, ``profile_pic``, ``religion``, ``gender``,
        ``date_of_birth``, ``nationality``, ``marital_status``,
        ``residential_address``, ``location``, ``primary_phone``,
        ``secondary_phone`` and ``zip_code``. Email, local dialect and the
        hard-coded password the page also sends are *not* fields of that model
        and are dropped, so a page object that offered them would be promising
        writes that cannot land.

        The wizard hides its Assigned Class/Subject pickers in edit mode
        (``formData.staffID`` is set) and says so on screen: assignments are
        managed from the profile's Academics tab instead.
        """
        self.page.get_by_role("button", name=EDIT_PROFILE_BUTTON).first.click()
        self.page.wait_for_url(EDIT_URL, timeout=25_000)

        # Step 1 is already complete; Continue waits for its own button to
        # enable, which is what waits out the prefill fetch.
        self._await_step(FIRST_NAME_FIELD)
        self._continue(ADDRESS_FIELD)

        if address is not None:
            self.fill_labeled(ADDRESS_FIELD, address)
        if location is not None:
            self.fill_labeled(LOCATION_FIELD, _letters(location))
        if phone is not None:
            self.fill_labeled(PHONE_FIELD, _digits(phone))
        if religion is not None:
            self.fill_labeled(RELIGION_FIELD, _letters(religion))
        self._continue(JOB_TITLE_FIELD)

        if job_title is not None:
            self.fill_labeled(JOB_TITLE_FIELD, _letters(job_title))
        if field_of_study is not None:
            self.fill_labeled(FIELD_OF_STUDY_FIELD, _letters(field_of_study))
        if employment_type is not None:
            # By label, not by placeholder: the trigger already shows the
            # prefilled selection, so there is no placeholder text to filter on.
            self.select_option_by_label(EMPLOYMENT_TYPE_LABEL, _exact(employment_type))
        if description is not None:
            self.fill_labeled(DESCRIPTION_FIELD, _letters(description))

        self._submit(SUBMIT_UPDATE)
        self.expect_toast(UPDATED_TOAST, timeout_ms=20_000)

        # The wizard routes back to /module/staff on success.
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)

    # ──────────────────────────── lookup ──────────────────────────

    def find_row(self, email_or_name: str) -> Locator:
        """Row for ``email_or_name`` in whichever tab is showing.

        Types the term into the toolbar search first: the table is
        server-paginated at 25 rows, and the backend's ``search`` matches first
        name, other names, full name, staff id and email. Select the tab before
        calling — the table only ever holds the active tab's staff.

        The row markup only renders at the ``lg`` breakpoint (below it the page
        switches to cards), so use a desktop viewport.
        """
        self.page.get_by_placeholder(SEARCH_FIELD).first.fill(email_or_name)
        return self.page.get_by_role("row").filter(
            has_text=re.compile(re.escape(email_or_name), re.I)
        ).first

    # ─────────────────────────── internals ────────────────────────

    def _fill_basic_step(
        self,
        *,
        first_name: str,
        last_name: str,
        gender: str,
        date_of_birth: str,
        nationality: str,
        marital_status: str,
        dialect: str,
    ) -> None:
        self.fill_labeled(FIRST_NAME_FIELD, _letters(first_name))
        self.fill_labeled(LAST_NAME_FIELD, _letters(last_name))
        self.fill_labeled(NATIONALITY_FIELD, _letters(nationality))
        self.fill_labeled(DIALECT_FIELD, _letters(dialect))
        self.select_option_in_combobox(GENDER_TRIGGER, _exact(gender))
        self.select_option_in_combobox(MARITAL_STATUS_TRIGGER, _exact(marital_status))
        # Last on the step: the calendar overlay would sit on top of the selects.
        self._fill_date(date_of_birth)
        self._continue(ADDRESS_FIELD)

    def _fill_contact_step(
        self,
        *,
        address: str,
        location: str,
        phone: str,
        email: str,
        religion: str,
    ) -> None:
        self.fill_labeled(ADDRESS_FIELD, address)
        self.fill_labeled(LOCATION_FIELD, _letters(location))
        self.fill_labeled(PHONE_FIELD, _digits(phone))
        self.fill_labeled(EMAIL_FIELD, email)
        self.fill_labeled(RELIGION_FIELD, _letters(religion))
        self._continue(JOB_TITLE_FIELD)

    def _await_step(self, marker: re.Pattern[str]) -> None:
        expect(self.page.get_by_placeholder(marker).first).to_be_visible(timeout=20_000)

    def _continue(self, next_marker: re.Pattern[str]) -> None:
        button = self.page.get_by_role("button", name=CONTINUE_BUTTON).first
        expect(button).to_be_enabled(timeout=10_000)
        button.click()
        self._await_step(next_marker)

    def _submit(self, name: re.Pattern[str]) -> None:
        button = self.page.get_by_role("button", name=name).first
        expect(button).to_be_enabled(timeout=10_000)
        button.click()

    def _fill_date(self, value: str) -> None:
        self.commit_date(self.page.get_by_placeholder(DATE_PICKER_FIELD).first,
                         value, display_format="%d/%m/%Y")


def _exact(text: str | re.Pattern[str]) -> re.Pattern[str]:
    """Anchored option matcher — an unanchored "Male" also matches "Female".

    The degree labels ship an ``&apos;``, which can come back as either
    apostrophe, so both are accepted. A pattern is passed through untouched, so
    callers that already anchored their own (the profile screen's captions) can
    hand one straight in.
    """
    if isinstance(text, re.Pattern):
        return text
    body = re.escape(text).replace("'", _APOSTROPHES)
    return re.compile(rf"^\s*{body}\s*$", re.I)


def _picker_date(value: str) -> str:
    """These pickers declare ``format="DD/MM/YYYY"``; the suite passes ISO dates."""
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
