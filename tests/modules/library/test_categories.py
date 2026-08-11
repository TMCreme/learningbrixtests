"""Library → Book Categories — the shelving taxonomy (`categories`).

Where this module lives
    ``/module/categories`` (``smsfrontend/src/app/module/categories/page.tsx``).
    One screen for every role: the "Manage Category" workspace, a paginated
    Category / Date Added / Last Modified / Description table over
    ``GET /book/categories/``, with a "Search category by name" box, an "Add
    Category" button and a per-row menu (``components/CategoryActions.tsx``)
    offering "Edit category" and "Delete category". Both write paths open
    ``components/CategoryModal.tsx``.

Manage path: a SchoolAdmin of the ``library_and_community`` school
(``test_school_admin_creates_and_manages_a_book_category``) — the whole life of
one category, created, corrected and retired from the screen above.

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack is
the floor case the pack builder can actually produce — the locked "people" and
"governance" groups and nothing else, so no ``categories``
(``test_categories_denied_for_school_admin_when_module_disabled``).

Where the denial actually lives — and where it does NOT
    Not in the sidebar, not in the middleware, and not in either of the two
    guards ``page.tsx`` itself calls. All of them wave this role through before
    the feature pack is ever consulted:

    * ``useModuleGuard("categories")`` returns ``true`` for a SchoolAdmin *before*
      it reads the ``schoolModules`` cookie, so the ``hasModuleAccess === false``
      branch — the one that renders ``null`` and pushes /auth/no-access — is
      unreachable for this role.
    * ``usePermissionGuard("categories")`` returns early on
      ``isSchoolAdminRole(role)`` in its effect, and its ``hasAccess`` memo
      returns ``true`` on the same test, so ``if (!hasPermission) return null``
      never fires either.
    * ``src/middleware.ts`` exempts a SchoolAdmin from its module enforcement, so
      the route is never turned away before it mounts.

    What denies them is the backend. Every route in
    ``newschoolapp/api/routes/book_category.py`` carries
    ``Depends(has_permission(<read|manage>, "categories"))``; that dependency is
    solved before the path params are used and before any row is looked up, and
    the feature-pack half of ``utils.permissions.has_permission`` answers
    **403 "Feature not available in your plan"** for a school whose pack omits
    the module named in it. The gate module is ``categories`` — the same key the
    pack, the nav entry and ``page.tsx`` all use — so the pack that omits it is
    exactly what produces the 403.

    The UI consequence follows from that 403. ``fetchCategories`` runs from the
    page's mount effect; the axios response interceptor in
    ``src/utils/handleErrorMessage.ts`` recognises the "not available in your
    plan" detail (``shouldRedirectToNoAccess``) and performs a hard
    ``window.location`` redirect to **/auth/no-access**. So the landing page —
    not the ``PageError`` panel this page renders for an ordinary fetch failure —
    is the denial surface, and that panel is asserted absent below for exactly
    that reason.

Why the branch is selected first, and why it is not incidental
    This page's fetch effect returns early for a SchoolAdmin while
    ``currentSchoolAdminBranch?.branch_id`` is unset::

        if (authUserProfile?.roles?.name?.toLowerCase().includes("schooladmin") …) {
          if (!currentSchoolAdminBranch?.branch_id) return;
        }

    With no branch in the store the page issues no request at all, so there is no
    403, no interceptor, and no redirect — the screen simply sits on its skeleton
    loader. That would make every "the workspace is absent" assertion below pass
    for the wrong reason. ``BranchesPage.select_branch`` fills the store (see
    that method for why only the branch row's "View" button can), which is the
    same prerequisite every SchoolAdmin create has.

Deliberately *not* asserted: that the sidebar hides "Book Categories"
    ``nav-config.tsx`` gives that entry ``permission: "categories"``, and
    ``SideNavigation.canShowItem`` returns on the permission check *before* the
    module gate ("Permission check takes priority — having the permission
    implies the module is available"). The seeded SchoolAdmin holds
    ``("manage", "categories")`` (``db/repository/permissions.py``), so the entry
    renders whatever the pack says. Its presence says nothing about this school's
    licence, so it is not asserted either way.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import TEST_PREFIX, run_tag
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.library.categories import RENDERED_DATE, CategoriesPage
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

CATEGORIES_MODULE = "categories"

# config/module_catalog.py's route for this module.
CATEGORIES_ROUTE = "categories"

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

# ── the categories workspace's own chrome, none of which may reach this admin ─
# src/app/module/categories/page.tsx and its components/.
CATEGORIES_HEADING = re.compile(r"^\s*Manage Category\s*$", re.I)
CATEGORIES_SUBHEADING = re.compile(
    r"Easily update subjects to ensure data accuracy", re.I
)
CATEGORIES_SEARCH_FIELD = re.compile(r"^\s*Search category by name\s*$", re.I)
CATEGORIES_TABLE_CAPTION = re.compile(r"^\s*All Categories\s*$", re.I)
ADD_CATEGORY_BUTTON = re.compile(r"^\s*Add Category\s*$", re.I)
CATEGORIES_EMPTY_STATE = re.compile(r"^\s*No categories found\s*$", re.I)
# The row menu's two writes (components/CategoryActions.tsx).
EDIT_CATEGORY_ACTION = re.compile(r"^\s*Edit category\s*$", re.I)
DELETE_CATEGORY_ACTION = re.compile(r"^\s*Delete category\s*$", re.I)
# The panel the page renders when a fetch fails for any *ordinary* reason
# (components/common/PageError). Seeing it would mean a licensing refusal had
# been handled as a plain error instead of as a denial.
CATEGORIES_LOAD_FAILURE = re.compile(r"Failed to load categories", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_categories_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With the module off the pack, a SchoolAdmin gets no category manager at all."""
    ctx = provisioned_school
    if CATEGORIES_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {CATEGORIES_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had library rights anyway", which would make the 403s vacuous.
    # db/repository/permissions.py seeds this role with ("manage", "categories"),
    # and has_permission lets manage stand in for read — so the permission half
    # of the gate passes outright for every route asserted below.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert CATEGORIES_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{CATEGORIES_MODULE!r} permission, which is the one every book-category "
        f"route is gated on. This test would then be asserting a denial the role "
        f"gets for free. Re-point it at the feature pack only, or fix the seed in "
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
        f"{CATEGORIES_MODULE!r} proves nothing about the gate. Provisioning "
        f"phase A assigns one — check that it did."
    )
    licensed = body.get("modules") or []
    assert CATEGORIES_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {CATEGORIES_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every book-category route is refused ────────────
    #
    # Both halves of the gate are covered — the reads the table performs
    # (has_permission("read", "categories")) and the writes its "Add Category"
    # button and row menu perform (has_permission("manage", "categories")). The
    # category id is deliberately arbitrary: has_permission is a route-level
    # dependency, solved before the path params are used and long before any row
    # is looked up, so a 404 here would itself be the failure. The list read is
    # asserted both with and without the branch scope the page appends, because
    # the unscoped form is a 400 BRANCH_ID_REQUIRED for a SchoolAdmin *inside*
    # the handler — the licence must be refused before that ever runs. For the
    # same reason the create body below never has to be creatable, but it carries
    # the TEST prefix anyway so a regression that *did* let it through leaves a
    # sweepable row.
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"?branch_id={branch_id}" if branch_id else ""

    refusals = {
        # What the table itself calls on mount, in both the shapes page.tsx
        # builds depending on whether a branch has been zoomed into.
        "list": api.get(f"/book/categories/{branch_query}", token=token),
        "list_unscoped": api.get("/book/categories/", token=token),
        "detail": api.get("/book/categories/1", token=token),
        # …and the manage half: "Add Category", "Edit category", "Delete category".
        "create": api.post(
            "/book/categories/create/",
            token=token,
            json={
                "name": f"{TEST_PREFIX} Denied Category {run_tag()}",
                "description": f"{TEST_PREFIX} created by a denial test",
                "school_branch_id": branch_id or 1,
            },
        ),
        "update": api.put(
            "/book/categories/1/update/",
            token=token,
            json={"name": f"{TEST_PREFIX} Denied Rename {run_tag()}"},
        ),
        "delete": api.delete("/book/categories/1/delete/", token=token),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{CATEGORIES_MODULE!r}, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a category manager in front of them ─────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Mandatory, and not merely the usual SchoolAdmin branch prerequisite: this
    # page's mount effect refuses to fetch anything until the branch store is
    # filled (see the module docstring), and with no fetch there is no 403 to
    # deny them with. Selecting the branch is what makes the denial observable.
    if ctx.branches:
        BranchesPage(page, frontend_base_url).select_branch(ctx.branches[0]["name"])

    # A SchoolAdmin is exempt from the middleware gate, from useModuleGuard and
    # from usePermissionGuard, so this route really does mount and really does
    # start fetching — and the axios interceptor turns the refusal into a hard
    # redirect. Waiting for the URL is therefore also what stops the "workspace
    # is absent" assertions below from passing merely because the page had not
    # finished loading.
    goto_module(page, frontend_base_url, CATEGORIES_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the workspace survives the redirect: not its heading, not its
    # toolbar, not the table, not a single row, and not the row menu's two
    # writes. "Failed to load categories" is asserted absent for the same reason
    # as the catalogue unit: rendering it would mean a licensing refusal had been
    # handled as an ordinary fetch error rather than as a denial.
    expect(
        page.get_by_role("heading", name=as_pattern(CATEGORIES_HEADING))
    ).to_have_count(0)
    expect(page.get_by_text(as_pattern(CATEGORIES_SUBHEADING))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(CATEGORIES_SEARCH_FIELD))).to_have_count(0)
    expect(page.get_by_text(as_pattern(CATEGORIES_TABLE_CAPTION))).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(ADD_CATEGORY_BUTTON))
    ).to_have_count(0)
    expect(page.get_by_text(as_pattern(CATEGORIES_EMPTY_STATE))).to_have_count(0)
    expect(page.get_by_text(as_pattern(EDIT_CATEGORY_ACTION))).to_have_count(0)
    expect(page.get_by_text(as_pattern(DELETE_CATEGORY_ACTION))).to_have_count(0)
    expect(page.get_by_text(as_pattern(CATEGORIES_LOAD_FAILURE))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)


