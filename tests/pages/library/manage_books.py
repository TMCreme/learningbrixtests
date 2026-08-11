"""Library → Catalogue, as the librarian runs it: the "Manage Books" register.

Same route as :mod:`tests.pages.library.catalogue` — ``/module/catalogue`` —
but the other half of it. ``src/app/module/catalogue/page.tsx`` picks its view
off the signed-in role: "schooladmin", an "admin" holding a ``catalogue``
permission, or a role whose name contains "library"/"librarian" get
``views/AdminCatalogueView.tsx``; everyone else gets the read-only
``StudentCatalogueView`` that the sibling module models.

What this workspace is
    A "Manage Books" header, ``components/CatalogueTableToolbar`` (search,
    category filter, Advanced Search, Reset Filter — plus, when
    ``usePermission("catalogue", …manage)`` holds, "Bulk Upload" and "Add Book"),
    and a five-column register: Title / Author(s) / ISBN / Category / Copies
    Available, with a sixth, unlabelled column carrying
    ``components/CatalogueActions`` — the antd dropdown holding Edit Book, Add
    More Book Copies, Remove Book Copies, Delete Book, View details, View All
    Copies.

Two traps this page object exists to absorb
    1. **The add/edit form resets itself when its category list arrives.**
       ``CatalogueModal``'s effect is keyed on ``[open, initialData, categories]``
       and re-seeds ``formData`` from scratch (add) or from ``initialData``
       (edit) every time ``categories`` changes identity — and ``categories`` is
       fetched *on open*. So anything typed before ``GET /book/categories/``
       resolves is silently wiped, and the symptom is a form that submits with
       an empty title. :meth:`_choose_category` is therefore always called
       first: it opens the Radix select and waits for the wanted category to be
       offered, which cannot happen until that fetch has landed and the reset
       has already run.

    2. **The publication date must be committed by clicking the panel cell.**
       ``BasePage.commit_date`` is used rather than typing + Enter. This picker
       does sit in a form with an ``onSubmit``, so Enter would not reload the
       page — it would *submit the half-filled form*, which is no better.

Required fields, and which layer requires them
    ``handleSubmit`` refuses to post without title, publisher, description,
    category, at least one author, a thumbnail and a positive page count. It
    does **not** check the publication date — but ``Book.published_date`` is
    ``nullable=False`` in the database, so a book saved without one is a 400
    from the backend. This page object treats the date as mandatory.

    The cover image is a real upload: the hidden ``#fileInput`` is read by
    ``FileReader`` into a ``data:`` URL, which ``POST /books/create/`` then
    pushes to S3 (``utils/s3_upload_service.upload_file_to_s3``) before storing
    the resulting URL. :data:`COVER_IMAGE` is a 1×1 PNG — the smallest payload
    that survives that round trip.

Input sanitising the caller has to live with
    The Authors field strips digits and hyphens, and Publisher strips anything
    outside ``[A-Za-z\\s'-]``. So a run tag (which contains digits) can go in the
    title but never in the author or publisher — put it in the title, which is
    unsanitised, and which is also what the register is searched on.
"""
from __future__ import annotations

import base64
import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern
from tests.pages.library.catalogue import NAV_CATALOGUE, NAV_LIBRARY_SECTION

# ── the route ────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/catalogue(?:$|[?#])")

# ── the librarian workspace (views/AdminCatalogueView.tsx) ───────────────────
MANAGE_HEADING = re.compile(r"^\s*Manage Books\s*$", re.I)
MANAGE_SUBHEADING = re.compile(r"Easily update book details", re.I)
# The read-only view the same route renders for every other role; a librarian
# must never be quietly demoted into it.
READER_HEADING = re.compile(r"^\s*Library Books\s*$", re.I)

# ── the toolbar (components/CatalogueTableToolbar.tsx) ───────────────────────
SEARCH_PLACEHOLDER = re.compile(r"Search book by id, name or ISBN", re.I)
ALL_CATEGORIES = re.compile(r"^\s*All Categories\s*$", re.I)
ADVANCED_SEARCH_BUTTON = re.compile(r"^\s*Advanced Search\s*$", re.I)
RESET_FILTER_BUTTON = re.compile(r"^\s*Reset Filter\s*$", re.I)
# Drawn only when the toolbar is handed the callbacks, which only this view does,
# and only while ``isManage`` holds.
ADD_BOOK_BUTTON = re.compile(r"^\s*Add Book\s*$", re.I)
BULK_UPLOAD_BUTTON = re.compile(r"^\s*Bulk Upload\s*$", re.I)

