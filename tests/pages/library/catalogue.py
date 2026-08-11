"""Library → Catalogue, as everyone who is not a librarian sees it.

``/module/catalogue`` renders one of two workspaces off the signed-in role
(``src/app/module/catalogue/page.tsx``). A SchoolAdmin — or an Admin/librarian
holding a ``catalogue`` permission — gets ``views/AdminCatalogueView.tsx``, the
"Manage Books" register with Add Book / Bulk Upload and a per-row edit menu.
*Everyone else*, a Teacher included, gets ``views/StudentCatalogueView.tsx``:
the same table, read-only, headed "Library Books".

This page object models that second view. It exposes readers, the two filters
the toolbar offers, and :meth:`expect_authoring_controls_absent` — and no create
or edit verbs at all, because the view renders none: ``StudentCatalogueView``
mounts ``CatalogueTableToolbar`` without ``onAddBookClick``/``onBulkUploadClick``,
and the toolbar only draws those buttons when it is handed the callbacks.

What the table is
    A plain ``<table>``: a header row of Thumbnail / Title / Author / ISBN /
    Category / Copies Available plus one unlabelled actions column, then one row
    per book from ``GET /books/`` (25 per page). With nothing to show, the body
    collapses to a single ``EmptyState`` row reading "No books available in the
    catalogue".

    The header cells carry no ``scope``, so — exactly as on the student
    timetable — they resolve to plain ``cell`` rather than ``columnheader``, and
    :meth:`expect_column_headers` reads them positionally off
    ``table thead tr th`` instead of by role.

Both filters are server-side
    The search box is debounced 500 ms and then re-requests ``GET /books/`` with
    ``search=``; the category select re-requests it with ``category_name=``.
    Neither one filters rows in the browser, so every wait here is a wait on a
    network round trip, not on a re-render — which is why the readers take
    generous timeouts.

The row's "Copies Available"
    ``available_copies_count`` is a computed field on the API response — the
    number of ``BookCopy`` rows still marked available — and the cell shows the
    word "Out of stock" instead of a zero. Asserting it is therefore an
    assertion about what the server counted, not about anything the browser
    could have derived from the title.

Whose books they are
    For any non-admin role ``list_books`` ignores the query string and scopes on
    ``user.school_branch_id`` (``api/routes/book.py``), so a Teacher can only
    ever be shown their own branch's shelves.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── the route ────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/catalogue(?:$|[?#])")
DETAIL_URL = re.compile(r"/module/catalogue/student_book_view/\d+")

# ── the sidebar (SideNavigation/nav-config.tsx, "Library Module" section) ────
# The section is ``branchOnly``, but ``canShowSection`` treats branch state as a
# SchoolAdmin-only concept, so a Teacher holding ("manage", "catalogue") sees it
# as long as the pack licenses the module.
NAV_LIBRARY_SECTION = re.compile(r"^\s*Library Module\s*$", re.I)
NAV_CATALOGUE = re.compile(r"^\s*Catalogue\s*$", re.I)

# ── the reader-facing workspace (views/StudentCatalogueView.tsx) ─────────────
READER_HEADING = re.compile(r"^\s*Library Books\s*$", re.I)
READER_SUBHEADING = re.compile(
    r"Search through the available books and send a request", re.I
)
# The librarian workspace this role must NOT be given instead
# (views/AdminCatalogueView.tsx).
ADMIN_HEADING = re.compile(r"^\s*Manage Books\s*$", re.I)

# ── the toolbar (components/CatalogueTableToolbar.tsx) ───────────────────────
SEARCH_PLACEHOLDER = re.compile(r"Search book by id, name or ISBN", re.I)
ALL_CATEGORIES = re.compile(r"^\s*All Categories\s*$", re.I)
ADVANCED_SEARCH_BUTTON = re.compile(r"^\s*Advanced Search\s*$", re.I)
RESET_FILTER_BUTTON = re.compile(r"^\s*Reset Filter\s*$", re.I)
# Rendered only when the toolbar is handed the matching callback, which only the
# librarian workspace does.
ADD_BOOK_BUTTON = re.compile(r"^\s*Add Book\s*$", re.I)
BULK_UPLOAD_BUTTON = re.compile(r"^\s*Bulk Upload\s*$", re.I)

# ── the table ────────────────────────────────────────────────────────────────
COLUMN_HEADERS = (
    "Thumbnail", "Title", "Author", "ISBN", "Category", "Copies Available",
)
# …plus one deliberately empty header over the actions column.
COLUMN_COUNT = len(COLUMN_HEADERS) + 1

OUT_OF_STOCK = re.compile(r"^\s*Out of stock\s*$", re.I)
EMPTY_STATE = re.compile(r"No books available in the catalogue", re.I)

# ── row actions the reader view offers (both read-only) ─────────────────────
VIEW_DETAILS_BUTTON = re.compile(r"^\s*View details\s*$", re.I)
REQUEST_BOOK_BUTTON = re.compile(r"^\s*Request Book\s*$", re.I)

# ── failure surfaces (handleErrorMessage's fallbacks) ───────────────────────
BOOKS_LOAD_FAILURE = re.compile(r"Failed to fetch books", re.I)
CATEGORIES_LOAD_FAILURE = re.compile(r"Failed to fetch categories", re.I)

# Anything that would let the viewer rewrite the shelf. Anchored at the start of
# the accessible name so the view's own read-side controls — "Reset Filter",
# "Advanced Search", "Request Book", "Previous"/"Next" — are not swept up.
WRITE_CONTROL = re.compile(
    r"^\s*(?:add|create|new|edit|delete|remove|update|save|upload|import)\b", re.I
)


class CataloguePage(BasePage):
    """The read-only "Library Books" catalogue at /module/catalogue."""

    URL = "/module/catalogue"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "CataloguePage":
        super().open()
        return self

    def open_from_sidebar(self) -> "CataloguePage":
        """Reach the catalogue the way a real reader does — via Library Module.

        Falls back to the route itself when the sidebar is collapsed (it is on
        narrow viewports); how the user got here is worth showing, but it is not
        what this page object asserts.
        """
        link = self.page.get_by_role("link", name=as_pattern(NAV_CATALOGUE)).first
        if link.count():
            link.click()
        else:
            self.open()
        self.page.wait_for_url(LIST_URL, timeout=25_000)
        return self

    def expect_nav_entry(self) -> None:
        """The Library section is on offer, and Catalogue inside it.

        The section title is asserted too, so "the Catalogue link is there"
        cannot pass off the back of a half-rendered sidebar.
        """
        expect(
            self.page.get_by_text(as_pattern(NAV_LIBRARY_SECTION)).first
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_CATALOGUE)).first
        ).to_be_visible(timeout=25_000)

    # ───────────────────────── readers ───────────────────────────

    def wait_for_table(self, timeout_ms: int = 30_000) -> "CataloguePage":
        """Wait out ``StudentViewCatalogueLoader``.

        The header row only exists once ``GetBooks`` has resolved, and unlike a
        book row it is drawn for an empty shelf too — so this can neither pass
        on a half-rendered screen nor hang on a legitimately empty one.
        """
        expect(self.page.locator("table thead tr").first).to_be_visible(
            timeout=timeout_ms
        )
        return self

    def expect_reader_view(self) -> None:
        """This is the read-only catalogue, not the librarian's register."""
        expect(
            self.page.get_by_role("heading", name=as_pattern(READER_HEADING))
        ).to_be_visible(timeout=25_000)
        expect(self.page.get_by_text(as_pattern(READER_SUBHEADING))).to_be_visible()
        expect(
            self.page.get_by_role("heading", name=as_pattern(ADMIN_HEADING))
        ).to_have_count(0)

    def expect_column_headers(self) -> None:
        """Assert the header row by position, pinning the column order."""
        cells = self.page.locator("table thead tr").first.locator("th")
        expect(cells).to_have_count(COLUMN_COUNT)
        for index, header in enumerate(COLUMN_HEADERS):
            expect(cells.nth(index)).to_have_text(
                as_pattern(rf"^\s*{re.escape(header)}\s*$")
            )

    def expect_toolbar(self) -> None:
        expect(
            self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_role("button", name=as_pattern(ADVANCED_SEARCH_BUTTON))
        ).to_be_visible()
        expect(
            self.page.get_by_role("button", name=as_pattern(RESET_FILTER_BUTTON))
        ).to_be_visible()

    def rows(self) -> Locator:
        return self.page.locator("table tbody tr")

    def row(self, title: str) -> Locator:
        """The row for one book, matched on its title cell."""
        return self.rows().filter(has_text=as_pattern(re.escape(title))).first

    def expect_book(self, title: str, *, author: str | None = None,
                    isbn: str | None = None, category: str | None = None,
                    copies: int | None = None) -> None:
        """One row, and the server-side values it carries, cell by cell.

        Every optional field here is something only the backend could supply —
        the author rows joined onto the book, the category it was filed under,
        the count of copies still marked available — so matching them proves the
        table really rendered this school's ``GET /books/`` answer.

        Asserted per *cell* rather than against the row's whole text, which both
        pins :data:`COLUMN_HEADERS`' order and keeps a copy count from being
        satisfied by a stray digit inside an ISBN or a title.
        """
        row = self.row(title)
        expect(row).to_be_visible(timeout=25_000)
        expect(self._cell(row, "Title")).to_have_text(
            as_pattern(rf"^\s*{re.escape(title)}\s*$")
        )
        if author:
            expect(self._cell(row, "Author")).to_contain_text(
                as_pattern(re.escape(author))
            )
        if isbn:
            expect(self._cell(row, "ISBN")).to_have_text(
                as_pattern(rf"^\s*{re.escape(isbn)}\s*$")
            )
        if category:
            expect(self._cell(row, "Category")).to_have_text(
                as_pattern(rf"^\s*{re.escape(category)}\s*$")
            )
        if copies is not None:
            # A zero renders as the words "Out of stock", never as a digit.
            cell = self._cell(row, "Copies Available")
            expect(cell).to_have_text(
                OUT_OF_STOCK if copies == 0
                else as_pattern(rf"^\s*{copies}\s*$")
            )

    @staticmethod
    def _cell(row: Locator, column: str) -> Locator:
        return row.locator("td").nth(COLUMN_HEADERS.index(column))

    def expect_book_absent(self, title: str, timeout_ms: int = 25_000) -> None:
        expect(
            self.rows().filter(has_text=as_pattern(re.escape(title)))
        ).to_have_count(0, timeout=timeout_ms)

    def expect_total(self, count: int, timeout_ms: int = 25_000) -> None:
        """The "N books total" badge beside the category heading.

        It is rendered from ``total_count`` — the server's count of everything
        matching the current filter, not of the rows on this page — so it is the
        honest witness that a filter round-tripped.
        """
        noun = "book" if count == 1 else "books"
        expect(
            self.page.get_by_text(as_pattern(rf"{count}\s+{noun}\s+total")).first
        ).to_be_visible(timeout=timeout_ms)

    def expect_category_heading(self, category: str | None = None) -> None:
        """The table's own heading — the selected category, or "All Categories".

        Not anchored: the ``<h2>`` also carries the "N books total" badge, so its
        text content is "All Categories3 books total". Scoping to ``h2`` is what
        keeps this off the toolbar's select trigger, which reads the same word.
        """
        wanted = as_pattern(
            re.escape("All Categories") if category is None else re.escape(category)
        )
        expect(
            self.page.locator("h2").filter(has_text=wanted).first
        ).to_be_visible(timeout=25_000)

    def expect_no_load_failure(self) -> None:
        """Neither fetch fell over.

        Asserted rather than assumed: ``handleErrorMessage`` swallows a licensing
        refusal silently, so an empty table on its own would not tell the two
        apart.
        """
        expect(self.page.get_by_text(as_pattern(BOOKS_LOAD_FAILURE))).to_have_count(0)
        expect(
            self.page.get_by_text(as_pattern(CATEGORIES_LOAD_FAILURE))
        ).to_have_count(0)

    def expect_authoring_controls_absent(self) -> None:
        """Nothing on this view offers to change the catalogue.

        The two named buttons are the toolbar's write half, which
        ``CatalogueTableToolbar`` only draws when it is handed
        ``onAddBookClick``/``onBulkUploadClick`` — and only the librarian
        workspace hands them over.

        The generic sweep is scoped to the table because that is where the
        librarian workspace keeps its per-row edit / delete / add-copies menu;
        page-wide it would also be reading the app chrome, which is not this
        screen's to answer for.
        """
        expect(
            self.page.get_by_role("button", name=as_pattern(ADD_BOOK_BUTTON))
        ).to_have_count(0)
        expect(
            self.page.get_by_role("button", name=as_pattern(BULK_UPLOAD_BUTTON))
        ).to_have_count(0)
        expect(
            self.page.locator("table").get_by_role(
                "button", name=as_pattern(WRITE_CONTROL)
            )
        ).to_have_count(0)

    # ───────────────────────── filters ───────────────────────────

    def search(self, term: str) -> None:
        """Type into the search box; the fetch fires 500 ms after the last key."""
        self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER)).first.fill(term)

    def reset_filters(self) -> None:
        self.click_button(RESET_FILTER_BUTTON)

    def filter_by_category(self, category: str) -> None:
        """Pick a category from the toolbar's Radix select.

        Anchored on the trigger's current text rather than on a label — the
        select has none — and the trigger always reads either "All Categories"
        or the category in force, so it is never the empty trigger that a Radix
        value matching no item would render.
        """
        self.page.get_by_role("combobox").first.click()
        self.page.get_by_role(
            "option", name=as_pattern(rf"^\s*{re.escape(category)}\s*$")
        ).first.click()

    def expect_search_value(self, term: str) -> None:
        expect(
            self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER)).first
        ).to_have_value(term)

    # ───────────────────────── drill-down ────────────────────────

    def open_details(self, title: str) -> "BookDetailsPage":
        """Follow a row's "View details" link into the book's own page."""
        self.row(title).get_by_role(
            "button", name=as_pattern(VIEW_DETAILS_BUTTON)
        ).first.click()
        self.page.wait_for_url(DETAIL_URL, timeout=25_000)
        return BookDetailsPage(self.page, self.frontend_base_url)


