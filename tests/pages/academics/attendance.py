"""Academics → Attendance page object (/module/attendance).

The register is one screen: a stats strip, a filter bar (search / date / year /
term / class) and a table with one row per *student* — not per attendance
record. A student with no record for the selected date still gets a row, whose
Status cell reads "Not Marked"; marking is done from that row's "…" menu.

Two selector families live on this screen and they behave differently:

* the filter bar is **Radix** (``@/components/ui/select``), so its dropdowns
  expose ``role=option`` and ``BasePage.select_option_by_label`` works — the
  labels are bare ``<label>``s with no ``for``, which is exactly what that
  helper anchors on;
* the action modals are **antd** (``AttendanceActionModal``), so their Selects
  render their real rows as role-less ``.ant-select-item-option`` divs plus a
  0×0 accessibility-only mirror. ``get_by_role("option")`` therefore only ever
  finds the invisible mirror — the same trap documented in
  ``tests/pages/academics/assessments.py`` — so options are matched on
  ``.ant-select-item-option`` inside the dropdown that is actually open.

The modal is not an antd ``Form`` either: its fields are
``<div><label>…</label><control/></div>``, so each control is reached through
its label's parent rather than through ``.ant-form-item``.

Writing is gated on ``("manage", "attendance")`` and, for a Teacher, on being
the *class teacher* of the row's class (``assert_class_teacher`` in
``api/routes/attendance.py``) — a teacher who is not gets a 403 that surfaces as
an error toast, not as a missing control.
"""
from __future__ import annotations

import re
import time

from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError, expect

from tests.pages.base import BasePage, as_pattern

PAGE_HEADING = re.compile(r"^\s*Attendance Management\s*$", re.I)
TABLE_HEADING = re.compile(r"^\s*Attendance Records\s*$", re.I)
EMPTY_TABLE = re.compile(r"^\s*No students found\s*$", re.I)
LOADING_ROW = re.compile(r"^\s*Loading records\.\.\.\s*$", re.I)

# Filter-bar labels (page.tsx). Anchored so "Select Class" cannot also match the
# bulk modal's "Please select a class filter." toast.
CLASS_FILTER_LABEL = re.compile(r"^\s*Select Class\s*$", re.I)
SEARCH_PLACEHOLDER = re.compile(r"Search by name or student ID", re.I)

# Row action menu (AttendanceTable.tsx) and the modal it opens.
MARK_ITEM = re.compile(r"^\s*Mark Attendance\s*$", re.I)
MARK_MODAL = re.compile(r"Mark Attendance:", re.I)
SAVE_CHANGES_BUTTON = re.compile(r"^\s*Save Changes\s*$", re.I)
# page.tsx uses the same toast for the create (POST /attendance/) and the edit
# (PUT /attendance/{id}) — the modal decides which by whether a record exists.
SAVE_TOAST = re.compile(r"Attendance updated successfully", re.I)

STATUS_FIELD_LABEL = re.compile(r"^\s*Status\s*$", re.I)
NOTES_PLACEHOLDER = re.compile(r"Add any additional notes here", re.I)

# ── what the read-only path asserts ──────────────────────────────────────────

# AttendanceTable.tsx column headers, in render order (after the bulk-select
# checkbox column, which has no heading).
TABLE_COLUMNS = (
    "Student Name", "Class", "Check In", "Check Out", "Status", "Notes", "Actions",
)

# AttendanceStatsOverview.tsx — the strip only mounts once the stats fetch has
# answered, so its tiles are the proof that GET /attendance/stats/summary was
# served rather than refused.
STAT_TILES = (
    "Total Students", "Present Today", "Absent",
    "Late Arrivals", "Excused Absence", "Half Day", "Overall Attendance",
)

# src/components/common/PageError.tsx, mounted with this exact title when any of
# the page's fetches fails — it replaces the entire register.
LOAD_FAILURE_TITLE = re.compile(r"Failed to load attendance data", re.I)

# ── /module/attendance/view_all — the month calendar ─────────────────────────
VIEW_ALL_BUTTON = re.compile(r"^\s*View All Attendance\s*$", re.I)
VIEW_ALL_HEADING = re.compile(r"^\s*Attendance Overview\s*$", re.I)
VIEW_ALL_LOADING = re.compile(r"Loading attendance data", re.I)
VIEW_ALL_FAILURE_TITLE = re.compile(r"Failed to load attendance records", re.I)
WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

# Column order of AttendanceTable, for AttendancePage.cell(). Column 0 is the
# bulk-select checkbox.
COLUMN = {
    "name": 1,
    "class": 2,
    "check_in": 3,
    "check_out": 4,
    "status": 5,
    "notes": 6,
}

# What the Status cell renders per stored status (STATUS_CONFIG in
# AttendanceTable.tsx); an unmatched/absent record falls back to "Not Marked".
NOT_MARKED = "Not Marked"


