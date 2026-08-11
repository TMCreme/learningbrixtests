"""``school_admin_dashboard`` — the governance module a SchoolAdmin can never lose.

Ledger unit: ``governance.school_admin_dashboard.denied``
(scenario ``academics_only``, role ``school_admin``, intent ``negative``).

That unit is recorded **BLOCKED**, and this file is the guard that stands in its
place. The product question it is blocked on is stated in ``state/blockers.md``:

    Should a SchoolAdmin be subject to the feature-pack gate on the governance
    modules — ``school_admin_dashboard`` in particular — or is their unconditional
    access to it deliberate?

Why the denial cannot be asserted
    The ledger's phrasing — "hidden when the feature pack excludes it" — has two
    halves, and **both** are unreachable in the app as built.

    *The pack cannot exclude it.* ``smsfrontend/src/app/module/feature_flag/
    create/page.tsx`` declares ``BASIC_GROUPS = ["people", "governance"]`` and
    renders every module in those groups ``locked``, pre-selected, un-clickable
    and exempt from "Clear All"; submitting without them is refused outright
    ("All basic modules (People & Governance) must be selected"). The page says
    so to the operator's face: the basic modules "are automatically included in
    every pack". ``school_admin_dashboard`` sits in the backend's ``governance``
    group (``services/feature_pack_service.py``), so **no pack a SuperAdmin can
    build through the product omits it** — including this scenario's. The
    ``academics_only`` pack is requested without it and comes back with it, plus
    the rest of the locked set; step 2 below asserts that delta exactly. The
    backend would happily store a pack without it (``FeaturePackService.
    create_pack`` writes whatever list it is given), so this is a rule the
    SuperAdmin UI imposes, and removing it is a product decision.

    *And nothing would deny it even if the pack did.* Four separate places carry
    an explicit SchoolAdmin carve-out, three of them with a comment saying so:

    * **No route guard.** ``smsfrontend/src/middleware.ts`` gates ``/module/*``
      on the ``schoolModules`` cookie, but the condition carries ``!isSchoolAdmin``
      ("SchoolAdmin bypasses: governance pages are not feature-flag modules").
      Independently of that, ``school_admin_dashboard`` is listed in
      ``CORE_MODULES`` (``src/utils/postAuthRedirect.ts``), whose own comment
      defines core as *not licensable* — so ``isCoreModulePath`` short-circuits
      the same gate a second time. Either bypass alone lets the request through.
    * **No page guard.** ``src/app/module/school_admin_dashboard/page.tsx`` calls
      ``useModuleGuard("school_admin_dashboard")``, and that hook returns ``true``
      for a SchoolAdmin *before* it ever reads the module list
      (``src/hooks/useModuleGuard.tsx``). ``hasAccess === false`` — the branch
      that redirects to ``/auth/no-access`` — is unreachable for this role.
    * **No hidden sidebar entry.** This is the surface the provisioning flow's
      own docstring predicted would deny, and it does not. The Governance section
      lists the item *with* ``module: "school_admin_dashboard"``
      (``nav-config.tsx``), but ``SideNavigation.canShowItem`` returns ``true``
      for a SchoolAdmin before it consults ``item.module`` ("SchoolAdmin bypasses
      the module gate: they own the school config and governance pages").
    * **No 403.** ``utils/permissions.has_permission`` in the backend *does*
      enforce feature packs (403 "Feature not available in your plan"), for
      SchoolAdmins too — but no endpoint anywhere in ``newschoolapp`` is gated on
      the module ``school_admin_dashboard``. It exists in the backend only as a
      gateable name in ``services/feature_pack_service.py``'s ``governance``
      group; it is not even a permission on any seeded role
      (``db/repository/permissions.py``). The one call this page makes,
      ``GET /branch/members/statistics``, is gated on ``school_configuration`` —
      which every scenario licenses by construction.

    Unlocking the governance group, or making any of those four deny, would be
    *enforcing a gate that was previously unenforced* — a product decision, not a
    defect fix. So nothing was changed in either app.

What this test asserts instead
    The exact shape of the gap, from both ends, so that the day either half is
    closed this fails loudly and the real negative path can be written:

    1. ``school_admin_dashboard`` is a genuinely licensable module in the backend
       catalogue, in the ``governance`` group — otherwise the unit is vacuous.
    2. This school's licence carries it *even though the pack was built without
       it*, and the licence is exactly "what was asked for ∪ the locked basic
       modules". That is the un-excludability, measured rather than asserted from
       source, read from ``GET /school_profile/{id}/features`` — the single
       endpoint every frontend guard derives its answer from — and from the
       ``schoolModules`` cookie the app writes out of it.
    3. The pack is nonetheless *enforced* for this very user: ``fees`` is outside
       the locked set, this pack omits it, the SchoolAdmin role holds
       ``("manage", "fees")``, and ``GET /fees/{id}`` answers 403 "Feature not
       available in your plan". So step 4 is a carve-out, not a pack that does
       nothing.
    4. And the frontend gate does not bite this role even on a module the school
       genuinely lacks: ``/module/fees`` is absent from the cookie, so middleware
       would bounce any other role to ``/auth/no-access``, and the SchoolAdmin
       still lands on the page. That is the carve-out the ledger's denial would
       have run into, demonstrated on the one module where it can be seen.
    5. And the dashboard itself is fully open: the sidebar offers the entry, the
       route is not redirected, and the Branches workspace renders with its
       controls and its data.

Reading this test when it fails
    * **Step 2 finding the licence equal to what was requested** is one good
      failure: the governance group is no longer force-included, so a pack can
      exclude ``school_admin_dashboard`` and half the blocker is answered.
    * **A 403 or an /auth/no-access redirect at step 4 or 5** is the other good
      failure: the gate was closed for SchoolAdmins, the blocker is answered
      "yes, enforce it", and this unit should be rewritten as an ordinary denial
      test.
    * ``school_admin_dashboard`` **missing from ``/feature-packs/system-modules``**
      means the backend dropped the module; that is a catalogue change —
      ``config/module_catalog.py`` and ``config/feature_scenarios.yaml`` need
      updating with it, not this assertion loosened.

The other side of the same coin: ``governance.school_admin_dashboard.always_licensed``
    ``test_school_admin_dashboard_is_reachable_on_the_minimal_pack`` (scenario
    ``minimal``, role ``school_admin``, intent ``mandatory``).

    The blocked unit above measures the gap from the *unlicensed* end — a pack
    that asked not to have the module and got it anyway. This one measures it
    from the floor: ``minimal`` is the most restricted pack the product can
    actually build, and the module has to still be there. Governance being core
    and always on is **intended product behaviour, confirmed by the user on
    2026-08-09** — it is not a licensing hole, so this test asserts reachability
    and nothing else. Nothing here should ever be turned into a gate; if a
    future change makes the module droppable, that is a product decision and
    both units get rewritten together, starting from the blocker note.

    What "reachable" is taken to mean, all three surfaces the app has:

    1. **Licensed.** ``GET /school_profile/{id}/features`` lists the module for
       this school, and the browser session's ``schoolModules`` cookie — the
       thing every frontend gate actually reads — agrees with it. The licence is
       also checked to be exactly "what the pack asked for ∪ the locked basic
       modules", which is what makes the floor a floor: even a pack built
       without the governance group carries it.
    2. **Offered.** The Governance section of the sidebar renders the "School
       Admin Dashboard" entry, in the no-branch state a SchoolAdmin lands in
       straight after signing in.
    3. **Working.** Asking for ``/module/school_admin_dashboard`` by hand — the
       request ``src/middleware.ts`` sees — lands on the Branches workspace with
       its three controls and the branch provisioning created, and the one API
       call the page makes, ``GET /branch/members/statistics``, answers 200 with
       that branch in it. A page that mounted behind a guard but could not load
       its data would pass (2) and fail here.
"""
from __future__ import annotations

