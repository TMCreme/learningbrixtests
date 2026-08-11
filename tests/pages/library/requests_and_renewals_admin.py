"""Library → Returns & Renewals, as the person who runs the library sees it.

``/module/requests_and_renewals`` renders one of two workspaces off the signed-in
role (``src/app/module/requests_and_renewals/page.tsx``). ``shouldShowAdminView()``
returns true for a role name containing "schooladmin", for "admin" holding a
``requests_and_renewals`` manage permission, and for anything reading
"library"/"librarian" — so a SchoolAdmin gets ``views/AdminView.tsx``, the
"Manage Requests" circulation desk. Everyone else, a pupil included, gets
``views/StudentView.tsx``: their own borrowing record, with "Renew" and "Return"
and nothing to decide. That second view has its own page object, in
``tests/pages/library/requests_and_renewals.py``; this module is the desk, and
the two are deliberately kept in separate files because they share a route and
almost no markup.

What the desk is
    Three queues behind three tabs of one table:

    ``Book Requests``
        ``GET /book-requests/`` — every request a reader has raised for a title.
        A pending row's "…" menu offers **Approve** (a dialog asking which
        physical copy to hand over and when it is due back) and **Reject** (which
        asks for a reason the reader will be shown).

    ``Book Returns / Renewals``
        ``GET /return-renewal-requests/`` — what readers have asked to *do* with
        a book already in their hands. The row menu is request-type-dependent: a
        ``return`` row offers "Approve Return"/"Reject Return", a ``renewal`` row
        "Approve Renewal"/"Reject Renewal". Approving a renewal opens the
        "Re-assign to Student" dialog, whose only input is the new return date.

    ``Overdue Books``
        ``GET /book-requests/overdue/students`` — one row per reader, with the
        reminder controls.

Why a branch must be selected first
    The view's fetch effect returns early for a SchoolAdmin while
    ``currentSchoolAdminBranch?.branch_id`` is unset::

        if (authUserProfile?.roles?.name?.toLowerCase().includes("schooladmin") …) {
          if (!currentSchoolAdminBranch?.branch_id) return;
        }

    With no branch in the store nothing is ever requested, ``isLoading`` never
    clears, and the screen sits on ``AdminRequestAndRenewalLoader`` forever — so
    every wait here would time out for a reason that looks nothing like its
    cause. ``BranchesPage.select_branch`` is the prerequisite (it is also what
    puts ``branch_id`` on the three GETs; the backend answers 400
    BRANCH_ID_REQUIRED for a SchoolAdmin without it).

Dates are committed by clicking, never by Enter
    Both write dialogs carry an antd ``DatePicker`` inside a Radix
    ``DialogContent``, so every date goes through :meth:`BasePage.commit_date`
    (see that method for why a keystroke commit is unsafe in this app). Both
    pickers declare ``format="YYYY-MM-DD"``, and both refuse a date in the past:
    the approve dialog's ``disabledDate`` rules out anything at or before the end
    of today, the re-assign dialog's anything before the start of today.

The table has no ``scope``d headers and no test ids
    Rows are matched on the book's title — the one cell carrying a value this
    suite chose — and cells are read positionally off :data:`REQUEST_COLUMNS` /
    :data:`RENEWAL_COLUMNS`, which is what pins the column order.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── the route ────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/requests_and_renewals(?:$|[?#])")

# ── the sidebar (SideNavigation/nav-config.tsx, "Library Module" section) ────
# The section is ``branchOnly``, which for a SchoolAdmin means "only once a
# branch has been zoomed into" — see the module docstring.
NAV_LIBRARY_SECTION = re.compile(r"^\s*Library Module\s*$", re.I)
NAV_ENTRY = re.compile(r"^\s*Returns & Renewals\s*$", re.I)

# ── the librarian workspace (views/AdminView.tsx) ───────────────────────────
# Both faces of this route are headed "Manage Requests", so the subheading is
# what tells them apart: the borrower's is the one word shorter.
DESK_HEADING = re.compile(r"^\s*Manage Requests\s*$", re.I)
DESK_SUBHEADING = re.compile(
    r"All book requests initiated by students will appear here", re.I
)
READER_SUBHEADING = re.compile(
    r"^\s*All book requests initiated will appear here\s*$", re.I
)

SEARCH_PLACEHOLDER = re.compile(r"^\s*Search book by id or name\s*$", re.I)

# ── the three tabs ───────────────────────────────────────────────────────────
# Each tab button carries its own row count in a badge, so the accessible name
# reads "Book Requests 3" — matched unanchored on purpose. "Book Returns /
# Renewals" carries a slash and must go through as_pattern().
TAB_BOOK_REQUESTS = re.compile(r"Book Requests", re.I)
TAB_RETURNS_RENEWALS = re.compile(r"Book Returns\s*/\s*Renewals", re.I)
TAB_OVERDUE = re.compile(r"Overdue Books", re.I)

# ── the two tables, column for column ───────────────────────────────────────
REQUEST_COLUMNS = (
    "Name of Student", "Requested Book", "Request Date",
    "Expected Return Date", "Request Status", "Approve By",
)
RENEWAL_COLUMNS = (
    "Name of Student", "Book Title", "Request Date",
    "Expected Return Date", "Request Status", "Approve By",
)
# …plus the actions column both tables end on.
COLUMN_COUNT = len(REQUEST_COLUMNS) + 1

NOT_SPECIFIED = re.compile(r"^\s*Not specified\s*$", re.I)

# ── the row menu (Radix DropdownMenu) ───────────────────────────────────────
VIEW_DETAILS_ITEM = re.compile(r"^\s*View Details\s*$", re.I)
APPROVE_ITEM = re.compile(r"^\s*Approve\s*$", re.I)
REJECT_ITEM = re.compile(r"^\s*Reject\s*$", re.I)
APPROVE_RETURN_ITEM = re.compile(r"^\s*Approve Return\s*$", re.I)
REJECT_RETURN_ITEM = re.compile(r"^\s*Reject Return\s*$", re.I)
APPROVE_RENEWAL_ITEM = re.compile(r"^\s*Approve Renewal\s*$", re.I)
REJECT_RENEWAL_ITEM = re.compile(r"^\s*Reject Renewal\s*$", re.I)

# ── "Approve Request" dialog ────────────────────────────────────────────────
APPROVE_DIALOG = re.compile(r"^\s*Approve Request\s*$", re.I)
BOOK_COPY_PLACEHOLDER = re.compile(r"^\s*Select specific book\s*$", re.I)
# `Assign to ${role}` — "Student" or "Staff" off the requester's role — and
# "Processing..." while the PUT is in flight.
ASSIGN_BUTTON = re.compile(r"^\s*Assign to\s+\w+\s*$", re.I)
APPROVED_TOAST = re.compile(r"Request successfully Approved", re.I)

# ── "Reject Request" dialog ─────────────────────────────────────────────────
REJECT_DIALOG = re.compile(r"^\s*Reject Request\s*$", re.I)
# The textarea strips every digit as it is typed, so a reason with numbers in it
# would not survive the round trip.
COMMENT_PLACEHOLDER = re.compile(r"Add a comment for student", re.I)
CONFIRM_REJECT_BUTTON = re.compile(r"^\s*Yes,\s*reject\s*$", re.I)
REJECTED_TOAST = re.compile(r"Request successfully rejected", re.I)

# ── "Re-assign to Student" dialog (approving a renewal) ─────────────────────
REASSIGN_DIALOG = re.compile(r"^\s*Re-assign to Student\s*$", re.I)
REASSIGN_BUTTON = re.compile(r"^\s*Re-assign\s*$", re.I)
REASSIGNED_TOAST = re.compile(r"Book successfully Re-assigned", re.I)

# ── "Book Request Details" dialog (read-only) ───────────────────────────────
DETAILS_DIALOG = re.compile(r"^\s*Book Request Details\s*$", re.I)
DETAILS_CLOSE_BUTTON = re.compile(r"^\s*Close Preview\s*$", re.I)

# ── empty states (components/common/EmptyState) ─────────────────────────────
NO_REQUESTS = re.compile(r"^\s*No requests found\s*$", re.I)
NO_RETURN_REQUESTS = re.compile(
    r"^\s*No return or renewal requests found\s*$", re.I
)
NO_OVERDUE = re.compile(r"^\s*No overdue books found\s*$", re.I)


class RequestDeskPage(BasePage):
    """The librarian's circulation desk at /module/requests_and_renewals."""

    URL = "/module/requests_and_renewals"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "RequestDeskPage":
        super().open()
        return self

    def open_from_sidebar(self) -> "RequestDeskPage":
        """Reach the desk the way a librarian does — via the Library menu.

        Falls back to the route when the sidebar is collapsed (it is on narrow
        viewports); how the user got here is worth showing, but it is not what
        this page object asserts.
        """
        link = self.page.get_by_role("link", name=as_pattern(NAV_ENTRY)).first
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
            self.page.get_by_role("link", name=as_pattern(NAV_ENTRY)).first
        ).to_be_visible(timeout=25_000)

    # ───────────────────────── readers ───────────────────────────

    def wait_for_table(self, timeout_ms: int = 40_000) -> "RequestDeskPage":
        """Wait out ``AdminRequestAndRenewalLoader``.

        The whole workspace is replaced by that skeleton while any of the three
        fetches is in flight — including the refetch that follows every decision
        — so waiting on the header row is what makes the rest of this object safe
        to call. The header row is drawn for an empty queue too, so this can
        neither pass on a half-rendered screen nor hang on a legitimately empty
        one.
        """
        expect(self.page.locator("table thead tr").first).to_be_visible(
            timeout=timeout_ms
        )
        return self

    def expect_desk_view(self) -> None:
        """This is the librarian's desk, not the borrower's own record."""
        expect(
            self.page.get_by_role("heading", name=as_pattern(DESK_HEADING)).first
        ).to_be_visible(timeout=25_000)
        expect(self.page.get_by_text(DESK_SUBHEADING)).to_be_visible()
        expect(self.page.get_by_text(READER_SUBHEADING)).to_have_count(0)
        expect(
            self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))
        ).to_be_visible()

    def expect_tabs(self) -> None:
        """All three queues are on offer."""
        for tab in (TAB_BOOK_REQUESTS, TAB_RETURNS_RENEWALS, TAB_OVERDUE):
            expect(
                self.page.get_by_role("button", name=as_pattern(tab)).first
            ).to_be_visible(timeout=25_000)

    def expect_column_headers(self, columns: tuple[str, ...]) -> None:
        """Assert the header row by position, pinning the column order."""
        cells = self.page.locator("table thead tr").first.locator("th")
        expect(cells).to_have_count(COLUMN_COUNT)
        for index, header in enumerate(columns):
            expect(cells.nth(index)).to_have_text(
                as_pattern(rf"^\s*{re.escape(header)}\s*$")
            )

    def open_tab(self, tab: re.Pattern[str]) -> "RequestDeskPage":
        """Switch queues. The tab is client-side — no refetch, no loader."""
        self.page.get_by_role("button", name=as_pattern(tab)).first.click()
        return self

    def rows(self) -> Locator:
        return self.page.locator("table tbody tr")

    def row(self, book_title: str) -> Locator:
        """The row for one request, matched on its book title cell."""
        return self.rows().filter(
            has_text=as_pattern(re.escape(book_title))
        ).first

    def expect_request(
        self,
        book_title: str,
        *,
        columns: tuple[str, ...] = REQUEST_COLUMNS,
        student: str | None = None,
        status: str | None = None,
        manager: str | None = None,
        return_date_set: bool | None = None,
    ) -> None:
        """One row, cell by cell.

        Everything optional here is a value only the server could have supplied
        — the requester joined onto the request, the status the decision wrote,
        the manager recorded against it — so a row that matches them can only
        have rendered this branch's queue.

        ``return_date_set`` is asserted as "is/is not the literal 'Not
        specified'" rather than as a date: the browser sends the chosen day with
        the current wall-clock time appended and the API answers in UTC, so the
        rendered day is not reliably the day that was picked.
        """
        row = self.row(book_title)
        expect(row).to_be_visible(timeout=30_000)
        title_column = "Requested Book" if "Requested Book" in columns else "Book Title"
        expect(_cell(row, columns, title_column)).to_have_text(
            as_pattern(rf"^\s*{re.escape(book_title)}\s*$")
        )
        if student:
            expect(_cell(row, columns, "Name of Student")).to_contain_text(
                as_pattern(re.escape(student))
            )
        if status:
            expect(_cell(row, columns, "Request Status")).to_have_text(
                as_pattern(rf"^\s*{re.escape(status)}\s*$"), timeout=30_000
            )
        if manager:
            expect(_cell(row, columns, "Approve By")).to_contain_text(
                as_pattern(re.escape(manager)), timeout=30_000
            )
        if return_date_set is not None:
            cell = _cell(row, columns, "Expected Return Date")
            if return_date_set:
                expect(cell).not_to_have_text(NOT_SPECIFIED, timeout=30_000)
            else:
                expect(cell).to_have_text(NOT_SPECIFIED, timeout=30_000)

    def expect_request_absent(self, book_title: str, timeout_ms: int = 25_000) -> None:
        expect(
            self.rows().filter(has_text=as_pattern(re.escape(book_title)))
        ).to_have_count(0, timeout=timeout_ms)

    # ───────────────────────── row menu ──────────────────────────

    def open_row_menu(self, book_title: str) -> None:
        """Open a row's "…" menu. Its trigger carries an icon and no label."""
        row = self.row(book_title)
        expect(row).to_be_visible(timeout=30_000)
        row.get_by_role("button").last.click()

    def expect_menu_items(
        self, book_title: str, *, present: tuple[re.Pattern[str], ...] = (),
        absent: tuple[re.Pattern[str], ...] = (),
    ) -> None:
        """What the row offers to do about this request, and what it does not.

        The decision items are rendered only while ``status === "pending"``, so
        this is how "already decided" is read off the UI rather than off a toast.
        """
        self.open_row_menu(book_title)
        for item in present:
            expect(
                self.page.get_by_role("menuitem", name=as_pattern(item)).first
            ).to_be_visible(timeout=15_000)
        for item in absent:
            expect(
                self.page.get_by_role("menuitem", name=as_pattern(item))
            ).to_have_count(0)
        # Closed before returning: a Radix menu is modal while it is open, and
        # the next row's trigger would sit behind its dismiss layer.
        self.page.keyboard.press("Escape")
        expect(self.page.get_by_role("menu")).to_have_count(0, timeout=10_000)

    # ───────────────────────── decisions ─────────────────────────

    def approve_request(
        self, book_title: str, *, copy_name: str, expected_return_date: str
    ) -> None:
        """Hand a physical copy over and set the date it is due back.

        ``copy_name`` is the name the backend generated for the copy
        (``"<book title> <6 digits>"``, ``BookCopyService.add_book_copies``), so
        picking it by name is an assertion that the dialog listed the server's
        own ``available_copies_list`` rather than anything the browser invented.
        """
        self.open_row_menu(book_title)
        self.page.get_by_role("menuitem", name=as_pattern(APPROVE_ITEM)).first.click()

        dialog = self.dialog_titled(APPROVE_DIALOG)
        dialog.get_by_role("combobox").first.click()
        self.page.get_by_role(
            "option", name=as_pattern(rf"^\s*{re.escape(copy_name)}\s*$")
        ).first.click()
        self.commit_date(
            dialog.locator(".ant-picker input").first,
            expected_return_date,
            display_format="%Y-%m-%d",
        )

        dialog.get_by_role("button", name=as_pattern(ASSIGN_BUTTON)).first.click()
        self.expect_toast(APPROVED_TOAST, timeout_ms=25_000)
        expect(dialog).to_be_hidden(timeout=20_000)
        self.wait_for_table()

    def reject_request(self, book_title: str, *, reason: str) -> None:
        """Turn a request down, recording the reason the reader will be shown."""
        self.open_row_menu(book_title)
        self.page.get_by_role("menuitem", name=as_pattern(REJECT_ITEM)).first.click()

        dialog = self.dialog_titled(REJECT_DIALOG)
        dialog.get_by_placeholder(COMMENT_PLACEHOLDER).first.fill(reason)
        dialog.get_by_role(
            "button", name=as_pattern(CONFIRM_REJECT_BUTTON)
        ).first.click()
        self.expect_toast(REJECTED_TOAST, timeout_ms=25_000)
        expect(dialog).to_be_hidden(timeout=20_000)
        self.wait_for_table()

    def approve_renewal(self, book_title: str, *, new_return_date: str) -> None:
        """Grant a reader longer with a book they already hold.

        The dialog shows the reader's own reason read-only and asks for one
        thing: the new return date, which ``process_checkout_request`` writes
        back onto the original book request.
        """
        self.open_row_menu(book_title)
        self.page.get_by_role(
            "menuitem", name=as_pattern(APPROVE_RENEWAL_ITEM)
        ).first.click()

        dialog = self.dialog_titled(REASSIGN_DIALOG)
        self.commit_date(
            dialog.locator(".ant-picker input").first,
            new_return_date,
            display_format="%Y-%m-%d",
        )
        dialog.get_by_role("button", name=as_pattern(REASSIGN_BUTTON)).first.click()
        self.expect_toast(REASSIGNED_TOAST, timeout_ms=25_000)
        expect(dialog).to_be_hidden(timeout=20_000)
        self.wait_for_table()

    # ───────────────────────── drill-down ────────────────────────

    def open_details(self, book_title: str) -> Locator:
        """Open a row's read-only "Book Request Details" dialog."""
        self.open_row_menu(book_title)
        self.page.get_by_role(
            "menuitem", name=as_pattern(VIEW_DETAILS_ITEM)
        ).first.click()
        return self.dialog_titled(DETAILS_DIALOG)

    def close_details(self, dialog: Locator) -> None:
        dialog.get_by_role(
            "button", name=as_pattern(DETAILS_CLOSE_BUTTON)
        ).first.click()
        expect(dialog).to_be_hidden(timeout=15_000)

    # ───────────────────────── internals ─────────────────────────

    def dialog_titled(self, title: re.Pattern[str]) -> Locator:
        """Scope to the one Radix dialog carrying ``title``.

        Radix mounts a ``DialogContent`` only while it is open, so at most one of
        this view's eight dialogs exists at a time — but several of them share a
        textarea placeholder, so they are still addressed by title rather than by
        ``get_by_role("dialog")`` alone.
        """
        dialog = self.page.get_by_role("dialog").filter(
            has=self.page.get_by_text(as_pattern(title))
        ).first
        expect(dialog).to_be_visible(timeout=20_000)
        return dialog


def _cell(row: Locator, columns: tuple[str, ...], column: str) -> Locator:
    return row.locator("td").nth(columns.index(column))
