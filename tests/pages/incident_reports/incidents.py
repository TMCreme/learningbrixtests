"""Incident Reports → the school's incident register (/module/incidents_reporting).

The module key is ``incidents`` but the route is ``incidents_reporting`` —
``src/middleware.ts`` maps the second onto the first, and ``nav-config.tsx``
files the single sidebar entry ("Incidents Reporting") under an **Incidents
Module** group that is ``branchOnly``. So for a SchoolAdmin the entry does not
exist at all until a branch has been picked on ``/module/school_admin_dashboard``
(``BranchesPage.select_branch``) — and the screen's own three calls
(``/incidents/list``, ``/incidents/statistics/summary`` and the per-row
``/incidents/{id}``) all append ``branch_id`` from ``useBranchStore`` for that
role, which the backend's ``branch_id_required`` insists on.

What the register renders
    One ``GET /incidents/list`` into a real ``<table>`` (desktop) plus a
    ``md:hidden`` card list (mobile) — at the 1280px demo viewport only the table
    is on screen, which is why :meth:`row` is anchored on ``table tbody tr``.
    Above it, ``ModuleHeader`` renders three ``<dt>``/``<dd>`` stat tiles fed by
    the statistics endpoint, and a search box plus three Radix Selects that
    filter the already-fetched rows *client-side* — no refetch, so nothing here
    needs to wait on a response.

    ``listIncidentReports()`` is called with no academic year, and the route then
    falls back to the branch's active year: an incident filed under a different
    year is simply not on this screen. Provisioning phase B activates one.

The detail modal is antd, not Radix
    "View Details" on the row menu fetches ``GET /incidents/{id}`` and opens an
    antd ``Modal``. antd leaves a modal it has opened once mounted-but-hidden, so
    every lookup is scoped to ``.ant-modal:visible`` rather than to
    ``get_by_role("dialog")``, which would match the (also mounted) delete
    confirmation just as happily.

Read-only companions
    ``/module/incidents_reporting/students`` and its
    ``students/{student_id}`` page are modelled by
    :class:`StudentIncidentHistoryPage`. Neither writes anything: the first is a
    student picker, the second renders
    ``GET /incidents/student/{id}/history`` with the same view-only modal.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── the routes ───────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/incidents_reporting(?:$|[?#])")
STUDENT_PICKER_URL = re.compile(r"/module/incidents_reporting/students(?:$|[?#])")
STUDENT_HISTORY_URL = re.compile(r"/module/incidents_reporting/students/\d+")

# ── sidebar entry (SideNavigation/nav-config.tsx, "Incidents Module") ────────
NAV_INCIDENTS_REPORTING = re.compile(r"^\s*Incidents Reporting\s*$", re.I)

# ── page chrome (incidents_reporting/page.tsx) ───────────────────────────────
HEADING = re.compile(r"^\s*Incident Reports\s*$", re.I)
SUBHEADING = re.compile(r"Manage, track, and resolve all school incidents", re.I)

LOADING_ROW = re.compile(r"Loading incidents", re.I)
LOAD_FAILURE = re.compile(r"^\s*Failed to load incidents\s*$", re.I)
EMPTY_TITLE = re.compile(r"^\s*No incidents found\s*$", re.I)

# The register's columns, in the order page.tsx declares its <TableHead>s.
TABLE_HEADERS = (
    "Title", "Involved", "Severity", "Status", "Date", "Reported By",
    "Assigned To", "Actions",
)

# ── the three ModuleHeader tiles, as page.tsx names them ─────────────────────
STAT_TOTAL = "Total Incidents"
STAT_OPEN = "Open / Reported"   # the "/" is why every lookup goes via as_pattern
STAT_CRITICAL_OPEN = "Critical Open"

# ── toolbar buttons ──────────────────────────────────────────────────────────
STUDENT_HISTORY_BUTTON = re.compile(r"^\s*Student History\s*$", re.I)
MY_ASSIGNED_BUTTON = re.compile(r"^\s*My Assigned\s*$", re.I)
NEW_INCIDENT_BUTTON = re.compile(r"^\s*New Incident\s*$", re.I)

# ── filters (client-side; each Select shows its current value) ───────────────
SEARCH_PLACEHOLDER = re.compile(r"Search by title, reporter, location", re.I)
FILTER_ALL_TYPES = "All Types"
FILTER_ALL_SEVERITIES = "All Severities"
FILTER_ALL_STATUSES = "All Statuses"

# ── the row menu ─────────────────────────────────────────────────────────────
VIEW_DETAILS_ITEM = re.compile(r"View Details", re.I)

# ── the detail modal ─────────────────────────────────────────────────────────
DETAIL_DESCRIPTION_HEADING = re.compile(r"^\s*Description\s*$", re.I)
DETAIL_ACTIONS_TAKEN_HEADING = re.compile(r"^\s*Actions Taken\s*$", re.I)
DETAIL_WITNESSES_HEADING = re.compile(r"^\s*Witnesses\s*$", re.I)
DETAIL_FOLLOW_UP_HEADING = re.compile(r"^\s*Follow-up Notes\s*$", re.I)
DETAIL_INVOLVED_STUDENTS_HEADING = re.compile(r"Involved Students \(\d+\)", re.I)
FOLLOW_UP_BADGE = re.compile(r"^\s*Follow-up Required\s*$", re.I)
CLOSE_BUTTON = re.compile(r"^\s*Close\s*$", re.I)


class IncidentsPage(BasePage):
    """The incident register — every incident filed against the active branch."""

    URL = "/module/incidents_reporting"

    def __init__(self, page, frontend_base_url: str):
        super().__init__(page, frontend_base_url)
        # Each Select opens on its "all" option and renders whatever is currently
        # chosen; that text is what select_option_in_combobox anchors on.
        self._type_filter = FILTER_ALL_TYPES
        self._severity_filter = FILTER_ALL_SEVERITIES
        self._status_filter = FILTER_ALL_STATUSES

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "IncidentsPage":
        super().open()
        return self

    def open_from_sidebar(self) -> "IncidentsPage":
        """Reach the register the way a real user does — via the sidebar.

        Falls back to the route when the sidebar is collapsed (it is on narrow
        viewports); how the user got here is worth showing, but it is not what
        this page object asserts.
        """
        link = self.page.get_by_role(
            "link", name=as_pattern(NAV_INCIDENTS_REPORTING)
        ).first
        if link.count():
            link.click()
        else:
            self.open()
        self.page.wait_for_url(LIST_URL, timeout=30_000)
        return self

    def expect_nav_entry(self) -> None:
        """The "Incidents Module" group is ``branchOnly`` — a branch must be
        selected before this can be visible for a SchoolAdmin."""
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_INCIDENTS_REPORTING)).first
        ).to_be_visible(timeout=30_000)

    def open_student_history(self) -> "StudentIncidentHistoryPage":
        """Toolbar → "Student History", the read-only per-pupil view."""
        self.click_button(STUDENT_HISTORY_BUTTON)
        self.page.wait_for_url(STUDENT_PICKER_URL, timeout=30_000)
        return StudentIncidentHistoryPage(self.page, self.frontend_base_url)

    # ───────────────────────── readers ───────────────────────────

    def wait_for_table(self, timeout_ms: int = 30_000) -> "IncidentsPage":
        """Wait out the "Loading incidents…" panel.

        The table is not rendered at all while the fetch is in flight, so the
        spinner's copy going away is what says the response has landed — an empty
        register and a populated one both clear it.
        """
        expect(self.page.get_by_text(as_pattern(LOADING_ROW))).to_have_count(
            0, timeout=timeout_ms
        )
        return self

    def expect_loaded(self) -> None:
        expect(
            self.page.get_by_role("heading", name=as_pattern(HEADING))
        ).to_be_visible(timeout=30_000)
        expect(self.page.get_by_text(as_pattern(SUBHEADING)).first).to_be_visible()

    def expect_no_load_failure(self) -> None:
        """The fetch did not fall into ``PageError``."""
        expect(self.page.get_by_text(as_pattern(LOAD_FAILURE))).to_have_count(0)

    def expect_headers(self) -> None:
        """Assert the header row by position, pinning the column order."""
        header_cells = self.page.locator("table thead tr").first.locator("th")
        expect(header_cells).to_have_count(len(TABLE_HEADERS))
        for index, header in enumerate(TABLE_HEADERS):
            expect(header_cells.nth(index)).to_have_text(
                as_pattern(rf"^\s*{re.escape(header)}\s*$")
            )

    def rows(self) -> Locator:
        return self.page.locator("table tbody tr")

    def row(self, title: str) -> Locator:
        """The row for one incident, matched on the title its first cell shows.

        Anchored on a *cell* rather than on the whole row: a row's text is every
        column run together, so a title that happened to repeat a reporter's name
        or a location would match rows it does not belong to.
        """
        return self.rows().filter(
            has=self.page.locator("td").filter(
                has_text=as_pattern(re.escape(title))
            )
        ).first

    def expect_incident(
        self,
        title: str,
        *,
        severity: str | None = None,
        status: str | None = None,
        incident_type: str | None = None,
        reported_by: str | None = None,
        students: int | None = None,
    ) -> None:
        """The incident is listed, carrying what the server stored against it."""
        row = self.row(title)
        expect(row).to_be_visible(timeout=30_000)
        for value in (severity, status, incident_type, reported_by):
            if value:
                expect(row).to_contain_text(as_pattern(re.escape(value)))
        if students is not None:
            expect(row).to_contain_text(as_pattern(rf"Students:\s*{students}\b"))

    def expect_incident_absent(self, title: str) -> None:
        expect(self.row(title)).to_have_count(0)

    def expect_empty_state(self) -> None:
        expect(self.page.get_by_text(as_pattern(EMPTY_TITLE)).first).to_be_visible(
            timeout=30_000
        )

    # ───────────────────────── stat tiles ────────────────────────

    def stat(self, name: str) -> Locator:
        """The ``<dd>`` value of one ModuleHeader tile, found by its ``<dt>``."""
        card = self.page.locator("dl > div").filter(
            has=self.page.locator("dt").filter(has_text=as_pattern(re.escape(name)))
        ).first
        return card.locator("dd").first

    def expect_stat_at_least(self, name: str, minimum: int) -> None:
        """The tile shows a number, and at least ``minimum``.

        Deliberately a floor rather than an equality: the whole batch shares one
        provisioned school, so a sibling unit filing an incident of its own must
        not turn this into a failure. What is being proved is that the tile is fed
        by the statistics endpoint rather than stuck on its "0" initial state.
        """
        value = self.stat(name)
        expect(value).to_be_visible(timeout=30_000)
        expect(value).to_have_text(as_pattern(r"^\s*\d+\s*$"), timeout=30_000)
        shown = int((value.inner_text() or "0").strip())
        assert shown >= minimum, (
            f"the {name!r} tile shows {shown}, but at least {minimum} incident(s) "
            f"were filed against this branch — the tile is fed by "
            f"GET /incidents/statistics/summary, so either that call was refused "
            f"or its answer never reached the tile"
        )

    # ───────────────────────── filtering ─────────────────────────

    def search(self, text: str) -> "IncidentsPage":
        """Type into the search box. Filtering is client-side — no refetch."""
        self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER)).first.fill(text)
        return self

    def filter_by_severity(self, label: str) -> "IncidentsPage":
        self.select_option_in_combobox(
            rf"^\s*{re.escape(self._severity_filter)}\s*$",
            rf"^\s*{re.escape(label)}\s*$",
        )
        self._severity_filter = label
        return self

    def filter_by_status(self, label: str) -> "IncidentsPage":
        self.select_option_in_combobox(
            rf"^\s*{re.escape(self._status_filter)}\s*$",
            rf"^\s*{re.escape(label)}\s*$",
        )
        self._status_filter = label
        return self

    def filter_by_type(self, label: str) -> "IncidentsPage":
        self.select_option_in_combobox(
            rf"^\s*{re.escape(self._type_filter)}\s*$",
            rf"^\s*{re.escape(label)}\s*$",
        )
        self._type_filter = label
        return self

    # ─────────────────────── the detail modal ────────────────────

    def open_details(self, title: str) -> "IncidentsPage":
        """Row menu → "View Details", which fetches ``GET /incidents/{id}``.

        The menu trigger is an icon-only Radix button with no accessible name; it
        is the only button in the row's last cell, which is how it is found here.
        """
        self.row(title).locator("td").last.get_by_role("button").first.click()
        self.page.get_by_role("menuitem", name=as_pattern(VIEW_DETAILS_ITEM)).first.click()
        expect(self.modal()).to_be_visible(timeout=30_000)
        return self

    def modal(self) -> Locator:
        """The open antd modal. Scoped to ``:visible`` — see the module docstring."""
        return self.page.locator(".ant-modal:visible").first

    def detail_value(self, label: str) -> Locator:
        """The content cell of one ``Descriptions.Item``, found by its label.

        ``Descriptions`` is ``bordered``, so a label renders as a ``<th>`` with
        its value in the very next cell. If that shape ever changes, the whole row
        is used instead — a looser but never wrong container.
        """
        cell = self.modal().locator(".ant-descriptions-item-label").filter(
            has_text=as_pattern(rf"^\s*{re.escape(label)}\s*$")
        ).first
        sibling = cell.locator("xpath=following-sibling::*[1]")
        return sibling if sibling.count() else cell.locator("xpath=ancestor::tr[1]")

    def expect_details(
        self,
        title: str,
        *,
        severity: str | None = None,
        status: str | None = None,
        incident_type: str | None = None,
        location: str | None = None,
        reported_by: str | None = None,
        assigned_to: str | None = None,
        description: str | None = None,
        actions_taken: str | None = None,
        witnesses: str | None = None,
        follow_up_notes: str | None = None,
        involved_student: str | None = None,
        follow_up_required: bool | None = None,
    ) -> None:
        """Assert the open modal against what the server holds for the incident.

        Every lookup is scoped to the modal rather than to the page: the register
        is still mounted behind the overlay and repeats the title, severity and
        status, so a page-level match on any of those would pass whether the modal
        rendered them or not.
        """
        modal = self.modal()
        expect(modal).to_be_visible(timeout=30_000)
        expect(modal).to_contain_text(as_pattern(re.escape(title)))

        for label, value in (
            ("Severity", severity), ("Status", status), ("Type", incident_type)
        ):
            if value:
                expect(modal).to_contain_text(
                    as_pattern(rf"{label}:\s*{re.escape(value)}")
                )

        for label, value in (
            ("Location", location),
            ("Reported By", reported_by),
            ("Assigned To", assigned_to),
        ):
            if value:
                expect(self.detail_value(label)).to_contain_text(
                    as_pattern(re.escape(value))
                )

        for heading, value in (
            (DETAIL_DESCRIPTION_HEADING, description),
            (DETAIL_ACTIONS_TAKEN_HEADING, actions_taken),
            (DETAIL_WITNESSES_HEADING, witnesses),
            (DETAIL_FOLLOW_UP_HEADING, follow_up_notes),
        ):
            if value:
                expect(modal.get_by_text(as_pattern(heading)).first).to_be_visible()
                expect(
                    modal.get_by_text(as_pattern(re.escape(value))).first
                ).to_be_visible()

        if involved_student:
            expect(
                modal.get_by_text(as_pattern(DETAIL_INVOLVED_STUDENTS_HEADING)).first
            ).to_be_visible()
            expect(
                modal.get_by_text(as_pattern(re.escape(involved_student))).first
            ).to_be_visible()

        if follow_up_required is not None:
            expect(modal.get_by_text(as_pattern(FOLLOW_UP_BADGE))).to_have_count(
                1 if follow_up_required else 0
            )

    def close_details(self) -> "IncidentsPage":
        self.modal().get_by_role("button", name=as_pattern(CLOSE_BUTTON)).first.click()
        expect(self.page.locator(".ant-modal:visible")).to_have_count(0, timeout=15_000)
        return self


# ── the student-facing half ──────────────────────────────────────────────────

STUDENT_PICKER_HEADING = re.compile(r"^\s*Student Incident History\s*$", re.I)
STUDENT_PICKER_SEARCH = re.compile(r"Search student by name or admission number", re.I)
STUDENT_PICKER_LOADING = re.compile(r"Loading students", re.I)
VIEW_HISTORY_BUTTON = re.compile(r"^\s*View Incident History\s*$", re.I)

HISTORY_HEADING = re.compile(r"^\s*Incident History\s*$", re.I)
HISTORY_LOG_HEADING = re.compile(r"^\s*Incident Log\s*$", re.I)
HISTORY_EMPTY = re.compile(r"^\s*No incident history recorded\s*$", re.I)
HISTORY_LOAD_FAILURE = re.compile(
    r"^\s*Failed to load student incident history\s*$", re.I
)
HISTORY_VIEW_DETAILS = re.compile(r"^\s*View details\s*$", re.I)


class StudentIncidentHistoryPage(BasePage):
    """The per-pupil incident record, reached from the register's toolbar.

    Two screens, both read-only: ``/students`` picks a pupil out of
    ``GET /student/``, and ``/students/{id}`` renders that pupil's
    ``GET /incidents/student/{id}/history`` plus the same view-only modal.
    """

    URL = "/module/incidents_reporting/students"

    def wait_for_students(self, timeout_ms: int = 30_000) -> "StudentIncidentHistoryPage":
        expect(self.page.get_by_text(as_pattern(STUDENT_PICKER_LOADING))).to_have_count(
            0, timeout=timeout_ms
        )
        return self

    def expect_picker_loaded(self) -> None:
        expect(
            self.page.get_by_role("heading", name=as_pattern(STUDENT_PICKER_HEADING))
        ).to_be_visible(timeout=30_000)

    def search_student(self, text: str) -> "StudentIncidentHistoryPage":
        """Type into the picker's search box; it refetches on every keystroke."""
        self.page.get_by_placeholder(as_pattern(STUDENT_PICKER_SEARCH)).first.fill(text)
        self.wait_for_students()
        return self

    def open_history_for(self, student_name: str) -> "StudentIncidentHistoryPage":
        row = self.page.locator("table tbody tr").filter(
            has_text=as_pattern(re.escape(student_name))
        ).first
        expect(row).to_be_visible(timeout=30_000)
        row.get_by_role("button", name=as_pattern(VIEW_HISTORY_BUTTON)).first.click()
        self.page.wait_for_url(STUDENT_HISTORY_URL, timeout=30_000)
        expect(
            self.page.get_by_role("heading", name=as_pattern(HISTORY_HEADING))
        ).to_be_visible(timeout=30_000)
        return self

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(as_pattern(HISTORY_LOAD_FAILURE))).to_have_count(0)

    def expect_student_header(self, name: str, *, class_name: str | None = None) -> None:
        expect(
            self.page.get_by_text(as_pattern(re.escape(name))).first
        ).to_be_visible(timeout=30_000)
        if class_name:
            expect(
                self.page.get_by_text(as_pattern(re.escape(class_name))).first
            ).to_be_visible()

    def entry(self, title: str) -> Locator:
        return self.page.locator("table tbody tr").filter(
            has=self.page.locator("td").filter(has_text=as_pattern(re.escape(title)))
        ).first

    def expect_entry(
        self,
        title: str,
        *,
        severity: str | None = None,
        status: str | None = None,
        location: str | None = None,
        reported_by: str | None = None,
    ) -> None:
        expect(
            self.page.get_by_text(as_pattern(HISTORY_LOG_HEADING)).first
        ).to_be_visible(timeout=30_000)
        row = self.entry(title)
        expect(row).to_be_visible(timeout=30_000)
        for value in (severity, status, location, reported_by):
            if value:
                expect(row).to_contain_text(as_pattern(re.escape(value)))

    def expect_entry_absent(self, title: str) -> None:
        expect(self.entry(title)).to_have_count(0)
