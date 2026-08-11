"""Library → Returns & Renewals, as the borrower sees it.

``/module/requests_and_renewals`` renders one of two workspaces off the
signed-in role (``src/app/module/requests_and_renewals/page.tsx``). A
SchoolAdmin — or an Admin/librarian holding a ``requests_and_renewals``
permission — gets ``views/AdminView.tsx``, the circulation desk with its three
tabs, its "Scan and Assign" scanner and a row menu that approves, rejects and
processes returns. *Everyone else*, a pupil included, gets
``views/StudentView.tsx``: their own borrowing record, one row per request they
have made.

This page object models that second view. It exposes readers, the two filters
its toolbar offers, and :meth:`expect_librarian_controls_absent` — and no verb
that changes a request's state, because the borrower's view offers none. Its two
row buttons, "Renew" and "Return", only *open* a dialog; sending either one is
the borrower's own write flow and belongs to the unit that covers it.

The librarian's face of the same route is a separate page object,
``tests/pages/library/requests_and_renewals_admin.py`` — the same split the
catalogue already makes between ``catalogue.py`` (the reader's shelf) and
``manage_books.py`` (the register). The two views share a heading and a search
placeholder and nothing else, so one class modelling both would have to branch on
the role in every method.

What the table is
    A plain ``<table>``: a header row of Book Thumbnail / Book Title / Book Copy
    / Category / Request Date / Expected Return Date / Book Days Remaining /
    Request Type / Book Returned Condition / Returned / Status plus one
    unlabelled actions column, then one row per request from
    ``GET /book-requests/student/{user_id}`` (10 per page). With nothing to show
    the table is replaced outright by an ``EmptyState`` reading "No book requests
    found" — so a header row is proof the fetch resolved *and* returned rows.

    The header cells carry no ``scope``, so — exactly as on the catalogue — they
    resolve to plain ``cell`` rather than ``columnheader``, and
    :meth:`expect_column_headers` reads them positionally off
    ``table thead tr th`` instead of by role. They are also rendered
    ``uppercase`` by CSS only; the DOM text is still title case, which is what
    the assertions match.

Both filters are client-side
    Unlike the catalogue's, neither filter re-requests anything: ``StudentView``
    holds the whole response in state and narrows it in ``filteredRequests``. The
    category list is *derived* from the requests on hand, so a genre only appears
    in that dropdown once the pupil has asked for a book filed under it.

    The search box is the one control whose behaviour is worth stating: it
    matches ``request.copy?.name`` and the request id — **not** the book title.
    A pending request has no copy assigned, so it can only ever be found by id.

Whose requests they are
    Their own, and they get no say in it: the view asks for
    ``/book-requests/student/{authUserProfile.id}``, and for a non-admin the
    route overwrites ``branch_id`` with ``user.school_branch_id`` before it
    queries (``api/routes/book_request.py``). So every row could only have come
    from this pupil's own borrowing record on their own campus.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── the route ────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/requests_and_renewals(?:$|[?#])")

# ── the sidebar (SideNavigation/nav-config.tsx, "Library Module" section) ────
# The section is ``branchOnly``, but ``canShowSection`` treats branch state as a
# SchoolAdmin-only concept, so a pupil holding ("manage", "requests_and_renewals")
# sees it as long as the pack licenses the module.
NAV_LIBRARY_SECTION = re.compile(r"^\s*Library Module\s*$", re.I)
NAV_RETURNS_AND_RENEWALS = re.compile(r"^\s*Returns & Renewals\s*$", re.I)

# ── the borrower's workspace (views/StudentView.tsx) ─────────────────────────
# Both faces of this route are headed "Manage Requests", so the subheading is
# what tells them apart: the librarian's says "…initiated by students…".
BORROWER_HEADING = re.compile(r"^\s*Manage Requests\s*$", re.I)
BORROWER_SUBHEADING = re.compile(
    r"^\s*All book requests initiated will appear here\s*$", re.I
)
LIBRARIAN_SUBHEADING = re.compile(
    r"All book requests initiated by students will appear here", re.I
)

# ── the toolbar ──────────────────────────────────────────────────────────────
SEARCH_PLACEHOLDER = re.compile(r"Search book by id or name", re.I)
ALL_CATEGORIES = "All Category"
ALL_STATUSES = "All Status"
# The toolbar's two Radix selects, in DOM order.
CATEGORY_FILTER = 0
STATUS_FILTER = 1

# ── the table ────────────────────────────────────────────────────────────────
TABLE_HEADING = re.compile(r"^\s*All Books\s*$", re.I)
COLUMN_HEADERS = (
    "Book Thumbnail",
    "Book Title",
    "Book Copy",
    "Category",
    "Request Date",
    "Expected Return Date",
    "Book Days Remaining",
    "Request Type",
    "Book Returned Condition",
    "Returned",
    "Status",
)
# …plus one deliberately empty header over the actions column.
COLUMN_COUNT = len(COLUMN_HEADERS) + 1

NO_COPY_ASSIGNED = re.compile(r"^\s*Copy not assigned\s*$", re.I)
NOT_RETURNED = re.compile(r"^\s*Book Not Returned\s*$", re.I)
UNSPECIFIED_RETURN_DATE = re.compile(r"^\s*Not specified\s*$", re.I)
DAYS_LEFT = re.compile(r"^\s*\d+\s+days?\s+left\s*$", re.I)
OVERDUE = re.compile(r"Overdue by", re.I)
EMPTY_STATE = re.compile(r"^\s*No book requests found\s*$", re.I)

# ── the two row controls the borrower's view does draw ───────────────────────
RENEW_BUTTON = re.compile(r"^\s*Renew\s*$", re.I)
RETURN_BUTTON = re.compile(r"^\s*Return\s*$", re.I)

# ── the librarian's circulation desk, which must never reach a borrower ──────
# views/AdminView.tsx. The tab labels carry their row count in the accessible
# name ("Book Requests 3"), so these are deliberately unanchored — an anchored
# pattern would report "absent" for a tab that was on screen. "Book Returns /
# Renewals" carries a slash and must go through as_pattern().
LIBRARIAN_TABS = (
    re.compile(r"Book Requests", re.I),
    re.compile(r"Book Returns\s*/\s*Renewals", re.I),
    re.compile(r"Overdue Books", re.I),
)
LIBRARIAN_CONTROLS = (
    re.compile(r"Scan and Assign", re.I),
    re.compile(r"Send Bulk Overdue Reminder", re.I),
)
LIBRARIAN_REQUEST_TYPE_FILTER = re.compile(r"All Request Types", re.I)
# The row menu's verbs on the librarian's side. Anchored at the start of the
# accessible name so the borrower's own "Renew"/"Return"/"Previous"/"Next" are
# not swept up.
WRITE_CONTROL = re.compile(
    r"^\s*(?:approve|reject|process|delete|remove|assign|scan|edit|update)\b", re.I
)

# ── failure surface (handleErrorMessage's fallback) ──────────────────────────
REQUEST_FAILURE = re.compile(r"Failed to process request", re.I)


class StudentRequestsAndRenewalsPage(BasePage):
    """The borrower's own book requests at /module/requests_and_renewals."""

    URL = "/module/requests_and_renewals"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "StudentRequestsAndRenewalsPage":
        super().open()
        return self

    def open_from_sidebar(self) -> "StudentRequestsAndRenewalsPage":
        """Reach the screen the way a real borrower does — via Library Module.

        Falls back to the route itself when the sidebar is collapsed (it is on
        narrow viewports); how the user got here is worth showing, but it is not
        what this page object asserts.
        """
        link = self.page.get_by_role(
            "link", name=as_pattern(NAV_RETURNS_AND_RENEWALS)
        ).first
        if link.count():
            link.click()
        else:
            self.open()
        self.page.wait_for_url(LIST_URL, timeout=25_000)
        return self

    def expect_nav_entry(self) -> None:
        """The Library section is on offer, and Returns & Renewals inside it."""
        expect(
            self.page.get_by_text(as_pattern(NAV_LIBRARY_SECTION)).first
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_role(
                "link", name=as_pattern(NAV_RETURNS_AND_RENEWALS)
            ).first
        ).to_be_visible(timeout=25_000)

    # ───────────────────────── readers ───────────────────────────

    def wait_for_table(self, timeout_ms: int = 40_000) -> "StudentRequestsAndRenewalsPage":
        """Wait out ``StudentRequestAndRenewalLoader``.

        The empty state is checked first so a borrower whose requests were never
        seeded fails with "the list is empty" rather than with a bare selector
        timeout on a header row that this view never draws for an empty list.
        """
        expect(self.page.get_by_text(as_pattern(EMPTY_STATE))).to_have_count(
            0, timeout=timeout_ms
        )
        expect(self.page.locator("table thead tr").first).to_be_visible(
            timeout=timeout_ms
        )
        return self

    def expect_borrower_view(self) -> None:
        """This is the borrower's own record, not the librarian's desk."""
        expect(
            self.page.get_by_role("heading", name=as_pattern(BORROWER_HEADING))
        ).to_be_visible(timeout=25_000)
        expect(self.page.get_by_text(BORROWER_SUBHEADING)).to_be_visible()
        expect(self.page.get_by_text(LIBRARIAN_SUBHEADING)).to_have_count(0)

    def expect_column_headers(self) -> None:
        """Assert the header row by position, pinning the column order."""
        cells = self.page.locator("table thead tr").first.locator("th")
        expect(cells).to_have_count(COLUMN_COUNT)
        for index, header in enumerate(COLUMN_HEADERS):
            expect(cells.nth(index)).to_have_text(
                as_pattern(rf"^\s*{re.escape(header)}\s*$")
            )

    def expect_toolbar(self) -> None:
        """The search box and the two filters, and nothing else selectable.

        The count is asserted because both filters are addressed by position:
        the category select has no label and its trigger reads whatever value is
        in force, so index is the only stable handle on it.
        """
        expect(
            self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))
        ).to_be_visible(timeout=25_000)
        expect(self.page.get_by_role("combobox")).to_have_count(2)
        self.expect_filter(CATEGORY_FILTER, ALL_CATEGORIES)
        self.expect_filter(STATUS_FILTER, ALL_STATUSES)

    def expect_total(self, count: int, timeout_ms: int = 25_000) -> None:
        """The badge beside the "All Books" heading.

        It is rendered from the length of the whole fetched response, not of the
        filtered rows — so it states how many requests this borrower has ever
        made, whatever filter is in force.
        """
        expect(
            self.page.get_by_role("heading", name=as_pattern(TABLE_HEADING)).first
        ).to_be_visible(timeout=timeout_ms)
        noun = "book" if count <= 1 else "books"
        expect(
            self.page.get_by_text(as_pattern(rf"^\s*{count}\s+{noun}\s*$")).first
        ).to_be_visible(timeout=timeout_ms)

    def rows(self) -> Locator:
        return self.page.locator("table tbody tr")

    def row(self, title: str) -> Locator:
        """The row for one request, matched on its book-title cell."""
        return self.rows().filter(has_text=as_pattern(re.escape(title))).first

    def expect_request(
        self,
        title: str,
        *,
        copy: str | re.Pattern | None = None,
        category: str | None = None,
        request_type: str | None = None,
        status: str | None = None,
        returned: str | None = None,
        condition: str | re.Pattern | None = None,
        expected_return: str | re.Pattern | None = None,
        days_remaining: re.Pattern | None = None,
    ) -> None:
        """One row, and the server-side values it carries, cell by cell.

        Every optional field here is something only the backend could supply —
        the physical copy the librarian handed over, the genre the book was filed
        under, the status the request was moved into, the return date recorded on
        approval — so matching them proves the table really rendered this
        borrower's ``GET /book-requests/student/{id}`` answer.

        Asserted per *cell* rather than against the row's whole text, which both
        pins :data:`COLUMN_HEADERS`' order and keeps a status from being
        satisfied by the same word appearing in a neighbouring column.
        """
        row = self.row(title)
        expect(row).to_be_visible(timeout=25_000)
        expect(self._cell(row, "Book Title")).to_have_text(
            as_pattern(rf"^\s*{re.escape(title)}\s*$")
        )
        # The request date renders as a relative phrase ("2 minutes ago") that is
        # re-derived in the browser's own timezone, so only its presence is worth
        # asserting — an empty cell would mean date_created never arrived.
        expect(self._cell(row, "Request Date")).to_have_text(re.compile(r"\S"))
        if copy is not None:
            expect(self._cell(row, "Book Copy")).to_have_text(as_pattern(copy))
        if category is not None:
            expect(self._cell(row, "Category")).to_have_text(
                as_pattern(rf"^\s*{re.escape(category)}\s*$")
            )
        if request_type is not None:
            expect(self._cell(row, "Request Type")).to_have_text(
                as_pattern(rf"^\s*{re.escape(request_type)}\s*$")
            )
        if status is not None:
            expect(self._cell(row, "Status")).to_have_text(
                as_pattern(rf"^\s*{re.escape(status)}\s*$")
            )
        if returned is not None:
            expect(self._cell(row, "Returned")).to_have_text(
                as_pattern(rf"^\s*{re.escape(returned)}\s*$")
            )
        if condition is not None:
            expect(self._cell(row, "Book Returned Condition")).to_have_text(
                as_pattern(condition)
            )
        if expected_return is not None:
            expect(self._cell(row, "Expected Return Date")).to_have_text(
                as_pattern(expected_return)
            )
        if days_remaining is not None:
            expect(self._cell(row, "Book Days Remaining")).to_have_text(
                as_pattern(days_remaining)
            )

    @staticmethod
    def _cell(row: Locator, column: str) -> Locator:
        return row.locator("td").nth(COLUMN_HEADERS.index(column))

    def expect_request_absent(self, title: str, timeout_ms: int = 25_000) -> None:
        expect(
            self.rows().filter(has_text=as_pattern(re.escape(title)))
        ).to_have_count(0, timeout=timeout_ms)

    def expect_borrowing_controls_enabled(self, title: str) -> None:
        """An approved, unreturned loan may be renewed or handed back."""
        row = self.row(title)
        expect(
            row.get_by_role("button", name=as_pattern(RENEW_BUTTON))
        ).to_be_enabled(timeout=25_000)
        expect(
            row.get_by_role("button", name=as_pattern(RETURN_BUTTON))
        ).to_be_enabled()

    def expect_borrowing_controls_disabled(self, title: str) -> None:
        """A request the librarian has not approved offers neither.

        Both buttons are drawn either way — ``StudentView`` disables rather than
        hides them — so this asserts the disabled state, not their absence.
        """
        row = self.row(title)
        expect(
            row.get_by_role("button", name=as_pattern(RENEW_BUTTON))
        ).to_be_disabled(timeout=25_000)
        expect(
            row.get_by_role("button", name=as_pattern(RETURN_BUTTON))
        ).to_be_disabled()

    def expect_librarian_controls_absent(self) -> None:
        """Nothing here lets a borrower act as the circulation desk.

        The named controls are the librarian workspace's own chrome — its three
        tabs, its scanner, its bulk reminder and its request-type filter — and
        the generic sweep is scoped to the table, which is where that workspace
        keeps its per-row approve / reject / process / delete menu. Page-wide the
        sweep would also be reading the app chrome, which is not this screen's to
        answer for.
        """
        for tab in LIBRARIAN_TABS:
            expect(
                self.page.get_by_role("button", name=as_pattern(tab))
            ).to_have_count(0)
        for control in LIBRARIAN_CONTROLS:
            expect(
                self.page.get_by_role("button", name=as_pattern(control))
            ).to_have_count(0)
        expect(
            self.page.get_by_text(as_pattern(LIBRARIAN_REQUEST_TYPE_FILTER))
        ).to_have_count(0)
        expect(
            self.page.locator("table").get_by_role(
                "button", name=as_pattern(WRITE_CONTROL)
            )
        ).to_have_count(0)

    def expect_no_failure_toast(self) -> None:
        """The one error surface this view raises, asserted absent.

        ``fetchBookRequest`` swallows its own failure into ``console.error``, so
        a broken read shows up as an empty list rather than as a message — which
        is why :meth:`wait_for_table` checks the empty state and this only has to
        cover the write path's toast.
        """
        expect(self.page.get_by_text(as_pattern(REQUEST_FAILURE))).to_have_count(0)

    # ───────────────────────── filters ───────────────────────────

    def filter_by_category(self, category: str) -> None:
        self._select(CATEGORY_FILTER, category)

    def filter_by_status(self, status: str) -> None:
        self._select(STATUS_FILTER, status)

    def clear_category_filter(self) -> None:
        self._select(CATEGORY_FILTER, ALL_CATEGORIES)

    def clear_status_filter(self) -> None:
        self._select(STATUS_FILTER, ALL_STATUSES)

    def expect_filter(self, index: int, value: str) -> None:
        expect(self.page.get_by_role("combobox").nth(index)).to_have_text(
            as_pattern(rf"^\s*{re.escape(value)}\s*$"), timeout=25_000
        )

    def _select(self, index: int, option: str) -> None:
        """Pick from one of the toolbar's two Radix selects.

        Addressed by position rather than by trigger text: the trigger reads
        whichever value is in force, so anchoring on "All Status" would only ever
        work for the first selection made.
        """
        self.page.get_by_role("combobox").nth(index).click()
        self.page.get_by_role(
            "option", name=as_pattern(rf"^\s*{re.escape(option)}\s*$")
        ).first.click()
        self.expect_filter(index, option)
