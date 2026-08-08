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

STUDENT_ADMITTED_TOAST = re.compile(r"student admitted successfully", re.I)


class StudentsPage(BasePage):
    URL = "/module/students"

    def open(self) -> "StudentsPage":
        super().open()
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        return self

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
        (converted to the picker's DD/MM/YYYY on the way in). ``class_name``
        and ``guardian_name`` must already exist — both dropdowns are populated
        from the branch's own records, so create the class and the guardian
        first. The admission date is left at the form's default (today).

        Ends on ``/module/students`` with the toast asserted, so ``find_row``
        can be called straight after.
        """
        if not guardian_name.strip():
            raise ValueError(
                "guardian_name is required: the 'Select a guardian' dropdown only lists "
                "guardians that already exist for the branch, so one must be created first."
            )

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
        self._select_guardian(guardian_name)
        if previous_school:
            self.fill_labeled(PREVIOUS_SCHOOL_FIELD, _letters(previous_school))

    def _fill_admission_information(self, *, class_name: str, blood_type: str) -> None:
        # The class trigger reads "Loading classes..." until /classes/ answers,
        # so filtering on "Select class" doubles as the wait for that fetch.
        self.select_option_in_combobox(CLASS_PLACEHOLDER, _exact(class_name))
        self.select_option_in_combobox(BLOOD_TYPE_PLACEHOLDER, _exact(blood_type))

    # ───────────────────────── internals ──────────────────────────

    def _continue(self, next_marker: Locator) -> None:
        self.click_button(CONTINUE_BUTTON)
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


def _exact(value: str) -> re.Pattern[str]:
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