class AttendancePage(BasePage):
    URL = "/module/attendance"

    def open(self) -> "AttendancePage":
        super().open()
        return self.expect_loaded()

    def expect_loaded(self) -> "AttendancePage":
        """Assert the register is through its guards — however it was reached.

        ``useModuleGuard``/``usePermissionGuard`` render ``null`` (and redirect)
        rather than an error, and a refused fetch swaps the whole page for
        ``PageError``, so the heading being present is what says "this user got
        the register".
        """
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
            timeout=20_000
        )
        expect(self.page.get_by_role("heading", name=TABLE_HEADING)).to_be_visible(
            timeout=20_000
        )
        return self

    # ────────────────────────── filtering ──────────────────────────

    def filter_by_class(self, class_name: str) -> None:
        """Point the register at one class.

        Worth doing before marking, not just for the narrowed list: the page
        posts ``class_id: selectedClassId || student.class_assigned?.id``, so an
        explicit class removes any dependence on the row's own enrollment being
        resolved.
        """
        self.select_option_by_label(CLASS_FILTER_LABEL, _exact(class_name))
        self.wait_for_rows()

    def search(self, query: str) -> None:
        self.page.get_by_placeholder(SEARCH_PLACEHOLDER).first.fill(query)
        self.wait_for_rows()

    def wait_for_rows(self, timeout_ms: int = 30_000) -> None:
        """Block until the table has settled on rows or on its empty state.

        The header renders immediately and the body swaps a spinner row for one
        of the two, so asserting on the header alone would pass mid-flight.
        """
        body = self.page.locator("table tbody")
        settled = body.get_by_text(EMPTY_TABLE).first.or_(
            body.locator("tr").filter(has=self.page.get_by_role("checkbox")).first
        )
        expect(settled.first).to_be_visible(timeout=timeout_ms)

    # ─────────────────────────── the rows ──────────────────────────

    def find_row(self, student_name: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has=self.page.get_by_text(_exact(student_name))
        ).first

    def cell(self, student_name: str, column: int) -> Locator:
        """One cell of ``student_name``'s row, by column index (see ``COLUMN``)."""
        return self.find_row(student_name).get_by_role("cell").nth(column)

    def expect_status(self, student_name: str, status_label: str,
                      timeout_ms: int = 20_000) -> None:
        expect(self.cell(student_name, COLUMN["status"])).to_have_text(
            _exact(status_label), timeout=timeout_ms
        )

    def open_row_menu(self, student_name: str) -> None:
        """Open a row's "…" menu (Mark Attendance / Check In / Check Out / View)."""
        row = self.find_row(student_name)
        expect(row).to_be_visible(timeout=30_000)
        # The bulk-select control is a Radix Checkbox, which carries an explicit
        # role=checkbox and so is not a "button" — the trigger is the only one.
        row.get_by_role("button").last.click()

    # ──────────────────────── reading only ─────────────────────────

    def expect_no_load_failure(self) -> None:
        """The register rendered its own content, not the load-failure panel.

        ``PageError`` replaces the whole page, so this is what separates "the
        register is empty" from "the register was never served".
        """
        expect(self.page.get_by_text(LOAD_FAILURE_TITLE)).to_have_count(0)

    def expect_stats(self) -> None:
        """Assert the seven-tile summary strip rendered.

        Scoped to the ``<dl>``: "Absent" is also a row status badge, so a
        page-wide match could pass on a table row instead of on the tile.
        """
        stats = self.page.locator("dl").first
        expect(stats).to_be_visible(timeout=20_000)
        for tile in STAT_TILES:
            expect(stats.get_by_text(_exact(tile)).first).to_be_visible()

    def expect_columns(self) -> None:
        """Assert the register's header row spells out every column.

        Not ``get_by_role("columnheader")``: the header row is the reliable
        anchor here, and matching each ``<th>`` inside it keeps the assertion
        insensitive to the icon the Status header also renders.
        """
        header = self.page.locator("table thead tr").first
        expect(header).to_be_visible(timeout=15_000)
        for column in TABLE_COLUMNS:
            expect(header.locator("th").filter(has_text=_exact(column)).first).to_be_visible()

    def expect_filter_shows(self, value: str) -> None:
        """Assert some filter trigger currently reads ``value``.

        Used for the academic year and term, which the page selects for itself
        from whichever pair is active — the assertion is that it did so, not
        that a test set them. ``as_pattern`` because an academic year is named
        "2026/2027" and a bare slash closes the serialized selector early.
        """
        trigger = self.page.get_by_role("combobox").filter(
            has_text=as_pattern(_exact(value))
        ).first
        expect(trigger).to_be_visible(timeout=20_000)

    # ───────────────────── the calendar overview ───────────────────

    def open_view_all(self) -> None:
        """Follow "View All Attendance" through to the month calendar."""
        self.page.get_by_role("button", name=VIEW_ALL_BUTTON).first.click()
        self.page.wait_for_url(re.compile(r"/module/attendance/view_all"), timeout=20_000)
        self.expect_view_all_loaded()

    def expect_view_all_loaded(self) -> None:
        expect(self.page.get_by_role("heading", name=VIEW_ALL_HEADING)).to_be_visible(
            timeout=20_000
        )
        # The grid mounts behind a blocking overlay while the month's fetch is in
        # flight; waiting it out is what makes the grid assertions meaningful.
        #
        # The overlay paints a beat *after* the route commits, so asking "is it
        # gone?" straight away races it: the check passes on the frame before the
        # spinner exists, and every later assertion then reads a calendar that is
        # still greyed out behind it. Wait for the overlay to show up first — and
        # tolerate the fetch resolving before it ever paints.
        #
        # A single "count == 0" is not enough either. The route mounts twice
        # under the dev server — the backend log shows /attendance/?start_date=…
        # (and /classes/, /academic-year/) fetched once per mount, a beat apart —
        # so the overlay clears, then comes straight back for the second mount.
        # A check that fires in that gap reports "loaded" for a calendar the user
        # is still watching spin. Require the absence to *hold* past the remount.
        loading = self.page.get_by_text(VIEW_ALL_LOADING)
        try:
            loading.first.wait_for(state="visible", timeout=3_000)
        except PlaywrightTimeoutError:
            pass
        self._wait_until_settled(loading, timeout_ms=45_000, stable_ms=2_500)
        expect(self.page.get_by_text(VIEW_ALL_FAILURE_TITLE)).to_have_count(0)

    def _wait_until_settled(
        self, locator: Locator, *, timeout_ms: int, stable_ms: int
    ) -> None:
        """Wait until ``locator`` has been absent continuously for ``stable_ms``."""
        deadline = time.monotonic() + timeout_ms / 1000
        gone_since: float | None = None
        while time.monotonic() < deadline:
            if locator.count() == 0:
                if gone_since is None:
                    gone_since = time.monotonic()
                elif time.monotonic() - gone_since >= stable_ms / 1000:
                    return
            else:
                gone_since = None
            self.page.wait_for_timeout(200)
        raise AssertionError(
            "the attendance calendar never finished loading: "
            f"{VIEW_ALL_LOADING.pattern!r} was still on screen after "
            f"{timeout_ms / 1000:.0f}s"
        )

    def expect_calendar_grid(self, month_label: str) -> None:
        """Assert the calendar shows ``month_label`` above a full week header."""
        expect(self.page.get_by_role("heading", name=_exact(month_label))).to_be_visible(
            timeout=20_000
        )
        for day in WEEKDAYS:
            expect(self.page.get_by_text(_exact(day)).first).to_be_visible()

    # ────────────────────────── the modal ──────────────────────────

    def mark_attendance(
        self,
        *,
        student_name: str,
        status: str,
        notes: str | None = None,
    ) -> None:
        """Record (or revise) one student's attendance for the selected date.

        The modal pre-fills from any existing record, so the same call creates
        the first record and edits it afterwards; only the fields named here are
        touched, and the date picker is deliberately left alone (its default is
        the date the register is already showing).
        """
        modal = self.open_mark_form(student_name)
        self.fill_mark_form(modal, status=status, notes=notes)
        self.submit_mark_form(modal)

    def open_mark_form(self, student_name: str) -> Locator:
        """Open a row's Mark Attendance modal and return it."""
        self.open_row_menu(student_name)
        self.page.get_by_role("menuitem", name=MARK_ITEM).first.click()

        modal = self.page.get_by_role("dialog").filter(has_text=MARK_MODAL).first
        expect(modal).to_be_visible(timeout=15_000)
        return modal

    def fill_mark_form(self, modal: Locator, *, status: str,
                       notes: str | None = None) -> None:
        self._select_status(modal, status)
        if notes is not None:
            modal.get_by_placeholder(NOTES_PLACEHOLDER).first.fill(notes)

    def submit_mark_form(self, modal: Locator) -> None:
        modal.get_by_role("button", name=SAVE_CHANGES_BUTTON).first.click()
        self.expect_toast(SAVE_TOAST, timeout_ms=20_000)
        expect(modal).to_be_hidden(timeout=15_000)
        # The save triggers a full refetch; wait it out so the caller's cell
        # assertions read the reloaded row rather than the stale one.
        self.wait_for_rows()

    # ───────────────────────── internals ───────────────────────────

    def _select_status(self, modal: Locator, status_label: str) -> None:
        """Pick ``status_label`` out of the modal's antd Status Select."""
        # <div class="space-y-2"><label>Status</label><Select/></div>
        group = modal.get_by_text(STATUS_FIELD_LABEL).first.locator("xpath=..")
        group.locator(".ant-select").first.click()

        # Scoped to the dropdown that is actually open: antd leaves every
        # dropdown it has rendered mounted-but-hidden.
        option = self.page.locator(".ant-select-dropdown:visible").last.locator(
            ".ant-select-item-option"
        ).filter(has_text=_exact(status_label)).first
        try:
            option.wait_for(state="visible", timeout=15_000)
        except PlaywrightTimeoutError as exc:
            raise AssertionError(
                f"The Status dropdown never offered {status_label!r}. Its options "
                "are the fixed STATUS_OPTIONS of AttendanceActionModal.tsx: "
                "Present, Absent, Late, Excused, Half Day."
            ) from exc
        option.click()


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
