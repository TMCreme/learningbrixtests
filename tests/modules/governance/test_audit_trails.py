"""/module/audit_trails — the governance log a SchoolAdmin reads.

View path: the SchoolAdmin of the ``finance_only`` school opens Audit Trails from
the Governance menu, finds what their accountant did, narrows the log with the
search box and the action filter, and opens one entry to read the record the
backend actually stored (``test_school_admin_views_audit_trails``). That is the
ledger unit ``governance.audit_trails.view.school_admin``.

This module is read-only by construction, so there is no manage unit to write
    ``api/routes/auditlog.py`` exposes exactly two endpoints, both ``GET``. The
    screen has no create, edit or delete control either — the one thing that
    looks like a write, the "Confirm Revert" modal in ``page.tsx``, is dead
    markup: nothing ever sets ``isModalOpen``, so no user can reach it, and no
    revert route exists to serve it. An audit trail you can edit is not an audit
    trail; the absence is the design, not a gap.

Why the rows have to be seeded, and why they are seeded as the *accountant*
    Two facts about the log meet here.

    First, the list route filters on branch. For a SchoolAdmin,
    ``list_audit_logs_with_separate_count`` resolves every branch of every school
    they administer and answers ``AuditLog.branch_id.in_(allowed_branch_ids)`` —
    so a row whose ``branch_id`` is NULL is invisible to them, however recently
    it was written.

    Second, hardly anything writes that column. ``capture_after_state`` takes
    ``branch_id`` from ``branch_context`` (set only when the request carried a
    ``branch_id`` *query* parameter) and otherwise falls back to
    ``user.school_branch_id``. A SchoolAdmin belongs to no branch, so their own
    writes — the entire provisioning walkthrough — land with a NULL branch and
    never appear on their own audit screen. A branch-scoped user's writes do.

    The accountant provisioning creates is exactly such a user, and in the
    ``finance_only`` pack they are licensed for the module they work in. So the
    seed books one income type and one receipt over ``/finance/…`` as them, which
    is what a bursar does on a Monday morning, and those two rows are then the
    newest entries the admin's log can show.

    Seeding over the API rather than through the finance UI is deliberate and is
    the same setup-only use of ``api`` that ``school_provisioning._seed_fee_group``
    makes: driving the Add Income modals here would be the
    ``account.incomes_and_expenses.manage.accountant`` walkthrough wearing a
    different name, and this unit is about the *log*, not about the money.

Why no branch is selected first, unlike the finance screens
    Audit Trails is reached from the "Governance Module" section of the sidebar,
    which is ``noBranchOnly`` (nav-config.tsx) — it is on screen for a SchoolAdmin
    *until* they pick a branch, at which point the ``branchOnly`` "Audit Overview"
    section offers the very same link instead. Either route arrives at the same
    page. The walkthrough takes the first because it is what a SchoolAdmin sees
    the moment they sign in, and because ``page.tsx`` only appends ``branch_id``
    to its fetch when the branch store is filled — leaving it empty is what makes
    the screen show the whole school rather than one campus, which is the
    governance view this unit is named for.

Deliberately not asserted: an UPDATE row
    The action filter offers "Update" and ``db/models/auditlog.py`` documents
    ``action`` as CREATE/UPDATE/DELETE, but the middleware never writes one.
    ``api/middlewares/auditlog.has_changes`` re-reads the instance with
    ``session.query(type(instance)).filter_by(id=…).first()``, which SQLAlchemy
    serves from the identity map — so it hands back the *same, already-mutated*
    object and every column compares equal to itself. In 13k+ rows on the running
    database there is not one UPDATE. That looks like a backend defect rather
    than a decision, but it is a change to a global ``before_flush`` listener that
    would start writing audit rows for every update in the product, so it is
    reported rather than patched from inside a test-writing pass. This unit
    asserts only what the app demonstrably records, and the filter is exercised
    with "Create".

Deliberately not asserted either: that the write controls are absent
    There are none to hide — see the first note. Asserting their absence would be
    asserting something no branch of ``page.tsx`` could ever render.

Mandatory path: the SchoolAdmin of the ``minimal`` school
    ``test_audit_trails_is_reachable_on_the_minimal_pack`` — the ledger unit
    ``governance.audit_trails.always_licensed``. There is no denial unit for this
    module, and there cannot be one: ``audit_trails`` sits in the ``governance``
    group of ``services/feature_pack_service.SYSTEM_MODULE_GROUPS``, and the
    SuperAdmin's only pack builder (``src/app/module/feature_flag/create/page.tsx``
    and its ``edit/[id]`` twin) declares ``BASIC_GROUPS = ["people",
    "governance"]`` and renders every module of those two groups locked,
    pre-selected and exempt from "Clear All" — only ``guardians`` and ``families``
    are optional inside them, and ``handleSave`` refuses a pack missing any of
    the rest outright. Governance being core and always on is **intended product
    behaviour, confirmed 2026-08-09**, not a licensing hole. So the unit asserts
    the opposite of a denial — the module is licensed, offered and working on the
    most restricted pack the product can build — and deliberately adds no gate.

    Two module keys, and both are asserted
        This module is the one place in the product where the gate module and the
        page's module are different keys. ``nav-config.tsx`` and
        ``useModuleGuard`` gate the screen on ``audit_trails``; every route in
        ``api/routes/auditlog.py`` is declared
        ``Depends(has_permission("read", "access_roles"))``. Both keys are in the
        locked governance group, so both are on the minimal pack, and the test
        checks both — "the audit screen works for this school" is only true while
        that stays so, whichever key the two are eventually reconciled onto.
        Re-pointing the routes at ``audit_trails`` would be a behaviour change (it
        would hand the log to any school licensed for the log but not for role
        administration, and take it away from every school licensed the other way
        round), so it is documented, not patched.

    Why a control on a module the pack really does omit
        Every frontend gate this screen has carries a SchoolAdmin carve-out —
        ``src/middleware.ts`` exempts the role from module enforcement outright,
        and ``useModuleGuard`` returns ``true`` for it before it ever reads the
        ``schoolModules`` cookie, so ``hasModuleAccess === false`` (the branch
        that renders ``null``) is unreachable for this role. "The page loaded" on
        its own is therefore compatible with a licence system that does nothing
        at all. The test pins that down with ``fees``: outside the locked set,
        omitted by this pack, held as a permission by the seeded SchoolAdmin
        role, and refused 403 "Feature not available in your plan" by
        ``utils.permissions.has_permission``. The gate bites; it just does not
        bite here, by design.
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
from tests.fixtures.data_factories import run_tag
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.governance.audit_trails import (
    COLUMN_CREATED_AT,
    COLUMN_RECORD_ID,
    COLUMN_RESOURCE,
    COLUMN_USER,
    CREATE_OPTION,
    DRAWER_AFFECTED_RESOURCE,
    DRAWER_AFTER_STATE,
    DRAWER_BEFORE_STATE,
    DRAWER_BRANCH_ID,
    DRAWER_NOT_PROVIDED,
    DRAWER_TIME_OF_ACTION,
    DRAWER_TITLE,
    DRAWER_USER_DETAILS,
    PAGINATION,
    SUBHEADING,
    AuditTrailsPage,
)
from tests.pages.login import login_as

AUDIT_MODULE = "audit_trails"
AUDIT_SCENARIO = "finance_only"
# config/module_catalog.py's route for this module.
AUDIT_ROUTE = "audit_trails"
# The floor case: the most restricted pack the product can actually build.
MANDATORY_SCENARIO = "minimal"
# The log's own list route is gated on ("read", "access_roles"), not on
# ("read", "audit_trails") — so the pack must license both for this screen to
# render anything at all. `finance_only` does.
AUDIT_LIST_PERMISSION_MODULE = "access_roles"
# The seed writes through the finance routes, which are gated on their own module.
AUDIT_SEED_MODULE = "incomes_and_expenses"

# The sidebar entry (SideNavigation/nav-config.tsx, "Governance Module"). Scoped
# to the sidebar in the test: /module/home's QuickActions card carries the same
# label and the same href, and the walkthrough narrates the menu.
AUDIT_NAV_AUDIT_TRAILS = re.compile(r"^\s*Audit Trails\s*$", re.I)

# What the two seeded writes are recorded as. These are __tablename__ values, and
# the Resource column renders them verbatim.
AUDIT_INCOME_TYPE_TABLE = "income_types"
AUDIT_INCOME_TABLE = "school_income"
# The middleware stores the action in upper case; the table renders it verbatim
# and the drawer title-cases it into a badge that sits beside the timestamp.
AUDIT_CREATE_ACTION = "CREATE"
AUDIT_CREATE_BADGE = "Create"
# The drawer title-cases the resource too ("income_types" → "Income_types"), so
# it is matched case-insensitively rather than as a literal.
AUDIT_INCOME_TYPE_TABLE_SHOWN = re.compile(re.escape(AUDIT_INCOME_TYPE_TABLE), re.I)

# ── what audit_seed writes. "TEST" is what the orphan sweeper matches on, and the
#    run tag keeps parallel agents from colliding. ─────────────────────────────
AUDIT_TAG = run_tag()
AUDIT_INCOME_TYPE_NAME = f"TEST Audited Bursary Receipts {AUDIT_TAG}"
AUDIT_INCOME_TYPE_DESCRIPTION = "Bursary money received on behalf of sponsored pupils."
AUDIT_INCOME_DESCRIPTION = f"TEST Audited bursary instalment banked {AUDIT_TAG}"
AUDIT_INCOME_AMOUNT = 1800

# A term nobody in this school is called and no table is named, used to prove the
# search box really filters rather than merely rerendering the same page.
AUDIT_NO_SUCH_ACTOR = f"TEST Nobody Did This {AUDIT_TAG}"

# ── what makes the module mandatory (the always_licensed unit) ───────────────
# src/app/module/feature_flag/create/page.tsx — the SuperAdmin's only surface for
# building a pack. Every module of a "basic" group is rendered locked and forced
# into the pack; only these two are exempt.
BASIC_GROUPS = ("people", "governance")
OPTIONAL_BASIC_MODULES = frozenset({"guardians", "families"})
GOVERNANCE_GROUP = "governance"

# The list route the screen mounts on, asked for exactly as page.tsx asks for it
# (ten rows at a time, no branch_id — a SchoolAdmin has no branch until they pick
# one, and the module's own screen is read school-wide).
AUDIT_LIST_PATH = "/audilog/?skip=0&limit=10"

# A module the same pack omits, *outside* the locked basic set, that the backend
# really does gate — the control proving the licence is enforced rather than
# decorative. The SchoolAdmin role holds ("manage", "fees") in
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

# nav-config.tsx — the section the "Audit Trails" entry lives in for a SchoolAdmin
# who has not picked a branch (roleGate SchoolAdmin, noBranchOnly). Asserted
# alongside the entry so "the entry is there" cannot pass on a sidebar that
# rendered nothing at all.
NAV_SECTION_GOVERNANCE = re.compile(r"^\s*Governance Module\s*$", re.I)

# Where the frontend sends a user it has decided is not allowed in
# (src/app/auth/no-access/page.tsx, reached by handleErrorMessage's interceptor).
DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")

SCHOOL_ADMIN_ROLE = "SchoolAdmin"


@dataclass(frozen=True)
class AuditedActions:
    """The two changes this unit puts into the school's audit trail."""

    branch_id: int
    actor_name: str
    income_type_id: int
    income_id: int