# ── the book's own page (catalogue/student_book_view/[studentBookId]) ────────

DETAIL_BREADCRUMB = re.compile(r"^\s*Book catalogue\s*$", re.I)
DETAIL_FIELDS = ("Genre:", "Author(s):", "ISBN:", "Published:", "Pages:", "Language:")
DETAIL_AVAILABILITY = re.compile(r"^\s*Availability\s*$", re.I)
DETAIL_OUT_OF_STOCK = re.compile(r"Out of stock - Currently unavailable", re.I)


class BookDetailsPage(BasePage):
    """One book, read-only: ``GET /books/{id}`` rendered as a detail card.

    Reached from a catalogue row's "View details" link. Nothing here writes —
    the page's only interactive control is the description's "Read more" toggle.
    """

    def expect_loaded(self, title: str) -> None:
        expect(
            self.page.get_by_role(
                "heading", name=as_pattern(rf"^\s*{re.escape(title)}\s*$")
            ).first
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_role("link", name=as_pattern(DETAIL_BREADCRUMB)).first
        ).to_be_visible()

    def expect_fields(self) -> None:
        """Every labelled field the card lays out, in the order it lays them out."""
        for field in DETAIL_FIELDS:
            expect(
                self.page.get_by_text(as_pattern(rf"^\s*{re.escape(field)}\s*$")).first
            ).to_be_visible(timeout=25_000)

    def expect_value(self, value: str) -> None:
        expect(
            self.page.get_by_text(as_pattern(re.escape(value))).first
        ).to_be_visible(timeout=25_000)

    def expect_available(self, copies: int) -> None:
        """The green availability banner, with the server's own copy count."""
        expect(
            self.page.get_by_text(as_pattern(DETAIL_AVAILABILITY)).first
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_text(
                as_pattern(
                    rf"Available for borrowing\s*\({copies}\s+copies available\)"
                )
            ).first
        ).to_be_visible()
        expect(self.page.get_by_text(as_pattern(DETAIL_OUT_OF_STOCK))).to_have_count(0)

    def expect_authoring_controls_absent(self) -> None:
        expect(
            self.page.get_by_role("button", name=as_pattern(WRITE_CONTROL))
        ).to_have_count(0)