# ── the register ─────────────────────────────────────────────────────────────
COLUMN_HEADERS = ("Title", "Author(s)", "ISBN", "Category", "Copies Available")
# …plus the unlabelled actions column.
COLUMN_COUNT = len(COLUMN_HEADERS) + 1
ACTIONS_COLUMN = len(COLUMN_HEADERS)

EMPTY_STATE = re.compile(r"No books available in the catalogue", re.I)
OUT_OF_STOCK = re.compile(r"Out of stock", re.I)

# ── the row menu (components/CatalogueActions.tsx) ───────────────────────────
EDIT_BOOK_ACTION = re.compile(r"^\s*Edit Book\s*$", re.I)
ADD_COPIES_ACTION = re.compile(r"^\s*Add More Book Copies\s*$", re.I)
REMOVE_COPIES_ACTION = re.compile(r"^\s*Remove Book Copies\s*$", re.I)
DELETE_BOOK_ACTION = re.compile(r"^\s*Delete Book\s*$", re.I)

# ── the add/edit dialog (components/CatalogueModal.tsx) ──────────────────────
# Its DialogDescription is the one string no other dialog on this route carries,
# so it is what scopes every field lookup below.
BOOK_DIALOG_MARKER = re.compile(r"Manage book details and metadata", re.I)
ADD_BOOK_DIALOG_TITLE = re.compile(r"^\s*Add Book\s*$", re.I)
EDIT_BOOK_DIALOG_TITLE = re.compile(r"^\s*Edit Book\s*$", re.I)

TITLE_PLACEHOLDER = re.compile(r"^\s*Book title\s*$", re.I)
ISBN_PLACEHOLDER = re.compile(r"^\s*ISBN number\s*$", re.I)
# The real placeholder carries commas and brackets — matched as a substring so
# the pattern stays readable.
AUTHORS_PLACEHOLDER = re.compile(r"Type full names, separated by commas", re.I)
PUBLISHER_PLACEHOLDER = re.compile(r"^\s*Publisher name\s*$", re.I)
CATEGORY_LABEL = re.compile(r"^\s*Category \*\s*$", re.I)
PUBLICATION_DATE_LABEL = re.compile(r"^\s*Publication Date \*\s*$", re.I)
PAGE_COUNT_LABEL = re.compile(r"^\s*Page Count \*\s*$", re.I)
DESCRIPTION_LABEL = re.compile(r"^\s*Description \*\s*$", re.I)
COVER_PREVIEW_ALT = re.compile(r"^\s*Book Cover\s*$", re.I)

SUBMIT_ADD_BOOK = re.compile(r"^\s*Add Book\s*$", re.I)
SUBMIT_UPDATE_BOOK = re.compile(r"^\s*Update Book\s*$", re.I)

# ── the copies dialog (components/BookCopiesModal.tsx) ───────────────────────
COPIES_DIALOG_MARKER = re.compile(r"Add new copies for", re.I)
NUM_COPIES_PLACEHOLDER = re.compile(r"^\s*Enter number of copies\s*$", re.I)
PHYSICAL_LOCATION_PLACEHOLDER = re.compile(r"Shelf A1, Room 201", re.I)
PHYSICAL_CONDITION_LABEL = re.compile(r"^\s*Physical Condition \*\s*$", re.I)
SUBMIT_COPIES = re.compile(r"^\s*Add \d+ Cop(?:y|ies)\s*$", re.I)

# ── the delete confirmation (an antd Modal, not a Radix dialog) ──────────────
DELETE_MODAL_MARKER = re.compile(r"Are you sure you want to delete", re.I)
DELETE_MODAL_CONFIRM = re.compile(r"^\s*Delete\s*$", re.I)

