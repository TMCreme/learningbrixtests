"""Governance → Access Roles — role administration (`access_roles`).

Where this module lives
    One page plus three sub-screens: ``/module/access_roles``
    (``smsfrontend/src/app/module/access_roles/page.tsx``) with
    ``add-access-role``, ``edit-access-role/{id}`` and ``preview-role/{id}``
    beneath it. The page is "Manage Access Roles" over two tabs — **Access
    Roles** (every role, with Preview / Edit / Delete per row and an "Add Access
    Role" button) and **Users & Roles** (every user, with Change Role and
    Deactivate). Its data comes from ``GET /roles/`` and ``GET /users/all``; its
    writes are ``POST/PUT/DELETE /roles/…`` and
    ``PATCH /usersrole/{user_id}/{role_id}``.

Mandatory unit: a SchoolAdmin of the ``minimal`` school
    ``test_access_roles_is_reachable_on_the_minimal_pack`` — the ledger unit
    ``governance.access_roles.always_licensed``. It asserts the *opposite* of a
    denial: on the most restricted pack this product can build, the module is
    still licensed, still offered on the sidebar, still loads, and its own gated
    route still answers. It adds no gate and tightens none.

THERE IS NO UNLICENSED SCHOOL TO DENY, AND THAT IS THE DESIGN
    ``smsfrontend/src/app/module/feature_flag/create/page.tsx`` (and its
    ``edit/[id]`` twin) declares ``BASIC_GROUPS = ["people", "governance"]`` and
    treats every module in those two groups as mandatory: ``isBasicLockedModule``
    renders the checkbox ``locked``, ``toggleModule`` returns early for it,
    ``clearAll`` resets the selection *to* the locked set rather than to nothing,
    the panel is captioned "Basic Modules Required", and ``handleSave`` refuses
    outright with "All basic modules (People & Governance) must be selected."
    ``access_roles`` sits in the ``governance`` group of
    ``services/feature_pack_service.SYSTEM_MODULE_GROUPS``, so **every pack the
    product can build carries it**. Reading the packs back off the running system
    confirms it: every ``TEST Minimal Pack`` holds the same ten modules — the six
    governance ones plus home, dashboard, students, staff — no matter what
    ``config/feature_scenarios.yaml`` asked for.

    Governance being core and always on is **intended product behaviour,
    confirmed 2026-08-09** (see the ``minimal`` note in
    ``config/feature_scenarios.yaml``), not a licensing hole. An earlier round of
    this file carried a denial test for a ``governance.access_roles.denied``
    unit; that unit no longer exists in ``state/feature_ledger.json`` — it was
    superseded by the ``always_licensed`` one below — and its test could never
    run again anyway (``minimal`` now lists ``access_roles``, so it skipped on
    its first line, and the body referenced three module-level names that were
    never defined). It has been replaced rather than duplicated: two tests for
    one unit both drag in a full provisioning walkthrough for the same scenario.

Why the frontend cannot be the thing that proves this
    Every frontend gate on this screen carves a SchoolAdmin out by name, so "the
    page loaded" is on its own compatible with a licence system that does nothing
    at all:

    * ``src/middleware.ts`` carries ``!isSchoolAdmin`` in its module-enforcement
      condition ("SchoolAdmin bypasses: governance pages (config, access_roles,
      etc.) are not feature-flag modules"), so the route is never turned away
      before it mounts.
    * The page calls ``useModuleGuard("access_roles")`` and
      ``usePermissionGuard("access_roles")``, and both return access for this
      role before they ever read the ``schoolModules`` cookie — so neither the
      ``hasModuleAccess === false`` branch (which renders ``null``) nor the
      ``/auth/no-access`` push inside those hooks is reachable here.
    * ``SideNavigation.canShowItem`` short-circuits the same way.

    The test therefore pins the gate down with a control — ``catalogue``, which
    is in the ``library`` group rather than the locked pair, which the ``minimal``
    pack really does omit, and which the seeded SchoolAdmin role holds
    ``("manage", "catalogue")`` on. ``GET /books/`` refuses it 403 "Feature not
    available in your plan". The gate bites; it just does not bite here, by
    design.

What actually carries the licence for this module
    The feature-pack half of ``utils.permissions.has_permission``: after the
    (permission, module) pair is found on the role it resolves the user's school
    and answers 403 "Feature not available in your plan" when the school's pack
    omits that module. Every gated surface of this page is declared
    ``Depends(has_permission("manage", "access_roles"))`` — ``GET /users/all``
    and ``PATCH /usersrole/{user_id}/{role_id}`` (api/routes/auth.py),
    ``POST /roles/``, ``PUT /roles/{id}`` and ``DELETE /roles/{id}``
    (api/routes/roles.py). ``GET /users/all`` is the one the screen fires on
    mount, so it is the one the mandatory test reads back: a 200 there is the
    licence passing for real, and a 403 would be the whole workspace collapsing
    into ``/auth/no-access`` via ``shouldRedirectToNoAccess`` in
    ``src/utils/handleErrorMessage.ts``.

    Deliberately *not* read as evidence: ``GET /roles/``.
    ``roles_router.get("/")`` is declared with no dependency at all, so the role
    list answers any token, licensed or not. It is asserted only as "the register
    has data to render", never as a licence check.

Reading the mandatory test when it fails
    ``access_roles`` *missing* from the school's licence, or missing from the
    locked set the pack builder forces in, is the headline result: it means a
    pack without the module can now be built. That is a product change, not a
    test to paper over — re-read the ``minimal`` note in
    ``config/feature_scenarios.yaml`` and rewrite the unit as an ordinary denial
    test. A 403 from ``/users/all`` while the module *is* licensed means the
    opposite: the licence gate started biting for a module the school holds.
    ``access_roles`` missing from ``/feature-packs/system-modules`` altogether
    would instead mean the backend stopped offering it as a licensable module,
    which is a catalogue change: ``config/feature_scenarios.yaml`` and
    ``config/module_catalog.py`` need updating with it, not this assertion.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.access_roles import (
    ADD_ROLE_BUTTON,
    EDIT_LEVELS,
    HEADING,
    NAV_ACCESS_ROLES,
    PAGINATION,
    ROLE_SEARCH,
    ROLES_TAB,
    USER_SEARCH,
    USERS_TAB,
    AccessRolesPage,
)

ACCESS_ROLES_MODULE = "access_roles"
# config/module_catalog.py's route for this module.
ACCESS_ROLES_ROUTE = "access_roles"

# The role whose permissions are checked against the pack below.
SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# ─────────────── the module can never be unlicensed (always_licensed) ─────────
#
# The floor case: the most restricted pack the product can actually build.
MANDATORY_SCENARIO = "minimal"

# src/app/module/feature_flag/create/page.tsx — the SuperAdmin's only surface for
# building a pack. Every module of a "basic" group is rendered locked and forced
# into the pack; only these two are exempt.
BASIC_GROUPS = ("people", "governance")
OPTIONAL_BASIC_MODULES = frozenset({"guardians", "families"})
GOVERNANCE_GROUP = "governance"

# The gated route the workspace fires on mount (api/routes/auth.py declares it on
# the users router, so it lands at /users/all). Its dependency is
# has_permission("manage", "access_roles") — the licence check this unit is about.
USERS_ALL_PATH = "/users/all"
# The register's own list. Ungated by design, so it is read as "the table has
# something to render", never as evidence about the licence.
ROLES_LIST_PATH = "/roles/"

# The control that proves the feature gate is live rather than decorative: a
# module in the `library` group (so the pack builder really does let a SuperAdmin
# clear it), omitted by the `minimal` pack, and held by the seeded SchoolAdmin
# role as ("manage", "catalogue") — which satisfies the route's ("read",
# "catalogue") through the manage-overrides-read branch of has_permission, so a
# refusal can only come from the pack. Any parameters will do: the dependency
# runs before the handler reads anything.
ENFORCED_UNLICENSED_MODULE = "catalogue"
ENFORCED_UNLICENSED_PATH = "/books/?skip=0&limit=1"
# newschoolapp/utils/permissions.py, the feature-pack branch of has_permission.
FEATURE_PACK_403 = re.compile(r"feature not available in your plan", re.I)

# The cookie every frontend gate derives its answer from, written by
# src/app/auth/login/page.tsx and refreshed by SideNavigation.
MODULES_COOKIE = "schoolModules"

# nav-config.tsx — the section the "Access Roles" entry lives in for a SchoolAdmin
# who has not picked a branch (roleGate SchoolAdmin, noBranchOnly). Asserted
# alongside the entry so "the entry is there" cannot pass on a sidebar that
# rendered nothing at all.
NAV_SECTION_GOVERNANCE = re.compile(r"^\s*Governance Module\s*$", re.I)

# Where the frontend sends a user it has decided is not allowed in
# (src/app/auth/no-access/page.tsx, reached by handleErrorMessage's interceptor).
DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")

# The workspace's own chrome, from access_roles/page.tsx: the register heading
# above the table, and the panel PageError swaps the whole page for when either
# mount fetch is refused.
ALL_ROLES_HEADING = re.compile(r"^\s*All Roles\s*$", re.I)
LOAD_FAILURE = re.compile(r"Failed to load access roles", re.I)

# A seeded role every school shares — proof the register rendered rows rather
# than an empty shell.
SEEDED_ROLE = "SchoolAdmin"


@pytest.mark.school_admin
@pytest.mark.scenario(MANDATORY_SCENARIO)
def test_access_roles_is_reachable_on_the_minimal_pack(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """The floor case still administers its own roles: licensed, offered, working.

    Ledger unit ``governance.access_roles.always_licensed``. See the module
    docstring: ``access_roles`` is in the ``governance`` group, the pack builder
    locks that whole group into every pack, and governance being core is
    **intended product behaviour, confirmed 2026-08-09**. So this asserts the
    opposite of a denial — and adds no gate of any kind.

    Read-only throughout. Reachability is the claim, and this school already has
    the seeded roles and the users provisioning created, so nothing is written:
    a create here would leave a row in ``roles``, which is a *global* table, on
    every other school's Access Roles tab.
    """
    ctx = provisioned_school
    requested = set(ctx.feature_modules)

    # ── 1. Licensed, and licensed because it cannot be dropped ────────────────
    super_token = api.login(
        ctx.super_admin.email, ctx.super_admin.password
    )["access_token"]
    catalogue = api.get("/feature-packs/system-modules", token=super_token)
    assert catalogue.status_code == 200, (
        "the SuperAdmin must be able to read the system module catalogue — got "
        f"{catalogue.status_code}: {catalogue.text[:300]}"
    )
    catalogue_body = catalogue.json()
    all_modules = {str(m) for m in (catalogue_body.get("all_modules") or [])}
    assert ACCESS_ROLES_MODULE in all_modules, (
        f"{ACCESS_ROLES_MODULE!r} is no longer a module the backend knows about "
        f"(services/feature_pack_service.SYSTEM_MODULE_GROUPS), so this unit is "
        f"asserting the reachability of something that has been withdrawn. That "
        f"is a catalogue change: update config/module_catalog.py and "
        f"config/feature_scenarios.yaml with it. Catalogue: {sorted(all_modules)}"
    )
    groups = {
        str(g.get("group")): [str(m) for m in (g.get("modules") or [])]
        for g in (catalogue_body.get("groups") or [])
    }
    assert ACCESS_ROLES_MODULE in groups.get(GOVERNANCE_GROUP, []), (
        f"{ACCESS_ROLES_MODULE!r} is no longer in the {GOVERNANCE_GROUP!r} group "
        f"of the backend catalogue. The create-pack form locks a module in "
        f"because of the group it belongs to, so that membership is the whole "
        f"reason this module is mandatory. "
        f"Groups: { {k: sorted(v) for k, v in groups.items()} }"
    )
    locked = {
        module
        for name in BASIC_GROUPS
        for module in groups.get(name, [])
        if module not in OPTIONAL_BASIC_MODULES
    }
    assert ACCESS_ROLES_MODULE in locked, (
        f"{ACCESS_ROLES_MODULE!r} is no longer one of the modules the "
        f"SuperAdmin's create-pack form forces into every pack, so role "
        f"administration can now be sold away from a school and this unit's "
        f"premise is gone. That is a product change, not a test failure to paper "
        f"over — re-read config/feature_scenarios.yaml's `minimal` note and "
        f"rewrite this unit as a real denial test. Locked: {sorted(locked)}"
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — the "
        f"sidebar calls this on every mount — got {features.status_code}: "
        f"{features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so this is not "
        f"the {MANDATORY_SCENARIO!r} floor and nothing below is about licensing — "
        f"has_permission treats 'no pack' as unrestricted. Provisioning phase A "
        f"assigns one; check that it did."
    )
    licensed = {str(m) for m in (body.get("modules") or [])}
    assert licensed == requested | locked, (
        f"{ctx.school_name!r}'s licence is not 'what the {MANDATORY_SCENARIO!r} "
        f"pack requested plus the locked basic modules'. Requested "
        f"{sorted(requested)}; locked {sorted(locked)}; got {sorted(licensed)}. "
        f"Unexpectedly granted: {sorted(licensed - (requested | locked))}; "
        f"expected but missing: {sorted((requested | locked) - licensed)}."
    )
    assert ACCESS_ROLES_MODULE in licensed, (
        f"{ctx.school_name!r} — the most restricted pack this product can build — "
        f"is not licensed for {ACCESS_ROLES_MODULE!r}. Governance is core and "
        f"always on by design, so a school has just lost the ability to say who "
        f"may do what. Licensed: {sorted(licensed)}"
    )

    # ── 2. The licence is enforced for this user, on a module outside the lock ─
    #
    # Without this, everything below is equally consistent with a feature-pack
    # system that never refuses anybody — every frontend gate on this screen
    # carves the SchoolAdmin out by name (see the module docstring).
    assert ENFORCED_UNLICENSED_MODULE not in licensed, (
        f"{ctx.school_name!r} is now licensed for {ENFORCED_UNLICENSED_MODULE!r}, "
        f"so it can no longer serve as the control that the feature gate bites "
        f"for this user. Pick another module the {MANDATORY_SCENARIO!r} pack "
        f"omits, that is outside the locked basic set, and that a backend route "
        f"gates on."
    )
    assert ENFORCED_UNLICENSED_MODULE in _role_modules(api, SCHOOL_ADMIN_ROLE), (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds an "
        f"{ENFORCED_UNLICENSED_MODULE!r} permission, so the 403 below would come "
        f"from the permission half of has_permission and prove nothing about "
        f"feature packs. Fix newschoolapp/db/repository/permissions.py or "
        f"re-point this control."
    )
    gated = api.get(ENFORCED_UNLICENSED_PATH, token=token)
    assert gated.status_code == 403, (
        f"{ENFORCED_UNLICENSED_PATH} answered {gated.status_code} for a "
        f"SchoolAdmin whose school is not licensed for "
        f"{ENFORCED_UNLICENSED_MODULE!r}; the feature-pack gate in "
        f"utils/permissions.has_permission should have refused it, and until it "
        f"does, 'access roles is reachable' says nothing. Body: {gated.text[:300]}"
    )
    assert FEATURE_PACK_403.search(gated.text), (
        f"{ENFORCED_UNLICENSED_PATH} was refused, but not by the feature pack — "
        f"the detail should be 'Feature not available in your plan'. "
        f"Body: {gated.text[:300]}"
    )

    # ── 3. Offered: the sidebar entry a SchoolAdmin sees on landing ───────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # No branch is selected, and that is deliberate rather than an omission: the
    # whole "Governance Module" section is noBranchOnly (nav-config.tsx), so
    # picking a branch is what would take this entry *off* the sidebar. Nothing
    # on the screen needs one — GET /roles/ takes no branch and GET /users/all
    # derives the school from the caller's own admin profile.
    expect(page.get_by_text(NAV_SECTION_GOVERNANCE).first).to_be_visible(timeout=20_000)
    # Scoped to the sidebar: /module/home's QuickActions grid can carry a card
    # with the same label and href, so an unscoped match would pass on the
    # landing page alone.
    nav = page.get_by_role("navigation")
    expect(nav.get_by_role("link", name=as_pattern(NAV_ACCESS_ROLES)).first).to_be_visible(
        timeout=20_000
    )
    expect(nav.locator(f'a[href="/module/{ACCESS_ROLES_ROUTE}"]').first).to_be_visible()

    cookie_modules = _school_modules_cookie(page)
    assert cookie_modules is not None, (
        f"the {MODULES_COOKIE!r} cookie was never written for this session. Every "
        f"frontend gate derives its answer from it, so without it the walk below "
        f"says nothing about what this school is licensed for. Both "
        f"src/app/auth/login/page.tsx and SideNavigation are meant to set it."
    )
    assert set(cookie_modules) == licensed, (
        f"the browser session claims {sorted(cookie_modules)} as its licensed "
        f"modules, out of step with /school_profile/{ctx.school_id}/features, "
        f"which reports {sorted(licensed)}"
    )
    assert ACCESS_ROLES_MODULE in cookie_modules, (
        f"{ACCESS_ROLES_MODULE!r} is missing from this session's "
        f"{MODULES_COOKIE!r} cookie, so src/middleware.ts would gate "
        f"/module/{ACCESS_ROLES_ROUTE} for any role without the SchoolAdmin "
        f"carve-out — the module is not reachable on the "
        f"{MANDATORY_SCENARIO!r} pack for anybody else"
    )

    # ── 4. Working: the route loads and the screen's own fetches answer ───────
    # Asking for the route by hand is the request middleware.ts actually sees.
    goto_module(page, frontend_base_url, ACCESS_ROLES_ROUTE)
    expect(page.get_by_role("heading", name=as_pattern(HEADING))).to_be_visible(
        timeout=25_000
    )
    assert not DENIAL_URL.search(page.url), (
        f"the SchoolAdmin of {ctx.school_name!r} was redirected to {page.url!r} "
        f"asking for a module their pack licenses. Governance is core and always "
        f"on by design — a denial here is a regression, not a gate to keep."
    )
    assert page.url.rstrip("/").endswith(f"/module/{ACCESS_ROLES_ROUTE}"), (
        f"expected to still be on /module/{ACCESS_ROLES_ROUTE}, but the app moved "
        f"to {page.url!r}"
    )

    # The workspace itself, not a shell. Either mount fetch failing swaps the
    # whole page for PageError("Failed to load access roles"), and a 403 from
    # /users/all would have taken the session to /auth/no-access before that.
    expect(page.get_by_text(as_pattern(LOAD_FAILURE))).to_have_count(0)
    expect(page.get_by_role("heading", name=as_pattern(ALL_ROLES_HEADING))).to_be_visible(
        timeout=20_000
    )
    expect(page.get_by_role("button", name=as_pattern(ROLES_TAB)).first).to_be_visible()
    expect(page.get_by_role("button", name=as_pattern(USERS_TAB)).first).to_be_visible()
    expect(page.get_by_role("button", name=as_pattern(ADD_ROLE_BUTTON)).first).to_be_visible()
    expect(page.get_by_placeholder(as_pattern(ROLE_SEARCH)).first).to_be_visible()
    # Rendered from `totalPages`, which only exists once the fetch resolved.
    expect(page.get_by_text(PAGINATION).first).to_be_visible(timeout=20_000)

    # Rows, not an empty table: every school shares the seeded roles.
    roles_page = AccessRolesPage(page, frontend_base_url)
    expect(roles_page.role_row(SEEDED_ROLE).first).to_be_visible(timeout=20_000)

    # The other tab is the one whose data is licence-gated, so it is the one that
    # would have collapsed the page had the pack omitted the module.
    #
    # Looked up by a *branch-scoped* colleague rather than by the SchoolAdmin
    # themselves: list_users (api/routes/auth.py) answers a SchoolAdmin with
    # `User.school_branch_id IN (their branches) OR User.id IN (admins associated
    # with their schools)`, and the second half is filled from
    # SchoolAdminAssociation, which a school created through the legacy
    # school_profile.school_admin_id column may not have a row in. The branch
    # admin phase B creates always carries a branch, so they are always in scope.
    #
    # The tab has to be opened before its chrome can be asserted: page.tsx
    # renders ONE search input for the whole workspace and swaps only its
    # placeholder on `activeTab`, so "Search users by name, email, or role"
    # simply does not exist while the Access Roles tab is the open one.
    roles_page.open_users_tab()
    expect(page.get_by_placeholder(as_pattern(USER_SEARCH)).first).to_be_visible(
        timeout=20_000
    )
    colleague = _branch_scoped_user(ctx)
    expect(roles_page.find_user_row(colleague)).to_be_visible()

    # ── 5. And the module's gated API surface answers this admin directly ─────
    users = api.get(USERS_ALL_PATH, token=token)
    assert users.status_code == 200, (
        f"GET {USERS_ALL_PATH} answered {users.status_code} for the SchoolAdmin "
        f"of {ctx.school_name!r}, whose pack licenses {ACCESS_ROLES_MODULE!r}. "
        f"This is the one route on the screen carrying "
        f"Depends(has_permission('manage', 'access_roles')) that the page fires "
        f"on mount, so a 403 'Feature not available in your plan' here would mean "
        f"the governance group stopped being locked into every pack; anything "
        f"else is the route itself breaking. Body: {users.text[:300]}"
    )
    assert not FEATURE_PACK_403.search(users.text), (
        f"GET {USERS_ALL_PATH} returned 200 but its body reads like the "
        f"feature-pack refusal: {users.text[:300]}"
    )
    emails = {str(u.get("email", "")).lower() for u in (users.json() or [])}
    assert colleague.lower() in emails, (
        f"GET {USERS_ALL_PATH} answered without {colleague!r} in it, so the Users "
        f"& Roles tab is not showing this school's own people"
    )

    # The register's list is ungated (roles_router.get('/') declares no
    # dependency), so this is asserted as 'the table had data', not as a licence
    # check — see the module docstring.
    listed = api.get(ROLES_LIST_PATH, token=token)
    assert listed.status_code == 200, (
        f"GET {ROLES_LIST_PATH} answered {listed.status_code} — the role register "
        f"the screen renders is unreadable. Body: {listed.text[:300]}"
    )
    assert any(
        str(row.get("name", "")).strip() == SEEDED_ROLE for row in (listed.json() or [])
    ), (
        f"{SEEDED_ROLE!r} is not on GET {ROLES_LIST_PATH}, so the roles table this "
        f"school administers has lost the seeded roles"
    )


def _branch_scoped_user(ctx: SchoolContext) -> str:
    """The email of a provisioned user who belongs to one of this school's branches.

    ``GET /users/all`` scopes a SchoolAdmin's answer to their branches (plus any
    admin the SchoolAdminAssociation table links to their school), so only a
    branch-scoped user is guaranteed to be on the list. The branch admin is
    created by provisioning phase B unconditionally — it is not feature-gated,
    because a SchoolAdmin cannot create anybody without a branch — with the staff
    the ``minimal`` pack also licenses as fallbacks.
    """
    for candidate in (ctx.branch_admin, ctx.generic_admin, ctx.teacher, ctx.accountant):
        if candidate is not None and candidate.email:
            return candidate.email
    raise AssertionError(
        f"{ctx.school_name!r} was provisioned without a single branch-scoped "
        f"user, so there is nobody the Users & Roles tab could show. Phase B "
        f"creates the branch admin unconditionally — check that it did."
    )


def _role_modules(api: BackendAPI, role_name: str) -> set[str]:
    """Every module the named seeded role holds a permission on."""
    role = api.get(f"/roles/{api.role_id_for(role_name)}")
    assert role.status_code == 200, (
        f"could not read the {role_name} role — got {role.status_code}: "
        f"{role.text[:300]}"
    )
    return {str(p.get("module")) for p in role.json().get("permissions", [])}


def _school_modules_cookie(page: Page) -> list[str] | None:
    """The ``schoolModules`` cookie as a list, or ``None`` if it is not readable.

    The frontend stores it URL-encoded JSON; ``None`` covers both "never set" and
    "set to something that is not a JSON array", which are the same failure from
    middleware.ts's point of view — it falls back to ``[]`` and skips the gate.
    """
    for cookie in page.context.cookies():
        if cookie.get("name") != MODULES_COOKIE:
            continue
        try:
            parsed = json.loads(unquote(str(cookie.get("value") or "")))
        except json.JSONDecodeError:
            return None
        return [str(m) for m in parsed] if isinstance(parsed, list) else None
    return None


# ───────────── manage path: the SchoolAdmin runs role administration ──────────
#
# Constants below are prefixed rather than sharing the denial section's names:
# this module file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# The role this workspace is built for
#     A SchoolAdmin holds ("manage", "access_roles") on the seeded role
#     (newschoolapp/db/repository/permissions.py), which is exactly what the
#     three writes below are declared with — POST /roles/, PUT /roles/{id} and
#     DELETE /roles/{id} all carry Depends(has_permission("manage",
#     "access_roles")). ``finance_only`` licenses the module, so the licence half
#     of that dependency passes too and the school really does get the workspace.
#
# Why this test must NOT activate a branch first
#     Unlike every academics or fees unit, this one deliberately skips
#     ``BranchesPage.select_branch``. The sidebar's whole "Governance Module"
#     group is declared ``noBranchOnly`` (SideNavigation/nav-config.tsx), and
#     ``SideNavigation.canShowSection`` reads that as "hide this for a SchoolAdmin
#     who is currently inside a branch" — so picking a branch is what would take
#     "Access Roles" *off* the sidebar. Nothing on the screen needs one either:
#     ``GET /roles/`` takes no branch at all and ``GET /users/all`` derives the
#     school from the caller's own admin profile.
#
# "Manage" here is create → widen → retire, against one role
#     A role's whole life, and each assertion is made on the reloaded register or
#     on the Preview screen rather than on the success toast, so a write the
#     frontend announced but that never reached the database fails on the
#     following step instead of passing quietly. The permissions the role ends up
#     holding are checked against ``GET /roles/`` as well, because the editor's
#     radio grid is rendered from a client-side map of module → level: a grant
#     the page displays but never sent (``handlePermissionChange`` silently drops
#     a level whose permission row it cannot find, adding id 0 to nothing) would
#     look identical on screen. The final delete also leaves the role table
#     exactly as provisioning found it — a role is a *global* record here, not a
#     per-school one, so leaving spares behind would inflate every other school's
#     Access Roles tab.
#
# One thing this unit deliberately does not do: rename the role
#     The Edit screen offers a "Role Name *" box, validates it, and posts it —
#     but ``RoleUpdate`` (newschoolapp/api/api_models/roles.py) declares
#     ``permissions`` and nothing else, so ``update()`` applies the grid and drops
#     the name. Whether role names should be immutable once handed out is a
#     product question, not a defect anyone can settle from the test suite, so
#     this test edits the grid — the thing an access role *is* — and asserts no
#     rename. Do not "fix" it by adding ``name`` to ``RoleUpdate``: that is adding
#     a request parameter the backend never accepted.

MANAGE_SCENARIO = "finance_only"

# The role this unit opens, widens and then retires. "TEST" is the prefix the
# orphan sweeper matches on; the run tag keeps parallel agents off each other's
# names, which matters more here than usual because ``roles.name`` is globally
# unique and a collision is a flat 400 on create.
MANAGE_ROLE_NAME = f"TEST Bursary Clerk {run_tag()}"

# Rows of the editor's permission grid, named exactly as
# access_roles/role_module.ts labels them, with the module each one writes.
MANAGE_GRID_FEES = "Fee Management"
MANAGE_GRID_STUDENTS = "Students"
MANAGE_GRID_PAYROLL = "Staff Payroll"
MANAGE_GRID_MODULES = {
    MANAGE_GRID_FEES: "fees",
    MANAGE_GRID_STUDENTS: "students",
    MANAGE_GRID_PAYROLL: "staff_payroll",
}

# What the bursary clerk may do when the role is created, and what is added to it
# when it is edited. Levels are the page object's vocabulary — the two editor
# screens spell them differently on screen ("manage" vs "can manage") and
# CREATE_LEVELS / EDIT_LEVELS carry that difference.
MANAGE_INITIAL_GRANTS = {MANAGE_GRID_FEES: "manage", MANAGE_GRID_STUDENTS: "read"}
MANAGE_ADDED_GRANTS = {MANAGE_GRID_PAYROLL: "manage"}

MANAGE_EXPECTED_AFTER_CREATE = {("manage", "fees"), ("read", "students")}
MANAGE_EXPECTED_AFTER_EDIT = MANAGE_EXPECTED_AFTER_CREATE | {("manage", "staff_payroll")}

# A seeded role every school shares, used to prove the register loaded something
# before the new role is added to it.
MANAGE_SEEDED_ROLE = "SchoolAdmin"

# page.tsx renders both date columns through Intl.DateTimeFormat("en-US", {year:
# "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit"}),
# fed from the backend's own "dd-mm-yy HH:MM:SS" encoding — e.g. "August 09, 2026
# at 03:21 PM". Asserted loosely, but asserted: its parser throws on any other
# shape and the cell then reads "Invalid Date".
#
# Matched against the *cell*, never the row. A row's text is the concatenation of
# its cells with no separator ("…Bursary Clerk 6f181aAugust 9, 2026 at 03:37 PM"),
# so a pattern anchored on a word boundary before the month can never fire there —
# the run tag's last character runs straight into "August".
MANAGE_DATE_CELL = re.compile(r"^\s*[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\b")
# Role Name | Date Added | Updated On | ⋮ — so the two dates are cells 1 and 2.
MANAGE_DATE_ADDED_CELL = 1
MANAGE_UPDATED_ON_CELL = 2


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="governance.access_roles.manage.school_admin",
    title="Access & Roles",
    subtitle="SchoolAdmin creates and manages access & roles",
)
def test_school_admin_creates_and_manages_an_access_role(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A SchoolAdmin opens a new access role, widens it, and retires it.

    Every claim is made against what the next person to open the screen would
    see — the register's own row, the Preview screen's grid, and the role as
    ``GET /roles/`` actually stores it.
    """
    ctx = provisioned_school
    assert ACCESS_ROLES_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {ACCESS_ROLES_MODULE!r} for "
        f"the manage path — an unlicensed school is denied the workspace outright "
        f"(see test_access_roles_denied_for_school_admin_when_module_disabled)"
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # Setup, never an assertion: ``provisioned_school`` is session-scoped, so a
    # second run of this test inside one process would meet the role it created
    # last time — and ``roles.name`` is unique, which makes that a 400 on create
    # rather than a fresh start.
    _drop_role_if_present(api, MANAGE_ROLE_NAME, token=token)

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    roles = AccessRolesPage(page, base_url)

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step("Open Access Roles from the Governance menu"):
        # No branch is picked on the way in, and that is deliberate — the
        # Governance group is hidden for a SchoolAdmin who is inside one (see the
        # section comment above).
        roles.open_from_nav()

    with demo.step("The register already lists the roles the platform ships with"):
        expect(roles.role_row(MANAGE_SEEDED_ROLE).first).to_be_visible(timeout=20_000)

    with demo.step("Open a new role for the bursary team"):
        # create_role fills the name, sets the grid, waits for the screen's own
        # "Form is ready to be saved" verdict and then saves.
        roles.create_role(name=MANAGE_ROLE_NAME, permissions=MANAGE_INITIAL_GRANTS)

    with demo.step("It may run fees, and read students — nothing else"):
        row = roles.role_row(MANAGE_ROLE_NAME)
        expect(row).to_have_count(1)
        cells = row.first.get_by_role("cell")
        expect(cells.nth(MANAGE_DATE_ADDED_CELL)).to_contain_text(MANAGE_DATE_CELL)
        expect(cells.nth(MANAGE_UPDATED_ON_CELL)).to_contain_text(MANAGE_DATE_CELL)
        _expect_grants(api, MANAGE_ROLE_NAME, MANAGE_EXPECTED_AFTER_CREATE, token=token)

    with demo.step("Preview shows exactly the access that was granted", dwell_ms=2000):
        roles.preview_role(MANAGE_ROLE_NAME)
        for item, level in MANAGE_INITIAL_GRANTS.items():
            roles.expect_permission(item, level, levels=EDIT_LEVELS)
        # A module nobody granted must still read as no access, or "the grid
        # shows what was granted" would pass against a grid that shows everything.
        roles.expect_permission(MANAGE_GRID_PAYROLL, "no-access", levels=EDIT_LEVELS)
        roles.back_to_register()

    with demo.step("The bursary takes on payroll, so widen the role to match"):
        roles.edit_role(name=MANAGE_ROLE_NAME, permissions=MANAGE_ADDED_GRANTS)

    with demo.step("The widened role keeps everything it already had", dwell_ms=2000):
        _expect_grants(api, MANAGE_ROLE_NAME, MANAGE_EXPECTED_AFTER_EDIT, token=token)
        roles.preview_role(MANAGE_ROLE_NAME)
        roles.expect_permission(MANAGE_GRID_PAYROLL, "manage", levels=EDIT_LEVELS)
        for item, level in MANAGE_INITIAL_GRANTS.items():
            roles.expect_permission(item, level, levels=EDIT_LEVELS)
        roles.back_to_register()

    with demo.step("Retire the role, and it leaves the platform for good"):
        # delete_role confirms the modal names this role, then asserts the row is
        # gone from the reloaded register.
        roles.delete_role(MANAGE_ROLE_NAME)
        assert _role_named(api, MANAGE_ROLE_NAME, token=token) is None, (
            f"{MANAGE_ROLE_NAME!r} is still on GET /roles/ after the register "
            f"reported it deleted — roles are global records, so a delete the UI "
            f"only performed locally would leave it on every school's tab"
        )
        # The seeded roles are untouched: a delete that took the role table with
        # it would fail here.
        expect(roles.role_row(MANAGE_SEEDED_ROLE).first).to_be_visible(timeout=20_000)