# ════════ manage path: the SchoolAdmin keeps the shelving taxonomy ═══════════
#
# Constants below are prefixed rather than sharing the negative section's names:
# this module file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# Why this role sees a workspace at all
#     Both halves of the gate pass. ``db/repository/permissions.py`` seeds the
#     SchoolAdmin role with ``("manage", "categories")``, which satisfies
#     ``usePermissionGuard("categories")`` and every ``has_permission`` dependency
#     in ``api/routes/book_category.py``; and the ``library_and_community`` pack
#     licenses ``categories``, which satisfies ``useModuleGuard("categories")`` and
#     the feature-pack half of ``utils.permissions.has_permission``. That pack is
#     also the right plan for this walkthrough for a second reason: it is the one
#     the ledger names, and it licenses the rest of the library alongside, so
#     nothing on this screen leans on a module the school does not hold.
#
# What "manage" means here, precisely
#     Three writes against the *same* category, because that is the whole life of
#     a shelving label: POST /book/categories/create/ opens it,
#     PUT /book/categories/{id}/update/ corrects it, DELETE
#     /book/categories/{id}/delete/ retires it. Every assertion is made on the
#     reloaded register row — the cells the next person to open the screen would
#     read — rather than on the success toast, so a write the frontend announced
#     but that never reached the database fails on the following step instead of
#     passing quietly. Retiring it also leaves the shared school exactly as this
#     test found it.
#
# The branch has to be activated first, and it is not the usual formality
#     ``fetchCategories``'s mount effect *returns early* for a SchoolAdmin whose
#     ``useBranchStore`` is empty (page.tsx lines 111-119), so the screen sits on
#     ``BookCategoriesLoader`` for ever — not an empty table and not an error. And
#     ``GET /book/categories/`` answers 400 BRANCH_ID_REQUIRED for that role
#     without the query parameter anyway. ``BranchesPage.select_branch`` is what
#     fills the store, and it is also what makes the sidebar's ``branchOnly``
#     "Library Module" section — the way into this screen — appear.
#
# Why the names are matched case-insensitively
#     ``BookCategoryService`` stores ``name.strip().capitalize()`` on create *and*
#     on update, so "TEST Poetry 3f9a1c" is rendered back as "Test poetry 3f9a1c".
#     Comparing a cell against the string that was typed would fail on the case
#     alone. Descriptions are stored verbatim, so those are compared exactly.