@pytest.fixture
def audit_seed(provisioned_school: SchoolContext, api: BackendAPI) -> AuditedActions:
    """Two branch-scoped CREATEs, written as the accountant.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert AUDIT_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {AUDIT_MODULE!r} for this "
        f"unit — a school refused the module has no audit screen to open"
    )
    assert AUDIT_LIST_PERMISSION_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must also license "
        f"{AUDIT_LIST_PERMISSION_MODULE!r}: GET /audilog/ is gated on "
        f"('read', {AUDIT_LIST_PERMISSION_MODULE!r}), so without it the screen "
        f"renders its load-failure panel instead of the log"
    )
    assert AUDIT_SEED_MODULE in ctx.feature_modules, (
        f"this unit seeds its audit rows through /finance/…, so scenario "
        f"{ctx.scenario_id!r} must license {AUDIT_SEED_MODULE!r}"
    )
    assert ctx.accountant is not None, (
        "provisioning created no accountant for this school, and only a "
        "branch-scoped user's writes get an AuditLog.branch_id — which is the "
        "column the SchoolAdmin's log filters on. Phase C creates one from "
        "/module/staff's Non-teaching Staff tab, which needs the `staff` module."
    )
    assert ctx.branches, (
        "provisioning left this school with no branch, so there is nothing for "
        "the audit rows to be scoped to — phase B creates one for every scenario"
    )
    branch_id = int(ctx.branches[0].get("id") or -1)
    assert branch_id > 0, (
        "provisioning could not capture the branch id, and the audit log is read "
        "by branch — re-run provisioning rather than guessing it"
    )

    admin_token = api.login(
        ctx.school_admin.email, ctx.school_admin.password
    )["access_token"]
    accountant_token = api.login(
        ctx.accountant.email, ctx.accountant.password
    )["access_token"]

    years = api.get(
        f"/academic-year/?skip=0&limit=100&school_id={ctx.school_id}", token=admin_token
    )
    assert years.status_code == 200, (
        f"could not read this school's academic years: "
        f"{years.status_code} {years.text[:300]}"
    )
    rows = years.json()
    assert rows, (
        f"{ctx.school_name!r} has no academic year, and every income is booked "
        f"against one — provisioning phase B creates one whenever the pack "
        f"licenses 'academic_year_and_term'"
    )
    year = next((y for y in rows if y.get("is_active")), rows[0])

    # `branch_id` is passed as a query parameter as well as in the body: app.py's
    # middleware feeds it to `branch_context`, which is the first source
    # `capture_after_state` reads for the audit row's branch. The accountant's own
    # `school_branch_id` is the fallback, so the row is scoped either way.
    income_type = _seed_audited_write(
        api, accountant_token,
        f"/finance/income-types/?school_branch_id={branch_id}&branch_id={branch_id}",
        {
            "name": AUDIT_INCOME_TYPE_NAME,
            "description": AUDIT_INCOME_TYPE_DESCRIPTION,
            "school_branch_id": branch_id,
        },
        what="income type",
        actor="accountant",
    )
    income = _seed_audited_write(
        api, accountant_token,
        f"/finance/income/?branch_id={branch_id}",
        {
            "amount": AUDIT_INCOME_AMOUNT,
            "description": AUDIT_INCOME_DESCRIPTION,
            "income_type_id": int(income_type["id"]),
            "academic_year_id": int(year["id"]),
            "school_branch_id": branch_id,
            "transaction_date": date.today().isoformat(),
        },
        what="income",
        actor="accountant",
    )

    return AuditedActions(
        branch_id=branch_id,
        actor_name=ctx.accountant.full_name,
        income_type_id=int(income_type["id"]),
        income_id=int(income["id"]),
    )


def _seed_audited_write(
    api: BackendAPI,
    token: str,
    path: str,
    payload: dict[str, Any],
    *,
    what: str,
    actor: str,
) -> dict[str, Any]:
    """POST one setup row, failing loudly rather than leaving an empty log."""
    response = api.post(path, token=token, json=payload)
    assert response.status_code < 400, (
        f"could not seed the {what} as the {actor}, so there is no audited change "
        f"for this unit to read: {response.status_code} {response.text[:300]}"
    )
    return response.json()


@pytest.mark.school_admin
@pytest.mark.scenario(AUDIT_SCENARIO)
@pytest.mark.demo(
    feature_id="governance.audit_trails.view.school_admin",
    title="Audit Trails",
    subtitle="SchoolAdmin views audit trails",
)
def test_school_admin_views_audit_trails(
    audit_seed: AuditedActions,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A SchoolAdmin reads the school's audit trail: who changed what, and to what.

    Every assertion is made on what the screen renders back from
    ``GET /audilog/``, and the last step re-reads the same route directly — so a
    log the backend holds but scopes to somebody else's school, the failure mode
    that matters most on a governance screen, cannot pass.
    """
    ctx = provisioned_school
    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    audit = AuditTrailsPage(page, base_url)

    with demo.step(
        f"Sign in as {ctx.school_admin.full_name}, who runs {ctx.school_name}",
        dwell_ms=2500,
    ):
        login_as(page, base_url, ctx.school_admin)

    with demo.step("Open Audit Trails from the Governance menu", dwell_ms=1800):
        # Scoped to the sidebar on purpose: /module/home's QuickActions grid
        # carries a card with the same label and href, and the caption above
        # promises the menu.
        link = page.get_by_role("navigation").get_by_role(
            "link", name=as_pattern(AUDIT_NAV_AUDIT_TRAILS)
        ).first
        expect(link).to_be_visible(timeout=25_000)
        link.click()
        page.wait_for_url(re.compile(r"/module/audit_trails"), timeout=25_000)
        audit.expect_loaded()

    with demo.step(
        "Every change made in the school, newest first", dwell_ms=2200
    ):
        expect(page.get_by_role("heading", name=SUBHEADING)).to_be_visible()
        for column in (
            COLUMN_RECORD_ID, COLUMN_CREATED_AT, COLUMN_USER, COLUMN_RESOURCE,
        ):
            expect(audit.column_header(column)).to_be_visible()
        expect(page.get_by_text(PAGINATION)).to_be_visible()
        audit.expect_no_load_failure()

    with demo.step(
        f"Search the log for what {audit_seed.actor_name} did today", dwell_ms=2200
    ):
        audit.search(audit_seed.actor_name)

        # Rows are picked out by their Resource, and the Record ID is then read
        # off the cell — not the other way round. A record id is a small integer
        # that appears in the timestamp of every row ("August 9, …"), and the two
        # seeded records can perfectly well share one (they are ids in *different*
        # tables), so filtering rows on it selects half the log.
        booked_category = audit.log_row(
            audit_seed.actor_name, AUDIT_INCOME_TYPE_TABLE
        ).first
        expect(booked_category).to_be_visible(timeout=20_000)
        expect(audit.record_id_cell(booked_category)).to_have_text(
            _audit_record_id(audit_seed.income_type_id)
        )
        expect(booked_category).to_contain_text(AUDIT_CREATE_ACTION)

        banked_receipt = audit.log_row(
            audit_seed.actor_name, AUDIT_INCOME_TABLE
        ).first
        expect(banked_receipt).to_be_visible(timeout=20_000)
        expect(audit.record_id_cell(banked_receipt)).to_have_text(
            _audit_record_id(audit_seed.income_id)
        )
        expect(banked_receipt).to_contain_text(AUDIT_CREATE_ACTION)

    with demo.step("Narrow it to the records that were created", dwell_ms=1800):
        audit.filter_by_action(CREATE_OPTION)
        expect(
            audit.log_row(audit_seed.actor_name, AUDIT_INCOME_TYPE_TABLE).first
        ).to_be_visible(timeout=15_000)
        expect(
            audit.log_row(audit_seed.actor_name, AUDIT_INCOME_TABLE).first
        ).to_be_visible(timeout=15_000)

    with demo.step("Nothing matches a name nobody here answers to", dwell_ms=1800):
        audit.search(AUDIT_NO_SUCH_ACTOR)
        audit.expect_empty()
        # Put the accountant's trail back, so the entry opened next is the one
        # the previous steps were reading.
        audit.search(audit_seed.actor_name)
        expect(
            audit.log_row(audit_seed.actor_name, AUDIT_INCOME_TYPE_TABLE).first
        ).to_be_visible(timeout=15_000)

    with demo.step(
        "Open one entry to see exactly what was recorded, and by whom",
        dwell_ms=3000,
    ):
        row = audit.log_row(
            audit_seed.actor_name, AUDIT_INCOME_TYPE_TABLE
        ).first
        drawer = audit.open_details(row)
        expect(drawer).to_contain_text(DRAWER_TITLE)

        expect(audit.drawer_value(DRAWER_USER_DETAILS)).to_contain_text(
            audit_seed.actor_name
        )
        # The badge sits in the same block as the timestamp, so this is a
        # substring of "August 9, 2026, 03:12:44 PMCreate" — never anchored.
        expect(audit.drawer_value(DRAWER_TIME_OF_ACTION)).to_contain_text(
            AUDIT_CREATE_BADGE
        )
        expect(audit.drawer_value(DRAWER_AFFECTED_RESOURCE)).to_contain_text(
            AUDIT_INCOME_TYPE_TABLE_SHOWN
        )
        # A creation has no before-state, so `parseState` falls through to its
        # placeholder — and the after-state is the record the backend stored.
        expect(audit.drawer_value(DRAWER_BEFORE_STATE)).to_have_text(
            DRAWER_NOT_PROVIDED
        )
        after_state = audit.drawer_value(DRAWER_AFTER_STATE)
        expect(after_state).to_contain_text(AUDIT_INCOME_TYPE_NAME)
        expect(after_state).to_contain_text(AUDIT_INCOME_TYPE_DESCRIPTION)
        expect(audit.drawer_value(DRAWER_BRANCH_ID)).to_contain_text(
            str(audit_seed.branch_id)
        )

    with demo.step(
        "Behind the screen, this trail is scoped to their own school alone",
        dwell_ms=2500,
    ):
        _expect_backend_serves_the_same_trail(api, ctx, audit_seed)


