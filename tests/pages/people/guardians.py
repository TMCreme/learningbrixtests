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
        """Not supported: the guardians module has no working link-ward action.

        Nothing under ``/module/guardians`` can attach a ward to an existing
        guardian:

        * The detail page (``/module/guardians/<id>``) only lists wards; its
          empty state says "You can assign wards by editing the guardian's
          profile".
        * That edit wizard does render the same Ward(s) picker, but its
          ``PUT /guardian/<id>`` is a dead end — ``GuardianService.update_guardian``
          hands ``student_ids`` to a generic ``setattr`` loop and
          ``GuardianProfile`` has no such column (the link lives on the
          ``guardian_students`` association behind the ``students``
          relationship), so the request succeeds and changes nothing. Driving it
          here would only produce a green test for a link that was never made.
        * ``POST /guardian/<id>/wards/<student_id>`` exists on the backend but is
          called from nowhere in the frontend.

        Use ``create_guardian(ward_names=[student_name])`` when the guardian is
        being created, or link from the student side: the Admit Student wizard's
        Contact Details step has a "Guardian's Name" picker that sends
        ``guardian_id`` on ``POST /student/`` (``tests/pages/people/students.py``).
        """
        raise NotImplementedError(
            "The guardians module cannot link a ward after creation: the edit "
            "wizard's PUT /guardian/<id> silently drops student_ids. Pass "
            "ward_names to create_guardian, or select the guardian during "
            f"student admission ({student_name!r} → {guardian_name!r})."
        )

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


def _exact(text: str) -> re.Pattern[str]:
    """Anchored option matcher — an unanchored "Male" also matches "Female"."""
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
