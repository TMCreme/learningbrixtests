"""Incident Reports — ``/module/incidents_reporting`` and its two forms.

Three screens, one page object
    ``/module/incidents_reporting`` is the log: a table of every incident filed
    in the signed-in user's branch this academic year, with a row menu offering
    "View Details", "Edit" and "Delete". ``/create`` and ``/{id}/edit`` are
    full-page forms rather than modals, so this object owns all three — the
    create form and the edit form are near-identical, and the only way to reach
    either is from the log.

The route is *not* the module key
    The sidebar entry and the URL both say ``incidents_reporting``; the feature
    pack, ``useModuleGuard`` and the backend's permission module all say
    ``incidents``. Both spellings are load-bearing and neither is a typo.

Why the fields are driven the way they are
    Every ``<label>`` on these forms is a bare ``<label>`` with no ``for``, so
    ``get_by_label`` never binds — the field patterns below therefore carry the
    real placeholder as an alternation branch, which is what
    ``BasePage.fill_labeled`` falls through to. The dropdowns are antd
    ``Select``s whose triggers render the *chosen* value (empty before one is
    chosen), so they too are anchored on the adjacent label — but through
    :meth:`IncidentsPage._select_antd` rather than
    ``BasePage.select_option_by_label``, because the only ``role="option"`` in
    rc-select's markup belongs to a 0×0 accessibility mirror rather than to the
    row a user clicks.

    The date is committed with ``BasePage.commit_date`` — never with Enter. The
    time is committed the equivalent way, by clicking the panel's own "OK"
    button (:meth:`_commit_time`): antd's TimePicker takes a typed value but
    only writes it back on OK, and Enter anywhere on these pages is the trap
    described in ``BasePage.commit_date``.

Desktop table only
    The page renders a ``<table>`` above ``md`` and a stack of cards below it,
    and *both* are in the DOM. Every row locator here is scoped to
    ``table tbody tr``, which is the desktop half — the demo viewport is 1280px
    wide, so that is the half a viewer sees.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── routes ───────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/incidents_reporting(?:$|[?#])")
CREATE_URL = re.compile(r"/module/incidents_reporting/create(?:$|[?#])")
EDIT_URL = re.compile(r"/module/incidents_reporting/\d+/edit(?:$|[?#])")

# The list's own fetch (incidentReportingHandler.listIncidentReports).
LIST_ENDPOINT = "/incidents/list"

# ── sidebar (SideNavigation/nav-config.tsx, "Incidents Module") ──────────────
NAV_INCIDENTS = re.compile(r"^\s*Incidents Reporting\s*$", re.I)

# ── the log (page.tsx) ───────────────────────────────────────────────────────
HEADING = re.compile(r"^\s*Incident Reports\s*$", re.I)
SUBHEADING = re.compile(r"Manage, track, and resolve all school incidents", re.I)

NEW_INCIDENT_BUTTON = re.compile(r"^\s*New Incident\s*$", re.I)
STUDENT_HISTORY_BUTTON = re.compile(r"^\s*Student History\s*$", re.I)
MY_ASSIGNED_BUTTON = re.compile(r"^\s*My Assigned\s*$", re.I)

LOADING_ROW = re.compile(r"Loading incidents", re.I)
LOAD_FAILURE = re.compile(r"^\s*Failed to load incidents\s*$", re.I)
EMPTY_TITLE = re.compile(r"^\s*No incidents found\s*$", re.I)

TABLE_HEADERS = (
    "Title", "Involved", "Severity", "Status", "Date", "Reported By",
    "Assigned To", "Actions",
)

SEARCH_PLACEHOLDER = re.compile(r"Search by title, reporter, location", re.I)

# Row menu items (Radix DropdownMenu → role="menuitem").
MENU_VIEW_DETAILS = re.compile(r"^\s*View Details\s*$", re.I)
MENU_EDIT = re.compile(r"^\s*Edit\s*$", re.I)
MENU_DELETE = re.compile(r"^\s*Delete\s*$", re.I)

# ── the detail modal (an antd Modal on the list route) ───────────────────────
DETAIL_CLOSE_BUTTON = re.compile(r"^\s*Close\s*$", re.I)
INVOLVED_STUDENTS_HEADING = re.compile(r"Involved Students \((\d+)\)", re.I)
FOLLOW_UP_BADGE = re.compile(r"Follow-up Required", re.I)

# ── the create form (create/page.tsx) ────────────────────────────────────────
CREATE_HEADING = re.compile(r"^\s*New Incident Report\s*$", re.I)
CREATE_SUBMIT = re.compile(r"^\s*Create Incident\s*$", re.I)
CREATED_TOAST = re.compile(r"Incident report created successfully", re.I)

# ── the edit form ([id]/edit/page.tsx) ───────────────────────────────────────
EDIT_HEADING = re.compile(r"^\s*Edit Incident Report\s*$", re.I)
EDIT_LOADING = re.compile(r"Loading incident record", re.I)
EDIT_SUBMIT = re.compile(r"^\s*Save Changes\s*$", re.I)
UPDATED_TOAST = re.compile(r"Incident report updated successfully", re.I)

# ── fields ───────────────────────────────────────────────────────────────────
# Each pattern is "<label>|<placeholder>": the labels carry no ``for``, so only
# the placeholder branch ever matches (see the module docstring).
TITLE_FIELD = re.compile(
    r"^\s*Title\s*\*?\s*$|Student altercation in the hallway", re.I
)
LOCATION_FIELD = re.compile(r"^\s*Location\s*$|Hallway near Block A", re.I)
DESCRIPTION_FIELD = re.compile(
    r"^\s*Description\s*\*?\s*$|Describe the incident in detail", re.I
)
WITNESSES_FIELD = re.compile(r"^\s*Witnesses\s*$|Names of witnesses", re.I)
ACTIONS_TAKEN_FIELD = re.compile(
    r"^\s*Actions Taken\s*$|Describe any immediate actions taken", re.I
)
FOLLOW_UP_NOTES_FIELD = re.compile(
    r"^\s*Follow-up Notes\s*$|What follow-up actions are needed", re.I
)
RESOLUTION_NOTES_FIELD = re.compile(
    r"^\s*Resolution Notes\s*$|How was this incident resolved", re.I
)

# Labels the antd Selects are anchored on. Anchored so "Incident Type" cannot
# also match "Incident Date", and so the trailing required-marker "*" (a <span>
# inside the same label) is tolerated.
TYPE_LABEL = re.compile(r"^\s*Incident Type\s*\*?\s*$", re.I)
SEVERITY_LABEL = re.compile(r"^\s*Severity\s*\*?\s*$", re.I)
STATUS_LABEL = re.compile(r"^\s*Status\s*\*?\s*$", re.I)
INVOLVED_STUDENTS_LABEL = re.compile(r"^\s*Involved Students\s*$", re.I)
ASSIGNED_TO_LABEL = re.compile(r"^\s*Assigned To\s*$", re.I)

# antd's own default picker placeholders.
DATE_PICKER = re.compile(r"^\s*Select date\s*$", re.I)
TIME_PICKER = re.compile(r"^\s*Select time\s*$", re.I)

FOLLOW_UP_PROMPT = re.compile(r"Requires Follow-up\?", re.I)

# What the table and the modal render for each stored enum value
# (page.tsx::fmt — underscores to spaces, title-cased).
BEHAVIORAL = "Behavioral"
INJURY = "Injury"
MEDICAL = "Medical"

SEVERITY_MEDIUM = "Medium"
SEVERITY_HIGH = "High"

STATUS_REPORTED = "Reported"
STATUS_UNDER_INVESTIGATION = "Under Investigation"
STATUS_RESOLVED = "Resolved"


class IncidentsPage(BasePage):
    """The incident log, plus the create and edit forms it leads to."""

    URL = "/module/incidents_reporting"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "IncidentsPage":
        super().open()
        return self

    def open_from_sidebar(self) -> "IncidentsPage":
        """Reach the log the way a real user does — through the sidebar.

        Falls back to the route when the sidebar is collapsed (it is on narrow
        viewports); how the user got here is worth showing, but it is not what
        this page object asserts.
        """
        link = self.page.get_by_role("link", name=as_pattern(NAV_INCIDENTS)).first
        if link.count():
            link.click()
        else:
            self.open()
        self.page.wait_for_url(LIST_URL, timeout=30_000)
        return self

    def expect_nav_entry(self) -> None:
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_INCIDENTS)).first
        ).to_be_visible(timeout=30_000)

    # ───────────────────────── the log ───────────────────────────

    def wait_for_table(self, timeout_ms: int = 40_000) -> "IncidentsPage":
        """Wait out the "Loading incidents…" panel.

        The table is not rendered at all while the fetch is in flight, so the
        spinner copy going away is the only signal that the response has landed;
        both an empty log and a populated one clear it.
        """
        expect(self.page.get_by_text(as_pattern(LOADING_ROW))).to_have_count(
            0, timeout=timeout_ms
        )
        expect(self.page.locator("table thead tr").first).to_be_visible(
            timeout=timeout_ms
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

    def expect_manage_controls(self) -> None:
        """The three things a role that may *manage* incidents is offered."""
        for name in (NEW_INCIDENT_BUTTON, STUDENT_HISTORY_BUTTON, MY_ASSIGNED_BUTTON):
            expect(
                self.page.get_by_role("button", name=as_pattern(name)).first
            ).to_be_visible(timeout=30_000)

    def rows(self) -> Locator:
        return self.page.locator("table tbody tr")

    def row(self, title: str) -> Locator:
        """The row for one incident, matched on its title cell.

        Anchored on the *cell* rather than the row: the row's text is every
        column run together, so a title that happens to be a prefix of another
        would match twice.
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
        incident_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        reported_by: str | None = None,
        assigned_to: str | None = None,
        student_count: int | None = None,
        follow_up: bool | None = None,
    ) -> None:
        """The row is listed, and carries what the server stored against it."""
        row = self.row(title)
        expect(row).to_be_visible(timeout=30_000)
        for value in (incident_type, severity, status, reported_by, assigned_to):
            if value:
                expect(row).to_contain_text(as_pattern(re.escape(value)))
        if student_count is not None:
            # The counts render as "Students: 1Staff: 0" with no separator, so
            # the boundary after the number has to be "not another digit" — a
            # ``\b`` would be looking for one between "1" and "S" and never find
            # it.
            expect(row).to_contain_text(
                as_pattern(rf"Students:\s*{student_count}(?!\d)")
            )
        if follow_up:
            # Rendered inside the title cell only while follow_up_required.
            expect(row.locator("td").first).to_contain_text(
                as_pattern("Follow-up needed")
            )

    def expect_incident_absent(self, title: str) -> None:
        expect(self.row(title)).to_have_count(0)

    def search(self, text: str) -> "IncidentsPage":
        """Filter the log client-side by title, reporter or location."""
        self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER)).first.fill(text)
        return self

    def filter_by(
        self,
        *,
        incident_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
    ) -> "IncidentsPage":
        """Narrow the log with the toolbar's three dropdowns.

        These three are **Radix** Selects (``@/components/ui/select``), unlike
        the antd ones on the create and edit forms, so their rows really are
        ``role="option"`` and can be clicked by accessible name.

        They are reached by position rather than by their current text: each one
        starts on its own "All …" item and then renders whatever was last
        chosen, so there is no stable string to filter the trigger on. Page order
        is the toolbar's own — Type, Severity, Status — and they are the only
        comboboxes this screen renders.

        Pass the "All Types" / "All Severities" / "All Statuses" row to clear one.
        """
        for index, choice in ((0, incident_type), (1, severity), (2, status)):
            if choice is None:
                continue
            self.page.get_by_role("combobox").nth(index).click()
            self.page.get_by_role(
                "option", name=as_pattern(rf"^\s*{re.escape(choice)}\s*$")
            ).first.click()
        return self

    # ───────────────────── the row's own menu ────────────────────

    def open_row_menu(self, title: str) -> None:
        """Open the ⋮ menu — the only control in the row's last cell."""
        self.row(title).locator("td").last.get_by_role("button").first.click()

    def view_details(self, title: str) -> "IncidentsPage":
        self.open_row_menu(title)
        self.page.get_by_role("menuitem", name=as_pattern(MENU_VIEW_DETAILS)).click()
        # The modal opens empty and fills from GET /incidents/{id}. "Created" is
        # what says that landed: it is one of the Descriptions labels, and it is
        # the one label the table underneath has no column for — waiting on
        # "Date" or "Reported By" would be answered by the table header instead.
        expect(
            self.page.get_by_text(as_pattern(r"^\s*Created\s*$")).first
        ).to_be_visible(timeout=30_000)
        return self

    def expect_details(
        self,
        *,
        severity: str | None = None,
        status: str | None = None,
        incident_type: str | None = None,
        location: str | None = None,
        description: str | None = None,
        actions_taken: str | None = None,
        witnesses: str | None = None,
        student_name: str | None = None,
        follow_up: bool = False,
    ) -> None:
        """Assert the open detail modal.

        Asserted at page level rather than inside a container, and every string
        chosen so that page level is honest: the table stays mounted behind the
        overlay, so a bare "Medium" would match the row's own severity tag
        whether the modal rendered one or not. The badges are therefore matched
        with the modal's own ``"Severity: Medium"`` prefixes, and the rest —
        location, description, actions taken, witnesses, the involved-student
        list — are fields the table has no column for at all.

        Deliberately not asserted here: reporter and assignee. Both *are*
        table columns, so a page-level match on them would prove nothing about
        the modal; they are checked on the row instead.
        """
        for label, value in (
            ("Severity", severity), ("Status", status), ("Type", incident_type),
        ):
            if value:
                expect(
                    self.page.get_by_text(
                        as_pattern(rf"{label}:\s*{re.escape(value)}")
                    ).first
                ).to_be_visible(timeout=15_000)
        for value in (location, description, actions_taken, witnesses):
            if value:
                expect(
                    self.page.get_by_text(as_pattern(re.escape(value))).first
                ).to_be_visible()
        if student_name:
            expect(
                self.page.get_by_text(as_pattern(INVOLVED_STUDENTS_HEADING)).first
            ).to_be_visible()
            expect(
                self.page.get_by_text(as_pattern(re.escape(student_name))).first
            ).to_be_visible()
        if follow_up:
            expect(
                self.page.get_by_text(as_pattern(FOLLOW_UP_BADGE)).first
            ).to_be_visible()

    def close_details(self) -> "IncidentsPage":
        """Dismiss the modal from its footer button.

        Hidden rather than removed afterwards: antd keeps a closed Modal mounted
        (``.ant-modal-wrap`` goes ``display:none``), so counting the button to
        zero would never come true.
        """
        footer_close = self.page.get_by_role(
            "button", name=as_pattern(DETAIL_CLOSE_BUTTON)
        ).last
        footer_close.click()
        expect(footer_close).to_be_hidden(timeout=15_000)
        return self

    # ───────────────────────── create ────────────────────────────

    def start_new_incident(self) -> "IncidentsPage":
        self.click_button(NEW_INCIDENT_BUTTON)
        self.page.wait_for_url(CREATE_URL, timeout=30_000)
        expect(
            self.page.get_by_role("heading", name=as_pattern(CREATE_HEADING))
        ).to_be_visible(timeout=30_000)
        return self

    def fill_incident_form(
        self,
        *,
        title: str | None = None,
        incident_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        incident_date: str | None = None,
        incident_time: str | None = None,
        location: str | None = None,
        description: str | None = None,
        witnesses: str | None = None,
        actions_taken: str | None = None,
        resolution_notes: str | None = None,
        student_name: str | None = None,
        assign_to: str | None = None,
        follow_up_notes: str | None = None,
    ) -> "IncidentsPage":
        """Fill whichever of the shared create/edit fields were named.

        Ordered the way the create form lays them out, so the video reads top to
        bottom. ``status`` exists on the edit form only, ``resolution_notes``
        likewise.
        """
        if title is not None:
            self.fill_labeled(TITLE_FIELD, title)
        if status is not None:
            self._select_antd(STATUS_LABEL, _exact(status))
        if incident_type is not None:
            self._select_antd(TYPE_LABEL, _exact(incident_type))
        if severity is not None:
            self._select_antd(SEVERITY_LABEL, _exact(severity))
        if incident_date is not None:
            # antd's default format, and never committed with Enter.
            self.commit_date(
                self.page.get_by_placeholder(as_pattern(DATE_PICKER)).first,
                incident_date,
            )
        if incident_time is not None:
            self._commit_time(incident_time)
        if location is not None:
            self.fill_labeled(LOCATION_FIELD, location)
        if description is not None:
            self.fill_labeled(DESCRIPTION_FIELD, description)
        if witnesses is not None:
            self.fill_labeled(WITNESSES_FIELD, witnesses)
        if actions_taken is not None:
            self.fill_labeled(ACTIONS_TAKEN_FIELD, actions_taken)
        if student_name is not None:
            self._pick_multiple(INVOLVED_STUDENTS_LABEL, student_name)
        if assign_to is not None:
            self._select_antd(
                ASSIGNED_TO_LABEL, re.compile(re.escape(assign_to), re.I)
            )
        if follow_up_notes is not None:
            self.require_follow_up(follow_up_notes)
        if resolution_notes is not None:
            self.fill_labeled(RESOLUTION_NOTES_FIELD, resolution_notes)
        return self

    def require_follow_up(self, notes: str) -> "IncidentsPage":
        """Flip the follow-up switch and write the note it reveals."""
        switch = self.page.get_by_role("switch").first
        if switch.get_attribute("aria-checked") != "true":
            switch.click()
        expect(switch).to_have_attribute("aria-checked", "true")
        self.fill_labeled(FOLLOW_UP_NOTES_FIELD, notes)
        return self

    def submit_new_incident(self) -> "IncidentsPage":
        """Save the create form and land back on the log."""
        self.click_button(CREATE_SUBMIT)
        self.expect_toast(CREATED_TOAST, timeout_ms=30_000)
        self.page.wait_for_url(LIST_URL, timeout=30_000)
        self.wait_for_table()
        return self

    # ────────────────────────── edit ─────────────────────────────

    def start_editing(self, title: str) -> "IncidentsPage":
        """Open the edit form from the row menu."""
        self.open_row_menu(title)
        self.page.get_by_role("menuitem", name=as_pattern(MENU_EDIT)).click()
        self.page.wait_for_url(EDIT_URL, timeout=30_000)
        expect(
            self.page.get_by_role("heading", name=as_pattern(EDIT_HEADING))
        ).to_be_visible(timeout=30_000)
        # The form mounts empty and is populated by GET /incidents/{id}; typing
        # before that lands would be overwritten by the response.
        expect(self.page.get_by_text(as_pattern(EDIT_LOADING))).to_have_count(
            0, timeout=30_000
        )
        expect(
            self.page.get_by_placeholder(as_pattern(TITLE_FIELD)).first
        ).not_to_have_value("", timeout=30_000)
        return self

    def expect_form_prefilled(self, **fields: str) -> None:
        """The edit form opened on the stored record, not on a blank one."""
        for name, value in fields.items():
            pattern = _FORM_FIELDS[name]
            expect(
                self.page.get_by_placeholder(as_pattern(pattern)).first
            ).to_have_value(value, timeout=15_000)

    def submit_edits(self) -> "IncidentsPage":
        self.click_button(EDIT_SUBMIT)
        self.expect_toast(UPDATED_TOAST, timeout_ms=30_000)
        self.page.wait_for_url(LIST_URL, timeout=30_000)
        self.wait_for_table()
        return self

    # ───────────────────────── internals ─────────────────────────

    def _commit_time(self, value: str) -> None:
        """Set an antd TimePicker without pressing Enter.

        Same trap as ``BasePage.commit_date``: these forms are plain ``<div>``s
        of controlled inputs, and Enter inside a picker is the gesture that has
        wiped half-filled forms elsewhere in this app. antd's TimePicker keeps
        the typed value in its panel until the panel's own "OK" is clicked, so
        that is what commits it here.
        """
        picker = self.page.get_by_placeholder(as_pattern(TIME_PICKER)).first
        picker.click()
        picker.fill(value)
        panel = self.page.locator(".ant-picker-dropdown:visible").last
        ok = panel.locator(".ant-picker-ok button").first
        if ok.count():
            ok.click()
            return
        picker.blur()

    def _select_antd(self, label: re.Pattern[str], option: re.Pattern[str]) -> None:
        """Pick from an antd ``Select`` identified by its adjacent ``<label>``.

        ``BasePage.select_option_by_label`` cannot drive these. rc-select (what
        antd builds on) renders each choice **twice**: once as the row a user
        sees, a role-less ``div.ant-select-item-option`` inside the portalled
        dropdown, and once inside a 0×0 ``overflow:hidden`` accessibility mirror
        that sits in place of the trigger and carries the only
        ``role="option"``/``aria-label`` in the markup. ``get_by_role("option")``
        therefore resolves to the mirror — which is earlier in the DOM and never
        visible — and the click waits out its timeout against a fully open,
        perfectly clickable menu. Same trap as ``AttendanceActionModal``'s
        Selects; see ``tests/pages/academics/attendance.py``.

        So the row is matched on ``.ant-select-item-option``, scoped to the
        dropdown that is actually *open*: antd leaves every dropdown it has
        rendered mounted-but-hidden, so a page-wide match would happily resolve
        into a closed one.
        """
        labels = self.page.locator("label").filter(has_text=label)
        node = labels.first if labels.count() else self.page.get_by_text(label).first
        group = node.locator("xpath=..")
        group.locator(".ant-select").first.click()
        row = (
            self.page.locator(".ant-select-dropdown:visible")
            .last.locator(".ant-select-item-option")
            .filter(has_text=option)
            .first
        )
        row.wait_for(state="visible", timeout=15_000)
        row.click()

    def _pick_multiple(self, label: re.Pattern[str], option_text: str) -> None:
        """Add one entry to a multi-select, then close the dropdown.

        The option text is matched loosely, not anchored: this Select labels its
        rows ``"<first> <other> (<admission number>)"``, so the person's name is
        a prefix of the row rather than the whole of it.

        A ``mode="multiple"`` antd Select keeps its list open after a pick — the
        open panel then covers the fields below it, so the next click would land
        on the overlay. Escape closes it; Enter must never be used (see
        ``BasePage.commit_date``).
        """
        self._select_antd(label, re.compile(re.escape(option_text), re.I))
        self.page.keyboard.press("Escape")


def _exact(text: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(text)}\s*$", re.I)


# Fields ``expect_form_prefilled`` can be asked about, by keyword.
_FORM_FIELDS: dict[str, re.Pattern[str]] = {
    "title": TITLE_FIELD,
    "location": LOCATION_FIELD,
    "witnesses": WITNESSES_FIELD,
}
