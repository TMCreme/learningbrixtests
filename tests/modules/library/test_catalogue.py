"""Library → Catalogue — the book register (`catalogue`).

Where this module lives
    ``/module/catalogue`` (``smsfrontend/src/app/module/catalogue/page.tsx``).
    The page picks a view by role: a SchoolAdmin (or an Admin/librarian holding
    a ``catalogue`` permission) gets ``views/AdminCatalogueView.tsx`` — the
    "Manage Books" workspace, a paginated Title / Author(s) / ISBN / Category /
    Copies Available table over ``GET /books/``, with a search box, a category
    filter fed by ``GET /book/categories/``, "Add Book", "Bulk Upload" and a
    per-row menu for edit / delete / add-copies / remove-copies. Everyone else
    gets the read-only ``views/StudentCatalogueView.tsx``.

Read-only path: a Teacher of the ``library_and_community`` school
(``test_teacher_browses_the_library_catalogue``). ``shouldShowAdminView()`` in
``page.tsx`` matches only "schooladmin", "admin" and a role name containing
"library"/"librarian", so a Teacher falls through to the reader-facing "Library
Books" view — the same table, with the toolbar's write half and the row menu
left undrawn. See the section comment above that test.

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack is the
floor case the pack builder can actually produce — the locked "people" and
"governance" groups and nothing else, so no ``catalogue``
(``test_catalogue_denied_for_school_admin_when_module_disabled``).

Where the denial actually lives — and where it does NOT
    Not in the sidebar, not in the middleware, and not in either of the page's
    two guards. All three exempt this role before the pack is ever consulted:

    * ``src/middleware.ts`` skips its module enforcement outright for a
      SchoolAdmin ("SchoolAdmin bypasses: governance pages … are not
      feature-flag modules"), so the route is never turned away before it mounts.
    * ``useModuleGuard("catalogue")`` — which ``page.tsx`` does call — returns
      ``true`` for a SchoolAdmin *before* it reads the ``schoolModules`` cookie,
      so its ``hasModuleAccess === false`` branch (which would render ``null``
      and push /auth/no-access) is unreachable for this role.
    * ``usePermissionGuard("catalogue")`` — called by both ``page.tsx`` and
      ``AdminCatalogueView`` — returns early on ``isSchoolAdminRole(role)``, in
      the effect and in the ``hasAccess`` memo alike.

    What denies them is the backend. Every route in ``api/routes/book.py``,
    ``book_copy.py`` and ``book_statistics.py`` carries
    ``Depends(has_permission(<read|manage>, "catalogue"))``, that dependency is
    solved before any row is looked up, and the feature-pack half of
    ``utils.permissions.has_permission`` answers **403 "Feature not available in
    your plan"** for a school whose pack omits the module named in it.

    Unlike the audit log — whose routes are gated on a *different* module than
    the frontend gates the page on — the gate module here is ``catalogue``
    itself, the same key the feature pack, the nav entry and ``page.tsx`` all
    use. So the pack that omits ``catalogue`` is exactly what produces the 403.

    The UI consequence follows from that 403. ``AdminCatalogueView`` fires
    ``GetBookCategories()`` and ``GetBooks()`` from its mount effect; the axios
    response interceptor in ``src/utils/handleErrorMessage.ts`` recognises the
    "not available in your plan" detail (``shouldRedirectToNoAccess``) and
    performs a hard ``window.location`` redirect to **/auth/no-access**,
    rejecting the promise with ``FeatureNotAvailableError`` — which the view's
    own ``catch`` → ``handleErrorMessage`` then deliberately swallows rather than
    toasting. So the landing page, not a toast and not an empty table, is the
    denial surface this test waits for.

Deliberately *not* asserted: that the sidebar hides "Catalogue"
    ``nav-config.tsx`` gives that entry ``permission: "catalogue"``, and
    ``SideNavigation.canShowItem`` returns on the permission check *before* the
    module gate ("Permission check takes priority — having the permission
    implies the module is available"). The seeded SchoolAdmin holds
    ``("manage", "catalogue")`` (``db/repository/permissions.py``), so the entry
    renders whatever the pack says. Its presence says nothing about this
    school's licence, so it is not asserted either way.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import TEST_PREFIX, run_tag
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.library.catalogue import REQUEST_BOOK_BUTTON, CataloguePage
from tests.pages.library.manage_books import ManageBooksPage
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

CATALOGUE_MODULE = "catalogue"

# config/module_catalog.py's route for this module.
CATALOGUE_ROUTE = "catalogue"

DENIED_SCENARIO = "minimal"

# The role whose permissions are checked against the pack.
SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# The two denials utils/permissions.py can answer with. A school that holds the
# permission but not the module gets the first; one that holds neither gets the
# second. Either is a correct denial — anything else is not.
DENIAL_DETAIL = re.compile(
    r"Feature not available in your plan"
    r"|You do not have permission to perform this action",
    re.I,
)

# Where the frontend sends a user it has decided is not allowed in, and the copy
# it greets them with (src/app/auth/no-access/page.tsx).
NO_ACCESS_URL = re.compile(r"/auth/no-access")
ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)

# ── the catalogue workspace's own chrome, none of which may reach this admin ──
# src/app/module/catalogue/views/AdminCatalogueView.tsx and its components/.
CATALOGUE_HEADING = re.compile(r"^\s*Manage Books\s*$", re.I)
CATALOGUE_SUBHEADING = re.compile(r"Easily update book details", re.I)
CATALOGUE_SEARCH_FIELD = re.compile(r"Search book by id, name or ISBN", re.I)
CATALOGUE_CATEGORY_FILTER = re.compile(r"^\s*All Categories\s*$", re.I)
ADVANCED_SEARCH_BUTTON = re.compile(r"^\s*Advanced Search\s*$", re.I)
RESET_FILTER_BUTTON = re.compile(r"^\s*Reset Filter\s*$", re.I)
ADD_BOOK_BUTTON = re.compile(r"^\s*Add Book\s*$", re.I)
BULK_UPLOAD_BUTTON = re.compile(r"^\s*Bulk Upload\s*$", re.I)
CATALOGUE_EMPTY_STATE = re.compile(r"No books available in the catalogue", re.I)
# The toast the view would raise if the 403 were treated as an ordinary failure
# rather than as a licensing refusal (handleErrorMessage's fallback text).
CATALOGUE_LOAD_FAILURE = re.compile(r"Failed to fetch books", re.I)
# The read-only view the same route renders for every non-admin role. A
# SchoolAdmin must not be quietly demoted into it either.
STUDENT_VIEW_HEADING = re.compile(r"^\s*Library Books\s*$", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_catalogue_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With the module off the pack, a SchoolAdmin gets no book catalogue at all."""
    ctx = provisioned_school
    if CATALOGUE_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {CATALOGUE_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had library rights anyway", which would make the 403s vacuous.
    # db/repository/permissions.py seeds this role with ("manage", "catalogue"),
    # and has_permission lets manage stand in for read — so the permission half
    # of the gate passes outright for every route asserted below.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert CATALOGUE_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{CATALOGUE_MODULE!r} permission, which is the one every book route is "
        f"gated on. This test would then be asserting a denial the role gets for "
        f"free. Re-point it at the feature pack only, or fix the seed in "
        f"newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{CATALOGUE_MODULE!r} proves nothing about the gate. Provisioning "
        f"phase A assigns one — check that it did."
    )
    licensed = body.get("modules") or []
    assert CATALOGUE_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {CATALOGUE_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every catalogue route is refused ────────────────
    #
    # Both halves of the gate are covered — the reads the register performs
    # (has_permission("read", "catalogue")) and the writes its toolbar and row
    # menu perform (has_permission("manage", "catalogue")). The book id is
    # deliberately arbitrary: has_permission is a route-level dependency, solved
    # before the path params are used and long before any row is looked up, so a
    # 404 here would itself be the failure. For the same reason the create body
    # below never has to be creatable — but it carries the TEST prefix anyway, so
    # that a regression which *did* let it through leaves a sweepable row.
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"&branch_id={branch_id}" if branch_id else ""

    refusals = {
        # What the register itself calls on mount, with and without the branch
        # scope catalogueHandler appends for a SchoolAdmin who selected a branch.
        "list": api.get(f"/books/?skip=0&limit=25{branch_query}", token=token),
        "list_unscoped": api.get("/books/?skip=0&limit=25", token=token),
        # The row's title link → /module/catalogue/{id} and its copies page.
        "detail": api.get("/books/1", token=token),
        "copies": api.get("/book/copies/1/copies", token=token),
        # The library statistics tile reads the same licence.
        "statistics": api.get("/book-statistics/total-books", token=token),
        # …and the manage half: "Add Book", the row menu's delete.
        "create": api.post(
            "/books/create/",
            token=token,
            json={
                "title": f"{TEST_PREFIX} Denied Book {run_tag()}",
                "category_id": 1,
                "school_branch_id": branch_id or 1,
            },
        ),
        "delete": api.delete("/books/1/delete/", token=token),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{CATALOGUE_MODULE!r}, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a catalogue in front of them ────────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # A SchoolAdmin is exempt from the middleware gate, from useModuleGuard and
    # from usePermissionGuard, so this route really does mount and really does
    # start fetching — and the axios interceptor turns the refusal into a hard
    # redirect (see the module docstring). Waiting for the URL is therefore also
    # what stops the "workspace is absent" assertions below from passing merely
    # because the page had not finished loading.
    goto_module(page, frontend_base_url, CATALOGUE_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the register survives the redirect: not its heading, not its
    # toolbar, not a single row — and not the read-only student view either,
    # which would mean the app had silently demoted a SchoolAdmin instead of
    # denying them. The "Failed to fetch books" toast is asserted absent for the
    # same reason as the audit unit: raising it would mean a licensing refusal
    # had been handled as an ordinary fetch error.
    expect(page.get_by_role("heading", name=as_pattern(CATALOGUE_HEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(CATALOGUE_SUBHEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(STUDENT_VIEW_HEADING))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(CATALOGUE_SEARCH_FIELD))).to_have_count(0)
    expect(page.get_by_text(as_pattern(CATALOGUE_CATEGORY_FILTER))).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(ADVANCED_SEARCH_BUTTON))
    ).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(RESET_FILTER_BUTTON))
    ).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(ADD_BOOK_BUTTON))).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(BULK_UPLOAD_BUTTON))
    ).to_have_count(0)
    expect(page.get_by_text(as_pattern(CATALOGUE_EMPTY_STATE))).to_have_count(0)
    expect(page.get_by_text(as_pattern(CATALOGUE_LOAD_FAILURE))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)