import json
import re
from urllib.parse import unquote

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.flows.school_provisioning import STAFF_MODULE, SchoolContext
from tests.pages.base import goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

DASHBOARD_MODULE = "school_admin_dashboard"
DASHBOARD_ROUTE = "school_admin_dashboard"
DENIED_SCENARIO = "academics_only"
# The floor case: the most restricted pack the feature-pack builder can produce.
# config/feature_scenarios.yaml lists nine modules for it because the app will
# license them whatever that file says — see the header of this module.
MANDATORY_SCENARIO = "minimal"
SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# src/app/module/feature_flag/create/page.tsx — the SuperAdmin's only surface for
# building a pack. Every module of a "basic" group is rendered locked and forced
# into the pack; only these two are exempt.
BASIC_GROUPS = ("people", "governance")
OPTIONAL_BASIC_MODULES = frozenset({"guardians", "families"})
GOVERNANCE_GROUP = "governance"

# A module the same pack omits, that is *outside* the locked basic set, and which
# the backend does gate — the control that proves the licence is enforced rather
# than decorative. The SchoolAdmin role holds ("manage", "fees") in
# newschoolapp/db/repository/permissions.py, so a refusal can only come from the
# pack. Any fee id will do: has_permission runs as a route dependency, before the
# handler ever looks the row up.
ENFORCED_UNLICENSED_MODULE = "fees"
ENFORCED_UNLICENSED_PATH = "/fees/1"
# src/app/module/fees/page.tsx calls useModuleGuard("fees"), and "fees" is not in
# CORE_MODULES — so this route is gated for every role that lacks the carve-out.
ENFORCED_UNLICENSED_ROUTE = "fees"
# newschoolapp/utils/permissions.py, the feature-pack branch of has_permission.
FEATURE_PACK_403 = re.compile(r"feature not available in your plan", re.I)

# The cookie every frontend gate derives its answer from, written by
# src/app/auth/login/page.tsx and refreshed by SideNavigation.
MODULES_COOKIE = "schoolModules"

