"""Change Requests → "My Change Requests", the requester's own log.

/module/change_request (singular — there is no ``/module/change_requests``
route; ``src/middleware.ts`` maps both this path and ``/module/pending_requests``
onto the ``change_requests`` *module* key). It renders one
``GET /pending-changes/my-requests`` into a table of the changes the signed-in
user has asked for, plus the status each is now in.

Read-only by design, for two different reasons
    The screen authors nothing: a request is raised from the module it belongs to
    (the fees and income screens' "Request Change" modals call
    ``POST /pending-changes/request``), and it is *approved* somewhere else again
    — ``/module/pending_requests``, whose sidebar entry ``SideNavigation.tsx``
    hides from anyone lacking ``manage change_requests``. So for a read-only role
    this page is the whole of the module: raise elsewhere, track here.

    The one write it does offer is a requester withdrawing their own request —
    the bin icon, rendered only while a row is still ``pending``. That is why
    :meth:`expect_no_authoring_controls` looks for *authoring* verbs (add / create
    / new / submit) rather than asserting a blanket absence of writes: the bin is
    legitimately there.

Locating things on it
    The rows are a real ``<table>``, so ``row()`` filters ``tbody tr`` on the
    request's own id cell — the "#12" the first column renders. That id comes back
    from the create call, so a row matched this way is provably the request the
    test seeded rather than "some row".

    The detail modal is a hand-rolled overlay ``<div>``, not a Radix dialog: it
    carries no ``role="dialog"``, so ``BasePage.dialog()`` would never find it and
    its contents are asserted at page level instead. That is safe because every
    string it shows — "Request Details", "Change Summary", "New Values
    (Requested)" — exists nowhere else on the route, and the table underneath
    renders neither the change summary nor either value set.

The status filter is a Radix Select whose trigger shows its current value, so it
is driven through :meth:`filter_by_status`, which anchors on that text and keeps
track of it (the page opens on "All Requests").
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── the route ────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/change_request(?:$|[?#])")

# The one call this screen makes (changeRequestHandler.GetMyRequestsHandler); the
# status filter is waited on through it rather than through the loading row.
MY_REQUESTS_ENDPOINT = "/pending-changes/my-requests"

# ── sidebar entries (SideNavigation/nav-config.tsx, "Change Request Module") ─
# Anchored so "Change Request" cannot also match the section heading "Change
# Request Module" that sits directly above it.
NAV_CHANGE_REQUEST = re.compile(r"^\s*Change Request\s*$", re.I)
# The approver's queue. Gated on `manage change_requests` in SideNavigation.tsx
# (`isChangeRequestManage`), so a read-only role must never be offered it.
NAV_PENDING_REQUESTS = re.compile(r"^\s*Pending Requests\s*$", re.I)

# ── page chrome (page.tsx) ───────────────────────────────────────────────────
HEADING = re.compile(r"^\s*My Change Requests\s*$", re.I)
SUBHEADING = re.compile(r"View and track your requested changes", re.I)

TABLE_HEADERS = (
    "ID", "Module", "Model", "Action", "Record ID", "Status", "Date Created",
    # The last column is headed "Action" too — the per-row buttons.
    "Action",
)

LOADING_ROW = re.compile(r"Loading requests", re.I)
LOAD_FAILURE = re.compile(r"^\s*Failed to load change requests\s*$", re.I)
EMPTY_TITLE = re.compile(r"^\s*No results found\s*$", re.I)
EMPTY_BODY = re.compile(r"You haven't made any .*change requests yet", re.I)

# ── the status filter (a Radix Select) ───────────────────────────────────────
STATUS_ALL = "All Requests"
STATUS_PENDING = "Pending"
STATUS_APPROVED = "Approved"
STATUS_REJECTED = "Rejected"

# ── the detail modal ─────────────────────────────────────────────────────────
DETAIL_HEADING = re.compile(r"^\s*Request Details\s*$", re.I)
CHANGE_SUMMARY_HEADING = re.compile(r"^\s*Change Summary\s*$", re.I)
OLD_VALUES_HEADING = re.compile(r"Old Values \(Before\)", re.I)
NEW_VALUES_HEADING = re.compile(r"New Values \(Requested\)", re.I)
NO_VALUES = re.compile(r"^\s*No values provided\s*$", re.I)
APPROVAL_HEADING = re.compile(r"^\s*Approval Information\s*$", re.I)
REVIEWER_REMARKS_LABEL = re.compile(r"^\s*Reviewer Remarks\s*$", re.I)
CLOSE_BUTTON = re.compile(r"^\s*Close\s*$", re.I)

# Anything that would let this screen raise a *new* request. The bin on a pending
# row is deliberately not in here — withdrawing your own request is the one write
# the page owns (see the module docstring).
AUTHORING_CONTROL = re.compile(r"^\s*(?:add|create|new|submit|request)\b", re.I)


class ChangeRequestsPage(BasePage):
    """The signed-in user's own change-request log."""

    URL = "/module/change_request"

    def __init__(self, page, frontend_base_url: str):
        super().__init__(page, frontend_base_url)
        # The Select opens on "All Requests"; the trigger renders whatever is
        # currently chosen, which is what filter_by_status() anchors on.
        self._status_filter = STATUS_ALL

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "ChangeRequestsPage":
        super().open()
        return self

    def open_from_sidebar(self) -> "ChangeRequestsPage":
        """Reach the screen the way a real user does — via the sidebar.

        Falls back to the route itself when the sidebar is collapsed (it is on
        narrow viewports); how the user got here is worth showing, but it is not
        what this page object asserts.
        """
        link = self.page.get_by_role("link", name=as_pattern(NAV_CHANGE_REQUEST)).first
        if link.count():
            link.click()
        else:
            self.open()
        self.page.wait_for_url(LIST_URL, timeout=25_000)
        return self

    def expect_nav_entry(self) -> None:
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_CHANGE_REQUEST)).first
        ).to_be_visible(timeout=25_000)

    def expect_approver_queue_absent(self) -> None:
        """"Pending Requests" is the approver's queue and must not be offered.

        ``SideNavigation.canShowItem`` drops it for anyone whose role holds only
        ``read change_requests``, which is what separates a requester from an
        approver in this module.
        """
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_PENDING_REQUESTS))
        ).to_have_count(0)

    # ───────────────────────── readers ───────────────────────────

    def wait_for_table(self, timeout_ms: int = 30_000) -> "ChangeRequestsPage":
        """Wait out the in-table loading row.

        The header row is rendered before the fetch resolves, so it is not enough
        on its own — the "Loading requests..." body row going away is what says
        the response has landed. Both an empty log and a populated one clear it.
        """
        expect(self.page.locator("table thead tr").first).to_be_visible(
            timeout=timeout_ms
        )
        expect(self.page.get_by_text(as_pattern(LOADING_ROW))).to_have_count(
            0, timeout=timeout_ms
        )
        return self

    def expect_loaded(self) -> None:
        expect(
            self.page.get_by_role("heading", name=as_pattern(HEADING))
        ).to_be_visible(timeout=25_000)
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

    def row(self, request_id: int) -> Locator:
        """The row for one request, matched on the "#<id>" its first cell shows.

        Anchored on a *cell* rather than on the row's own text: the row's text is
        every column run together ("#12incomes_and_expensesIncome…"), so an id
        prefix cannot be bounded there — "#1" would match "#12" as happily.
        """
        return self.rows().filter(
            has=self.page.locator("td").filter(
                has_text=as_pattern(rf"^\s*#{request_id}\s*$")
            )
        ).first

    def expect_request(
        self,
        request_id: int,
        *,
        module: str | None = None,
        model: str | None = None,
        action: str | None = None,
        status: str | None = None,
    ) -> None:
        """The row is listed, and carries what the server stored against it."""
        row = self.row(request_id)
        expect(row).to_be_visible(timeout=25_000)
        for value in (module, model, action, status):
            if value:
                expect(row).to_contain_text(as_pattern(re.escape(value)))

    def expect_request_absent(self, request_id: int) -> None:
        expect(self.row(request_id)).to_have_count(0)

    def expect_withdraw_offered(self, request_id: int, *, offered: bool = True) -> None:
        """A pending request may be withdrawn; a decided one may not.

        The bin is an icon-only button with no accessible name, so it is counted
        positionally: the last cell holds the view button always, and the bin only
        while ``status === "pending"``.
        """
        buttons = self.row(request_id).locator("td").last.get_by_role("button")
        expect(buttons).to_have_count(2 if offered else 1)

    # ───────────────────────── filtering ─────────────────────────

    def filter_by_status(self, label: str) -> "ChangeRequestsPage":
        """Pick a status from the Radix Select, refetching the list.

        The refetch is waited for explicitly rather than inferred from the
        in-table loading row. Choosing a status re-runs ``fetchMyRequests``, and
        between the click and that row appearing the *previous* result set is
        still on screen — an assertion made in that gap would be answered by the
        list the filter was supposed to replace.
        """
        with self.page.expect_response(
            lambda response: MY_REQUESTS_ENDPOINT in response.url,
            timeout=30_000,
        ):
            self.select_option_in_combobox(
                rf"^\s*{re.escape(self._status_filter)}\s*$",
                rf"^\s*{re.escape(label)}\s*$",
            )
        self._status_filter = label
        self.wait_for_table()
        return self

    def expect_status_filter(self, label: str) -> None:
        expect(
            self.page.get_by_role("combobox").filter(
                has_text=as_pattern(rf"^\s*{re.escape(label)}\s*$")
            ).first
        ).to_be_visible()

    def expect_empty_state(self) -> None:
        expect(self.page.get_by_text(as_pattern(EMPTY_TITLE)).first).to_be_visible(
            timeout=25_000
        )
        expect(self.page.get_by_text(as_pattern(EMPTY_BODY)).first).to_be_visible()

    # ─────────────────────── the detail modal ────────────────────

    def open_details(self, request_id: int) -> "ChangeRequestsPage":
        """Click the row's eye button — the first control in its last cell."""
        self.row(request_id).locator("td").last.get_by_role("button").first.click()
        expect(
            self.page.get_by_role("heading", name=as_pattern(DETAIL_HEADING))
        ).to_be_visible(timeout=15_000)
        return self

    def expect_details(
        self,
        request_id: int,
        *,
        module: str | None = None,
        change_summary: str | None = None,
        new_value_text: str | None = None,
        old_values_empty: bool = False,
    ) -> None:
        """Assert the open modal's contents.

        Scoped at page level rather than to a container: this overlay is not a
        ``role="dialog"``, and every string asserted here is rendered nowhere else
        on the route — the table shows neither the change summary nor either value
        set, and its own "#12" cell cannot match the modal's "ID: #12" subtitle.

        Deliberately *not* asserted here: the module, model and status the modal
        repeats from the row underneath it. The table is still mounted and visible
        behind the overlay, so a page-level match on those would pass whether the
        modal rendered them or not — the module is checked instead as part of the
        subtitle line that carries the id, which is unique to the modal.
        """
        subtitle = self.page.get_by_text(
            as_pattern(rf"ID:\s*#{request_id}(?!\d)")
        ).first
        expect(subtitle).to_be_visible(timeout=15_000)
        if module:
            expect(subtitle).to_contain_text(as_pattern(re.escape(module)))
        if change_summary:
            expect(
                self.page.get_by_text(as_pattern(CHANGE_SUMMARY_HEADING)).first
            ).to_be_visible()
            expect(
                self.page.get_by_text(as_pattern(re.escape(change_summary))).first
            ).to_be_visible()
        expect(
            self.page.get_by_text(as_pattern(NEW_VALUES_HEADING)).first
        ).to_be_visible()
        if new_value_text:
            expect(
                self.page.get_by_text(as_pattern(re.escape(new_value_text))).first
            ).to_be_visible()
        expect(
            self.page.get_by_text(as_pattern(OLD_VALUES_HEADING)).first
        ).to_be_visible()
        if old_values_empty:
            # A "create" request has nothing to show a before-picture of.
            expect(self.page.get_by_text(as_pattern(NO_VALUES)).first).to_be_visible()

    def expect_review_outcome(self, remarks: str) -> None:
        """The reviewer's verdict, which only a decided request carries."""
        expect(
            self.page.get_by_text(as_pattern(APPROVAL_HEADING)).first
        ).to_be_visible(timeout=15_000)
        expect(
            self.page.get_by_text(as_pattern(REVIEWER_REMARKS_LABEL)).first
        ).to_be_visible()
        expect(
            self.page.get_by_text(as_pattern(re.escape(remarks))).first
        ).to_be_visible()

    def close_details(self) -> "ChangeRequestsPage":
        self.page.get_by_role("button", name=as_pattern(CLOSE_BUTTON)).last.click()
        expect(
            self.page.get_by_role("heading", name=as_pattern(DETAIL_HEADING))
        ).to_have_count(0)
        return self

    # ───────────────────────── read-only ─────────────────────────

    def expect_no_authoring_controls(self) -> None:
        """Nothing here raises a new request — that happens in the owning module."""
        expect(
            self.page.get_by_role("button", name=as_pattern(AUTHORING_CONTROL))
        ).to_have_count(0)
