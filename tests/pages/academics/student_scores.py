"""Academics → the **Score** half of /module/assessment_score (the gradebook).

``AssessmentsPage`` drives the *Assessment* tab of this workspace — the register
of quizzes and exams. This page object drives the other tab, where a teacher
records and revises the marks those assessments earn:

* the Score tab itself (search box, assessment filter, ScoreTable),
* the **Bulk Score Entry** screen it links out to
  (/module/assessment_score/Score/bulk-entry), which is the only place a score is
  *created*, and
* the **Edit Student Score** modal a row's action menu opens.

Why the teacher's "student scores" feature lives here and not at
/module/student_assessment_score
    That route is the pupil-facing "Assignments & Scores" page: it calls
    ``GET /assessments/scores/me`` and ``GET /assessments/assignments/me``, both
    of which answer 403 for anyone without a ``student_profile``
    (newschoolapp/api/routes/assessment.py::list_my_scores). Its sidebar entry is
    gated on the ``student_scores`` permission, which the seeded Teacher role
    does not hold (db/repository/permissions.py) — a teacher never sees it. The
    write side of the same data is the gradebook below, reached from
    "Assessment & Scores".

Two UI-toolkit facts drive most of the selectors:

* The Score **tab** is shadcn/Radix (its assessment filter is a Radix ``Select``
  with ``role=combobox``/``role=option``), while **Bulk Score Entry** and the
  **Edit Student Score** modal are **antd** ``Form``s. So the two halves are
  located in two different ways — ``.ant-form-item`` + ``<label>`` for antd,
  roles for Radix.
* An antd ``Select`` renders its option list twice — a 0×0 accessibility-only
  ``role=listbox`` mirror plus the real, role-less rc-virtual-list rows — so its
  options are matched on ``.ant-select-item-option`` inside the dropdown that is
  actually ``:visible`` (the same reasoning as ``AssessmentsPage._select``).

Nothing here presses Enter to commit a field: this workspace has no date picker,
but the antd ``Form``s below do sit in real ``<form>`` elements and the house
rule (see ``BasePage.commit_date``) is to click, never to submit by keystroke.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError, expect

from tests.pages.base import BasePage, as_pattern

# ── the workspace ────────────────────────────────────────────────────────────
PAGE_HEADING = re.compile(r"^\s*Manage Assessment\s*&\s*Scores\s*$", re.I)
NAV_LINK = re.compile(r"^\s*Assessment\s*&\s*Scores\s*$", re.I)
SCORE_TAB = re.compile(r"^\s*Score\s*$", re.I)

# ── the Score tab (src/app/module/assessment_score/(views)/Score/page.tsx) ───
SEARCH_FIELD = "Search by student name or ID..."
ASSESSMENT_FILTER_PLACEHOLDER = re.compile(r"^\s*Select Assessment\s*$", re.I)
BULK_ENTRY_BUTTON = re.compile(r"^\s*Bulk Score Entry\s*$", re.I)
EMPTY_TABLE = re.compile(r"^\s*No scores found\.\s*$", re.I)
LOAD_FAILURE_TITLE = re.compile(r"Failed to load scores", re.I)

# ScoreTable.tsx column order, for ``StudentScoresPage.cell``.
COLUMN = {
    "student": 0,
    "id_number": 1,
    "assessment": 2,
    "score": 3,
    "percentage": 4,
    "weighted": 5,
    "remarks": 6,
    "date": 7,
}

# ── Bulk Score Entry (…/Score/bulk-entry/page.tsx) ───────────────────────────
BULK_ENTRY_URL = re.compile(r"/module/assessment_score/Score/bulk-entry")
BULK_ENTRY_HEADING = re.compile(r"^\s*Bulk Score Entry\s*$", re.I)
ASSESSMENT_FIELD = "Select Assessment"
MARKS_PLACEHOLDER = "Marks"
REMARKS_PLACEHOLDER = "Add remarks..."
SUBMIT_SCORES_BUTTON = re.compile(r"^\s*Submit Scores\s*$", re.I)
RECORDED_TOAST = re.compile(r"Scores recorded successfully", re.I)
NO_STUDENTS = re.compile(r"No students found in the associated class\.", re.I)
# Where the page sends the teacher back to once the marks are saved.
SCORES_TAB_URL = re.compile(r"/module/assessment_score\?tab=score")

# ── Edit Student Score (…/Score/components/EditScoreModal.tsx) ───────────────
EDIT_MENU_ITEM = re.compile(r"^\s*Edit Score\s*$", re.I)
EDIT_MODAL = re.compile(r"Edit Student Score", re.I)
MARKS_LABEL = "Marks Obtained"
REMARKS_LABEL = "Remarks"
UPDATE_SCORE_BUTTON = re.compile(r"^\s*Update Score\s*$", re.I)
UPDATED_TOAST = re.compile(r"Score updated successfully", re.I)


class StudentScoresPage(BasePage):
    URL = "/module/assessment_score"

    # ─────────────────────────── navigation ───────────────────────

    def open(self) -> "StudentScoresPage":
        super().open()
        return self.expect_loaded()

    def open_from_sidebar(self) -> "StudentScoresPage":
        """Reach the workspace the way a teacher does — via the Academics menu.

        Falls back to the route itself when the sidebar is collapsed (narrow
        viewports render it behind a toggle); how the user got there is worth
        showing, but it is not what this page object asserts.
        """
        link = self.page.get_by_role("link", name=NAV_LINK).first
        if link.count():
            link.click()
            return self.expect_loaded()
        return self.open()

    def expect_loaded(self) -> "StudentScoresPage":
        """Assert the workspace is through its module/permission guards."""
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
            timeout=20_000
        )
        # The heading renders before the guards resolve; the tab strip only
        # exists once they have.
        expect(self.page.get_by_role("button", name=SCORE_TAB).first).to_be_visible(
            timeout=20_000
        )
        return self

    def show_scores(self) -> "StudentScoresPage":
        """Switch to the Score tab and wait for its own controls."""
        self.page.get_by_role("button", name=SCORE_TAB).first.click()
        return self.expect_scores_loaded()

    def expect_scores_loaded(self) -> "StudentScoresPage":
        """The Score tab rendered its filters rather than its error panel."""
        expect(self.page.get_by_placeholder(SEARCH_FIELD).first).to_be_visible(
            timeout=20_000
        )
        expect(self.page.get_by_text(LOAD_FAILURE_TITLE)).to_have_count(0)
        return self

    # ───────────────────── the Score tab's filter ─────────────────

    def assessment_filter(self) -> Locator:
        """The Radix Select that chooses which assessment's marks are listed.

        ``.first`` is safe here: the only other combobox this tab can render is
        TablePagination's "Rows per page", which sits *below* the table and only
        exists once there is at least one row.
        """
        return self.page.get_by_role("combobox").first

    def filter_by_assessment(self, name: str) -> None:
        """Pick ``name`` in the assessment filter and wait for its marks.

        The filter is populated by a fetch, and it initialises to the *first*
        assessment the branch has — which, in a school several tests have written
        to, is very unlikely to be the one under test. So it is always set
        explicitly rather than trusted.
        """
        trigger = self.assessment_filter()
        # A Radix trigger whose value matches no option renders empty, so "has
        # any text at all" is what says the assessment list has arrived.
        expect(trigger).to_have_text(re.compile(r"\S"), timeout=30_000)

        trigger.click()
        option = self.page.get_by_role("option", name=as_pattern(_exact_source(name))).first
        try:
            option.wait_for(state="visible", timeout=20_000)
        except PlaywrightTimeoutError as exc:
            raise AssertionError(
                f"The assessment filter never offered {name!r}. It lists every "
                "assessment this teacher can see in the branch — if the "
                "assessment was seeded for another (subject, class) pair, they "
                "cannot see it at all."
            ) from exc
        option.click()

        expect(trigger).to_have_text(_exact(name), timeout=15_000)
        self.wait_for_table()

    def wait_for_table(self, timeout_ms: int = 30_000) -> None:
        """Block until the table has settled, with or without rows.

        The header renders immediately and a spinner row is swapped for either
        data rows or the empty state, so asserting on the header alone would pass
        while the fetch was still in flight — and would therefore also pass a
        moment before ``PageError`` replaced the whole tab. Every data row starts
        with a ``font-medium`` cell; the empty state is one centred message.
        """
        body = self.page.locator("table tbody")
        settled = body.get_by_text(EMPTY_TABLE).first.or_(
            body.locator("td.font-medium").first
        )
        expect(settled.first).to_be_visible(timeout=timeout_ms)

    def expect_empty(self) -> None:
        expect(self.page.locator("table tbody").get_by_text(EMPTY_TABLE).first).to_be_visible(
            timeout=20_000
        )

    # ────────────────────────── the rows ──────────────────────────

    def find_row(self, student_name: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has=self.page.get_by_text(_exact(student_name))
        ).first

    def cell(self, student_name: str, column: int) -> Locator:
        """One cell of a student's row, by column index (see ``COLUMN``)."""
        return self.find_row(student_name).get_by_role("cell").nth(column)

    def search(self, query: str) -> None:
        """Filter the listed marks. Client-side, debounced 500ms."""
        self.page.get_by_placeholder(SEARCH_FIELD).first.fill(query)

    # ────────────────────── bulk score entry ──────────────────────

    def open_bulk_entry(self) -> None:
        """Click "Bulk Score Entry" and land on its form.

        The trigger is absent entirely without ``usePermission("assessments",
        "manage")``, so a read-only role fails here as a missing control rather
        than as a backend rejection.
        """
        trigger = self.page.get_by_role("button", name=BULK_ENTRY_BUTTON).first
        trigger.wait_for(state="visible", timeout=20_000)
        trigger.click()
        self.page.wait_for_url(BULK_ENTRY_URL, timeout=20_000)
        expect(self.page.get_by_role("heading", name=BULK_ENTRY_HEADING)).to_be_visible(
            timeout=20_000
        )

    def choose_assessment_to_score(self, name: str) -> None:
        """Pick the assessment whose class list should load.

        Its options read ``"<name> (<lesson title>)"``, so ``name`` is matched as
        a substring rather than exactly. Choosing one triggers the dependent
        fetch of the students in the assessment's class.
        """
        field = self._form_item(ASSESSMENT_FIELD)
        field.locator(".ant-select").first.click()
        # showSearch: typing drives filterOption, which narrows the list.
        field.get_by_role("combobox").first.fill(name)

        option = self.page.locator(".ant-select-dropdown:visible").last.locator(
            ".ant-select-item-option"
        ).filter(has_text=re.compile(re.escape(name), re.I)).first
        try:
            option.wait_for(state="visible", timeout=20_000)
        except PlaywrightTimeoutError as exc:
            raise AssertionError(
                f"The 'Select Assessment' dropdown never offered {name!r}. It is "
                "fetched, not static, and is scoped to the (subject, class) pairs "
                "this teacher is the subject teacher of."
            ) from exc
        option.click()

    def set_student_marks(self, student_name: str, *, marks: float,
                          remarks: str = "") -> None:
        """Type one student's marks (and optional remark) into the class list.

        Both placeholders are matched **exactly**: Playwright's default is a
        case-insensitive substring, and "Add remarks…" contains "marks", so a
        loose match on the marks box would resolve to two inputs.
        """
        row = self._student_row(student_name)
        row.get_by_placeholder(MARKS_PLACEHOLDER, exact=True).first.fill(str(marks))
        if remarks:
            row.get_by_placeholder(REMARKS_PLACEHOLDER, exact=True).first.fill(remarks)

    def submit_scores(self) -> None:
        """Save the whole class's marks and follow the redirect back to the tab."""
        self.page.get_by_role("button", name=SUBMIT_SCORES_BUTTON).first.click()
        self.expect_toast(RECORDED_TOAST, timeout_ms=20_000)
        # The form pushes to ?tab=score on success, so the workspace remounts
        # straight onto the gradebook.
        self.page.wait_for_url(SCORES_TAB_URL, timeout=20_000)
        self.expect_scores_loaded()

    # ─────────────────────── editing one score ────────────────────

    def open_edit_score(self, student_name: str) -> Locator:
        """Open a row's "Edit Score" modal and return it."""
        row = self.find_row(student_name)
        expect(row).to_be_visible(timeout=20_000)
        # The row's only trailing control is the "..." menu trigger.
        row.get_by_role("button").last.click()
        self.page.get_by_role("menuitem", name=EDIT_MENU_ITEM).first.click()

        modal = self._modal(EDIT_MODAL)
        expect(modal).to_be_visible(timeout=15_000)
        return modal

    def submit_edit_score(self, modal: Locator, *, marks: float | None = None,
                          remarks: str | None = None) -> None:
        """Change what the caller named — the modal pre-fills the rest — and save."""
        if marks is not None:
            self._field(modal, MARKS_LABEL).locator("input").first.fill(str(marks))
        if remarks is not None:
            self._field(modal, REMARKS_LABEL).locator("textarea").first.fill(remarks)

        modal.get_by_role("button", name=UPDATE_SCORE_BUTTON).first.click()
        self.expect_toast(UPDATED_TOAST, timeout_ms=20_000)
        expect(modal).to_be_hidden(timeout=15_000)

    # ────────────────────────── internals ─────────────────────────

    def _modal(self, title: re.Pattern[str]) -> Locator:
        """Scope to one antd Modal — every one of them stays mounted once opened."""
        return self.page.get_by_role("dialog").filter(has_text=title).first

    def _form_item(self, label: str, scope: Locator | None = None) -> Locator:
        """The ``.ant-form-item`` wrapping the control labelled ``label``.

        antd does associate its labels, but the wrapper is what scopes a
        *composite* control (a ``.ant-select`` box), which is not the element
        ``get_by_label`` resolves to.
        """
        root = scope if scope is not None else self.page
        return root.locator(".ant-form-item").filter(
            has=self.page.locator("label").filter(has_text=_exact(label))
        ).first

    def _field(self, modal: Locator, label: str) -> Locator:
        return self._form_item(label, scope=modal)

    def _student_row(self, student_name: str) -> Locator:
        """One pupil's line in the bulk-entry class list.

        The list is a CSS grid of ``<div>``s, not a table — the header row shares
        the same classes, which the name filter is what excludes.
        """
        row = self.page.locator("div.grid.grid-cols-12").filter(
            has_text=re.compile(re.escape(student_name), re.I)
        ).first
        try:
            row.wait_for(state="visible", timeout=30_000)
        except PlaywrightTimeoutError as exc:
            raise AssertionError(
                f"The bulk-entry class list never showed {student_name!r}. It is "
                "fetched from the class the assessment's syllabus belongs to, so "
                "the student must be enrolled in that class for the current "
                "academic year."
            ) from exc
        return row


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(_exact_source(value), re.I)


def _exact_source(value: str) -> str:
    return rf"^\s*{re.escape(value)}\s*$"