def _role_named(api: BackendAPI, name: str, *, token: str) -> dict[str, Any] | None:
    """The role stored under `name`, read straight from ``GET /roles/``."""
    listed = api.get("/roles/", token=token)
    assert listed.status_code == 200, (
        f"could not read the role register — got {listed.status_code}: "
        f"{listed.text[:300]}"
    )
    for row in listed.json():
        if str(row.get("name", "")).strip() == name:
            return row
    return None


def _expect_grants(
    api: BackendAPI, name: str, expected: set[tuple[str, str]], *, token: str
) -> None:
    """Assert the backend stored exactly the permissions the editor showed.

    Exactly, not merely "at least": the editor writes the whole permission list
    on every save, so an edit that dropped the grants it was not asked to touch
    would still satisfy a containment check.
    """
    role = _role_named(api, name, token=token)
    assert role is not None, (
        f"{name!r} is not on GET /roles/, so the screen reported a role it never "
        f"stored"
    )
    stored = {(str(p.get("name")), str(p.get("module"))) for p in role.get("permissions", [])}
    assert stored == expected, (
        f"{name!r} holds {sorted(stored)}, not {sorted(expected)}. The editor "
        f"posts permission *ids* it looks up from GET /roles/permissions by "
        f"(module, level), and drops any level it cannot find — so a missing "
        f"grant here is a grant the screen displayed but never sent."
    )


def _drop_role_if_present(api: BackendAPI, name: str, *, token: str) -> None:
    """Setup only: clear a leftover role of this name so the create can run."""
    role = _role_named(api, name, token=token)
    if role is None:
        return
    api.delete(f"/roles/{role['id']}", token=token)
