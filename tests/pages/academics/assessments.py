"""Academics → Assessment & Scores page object (/module/assessment_score).

The feature ships as ``assessments`` in the feature packs but lives at
``/module/assessment_score`` (see ``config/module_catalog.py``); the screen
renders two tabs, "Assessment" and "Score", and this page object drives the
Assessment tab.

Everything that writes here is gated on ``usePermission("assessments", "manage")``
— for a read-only role the "Create Assessment" trigger is simply not rendered,
so these methods fail as a missing-control timeout rather than as a backend
rejection.

Two things about the Create/Edit modals are worth knowing before reading the
selectors:

* They are **antd** ``Modal`` + ``Form``, not the Radix dialogs used elsewhere in
  this app, so fields are found through their ``.ant-form-item`` wrapper's
  ``<label>`` rather than through ``BasePage.fill_labeled`` /
  ``select_option_by_label`` (both of which assume the Radix layout).
* An antd ``Select`` renders its option list **twice** — a 0×0
  accessibility-only ``role=listbox`` mirror and the real, role-less
  rc-virtual-list rows. ``get_by_role("option")`` therefore only ever finds the
  invisible mirror, which is why options are matched on
  ``.ant-select-item-option`` (the same reason documented in
  ``StudentsPage._select_guardian``).

The category dropdown is **dependent on the lesson**: it stays disabled until a
lesson is picked and is then filled from that lesson's syllabus, so
``create_assessment`` always sets the lesson first and waits for the dependent
fetch by waiting for the category select to lose ``ant-select-disabled``.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError, expect

from tests.pages.base import BasePage

PAGE_HEADING = re.compile(r"^\s*Manage Assessment\s*&\s*Scores\s*$", re.I)

ASSESSMENT_TAB = re.compile(r"^\s*Assessment\s*$", re.I)
SEARCH_FIELD = re.compile(r"^\s*Search assessments\.\.\.\s*$", re.I)
EMPTY_TABLE = re.compile(r"^\s*No assessments found\.\s*$", re.I)

# The page trigger and the modal's submit share this label, so every use is
# scoped — to the page for the trigger, to the dialog for the submit.
CREATE_TRIGGER = re.compile(r"^\s*Create Assessment\s*$", re.I)
CREATE_MODAL = re.compile(r"Create New Assessment", re.I)
CREATE_TOAST = re.compile(r"assessment created successfully", re.I)

EDIT_ITEM = re.compile(r"^\s*Edit\s*$", re.I)
EDIT_MODAL = re.compile(r"Edit Assessment", re.I)
SAVE_CHANGES_BUTTON = re.compile(r"^\s*Save Changes\s*$", re.I)
UPDATE_TOAST = re.compile(r"assessment updated successfully", re.I)

# antd Form.Item labels. They carry no visible asterisk (antd draws the
# required marker with CSS), so each is matched exactly.
NAME_LABEL = "Assessment Name"
DESCRIPTION_LABEL = "Description"
LESSON_LABEL = "Lesson"
CATEGORY_LABEL = "Assessment Category"
MAX_MARKS_LABEL = "Max Marks"
SCHEDULED_DATE_LABEL = "Scheduled Date"
DUE_DATE_LABEL = "Due Date"
STATUS_LABEL = "Status"

DISABLED_SELECT = re.compile(r"ant-select-disabled")

# Column order of AssessmentTable, for AssessmentsPage.cell().
COLUMN = {
    "name": 0,
    "lesson": 1,
    "category": 2,
    "max_marks": 3,
    "status": 4,
    "scheduled_date": 5,
    "due_date": 6,
}


class AssessmentsPage(BasePage):
    URL = "/module/assessment_score"

    def open(self) -> "AssessmentsPage":
        super().open()
        return self.expect_loaded()

    def expect_loaded(self) -> "AssessmentsPage":
        """Assert the workspace is through its guards — however it was reached."""
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        # The heading renders before the module/permission guards resolve; the
        # search box only exists once the Assessment tab itself is through them.
        expect(self.page.get_by_placeholder(SEARCH_FIELD).first).to_be_visible(timeout=20_000)
        return self

    def show_assessments(self) -> None:
        self.page.get_by_role("button", name=ASSESSMENT_TAB).first.click()

    # ───────────────────────── assessments ────────────────────────

    def create_assessment(
        self,
        *,
        name: str,
        lesson_title: str,
        category_name: str,
        description: str,
        max_marks: int,
        scheduled_date: str,
        due_date: str,
    ) -> None:
        """Open, fill and submit the Create New Assessment modal.

        Split into three public steps so a narrated demo can caption each one;
        this composes them for every other caller.
        """
        modal = self.open_create_form()
        self.fill_create_form(
            modal,
            name=name,
            lesson_title=lesson_title,
            category_name=category_name,
            description=description,
            max_marks=max_marks,
            scheduled_date=scheduled_date,
            due_date=due_date,
        )
        self.submit_create(modal, name=name)

    def open_create_form(self) -> Locator:
        """Click "Create Assessment" and return the open modal."""
        trigger = self.page.get_by_role("button", name=CREATE_TRIGGER).first
        # Absent entirely without the "manage" permission, and only rendered
        # once GET /assessments has answered.
        trigger.wait_for(state="visible", timeout=20_000)
        trigger.click()

        modal = self._modal(CREATE_MODAL)
        expect(modal).to_be_visible(timeout=15_000)
        return modal

    def fill_create_form(
        self,
        modal: Locator,
        *,
        name: str,
        lesson_title: str,
        category_name: str,
        description: str,
        max_marks: int,
        scheduled_date: str,
        due_date: str,
    ) -> None:
        """Fill every required field of the create modal.

        Dates are ISO (``YYYY-MM-DD``), which is also antd's default DatePicker
        display format, so they are typed verbatim and committed by clicking the
        panel cell — never by pressing Enter (see ``BasePage.commit_date``).
        """
        self._fill(modal, NAME_LABEL, name)
        self._fill(modal, DESCRIPTION_LABEL, description)
        self._select(modal, LESSON_LABEL, lesson_title, search=True)
        # Only now is the category dropdown enabled and filled — it is derived
        # from the lesson's syllabus, not from the branch.
        self._select(modal, CATEGORY_LABEL, category_name)
        self._fill(modal, MAX_MARKS_LABEL, str(max_marks))
        self._set_date(modal, SCHEDULED_DATE_LABEL, scheduled_date)
        self._set_date(modal, DUE_DATE_LABEL, due_date)

    def submit_create(self, modal: Locator, *, name: str) -> None:
        """Submit the create modal and wait for the new row to be listed."""
        modal.get_by_role("button", name=CREATE_TRIGGER).first.click()
        self.expect_toast(CREATE_TOAST, timeout_ms=20_000)
        expect(modal).to_be_hidden(timeout=15_000)
        expect(self.find_row(name)).to_be_visible(timeout=20_000)

    def edit_assessment(
        self,
        *,
        name: str,
        max_marks: int | None = None,
        status: str | None = None,
    ) -> None:
        """Open a row's Edit modal, change what was asked for, save.

        The modal pre-fills every field from the row, so only the fields the
        caller names are touched.
        """
        self.open_row_menu(name)
        self.page.get_by_role("menuitem", name=EDIT_ITEM).first.click()

        modal = self._modal(EDIT_MODAL)
        expect(modal).to_be_visible(timeout=15_000)

        if max_marks is not None:
            self._fill(modal, MAX_MARKS_LABEL, str(max_marks))
        if status is not None:
            self._select(modal, STATUS_LABEL, status)

        modal.get_by_role("button", name=SAVE_CHANGES_BUTTON).first.click()
        self.expect_toast(UPDATE_TOAST, timeout_ms=20_000)
        expect(modal).to_be_hidden(timeout=15_000)

    def open_row_menu(self, name: str) -> None:
        """Open a row's "..." action menu (Edit / Delete)."""
        row = self.find_row(name)
        expect(row).to_be_visible(timeout=20_000)
        row.get_by_role("button").last.click()

    def find_row(self, name: str) -> Locator:
        """Row in the assessments table.

        The list is server-paginated at 10 rows and the search box filters
        server-side (debounced 500ms), so call ``search`` first for anything
        that may have fallen off the first page.
        """
        return self.page.get_by_role("row").filter(has=self.page.get_by_text(_exact(name))).first

    def search(self, query: str) -> None:
        self.page.get_by_placeholder(SEARCH_FIELD).first.fill(query)

    def cell(self, name: str, column: int) -> Locator:
        """One cell of ``name``'s row, by column index (see ``COLUMN``)."""
        return self.find_row(name).get_by_role("cell").nth(column)

    # ────────────────────────── internals ──────────────────────────

    def _modal(self, title: re.Pattern[str]) -> Locator:
        """Scope to one antd Modal — every one of them stays mounted once opened."""
        return self.page.get_by_role("dialog").filter(has_text=title).first

    def _field(self, modal: Locator, label: str) -> Locator:
        """The ``.ant-form-item`` wrapping the control labelled ``label``.

        antd does associate its labels (``htmlFor`` = the field's ``name``), but
        the wrapper is what scopes a *composite* control — a DatePicker's panel
        trigger, a Select's ``.ant-select`` box — none of which is the element
        ``get_by_label`` resolves to.
        """
        return modal.locator(".ant-form-item").filter(
            has=self.page.locator("label").filter(has_text=_exact(label))
        ).first

    def _fill(self, modal: Locator, label: str, value: str) -> None:
        self._field(modal, label).locator("input, textarea").first.fill(value)

    def _set_date(self, modal: Locator, label: str, value: str) -> None:
        self.commit_date(self._field(modal, label).locator("input").first, value)

    def _select(self, modal: Locator, label: str, option_text: str,
                *, search: bool = False) -> None:
        """Pick ``option_text`` out of the antd Select labelled ``label``."""
        field = self._field(modal, label)
        select = field.locator(".ant-select").first
        # A dependent select (Assessment Category) is disabled until its parent
        # is chosen; the div itself is clickable either way, so its disabled
        # class — not Playwright's actionability — is what has to be waited on.
        expect(select).not_to_have_class(DISABLED_SELECT, timeout=20_000)
        select.click()

        if search:
            # showSearch: typing drives filterOption, which narrows a long list
            # to the one row we want.
            field.get_by_role("combobox").first.fill(option_text)

        # Scoped to the dropdown that is actually open: antd leaves every
        # dropdown it has rendered mounted-but-hidden, so a page-wide match
        # would happily find a stale option from a select we closed earlier.
        option = self.page.locator(".ant-select-dropdown:visible").last.locator(
            ".ant-select-item-option"
        ).filter(has_text=_exact(option_text)).first
        try:
            option.wait_for(state="visible", timeout=20_000)
        except PlaywrightTimeoutError as exc:
            raise AssertionError(
                f"The {label!r} dropdown never offered {option_text!r}. Its options are "
                "fetched, not static — a lesson must exist for the branch and a "
                "category must exist on that lesson's syllabus."
            ) from exc
        option.click()


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