# ─────────────────────── helpers for the view path ──────────────────────────


def _audit_record_id(record_id: int) -> re.Pattern[str]:
    """The Record ID cell for ``record_id`` — the whole cell, nothing else.

    Anchored so that id 9 cannot be satisfied by a cell reading 19 or 90.
    """
    return re.compile(rf"^\s*{record_id}\s*$")


def _expect_backend_serves_the_same_trail(
    api: BackendAPI, ctx: SchoolContext, audited: AuditedActions
) -> None:
    """``GET /audilog/`` answers this admin with their own school's rows, only.

    Without this the UI half proves only that *a* table rendered; it says nothing
    about the branch scoping in ``list_audit_logs_with_separate_count``, which is
    the single thing most likely to regress a governance log into showing another
    school's history.
    """
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    logs = api.get("/audilog/?skip=0&limit=50", token=token)
    assert logs.status_code == 200, (
        f"a SchoolAdmin of a school licensed for {AUDIT_MODULE!r} and "
        f"{AUDIT_LIST_PERMISSION_MODULE!r} must be able to read their own audit "
        f"log — got {logs.status_code}: {logs.text[:300]}"
    )
    body = logs.json()
    assert body.get("total_count", 0) > 0, (
        f"the audit log for {ctx.school_name!r} is empty, yet the accountant's "
        f"two writes were accepted — the rows are either not being written or "
        f"not being scoped to this school's branch"
    )

    results = body.get("results") or []
    recorded = {(row["table_name"], row["record_id"]) for row in results}
    assert (AUDIT_INCOME_TYPE_TABLE, audited.income_type_id) in recorded, (
        f"the accountant's new income type (id {audited.income_type_id}) is "
        f"missing from the school's audit log, so the screen above was showing "
        f"something other than this school's history"
    )
    assert (AUDIT_INCOME_TABLE, audited.income_id) in recorded, (
        f"the accountant's banked receipt (id {audited.income_id}) is missing "
        f"from the school's audit log"
    )

    branches = {row.get("branch_id") for row in results}
    assert branches <= {audited.branch_id}, (
        f"the log served this SchoolAdmin carries rows from branches "
        f"{sorted(b for b in branches if b is not None)}, but their school has "
        f"only branch {audited.branch_id} — the branch scoping in "
        f"list_audit_logs_with_separate_count is leaking another school's history"
    )