# nav-config.tsx — the Governance section (roleGate SchoolAdmin, noBranchOnly)
# and the entry under test. Asserted together so "the entry is there" cannot
# pass on a sidebar that happened to render nothing at all.
NAV_SECTION_GOVERNANCE = re.compile(r"^\s*Governance Module\s*$", re.I)
NAV_DASHBOARD_ENTRY = re.compile(r"^\s*School Admin Dashboard\s*$", re.I)

# src/app/module/school_admin_dashboard/page.tsx — the workspace itself.
PAGE_HEADING = re.compile(r"^\s*Branches\s*$", re.I)
BTN_ADD_BRANCH = re.compile(r"^\s*Add Branch\s*$", re.I)
BTN_CREATE_ADMIN = re.compile(r"^\s*Create Admin\s*$", re.I)
BTN_NEW_SCHOOL_ADMIN = re.compile(r"^\s*New School Admin\s*$", re.I)
BRANCH_NAME_COLUMN = re.compile(r"^\s*Branch\s+Name\s*$", re.I)

# The one call page.tsx makes (`fetchBranches`). A SchoolAdmin sends it bare:
# `withSchool` (src/lib/branchScope.ts) only adds ?school_id= for a SuperAdmin
# viewing somebody else's school, and the backend's `school_scope` dependency
# binds every other role to their own.
DASHBOARD_STATS_PATH = "/branch/members/statistics"