# ── toasts (react-hot-toast) ─────────────────────────────────────────────────
BOOK_ADDED_TOAST = re.compile(r"Book added successfully", re.I)
BOOK_UPDATED_TOAST = re.compile(r"Book updated successfully", re.I)
BOOK_DELETED_TOAST = re.compile(r"Book deleted successfully", re.I)
COPIES_ADDED_TOAST = re.compile(r"cop(?:y|ies) added successfully", re.I)

# ── failure surfaces (handleErrorMessage's fallbacks) ───────────────────────
BOOKS_LOAD_FAILURE = re.compile(r"Failed to fetch books", re.I)
CATEGORIES_LOAD_FAILURE = re.compile(r"Failed to (?:fetch|load) categories", re.I)
BOOK_SAVE_FAILURE = re.compile(r"Failed to (?:add|update|delete) book", re.I)
MISSING_FIELDS_TOAST = re.compile(r"Please fill out all the fields", re.I)

# The smallest cover the upload path accepts: a 1×1 transparent PNG. Sent as an
# in-memory FilePayload so no fixture file has to exist on disk.
COVER_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg=="
)


class ManageBooksPage(BasePage):
    """The librarian's "Manage Books" register at /module/catalogue."""

    URL = "/module/catalogue"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "ManageBooksPage":
        super().open()
        return self

    def open_from_sidebar(self) -> "ManageBooksPage":
        """Reach the register the way the librarian does — via Library Module.

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
        """The Library section is on offer, and Catalogue inside it."""
        expect(
            self.page.get_by_text(as_pattern(NAV_LIBRARY_SECTION)).first
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_CATALOGUE)).first
        ).to_be_visible(timeout=25_000)

    # ───────────────────────── readers ───────────────────────────

    def wait_for_register(self, timeout_ms: int = 30_000) -> "ManageBooksPage":
        """Wait out ``AdminViewCatalogueLoader``.

        The header row is drawn for an empty shelf too, so this can neither pass
        on a half-rendered screen nor hang on a legitimately empty one.
        """
        expect(self.page.locator("table thead tr").first).to_be_visible(
            timeout=timeout_ms
        )
        return self

    def expect_manage_view(self) -> None:
        """This is the librarian's register, not the reader's shelf."""
        expect(
            self.page.get_by_role("heading", name=as_pattern(MANAGE_HEADING))
        ).to_be_visible(timeout=25_000)
        expect(self.page.get_by_text(as_pattern(MANAGE_SUBHEADING))).to_be_visible()
        expect(
            self.page.get_by_role("heading", name=as_pattern(READER_HEADING))
        ).to_have_count(0)

    def expect_column_headers(self) -> None:
        """Assert the header row by position, pinning the column order."""
        cells = self.page.locator("table thead tr").first.locator("th")
        expect(cells).to_have_count(COLUMN_COUNT)
        for index, header in enumerate(COLUMN_HEADERS):
            expect(cells.nth(index)).to_have_text(
                as_pattern(rf"^\s*{re.escape(header)}\s*$")
            )

    def expect_authoring_controls(self) -> None:
        """The write half of the toolbar is drawn — this role may author.

        ``CatalogueTableToolbar`` renders these two only when it is handed
        ``onAddBookClick``/``onBulkUploadClick`` *and* ``isManage`` holds, so
        their presence is the screen's own statement that the signed-in role
        carries ("manage", "catalogue").
        """
        expect(
            self.page.get_by_role("button", name=as_pattern(ADD_BOOK_BUTTON))
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_role("button", name=as_pattern(BULK_UPLOAD_BUTTON))
        ).to_be_visible()

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

    def expect_no_load_failure(self) -> None:
        """Neither fetch fell over, and no write reported one either.

        Asserted rather than assumed: ``handleErrorMessage`` swallows a licensing
        refusal silently, so an empty register on its own would not tell the two
        apart.
        """
        expect(self.page.get_by_text(as_pattern(BOOKS_LOAD_FAILURE))).to_have_count(0)
        expect(
            self.page.get_by_text(as_pattern(CATEGORIES_LOAD_FAILURE))
        ).to_have_count(0)
        expect(self.page.get_by_text(as_pattern(BOOK_SAVE_FAILURE))).to_have_count(0)

    def rows(self) -> Locator:
        return self.page.locator("table tbody tr")

    def row(self, title: str) -> Locator:
        return self.rows().filter(has_text=as_pattern(re.escape(title))).first

    @staticmethod
    def _cell(row: Locator, column: str) -> Locator:
        return row.locator("td").nth(COLUMN_HEADERS.index(column))

    def expect_book(self, title: str, *, author: str | None = None,
                    isbn: str | None = None, category: str | None = None,
                    copies: int | None = None,
                    total_copies: int | None = None) -> None:
        """One row, cell by cell, against values only the server could supply.

        The authors are joined rows, the category is the genre the book was filed
        under and the copy count is ``available_copies_count`` computed over
        ``BookCopy`` — so a row that matches them can only have rendered this
        branch's ``GET /books/`` answer, not anything the browser held onto.
        """
        row = self.row(title)
        expect(row).to_be_visible(timeout=25_000)
        expect(self._cell(row, "Title")).to_have_text(
            as_pattern(rf"^\s*{re.escape(title)}\s*$")
        )
        if author:
            expect(self._cell(row, "Author(s)")).to_contain_text(
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
            cell = self._cell(row, "Copies Available")
            if copies == 0:
                # A zero renders as the words "Out of stock", never as a digit.
                expect(cell).to_contain_text(as_pattern(OUT_OF_STOCK))
            else:
                held = copies if total_copies is None else total_copies
                expect(cell).to_contain_text(
                    as_pattern(rf"{copies}\s*/\s*{held}\s+available")
                )

    def expect_book_absent(self, title: str, timeout_ms: int = 25_000) -> None:
        expect(
            self.rows().filter(has_text=as_pattern(re.escape(title)))
        ).to_have_count(0, timeout=timeout_ms)

    def expect_total(self, count: int, timeout_ms: int = 25_000) -> None:
        """The "N books total" badge beside the category heading.

        Rendered from ``total_count`` — the server's count of everything matching
        the current filter, not of the rows on this page — so it is the honest
        witness that a filter round-tripped.
        """
        noun = "book" if count == 1 else "books"
        expect(
            self.page.get_by_text(as_pattern(rf"{count}\s+{noun}\s+total")).first
        ).to_be_visible(timeout=timeout_ms)

    # ───────────────────────── filters ───────────────────────────

    def search(self, term: str) -> None:
        """Type into the search box; the fetch fires 500 ms after the last key."""
        self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER)).first.fill(term)

    def reset_filters(self) -> None:
        self.click_button(RESET_FILTER_BUTTON)

    def expect_search_value(self, term: str) -> None:
        expect(
            self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER)).first
        ).to_have_value(term)

    # ───────────────────────── writes ────────────────────────────

    def add_book(self, *, title: str, isbn: str, authors: str, publisher: str,
                 category: str, published_date: str, pages: int,
                 description: str) -> None:
        """Catalogue a new book through the "Add Book" dialog.

        ``published_date`` is ISO (``YYYY-MM-DD``) — the same notation the picker
        itself renders, so it is typed verbatim and committed by clicking the
        panel cell.
        """
        self.click_button(ADD_BOOK_BUTTON)
        dialog = self._book_dialog()
        expect(
            dialog.get_by_text(as_pattern(ADD_BOOK_DIALOG_TITLE)).first
        ).to_be_visible(timeout=25_000)

        # First, always: see the trap in the module docstring.
        self._choose_category(dialog, category)
        self._fill_book_fields(
            dialog,
            title=title,
            isbn=isbn,
            authors=authors,
            publisher=publisher,
            published_date=published_date,
            pages=pages,
            description=description,
        )
        self._upload_cover(dialog)

        self._expect_form_intact(dialog, title)
        dialog.get_by_role("button", name=as_pattern(SUBMIT_ADD_BOOK)).first.click()
        self._expect_saved(BOOK_ADDED_TOAST)

    def edit_book(self, title: str, *, new_title: str | None = None,
                  category: str, description: str | None = None,
                  pages: int | None = None) -> None:
        """Correct a catalogued book through the row menu's "Edit Book".

        ``category`` is required even when it is not being changed: re-picking it
        is what proves the dialog's category list has arrived, and until it has,
        every keystroke is at risk of the reset described in the module
        docstring.
        """
        self._click_row_action(title, EDIT_BOOK_ACTION)
        dialog = self._book_dialog()
        expect(
            dialog.get_by_text(as_pattern(EDIT_BOOK_DIALOG_TITLE)).first
        ).to_be_visible(timeout=25_000)

        self._choose_category(dialog, category)
        self._fill_book_fields(
            dialog,
            title=new_title,
            description=description,
            pages=pages,
        )

        if new_title is not None:
            self._expect_form_intact(dialog, new_title)
        dialog.get_by_role("button", name=as_pattern(SUBMIT_UPDATE_BOOK)).first.click()
        self._expect_saved(BOOK_UPDATED_TOAST)

    def add_copies(self, title: str, *, copies: int, location: str,
                   condition: str = "New") -> None:
        """Put physical copies of a catalogued book on the shelf.

        ``BookService.create_book`` writes no copies of its own, so a freshly
        catalogued book reads "Out of stock" until this runs.
        """
        self._click_row_action(title, ADD_COPIES_ACTION)
        dialog = self._copies_dialog()
        expect(dialog).to_be_visible(timeout=25_000)

        dialog.get_by_placeholder(as_pattern(NUM_COPIES_PLACEHOLDER)).first.fill(
            str(copies)
        )
        dialog.get_by_placeholder(
            as_pattern(PHYSICAL_LOCATION_PLACEHOLDER)
        ).first.fill(location)
        self._labeled_group(dialog, PHYSICAL_CONDITION_LABEL).get_by_role(
            "combobox"
        ).first.click()
        self.page.get_by_role(
            "option", name=as_pattern(rf"^\s*{re.escape(condition)}\s*$")
        ).first.click()

        dialog.get_by_role("button", name=as_pattern(SUBMIT_COPIES)).first.click()
        self.expect_toast(COPIES_ADDED_TOAST, timeout_ms=25_000)
        expect(dialog).to_have_count(0, timeout=15_000)

    def delete_book(self, title: str) -> None:
        """Withdraw a book, confirming the antd modal that names it."""
        self._click_row_action(title, DELETE_BOOK_ACTION)
        modal = self.page.locator(".ant-modal").filter(
            has_text=as_pattern(DELETE_MODAL_MARKER)
        ).first
        expect(modal).to_be_visible(timeout=25_000)
        # The confirmation names the book, so a mis-aimed row menu fails here
        # rather than by deleting somebody else's record.
        expect(modal).to_contain_text(as_pattern(re.escape(title)))
        modal.get_by_role(
            "button", name=as_pattern(DELETE_MODAL_CONFIRM)
        ).first.click()
        self.expect_toast(BOOK_DELETED_TOAST, timeout_ms=25_000)
        self.expect_book_absent(title)

    # ───────────────────────── internals ─────────────────────────

    def _book_dialog(self) -> Locator:
        """The add/edit dialog, scoped by the one string only it carries."""
        return self.page.get_by_role("dialog").filter(
            has_text=as_pattern(BOOK_DIALOG_MARKER)
        ).first

    def _copies_dialog(self) -> Locator:
        return self.page.get_by_role("dialog").filter(
            has_text=as_pattern(COPIES_DIALOG_MARKER)
        ).first

    @staticmethod
    def _labeled_group(scope: Locator, label: re.Pattern[str]) -> Locator:
        """The ``<div>`` wrapping one field's bare ``<label>`` and its control.

        Every field in these dialogs is laid out as
        ``<div class="space-y-2"><label>…</label><control/></div>`` with no
        ``for`` attribute, so ``get_by_label`` never binds and the label's parent
        is the only reliable anchor (the same reason
        ``BasePage.select_option_by_label`` exists).
        """
        return scope.locator("label").filter(has_text=label).first.locator("xpath=..")

    def _choose_category(self, dialog: Locator, category: str) -> None:
        """Pick the genre — and, in doing so, wait for the form to settle.

        Opening the select and waiting for ``category`` to be offered is the
        guard described in the module docstring: the option cannot exist until
        ``GET /book/categories/`` has resolved, and the form's self-reset fires
        on that same resolution. Everything typed afterwards therefore survives.
        """
        self._labeled_group(dialog, CATEGORY_LABEL).get_by_role(
            "combobox"
        ).first.click()
        option = self.page.get_by_role(
            "option", name=as_pattern(rf"^\s*{re.escape(category)}\s*$")
        ).first
        expect(option).to_be_visible(timeout=30_000)
        option.click()

    def _fill_book_fields(self, dialog: Locator, *, title: str | None = None,
                          isbn: str | None = None, authors: str | None = None,
                          publisher: str | None = None,
                          published_date: str | None = None,
                          pages: int | None = None,
                          description: str | None = None) -> None:
        if title is not None:
            dialog.get_by_placeholder(as_pattern(TITLE_PLACEHOLDER)).first.fill(title)
        if isbn is not None:
            dialog.get_by_placeholder(as_pattern(ISBN_PLACEHOLDER)).first.fill(isbn)
        if authors is not None:
            dialog.get_by_placeholder(
                as_pattern(AUTHORS_PLACEHOLDER)
            ).first.fill(authors)
        if publisher is not None:
            dialog.get_by_placeholder(
                as_pattern(PUBLISHER_PLACEHOLDER)
            ).first.fill(publisher)
        if published_date is not None:
            picker = self._labeled_group(
                dialog, PUBLICATION_DATE_LABEL
            ).locator(".ant-picker input").first
            self.commit_date(picker, published_date, display_format="%Y-%m-%d")
        if pages is not None:
            self._labeled_group(dialog, PAGE_COUNT_LABEL).locator(
                "input"
            ).first.fill(str(pages))
        if description is not None:
            self._labeled_group(dialog, DESCRIPTION_LABEL).locator(
                "textarea"
            ).first.fill(description)

    def _upload_cover(self, dialog: Locator) -> None:
        """Attach the cover the form refuses to submit without.

        ``#fileInput`` is ``class="hidden"`` and driven by a ``<label for>``; the
        file is handed to it directly as an in-memory payload, and the preview
        ``<Image alt="Book Cover">`` appearing is what proves ``FileReader``
        finished and ``formData.thumbnail`` is set.
        """
        dialog.locator("#fileInput").set_input_files(
            files=[{
                "name": "test-book-cover.png",
                "mimeType": "image/png",
                "buffer": COVER_IMAGE,
            }]
        )
        expect(
            dialog.get_by_role("img", name=as_pattern(COVER_PREVIEW_ALT)).first
        ).to_be_visible(timeout=15_000)

    def _expect_form_intact(self, dialog: Locator, title: str) -> None:
        """The title survived to the moment of submitting.

        This is the reset trap made visible. If ``categories`` changed identity
        after the typing started, ``CatalogueModal`` will have re-seeded
        ``formData`` and the title box is empty — ``handleSubmit`` then raises
        "Please fill out all the fields" and never reaches the network. Failing
        here says exactly that, instead of leaving the caller to puzzle over a
        row that never appeared.
        """
        expect(
            dialog.get_by_placeholder(as_pattern(TITLE_PLACEHOLDER)).first
        ).to_have_value(title, timeout=10_000)

    def _expect_saved(self, toast: re.Pattern[str]) -> None:
        """The write reported success, and the dialog closed behind it."""
        expect(self.page.get_by_text(as_pattern(MISSING_FIELDS_TOAST))).to_have_count(0)
        self.expect_toast(toast, timeout_ms=30_000)
        expect(self._book_dialog()).to_have_count(0, timeout=15_000)

    def _click_row_action(self, title: str, action: re.Pattern[str]) -> None:
        """Open one row's antd dropdown and pick an item from it.

        The menu is portalled to the end of the body and antd leaves every
        dropdown it has ever opened mounted-but-hidden, so the *visible* one is
        the only safe scope — a page-wide match would resolve into a menu
        belonging to a row that is no longer even on screen.
        """
        row = self.row(title)
        expect(row).to_be_visible(timeout=25_000)
        row.locator("td").nth(ACTIONS_COLUMN).get_by_role("button").first.click()
        menu = self.page.locator(".ant-dropdown:visible").last
        expect(menu).to_be_visible(timeout=15_000)
        menu.get_by_role("button", name=as_pattern(action)).first.click()
