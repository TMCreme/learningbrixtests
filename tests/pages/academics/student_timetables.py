"""Academics → the learner-facing "Student Class Timetable" screen.

/module/student_timetables — the week grid a pupil (or a guardian viewing as
their ward) reads their own schedule off. It is generated, not authored: the
backend turns every ``Lesson`` scheduled for the student's class in the chosen
week into a slot (``GET /lessons/timetable/student/{student_id}``), so nothing on
this screen creates or edits anything. The page object therefore exposes readers
plus :meth:`expect_write_controls_absent`, and no create/edit verbs at all.

Whose timetable it is, is not a choice
    ``page.tsx`` reads ``user_profile.student_profile.id`` from the auth store —
    there is no student picker. An account with no ``student_profile`` gets the
    "No student profile found for this account." error state instead of a grid,
    which is why a **guardian** reaches this screen by impersonating a ward (Home
    → Your Ward(s) → "Impersonate"): the impersonation store swaps the ward's
    profile into the same auth store, so the page then resolves the ward's id.

The grid's shape
    A plain ``<table>``: one header row of ``Time / Day`` plus Monday…Sunday, then
    one body row per *distinct start time* found anywhere in the week. A cell is
    either a lesson card (subject, teacher, "40 mins") or the hover-only word
    "Free". With no lessons at all the body collapses to a single "No Schedule
    Available" row.

    The header ``Time / Day`` contains a slash, so every selector built from it
    goes through :func:`tests.pages.base.as_pattern` — Playwright serialises a
    Pattern as ``/<source>/<flags>`` and a bare slash closes that literal early.

    The ``<th>`` cells carry no ``scope``, and HTML-AAM only promotes such a cell
    to ``columnheader`` through an algorithm Playwright does not implement, so
    they resolve to plain ``cell``. Headers are read positionally off
    ``table thead tr th`` rather than by role — which also pins the column order
    :data:`DAY_COLUMN` depends on.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── the route ────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/student_timetables(?:$|[?#])")

# The sidebar entry (SideNavigation/nav-config.tsx, "Academics Module" section).
# Anchored so it cannot also match "Classes & Timetables" two rows above it.
NAV_STUDENT_TIMETABLE = re.compile(r"^\s*Student Timetable\s*$", re.I)

# ── headings and banners (page.tsx / StudentTimetableView.tsx) ───────────────
# The loading and error states share this heading; the loaded grid replaces it
# with "<class name> Timetable", which is what proves the ward's class was
# resolved server-side rather than guessed by the client.
LOADING_HEADING = re.compile(r"^\s*Student Class Timetable\s*$", re.I)
WEEKLY_VIEW_BADGE = re.compile(r"^\s*Weekly View\s*$", re.I)
RANGE_LABEL = re.compile(r"Range:", re.I)

# ── failure and empty states ─────────────────────────────────────────────────
LOAD_FAILURE = re.compile(r"^\s*Error Loading Timetable\s*$", re.I)
NO_STUDENT_PROFILE = re.compile(r"No student profile found for this account", re.I)
EMPTY_GRID = re.compile(r"^\s*No Schedule Available\s*$", re.I)

# ── the grid ─────────────────────────────────────────────────────────────────
TIME_COLUMN_HEADER = "Time / Day"
DAYS_OF_WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                "Saturday", "Sunday")
GRID_HEADERS = (TIME_COLUMN_HEADER, *DAYS_OF_WEEK)
# Column 0 is the sticky time cell, so Monday starts at 1.
DAY_COLUMN = {day: index + 1 for index, day in enumerate(DAYS_OF_WEEK)}

# Anything that would let the viewer change the schedule. Anchored at the start
# of the accessible name so the screen's own read-side controls — "Reset to
# Current Week", "Download PDF" — are not swept up by it.
WRITE_CONTROL = re.compile(r"^\s*(?:add|create|new|edit|delete|remove|update|save)\b", re.I)


class StudentTimetablesPage(BasePage):
    URL = "/module/student_timetables"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "StudentTimetablesPage":
        super().open()
        return self

    def open_from_sidebar(self) -> "StudentTimetablesPage":
        """Reach the screen the way a real user does — via the Academics menu.

        Falls back to the route itself when the sidebar is collapsed (it is on
        narrow viewports); how the user got here is worth showing, but it is not
        what this page object asserts.
        """
        link = self.page.get_by_role(
            "link", name=as_pattern(NAV_STUDENT_TIMETABLE)
        ).first
        if link.count():
            link.click()
        else:
            self.open()
        self.page.wait_for_url(LIST_URL, timeout=25_000)
        return self

    def expect_nav_entry(self) -> None:
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_STUDENT_TIMETABLE)).first
        ).to_be_visible(timeout=25_000)

    # ───────────────────────── readers ───────────────────────────

    def wait_for_grid(self, timeout_ms: int = 30_000) -> "StudentTimetablesPage":
        """Wait out the skeleton loader.

        A real ``<table>`` header row only exists once the fetch resolves, and
        unlike a lesson card it is there for an empty week too — so this can
        neither pass on a half-rendered screen nor hang on a legitimately empty
        one.
        """
        expect(self.page.locator("table thead tr").first).to_be_visible(
            timeout=timeout_ms
        )
        return self

    def expect_class_heading(self, class_name: str) -> None:
        """The grid titles itself "<class> Timetable" from the server's answer."""
        expect(
            self.page.get_by_role(
                "heading",
                name=as_pattern(rf"^\s*{re.escape(class_name)}\s+Timetable\s*$"),
            )
        ).to_be_visible(timeout=25_000)

    def expect_weekly_view(self) -> None:
        expect(self.page.get_by_text(as_pattern(WEEKLY_VIEW_BADGE)).first).to_be_visible()
        expect(self.page.get_by_text(as_pattern(RANGE_LABEL)).first).to_be_visible()

    def expect_headers(self) -> None:
        """Assert the header row by position, pinning the column order."""
        header_cells = self.page.locator("table thead tr").first.locator("th")
        expect(header_cells).to_have_count(len(GRID_HEADERS))
        for index, header in enumerate(GRID_HEADERS):
            expect(header_cells.nth(index)).to_have_text(
                as_pattern(rf"^\s*{re.escape(header)}\s*$")
            )

    def time_row(self, time_label: str) -> Locator:
        """The body row for a start time, e.g. "08:00".

        Only the sticky first column renders a clock time, so filtering the row
        on the label cannot collide with a lesson card (which shows a subject, a
        teacher and a "40 mins" duration).
        """
        return self.page.locator("table tbody tr").filter(
            has_text=as_pattern(re.escape(time_label))
        ).first

    def slot(self, time_label: str, day: str) -> Locator:
        """The cell at (start time, weekday) — a lesson card, or empty."""
        return self.time_row(time_label).locator("td").nth(DAY_COLUMN[day])

    def expect_lesson(self, *, time_label: str, day: str, subject: str,
                      teacher: str | None = None,
                      duration_minutes: int | None = None) -> None:
        cell = self.slot(time_label, day)
        expect(cell).to_be_visible(timeout=25_000)
        expect(cell).to_contain_text(as_pattern(re.escape(subject)))
        if teacher:
            expect(cell).to_contain_text(as_pattern(re.escape(teacher)))
        if duration_minutes is not None:
            expect(cell).to_contain_text(
                as_pattern(rf"{duration_minutes}\s*mins")
            )

    def expect_no_load_failure(self) -> None:
        """Neither error state is on screen.

        Both are asserted: "Error Loading Timetable" is the fetch failing, and
        the "No student profile" copy is the screen deciding it has nobody to
        show a timetable for — a guardian who never actually entered the ward's
        view would land there, and the grid assertions below would then be
        asserting nothing.
        """
        expect(self.page.get_by_text(as_pattern(LOAD_FAILURE))).to_have_count(0)
        expect(self.page.get_by_text(as_pattern(NO_STUDENT_PROFILE))).to_have_count(0)

    def expect_write_controls_absent(self) -> None:
        """Nothing on this screen offers to change the schedule."""
        expect(
            self.page.get_by_role("button", name=as_pattern(WRITE_CONTROL))
        ).to_have_count(0)