# Where the frontend sends a user it has decided is not allowed in.
DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_school_admin_dashboard_is_unlicensed_yet_never_denied_to_its_admin(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """No pack can drop the module, and no guard would deny it anyway — by design.

    See the module docstring: the SuperAdmin's create-pack form forces the whole
    governance group into every pack, and every layer that could then deny this
    role carries an explicit SchoolAdmin carve-out. So the ledger's denial cannot
    be asserted and the unit is blocked on a product question. What is asserted
    here is that the exclusion is genuinely impossible, that the pack is
    genuinely enforced elsewhere for this same user, and that the frontend gate
    genuinely does not bite this role.
    """
    ctx = provisioned_school
    requested = set(ctx.feature_modules)
    assert DASHBOARD_MODULE not in requested, (
        f"scenario {ctx.scenario_id!r} now *asks* for {DASHBOARD_MODULE!r}, so "
        f"there is no unlicensed state left to observe. "
        f"config/feature_scenarios.yaml picked {DENIED_SCENARIO!r} precisely "
        f"because it omits the module; if that changed, re-point this unit at "
        f"whichever scenario still does."
    )

    # ── 1. It is a real, licensable module, in the group the UI locks ─────────
    super_token = api.login(
        ctx.super_admin.email, ctx.super_admin.password
    )["access_token"]
    catalogue = api.get("/feature-packs/system-modules", token=super_token)
    assert catalogue.status_code == 200, (
        "the SuperAdmin must be able to read the system module catalogue — got "
        f"{catalogue.status_code}: {catalogue.text[:300]}"
    )
    catalogue_body = catalogue.json()
    all_modules = catalogue_body.get("all_modules") or []
    assert DASHBOARD_MODULE in all_modules, (
        f"{DASHBOARD_MODULE!r} is no longer a gateable module in the backend "
        f"(services/feature_pack_service.py, group 'governance'). Everything "
        f"below would then be asserting the absence of a licence that cannot "
        f"exist — update config/module_catalog.py and this unit together. "
        f"Catalogue: {sorted(all_modules)}"
    )
    groups = {
        str(g.get("group")): [str(m) for m in (g.get("modules") or [])]
        for g in (catalogue_body.get("groups") or [])
    }
    assert DASHBOARD_MODULE in groups.get(GOVERNANCE_GROUP, []), (
        f"{DASHBOARD_MODULE!r} left the {GOVERNANCE_GROUP!r} group of the "
        f"backend catalogue. The create-pack form locks a module because of the "
        f"group it is in, so the whole argument below is about that membership. "
        f"Groups: { {k: sorted(v) for k, v in groups.items()} }"
    )

    # The set the SuperAdmin's create-pack form refuses to let anyone deselect.
    locked = {
        module
        for name in BASIC_GROUPS
        for module in groups.get(name, [])
        if module not in OPTIONAL_BASIC_MODULES
    }
    assert DASHBOARD_MODULE in locked, (
        f"{DASHBOARD_MODULE!r} is no longer one of the modules the create-pack "
        f"form forces into every pack. That is half the blocker answered — a "
        f"pack can now exclude it, so rewrite this unit as a real denial test. "
        f"Locked: {sorted(locked)}"
    )

    # ── 2. …so this school's licence carries it despite the pack asking not ───
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — the "
        f"sidebar calls this on every mount — got {features.status_code}: "
        f"{features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so nothing "
        f"below says anything about the gate. Provisioning phase A assigns one — "
        f"check that it did."
    )
    licensed = {str(m) for m in (body.get("modules") or [])}
    assert licensed, (
        f"{ctx.school_name!r} reports an empty module list; the "
        f"{ctx.scenario_id!r} pack should carry at least {sorted(requested)}"
    )
    assert licensed == requested | locked, (
        f"{ctx.school_name!r}'s licence is not 'what was requested plus the "
        f"locked basic modules'. Requested {sorted(requested)}; locked "
        f"{sorted(locked)}; got {sorted(licensed)}. Unexpectedly granted: "
        f"{sorted(licensed - (requested | locked))}; expected but missing: "
        f"{sorted((requested | locked) - licensed)}. Either the create-pack "
        f"form's BASIC_GROUPS rule changed (see the module docstring) or "
        f"provisioning phase A no longer builds the pack through it."
    )
    assert DASHBOARD_MODULE in licensed, (
        f"{ctx.school_name!r} is NOT licensed for {DASHBOARD_MODULE!r}, even "
        f"though the pack was built through a form that locks the whole "
        f"{GOVERNANCE_GROUP!r} group in. This is the good failure: the module "
        f"is excludable again, so the ledger's denial can finally be asserted — "
        f"rewrite governance.school_admin_dashboard.denied as a real denial test."
    )

    # ── 3. The pack IS enforced for this same user, on a module outside the lock ─
    #
    # Without this step, steps 4 and 5 would be indistinguishable from a pack
    # that simply does nothing. `fees` is omitted by this pack and outside the
    # locked set, the SchoolAdmin role holds ("manage", "fees"), and the fees
    # routes carry has_permission(..., "fees") — whose feature-pack branch
    # applies to every role except SuperAdmin.
    assert ENFORCED_UNLICENSED_MODULE not in licensed, (
        f"{ctx.school_name!r} is now licensed for {ENFORCED_UNLICENSED_MODULE!r}, "
        f"so it can no longer serve as the control that the feature gate bites "
        f"for this user. Pick another module this pack omits, that the locked "
        f"basic set does not contain, and that a backend route gates on."
    )
    role_modules = _role_modules(api, SCHOOL_ADMIN_ROLE)
    assert ENFORCED_UNLICENSED_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds an "
        f"{ENFORCED_UNLICENSED_MODULE!r} permission, so the 403 below would come "
        f"from the permission half of the gate and prove nothing about feature "
        f"packs. Fix newschoolapp/db/repository/permissions.py or re-point this "
        f"control."
    )
    gated = api.get(ENFORCED_UNLICENSED_PATH, token=token)
    assert gated.status_code == 403, (
        f"{ENFORCED_UNLICENSED_PATH} answered {gated.status_code} for a "
        f"SchoolAdmin whose school is not licensed for "
        f"{ENFORCED_UNLICENSED_MODULE!r}; the feature-pack gate in "
        f"utils/permissions.has_permission should have refused it. "
        f"Body: {gated.text[:300]}"
    )
    assert FEATURE_PACK_403.search(gated.text), (
        f"{ENFORCED_UNLICENSED_PATH} was refused, but not by the feature pack — "
        f"the detail should be 'Feature not available in your plan'. "
        f"Body: {gated.text[:300]}"
    )

    # ── 4. …yet the frontend module gate does not bite this role at all ───────
    login_as(page, frontend_base_url, ctx.school_admin)

    # No branch is selected right after login, which is the state the Governance
    # section (noBranchOnly) renders in — and the one the ledger's "sidebar entry
    # is absent" denial would have to appear in.
    expect(page.get_by_text(NAV_SECTION_GOVERNANCE).first).to_be_visible(timeout=20_000)

    cookie_modules = _school_modules_cookie(page)
    assert cookie_modules is not None, (
        f"the {MODULES_COOKIE!r} cookie was never written for this session, so "
        f"src/middleware.ts skipped its module gate entirely and the walks below "
        f"would prove nothing. Both src/app/auth/login/page.tsx and "
        f"SideNavigation are meant to set it."
    )
    assert set(cookie_modules) == licensed, (
        f"the browser session claims {sorted(cookie_modules)} as its licensed "
        f"modules, out of step with /school_profile/{ctx.school_id}/features, "
        f"which reports {sorted(licensed)}. Every frontend gate reads the "
        f"cookie, so the two must agree for anything below to mean what it says."
    )
    assert ENFORCED_UNLICENSED_MODULE not in cookie_modules, (
        f"{ENFORCED_UNLICENSED_MODULE!r} is in this session's cookie, so "
        f"/module/{ENFORCED_UNLICENSED_ROUTE} is an ordinary licensed visit and "
        f"cannot demonstrate the SchoolAdmin carve-out."
    )

    # middleware.ts would bounce any role without the carve-out straight to
    # /auth/no-access here, and useModuleGuard("fees") would redirect a second
    # time client-side. The SchoolAdmin gets neither.
    goto_module(page, frontend_base_url, ENFORCED_UNLICENSED_ROUTE)
    page.wait_for_timeout(1_500)  # let a client-side redirect happen if it will
    assert not DENIAL_URL.search(page.url), (
        f"the SchoolAdmin of {ctx.school_name!r} was refused "
        f"/module/{ENFORCED_UNLICENSED_ROUTE} ({page.url!r}) — a module their "
        f"school genuinely lacks. That is the good failure: the frontend "
        f"feature-pack gate now applies to SchoolAdmins, which answers the "
        f"product question this unit is blocked on (state/blockers.md)."
    )
    assert page.url.rstrip("/").endswith(f"/module/{ENFORCED_UNLICENSED_ROUTE}"), (
        f"expected the SchoolAdmin to stay on /module/{ENFORCED_UNLICENSED_ROUTE}, "
        f"but the app moved to {page.url!r}"
    )

    # ── 5. And the dashboard itself is wide open ──────────────────────────────
    dashboard_link = page.locator(f'a[href="/module/{DASHBOARD_ROUTE}"]')
    expect(dashboard_link.first).to_be_visible(timeout=20_000)
    expect(page.get_by_role("link", name=NAV_DASHBOARD_ENTRY).first).to_be_visible()

    # Asking for the route by hand is the request middleware.ts actually sees.
    goto_module(page, frontend_base_url, DASHBOARD_ROUTE)
    expect(page.get_by_role("heading", name=PAGE_HEADING).first).to_be_visible(
        timeout=30_000
    )
    assert not DENIAL_URL.search(page.url), (
        f"the SchoolAdmin of {ctx.school_name!r} was redirected to {page.url!r}. "
        f"That is the *good* failure: the feature-pack gate has been closed for "
        f"SchoolAdmins on {DASHBOARD_MODULE!r}, which answers the product "
        f"question this unit is blocked on (state/blockers.md). Rewrite "
        f"governance.school_admin_dashboard.denied as a real denial test."
    )
    assert page.url.rstrip("/").endswith(f"/module/{DASHBOARD_ROUTE}"), (
        f"expected to still be on /module/{DASHBOARD_ROUTE}, but the app moved "
        f"to {page.url!r}"
    )

    # The workspace is fully operational, not an empty shell behind a guard.
    expect(page.get_by_role("button", name=BTN_ADD_BRANCH).first).to_be_visible()
    expect(page.get_by_role("button", name=BTN_CREATE_ADMIN).first).to_be_visible()
    expect(page.get_by_role("button", name=BTN_NEW_SCHOOL_ADMIN).first).to_be_visible()

    # And it really did load its data — /branch/members/statistics is gated on
    # `school_configuration`, which every pack licenses, which is exactly why the
    # unlicensed dashboard has nothing to fail on. PageError would have replaced
    # the table with "Failed to load branches".
    expect(page.get_by_text(re.compile(r"failed to load branches", re.I))).to_have_count(0)
    # Not get_by_role("columnheader"): components/ui/table.tsx writes a bare
    # <th> with no `scope`, and Playwright resolves those to plain `cell` rather
    # than running the spec's scope-inference algorithm — a columnheader query
    # matches nothing here. Anchor on the header row instead.
    expect(page.locator("thead th").filter(has_text=BRANCH_NAME_COLUMN).first).to_be_visible()
    # …and the branch provisioning created is actually listed, so the statistics
    # call really did answer rather than the table rendering empty.
    branch_name = (ctx.branches[0] or {}).get("name") if ctx.branches else None
    assert branch_name, (
        f"provisioning recorded no branch for {ctx.school_name!r}, so there is "
        f"nothing to expect in the table. Phase B creates one."
    )
    expect(
        page.locator("tbody tr").filter(
            has_text=re.compile(re.escape(str(branch_name)), re.I)
        ).first
    ).to_be_visible()


