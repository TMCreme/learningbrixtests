"""People → Home — the landing page every signed-in user always has.

Where this module lives
    ``/module/home`` (``smsfrontend/src/app/module/home/page.tsx``). The page is a
    router, not a screen: it normalises the signed-in role name and renders one
    of four views. A SchoolAdmin's role name contains "admin", so
    ``determineUserRole`` picks ``"admin"`` and the page mounts
    ``ViewsComponents/AdminView.tsx`` — a profile ``Header`` (name, role badge,
    email, date of birth, branch) over a **Recent System Activities** table fed
    by ``GET /audilog/``, with three library counters between them.

Mandatory path: the SchoolAdmin of the ``minimal`` school
    ``test_home_is_reachable_on_the_minimal_pack`` — the ledger unit
    ``people.home.always_licensed``. There is no denial unit for this module and
    there cannot be one. ``home`` sits in the ``people`` group of
    ``services/feature_pack_service.SYSTEM_MODULE_GROUPS``, and the SuperAdmin's
    only pack builder (``src/app/module/feature_flag/create/page.tsx`` and its
    ``edit/[id]`` twin) declares ``BASIC_GROUPS = ["people", "governance"]`` and
    renders every module of those two groups locked, pre-selected and exempt from
    "Clear All" — ``OPTIONAL_BASIC_MODULES = ["guardians", "families"]`` are the
    only two members of "people" a pack may drop. The people and governance
    groups being core and always on is **intended product behaviour, confirmed
    2026-08-09**, not a licensing hole.

    So this unit asserts the opposite of a denial — the module is licensed,
    offered and working on the most restricted pack the product can build — and
    deliberately adds no gate of any kind.

    ``home`` is doubly locked, and both locks are asserted
        Besides the pack builder, ``CORE_MODULES`` in
        ``src/utils/postAuthRedirect.ts`` lists ``home`` as *not licensable* at
        all: ``src/middleware.ts`` skips its feature-pack redirect for any path in
        that list, whatever the ``schoolModules`` cookie says. The comment on that
        constant is explicit that "a module the backend feature-gates must never
        appear in it" — and no backend route is gated on ``home`` except
        ``GET /guardian/{id}/wards``, which is what a *Guardian's* own home screen
        calls. The test checks the pack-level lock (the catalogue group and the
        school's own features list) and then checks that the one ``home``-gated
        route is not feature-refused for this school.

    Why a control on a module the pack really does omit
        Every frontend gate a SchoolAdmin passes on the way to this page carries a
        carve-out for the role — ``src/middleware.ts`` exempts ``isSchoolAdmin``
        from module enforcement outright, and ``/module/home`` is core on top of
        that — so "the page loaded" on its own is equally consistent with a
        licence system that refuses nobody. The test pins that down with ``fees``:
        outside the locked basic groups, omitted by this pack, held as
        ``("manage", "fees")`` by the seeded SchoolAdmin role
        (``newschoolapp/db/repository/permissions.py``), and refused
        403 "Feature not available in your plan" by
        ``utils.permissions.has_permission``. The gate bites; it just does not
        bite here, by design.

    (The other view of this page a unit covers — a pupil reading their own home
    screen — lives in ``test_student_reads_their_own_home_page`` further down,
    with its own constants and fixture.)

Why the branch is selected first, and why it is not incidental
    Two separate reasons, both structural rather than a convenience:

    * The sidebar. The "People Module" section that carries the **Home** entry is
      ``branchOnly: true`` in ``SideNavigation/nav-config.tsx``, and
      ``SideNavigation.canShowItem`` additionally resolves ``currentUserRole`` to
      ``null`` for a SchoolAdmin with no branch in ``useBranchStore`` — which
      fails the section's ``permissionsGate`` as well. With no branch there is no
      People section to find the entry in, so "the entry is offered" could not be
      asserted at all.
    * The screen. ``AdminView``'s mount effect returns early for a SchoolAdmin
      while ``currentSchoolAdminBranch?.branch_id`` is unset, so the activities
      table would sit in its skeleton state for ever and prove nothing.

    ``BranchesPage.select_branch`` fills that store (see that method for why only
    the branch row's "View" button can). On the ``minimal`` pack its hardcoded
    ``router.push("/module/community")`` lands on /auth/no-access, because
    ``community`` is not licensed here — that is the branch page's own behaviour,
    documented in ``select_branch``, and the store is written before the push.

Deliberately not asserted: the three library counters
    ``AdminDashboardCards`` renders "Requests to Approve", "Total Books" and
    "Total Book Requests", every one of them counted from the library
    (``GET /book-requests/`` and ``GET /book-statistics/total-books``, both
    ``Depends(has_permission("read", "catalogue"))``). A school without the
    library has no such numbers, so their absence here is correct and is asserted
    as such — see the note below.

    That absence is also what a **defect fix** in ``AdminView.tsx`` produces, and
    the reason this unit could not pass before it: the view used to issue those
    two fetches unconditionally, the backend answered 403 "Feature not available
    in your plan", and the axios interceptor in
    ``src/utils/handleErrorMessage.ts`` turned that detail into a hard
    ``window.location`` redirect to /auth/no-access. An admin of a school without
    the library was thrown off a page ``home`` is permanently licensed for. The
    fix is the one ``StaffView.tsx``, ``StudentDashboardTabs.tsx`` and
    ``students/[student]/page.tsx`` already apply for exactly this failure —
    ``hasModuleLicence`` from ``src/utils/moduleLicence.ts``, whose whole
    docstring is about this case. It is recorded in
    ``state/app_changes_review.md``. No gate was added: the backend refusal is
    unchanged, and the page merely stopped asking for data it knows it will be
    refused.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import unquote

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.credentials import read_test_mode
from tests.fixtures.data_factories import make_person
from tests.flows.school_provisioning import (
    BRANCH_NAME,
    DEFAULT_LOCATION,
    STUDENT_BLOOD_TYPE,
    STUDENT_DATE_OF_BIRTH,
    STUDENT_ROLE,
    Credentials,
    SchoolContext,
)
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

HOME_MODULE = "home"
# config/module_catalog.py's route for this module.
HOME_ROUTE = "home"

# The floor case: the most restricted pack the product can actually build.
MANDATORY_SCENARIO = "minimal"

SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# ── what makes the module mandatory ──────────────────────────────────────────
# src/app/module/feature_flag/create/page.tsx — the SuperAdmin's only surface for
# building a pack. Every module of a "basic" group is rendered locked and forced
# into the pack; only these two are exempt.
BASIC_GROUPS = ("people", "governance")
OPTIONAL_BASIC_MODULES = frozenset({"guardians", "families"})
PEOPLE_GROUP = "people"

# src/utils/postAuthRedirect.ts — paths middleware.ts never feature-gates at all.
CORE_MODULES = frozenset(
    {"groups", "home", "dashboard", "school_admin_dashboard", "messages", "notifications"}
)

# The only backend route gated on ("read", "home") — api/routes/guardian.py. It
# is what a signed-in Guardian's own home screen calls, and it is asked for here
# purely to show that the `home` key itself passes the feature gate for this
# school: the id is deliberately one no guardian has, so the handler's own
# 404 GUARDIAN_NOT_FOUND is the *expected* answer. has_permission is a route
# dependency solved long before the row is looked up, so reaching that 404 is
# proof the licence was accepted.
HOME_GATED_PATH = "/guardian/99999999/wards"

# What AdminView's mount effect actually asks for (auditLogHandler.getAuditLogs,
# five rows, plus the branch_id getBranchIdParam appends once a branch is picked).
HOME_ACTIVITIES_PATH = "/audilog/?skip=0&limit=5"

# A module the same pack omits, *outside* the locked basic groups, that the
# backend really does gate — the control proving the licence is enforced rather
# than decorative. The SchoolAdmin role holds ("manage", "fees") in
# newschoolapp/db/repository/permissions.py, so a refusal can only come from the
# pack. Any fee id will do: has_permission runs as a route dependency, before the
# handler ever looks the row up.
ENFORCED_UNLICENSED_MODULE = "fees"
ENFORCED_UNLICENSED_PATH = "/fees/1"
# newschoolapp/utils/permissions.py, the feature-pack branch of has_permission.
FEATURE_PACK_403 = re.compile(r"feature not available in your plan", re.I)

# The cookie every frontend gate derives its answer from, written by
# src/app/auth/login/page.tsx and refreshed by SideNavigation.
MODULES_COOKIE = "schoolModules"

# nav-config.tsx — the section the "Home" entry lives in, and the entry itself.
# The section is branchOnly, so both only exist once a branch has been picked.
NAV_SECTION_PEOPLE = re.compile(r"^\s*People Module\s*$", re.I)
NAV_HOME = re.compile(r"^\s*Home\s*$", re.I)

# ── AdminView's own chrome (home/components/Header.tsx, SystemActivities.tsx) ──
# The role badge Header renders beside the name: roles.name upper-cased.
HOME_ROLE_BADGE = re.compile(r"^\s*SCHOOLADMIN\s*$")
HOME_EMAIL_LABEL = re.compile(r"^\s*Email\s*$", re.I)
ACTIVITIES_HEADING = re.compile(r"^\s*Recent System Activities\s*$", re.I)
ACTIVITIES_COLUMNS = ("Action", "Resource", "User", "Time", "Details")
VIEW_ADMIN_DASHBOARD = re.compile(r"^\s*View Admin Dashboard\s*$", re.I)
# Rendered only by the resolved branch of SystemActivities — the loading skeleton
# repeats the heading and the column headers, so this footer is what says the
# mount fetch came back.
ACTIVITIES_FOOTER = re.compile(r"Showing\s+\d+\s+recent activit", re.I)
# SchoolAdmin-only footer link through to the full log.
ACTIVITIES_FULL_LOG = re.compile(r"^\s*View full activities\s*$", re.I)

# The two failure panels AdminView can render instead of its content.
DASHBOARD_LOAD_FAILURE = re.compile(r"Failed to load dashboard data", re.I)
ACTIVITIES_LOAD_FAILURE = re.compile(r"Failed to load activities", re.I)

# AdminDashboardCards.tsx — the three library counters. Absent on a pack without
# the library; see the module docstring.
LIBRARY_CARDS = ("Requests to Approve", "Total Books", "Total Book Requests")
LIBRARY_MODULE = "catalogue"

# Where the frontend sends a user it has decided is not allowed in
# (src/app/auth/no-access/page.tsx, reached by handleErrorMessage's interceptor).
DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")


@pytest.mark.school_admin
@pytest.mark.scenario(MANDATORY_SCENARIO)
def test_home_is_reachable_on_the_minimal_pack(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """The floor case still has a home page: licensed, offered and answering.

    Ledger unit ``people.home.always_licensed``. See the module docstring —
    ``home`` is in the ``people`` group, the pack builder locks that whole group
    into every pack, and ``src/utils/postAuthRedirect.ts`` lists it as core on
    top of that. Both are intended product behaviour, confirmed 2026-08-09.

    Read-only throughout: nothing is created, so there is nothing to sweep. The
    school's own provisioning is all the state this needs.
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
    groups = {
        str(g.get("group")): [str(m) for m in (g.get("modules") or [])]
        for g in (catalogue.json().get("groups") or [])
    }
    assert HOME_MODULE in groups.get(PEOPLE_GROUP, []), (
        f"{HOME_MODULE!r} is no longer in the {PEOPLE_GROUP!r} group of the "
        f"backend catalogue (services/feature_pack_service.py). The create-pack "
        f"form locks a module in because of the group it belongs to, so that "
        f"membership is the whole reason this module is mandatory. "
        f"Groups: { {k: sorted(v) for k, v in groups.items()} }"
    )
    locked = {
        module
        for name in BASIC_GROUPS
        for module in groups.get(name, [])
        if module not in OPTIONAL_BASIC_MODULES
    }
    assert HOME_MODULE in locked, (
        f"{HOME_MODULE!r} is no longer one of the modules the SuperAdmin's "
        f"create-pack form forces into every pack, so a school can now be sold a "
        f"plan with no landing page at all and this unit's premise is gone. That "
        f"is a product change, not a test failure to paper over — re-read "
        f"config/feature_scenarios.yaml's `minimal` note and rewrite this unit "
        f"as a real denial test. Locked: {sorted(locked)}"
    )
    assert HOME_MODULE in CORE_MODULES, (
        f"{HOME_MODULE!r} has been dropped from CORE_MODULES in "
        f"src/utils/postAuthRedirect.ts, which is the list src/middleware.ts "
        f"skips its feature-pack redirect for. The second of the module's two "
        f"locks is gone."
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
        f"the {MANDATORY_SCENARIO!r} floor and nothing below is about licensing. "
        f"Provisioning phase A assigns one — check that it did."
    )
    licensed = {str(m) for m in (body.get("modules") or [])}
    assert licensed == requested | locked, (
        f"{ctx.school_name!r}'s licence is not 'what the {MANDATORY_SCENARIO!r} "
        f"pack requested plus the locked basic modules'. Requested "
        f"{sorted(requested)}; locked {sorted(locked)}; got {sorted(licensed)}. "
        f"Unexpectedly granted: {sorted(licensed - (requested | locked))}; "
        f"expected but missing: {sorted((requested | locked) - licensed)}."
    )
    assert HOME_MODULE in licensed, (
        f"{ctx.school_name!r} — the most restricted pack this product can build — "
        f"is not licensed for {HOME_MODULE!r}. Every role in the app lands on "
        f"/module/{HOME_ROUTE}, so a school has just lost its front door. "
        f"Licensed: {sorted(licensed)}"
    )

    # ── 2. The licence is enforced for this user, on a module outside the lock ─
    #
    # Without this, everything below is equally consistent with a feature-pack
    # system that never refuses anybody — and /module/home is exempt from the
    # middleware gate twice over (see the module docstring).
    assert ENFORCED_UNLICENSED_MODULE not in licensed, (
        f"{ctx.school_name!r} is now licensed for {ENFORCED_UNLICENSED_MODULE!r}, "
        f"so it can no longer serve as the control that the feature gate bites "
        f"for this user. Pick another module the {MANDATORY_SCENARIO!r} pack "
        f"omits, that is outside the locked basic groups, and that a backend "
        f"route gates on."
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
        f"does, 'home is reachable' says nothing. Body: {gated.text[:300]}"
    )
    assert FEATURE_PACK_403.search(gated.text), (
        f"{ENFORCED_UNLICENSED_PATH} was refused, but not by the feature pack — "
        f"the detail should be 'Feature not available in your plan'. "
        f"Body: {gated.text[:300]}"
    )

    # ── 3. Offered: the sidebar entry, once the admin is inside a branch ──────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Mandatory, not a convenience: the People Module section is branchOnly, and
    # AdminView's mount effect refuses to fetch anything for a SchoolAdmin until
    # the branch store is filled. See the module docstring. On this pack the
    # click's hardcoded push to /module/community lands on /auth/no-access, which
    # select_branch tolerates by design — the store is written before the push.
    assert ctx.branches, (
        f"{ctx.school_name!r} was provisioned without a branch, so the People "
        f"Module section can never render for its SchoolAdmin and AdminView "
        f"never fetches. Provisioning phase B always creates one."
    )
    branch_name = str(ctx.branches[0]["name"])
    BranchesPage(page, frontend_base_url).select_branch(branch_name)

    # Asking for the route by hand is the request middleware.ts actually sees,
    # and the sidebar only exists inside /module/* (src/app/module/layout.tsx).
    goto_module(page, frontend_base_url, HOME_ROUTE)

    expect(page.get_by_text(NAV_SECTION_PEOPLE).first).to_be_visible(timeout=30_000)
    # Scoped to the sidebar: "Home" is a common word elsewhere on the page
    # (Header renders a "Home Address" detail), so an unscoped text match would
    # pass on chrome that is not the nav.
    nav = page.get_by_role("navigation")
    expect(nav.get_by_role("link", name=as_pattern(NAV_HOME)).first).to_be_visible(
        timeout=30_000
    )
    expect(nav.locator(f'a[href="/module/{HOME_ROUTE}"]').first).to_be_visible()

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
    assert HOME_MODULE in cookie_modules, (
        f"{HOME_MODULE!r} is missing from this session's {MODULES_COOKIE!r} "
        f"cookie. /module/{HOME_ROUTE} is in CORE_MODULES so src/middleware.ts "
        f"would still let it through, but every other gate that reads this cookie "
        f"— hasModuleLicence, the nav's module gate — would now treat the app's "
        f"own landing page as unlicensed."
    )

    # ── 4. Working: the admin's home really renders, and keeps them on it ─────
    #
    # Header draws straight from the auth store, so it is on screen before any
    # fetch resolves — it is asserted first so that a failure further down cannot
    # be confused with "the page never mounted".
    expect(page.get_by_text(HOME_ROLE_BADGE).first).to_be_visible(timeout=30_000)
    expect(page.get_by_text(HOME_EMAIL_LABEL).first).to_be_visible()
    expect(
        page.get_by_text(as_pattern(re.escape(ctx.school_admin.email))).first
    ).to_be_visible()

    # The activities panel, resolved rather than skeletal. This is also where a
    # regression of the AdminView defect recorded in state/app_changes_review.md
    # would surface: the unlicensed library fetch 403s, the axios interceptor
    # hard-redirects to /auth/no-access, and this footer never appears.
    expect(
        page.get_by_role("heading", name=as_pattern(ACTIVITIES_HEADING))
    ).to_be_visible(timeout=30_000)
    expect(page.get_by_text(ACTIVITIES_FOOTER).first).to_be_visible(timeout=30_000)
    expect(
        page.get_by_role("button", name=as_pattern(VIEW_ADMIN_DASHBOARD)).first
    ).to_be_visible()
    # Anchored on ``thead th`` rather than on ``get_by_role("columnheader")``:
    # SystemActivities.tsx writes a bare <th> with no ``scope``, and Playwright
    # resolves such a cell to ``cell`` rather than inferring ``columnheader``
    # from its position in the header row — so a columnheader query matches
    # nothing on this panel at all. Same reasoning as
    # BranchesPage.expect_column_headers.
    for column in ACTIVITIES_COLUMNS:
        expect(
            page.locator("thead th")
            .filter(has_text=as_pattern(rf"^\s*{re.escape(column)}\s*$"))
            .first
        ).to_be_visible()
    # The SchoolAdmin-only way through to the full register, which is itself a
    # locked governance module on this pack.
    expect(page.get_by_text(ACTIVITIES_FULL_LOG).first).to_be_visible()

    # Neither of AdminView's two failure panels: this school is entitled to
    # everything the page still asks for.
    expect(page.get_by_text(DASHBOARD_LOAD_FAILURE)).to_have_count(0)
    expect(page.get_by_text(ACTIVITIES_LOAD_FAILURE)).to_have_count(0)

    assert not DENIAL_URL.search(page.url), (
        f"the SchoolAdmin of {ctx.school_name!r} ended up at {page.url!r} asking "
        f"for a module their pack permanently licenses. `home` is core and always "
        f"on by design — a denial here is a regression, not a gate to keep."
    )
    assert page.url.rstrip("/").endswith(f"/module/{HOME_ROUTE}"), (
        f"expected to still be on /module/{HOME_ROUTE}, but the app moved to "
        f"{page.url!r}"
    )

    # The library counters belong to a module this pack omits, so the page must
    # not be showing them — and, more to the point, must not be fetching them.
    # See the module docstring: doing so is what used to evict this admin.
    assert LIBRARY_MODULE not in licensed, (
        f"{ctx.school_name!r} is now licensed for {LIBRARY_MODULE!r}, so the "
        f"library counters below would legitimately render and this check no "
        f"longer means anything. Re-read the {MANDATORY_SCENARIO!r} pack."
    )
    # Not a licensing assertion in its own right — the backend already refuses
    # the data. This is the visible edge of the AdminView fix.
    for card in LIBRARY_CARDS:
        expect(
            page.get_by_text(as_pattern(rf"^\s*{re.escape(card)}\s*$"))
        ).to_have_count(0)

    # ── 5. And the module's API surface answers this admin ────────────────────
    # The one route in the product gated on ("read", "home"). A 404 is the
    # expected answer for a guardian id nobody has; what matters is that the
    # request got *past* the feature gate to reach the handler at all.
    home_gated = api.get(HOME_GATED_PATH, token=token)
    assert home_gated.status_code != 403, (
        f"GET {HOME_GATED_PATH} — the only route declared "
        f"Depends(has_permission('read', {HOME_MODULE!r})) — answered 403 for the "
        f"SchoolAdmin of {ctx.school_name!r}, whose pack licenses "
        f"{HOME_MODULE!r}. Body: {home_gated.text[:300]}"
    )
    assert not FEATURE_PACK_403.search(home_gated.text), (
        f"GET {HOME_GATED_PATH} was refused by the feature pack even though "
        f"{HOME_MODULE!r} is licensed: {home_gated.text[:300]}"
    )
    assert home_gated.status_code in (200, 404), (
        f"GET {HOME_GATED_PATH} answered {home_gated.status_code}; the licence is "
        f"accepted, so the handler should answer either the wards (200) or "
        f"GUARDIAN_NOT_FOUND (404). Body: {home_gated.text[:300]}"
    )

    # …and what the admin's home screen itself mounts on.
    branch_id = ctx.branches[0].get("id")
    activities_path = HOME_ACTIVITIES_PATH + (
        f"&branch_id={int(branch_id)}" if branch_id else ""
    )
    activities = api.get(activities_path, token=token)
    assert activities.status_code == 200, (
        f"GET {activities_path} — the single fetch AdminView makes for a "
        f"SchoolAdmin — answered {activities.status_code} for "
        f"{ctx.school_name!r}. It is gated on ('read', 'access_roles'), which is "
        f"in the same locked governance group, so a 403 would mean the lock is "
        f"gone; anything else is the route itself breaking. "
        f"Body: {activities.text[:300]}"
    )
    assert "results" in activities.json(), (
        f"GET {activities_path} did not answer the shape SystemActivities reads "
        f"(`results`, api/api_models/auditlog.py) — got keys "
        f"{sorted(activities.json())}"
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


# ─────────────── read-only path: a pupil reads their own home ────────────────
#
# Ledger unit ``people.home.view.student``. The constants below are
# ``STUDENT_``-prefixed rather than sharing the mandatory section's names: this
# file is written one unit at a time, and a shared module-level name would
# silently rebind under whichever section is appended last.
#
# What the pupil actually gets
#     ``page.tsx`` normalises the role name — "student" matches none of the
#     admin/guardian/teacher/staff tests in ``determineUserRole`` and falls
#     through to ``"student"`` — so the page mounts
#     ``ViewsComponents/StudentView.tsx``: the same profile ``Header`` the admin
#     view uses, over ``components/StudentDashboardTabs.tsx``.
#
# Why the pupil is seeded here instead of coming off SchoolContext
#     ``ctx.student`` is ``None`` on this scenario, and not by accident. Phase C
#     of provisioning only admits a student once a guardian exists — the
#     admission wizard's Contact Details step is the only working way to link the
#     two — and the ``minimal`` pack omits ``guardians``, one of the two optional
#     members of the otherwise locked "people" group.
#
#     Nor could this unit drive that wizard itself. ``ContactDetails.tsx`` fetches
#     ``GET /guardian/`` from its mount effect through ``apiGet`` (plain global
#     axios); on this pack that answers 403 "Feature not available in your plan",
#     and the interceptor in ``src/utils/handleErrorMessage.ts`` turns that detail
#     into a hard ``window.location`` redirect to /auth/no-access — half way
#     through admission. That is the guardians gate doing its job, not a defect.
#
#     So the pupil is created over the API instead: the same setup-only use of
#     ``api`` as ``school_provisioning._seed_fee_group``. ``POST /student/`` is
#     gated on ("manage", "students"), which this pack licenses and the seeded
#     SchoolAdmin role holds, and both ``guardian_id`` and ``class_id`` are
#     Optional on ``StudentProfileCreate`` (``api/api_models/student.py``). The
#     password is generated server-side — ``StudentService.create_student``
#     overwrites whatever is posted with the new ``student_id`` — and is read back
#     through QA mode's ``X-Test-Mode`` header, never guessed.
#
# Why no class, and why that is the correct picture rather than a thin one
#     ``classes_and_timetables`` is not on this pack, so the school has no class
#     to enrol anyone into and the Header's class fields render their "not set"
#     copy. That is exactly what a pupil of the floor-case school sees, and the
#     assertions below spell it out rather than skirting it.

STUDENT_VIEW_SCENARIO = "minimal"

# Seeded onto the pupil's record so the profile dialog has one field that is
# unmistakably *theirs* to read back. Carries the TEST prefix for the sweeper.
STUDENT_PREVIOUS_SCHOOL = "TEST Riverbank Primary"

# ── the profile card (home/components/Header.tsx) ────────────────────────────
# The badge beside the name is roles.name upper-cased; matched case-sensitively
# so it cannot be satisfied by the "Student Dashboard" heading below it.
STUDENT_ROLE_BADGE = re.compile(r"^\s*STUDENT\s*$")
STUDENT_EMAIL_LABEL = re.compile(r"^\s*Email\s*$", re.I)
STUDENT_DOB_LABEL = re.compile(r"^\s*Date of Birth\s*$", re.I)
# getIdLabel("student"), and getClassLabel() for any non-teaching role.
STUDENT_ID_LABEL = re.compile(r"^\s*Student ID\s*$", re.I)
STUDENT_CLASS_LABEL = re.compile(r"^\s*Class Assigned\s*$", re.I)
# getClassValue()/getRoleSubtitle() with no class_assigned on the profile, and
# the fee-group chip Header renders for students only. All three are the honest
# reading of a school whose pack has no classes and no fees.
STUDENT_CLASS_UNSET = re.compile(r"^\s*Not Assigned\s*$", re.I)
STUDENT_SUBTITLE_UNSET = re.compile(r"^\s*Class Not Provided\s*$", re.I)
STUDENT_FEE_GROUP_UNSET = re.compile(r"^\s*Fee Group Not Provided\s*$", re.I)
# getBranchName() suffixes " Branch" onto any branch name that does not already
# say it. The dialog further down prints the raw name, which is how the two are
# told apart.
STUDENT_HEADER_BRANCH = re.compile(rf"^\s*{re.escape(BRANCH_NAME)} Branch\s*$", re.I)

# The dialog behind Header's title="View full profile" button.
STUDENT_PROFILE_BUTTON_TITLE = "View full profile"
STUDENT_PROFILE_DIALOG = re.compile(r"^\s*Profile Details\s*$", re.I)
STUDENT_PROFILE_LABELS = ("First Name", "Other Name(s)", "Enrollment Date", "Current Level")
STUDENT_PROFILE_PREVIOUS_SCHOOL_LABEL = re.compile(r"^\s*Previous School\s*$", re.I)
STUDENT_PROFILE_BRANCH_LABEL = re.compile(r"^\s*School Branch\s*$", re.I)
STUDENT_PROFILE_CLOSE = re.compile(r"^\s*Close\s*$", re.I)

# ── the panel underneath (home/components/StudentDashboardTabs.tsx) ──────────
STUDENT_DASHBOARD_HEADING = re.compile(r"^\s*Student Dashboard\s*$", re.I)
# Each tab is dropped when its module is unlicensed (hasModuleLicence, from
# src/utils/moduleLicence.ts) precisely so its fetch cannot 403 and bounce the
# pupil to /auth/no-access — the same fix AdminView carries. So the tab strip is
# a direct reading of what this school bought, and it is asserted in both
# directions: these two modules are outside the locked basic groups and off this
# pack, …
STUDENT_TABS_OFF = {"Fees": "fees", "Library": "catalogue"}
# …while "reports" is in the *governance* group, which the pack builder locks
# into every pack exactly as it does "people" (BASIC_GROUPS). It is licensed here
# whatever config/feature_scenarios.yaml lists, so its tab must still be offered.
# It is deliberately not clicked: the panel behind it is gated on
# ("read", "reports"), which the seeded Student role does not hold, and refusing
# a pupil their published reports is a different unit's question.
STUDENT_TAB_ON = ("Reports", "reports")

# Deliberately NOT asserted: the Attendance tab's *panel*. `activeTab` initialises
# to "attendance" whatever the licence says, so the panel renders even though its
# tab button is gone. Its one fetch is harmless here — a pupil never holds
# ("read", "attendance") in db/repository/permissions.py, so the refusal is the
# permission half of has_permission ("You do not have permission to perform this
# action"), which shouldRedirectToNoAccess does not act on. Asserting either its
# presence or its absence would be pinning down cosmetics this unit is not about.

# What a pupil must not be able to do from a screen they only read.
STUDENT_ROLE_DENIAL_DETAIL = re.compile(
    r"You do not have permission to perform this action", re.I
)


@dataclass(frozen=True)
class Pupil:
    """The seeded student, and the two fields their own screen prints back."""

    creds: Credentials
    student_id: str
    previous_school: str


class _QaResponse:
    """Adapts an ``httpx`` response to what ``read_test_mode`` expects.

    ``read_test_mode`` is written against Playwright's ``Response`` and uses only
    ``header_value``/``json`` — the duck type ``tests/test_qa_mode.py`` already
    exercises it through. The QA-mode block is identical on either transport, so
    the reader is reused rather than re-implemented here.
    """

    def __init__(self, response: Any) -> None:
        self._response = response

    def header_value(self, name: str) -> str | None:
        return self._response.headers.get(name)

    def json(self) -> Any:
        return self._response.json()


def _qa_password(response: Any, *, where: str) -> str:
    """The server-generated password QA mode attached to ``response``."""
    block = read_test_mode(_QaResponse(response))
    if not block:
        raise AssertionError(
            f"No test_mode data on {where}. QA mode is not enabled on the "
            f"backend. Enable it with `touch <backend-repo>/.qa_mode_enabled` "
            f"(or QA_MODE=1) and wait for uvicorn --reload to pick it up — do "
            f"not guess the password, it is generated server-side."
        )
    password = block.get("initial_password") or next(
        iter(block.get("passwords") or []), None
    )
    assert password, (
        f"QA mode answered on {where} but carried no password: {sorted(block)}"
    )
    return str(password)


@pytest.fixture
def pupil(provisioned_school: SchoolContext, api: BackendAPI) -> Pupil:
    """Admit one pupil to the floor-case school, over the API.

    Requested *before* the ``demo`` fixture in the test signature so this setup
    happens before the camera rolls — the video is about what the pupil sees, not
    about how they came to exist. See the section header for why the admission
    wizard cannot be used on this pack.
    """
    ctx = provisioned_school
    assert ctx.branches, (
        f"{ctx.school_name!r} was provisioned without a branch, so there is no "
        f"branch to admit a pupil into. Provisioning phase B always creates one."
    )
    branch_id = int(ctx.branches[0]["id"])

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    person = make_person("student", ctx.scenario_id)
    # Letters only, for the same reason school_provisioning._person sanitises:
    # every name input in this app stores /[A-Za-z\s]/ and nothing else, so an
    # unsanitised "O'Brien" would be shown back differently from what was posted.
    first_name = re.sub(r"[^A-Za-z\s]", "", person.first_name).strip()
    other_names = re.sub(r"[^A-Za-z\s]", "", person.last_name).strip()

    response = api.post(
        "/student/",
        token=token,
        json={
            "date_of_admission": date.today().isoformat(),
            "previous_school": STUDENT_PREVIOUS_SCHOOL,
            "blood_type": STUDENT_BLOOD_TYPE,
            # Sent empty, exactly as the admission wizard posts it
            # (students/admit-student/page.tsx seeds `fees_breakdown: []` and
            # only fills it from the fees screen). It cannot be omitted:
            # api/routes/student.py rebuilds the request model with
            # `fees_breakdown=student_data.fees_breakdown`, which turns the
            # model's own `None` default into an explicit value and fails its
            # `list[StudentFeeItem]` annotation with a 422. This pupil is on the
            # `minimal` pack, which has no fees module at all, so an empty
            # breakdown is also the truthful admission here.
            "fees_breakdown": [],
            "user": {
                "first_name": first_name,
                "other_names": other_names,
                "email": person.email,
                "gender": person.gender,
                "date_of_birth": STUDENT_DATE_OF_BIRTH,
                "nationality": person.nationality,
                "residential_address": person.address,
                "location": DEFAULT_LOCATION,
                "primary_phone": person.phone,
                "school_branch_id": branch_id,
                "is_active": True,
                # Overwritten by StudentService.create_student with the generated
                # student_id; sent only because UserSignup requires the pair.
                "password": "placeholder",
                "password_confirmation": "placeholder",
                "role_id": api.role_id_for(STUDENT_ROLE),
            },
        },
    )
    assert response.status_code == 201, (
        f"could not admit a pupil to {ctx.school_name!r}: {response.status_code} "
        f"{response.text[:400]}. POST /student/ is gated on "
        f"('manage', 'students'), which the {STUDENT_VIEW_SCENARIO!r} pack "
        f"licenses and the seeded SchoolAdmin role holds."
    )
    body = response.json()
    creds = Credentials(
        email=person.email,
        password=_qa_password(response, where="POST /student/"),
        user_id=(body.get("user") or {}).get("id"),
        role_name=STUDENT_ROLE,
        first_name=first_name,
        last_name=other_names,
        role=STUDENT_ROLE,
    )
    return Pupil(
        creds=creds,
        student_id=str(body.get("student_id") or ""),
        previous_school=STUDENT_PREVIOUS_SCHOOL,
    )


@pytest.mark.student
@pytest.mark.scenario(STUDENT_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="people.home.view.student",
    title="Home",
    subtitle="Student views home",
)
def test_student_reads_their_own_home_page(
    pupil: Pupil,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A pupil signs in and reads their own record on the school's front door."""
    ctx = provisioned_school
    assert HOME_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {HOME_MODULE!r} for this unit "
        f"— it is a locked basic module, so if this ever fails the pack builder "
        f"has changed and the whole file's premise with it"
    )

    page: Page = demo.page
    student = pupil.creds

    with demo.step(f"Sign in as {student.full_name}, a pupil at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, student)

    with demo.step("Signing in drops them straight onto their own home page"):
        # Not a deep link: src/app/auth/login/page.tsx filters the role's
        # permissions down to what the school licensed, and "home" is the only
        # one of a pupil's eleven permissions this pack leaves standing — so this
        # is where a real sign-in lands them, every time.
        page.wait_for_url(re.compile(rf"/module/{HOME_ROUTE}"), timeout=30_000)
        expect(page.get_by_text(STUDENT_ROLE_BADGE).first).to_be_visible(timeout=30_000)

    with demo.step("Home is offered in their side menu too", dwell_ms=1500):
        nav = page.get_by_role("navigation")
        expect(page.get_by_text(NAV_SECTION_PEOPLE).first).to_be_visible(timeout=30_000)
        home_link = nav.get_by_role("link", name=as_pattern(NAV_HOME)).first
        expect(home_link).to_be_visible()
        home_link.click()
        page.wait_for_url(re.compile(rf"/module/{HOME_ROUTE}"), timeout=30_000)

    with demo.step("Their profile card: who they are, and what they are studying",
                   dwell_ms=2000):
        expect(
            page.get_by_role(
                "heading", name=as_pattern(rf"^\s*{re.escape(student.full_name)}\s*$")
            ).first
        ).to_be_visible(timeout=30_000)
        expect(page.get_by_text(STUDENT_ROLE_BADGE).first).to_be_visible()
        expect(page.get_by_text(STUDENT_HEADER_BRANCH).first).to_be_visible()
        # This school's pack has neither classes nor fees, so the card says so
        # rather than inventing either.
        expect(page.get_by_text(STUDENT_SUBTITLE_UNSET).first).to_be_visible()
        expect(page.get_by_text(STUDENT_FEE_GROUP_UNSET).first).to_be_visible()

    with demo.step("The details underneath are their own — right down to the "
                   "student number the school issued", dwell_ms=2500):
        expect(page.get_by_text(STUDENT_EMAIL_LABEL).first).to_be_visible()
        expect(
            page.get_by_text(as_pattern(re.escape(student.email))).first
        ).to_be_visible()
        expect(page.get_by_text(STUDENT_DOB_LABEL).first).to_be_visible()
        expect(page.get_by_text(STUDENT_ID_LABEL).first).to_be_visible()
        assert pupil.student_id, (
            "the admission response carried no student_id, so the card's ID field "
            "cannot be checked against anything"
        )
        expect(
            page.get_by_text(as_pattern(rf"^\s*{re.escape(pupil.student_id)}\s*$")).first
        ).to_be_visible()
        expect(page.get_by_text(STUDENT_CLASS_LABEL).first).to_be_visible()
        expect(page.get_by_text(STUDENT_CLASS_UNSET).first).to_be_visible()

    with demo.step("Open the full profile for the rest of the record", dwell_ms=2500):
        page.get_by_title(STUDENT_PROFILE_BUTTON_TITLE).first.click()
        dialog = page.get_by_text(STUDENT_PROFILE_DIALOG).first
        expect(dialog).to_be_visible(timeout=15_000)
        for label in STUDENT_PROFILE_LABELS:
            expect(
                page.get_by_text(as_pattern(rf"^\s*{re.escape(label)}\s*$")).first
            ).to_be_visible()
        # The two fields that could only have come from this pupil's own record:
        # the school they came from, and the branch they were admitted into. The
        # branch is matched exactly, because the card above prints the same name
        # with " Branch" appended.
        expect(page.get_by_text(STUDENT_PROFILE_PREVIOUS_SCHOOL_LABEL).first).to_be_visible()
        expect(
            page.get_by_text(as_pattern(rf"^\s*{re.escape(pupil.previous_school)}\s*$")).first
        ).to_be_visible()
        expect(page.get_by_text(STUDENT_PROFILE_BRANCH_LABEL).first).to_be_visible()
        expect(
            page.get_by_text(as_pattern(rf"^\s*{re.escape(BRANCH_NAME)}\s*$")).first
        ).to_be_visible()

    with demo.step("Close it — and the dashboard below shows only what this "
                   "school actually bought", dwell_ms=2000):
        page.get_by_role("button", name=as_pattern(STUDENT_PROFILE_CLOSE)).first.click()
        expect(page.get_by_text(STUDENT_PROFILE_DIALOG)).to_have_count(0)

        expect(
            page.get_by_role("heading", name=as_pattern(STUDENT_DASHBOARD_HEADING)).first
        ).to_be_visible(timeout=20_000)

        # Read from the cookie rather than from ctx.feature_modules, because that
        # is what hasModuleLicence itself reads — and because the effective
        # licence is "what the pack asked for *plus* the locked basic groups",
        # which is why Reports below is on a pack that never named it. A missing
        # cookie makes hasModuleLicence permissive, so every tab would render and
        # the absences below would be meaningless.
        cookie_modules = _school_modules_cookie(page)
        assert cookie_modules is not None, (
            f"the {MODULES_COOKIE!r} cookie was never written for this pupil's "
            f"session, so hasModuleLicence falls back to 'unknown means allowed' "
            f"and the tab strip stops reflecting the licence at all. Both "
            f"src/app/auth/login/page.tsx and SideNavigation are meant to set it."
        )
        for label, module in STUDENT_TABS_OFF.items():
            assert module not in cookie_modules, (
                f"this school is now licensed for {module!r}, so its {label!r} "
                f"tab would legitimately render and this check means nothing. "
                f"Re-read config/feature_scenarios.yaml's {STUDENT_VIEW_SCENARIO!r}."
            )
            expect(
                page.get_by_role("button", name=as_pattern(rf"^\s*{label}\s*$"))
            ).to_have_count(0)

        on_label, on_module = STUDENT_TAB_ON
        assert on_module in cookie_modules, (
            f"{on_module!r} is missing from this school's licence even though it "
            f"sits in the locked 'governance' group, so the {on_label!r} tab "
            f"cannot be expected either. That is a pack-builder change, not a "
            f"test failure to paper over."
        )
        expect(
            page.get_by_role("button", name=as_pattern(rf"^\s*{on_label}\s*$")).first
        ).to_be_visible()

        # The whole point of dropping those tabs: a pupil stays on the page they
        # are permanently licensed for instead of being thrown to /auth/no-access
        # by a fetch their school was never entitled to make.
        assert not DENIAL_URL.search(page.url), (
            f"the pupil of {ctx.school_name!r} ended up at {page.url!r}. `home` is "
            f"core and always on — a denial here is a regression, not a gate."
        )
        assert page.url.rstrip("/").endswith(f"/module/{HOME_ROUTE}"), (
            f"expected to still be on /module/{HOME_ROUTE}, but the app moved to "
            f"{page.url!r}"
        )

    with demo.step("Home is a pupil's to read, never to write", dwell_ms=2000):
        _expect_home_is_read_only_for_student(api, ctx, pupil)


def _expect_home_is_read_only_for_student(
    api: BackendAPI, ctx: SchoolContext, pupil: Pupil
) -> None:
    """The backend gives this pupil the same read-only deal the screen does.

    Without it the UI half proves only that the *frontend* renders no write
    controls, which a hand-built request would walk straight past. The pupil's
    own record is the thing on screen, so the people-module writes behind it are
    what is checked: a pupil holds no ``students`` permission at all
    (db/repository/permissions.py), so every one of these is refused by the
    permission half of ``has_permission`` — never by the feature pack, which
    licenses ``students`` here.
    """
    token = api.login(pupil.creds.email, pupil.creds.password)["access_token"]
    assert token, f"the seeded pupil {pupil.creds.email!r} could not sign in"

    person = make_person("student-denied", ctx.scenario_id)
    branch_id = int(ctx.branches[0]["id"])
    refusals = {
        "admit_another": api.post(
            "/student/",
            token=token,
            json={
                "date_of_admission": date.today().isoformat(),
                "user": {
                    "first_name": "TEST",
                    "other_names": "Denied Pupil",
                    "email": person.email,
                    "gender": person.gender,
                    "date_of_birth": STUDENT_DATE_OF_BIRTH,
                    "nationality": person.nationality,
                    "residential_address": person.address,
                    "primary_phone": person.phone,
                    "school_branch_id": branch_id,
                    "is_active": True,
                    "password": "placeholder",
                    "password_confirmation": "placeholder",
                    "role_id": api.role_id_for(STUDENT_ROLE),
                },
            },
        ),
        # Their own record included: the id is arbitrary because has_permission is
        # a route dependency, solved before the handler looks any row up.
        "edit_a_record": api.put(
            f"/student/{pupil.creds.user_id or 1}",
            token=token,
            json={"previous_school": "TEST Rewritten By The Pupil"},
        ),
        "read_the_register": api.get(f"/student/?branch_id={branch_id}", token=token),
    }
    for label, response in refusals.items():
        assert response.status_code == 403, (
            f"{label}: a pupil holds no 'students' permission, so the backend "
            f"must refuse with 403 — got {response.status_code}: "
            f"{response.text[:300]}"
        )
        detail = str((response.json() or {}).get("detail", ""))
        assert STUDENT_ROLE_DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right, but the reason should be the role's, not the "
            f"school's — {ctx.school_name!r} is licensed for 'students'. "
            f"Got {detail!r}"
        )


# ───────── read-only path: a SchoolAdmin reads their school's front door ──────
#
# Ledger unit ``people.home.view.school_admin``, and the narrated twin of
# ``test_home_is_reachable_on_the_minimal_pack`` above: that unit proves the
# module *cannot be dropped* from a pack and does its work mostly against the
# API; this one is the walkthrough — what an administrator of the floor-case
# school actually sees when they open /module/home, in the order they see it.
#
# What AdminView puts on the page
#     ``components/Header.tsx`` (the profile card, straight off the auth store,
#     so it is on screen before any fetch resolves) over
#     ``components/SystemActivities.tsx`` (the audit feed, ``GET /audilog/``),
#     and — on a school licensed for the library — the three counters of
#     ``components/AdminDashboardCards.tsx``. This pack has no ``catalogue``, so
#     those three must be neither rendered *nor fetched*: the fetch is what used
#     to 403 and bounce the admin to /auth/no-access (state/app_changes_review.md).
#
# Constants are ``ADMIN_VIEW_``-prefixed for the reason given in the student
# section: this file is appended to one unit at a time.

ADMIN_VIEW_SCENARIO = "minimal"

# Header, for a SchoolAdmin. The badge is roles.name upper-cased; the ID *label*
# is deliberately not asserted — getIdLabel() has no entry for "schooladmin" and
# renders the literal "Not Provided" beside a perfectly real admin id, which is
# cosmetics this unit is not about. The id itself is asserted, because it could
# only have come from this administrator's own record.
ADMIN_VIEW_ROLE_BADGE = re.compile(r"^\s*SCHOOLADMIN\s*$")
ADMIN_VIEW_EMAIL_LABEL = re.compile(r"^\s*Email\s*$", re.I)
ADMIN_VIEW_DOB_LABEL = re.compile(r"^\s*Date of Birth\s*$", re.I)
ADMIN_VIEW_HEADER_BRANCH = re.compile(rf"^\s*{re.escape(BRANCH_NAME)} Branch\s*$", re.I)

# The activities panel and its two ways onward.
ADMIN_VIEW_ACTIVITIES_HEADING = re.compile(r"^\s*Recent System Activities\s*$", re.I)
ADMIN_VIEW_ACTIVITIES_COLUMNS = ("Action", "Resource", "User", "Time", "Details")
ADMIN_VIEW_ACTIVITIES_FOOTER = re.compile(r"Showing\s+\d+\s+recent activit", re.I)
ADMIN_VIEW_DASHBOARD_BUTTON = re.compile(r"^\s*View Admin Dashboard\s*$", re.I)
ADMIN_VIEW_FULL_LOG = re.compile(r"^\s*View full activities\s*$", re.I)
ADMIN_VIEW_ACTIVITIES_FAILURE = re.compile(r"Failed to load activities", re.I)
ADMIN_VIEW_DASHBOARD_FAILURE = re.compile(r"Failed to load dashboard data", re.I)


@pytest.mark.school_admin
@pytest.mark.scenario(ADMIN_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="people.home.view.school_admin",
    title="Home",
    subtitle="SchoolAdmin views home",
)
def test_school_admin_reads_their_home_page(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """The administrator of the floor-case school opens their own front door."""
    ctx = provisioned_school
    assert HOME_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {HOME_MODULE!r} for this unit "
        f"— it is a locked basic module, so if this ever fails the pack builder "
        f"has changed and the whole file's premise with it"
    )
    assert ctx.branches, (
        f"{ctx.school_name!r} was provisioned without a branch, so the People "
        f"Module section can never render for its SchoolAdmin and AdminView never "
        f"fetches. Provisioning phase B always creates one."
    )
    branch_name = str(ctx.branches[0]["name"])

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    admin = ctx.school_admin

    # Setup, never an assertion about /users/login: the record the page renders
    # from, so the card below is read back against this administrator's own row
    # rather than against a literal.
    login_body = api.login(admin.email, admin.password)
    profile = login_body.get("user_profile") or {}
    admin_id = str(((profile.get("admin_profile") or {}).get("admin_id")) or "")
    assert admin_id, (
        f"the login response for {admin.email!r} carried no admin_profile.admin_id, "
        f"which is what Header prints in its ID field (adminProfile?.admin_id). "
        f"Profile keys: {sorted(profile)}"
    )

    with demo.step(f"Sign in as {admin.full_name}, who runs {ctx.school_name}"):
        login_as(page, base_url, admin)

    with demo.step(f"Open {branch_name} — an administrator belongs to no branch",
                   dwell_ms=2000):
        # Mandatory, not scene-setting: the People Module section is branchOnly
        # and AdminView's mount effect refuses to fetch anything for a SchoolAdmin
        # until the branch store is filled. On this pack select_branch's hardcoded
        # push to /module/community lands on /auth/no-access, which it tolerates by
        # design — the store is written before the push.
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Home is where the People menu starts", dwell_ms=1500):
        goto_module(page, base_url, HOME_ROUTE)
        expect(page.get_by_text(NAV_SECTION_PEOPLE).first).to_be_visible(timeout=30_000)
        # Scoped to the sidebar: Header renders a "Home Address" detail, so an
        # unscoped text match would pass on chrome that is not the nav.
        nav = page.get_by_role("navigation")
        home_link = nav.get_by_role("link", name=as_pattern(NAV_HOME)).first
        expect(home_link).to_be_visible(timeout=30_000)
        home_link.click()
        page.wait_for_url(re.compile(rf"/module/{HOME_ROUTE}"), timeout=30_000)

    with demo.step("Their own card: who is signed in, and to which branch",
                   dwell_ms=2500):
        expect(
            page.get_by_role(
                "heading", name=as_pattern(rf"^\s*{re.escape(admin.full_name)}\s*$")
            ).first
        ).to_be_visible(timeout=30_000)
        expect(page.get_by_text(ADMIN_VIEW_ROLE_BADGE).first).to_be_visible()
        expect(page.get_by_text(ADMIN_VIEW_HEADER_BRANCH).first).to_be_visible()
        expect(page.get_by_text(ADMIN_VIEW_EMAIL_LABEL).first).to_be_visible()
        expect(
            page.get_by_text(as_pattern(re.escape(admin.email))).first
        ).to_be_visible()
        expect(page.get_by_text(ADMIN_VIEW_DOB_LABEL).first).to_be_visible()
        # The administrator number the backend issued when the school was created
        # (UserService.create_school_admin) — the one field on this card that no
        # other user could be showing.
        expect(
            page.get_by_text(as_pattern(rf"^\s*{re.escape(admin_id)}\s*$")).first
        ).to_be_visible()

    with demo.step("Underneath it, everything that has happened in the school",
                   dwell_ms=2500):
        expect(
            page.get_by_role("heading", name=as_pattern(ADMIN_VIEW_ACTIVITIES_HEADING))
        ).to_be_visible(timeout=30_000)
        # The footer is what says the mount fetch came back: the loading skeleton
        # repeats the heading and the column headers, but never this line.
        expect(page.get_by_text(ADMIN_VIEW_ACTIVITIES_FOOTER).first).to_be_visible(
            timeout=30_000
        )
        # Anchored on ``thead th`` rather than on get_by_role("columnheader"):
        # SystemActivities.tsx writes a bare <th> with no ``scope``, which
        # Playwright resolves to ``cell``. Same reasoning as
        # BranchesPage.expect_column_headers.
        for column in ADMIN_VIEW_ACTIVITIES_COLUMNS:
            expect(
                page.locator("thead th")
                .filter(has_text=as_pattern(rf"^\s*{re.escape(column)}\s*$"))
                .first
            ).to_be_visible()
        expect(page.get_by_text(ADMIN_VIEW_ACTIVITIES_FAILURE)).to_have_count(0)
        expect(page.get_by_text(ADMIN_VIEW_DASHBOARD_FAILURE)).to_have_count(0)

    with demo.step("…and the two ways on from it that only an administrator gets",
                   dwell_ms=2000):
        expect(
            page.get_by_role("button", name=as_pattern(ADMIN_VIEW_DASHBOARD_BUTTON)).first
        ).to_be_visible()
        # SystemActivities renders this footer link only for a SchoolAdmin, and it
        # leads to audit_trails — itself a locked governance module on this pack.
        expect(page.get_by_text(ADMIN_VIEW_FULL_LOG).first).to_be_visible()

    with demo.step("The page shows only what this school actually bought",
                   dwell_ms=2000):
        cookie_modules = _school_modules_cookie(page)
        assert cookie_modules is not None, (
            f"the {MODULES_COOKIE!r} cookie was never written for this session, so "
            f"hasModuleLicence falls back to 'unknown means allowed' and the "
            f"absences below stop reflecting the licence at all."
        )
        assert LIBRARY_MODULE not in cookie_modules, (
            f"this school is now licensed for {LIBRARY_MODULE!r}, so AdminView's "
            f"three library counters would legitimately render and this check "
            f"means nothing. Re-read config/feature_scenarios.yaml's "
            f"{ADMIN_VIEW_SCENARIO!r}."
        )
        for card in LIBRARY_CARDS:
            expect(
                page.get_by_text(as_pattern(rf"^\s*{re.escape(card)}\s*$"))
            ).to_have_count(0)

        # The whole point of not rendering them: the admin stays on the page they
        # are permanently licensed for, instead of being thrown to /auth/no-access
        # by a fetch their school was never entitled to make.
        assert not DENIAL_URL.search(page.url), (
            f"the SchoolAdmin of {ctx.school_name!r} ended up at {page.url!r}. "
            f"`home` is core and always on — a denial here is a regression."
        )
        assert page.url.rstrip("/").endswith(f"/module/{HOME_ROUTE}"), (
            f"expected to still be on /module/{HOME_ROUTE}, but the app moved to "
            f"{page.url!r}"
        )


# ─────────────── read-only path: a teacher reads their own home ──────────────
#
# Ledger unit ``people.home.view.teacher``.
#
# What a teacher gets
#     ``page.tsx``'s ``determineUserRole`` matches "teacher" and mounts
#     ``ViewsComponents/StaffView.tsx``: the same profile ``Header`` as every
#     other role, plus two panels that belong to *other* modules —
#     ``RecentPayslips`` (staff_payroll) and ``StaffBookDashboard`` (catalogue).
#     On the floor-case pack the school has neither, so StaffView's
#     ``hasModuleLicence`` reads drop both and the teacher's home is the profile
#     card alone. That is the honest picture of this school, not a thin one: the
#     panels are absent because the school never bought them.
#
#     Dropping them is load-bearing rather than cosmetic for the library half:
#     ``GET /book-requests/student/{id}`` is gated on ("read", "catalogue"), and
#     the 403 "Feature not available in your plan" it answers would be turned
#     into a hard redirect to /auth/no-access by the axios interceptor — i.e. the
#     teacher could not stay on their own home page. That refusal is asserted
#     directly, so the panel's absence is tied to the reason for it.
#
#     Not asserted the same way: ``GET /payroll/me/payslips``, which
#     RecentPayslips calls. Unlike every other route in api/routes/payroll.py it
#     carries no ``has_permission`` dependency at all, so it is *not* refused for
#     an unlicensed school. Whether that gate is missing by oversight is a
#     product question, and this unit neither asserts the hole away nor freezes
#     it in place — it asserts only what the screen does, which is to withhold a
#     payslips panel from a school with no payroll module.

TEACHER_VIEW_SCENARIO = "minimal"

# Header, for a teacher.
TEACHER_VIEW_ROLE_BADGE = re.compile(r"^\s*TEACHER\s*$")
TEACHER_VIEW_EMAIL_LABEL = re.compile(r"^\s*Email\s*$", re.I)
TEACHER_VIEW_ID_LABEL = re.compile(r"^\s*Teacher ID\s*$", re.I)
# getClassLabel() pluralises on the assigned-class count, and getClassValue()
# says so when there are none. `classes_and_timetables` is off this pack, so the
# school has no class to assign anybody to.
TEACHER_VIEW_CLASS_LABEL = re.compile(r"^\s*Classes Assigned\s*$", re.I)
TEACHER_VIEW_CLASS_UNSET = re.compile(r"^\s*Not Assigned\s*$", re.I)
TEACHER_VIEW_HEADER_BRANCH = re.compile(rf"^\s*{re.escape(BRANCH_NAME)} Branch\s*$", re.I)

# The two panels StaffView withholds on a pack that carries neither module, and
# the modules each one belongs to.
TEACHER_VIEW_PAYSLIPS_PANEL = re.compile(r"^\s*Recent Payslips\s*$", re.I)
TEACHER_VIEW_PAYROLL_MODULE = "staff_payroll"
TEACHER_VIEW_BOOKS_PANEL = re.compile(r"^\s*My Book Requests\s*$", re.I)
TEACHER_VIEW_LIBRARY_MODULE = "catalogue"

# The fetch StaffBookDashboard would have made, and the refusal it would have got.
TEACHER_VIEW_BOOK_REQUESTS_PATH = "/book-requests/student/{user_id}"


@pytest.mark.teacher
@pytest.mark.scenario(TEACHER_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="people.home.view.teacher",
    title="Home",
    subtitle="Teacher views home",
)
def test_teacher_reads_their_own_home_page(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A teacher signs in and reads their own record on the school's front door."""
    ctx = provisioned_school
    assert HOME_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {HOME_MODULE!r} for this unit "
        f"— it is a locked basic module, so if this ever fails the pack builder "
        f"has changed and the whole file's premise with it"
    )
    assert ctx.teacher is not None, (
        f"provisioning created no teacher for {ctx.school_name!r}. The "
        f"{TEACHER_VIEW_SCENARIO!r} pack licenses `staff`, so phase C should have "
        f"created one; without a teacher there is no home page to read."
    )
    teacher = ctx.teacher

    page: Page = demo.page
    base_url: str = demo.frontend_base_url

    # Setup, never an assertion about /users/login: the record the card is read
    # back against, so nothing below is checked against a literal this test made
    # up. Both fields come from the same profile the page renders from.
    login_body = api.login(teacher.email, teacher.password)
    profile = login_body.get("user_profile") or {}
    teacher_profile = profile.get("teacher_profile") or {}
    staff_id = str(teacher_profile.get("staff_id") or "")
    assert staff_id, (
        f"the login response for {teacher.email!r} carried no "
        f"teacher_profile.staff_id, which is what Header prints in its ID field. "
        f"Profile keys: {sorted(profile)}"
    )
    user_id = profile.get("id") or login_body.get("id")
    assert user_id, (
        f"the login response for {teacher.email!r} carried no user id, so the "
        f"book-requests fetch StaffBookDashboard makes cannot be reproduced"
    )
    # getRoleSubtitle() for a teacher is their first subject, or a placeholder.
    # Read rather than assumed: `subjects` is not on this pack, so the placeholder
    # is what this school produces — but the assertion follows the record either
    # way rather than freezing one of the two answers in.
    subjects = teacher_profile.get("subjects") or []
    expected_subtitle = (
        str((subjects[0] or {}).get("name") or "") if subjects else ""
    ) or "Job Title Not Provided"

    with demo.step(f"Sign in as {teacher.full_name}, who teaches at {ctx.school_name}",
                   dwell_ms=2500):
        login_as(page, base_url, teacher)

    with demo.step("Home is the first thing their side menu offers", dwell_ms=1500):
        expect(page.get_by_text(NAV_SECTION_PEOPLE).first).to_be_visible(timeout=30_000)
        nav = page.get_by_role("navigation")
        home_link = nav.get_by_role("link", name=as_pattern(NAV_HOME)).first
        expect(home_link).to_be_visible(timeout=30_000)
        home_link.click()
        page.wait_for_url(re.compile(rf"/module/{HOME_ROUTE}"), timeout=30_000)

    with demo.step("Their profile card: who they are, and where they teach",
                   dwell_ms=2500):
        expect(
            page.get_by_role(
                "heading", name=as_pattern(rf"^\s*{re.escape(teacher.full_name)}\s*$")
            ).first
        ).to_be_visible(timeout=30_000)
        expect(page.get_by_text(TEACHER_VIEW_ROLE_BADGE).first).to_be_visible()
        expect(
            page.get_by_text(
                as_pattern(rf"^\s*{re.escape(expected_subtitle)}\s*$")
            ).first
        ).to_be_visible()
        expect(page.get_by_text(TEACHER_VIEW_HEADER_BRANCH).first).to_be_visible()

    with demo.step("…down to the staff number the school issued them",
                   dwell_ms=2500):
        expect(page.get_by_text(TEACHER_VIEW_EMAIL_LABEL).first).to_be_visible()
        expect(
            page.get_by_text(as_pattern(re.escape(teacher.email))).first
        ).to_be_visible()
        expect(page.get_by_text(TEACHER_VIEW_ID_LABEL).first).to_be_visible()
        expect(
            page.get_by_text(as_pattern(rf"^\s*{re.escape(staff_id)}\s*$")).first
        ).to_be_visible()
        # This school's pack has no classes to assign anyone to, so the card says
        # so rather than inventing one.
        expect(page.get_by_text(TEACHER_VIEW_CLASS_LABEL).first).to_be_visible()
        expect(page.get_by_text(TEACHER_VIEW_CLASS_UNSET).first).to_be_visible()

    with demo.step("The rest of the page is only what this school bought",
                   dwell_ms=2000):
        cookie_modules = _school_modules_cookie(page)
        assert cookie_modules is not None, (
            f"the {MODULES_COOKIE!r} cookie was never written for this teacher's "
            f"session, so hasModuleLicence falls back to 'unknown means allowed' "
            f"and both panels would render whatever the licence says."
        )
        for panel, module in (
            (TEACHER_VIEW_PAYSLIPS_PANEL, TEACHER_VIEW_PAYROLL_MODULE),
            (TEACHER_VIEW_BOOKS_PANEL, TEACHER_VIEW_LIBRARY_MODULE),
        ):
            assert module not in cookie_modules, (
                f"this school is now licensed for {module!r}, so its panel would "
                f"legitimately render and this check means nothing. Re-read "
                f"config/feature_scenarios.yaml's {TEACHER_VIEW_SCENARIO!r}."
            )
            expect(page.get_by_text(as_pattern(panel))).to_have_count(0)

        assert not DENIAL_URL.search(page.url), (
            f"the teacher of {ctx.school_name!r} ended up at {page.url!r}. `home` "
            f"is core and always on — a denial here is a regression, not a gate."
        )
        assert page.url.rstrip("/").endswith(f"/module/{HOME_ROUTE}"), (
            f"expected to still be on /module/{HOME_ROUTE}, but the app moved to "
            f"{page.url!r}"
        )

    with demo.step("…because the data behind the missing panel is not theirs to "
                   "have", dwell_ms=2000):
        # The exact call StaffBookDashboard makes on mount. Withholding the panel
        # is what stops this 403 from evicting the teacher from their own home
        # page — so the refusal and the absence above are one fact, not two.
        token = login_body["access_token"]
        refused = api.get(
            TEACHER_VIEW_BOOK_REQUESTS_PATH.format(user_id=int(user_id)), token=token
        )
        assert refused.status_code == 403, (
            f"GET {TEACHER_VIEW_BOOK_REQUESTS_PATH.format(user_id=user_id)} is "
            f"gated on ('read', {TEACHER_VIEW_LIBRARY_MODULE!r}), which the "
            f"{ctx.scenario_id!r} pack omits, so it must be refused — got "
            f"{refused.status_code}: {refused.text[:300]}"
        )
        assert FEATURE_PACK_403.search(refused.text), (
            f"the book-requests fetch was refused, but not by the feature pack — "
            f"the detail should be 'Feature not available in your plan', which is "
            f"the one shouldRedirectToNoAccess acts on. Body: {refused.text[:300]}"
        )