MANAGE_SCENARIO = "library_and_community"
MANAGE_TAG = run_tag()

# Deliberately not "Fiction"/"Science": the catalogue unit seeds those two into
# this same shared school, and ``create_book_category`` answers 400 on a
# duplicate name within a branch.
MANAGE_CATEGORY = f"{TEST_PREFIX} Poetry {MANAGE_TAG}"
MANAGE_RENAMED_CATEGORY = f"{TEST_PREFIX} Poetry Anthologies {MANAGE_TAG}"

MANAGE_DESCRIPTION = "Verse collections for the upper primary reading corner."
MANAGE_CORRECTED_DESCRIPTION = (
    "Verse collections and anthologies, shelved beside the reading corner."
)


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="library.categories.manage.school_admin",
    title="Library Categories",
    subtitle="SchoolAdmin creates and manages library categories",
)
def test_school_admin_creates_and_manages_a_book_category(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A SchoolAdmin adds a shelving category, corrects it, then retires it.

    Everything asserted is the register the next librarian would open — the
    row's own Category, Date Added, Last Modified and Description cells — so a
    write that the UI toasted about but that the backend never stored cannot
    pass. The dates are the server's ``date_created``/``last_modified``, printed
    through the page's own ``formatDate``, which is why they are asserted as
    rendered dates rather than as anything this test chose.
    """
    ctx = provisioned_school
    assert CATEGORIES_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {CATEGORIES_MODULE!r} for the "
        f"manage path — a school without the module has no taxonomy to manage"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — phase B creates one for "
        "every scenario, and this page never issues its GET at all for a "
        "branch-less SchoolAdmin, so the register would never load"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    categories = CategoriesPage(page, base_url)
    branch_name = str(ctx.branches[0]["name"])

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Point the console at {branch_name}"):
        # Mandatory, not cosmetic: it is what fills the branch store this page's
        # fetch effect waits on, and what unlocks the branchOnly Library menu.
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Open Book Categories from the Library menu"):
        categories.expect_nav_entry()
        categories.open_from_nav()

    with demo.step("This is how the campus files its books today"):
        categories.expect_column_headers()
        expect(categories.count_badge()).to_be_visible(timeout=20_000)
        categories.expect_no_load_failure()

    with demo.step("Open a new shelf for poetry"):
        categories.create_category(
            name=MANAGE_CATEGORY, description=MANAGE_DESCRIPTION
        )

    with demo.step("The new category is on the register, described and dated"):
        # create_category leaves the name it typed in the search box, and that
        # box really does filter the rendered list. Clearing it means every
        # assertion from here on is made against the whole register rather than
        # against one filtered view of it — including the "the old name is gone"
        # claim below, which would otherwise be trivially true.
        categories.search("")
        expect(categories.cell(MANAGE_CATEGORY, "name")).to_have_text(
            _manage_rendered(MANAGE_CATEGORY)
        )
        expect(categories.cell(MANAGE_CATEGORY, "description")).to_have_text(
            MANAGE_DESCRIPTION
        )
        expect(categories.cell(MANAGE_CATEGORY, "date_added")).to_have_text(
            RENDERED_DATE
        )
        expect(categories.cell(MANAGE_CATEGORY, "last_modified")).to_have_text(
            RENDERED_DATE
        )

    with demo.step("Rename it, and say more precisely what it holds"):
        categories.edit_category(
            name=MANAGE_CATEGORY,
            new_name=MANAGE_RENAMED_CATEGORY,
            description=MANAGE_CORRECTED_DESCRIPTION,
        )

    with demo.step("The correction is what the register now shows"):
        expect(categories.cell(MANAGE_RENAMED_CATEGORY, "name")).to_have_text(
            _manage_rendered(MANAGE_RENAMED_CATEGORY)
        )
        expect(categories.cell(MANAGE_RENAMED_CATEGORY, "description")).to_have_text(
            MANAGE_CORRECTED_DESCRIPTION
        )
        # Renamed, not duplicated: the name it was corrected *from* is gone.
        # Asserted on the register's rows rather than page-wide, because antd
        # leaves every modal it has opened mounted-but-hidden and ``get_by_text``
        # matches hidden nodes.
        expect(categories.find_row(MANAGE_CATEGORY)).to_have_count(0)
        categories.expect_no_load_failure()

    with demo.step("Retire the shelf, and it leaves the taxonomy for good"):
        # delete_category confirms the modal names this category before it
        # clicks Delete, then asserts the row is gone from the reloaded register.
        categories.delete_category(name=MANAGE_RENAMED_CATEGORY)
        expect(categories.find_row(MANAGE_RENAMED_CATEGORY)).to_have_count(0)
        categories.expect_no_load_failure()


def _manage_rendered(name: str) -> re.Pattern[str]:
    """How the backend will have stored ``name`` — see the section comment."""
    return re.compile(rf"^\s*{re.escape(name)}\s*$", re.I)