# ════════════ read-only path: a teacher browses the library shelves ══════════
#
# Constants below are prefixed rather than sharing the negative section's names:
# this module file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# Why a Teacher gets a *different* screen from the same route
#     ``page.tsx``'s ``shouldShowAdminView()`` returns true only for a role name
#     of "schooladmin", for "admin" holding a ``catalogue`` permission, or for one
#     whose name contains "library"/"librarian". "teacher" matches none of them,
#     so the route renders ``views/StudentCatalogueView.tsx`` — the reader-facing
#     "Library Books" table. That is the whole of this unit: the catalogue as a
#     member of staff who borrows from the library, not as the person who runs it.
#
# Why the route is reachable at all for this role
#     Both halves of the gate pass. ``db/repository/permissions.py`` seeds the
#     Teacher role with ``("manage", "catalogue")``, which satisfies
#     ``usePermissionGuard("catalogue")`` and every ``has_permission(read,
#     catalogue)`` dependency in ``api/routes/book.py``; and the
#     ``library_and_community`` pack licenses ``catalogue``, which satisfies
#     ``useModuleGuard("catalogue")`` and the feature-pack half of
#     ``utils.permissions.has_permission``. The sidebar's "Library Module" section
#     is ``branchOnly``, but ``SideNavigation.canShowSection`` treats branch state
#     as a SchoolAdmin-only concept, so the entry is offered to a Teacher outright.
#
# What "read-only" means here, precisely
#     Not that the Teacher is denied anything — they hold ``manage``. It is the
#     *view* that authors nothing: ``StudentCatalogueView`` mounts
#     ``CatalogueTableToolbar`` without ``onAddBookClick``/``onBulkUploadClick``,
#     so the toolbar's write half is never drawn, and it renders no row menu at
#     all (no edit, no delete, no add/remove copies). The two row controls it does
#     offer — "Request Book" and "View details" — are a borrowing request and a
#     drill-down, neither of which changes the catalogue. This unit exercises the
#     drill-down and deliberately leaves "Request Book" to the
#     ``requests_and_renewals`` unit, which is what that button belongs to.
#
# Whose shelves the Teacher is shown
#     Their own branch's, and they get no say in it: for any non-admin role
#     ``list_books`` overwrites ``branch_id`` with ``user.school_branch_id``
#     before it queries (``api/routes/book.py``). So the rows below could only
#     have come from the branch provisioning created this account under.
#
# Why the books are seeded over the API
#     Writing them is the librarian's walkthrough — a category, then a book, then
#     its physical copies, all from ``AdminCatalogueView``'s dialogs, and all as a
#     *different role*. That is the ``library.catalogue.manage`` unit's subject,
#     not this one's. Seeding them the same way
#     ``school_provisioning._seed_fee_group`` seeds the fee group the Add Class
#     dialog insists on keeps this walkthrough to the one thing it is about, and
#     keeps the video to the one story it is telling.

