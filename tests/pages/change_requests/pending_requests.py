"""Change Requests → "Pending Requests", the approver's queue.

/module/pending_requests (there is no ``/module/change_requests`` route;
``src/middleware.ts`` maps this segment and ``/module/change_request`` onto the
same ``change_requests`` module key). The screen has two tabs:

* **All Pending Requests** — ``GET /pending-changes/`` scoped to the approver's
  branch, one row per request still awaiting a decision, each with a row menu
  offering Approve and Reject;
* **My Requests** — the same ``GET /pending-changes/my-requests`` register that
  ``tests/pages/change_requests/change_request.py`` models, for requests the
  approver filed themselves.

Only this page can *decide* anything. ``SideNavigation.canShowItem`` hides its
sidebar entry from anyone holding merely ``read change_requests``, and every
route behind it is gated on ``has_permission("manage", "change_requests")``.

Branch selection is a precondition, not a nicety
    ``GetPendingChangesHandler`` appends ``branch_id`` from ``useBranchStore``
    whenever the signed-in user is a SchoolAdmin, and the backend's
    ``branch_id_required`` refuses a SchoolAdmin request that carries none. So
    without ``BranchesPage.select_branch`` first there is no sidebar entry to
    click (the whole "Change Request Module" group is ``branchOnly``) and the
    queue would answer 400 rather than listing anything.

Locating things on it
    Rows are a real ``<table>``, so :meth:`row` filters ``tbody tr`` on the
    "#12" its first cell renders — an id that came back from the create call, so
    a row matched this way is provably the request the test seeded.

    The row menu's trigger is an icon-only Radix button with no accessible name;
    it is the only button in the row's last cell, which is how :meth:`_open_menu`
    finds it. Its items are real ``role="menuitem"`` nodes.

    Approve and Reject each open an **antd** ``Modal`` — not a Radix dialog, and
    not react-hot-toast underneath either: both handlers report through antd's
    ``message``. antd leaves a modal it has opened once mounted-but-hidden, so
    every lookup here is scoped to ``.ant-modal:visible`` rather than to
    ``get_by_role("dialog")``, which would match the closed one just as happily.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── the route ────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/pending_requests(?:$|[?#])")

# ── sidebar entry (SideNavigation/nav-config.tsx, "Change Request Module") ────
NAV_PENDING_REQUESTS = re.compile(r"^\s*Pending Requests\s*$", re.I)

# ── page chrome (pending_requests/page.tsx) ──────────────────────────────────
HEADING = re.compile(r"^\s*Pending Requests\s*$", re.I)
SUBHEADING = re.compile(r"Review and manage pending change requests", re.I)

ALL_PENDING_TAB = re.compile(r"^\s*All Pending Requests\s*$", re.I)
MY_REQUESTS_TAB = re.compile(r"^\s*My Requests\s*$", re.I)

# The queue's columns, in order. Its last column is headed "Actions"; the
# My Requests tab's equivalent is headed "Action" — they are different tables.
TABLE_HEADERS = (
    "ID", "Module", "Model", "Action", "Record ID", "Date Created", "Actions",
)

LOADING_ROW = re.compile(r"Loading requests", re.I)
LOAD_FAILURE = re.compile(r"^\s*Failed to load pending requests\s*$", re.I)
EMPTY_TITLE = re.compile(r"No pending requests found", re.I)

# ── the row menu ─────────────────────────────────────────────────────────────
APPROVE_ITEM = re.compile(r"^\s*Approve\s*$", re.I)
REJECT_ITEM = re.compile(r"^\s*Reject\s*$", re.I)

# ── the decision modals (antd Modal + antd message) ──────────────────────────
APPROVE_MODAL_TITLE = "Approve Request #{id}"
REJECT_MODAL_TITLE = "Reject Request #{id}"
REMARKS_PLACEHOLDER = re.compile(r"^\s*Enter remarks", re.I)
APPROVE_SUBMIT = re.compile(r"^\s*Proceed Approval\s*$", re.I)
REJECT_SUBMIT = re.compile(r"^\s*Proceed Rejection\s*$", re.I)
DISCARD_BUTTON = re.compile(r"^\s*Discard\s*$", re.I)

APPROVED_MESSAGE = re.compile(r"Request approved successfully", re.I)
REJECTED_MESSAGE = re.compile(r"Request rejected successfully", re.I)


class PendingRequestsPage(BasePage):
    """The approver's queue of change requests awaiting a decision."""

    URL = "/module/pending_requests"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "PendingRequestsPage":
        super().open()
        return self

    def open_from_sidebar(self) -> "PendingRequestsPage":
        """Reach the queue the way a real user does — via the sidebar.

        Falls back to the route itself when the sidebar is collapsed (it is on
        narrow viewports); how the user got here is worth showing, but it is not
        what this page object asserts.
        """
        link = self.page.get_by_role(
            "link", name=as_pattern(NAV_PENDING_REQUESTS)
        ).first
        if link.count():
            link.click()
        else:
            self.open()
        self.page.wait_for_url(LIST_URL, timeout=25_000)
        return self

    def expect_nav_entry(self) -> None:
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_PENDING_REQUESTS)).first
        ).to_be_visible(timeout=25_000)

    # ───────────────────────── readers ───────────────────────────

    def expect_loaded(self) -> None:
        expect(
            self.page.get_by_role("heading", name=as_pattern(HEADING))
        ).to_be_visible(timeout=25_000)
        expect(self.page.get_by_text(as_pattern(SUBHEADING)).first).to_be_visible()

    def expect_tabs(self) -> None:
        expect(
            self.page.get_by_role("button", name=as_pattern(ALL_PENDING_TAB))
        ).to_be_visible()
        expect(
            self.page.get_by_role("button", name=as_pattern(MY_REQUESTS_TAB))
        ).to_be_visible()

    def open_all_pending_tab(self) -> "PendingRequestsPage":
        self.page.get_by_role("button", name=as_pattern(ALL_PENDING_TAB)).first.click()
        return self.wait_for_table()

    def open_my_requests_tab(self) -> "PendingRequestsPage":
        self.page.get_by_role("button", name=as_pattern(MY_REQUESTS_TAB)).first.click()
        return self.wait_for_table()

    def wait_for_table(self, timeout_ms: int = 30_000) -> "PendingRequestsPage":
        """Wait out the in-table loading row.

        The header row renders before the fetch resolves, so it is not enough on
        its own — the "Loading requests..." body row going away is what says the
        response has landed. Both an empty queue and a populated one clear it.
        """
        expect(self.page.locator("table thead tr").first).to_be_visible(
            timeout=timeout_ms
        )
        expect(self.page.get_by_text(as_pattern(LOADING_ROW))).to_have_count(
            0, timeout=timeout_ms
        )
        return self

    def expect_no_load_failure(self) -> None:
        """The queue's fetch did not fall into ``PageError``.

        A SchoolAdmin who never picked a branch lands here: the list call goes
        out without ``branch_id`` and the backend answers 400.
        """
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
        """The row for one request, matched on the "#<id>" its first cell shows."""
        return self.rows().filter(
            has=self.page.get_by_role(
                "cell", name=as_pattern(rf"^\s*#{request_id}\s*$")
            )
        ).first

    def expect_request(
        self,
        request_id: int,
        *,
        module: str | None = None,
        model: str | None = None,
        action: str | None = None,
    ) -> None:
        """The request is queued, and carries what the server stored against it."""
        row = self.row(request_id)
        expect(row).to_be_visible(timeout=25_000)
        for value in (module, model, action):
            if value:
                expect(row).to_contain_text(as_pattern(re.escape(value)))

    def expect_request_absent(self, request_id: int, timeout_ms: int = 25_000) -> None:
        """A decided request drops out of the queue on the next fetch."""
        expect(self.row(request_id)).to_have_count(0, timeout=timeout_ms)

    def expect_empty_state(self) -> None:
        expect(self.page.get_by_text(as_pattern(EMPTY_TITLE)).first).to_be_visible(
            timeout=25_000
        )

    # ───────────────────── deciding a request ────────────────────

    def approve(self, request_id: int, remarks: str) -> "PendingRequestsPage":
        """Approve through the row menu, which also *applies* the change.

        ``approve_change`` runs the request's payload through the owning module's
        own service, so a successful approval writes the real record — the point
        of the workflow, and the reason the caller must seed a request whose
        payload is actually applicable.
        """
        self._decide(
            request_id,
            item=APPROVE_ITEM,
            title=APPROVE_MODAL_TITLE.format(id=request_id),
            submit=APPROVE_SUBMIT,
            remarks=remarks,
        )
        self.expect_message(APPROVED_MESSAGE)
        return self

    def reject(self, request_id: int, remarks: str) -> "PendingRequestsPage":
        """Reject through the row menu. The reason is mandatory server-side —
        ``reject_change`` declares ``remarks`` with ``min_length=10``."""
        self._decide(
            request_id,
            item=REJECT_ITEM,
            title=REJECT_MODAL_TITLE.format(id=request_id),
            submit=REJECT_SUBMIT,
            remarks=remarks,
        )
        self.expect_message(REJECTED_MESSAGE)
        return self

    def expect_message(self, pattern: re.Pattern[str], timeout_ms: int = 20_000) -> None:
        """Assert an antd ``message`` banner.

        Not :meth:`BasePage.expect_toast`: these two handlers report through
        antd's ``message`` rather than react-hot-toast, and its notice nests the
        text a few elements deep — hence ``.first``.
        """
        expect(self.page.get_by_text(as_pattern(pattern)).first).to_be_visible(
            timeout=timeout_ms
        )

    # ───────────────────────── internals ─────────────────────────

    def _decide(
        self,
        request_id: int,
        *,
        item: re.Pattern[str],
        title: str,
        submit: re.Pattern[str],
        remarks: str,
    ) -> None:
        self._open_menu(request_id)
        self.page.get_by_role("menuitem", name=as_pattern(item)).first.click()

        modal = self.modal()
        expect(modal.locator(".ant-modal-title")).to_have_text(
            as_pattern(rf"^\s*{re.escape(title)}\s*$"), timeout=15_000
        )
        modal.get_by_placeholder(as_pattern(REMARKS_PLACEHOLDER)).first.fill(remarks)
        modal.get_by_role("button", name=as_pattern(submit)).first.click()

    def _open_menu(self, request_id: int) -> None:
        """Open a row's action menu — the only button in its last cell."""
        row = self.row(request_id)
        expect(row).to_be_visible(timeout=25_000)
        row.locator("td").last.get_by_role("button").first.click()

    def modal(self) -> Locator:
        """The antd modal that is actually open.

        antd keeps a modal mounted after it closes, so a page-wide
        ``get_by_role("dialog")`` would resolve to a hidden one as readily as to
        the live one.
        """
        return self.page.locator(".ant-modal:visible").last