# ───────────────────── the module can never be unlicensed ───────────────────


@pytest.mark.school_admin
@pytest.mark.scenario(MANDATORY_SCENARIO)
def test_audit_trails_is_reachable_on_the_minimal_pack(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """The floor case still has its audit log: licensed, offered and answering.

    Ledger unit ``governance.audit_trails.always_licensed``. See the module
    docstring: ``audit_trails`` is in the ``governance`` group, the pack builder
    locks that whole group into every pack, and governance being core is
    **intended product behaviour, confirmed 2026-08-09**. So this asserts the
    opposite of a denial — and adds no gate of any kind.

    Read-only throughout. The log is a read-only screen (``api/routes/auditlog.py``
    exposes two GETs and nothing else), and the point here is reachability, so
    nothing is seeded: an empty table is a perfectly good pass as long as it is
    the *table* and not ``PageError`` or ``/auth/no-access``.
    """
    ctx = provisioned_school
    requested = set(ctx.feature_modules)
    audit = AuditTrailsPage(page, frontend_base_url)

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
    assert AUDIT_MODULE in groups.get(GOVERNANCE_GROUP, []), (
        f"{AUDIT_MODULE!r} is no longer in the {GOVERNANCE_GROUP!r} group of the "
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
    for key in (AUDIT_MODULE, AUDIT_LIST_PERMISSION_MODULE):
        assert key in locked, (
            f"{key!r} is no longer one of the modules the SuperAdmin's "
            f"create-pack form forces into every pack, so the audit screen can "
            f"now be sold away from a school and this unit's premise is gone. "
            f"That is a product change, not a test failure to paper over — "
            f"re-read config/feature_scenarios.yaml's `minimal` note and rewrite "
            f"this unit as a real denial test. Locked: {sorted(locked)}"
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
    assert AUDIT_MODULE in licensed, (
        f"{ctx.school_name!r} — the most restricted pack this product can build — "
        f"is not licensed for {AUDIT_MODULE!r}. Governance is core and always on "
        f"by design, so a school has just lost the record of who changed what. "
        f"Licensed: {sorted(licensed)}"
    )
    assert AUDIT_LIST_PERMISSION_MODULE in licensed, (
        f"{ctx.school_name!r} is licensed for {AUDIT_MODULE!r} but not for "
        f"{AUDIT_LIST_PERMISSION_MODULE!r}, and every route in "
        f"api/routes/auditlog.py is gated on "
        f"('read', {AUDIT_LIST_PERMISSION_MODULE!r}) rather than on the module "
        f"the screen is named for. The log would render its shell and then be "
        f"refused its own data. Licensed: {sorted(licensed)}"
    )

    # ── 2. The licence is enforced for this user, on a module outside the lock ─
    #
    # Without this, everything below is equally consistent with a feature-pack
    # system that never refuses anybody — and every frontend gate on this screen
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
        f"does, 'audit trails is reachable' says nothing. Body: {gated.text[:300]}"
    )
    assert FEATURE_PACK_403.search(gated.text), (
        f"{ENFORCED_UNLICENSED_PATH} was refused, but not by the feature pack — "
        f"the detail should be 'Feature not available in your plan'. "
        f"Body: {gated.text[:300]}"
    )

    # ── 3. Offered: the sidebar entry a SchoolAdmin sees on landing ───────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # No branch is selected right after login, which is the state the Governance
    # section (noBranchOnly in nav-config.tsx) renders in. The branchOnly "Audit
    # Overview" section offers the same link once a branch is picked; either
    # route arrives at the same page.
    expect(page.get_by_text(NAV_SECTION_GOVERNANCE).first).to_be_visible(timeout=20_000)
    # Scoped to the sidebar: /module/home's QuickActions grid carries a card with
    # the same label and the same href, so an unscoped match would pass on the
    # landing page alone.
    nav = page.get_by_role("navigation")
    expect(
        nav.get_by_role("link", name=as_pattern(AUDIT_NAV_AUDIT_TRAILS)).first
    ).to_be_visible(timeout=20_000)
    expect(nav.locator(f'a[href="/module/{AUDIT_ROUTE}"]').first).to_be_visible()

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
    assert AUDIT_MODULE in cookie_modules, (
        f"{AUDIT_MODULE!r} is missing from this session's {MODULES_COOKIE!r} "
        f"cookie, so src/middleware.ts would gate /module/{AUDIT_ROUTE} for any "
        f"role without the SchoolAdmin carve-out — the module is not reachable "
        f"on the {MANDATORY_SCENARIO!r} pack for anybody else"
    )

    # ── 4. Working: the route loads and the screen's own fetch answers ────────
    # Asking for the route by hand is the request middleware.ts actually sees.
    goto_module(page, frontend_base_url, AUDIT_ROUTE)
    audit.expect_loaded()
    assert not DENIAL_URL.search(page.url), (
        f"the SchoolAdmin of {ctx.school_name!r} was redirected to {page.url!r} "
        f"asking for a module their pack licenses. Governance is core and always "
        f"on by design — a denial here is a regression, not a gate to keep."
    )
    assert page.url.rstrip("/").endswith(f"/module/{AUDIT_ROUTE}"), (
        f"expected to still be on /module/{AUDIT_ROUTE}, but the app moved to "
        f"{page.url!r}"
    )

    # The register itself, not a shell: PageError would have replaced the whole
    # table with "Failed to load audit logs" had the mount fetch been refused.
    audit.expect_no_load_failure()
    expect(page.get_by_role("heading", name=SUBHEADING)).to_be_visible()
    for column in (COLUMN_RECORD_ID, COLUMN_CREATED_AT, COLUMN_USER, COLUMN_RESOURCE):
        expect(audit.column_header(column).first).to_be_visible()
    # Rendered from `totalPages`, which only exists once the fetch resolved.
    expect(page.get_by_text(PAGINATION)).to_be_visible()
    # Deliberately no assertion about rows. This school's writes are all the
    # SchoolAdmin's own, and those land with a NULL AuditLog.branch_id, which the
    # list route's branch filter excludes — an empty log here is expected, and
    # reachability is what this unit is about.

    # ── 5. And the module's API surface answers this admin directly ───────────
    logs = api.get(AUDIT_LIST_PATH, token=token)
    assert logs.status_code == 200, (
        f"GET {AUDIT_LIST_PATH} answered {logs.status_code} for the SchoolAdmin "
        f"of {ctx.school_name!r}, whose pack licenses both {AUDIT_MODULE!r} and "
        f"{AUDIT_LIST_PERMISSION_MODULE!r}. A 403 carrying 'Feature not available "
        f"in your plan' would mean the governance group stopped being locked into "
        f"every pack; anything else is the route itself breaking. "
        f"Body: {logs.text[:300]}"
    )
    assert not FEATURE_PACK_403.search(logs.text), (
        f"GET {AUDIT_LIST_PATH} returned 200 but its body reads like the "
        f"feature-pack refusal: {logs.text[:300]}"
    )
    log_body = logs.json()
    assert "results" in log_body and "total_count" in log_body, (
        f"GET {AUDIT_LIST_PATH} did not answer the paginated shape the screen "
        f"reads (`results` + `total_count`, api/api_models/auditlog.py) — got "
        f"keys {sorted(log_body)}"
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