VIEW_SCENARIO = "library_and_community"
VIEW_TAG = run_tag()

# Two genres so the category filter has something to narrow *to* and something to
# narrow *away from*. Tagged per run, so a filter's row count is a fact about this
# test's books rather than about whatever else the shared school is carrying.
VIEW_FICTION = f"{TEST_PREFIX} Fiction {VIEW_TAG}"
VIEW_SCIENCE = f"{TEST_PREFIX} Science {VIEW_TAG}"

VIEW_SHELF = "Shelf A-3"

# The term typed into the search box. It appears in exactly one seeded title and
# in no seeded author, ISBN, publisher or description — which is what lets the
# search assertion below demand a total of one.
VIEW_SEARCH_TERM = "Clay Marble"


@dataclass(frozen=True)
class SeededBook:
    """One book on the shelf, and every value the table renders for it."""

    title: str
    author: str
    isbn: str
    category: str
    copies: int
    published_date: str
    pages: int
    description: str


VIEW_BOOKS: tuple[SeededBook, ...] = (
    SeededBook(
        title=f"{TEST_PREFIX} The Clay Marble {VIEW_TAG}",
        author="Minfong Ho",
        isbn="9780374412296",
        category=VIEW_FICTION,
        copies=4,
        published_date="2019-03-14",
        pages=176,
        description="A novel set on a border, seeded for the catalogue unit.",
    ),
    SeededBook(
        title=f"{TEST_PREFIX} Weep Not Child {VIEW_TAG}",
        author="Ngugi wa Thiongo",
        isbn="9780143026242",
        category=VIEW_FICTION,
        copies=2,
        published_date="2018-07-02",
        pages=160,
        description="A second novel in the same genre, seeded for the catalogue unit.",
    ),
    SeededBook(
        title=f"{TEST_PREFIX} Atoms and Elements {VIEW_TAG}",
        author="Aisha Mensah",
        isbn="9780198392675",
        category=VIEW_SCIENCE,
        copies=3,
        published_date="2020-01-20",
        pages=224,
        description="An introduction to matter, seeded for the catalogue unit.",
    ),
)

VIEW_FEATURED = VIEW_BOOKS[0]          # the one the search narrows down to
VIEW_DRILL_DOWN = VIEW_BOOKS[2]        # the one the walkthrough opens in full
VIEW_FICTION_COUNT = sum(1 for b in VIEW_BOOKS if b.category == VIEW_FICTION)
VIEW_SCIENCE_COUNT = sum(1 for b in VIEW_BOOKS if b.category == VIEW_SCIENCE)


class CatalogueSeedError(RuntimeError):
    """A prerequisite could not be seeded, so the shelf would render empty."""


