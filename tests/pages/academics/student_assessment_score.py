"""Academics → the pupil-facing "Assignments & Scores" screen.

/module/student_assessment_score — deliberately a *different* page object from
``tests.pages.academics.student_scores``, which drives the teacher's gradebook at
/module/assessment_score. The two screens read and write the same
``StudentScore`` rows, but they are separate routes with separate tables,
separate permissions and separate audiences:

* ``/module/assessment_score`` — the teacher/admin gradebook (``manage:assessments``).
* ``/module/student_assessment_score`` — this one: what the learner and their
  guardian are shown (``read:student_scores``).

The route is not named after its module
    The feature-pack key is ``student_scores``; ``src/middleware.ts`` maps the
    ``student_assessment_score`` path segment back onto it, and
    ``nav-config.tsx`` points the "Student Scores" sidebar entry here.
    ``/module/student_scores`` does not exist.

One route, two tabs
    ``page.tsx`` is a single screen with two plain ``<button>`` tabs —
    **Assignments** (the default) and **Scores** — each rendering its own table
    and its own ``PageError`` on a failed fetch. There is no dialog, no form and
    no row menu on it: the screen is read-only for everyone it is built for,
    which is why this page object exposes readers plus
    ``expect_write_controls_absent`` rather than any create/edit verbs.

    The Assignments tab also carries two client-side filter buttons, "To Do"
    (``?status=pending``) and "All" (no filter). Both refetch.

Loading
    Both tables render an animated skeleton — not a ``<table>`` — while their
    fetch is in flight, so "the header row exists" is the honest signal that a
    tab has finished loading. ``wait_for_table`` waits on that rather than on a
    data row, which would be indistinguishable from the empty state.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── the route and its heading (page.tsx) ─────────────────────────────────────
PAGE_HEADING = re.compile(r"^\s*Assignments\s*&\s*Scores\s*$", re.I)
PAGE_INTRO = re.compile(r"review your scores for completed assessments", re.I)
# Anchored so it cannot also match /module/student_assessment_score/assignment/{id}.
LIST_URL = re.compile(r"/module/student_assessment_score(?:$|[?#])")

# The sidebar entry (SideNavigation/nav-config.tsx, "Academics Module" section).
NAV_STUDENT_SCORES = re.compile(r"^\s*Student Scores\s*$", re.I)

# ── tabs and filters ─────────────────────────────────────────────────────────
ASSIGNMENTS_TAB = re.compile(r"^\s*Assignments\s*$", re.I)
SCORES_TAB = re.compile(r"^\s*Scores\s*$", re.I)
TODO_FILTER = re.compile(r"^\s*To Do\s*$", re.I)
ALL_FILTER = re.compile(r"^\s*All\s*$", re.I)

# ── failure and empty states ─────────────────────────────────────────────────
# src/components/common/PageError.tsx, mounted with these exact titles; each
# replaces its own tab's table.
ASSIGNMENTS_FAILURE_TITLE = re.compile(r"Failed to load assignments", re.I)
SCORES_FAILURE_TITLE = re.compile(r"Failed to load assessment scores", re.I)
EMPTY_ASSIGNMENTS = re.compile(r"No assignments found", re.I)
EMPTY_SCORES = re.compile(r"No scores found", re.I)

# ── table shapes (AssessmentScoresTable.tsx / AssignmentsFeedTable.tsx) ──────
SCORE_HEADERS = ("Assessment Name", "Category", "Marks", "Percentage",
                 "Weighted Score", "Remarks", "Date")
ASSIGNMENT_HEADERS = ("Assignment", "Subject", "Due Date", "Status", "Marks", "Action")

SCORE_COLUMN = {
    "assessment": 0,
    "category": 1,
    "marks": 2,
    "percentage": 3,
    "weighted": 4,
    "remarks": 5,
    "date": 6,
}
ASSIGNMENT_COLUMN = {
    "assignment": 0,
    "subject": 1,
    "due_date": 2,
    "status": 3,
    "marks": 4,
    "action": 5,
}

# Anything that would let the viewer change a grade. Anchored at the start of the
# accessible name so the Scores tab's pagination controls ("First", "Previous",
# "Next", "Last") are not swept up by it.
WRITE_CONTROL = re.compile(r"^\s*(?:add|create|new|edit|delete|remove|update|save)\b", re.I)


class StudentAssessmentScorePage(BasePage):
    URL = "/module/student_assessment_score"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "StudentAssessmentScorePage":
        super().open()
        return self

    def open_from_sidebar(self) -> "StudentAssessmentScorePage":
        """Reach the screen the way a real user does — via the Academics menu.

        Falls back to the route itself when the sidebar is collapsed (it is on
        narrow viewports); how the user got here is worth showing, but it is not
        what this page object asserts.
        """
        link = self.page.get_by_role("link", name=as_pattern(NAV_STUDENT_SCORES)).first
        if link.count():
            link.click()
        else:
            self.open()
        self.page.wait_for_url(LIST_URL, timeout=25_000)
        return self

    def expect_loaded(self) -> "StudentAssessmentScorePage":
        expect(
            self.page.get_by_role("heading", name=as_pattern(PAGE_HEADING))
        ).to_be_visible(timeout=25_000)
        return self

    # ─────────────────────────── tabs ────────────────────────────

    def open_assignments_tab(self) -> None:
        self.click_button(ASSIGNMENTS_TAB)
        self.wait_for_table()

    def open_scores_tab(self) -> None:
        self.click_button(SCORES_TAB)
        self.wait_for_table()

    def filter_assignments(self, label: str | re.Pattern) -> None:
        self.click_button(label)
        self.wait_for_table()

    # ───────────────────────── readers ───────────────────────────

    def wait_for_table(self, timeout_ms: int = 30_000) -> None:
        """Wait out the skeleton.

        A real ``<table>`` header only exists once the fetch resolves, and unlike
        a data row it is there for an empty list too — so this cannot pass on a
        half-rendered tab and cannot hang on a legitimately empty one.
        """
        expect(self.page.locator("table thead tr").first).to_be_visible(
            timeout=timeout_ms
        )

    def expect_headers(self, headers: tuple[str, ...]) -> None:
        """Assert the header row, by position.

        Not ``get_by_role("columnheader")``: both tables write a bare ``<th>``
        with no ``scope``, and HTML-AAM only promotes such a cell to
        ``columnheader`` through an algorithm Playwright does not implement — it
        resolves them to plain ``cell``, so a columnheader query matches nothing
        however correct the markup looks.

        Matching by index rather than by presence also pins the column *order*,
        which is what ``SCORE_COLUMN`` / ``ASSIGNMENT_COLUMN`` (and therefore
        every ``cell()`` assertion below) actually depend on.
        """
        header_cells = self.page.locator("table thead tr").first.locator("th")
        expect(header_cells).to_have_count(len(headers))
        for index, header in enumerate(headers):
            expect(header_cells.nth(index)).to_have_text(
                as_pattern(rf"^\s*{re.escape(header)}\s*$")
            )

    def row(self, text: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has_text=as_pattern(re.escape(text))
        ).first

    def cell(self, text: str, column: int) -> Locator:
        return self.row(text).get_by_role("cell").nth(column)

    def expect_row(self, text: str) -> None:
        expect(self.row(text)).to_be_visible(timeout=25_000)

    def expect_no_load_failure(self) -> None:
        """Neither tab's PageError is on screen.

        Both are asserted whichever tab is active: a refusal on either fetch is a
        denial this screen must not be showing to a role that is entitled to it.
        """
        expect(
            self.page.get_by_text(as_pattern(ASSIGNMENTS_FAILURE_TITLE))
        ).to_have_count(0)
        expect(self.page.get_by_text(as_pattern(SCORES_FAILURE_TITLE))).to_have_count(0)

    def expect_write_controls_absent(self) -> None:
        """Nothing on this screen offers to change a grade."""
        expect(
            self.page.get_by_role("button", name=as_pattern(WRITE_CONTROL))
        ).to_have_count(0)