@pytest.mark.school_admin
@pytest.mark.scenario(MANDATORY_SCENARIO)
def test_school_admin_dashboard_is_reachable_on_the_minimal_pack(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """The floor case still has its dashboard: licensed, offered, and working.

    Ledger unit ``governance.school_admin_dashboard.always_licensed``. See the
    module docstring: governance is core and always on **by design** (confirmed
    2026-08-09), so this proves the module survives the most restricted pack the
    product can build — and deliberately adds no gate of any kind.
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
    groups = {
        str(g.get("group")): [str(m) for m in (g.get("modules") or [])]
        for g in (catalogue_body.get("groups") or [])
    }
    assert DASHBOARD_MODULE in groups.get(GOVERNANCE_GROUP, []), (
        f"{DASHBOARD_MODULE!r} is no longer in the {GOVERNANCE_GROUP!r} group of "
        f"the backend catalogue (services/feature_pack_service.py). The "
        f"create-pack form locks a module in because of the group it belongs to, "
        f"so that membership is the whole reason this module is mandatory. "
        f"Groups: { {k: sorted(v) for k, v in groups.items()} }"
    )
    locked = {
        module
        for name in BASIC_GROUPS
        for module in groups.get(name, [])
        if module not in OPTIONAL_BASIC_MODULES
    }
    assert DASHBOARD_MODULE in locked, (
        f"{DASHBOARD_MODULE!r} is no longer one of the modules the SuperAdmin's "
        f"create-pack form forces into every pack, so it is no longer mandatory "
        f"and this unit's premise is gone. That is a product change, not a test "
        f"failure to paper over — re-read state/blockers.md and rewrite this and "
        f"the denial unit together. Locked: {sorted(locked)}"
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
    assert DASHBOARD_MODULE in licensed, (
        f"{ctx.school_name!r} — the most restricted pack this product can build — "
        f"is not licensed for {DASHBOARD_MODULE!r}. Governance is core and always "
        f"on by design, so a SchoolAdmin has just lost the only screen that "
        f"creates branches, and every later create posts school_branch_id: 0. "
        f"Licensed: {sorted(licensed)}"
    )

    # ── 2. Offered: the sidebar entry a SchoolAdmin sees on landing ───────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # No branch is selected right after login, which is the state the Governance
    # section (noBranchOnly in nav-config.tsx) renders in.
    expect(page.get_by_text(NAV_SECTION_GOVERNANCE).first).to_be_visible(timeout=20_000)
    expect(page.get_by_role("link", name=NAV_DASHBOARD_ENTRY).first).to_be_visible(
        timeout=20_000
    )
    expect(page.locator(f'a[href="/module/{DASHBOARD_ROUTE}"]').first).to_be_visible()

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
    assert DASHBOARD_MODULE in cookie_modules, (
        f"{DASHBOARD_MODULE!r} is missing from this session's {MODULES_COOKIE!r} "
        f"cookie, so src/middleware.ts would gate the route for any role without "
        f"the SchoolAdmin carve-out — the module is not reachable on the "
        f"{MANDATORY_SCENARIO!r} pack for anybody else"
    )

    # ── 3. Working: the route loads and the page's own data call answers ──────
    # Asking for the route by hand is the request middleware.ts actually sees.
    goto_module(page, frontend_base_url, DASHBOARD_ROUTE)
    expect(page.get_by_role("heading", name=PAGE_HEADING).first).to_be_visible(
        timeout=30_000
    )
    assert not DENIAL_URL.search(page.url), (
        f"the SchoolAdmin of {ctx.school_name!r} was redirected to {page.url!r} "
        f"asking for a module their pack licenses. Governance is core and always "
        f"on by design — a denial here is a regression, not a gate to keep."
    )
    assert page.url.rstrip("/").endswith(f"/module/{DASHBOARD_ROUTE}"), (
        f"expected to still be on /module/{DASHBOARD_ROUTE}, but the app moved "
        f"to {page.url!r}"
    )

    expect(page.get_by_role("button", name=BTN_ADD_BRANCH).first).to_be_visible()
    expect(page.get_by_role("button", name=BTN_CREATE_ADMIN).first).to_be_visible()
    expect(page.get_by_role("button", name=BTN_NEW_SCHOOL_ADMIN).first).to_be_visible()

    # PageError would have replaced the whole table with this panel.
    expect(page.get_by_text(re.compile(r"failed to load branches", re.I))).to_have_count(0)
    # Not get_by_role("columnheader"): components/ui/table.tsx writes a bare <th>
    # with no `scope`, which Playwright resolves to `cell` rather than running
    # the spec's scope-inference algorithm.
    expect(page.locator("thead th").filter(has_text=BRANCH_NAME_COLUMN).first).to_be_visible()

    branch_name = (ctx.branches[0] or {}).get("name") if ctx.branches else None
    assert branch_name, (
        f"provisioning recorded no branch for {ctx.school_name!r}, so there is "
        f"nothing to expect in the table. Phase B creates one for every scenario."
    )
    expect(
        page.locator("tbody tr").filter(
            has_text=re.compile(re.escape(str(branch_name)), re.I)
        ).first
    ).to_be_visible()

    # And the module's API surface answers this admin directly — a page that
    # rendered its shell behind a guard but could not fetch would stop here.
    stats = api.get(DASHBOARD_STATS_PATH, token=token)
    assert stats.status_code == 200, (
        f"{DASHBOARD_STATS_PATH} answered {stats.status_code} for the SchoolAdmin "
        f"of {ctx.school_name!r}; it is the only call "
        f"/module/{DASHBOARD_ROUTE} makes, and the dashboard is unusable without "
        f"it. Body: {stats.text[:300]}"
    )
    served = {str(row.get("name")) for row in (stats.json() or [])}
    assert str(branch_name) in served, (
        f"the branch statistics served this admin are {sorted(served)}, which "
        f"does not include their own branch {branch_name!r} — the table above "
        f"was rendering something other than this school's branches"
    )


# ───────── view path: the SchoolAdmin reads the branches workspace ────────────
#
# Ledger unit: ``governance.school_admin_dashboard.view.school_admin``
# (scenario ``minimal``, role ``school_admin``, intent ``view``).
#
# Constants below are prefixed ``VIEW_`` rather than reusing the denial section's
# names: this file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# What the screen is
#     ``/module/school_admin_dashboard`` is the SchoolAdmin's landing page —
#     ``getPostAuthRedirect`` (src/utils/postAuthRedirect.ts) sends the role
#     straight here after login — and it renders one thing: the **Branches**
#     register. An h1 of "Branches" over the school's own name, a sentence
#     describing the list, three toolbar actions (Add Branch / Create Admin /
#     New School Admin) and an eight-column table of every branch with its
#     people counts. Its only fetch is ``GET /branch/members/statistics``.
#
# Why the ``minimal`` pack is the right place to read it
#     ``minimal`` is the most restricted pack the product can actually build, and
#     it still licenses this module — the pack builder locks the whole
#     ``governance`` group into every pack (BASIC_GROUPS in
#     src/app/module/feature_flag/{create,edit}/page.tsx), which is intended
#     product behaviour rather than a licensing hole (see the module docstring
#     and config/feature_scenarios.yaml). So the view path is asserted on the
#     floor case: even a school that bought as little as the product will sell
#     gets the whole workspace.
#
# Why no branch is activated first
#     Deliberately, and unlike every academics or fees unit. The sidebar's
#     "Governance Module" section is declared ``noBranchOnly``
#     (SideNavigation/nav-config.tsx), so picking a branch is what would take the
#     "School Admin Dashboard" entry *off* the sidebar — the very link this test
#     walks in through. The page needs no branch either: it is school-scoped
#     (``school_scope`` binds a SchoolAdmin to their own school) and its mount
#     effect calls ``clearBranch()`` regardless.
#
# What is asserted, and what is deliberately not
#     A view unit's claim is that the screen *reads correctly*, so every rendered
#     cell of the provisioned branch is compared against what
#     ``GET /branch/members/statistics`` reports for the same branch — the table
#     formats each count through ``Number.toLocaleString()`` with a ``"0"``
#     fallback and the date through ``Intl``, and a screen that quietly shows
#     "0", "N/A" or "Invalid Date" for real data would otherwise look identical
#     to a correct one. The three toolbar actions are asserted *present* — the
#     seeded SchoolAdmin role owns this page, so hiding them would be the bug —
#     but never pressed: this visit writes nothing.

VIEW_SCENARIO = "minimal"

# nav-config.tsx: the section is roleGate ["SchoolAdmin"] + noBranchOnly, and the
# entry under test sits at the top of it. Asserted together so "the entry is
# offered" cannot pass on a sidebar that happened to render nothing at all.
VIEW_NAV_SECTION = re.compile(r"^\s*Governance Module\s*$", re.I)

# page.tsx renders "Date Created" through
# new Date(...).toLocaleDateString("en-US", {day:"numeric", month:"short",
# year:"numeric"}) — e.g. "Aug 9, 2026". Asserted by shape rather than by value:
# the backend serialises date_created as ISO, which the browser reads in its own
# timezone, so the day can legitimately differ by one from the raw payload. What
# must never appear is the "N/A" fallback or JavaScript's "Invalid Date".
VIEW_DATE_CREATED = re.compile(r"^[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}$")

# The failure panel PageError puts up when GET /branch/members/statistics is
# refused, and the empty state the table falls back to. Neither may appear: this
# school has a branch.
VIEW_LOAD_FAILURE = re.compile(r"failed to load branches", re.I)

# Where the frontend sends a user it has decided is not allowed in, and the
# endpoint the workspace is built on.
VIEW_STATS_PATH = "/branch/members/statistics"


@pytest.mark.school_admin
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="governance.school_admin_dashboard.view.school_admin",
    title="School Admin Dashboard",
    subtitle="SchoolAdmin views school admin dashboard",
)
def test_school_admin_views_the_branches_dashboard(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A SchoolAdmin walks in from the Governance menu and reads the branch register.

    The read *is* the feature, so nothing here writes. Every value on the row is
    checked against ``GET /branch/members/statistics`` for the same branch, which
    is what separates "the table rendered" from "the table rendered the school's
    actual numbers".
    """
    ctx = provisioned_school
    assert DASHBOARD_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {DASHBOARD_MODULE!r} for the "
        f"view path. {VIEW_SCENARIO!r} is chosen precisely because it is the "
        f"floor case that still carries it — see config/feature_scenarios.yaml."
    )
    branch_name = str((ctx.branches[0] or {}).get("name") or "") if ctx.branches else ""
    assert branch_name, (
        f"provisioning recorded no branch for {ctx.school_name!r}, so there is "
        f"nothing for this screen to list. Phase B always creates one — a school "
        f"without a branch cannot create people at all."
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    branches = BranchesPage(page, base_url)

    # Setup, never an assertion: the numbers the screen must agree with, read
    # from the one endpoint the page itself calls.
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    reported = _branch_statistics(api, branch_name, token=token)

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step("The Governance menu offers the School Admin Dashboard"):
        # No branch is picked on the way in, and that is deliberate: this whole
        # sidebar section is hidden for a SchoolAdmin who is inside a branch
        # (see the section comment above).
        expect(page.get_by_text(VIEW_NAV_SECTION).first).to_be_visible(timeout=25_000)
        branches.expect_nav_entry()

    with demo.step("Open it, and every branch of the school is listed"):
        branches.open_from_sidebar()
        assert not DENIAL_URL.search(page.url), (
            f"the SchoolAdmin of {ctx.school_name!r} was sent to {page.url!r} "
            f"instead of the dashboard. On the {ctx.scenario_id!r} pack this "
            f"module is licensed, so a denial here is a real regression — see "
            f"the module docstring for the four layers that carve this role out."
        )
        expect(page.get_by_text(VIEW_LOAD_FAILURE)).to_have_count(0)

    with demo.step("The page names the school whose branches these are"):
        branches.expect_intro(ctx.school_name)

    with demo.step("Each branch is listed with its location, age and headcounts"):
        branches.expect_column_headers()

    with demo.step(f"{branch_name} reads back exactly as the school recorded it"):
        row = branches.read_row(branch_name)
        assert row.name == branch_name, (
            f"the Branch Name cell reads {row.name!r}, not {branch_name!r}"
        )
        assert row.location == str(reported["location"] or ""), (
            f"{branch_name}'s Location cell reads {row.location!r}, but "
            f"{VIEW_STATS_PATH} reports {reported['location']!r}"
        )
        assert VIEW_DATE_CREATED.match(row.date_created), (
            f"{branch_name}'s Date Created cell reads {row.date_created!r}. The "
            f"page formats branch.date_created through Intl, so 'N/A' means the "
            f"field arrived empty and 'Invalid Date' means the backend stopped "
            f"serialising it as ISO (several api_models carry a "
            f"'%d-%m-%y %H:%M:%S' json_encoder that this one does not)."
        )

    with demo.step("…and its people counts match what the school actually has"):
        stats = reported["members_overview_stats"] or {}
        for column, key in (
            ("Total Students", "total_students"),
            ("Total Parents", "total_guardians"),
            ("Teaching Staff", "total_teachers"),
            ("Non-Teaching Staff", "total_non_teaching"),
        ):
            rendered = getattr(row, _VIEW_COUNT_FIELDS[key])
            assert _as_count(rendered) == int(stats.get(key, -1)), (
                f"{branch_name}'s {column} cell reads {rendered!r}, but "
                f"{VIEW_STATS_PATH} reports {stats.get(key)!r}. The cell is "
                f"`stats?.{key}?.toLocaleString() || \"0\"`, so a mismatch is "
                f"either a lost payload field rendering as the '0' fallback or "
                f"the table reading the wrong branch's row."
            )

        # And the numbers are not all zero by construction: `minimal` licenses
        # `staff`, so provisioning put a teacher and an accountant in this
        # branch this calendar year — which is the window
        # StatisticsService.get_school_members_overview_stats counts over.
        if STAFF_MODULE in ctx.feature_modules:
            assert _as_count(row.total_teachers) >= 1, (
                f"{branch_name} shows no teaching staff, yet provisioning "
                f"created a teacher in it. Either the create never landed in "
                f"this branch or the statistics query stopped counting them."
            )
            assert _as_count(row.total_non_teaching) >= 1, (
                f"{branch_name} shows no non-teaching staff, yet provisioning "
                f"created an accountant in it."
            )

    with demo.step("Add Branch, Create Admin and New School Admin stand ready", dwell_ms=2000):
        # Asserted, never pressed: the seeded SchoolAdmin role owns this page, so
        # the controls belong on screen — but this unit is a read.
        branches.expect_actions_offered()


# Which BranchRow field carries each statistic, so the comparison above can be
# written as one loop over the four count columns.
_VIEW_COUNT_FIELDS = {
    "total_students": "total_students",
    "total_guardians": "total_guardians",
    "total_teachers": "total_teachers",
    "total_non_teaching": "total_non_teaching",
}


def _as_count(rendered: str) -> int:
    """A count cell as a number. The page prints it through ``toLocaleString()``."""
    return int(rendered.replace(",", "").strip() or 0)


def _branch_statistics(api: BackendAPI, branch_name: str, *, token: str) -> dict:
    """The branch the screen is about, as ``GET /branch/members/statistics`` has it.

    Setup for the comparison, not an assertion about the endpoint — except that
    it must answer at all: the page has no other source, and a refusal here would
    make every "the cell is empty" failure below unreadable.
    """
    res = api.get(VIEW_STATS_PATH, token=token)
    assert res.status_code == 200, (
        f"a SchoolAdmin must be able to read {VIEW_STATS_PATH} — it is the only "
        f"fetch /module/school_admin_dashboard makes, and it is gated on "
        f"'school_configuration', which every pack licenses. Got "
        f"{res.status_code}: {res.text[:300]}"
    )
    for branch in res.json():
        if str(branch.get("name", "")).strip() == branch_name:
            return branch
    raise AssertionError(
        f"{branch_name!r} is not in {VIEW_STATS_PATH}'s response, so the screen "
        f"cannot be listing it either. Branches reported: "
        f"{[b.get('name') for b in res.json()]}"
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