@pytest.fixture
def stocked_library(
    provisioned_school: SchoolContext, api: BackendAPI
) -> tuple[SeededBook, ...]:
    """Put two genres and three books, with copies, on the teacher's branch.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.branches, "provisioning created no branch for this school"

    branch_id = int(ctx.branches[0]["id"])
    token = _view_login(api, ctx.school_admin.email, ctx.school_admin.password)
    category_ids = _view_category_ids(api, token, branch_id=branch_id)

    for book in VIEW_BOOKS:
        _view_seed_book(
            api, token, book,
            branch_id=branch_id,
            category_id=category_ids[book.category],
        )

    _view_assert_teacher_sees_them(api, ctx)
    return VIEW_BOOKS


@pytest.mark.teacher
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="library.catalogue.view.teacher",
    title="Library Catalogue",
    subtitle="Teacher views library catalogue",
)
def test_teacher_browses_the_library_catalogue(
    stocked_library: tuple[SeededBook, ...],
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A teacher opens the library catalogue, searches it, filters it and reads
    one book's full record — and is never offered a way to change any of it.

    Everything asserted is the server's answer rather than the browser's: the
    authors are joined rows, the category is the genre the book was filed under,
    the copy count is ``available_copies_count`` computed over ``BookCopy``, and
    both the search and the category filter are ``GET /books/`` query parameters
    that ``BookService.list_books`` resolves in SQL. So a table that matches them
    can only have rendered this branch's catalogue.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"

    page: Page = demo.page
    catalogue = CataloguePage(page, demo.frontend_base_url)
    teacher = ctx.teacher.full_name

    with demo.step(f"Sign in as {teacher}, a teacher at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.teacher)

    with demo.step("The Library menu is waiting in their sidebar"):
        catalogue.expect_nav_entry()
        catalogue.open_from_sidebar().wait_for_table()
        catalogue.expect_no_load_failure()

    with demo.step("The shelf opens: every book on this campus, with its author, "
                   "ISBN and how many copies are free"):
        catalogue.expect_reader_view()
        catalogue.expect_column_headers()
        catalogue.expect_toolbar()
        catalogue.expect_category_heading()
        for book in stocked_library:
            catalogue.expect_book(
                book.title,
                author=book.author,
                isbn=book.isbn,
                category=book.category,
                copies=book.copies,
            )

    with demo.step(f"Searching for “{VIEW_SEARCH_TERM}” finds the one "
                   f"title that matches"):
        catalogue.search(VIEW_SEARCH_TERM)
        catalogue.expect_total(1)
        catalogue.expect_book(VIEW_FEATURED.title, author=VIEW_FEATURED.author)
        for book in stocked_library:
            if book.title != VIEW_FEATURED.title:
                catalogue.expect_book_absent(book.title)

    with demo.step("Reset Filter puts the whole shelf back"):
        catalogue.reset_filters()
        catalogue.expect_search_value("")
        for book in stocked_library:
            catalogue.expect_book(book.title)

    with demo.step(f"Filtering by genre narrows it to {VIEW_SCIENCE}"):
        catalogue.filter_by_category(VIEW_SCIENCE)
        catalogue.expect_category_heading(VIEW_SCIENCE)
        catalogue.expect_total(VIEW_SCIENCE_COUNT)
        catalogue.expect_book(VIEW_DRILL_DOWN.title, category=VIEW_DRILL_DOWN.category)
        for book in stocked_library:
            if book.category != VIEW_SCIENCE:
                catalogue.expect_book_absent(book.title)

    with demo.step(f"Opening “{VIEW_DRILL_DOWN.title}” shows the full "
                   f"record and how many copies are on the shelf"):
        details = catalogue.open_details(VIEW_DRILL_DOWN.title)
        details.expect_loaded(VIEW_DRILL_DOWN.title)
        details.expect_fields()
        details.expect_value(VIEW_DRILL_DOWN.author)
        details.expect_value(VIEW_DRILL_DOWN.isbn)
        details.expect_value(VIEW_DRILL_DOWN.category)
        details.expect_value(str(VIEW_DRILL_DOWN.pages))
        details.expect_available(VIEW_DRILL_DOWN.copies)

    with demo.step("A teacher may read the whole library — nothing here lets them "
                   "rewrite it", dwell_ms=1500):
        details.expect_authoring_controls_absent()
        page.get_by_role("link", name=as_pattern(r"^\s*Book catalogue\s*$")).first.click()
        catalogue.wait_for_table()
        catalogue.expect_reader_view()
        catalogue.expect_authoring_controls_absent()


# ════════════ read-only path: a pupil browses the library shelves ════════════
#
# The same route, the same shelf and the same read-only view as the teacher unit
# above — deliberately. ``page.tsx``'s ``shouldShowAdminView()`` matches only
# "schooladmin", "admin" and a role name containing "library"/"librarian", so
# "student" falls through to ``views/StudentCatalogueView.tsx`` exactly as
# "teacher" does. What this unit adds is the reader the view is *named* after:
# the pupil who borrows from the library, on the account the admission wizard
# created, scoped to the branch that account was admitted into.
#
# Why the route is reachable for this role
#     Both halves of the gate pass. ``db/repository/permissions.py`` seeds the
#     Student role with ``("manage", "catalogue")`` and ``("read", "categories")``
#     — which satisfies ``usePermissionGuard("catalogue")``, every
#     ``has_permission(read, catalogue)`` dependency in ``api/routes/book.py``
#     and the ``read categories`` dependency the toolbar's filter list needs —
#     and the ``library_and_community`` pack licenses both modules, which
#     satisfies ``useModuleGuard("catalogue")`` and the feature-pack half of
#     ``utils.permissions.has_permission``. The sidebar's "Library Module"
#     section is ``branchOnly``, but ``SideNavigation.canShowSection`` treats
#     branch state as a SchoolAdmin-only concept, so the entry is offered to a
#     pupil outright.
#
# Whose shelves the pupil is shown
#     Their own branch's, and they get no say in it: for any non-admin role
#     ``list_books`` overwrites ``branch_id`` with ``user.school_branch_id``
#     before it queries (``api/routes/book.py``), and ``list_book_categories``
#     does the same. So the rows below could only have come from the branch the
#     pupil was admitted into.
#
# What "read-only" means for a pupil, precisely
#     Not that they are denied anything they hold — like the teacher they hold
#     ``manage``, which is what makes ``isManage`` true and draws the row's two
#     controls at all. It is the *view* that authors nothing: it mounts
#     ``CatalogueTableToolbar`` without ``onAddBookClick``/``onBulkUploadClick``,
#     so the toolbar's write half is never drawn, and it renders no row menu —
#     no edit, no delete, no add/remove copies. The two controls it does offer,
#     "Request Book" and "View details", are a borrowing request and a
#     drill-down; neither changes the catalogue. This unit asserts "Request
#     Book" is *offered* — a library a pupil could not borrow from would be the
#     wrong screen — and leaves actually sending the request to the
#     ``requests_and_renewals`` unit it belongs to.
#
# The shelf is seeded the same way, and for the same reason, as the teacher
# unit's: stocking it is the librarian's walkthrough from a different role's
# workspace, which is the ``library.catalogue.manage`` unit's subject. The
# seeding helpers are idempotent by title, so the two units share one shelf when
# they run against the same provisioned school.

# The term typed into the search box. It is the author of exactly one seeded
# book and appears in no other seeded title, ISBN, publisher or description —
# which is what lets the assertion demand a total of one, and what makes the
# match an answer from ``BookAuthor.fullname`` rather than from the title the
# pupil typed.
STUDENT_SEARCH_TERM = "Ngugi wa Thiongo"
STUDENT_SEARCH_MATCH = VIEW_BOOKS[1]

# The genre the pupil narrows to, and the book they open out of it.
STUDENT_GENRE = VIEW_FICTION
STUDENT_GENRE_COUNT = VIEW_FICTION_COUNT
STUDENT_DRILL_DOWN = VIEW_BOOKS[0]


@pytest.fixture
def pupils_stocked_library(
    provisioned_school: SchoolContext, api: BackendAPI
) -> tuple[SeededBook, ...]:
    """Put two genres and three books, with copies, on the pupil's branch.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert ctx.branches, "provisioning created no branch for this school"

    branch_id = int(ctx.branches[0]["id"])
    token = _view_login(api, ctx.school_admin.email, ctx.school_admin.password)
    category_ids = _view_category_ids(api, token, branch_id=branch_id)

    for book in VIEW_BOOKS:
        _view_seed_book(
            api, token, book,
            branch_id=branch_id,
            category_id=category_ids[book.category],
        )

    _view_assert_reader_sees_them(
        api,
        email=ctx.student.email,
        password=ctx.student.password,
        who="pupil",
        branch_id=branch_id,
    )
    return VIEW_BOOKS


