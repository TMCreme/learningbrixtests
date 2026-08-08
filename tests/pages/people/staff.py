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

_APOSTROPHES = "['’]"


class StaffPage(BasePage):
    URL = "/module/staff"

    def open(self) -> "StaffPage":
        super().open()
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        return self

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


def _exact(text: str) -> re.Pattern[str]:
    """Anchored option matcher — an unanchored "Male" also matches "Female".

    The degree labels ship an ``&apos;``, which can come back as either
    apostrophe, so both are accepted.
    """
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
