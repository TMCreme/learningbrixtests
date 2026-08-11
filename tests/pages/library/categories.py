"""Library → Book Categories page object (/module/categories).

One screen, one table: "Manage Category" over ``GET /book/categories/``, with a
client-side "Search category by name" box, an "Add Category" button, and a
per-row kebab offering "Edit category" / "Delete category"
(``smsfrontend/src/app/module/categories/page.tsx`` plus its ``components/``).

Three things about this screen that are not obvious from the route:

* **The backend capitalises every category name it stores.**
  ``BookCategoryService.create_book_category`` does
  ``name.strip().capitalize()`` — and ``update_book_category`` does the same —
  so a category typed as "TEST Fiction 3f9a1c" comes back from the API, and is
  therefore rendered, as "Test fiction 3f9a1c". Every name matcher here is
  built with ``re.I`` for that reason; comparing a rendered cell against the
  caller's own string with ``to_have_text(str)`` would fail on the case alone.
* **A SchoolAdmin must have picked a branch first.** ``fetchCategories``'s
  mount effect returns early for a SchoolAdmin/SuperAdmin whose
  ``useBranchStore`` is empty, so ``isLoading`` never clears and the screen
  stays on ``BookCategoriesLoader`` forever — not an empty table, and not an
  error. ``GET /book/categories/`` answers 400 BRANCH_ID_REQUIRED for that role
  without the query parameter anyway. Call
  ``BranchesPage.select_branch(...)`` before opening this page.
* **The kebab menu is an antd ``Dropdown``, and antd leaves each one it has
  opened mounted-but-hidden in a portal.** The menu items are plain
  ``<button>``s, so a page-wide ``get_by_role("button", name="Edit category")``
  can resolve to a *previous* row's closed menu. ``_menu_item`` therefore scopes
  to the dropdown that is actually visible.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage

PAGE_HEADING = re.compile(r"^\s*Manage Category\s*$", re.I)
# The header's second line. Its wording talks about "subjects" — that is the
# copy the page actually ships, not a typo in this file.
PAGE_SUBHEADING = re.compile(
    r"Easily update subjects to ensure data accuracy and completeness", re.I
)

# The sidebar entry (SideNavigation/nav-config.tsx, "Library Module" section).
# The section is ``branchOnly``, so for a SchoolAdmin it only appears once a
# branch has been selected — the same prerequisite the table itself has.
NAV_LIBRARY_SECTION = re.compile(r"^\s*Library Module\s*$", re.I)
NAV_CATEGORIES = re.compile(r"^\s*Book Categories\s*$", re.I)

SEARCH_FIELD = re.compile(r"^\s*Search category by name\s*$", re.I)

# The panel the table sits in, and the pill beside it counting the *whole*
# branch's categories (page.tsx prints `categories.length`, not the filtered
# length, and pluralises to "category" at one).
CATEGORIES_PANEL = re.compile(r"^\s*All Categories\s*$", re.I)
CATEGORY_COUNT = re.compile(r"^\s*\d+\s+categor(y|ies)\s*$", re.I)

# Rendered only for a role holding ("manage", …) — page.tsx puts both the
# toolbar button and every row kebab behind the same ``isManage`` flag.
ADD_CATEGORY_TRIGGER = re.compile(r"^\s*Add Category\s*$", re.I)

# The Radix dialog CategoryModal renders for each mode (its DialogTitle).
ADD_CATEGORY_MODAL = re.compile(r"^\s*Add Category\s*$", re.I)
EDIT_CATEGORY_MODAL = re.compile(r"^\s*Edit Category\s*$", re.I)

# Both fields *are* label-associated here (``<label htmlFor>`` over an Input
# that forwards its id), which is unusual in this app; the alternation keeps the
# placeholder fallback in BasePage.fill_labeled working if that ever drops.
NAME_FIELD = re.compile(r"^\s*Category\s*$|^\s*Enter name of category\s*$", re.I)
DESCRIPTION_FIELD = re.compile(
    r"^\s*Description\s*$|^\s*Add additional comments\s*$", re.I
)

SAVE_BUTTON = re.compile(r"^\s*Save Data\s*$", re.I)
DISCARD_BUTTON = re.compile(r"^\s*Discard\s*$", re.I)

# Row kebab menu (antd Dropdown; the trigger is an icon-only antd Button with no
# accessible name, so it is reached as the row's last button).
EDIT_CATEGORY_ITEM = re.compile(r"^\s*Edit category\s*$", re.I)
DELETE_CATEGORY_ITEM = re.compile(r"^\s*Delete category\s*$", re.I)

# The antd confirmation Modal, its OK label, and the sentence it frames the
# category's name in.
DELETE_CATEGORY_MODAL = re.compile(r"^\s*Delete Category\s*$", re.I)
DELETE_CONFIRM_BUTTON = re.compile(r"^\s*Delete\s*$", re.I)
DELETE_WARNING = re.compile(r"Are you sure you want to delete", re.I)

CATEGORY_CREATED_TOAST = re.compile(r"Category added successfully", re.I)
CATEGORY_UPDATED_TOAST = re.compile(r"Category updated successfully", re.I)
CATEGORY_DELETED_TOAST = re.compile(r"Category deleted successfully", re.I)

# EmptyState / PageError, both mounted by page.tsx with these exact strings.
EMPTY_TITLE = re.compile(r"^\s*No categories found\s*$", re.I)
EMPTY_DESCRIPTION = re.compile(r"^\s*Try adjusting your search terms\s*$", re.I)
LOAD_FAILURE_TITLE = re.compile(r"^\s*Failed to load categories\s*$", re.I)

# The table's columns, in render order (page.tsx <TableHeader>). The fifth cell
# holds the row kebab and carries no data.
CATEGORY_COLUMNS = {
    "name": 0,
    "date_added": 1,
    "last_modified": 2,
    "description": 3,
}

# The same header row read as text, in render order. The fifth <th> is the
# empty one above the row kebab, so it is matched as blank rather than skipped —
# a column silently appearing or moving is exactly what this pins.
CATEGORY_COLUMN_HEADERS = (
    re.compile(r"^\s*Category\s*$", re.I),
    re.compile(r"^\s*Date Added\s*$", re.I),
    re.compile(r"^\s*Last Modified\s*$", re.I),
    re.compile(r"^\s*Description\s*$", re.I),
    re.compile(r"^\s*$"),
)

# page.tsx's ``formatDate`` reads the API's "dd-mm-yy HH:MM:SS" (the
# json_encoders on BookCategoryBase) and re-prints it with
# toLocaleDateString("en-US", {year: "numeric", month: "long", day: "numeric"}),
# e.g. "August 9, 2026".
RENDERED_DATE = re.compile(r"^\s*[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s*$")


class CategoriesPage(BasePage):
    URL = "/module/categories"

    def open(self) -> "CategoriesPage":
        super().open()
        self.expect_loaded()
        return self

    def open_from_nav(self) -> "CategoriesPage":
        """Reach the screen the way a user does — the sidebar entry.

        A demo video has to show how someone gets to the module rather than
        teleport there, so recorded tests navigate with this; ``open`` stays the
        deep link for everything else. Falls back to the deep link when the
        sidebar is collapsed (narrow viewports), since the workspace is the
        point, not the way in.
        """
        link = self.page.get_by_role("link", name=NAV_CATEGORIES).first
        if link.count():
            link.click()
            self.page.wait_for_url(re.compile(r"/module/categories"), timeout=20_000)
            self.expect_loaded()
            return self
        return self.open()

    def expect_nav_entry(self) -> None:
        """The Library section is on offer, and Book Categories inside it.

        The section title is asserted too, so "the link is there" cannot pass
        off the back of a half-rendered sidebar. Note the section is
        ``branchOnly``: for a SchoolAdmin neither is drawn until a branch has
        been selected.
        """
        expect(
            self.page.get_by_text(NAV_LIBRARY_SECTION).first
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_role("link", name=NAV_CATEGORIES).first
        ).to_be_visible(timeout=25_000)

    def expect_column_headers(self) -> None:
        """Assert the header row cell by cell, pinning the column order.

        ``cell()`` addresses columns positionally (``CATEGORY_COLUMNS``), so a
        column that moved would otherwise make every later assertion read the
        wrong value rather than fail.
        """
        cells = self.page.locator("table thead tr").first.locator("th")
        expect(cells).to_have_count(len(CATEGORY_COLUMN_HEADERS))
        for index, header in enumerate(CATEGORY_COLUMN_HEADERS):
            expect(cells.nth(index)).to_have_text(header)

    def expect_loaded(self) -> None:
        """Wait for the register itself, not merely for the route.

        The heading is asserted first, then the search box: for a SchoolAdmin
        who has not selected a branch this page never leaves its skeleton
        loader, and waiting on a control that only the loaded screen renders is
        what turns that into a legible failure.
        """
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
            timeout=20_000
        )
        expect(self.page.get_by_placeholder(SEARCH_FIELD).first).to_be_visible(
            timeout=20_000
        )
        self.expect_no_load_failure()

    # ────────────────────────── categories ─────────────────────────

    def search(self, query: str) -> None:
        """Type into the search box. Filters the already-fetched list client-side."""
        self.page.get_by_placeholder(SEARCH_FIELD).first.fill(query)

    def find_row(self, name: str) -> Locator:
        """The register row for ``name``.

        Matched case-insensitively because the backend capitalises the name it
        stores (see the module docstring).
        """
        return (
            self.page.get_by_role("row")
            .filter(has=self.page.get_by_text(_exact(name)))
            .first
        )

    def cell(self, name: str, column: str) -> Locator:
        """One cell of a category's row, by column key (``CATEGORY_COLUMNS``)."""
        return self.find_row(name).get_by_role("cell").nth(CATEGORY_COLUMNS[column])

    def count_badge(self) -> Locator:
        """The "<n> categories" pill beside the panel title."""
        return self.page.get_by_text(CATEGORY_COUNT).first

    def create_category(self, *, name: str, description: str) -> None:
        """Add a category from the "Add Category" dialog.

        Both fields are free text and neither is validated client-side — the
        form has no disabled state to wait on — so the success toast is what
        says the POST was accepted. Ends with the register refetched and
        ``name`` typed into the search box, so ``find_row`` can be called
        straight after.
        """
        self.click_button(ADD_CATEGORY_TRIGGER)

        modal = self._modal(ADD_CATEGORY_MODAL)
        expect(modal).to_be_visible(timeout=10_000)
        self._fill_in(modal, NAME_FIELD, name)
        self._fill_in(modal, DESCRIPTION_FIELD, description)
        modal.get_by_role("button", name=SAVE_BUTTON).first.click()

        self.expect_toast(CATEGORY_CREATED_TOAST, timeout_ms=20_000)
        expect(modal).to_have_count(0, timeout=10_000)

        self.search(name)
        expect(self.find_row(name)).to_be_visible(timeout=20_000)

    def edit_category(
        self, *, name: str, new_name: str | None = None, description: str | None = None
    ) -> None:
        """Rename a category and/or rewrite its description from the row menu.

        The dialog opens pre-filled from the row, so a caller may change either
        field alone. Clears the search box first: the box filters the rendered
        list, and a stale filter would hide the row this has to reach.
        """
        self.search("")
        self._open_row_menu(name)
        self._menu_item(EDIT_CATEGORY_ITEM).click()

        modal = self._modal(EDIT_CATEGORY_MODAL)
        expect(modal).to_be_visible(timeout=10_000)
        if new_name is not None:
            self._fill_in(modal, NAME_FIELD, new_name)
        if description is not None:
            self._fill_in(modal, DESCRIPTION_FIELD, description)
        modal.get_by_role("button", name=SAVE_BUTTON).first.click()

        self.expect_toast(CATEGORY_UPDATED_TOAST, timeout_ms=20_000)
        expect(modal).to_have_count(0, timeout=10_000)

    def delete_category(self, *, name: str) -> None:
        """Delete a category from the row menu, confirming the antd modal.

        The confirmation names the category it is about to remove, so that is
        asserted before confirming — it is driven from ``categoryToDelete``
        state that a mis-aimed row menu would have left pointing elsewhere.
        Ends with the row gone from the refetched register.
        """
        self.search("")
        self._open_row_menu(name)
        self._menu_item(DELETE_CATEGORY_ITEM).click()

        modal = self._modal(DELETE_CATEGORY_MODAL)
        expect(modal).to_be_visible(timeout=10_000)
        expect(modal.get_by_text(DELETE_WARNING).first).to_be_visible(timeout=10_000)
        expect(modal.get_by_text(_exact(name)).first).to_be_visible(timeout=10_000)

        modal.get_by_role("button", name=DELETE_CONFIRM_BUTTON).first.click()

        self.expect_toast(CATEGORY_DELETED_TOAST, timeout_ms=20_000)
        expect(modal).to_be_hidden(timeout=10_000)
        expect(self.find_row(name)).to_have_count(0, timeout=20_000)

    def expect_no_load_failure(self) -> None:
        """Fail loudly when the screen is showing PageError instead of the table.

        Without this, a "no row for X" assertion passes just as happily on a
        register whose GET was refused as on one that genuinely holds no such
        category.
        """
        expect(self.page.get_by_text(LOAD_FAILURE_TITLE)).to_have_count(0)

    # ────────────────────────── internals ──────────────────────────

    def _modal(self, title: re.Pattern[str]) -> Locator:
        """Scope to one dialog by its title.

        Covers both flavours on this screen: the Radix ``CategoryModal`` (which
        unmounts when closed, hence the ``to_have_count(0)`` waits above) and
        the antd delete ``Modal`` (which stays mounted-but-hidden, hence
        ``to_be_hidden``).

        Anchored on the *heading element* carrying the title rather than on
        ``filter(has_text=...)``. Playwright tests a ``has_text`` pattern against
        the whole subtree's text, and every title here is anchored ``^…$`` — so
        against a dialog reading "Add Category" + its description + both field
        labels + both buttons, the match can never succeed and the modal reads as
        "element(s) not found" while it is plainly open. ``has=`` asks instead
        for a descendant whose own text is the title, which is the ``<h2>``.
        """
        return self.page.get_by_role("dialog").filter(
            has=self.page.get_by_text(title)
        ).first

    def _fill_in(self, modal: Locator, field: re.Pattern[str], value: str) -> None:
        """Fill a field inside one specific dialog.

        Deliberately not ``BasePage.fill_labeled(..., in_dialog=True)``: that
        scopes to *every* dialog in the DOM, and the delete Modal antd leaves
        behind would put a hidden competitor in front of the one being driven.
        """
        loc = modal.get_by_label(field).first
        if loc.count() == 0:
            loc = modal.get_by_placeholder(field).first
        loc.fill(value)

    def _open_row_menu(self, name: str) -> None:
        """Open the per-row actions menu for ``name``.

        The trigger is an icon-only antd Button with no accessible name, and it
        is the only button in the row, so it is reached positionally.
        """
        row = self.find_row(name)
        expect(row).to_be_visible(timeout=20_000)
        row.get_by_role("button").last.click()

    def _menu_item(self, label: re.Pattern[str]) -> Locator:
        """One item of the kebab menu that is currently open.

        antd renders each Dropdown into its own portal and keeps it mounted once
        opened, so the menu is anchored on the visible ``.ant-dropdown`` rather
        than page-wide. The items themselves are plain ``<button>``s carrying
        the click handler, so the button — not the wrapping ``menuitem`` — is
        what gets clicked.
        """
        menu = self.page.locator(".ant-dropdown:visible").last
        expect(menu).to_be_visible(timeout=10_000)
        return menu.get_by_role("button", name=label).first


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