@pytest.mark.student
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="library.catalogue.view.student",
    title="Library Catalogue",
    subtitle="Student views library catalogue",
)
def test_student_browses_the_library_catalogue(
    pupils_stocked_library: tuple[SeededBook, ...],
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A pupil opens the library catalogue, searches it, filters it and reads one
    book's full record — and is never offered a way to change any of it.

    Everything asserted is the server's answer rather than the browser's: the
    authors are joined rows, the category is the genre the book was filed under,
    the copy count is ``available_copies_count`` computed over ``BookCopy``, and
    both the search and the category filter are ``GET /books/`` query parameters
    that ``BookService.list_books`` resolves in SQL. So a table that matches them
    can only have rendered this pupil's branch's catalogue.
    """
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"

    page: Page = demo.page
    catalogue = CataloguePage(page, demo.frontend_base_url)
    pupil = ctx.student.full_name

    with demo.step(f"Sign in as {pupil}, a pupil at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.student)

    with demo.step("The session that opens is the pupil's own account"):
        # Deliberately not an assertion about which page they land on: login
        # sends a non-admin to `/module/<first permission's module>`
        # (auth/login/page.tsx::handlePostLoginNavigation). Whose session this is
        # is what matters, and NavigationHeader states it on every route.
        expect(
            page.get_by_text(as_pattern(re.escape(pupil))).first
        ).to_be_visible(timeout=30_000)
        expect(
            page.get_by_text(as_pattern(re.escape(ctx.student.email))).first
        ).to_be_visible(timeout=30_000)

    with demo.step("The Library menu is waiting in their sidebar"):
        catalogue.expect_nav_entry()
        catalogue.open_from_sidebar().wait_for_table()
        catalogue.expect_no_load_failure()

    with demo.step("The shelf opens: every book on their campus, with its author, "
                   "ISBN and how many copies are free"):
        catalogue.expect_reader_view()
        catalogue.expect_column_headers()
        catalogue.expect_toolbar()
        catalogue.expect_category_heading()
        for book in pupils_stocked_library:
            catalogue.expect_book(
                book.title,
                author=book.author,
                isbn=book.isbn,
                category=book.category,
                copies=book.copies,
            )

    with demo.step(f"Searching for “{STUDENT_SEARCH_TERM}” finds the one book "
                   f"that author wrote"):
        catalogue.search(STUDENT_SEARCH_TERM)
        catalogue.expect_total(1)
        catalogue.expect_book(
            STUDENT_SEARCH_MATCH.title, author=STUDENT_SEARCH_MATCH.author
        )
        for book in pupils_stocked_library:
            if book.title != STUDENT_SEARCH_MATCH.title:
                catalogue.expect_book_absent(book.title)

    with demo.step("Reset Filter puts the whole shelf back"):
        catalogue.reset_filters()
        catalogue.expect_search_value("")
        for book in pupils_stocked_library:
            catalogue.expect_book(book.title)

    with demo.step(f"Filtering by genre narrows it to {STUDENT_GENRE}"):
        catalogue.filter_by_category(STUDENT_GENRE)
        catalogue.expect_category_heading(STUDENT_GENRE)
        catalogue.expect_total(STUDENT_GENRE_COUNT)
        for book in pupils_stocked_library:
            if book.category == STUDENT_GENRE:
                catalogue.expect_book(book.title, category=book.category)
            else:
                catalogue.expect_book_absent(book.title)

    with demo.step(f"“{STUDENT_DRILL_DOWN.title}” has copies on the shelf, so the "
                   f"pupil is offered a way to borrow it"):
        expect(
            catalogue.row(STUDENT_DRILL_DOWN.title).get_by_role(
                "button", name=as_pattern(REQUEST_BOOK_BUTTON)
            )
        ).to_be_enabled(timeout=25_000)

    with demo.step("Opening it shows the full record and how many copies are free"):
        details = catalogue.open_details(STUDENT_DRILL_DOWN.title)
        details.expect_loaded(STUDENT_DRILL_DOWN.title)
        details.expect_fields()
        details.expect_value(STUDENT_DRILL_DOWN.author)
        details.expect_value(STUDENT_DRILL_DOWN.isbn)
        details.expect_value(STUDENT_DRILL_DOWN.category)
        details.expect_value(str(STUDENT_DRILL_DOWN.pages))
        details.expect_available(STUDENT_DRILL_DOWN.copies)

    with demo.step("A pupil may read the whole library — nothing here lets them "
                   "rewrite it", dwell_ms=1500):
        details.expect_authoring_controls_absent()
        page.get_by_role("link", name=as_pattern(r"^\s*Book catalogue\s*$")).first.click()
        catalogue.wait_for_table()
        catalogue.expect_reader_view()
        catalogue.expect_authoring_controls_absent()


# ────────── setup-only seeding for these units (never asserted) ──────────────


def _view_rows(payload: Any) -> list[dict]:
    """Some list endpoints answer a bare list, others a paginated envelope."""
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    return [row for row in payload if isinstance(row, dict)]


def _view_login(api: BackendAPI, email: str, password: str) -> str:
    try:
        return str(api.login(email, password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise CatalogueSeedError(f"could not log in as {email}: {exc}") from exc


def _view_category_ids(
    api: BackendAPI, token: str, *, branch_id: int
) -> dict[str, int]:
    """Find or create every genre the seeded books are filed under.

    A SchoolAdmin must name the branch explicitly — ``list_book_categories``
    answers 400 BRANCH_ID_REQUIRED for them otherwise — while the create takes
    the branch in its body.

    Matched case-insensitively, and that is load-bearing rather than defensive:
    ``BookCategoryService.create_book_category`` stores
    ``name.strip().capitalize()``, so "TEST Fiction c59321" is listed back as
    "Test fiction c59321". A case-sensitive lookup never recognises the genre it
    created a moment ago, tries to create it a second time, and is refused with
    400 "A category with the name … already exists in this branch" — which is
    what the teacher and pupil units, sharing one school and one shelf, do.
    """
    listed = api.get(f"/book/categories/?branch_id={branch_id}", token=token)
    if listed.status_code >= 400:
        raise CatalogueSeedError(
            f"could not list book categories in branch {branch_id}: "
            f"{listed.status_code} {listed.text[:300]}"
        )
    existing = {
        str(row.get("name", "")).casefold(): int(row["id"])
        for row in _view_rows(listed.json())
    }

    ids: dict[str, int] = {}
    for name in sorted({book.category for book in VIEW_BOOKS}):
        if name.casefold() in existing:
            ids[name] = existing[name.casefold()]
            continue
        created = api.post(
            "/book/categories/create/",
            token=token,
            json={
                "name": name,
                "description": "Seeded so the catalogue has a genre to filter by.",
                "school_branch_id": branch_id,
            },
        )
        if created.status_code >= 400:
            raise CatalogueSeedError(
                f"could not create the book category {name!r}: "
                f"{created.status_code} {created.text[:300]}"
            )
        ids[name] = int(created.json()["id"])
    return ids


def _view_seed_book(
    api: BackendAPI,
    token: str,
    book: SeededBook,
    *,
    branch_id: int,
    category_id: int,
) -> int:
    """One book, plus enough physical copies for its "Copies Available" cell.

    ``BookService.create_book`` writes no copies of its own (``create_copy`` is
    False on this route), so ``available_copies_count`` would be 0 and every row
    would read "Out of stock" — true, but nothing to look at. The copies are
    topped up rather than blindly added so that re-running against a school this
    session already stocked cannot double the count the assertions expect.

    ``published_date`` is not optional in practice: the book detail page calls
    ``bookData.published_date.toString()`` unguarded, so a book seeded without
    one could not be drilled into at all.
    """
    existing = _view_existing_book(api, token, branch_id=branch_id, title=book.title)
    if existing is None:
        created = api.post(
            "/books/create/",
            token=token,
            json={
                "title": book.title,
                "isbn": book.isbn,
                "publisher": f"{TEST_PREFIX} University Press",
                "description": book.description,
                "published_date": book.published_date,
                "number_of_pages": book.pages,
                "category_id": category_id,
                "author_names": [book.author],
                "school_branch_id": branch_id,
            },
        )
        if created.status_code >= 400:
            raise CatalogueSeedError(
                f"could not seed the book {book.title!r}: "
                f"{created.status_code} {created.text[:300]}"
            )
        existing = created.json()

    book_id = int(existing["id"])
    shortfall = book.copies - int(existing.get("available_copies_count") or 0)
    if shortfall > 0:
        added = api.post(
            f"/book/copies/books/{book_id}/add-copies",
            token=token,
            json={
                "num_copies": shortfall,
                "physical_location": VIEW_SHELF,
                "physical_condition": "new",
            },
        )
        if added.status_code >= 400:
            raise CatalogueSeedError(
                f"could not add {shortfall} copies of {book.title!r}: "
                f"{added.status_code} {added.text[:300]}"
            )
    return book_id


def _view_existing_book(
    api: BackendAPI, token: str, *, branch_id: int, title: str
) -> dict | None:
    """Reuse a book a previous run in this session already shelved.

    The whole batch shares one provisioned school, and ``create_book`` answers
    409 on an exact title/ISBN/author match rather than being idempotent.
    """
    response = api.get(
        f"/books/?branch_id={branch_id}&skip=0&limit=100&search={title}", token=token
    )
    if response.status_code >= 400:
        return None
    wanted = re.compile(rf"^\s*{re.escape(title)}\s*$", re.I)
    for row in _view_rows(response.json()):
        if wanted.match(str(row.get("title", ""))):
            return row
    return None


def _view_assert_reader_sees_them(
    api: BackendAPI, *, email: str, password: str, who: str, branch_id: int
) -> None:
    """Fail here, loudly, rather than as an empty table three steps into the video.

    ``list_books`` ignores the query string for a non-admin and scopes on
    ``user.school_branch_id``, so a reader whose account was created before
    provisioning selected a branch would be shown a different shelf entirely —
    a symptom that looks nothing like its cause once it reaches the browser.
    """
    token = _view_login(api, email, password)
    response = api.get("/books/?skip=0&limit=100", token=token)
    if response.status_code >= 400:
        raise CatalogueSeedError(
            f"the {who} {email} cannot read the catalogue at all: "
            f"{response.status_code} {response.text[:300]}"
        )
    titles = {str(row.get("title", "")) for row in _view_rows(response.json())}
    missing = sorted(book.title for book in VIEW_BOOKS if book.title not in titles)
    if missing:
        raise CatalogueSeedError(
            f"the {who}'s branch does not hold {missing} — the books were seeded "
            f"into branch {branch_id}, which is evidently not the branch "
            f"{email} belongs to."
        )


def _view_assert_teacher_sees_them(api: BackendAPI, ctx: SchoolContext) -> None:
    assert ctx.teacher is not None
    _view_assert_reader_sees_them(
        api,
        email=ctx.teacher.email,
        password=ctx.teacher.password,
        who="teacher",
        branch_id=int(ctx.branches[0]["id"]),
    )


# ═══════════ manage path: the librarian runs the book register ══════════════
#
# Constants below are prefixed rather than sharing the other sections' names:
# this module file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# Why a SchoolAdmin gets a *different* screen from the same route
#     ``page.tsx``'s ``shouldShowAdminView()`` returns true for a role name of
#     "schooladmin" outright, so this role is handed
#     ``views/AdminCatalogueView.tsx`` — the "Manage Books" register — rather
#     than the reader-facing shelf the teacher and pupil units drive. The
#     toolbar's write half ("Add Book", "Bulk Upload") and the per-row menu are
#     drawn on top of that only while ``usePermission("catalogue", …manage)``
#     holds, which for the seeded SchoolAdmin it does
#     (``db/repository/permissions.py`` gives the role ("manage", "catalogue")).
#     Asserting those controls are on screen is therefore the app's own
#     statement that this account may author, made before anything is authored.
#
# The branch is not optional here
#     ``lib/handlers/catalogueHandler.getBranchIdParam`` appends ``branch_id``
#     for a SchoolAdmin only from ``useBranchStore``, and ``GET /books/`` answers
#     400 BRANCH_ID_REQUIRED for this role without it. Worse for a *write*:
#     ``CatalogueModal.handleAddBook`` reads the same store for
#     ``school_branch_id`` and posts ``null`` when it is empty, which
#     ``BookService.create_book`` refuses with 404 BRANCH_NOT_FOUND. So
#     ``BranchesPage.select_branch`` is a prerequisite, not scene-setting.
#
# Why the genre is seeded over the API
#     The Add Book dialog will not submit without a category, and a fresh branch
#     has none. Building one through the dialog's own "+" drawer is possible, but
#     it is the ``library.categories.manage`` unit's subject — and it re-fetches
#     ``GET /book/categories/``, which re-runs ``CatalogueModal``'s
#     ``[open, initialData, categories]`` effect and wipes anything already typed
#     into the form. Seeding it the same way
#     ``school_provisioning._seed_fee_group`` seeds the fee group the Add Class
#     dialog insists on keeps this walkthrough to the one thing it is about.
#
# What the walkthrough proves, and where
#     Every assertion is made against the register the next person to open the
#     screen would see — the row's own Title / Author(s) / ISBN / Category /
#     Copies Available cells, and the "N books total" badge, which is rendered
#     from the server's ``total_count`` rather than from the rows on the page. A
#     write the UI toasted as successful but never stored cannot pass.

MANAGE_SCENARIO = "library_and_community"

# Unique per *test process*, not merely per run: the whole batch shares one
# provisioned school, and ``create_book`` answers 409 both on an exact
# title/ISBN/author match and on a title/author match under a different ISBN, so
# a re-run inside one session would collide with its own leftovers.
MANAGE_TAG = f"{run_tag()}{uuid.uuid4().hex[:4]}"

MANAGE_GENRE = f"{TEST_PREFIX} Reference {MANAGE_TAG}"

MANAGE_TITLE = f"{TEST_PREFIX} Atlas of Quiet Places {MANAGE_TAG}"
MANAGE_RETITLED = f"{TEST_PREFIX} Atlas of Quiet Places Revised {MANAGE_TAG}"
# The Authors box strips digits and hyphens and Publisher strips anything outside
# [A-Za-z\s'-], so neither may carry the tag; the title is unsanitised and is
# also what the register searches on, so it carries it instead.
MANAGE_AUTHOR = "Efua Sarkodie"
MANAGE_PUBLISHER = "Bookworm University Press"
# ``validate_isbn`` accepts ISBN-10, or ISBN-13 beginning 978/979. Derived from
# the same process-unique source as the tag so it cannot collide with the books
# the reader units shelve into this very branch.
MANAGE_ISBN = f"978{uuid.uuid4().int % 10**10:010d}"
MANAGE_PUBLISHED = "2019-03-14"
MANAGE_PAGES = 148
MANAGE_DESCRIPTION = (
    "A photographic survey of reading rooms, catalogued for the library unit."
)

MANAGE_CORRECTED_PAGES = 212
MANAGE_CORRECTED_DESCRIPTION = (
    "A revised photographic survey of reading rooms, with a new closing chapter."
)

MANAGE_SHELF = "Shelf B-2"
MANAGE_CONDITION = "New"
MANAGE_COPIES = 3


@pytest.fixture
def shelved_genre(provisioned_school: SchoolContext, api: BackendAPI) -> str:
    """Give the branch the genre the Add Book dialog insists on.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.branches, "provisioning created no branch for this school"

    branch_id = int(ctx.branches[0]["id"])
    token = _view_login(api, ctx.school_admin.email, ctx.school_admin.password)

    # A SchoolAdmin must name the branch explicitly — list_book_categories
    # answers 400 BRANCH_ID_REQUIRED for them otherwise — while the create takes
    # the branch in its body.
    listed = api.get(f"/book/categories/?branch_id={branch_id}", token=token)
    if listed.status_code >= 400:
        raise CatalogueSeedError(
            f"could not list book categories in branch {branch_id}: "
            f"{listed.status_code} {listed.text[:300]}"
        )
    # Case-insensitively: the service capitalises every name it stores, so the
    # genre this seeded on an earlier test in the same session comes back as
    # "Test reference …" and a second create would be refused with a 400.
    for row in _view_rows(listed.json()):
        if str(row.get("name", "")).casefold() == MANAGE_GENRE.casefold():
            return MANAGE_GENRE

    created = api.post(
        "/book/categories/create/",
        token=token,
        json={
            "name": MANAGE_GENRE,
            "description": "Seeded so the Add Book dialog has a genre to file under.",
            "school_branch_id": branch_id,
        },
    )
    if created.status_code >= 400:
        raise CatalogueSeedError(
            f"could not create the book category {MANAGE_GENRE!r}: "
            f"{created.status_code} {created.text[:300]}"
        )
    return MANAGE_GENRE


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="library.catalogue.manage.school_admin",
    title="Library Catalogue",
    subtitle="SchoolAdmin creates and manages library catalogue",
)
def test_school_admin_creates_and_manages_a_library_book(
    shelved_genre: str,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A SchoolAdmin catalogues a new book, stocks it, corrects it, withdraws it.

    The four writes are the four the librarian's workspace offers: ``POST
    /books/create/`` from the Add Book dialog, ``POST
    /book/copies/books/{id}/add-copies`` from the row menu, ``PUT
    /books/{id}/update/`` from the Edit Book dialog and ``DELETE
    /books/{id}/delete/`` behind its confirmation. Each is read back off the
    register before the next one runs.
    """
    ctx = provisioned_school
    assert CATALOGUE_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {CATALOGUE_MODULE!r} for the "
        f"manage path — a school without the module has no register to manage"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — GET /books/ is a 400 for "
        "a branch-less SchoolAdmin and every create would post school_branch_id "
        "null, so the register would never load"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    books = ManageBooksPage(page, base_url)
    branch_name = str(ctx.branches[0]["name"])

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Point the console at {branch_name} — the library "
                   f"belongs to a campus"):
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Open the Catalogue from the Library menu"):
        books.expect_nav_entry()
        books.open_from_sidebar().wait_for_register()
        books.expect_manage_view()
        books.expect_column_headers()
        books.expect_toolbar()
        # The screen's own statement that this account may author, made before
        # anything is authored.
        books.expect_authoring_controls()
        books.expect_no_load_failure()

    with demo.step(f"Catalogue a new arrival — “{MANAGE_TITLE}”, cover and all"):
        books.add_book(
            title=MANAGE_TITLE,
            isbn=MANAGE_ISBN,
            authors=MANAGE_AUTHOR,
            publisher=MANAGE_PUBLISHER,
            category=shelved_genre,
            published_date=MANAGE_PUBLISHED,
            pages=MANAGE_PAGES,
            description=MANAGE_DESCRIPTION,
        )

    with demo.step("It is on the register — filed and searchable, but with no "
                   "copies on the shelf yet"):
        # Searching is a GET /books/?search= round trip, not a browser-side
        # filter, so the badge reading "1 book total" is the server agreeing the
        # book was stored — and the row's author, ISBN and category cells are
        # values only the API could have supplied.
        books.search(MANAGE_TAG)
        books.expect_total(1)
        books.expect_book(
            MANAGE_TITLE,
            author=MANAGE_AUTHOR,
            isbn=MANAGE_ISBN,
            category=shelved_genre,
            copies=0,
        )
        books.reset_filters()
        books.expect_search_value("")
        books.expect_no_load_failure()

    with demo.step(f"Put {MANAGE_COPIES} physical copies on {MANAGE_SHELF}"):
        books.add_copies(
            MANAGE_TITLE,
            copies=MANAGE_COPIES,
            location=MANAGE_SHELF,
            condition=MANAGE_CONDITION,
        )
        # available_copies_count is computed over the BookCopy rows the server
        # now holds, so the cell can only read 3 if three copies were written.
        books.expect_book(
            MANAGE_TITLE, copies=MANAGE_COPIES, total_copies=MANAGE_COPIES
        )

    with demo.step("A second edition arrives: correct the title, the blurb and "
                   "the page count"):
        books.edit_book(
            MANAGE_TITLE,
            new_title=MANAGE_RETITLED,
            category=shelved_genre,
            description=MANAGE_CORRECTED_DESCRIPTION,
            pages=MANAGE_CORRECTED_PAGES,
        )

    with demo.step("The correction is what the register now shows — and the "
                   "copies stayed with the book"):
        books.expect_book(
            MANAGE_RETITLED,
            author=MANAGE_AUTHOR,
            isbn=MANAGE_ISBN,
            category=shelved_genre,
            copies=MANAGE_COPIES,
            total_copies=MANAGE_COPIES,
        )
        # Corrected, not duplicated: the title it was corrected *from* is gone.
        books.expect_book_absent(MANAGE_TITLE)
        books.expect_no_load_failure()

    with demo.step("Withdraw the book, and it leaves the library for good",
                   dwell_ms=1500):
        # delete_book confirms the modal names this book, then asserts the row is
        # gone from the reloaded register.
        books.delete_book(MANAGE_RETITLED)
        books.expect_book_absent(MANAGE_TITLE)
        books.expect_no_load_failure()
