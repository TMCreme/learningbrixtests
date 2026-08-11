"""Payroll → Staff Payroll — monthly payroll runs (`staff_payroll`).

Where this module lives
    ``/module/staff_payroll`` (``smsfrontend/src/app/module/staff_payroll/page.tsx``),
    reached from the sidebar's branch-only "Payroll Module" section
    (``nav-config.tsx``: "Staff Payroll", alongside "Tax Config" and
    "Net-to-Gross"). The screen is the "Staff payroll" workspace — a card/table
    list of payroll runs over ``GET /payroll/runs``, a "Generate payroll Run"
    button that posts ``POST /payroll/{branch_id}/{period}``, per-run
    "View details" / "Approve" / "Reject" actions, and the tax screens that sit
    beside it (``/payroll/tax-config``, ``/payroll/reverse-calculate/{branch}``,
    ``/payroll/export/…``, ``/payroll/ssnit-remittance/…``).

Manage path: the ledger unit ``payroll.staff_payroll.manage.accountant`` is
**BLOCKED** — the Accountant role holds no ``staff_payroll`` permission of any
kind, so the generate-then-review walkthrough it asks for cannot be performed by
that role at all, and granting the permission is a product decision rather than a
defect fix. ``test_staff_payroll_is_licensed_but_closed_to_the_accountant``
stands in its place and pins the refusal from both ends; its section below
carries the product question, the evidence, and the walkthrough to write the day
the question is answered.

View path: the Teacher of the same ``finance_only`` school reads their own pay
(``test_teacher_views_their_payslips``) — ledger unit
``payroll.staff_payroll.view.teacher``. It is a *different screen* from the
register above, deliberately, and the long section comment beside that test
explains why the register is not the teacher's read-only surface and why nothing
in the app was changed to make it one.

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack is
the floor case the pack builder can actually produce — the locked "people" and
"governance" groups and nothing else, so no ``staff_payroll``
(``test_staff_payroll_denied_for_school_admin_when_module_disabled``).

Where the denial actually lives — and where it does NOT
    Nothing in the frontend denies this role. Every gate it passes through waves
    a SchoolAdmin past *before* the feature pack is consulted:

    * ``src/middleware.ts`` skips its module enforcement for a SchoolAdmin
      outright (``!isSchoolAdmin`` in the redirect condition), so the route is
      never turned away before it mounts.
    * ``useModuleGuard("staff_payroll")`` returns ``true`` for a SchoolAdmin
      *before* it reads the ``schoolModules`` cookie, so the
      ``hasModuleAccess === false`` branch — the one that renders ``null`` and
      pushes /auth/no-access — is unreachable for this role.
    * ``usePermissionGuard("staff_payroll")`` returns early on
      ``isSchoolAdminRole(role)`` in its effect and returns ``true`` from its
      ``hasAccess`` memo on the same test, so ``if (!hasPermission) return null``
      never fires either.
    * The sidebar entry is not hidden. ``SideNavigation.canShowItem`` returns on
      the *permission* check before the module gate ("Permission check takes
      priority — having the permission implies the module is available"), and
      ``db/repository/permissions.py`` seeds the SchoolAdmin role with
      ``("manage", "staff_payroll")`` — which also satisfies the section-level
      ``permissionsGate: ["staff_payroll", "payslips"]``. So both the "Payroll
      Module" section and its "Staff Payroll" item render whatever the pack says,
      and their presence asserts nothing about this school's licence.

    What denies them is the backend, and only on the routes that actually carry
    the gate. ``api/routes/payroll.py`` puts
    ``Depends(has_permission(<read|manage>, "staff_payroll"))`` on the tax
    configuration CRUD, the net-to-gross reverse calculator, the approve/reject
    actions, the CSV export and the SSNIT remittance summary. That dependency is
    solved before the path params are used and before any row is looked up, and
    the feature-pack half of ``utils.permissions.has_permission`` answers
    **403 "Feature not available in your plan"** for a school whose pack omits
    the module named in it. Those routes are what this test asserts.

Deliberately NOT asserted: that the list/calculate routes are refused
    ``GET /payroll/runs``, ``POST /payroll/{branch_id}/{period}`` (the "Generate
    payroll Run" button), ``GET /payroll/runs/{id}/details`` and
    ``GET /payroll/runs/{branch_id}/{period}`` carry **no** ``has_permission``
    dependency at all — unlike every sibling route in the same file. So an
    unlicensed SchoolAdmin still reaches the workspace, still lists runs and
    still generates one. That is a product question (is the gate missing by
    oversight, or are payroll runs deliberately readable by a school admin
    regardless of plan?), not something a test may decide: adding the dependency
    would be enforcing a licence check that is currently unenforced. It is
    therefore neither asserted as denied (it is not) nor asserted as allowed
    (that would freeze the hole in place as expected behaviour). The gap is
    recorded for the product owner instead.

    For the same reason there is no UI half to this test. With no refusal on the
    page's own fetch there is no redirect for the axios interceptor in
    ``src/utils/handleErrorMessage.ts`` to perform, so there is no denial surface
    on ``/module/staff_payroll`` to assert against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import TEST_PREFIX, run_tag
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto
from tests.pages.login import login_as

STAFF_PAYROLL_MODULE = "staff_payroll"

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

# A period the payroll screens would ask for. Arbitrary: every route below is
# refused by its route-level dependency long before the period is parsed.
DENIED_PERIOD = "2026-01"


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_staff_payroll_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """With the module off the pack, every gated payroll route refuses this admin.

    "Gated" is the whole qualification, and it is deliberate — see the module
    docstring for the four payroll routes that carry no feature-pack dependency
    and are therefore left out rather than asserted either way.
    """
    ctx = provisioned_school
    if STAFF_PAYROLL_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {STAFF_PAYROLL_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had payroll rights anyway", which would make the 403s vacuous.
    # db/repository/permissions.py seeds this role with ("manage",
    # "staff_payroll"), and has_permission lets manage stand in for read — so the
    # permission half of the gate passes outright for every route asserted below.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert STAFF_PAYROLL_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{STAFF_PAYROLL_MODULE!r} permission, which is the one every gated "
        f"payroll route is checked against. This test would then be asserting a "
        f"denial the role gets for free. Re-point it at the feature pack only, or "
        f"fix the seed in newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{STAFF_PAYROLL_MODULE!r} proves nothing about the gate — "
        f"has_permission treats an unpacked school as unrestricted. Provisioning "
        f"phase A assigns one; check that it did."
    )
    licensed = body.get("modules") or []
    assert STAFF_PAYROLL_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {STAFF_PAYROLL_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every gated payroll route is refused ────────────
    #
    # Both halves of the gate are covered — the reads the payroll screens perform
    # (has_permission("read", "staff_payroll")) and the writes their buttons
    # perform (has_permission("manage", "staff_payroll")). Ids and periods are
    # deliberately arbitrary: has_permission is a route-level dependency, solved
    # before the path params are used and long before any row is looked up, so a
    # 404 here would itself be the failure. The branch id is real so that a
    # regression which *did* let one through fails on its own merits rather than
    # on a 400 BRANCH_ID_REQUIRED raised inside the handler. For the same reason
    # the create body below never has to be creatable, but it carries the TEST
    # prefix anyway so a regression that stored it leaves a sweepable row.
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"?branch_id={branch_id}" if branch_id else ""
    tag = run_tag()

    refusals = {
        # The read half — /module/tax_config's list and detail, the CSV export
        # the payroll screen offers, and the SSNIT remittance summary.
        "tax_config_list": api.get(f"/payroll/tax-config{branch_query}", token=token),
        "tax_config_detail": api.get(
            f"/payroll/tax-config/1{branch_query}", token=token
        ),
        "export_csv": api.get(
            f"/payroll/export/{branch_id or 1}/{DENIED_PERIOD}", token=token
        ),
        "ssnit_remittance": api.get(
            f"/payroll/ssnit-remittance/{branch_id or 1}/{DENIED_PERIOD}", token=token
        ),
        # …and the manage half: the tax-config writes, the Net-to-Gross
        # calculator, and the run list's "Approve" / "Reject" actions.
        "tax_config_create": api.post(
            f"/payroll/tax-config{branch_query}",
            token=token,
            json={
                "name": f"{TEST_PREFIX} Denied Levy {tag}",
                "mode": "flat_percent",
                "rate": 0.05,
                "tax_bearer": "Employee",
                "target": "base_salary",
                "expense_account": f"{TEST_PREFIX} Payroll Expense",
                "liability_account": f"{TEST_PREFIX} Payroll Liability",
            },
        ),
        "tax_config_reorder": api.post(
            f"/payroll/tax-config/reorder-steps{branch_query}",
            token=token,
            json={"ordered_ids": {"1": 1}},
        ),
        "tax_config_delete": api.delete(
            f"/payroll/tax-config/1{branch_query}", token=token
        ),
        "reverse_calculate": api.post(
            f"/payroll/reverse-calculate/{branch_id or 1}",
            token=token,
            json={
                "target_net_pay": 1000,
                "selected_config_ids": [],
                "benefit_code": "base_salary",
            },
        ),
        "approve_run": api.post(
            f"/payroll/runs/1/approve?remarks={TEST_PREFIX}+denied+{tag}"
            + (f"&branch_id={branch_id}" if branch_id else ""),
            token=token,
        ),
        "reject_run": api.post(
            f"/payroll/runs/1/reject?remarks={TEST_PREFIX}+denied+{tag}"
            + (f"&branch_id={branch_id}" if branch_id else ""),
            token=token,
        ),
    }

    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{STAFF_PAYROLL_MODULE!r}, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )


# ═══════ payroll.staff_payroll.manage.accountant — BLOCKED ══════════════════
#
# The ledger unit ``payroll.staff_payroll.manage.accountant`` (scenario
# ``finance_only``, role ``accountant``, intent ``manage``) is recorded
# **BLOCKED** in ``state/blockers.md``. This test is the guard that stands in its
# place, exactly as its sibling unit
# ``payroll.employee_benefit.view.accountant`` is guarded in
# ``test_employee_benefit.py``.
#
# The product question it is blocked on
#     Should the **Accountant** role carry ``("manage", "staff_payroll")`` — i.e.
#     is running the monthly payroll an accountant's job in this product, or is
#     it reserved to the SchoolAdmin, who is the only seeded role that holds it?
#
# Why the happy path cannot be written
#     ``db/repository/permissions.py`` seeds the Accountant with fees,
#     incomes_and_expenses, the staff/student reads and the messaging baseline —
#     and nothing from the Payroll module (neither ``staff_payroll`` nor
#     ``employee_benefit``). Measured live below from ``GET /roles/{id}``, not
#     quoted from source.
#
#     The accountant is therefore shut out in three independent places, none of
#     them the feature pack — this school *is* licensed for the module:
#
#       * **No way in.** The sidebar's "Payroll Module" section is gated on
#         ``permissionsGate: ["staff_payroll", "payslips"]`` and its "Staff
#         Payroll" entry again on ``permission: "staff_payroll"``
#         (``SideNavigation/nav-config.tsx``), so there is no link to click.
#       * **No page.** ``usePermissionGuard("staff_payroll")`` finds no matching
#         permission, so ``/module/staff_payroll`` renders ``null`` and the hook
#         pushes the browser to ``/unauthorized``.
#       * **No data** on the routes that carry the gate: the tax-configuration
#         CRUD, the net-to-gross reverse calculator, the approve/reject actions,
#         the CSV export and the SSNIT remittance summary all sit behind
#         ``has_permission(<read|manage>, "staff_payroll")``
#         (``api/routes/payroll.py``), which answers 403 "You do not have
#         permission to perform this action".
#
#     Making the walkthrough pass would mean granting the Accountant role a
#     ``staff_payroll`` permission. That is granting a role permissions it does
#     not have — a product decision about who may run and sign off payroll, not a
#     defect fixable in place — so nothing was changed in either app.
#
#     Note the Accountant seed was already corrected once, for a real defect: the
#     role shipped with *no* permissions whatsoever and could not open even the
#     finance module it is named after (see ``state/backend_patches.md``). That
#     fix stopped deliberately at the finance modules. Extending it into payroll
#     is the question being escalated, not a continuation of it.
#
# What this test asserts instead — the exact shape of the refusal, from both ends
#     1. The school **is** licensed for ``staff_payroll``, and a role at that same
#        school **does** hold ``manage staff_payroll``. Without this the 403s
#        below would be indistinguishable from an unlicensed school.
#     2. The Accountant role's own permission set carries nothing for
#        ``staff_payroll``, read live from the API.
#     3. Every payroll route that carries the gate refuses this accountant with
#        403 **"You do not have permission to perform this action"** — the *role*
#        denial. A "Feature not available in your plan" here would mean the pack
#        talking instead, and would make this test a lie.
#     4. The UI never puts the workspace in front of them: no Payroll section and
#        no Staff Payroll link in the sidebar, and asking for
#        ``/module/staff_payroll`` by hand lands on ``/unauthorized`` with none of
#        the workspace's chrome on screen. Deep-linking is the assertion, not a
#        shortcut past the UI: for this role there is no navigation to deep-link
#        past.
#     5. The same gated call succeeds for the SchoolAdmin of the very same school
#        — the control that proves step 3 is about the caller.
#
# Deliberately NOT asserted: that the list/calculate routes refuse the accountant
#     ``GET /payroll/runs``, ``POST /payroll/{branch_id}/{period}`` (the "Generate
#     payroll Run" button), ``GET /payroll/runs/{id}/details`` and
#     ``GET /payroll/runs/{branch_id}/{period}`` carry **no** ``has_permission``
#     dependency at all — unlike every sibling route in the same file. An
#     accountant is therefore *not* refused them over HTTP, and asserting that
#     they are would fail; asserting that they are allowed would freeze an
#     ungated route in place as intended behaviour. Same gap, same reasoning as
#     the denial test at the top of this file.
#
# The walkthrough to write the day this is unblocked
#     Sign in as the accountant → "Staff Payroll" in the sidebar's Payroll
#     section → "Generate payroll Run" → the "Select period" dialog → the run
#     lands on the register (table view; the card grid has no roles to anchor on)
#     showing the processor's name and a Pending badge → the row's "Actions"
#     menu → "View details" → ``/module/staff_payroll/runs/{id}`` → read the run
#     back off ``GET /payroll/runs`` as the accountant with no ``branch_id``, to
#     prove it was written against their own branch. Two things that walkthrough
#     has to know, learned while writing it:
#
#       * The period picker is an antd month picker inside a **modal Radix
#         dialog**. ``BasePage.commit_date`` cannot drive it: antd portals its
#         panel to ``document.body``, which inherits the ``pointer-events: none``
#         Radix puts there, so the panel cell can never receive the click. Fill
#         the ``.ant-picker input`` and press Enter — safe *here specifically*,
#         because this picker's ancestor chain is ``DialogContent`` → ``div`` →
#         ``div`` with no ``<form>`` for a native submit to reach (trap 1), and
#         because the dialog's button label is rebuilt from the picker's state
#         ("Calculate (2026-09)"), so a keystroke that failed to commit fails
#         loudly instead of silently calculating the current month.
#       * ``GET /payroll/runs`` answers **404 "No payroll runs found."** for a
#         branch that has none yet, ``fetchRuns``'s catch turns any error into
#         ``fetchError``, and PageError then replaces the whole workspace —
#         including the "Generate payroll Run" button. A freshly provisioned
#         school therefore cannot generate its *first* run through the UI, and the
#         screen's own empty state is unreachable. Seed one run over the API
#         first, or raise that as its own defect.

MANAGE_SCENARIO = "finance_only"
MANAGE_ACCOUNTANT_ROLE = "Accountant"
MANAGE_SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# Arbitrary ids and periods: every route asserted below is refused by its
# route-level dependency, which is solved before any path param is used and long
# before a row is looked up. A 404 here would itself be the failure.
MANAGE_PERIOD = "2026-09"
MANAGE_UNREACHABLE_ID = 9_999_999

# newschoolapp/core/exceptions.py — the role denial, raised by has_permission
# before the feature-pack branch is reached…
MANAGE_ROLE_403 = re.compile(
    r"^\s*You do not have permission to perform this action\s*$", re.I
)
# …and the denial this test must never see, which would mean the licence, not the
# role, is what refused (utils/permissions.py, feature-pack branch).
MANAGE_PLAN_403 = re.compile(r"feature not available in your plan", re.I)

# Where usePermissionGuard sends a user whose role lacks the module, and the copy
# that page greets them with (src/app/unauthorized/page.tsx).
MANAGE_UNAUTHORIZED_URL = re.compile(r"/unauthorized")
MANAGE_ACCESS_DENIED = re.compile(r"^\s*Access Denied\s*$", re.I)
MANAGE_UNAUTHORIZED_ACCESS = re.compile(r"^\s*Unauthorized Access\s*$", re.I)

# ── the sidebar (SideNavigation/nav-config.tsx) ──────────────────────────────
# The Payroll section and its three register entries must be absent for this
# role…
MANAGE_NAV_PAYROLL_SECTION = re.compile(r"^\s*Payroll Module\s*$", re.I)
MANAGE_NAV_STAFF_PAYROLL = re.compile(r"^\s*Staff Payroll\s*$", re.I)
MANAGE_NAV_TAX_CONFIG = re.compile(r"^\s*Tax Config\s*$", re.I)
MANAGE_NAV_NET_TO_GROSS = re.compile(r"^\s*Net-to-Gross\s*$", re.I)

# …while the Account section is present, which is what stops "nothing was
# rendered" from passing as "payroll was hidden". Both sections are gated the
# same way, on permissionsGate + per-item permission, so the pair reads the
# accountant's own permission set back off the screen.
MANAGE_NAV_ACCOUNT_SECTION = re.compile(r"^\s*Account Module\s*$", re.I)
MANAGE_NAV_INCOME_AND_EXPENSES = re.compile(r"^\s*Income\s*&\s*Expenses\s*$", re.I)

# ── the workspace this role must never be shown (staff_payroll/page.tsx) ─────
MANAGE_HEADING = re.compile(r"^\s*Staff payroll\s*$", re.I)
MANAGE_RUNS_HEADING = re.compile(r"^\s*Payroll Runs\s*$", re.I)
MANAGE_GENERATE_BUTTON = re.compile(r"^\s*Generate payroll Run\s*$", re.I)
MANAGE_SEARCH_FIELD = re.compile(r"^\s*Search by period or processor name\s*$", re.I)

MANAGE_DENIAL_TIMEOUT_MS = 25_000


@pytest.mark.accountant
@pytest.mark.negative
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="payroll.staff_payroll.manage.accountant",
    title="Staff Payroll",
    subtitle="BLOCKED — the Accountant role holds no key to the payroll register",
)
def test_staff_payroll_is_licensed_but_closed_to_the_accountant(
    provisioned_school: SchoolContext,
    api: BackendAPI,
    demo,
) -> None:
    """The accountant of a school licensed for payroll is refused it by role.

    Stands in for the blocked ledger unit
    ``payroll.staff_payroll.manage.accountant``; see the section header for the
    product question and for the walkthrough to write the day it is answered.

    ``provisioned_school`` is requested *before* ``demo`` so that, when this test
    is the first of its scenario to run, the provisioning walkthrough happens
    before the camera rolls rather than as dead frames at the head of the video.
    """
    ctx = provisioned_school
    assert ctx.accountant is not None, (
        "provisioning created no accountant for this school — phase C creates one "
        "from /module/staff's Non-teaching Staff tab, which needs the `staff` "
        "module on the pack"
    )
    assert STAFF_PAYROLL_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {STAFF_PAYROLL_MODULE!r} for "
        f"this unit: the whole point is that the refusal below is the "
        f"accountant's role and not the school's plan"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch, and every payroll route is "
        "scoped to one — phase B creates one for every scenario"
    )
    branch_id = int(ctx.branches[0].get("id") or -1)
    assert branch_id > 0, (
        "provisioning could not capture the branch id — re-run provisioning "
        "rather than guessing it"
    )

    accountant = ctx.accountant
    page: Page = demo.page
    base_url: str = demo.frontend_base_url

    with demo.step(
        f"Sign in as {accountant.full_name}, who keeps the books at "
        f"{ctx.school_name}",
        dwell_ms=2000,
    ):
        login_as(page, base_url, accountant)

    with demo.step("Fees and the books are theirs — the Account menu is right there",
                   dwell_ms=1800):
        expect(
            page.get_by_role(
                "link", name=as_pattern(MANAGE_NAV_INCOME_AND_EXPENSES)
            ).first
        ).to_be_visible(timeout=25_000)
        expect(
            page.get_by_text(as_pattern(MANAGE_NAV_ACCOUNT_SECTION)).first
        ).to_be_visible()

    with demo.step("But there is no Payroll menu, and no Staff Payroll in it",
                   dwell_ms=2000):
        expect(
            page.get_by_text(as_pattern(MANAGE_NAV_PAYROLL_SECTION))
        ).to_have_count(0)
        for entry in (
            MANAGE_NAV_STAFF_PAYROLL, MANAGE_NAV_TAX_CONFIG, MANAGE_NAV_NET_TO_GROSS
        ):
            expect(page.get_by_role("link", name=as_pattern(entry))).to_have_count(0)

    with demo.step("Asking for the payroll register by hand is refused outright",
                   dwell_ms=2500):
        goto(page, base_url.rstrip("/") + "/module/staff_payroll")
        _manage_expect_denial_surface(page)

    with demo.step("The school does license payroll — it is the role that has no key",
                   dwell_ms=2200):
        _manage_expect_school_is_licensed(api, ctx)
        _manage_expect_accountant_role_holds_nothing(api)

    with demo.step("Every gated payroll call answers this accountant 403",
                   dwell_ms=2200):
        _manage_expect_backend_refuses(api, ctx, branch_id=branch_id)

    with demo.step("The same call opens for the administrator of that school",
                   dwell_ms=2000):
        _manage_expect_school_admin_gets_through(api, ctx, branch_id=branch_id)


# ─────────────────────── helpers for the blocked manage unit ─────────────────


def _manage_expect_denial_surface(page: Page) -> None:
    """The workspace must not render for this role, however the app says no.

    ``usePermissionGuard`` does two things at once: ``page.tsx`` renders ``null``
    because ``hasPermission`` is false, and the hook's effect pushes the browser
    to ``/unauthorized``. The redirect is the surface a user sees, so it is what
    is waited for — but a blank module page is a refusal too, and is accepted as
    long as none of the workspace's chrome came with it.
    """
    landed_on_unauthorized = False
    heading = page.get_by_role("heading", name=as_pattern(MANAGE_HEADING)).first

    remaining = MANAGE_DENIAL_TIMEOUT_MS
    while remaining > 0:
        if MANAGE_UNAUTHORIZED_URL.search(page.url):
            landed_on_unauthorized = True
            break
        assert heading.count() == 0, (
            "the Staff Payroll workspace rendered for an Accountant, whose role "
            "holds no staff_payroll permission — the frontend gate has been "
            "dropped while the backend still answers 403 on every gated route, so "
            "this user is being shown a screen whose actions can only fail"
        )
        page.wait_for_timeout(500)
        remaining -= 500

    # Nothing the workspace carries may be on screen, on either surface.
    expect(page.get_by_role("heading", name=as_pattern(MANAGE_HEADING))).to_have_count(0)
    expect(
        page.get_by_role("heading", name=as_pattern(MANAGE_RUNS_HEADING))
    ).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(MANAGE_GENERATE_BUTTON))
    ).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(MANAGE_SEARCH_FIELD))).to_have_count(0)

    if landed_on_unauthorized:
        expect(page.get_by_text(as_pattern(MANAGE_ACCESS_DENIED))).to_be_visible(
            timeout=15_000
        )
        expect(page.get_by_text(as_pattern(MANAGE_UNAUTHORIZED_ACCESS))).to_be_visible()


def _manage_expect_school_is_licensed(api: BackendAPI, ctx: SchoolContext) -> None:
    """The pack carries the module, so the refusal cannot be the licence.

    Read with the SchoolAdmin's token: ``/school_profile/{id}/features`` is the
    single endpoint every frontend gate derives its answer from.
    """
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so this test "
        f"cannot tell a role refusal from an unlicensed school. Provisioning "
        f"phase A assigns one; check that it did."
    )
    assert STAFF_PAYROLL_MODULE in (body.get("modules") or []), (
        f"{ctx.school_name!r} is not licensed for {STAFF_PAYROLL_MODULE!r} despite "
        f"the {ctx.scenario_id!r} pack listing it, so every 403 below would be the "
        f"plan talking rather than the role"
    )


def _manage_expect_accountant_role_holds_nothing(api: BackendAPI) -> None:
    """Measured, not quoted: the Accountant role's permission set is the blocker.

    Also checks that a role at the same school *does* hold
    ``manage staff_payroll``, so "nobody can run payroll" can never pass as "the
    accountant cannot".
    """
    accountant_role = api.get(f"/roles/{api.role_id_for(MANAGE_ACCOUNTANT_ROLE)}")
    assert accountant_role.status_code == 200, (
        f"could not read the {MANAGE_ACCOUNTANT_ROLE} role — got "
        f"{accountant_role.status_code}: {accountant_role.text[:300]}"
    )
    held = {
        (str(p.get("name")), str(p.get("module")))
        for p in accountant_role.json().get("permissions", [])
    }
    payroll_held = {pair for pair in held if pair[1] == STAFF_PAYROLL_MODULE}
    assert not payroll_held, (
        f"the {MANAGE_ACCOUNTANT_ROLE} role now holds {sorted(payroll_held)}. That "
        f"answers the product question this unit is BLOCKED on (state/"
        f"blockers.md): rewrite it as the generate-then-review walkthrough the "
        f"ledger asked for — the recipe is in this section's header — and delete "
        f"this guard."
    )
    assert held, (
        f"the {MANAGE_ACCOUNTANT_ROLE} role has no permissions at all, which is the "
        f"defect already fixed in newschoolapp/db/repository/permissions.py (see "
        f"state/backend_patches.md). It has regressed: every accountant now logs "
        f"in to an empty application, and this test's finding is the least of it."
    )

    admin_role = api.get(f"/roles/{api.role_id_for(MANAGE_SCHOOL_ADMIN_ROLE)}")
    assert admin_role.status_code == 200, (
        f"could not read the {MANAGE_SCHOOL_ADMIN_ROLE} role — got "
        f"{admin_role.status_code}: {admin_role.text[:300]}"
    )
    admin_held = {
        (str(p.get("name")), str(p.get("module")))
        for p in admin_role.json().get("permissions", [])
    }
    assert ("manage", STAFF_PAYROLL_MODULE) in admin_held, (
        f"no seeded {MANAGE_SCHOOL_ADMIN_ROLE} permission for "
        f"{STAFF_PAYROLL_MODULE!r} either, so this module is closed to everybody "
        f"and the accountant's refusal says nothing about the accountant"
    )


def _manage_expect_backend_refuses(
    api: BackendAPI, ctx: SchoolContext, *, branch_id: int
) -> None:
    """Every payroll route that carries the gate refuses this accountant.

    Both halves are covered — the reads the payroll screens perform
    (``has_permission("read", "staff_payroll")``) and the writes their buttons
    perform (``manage``) — because the grant being escalated would carry both.
    The four ungated routes are deliberately absent; see the section header.
    """
    token = api.login(ctx.accountant.email, ctx.accountant.password)["access_token"]
    tag = run_tag()

    refusals = {
        # The read half — /module/tax_config's list and detail, the CSV export the
        # payroll screen offers, and the SSNIT remittance summary.
        "tax_config_list": api.get(
            f"/payroll/tax-config?branch_id={branch_id}", token=token
        ),
        "tax_config_detail": api.get(
            f"/payroll/tax-config/{MANAGE_UNREACHABLE_ID}?branch_id={branch_id}",
            token=token,
        ),
        "export_csv": api.get(
            f"/payroll/export/{branch_id}/{MANAGE_PERIOD}", token=token
        ),
        "ssnit_remittance": api.get(
            f"/payroll/ssnit-remittance/{branch_id}/{MANAGE_PERIOD}", token=token
        ),
        # …and the manage half: the tax-config writes, the Net-to-Gross
        # calculator, and the run list's Approve / Reject actions — the two the
        # workspace would offer this role if it could reach it at all.
        "tax_config_create": api.post(
            f"/payroll/tax-config?branch_id={branch_id}",
            token=token,
            json={
                "name": f"{TEST_PREFIX} Refused Levy {tag}",
                "mode": "flat_percent",
                "rate": 0.05,
                "tax_bearer": "Employee",
                "target": "base_salary",
                "expense_account": f"{TEST_PREFIX} Payroll Expense",
                "liability_account": f"{TEST_PREFIX} Payroll Liability",
            },
        ),
        "tax_config_delete": api.delete(
            f"/payroll/tax-config/{MANAGE_UNREACHABLE_ID}?branch_id={branch_id}",
            token=token,
        ),
        "reverse_calculate": api.post(
            f"/payroll/reverse-calculate/{branch_id}",
            token=token,
            json={
                "target_net_pay": 1000,
                "selected_config_ids": [],
                "benefit_code": "base_salary",
            },
        ),
        "approve_run": api.post(
            f"/payroll/runs/{MANAGE_UNREACHABLE_ID}/approve"
            f"?remarks={TEST_PREFIX}+refused+{tag}&branch_id={branch_id}",
            token=token,
        ),
        "reject_run": api.post(
            f"/payroll/runs/{MANAGE_UNREACHABLE_ID}/reject"
            f"?remarks={TEST_PREFIX}+refused+{tag}&branch_id={branch_id}",
            token=token,
        ),
    }

    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: the {MANAGE_ACCOUNTANT_ROLE} role holds no "
            f"{STAFF_PAYROLL_MODULE!r} permission, so the backend must refuse with "
            f"403 — got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert MANAGE_ROLE_403.search(detail), (
            f"{label}: 403 is right but the reason is not the role — got {detail!r}"
        )
        assert not MANAGE_PLAN_403.search(detail), (
            f"{label}: refused for the school's plan rather than the caller's "
            f"role. {ctx.school_name!r} is licensed for {STAFF_PAYROLL_MODULE!r}, "
            f"so this test would be reporting somebody else's denial — got "
            f"{detail!r}"
        )


def _manage_expect_school_admin_gets_through(
    api: BackendAPI, ctx: SchoolContext, *, branch_id: int
) -> None:
    """The control: the same gated call, the same school, a role that holds it.

    Only the permission gate is under test here, so the assertion is "not 403"
    rather than "200".
    """
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    res = api.get(f"/payroll/tax-config?branch_id={branch_id}", token=token)
    assert res.status_code != 403, (
        f"the {MANAGE_SCHOOL_ADMIN_ROLE} of {ctx.school_name!r} was refused the "
        f"branch's tax configuration too ({res.status_code}: {res.text[:300]}), so "
        f"the accountant's 403 is not about the accountant — the whole payroll "
        f"module has closed, and that is a bigger finding than this unit's."
    )


# ═════════════════ payroll.staff_payroll.view.teacher ════════════════════════
#
# The read-only half of `staff_payroll`, for a Teacher of the `finance_only`
# school: they open their own payslips, not the school's payroll register.
#
# Why this test does NOT drive /module/staff_payroll
#     Because that screen is not a teacher's screen, by the app's own design, and
#     making it one would be exactly the kind of change a test may not make.
#
#     `db/repository/permissions.py` seeds the Teacher role with no
#     `staff_payroll` permission of any kind — not `read`, not `manage`. The
#     consequences are consistent all the way down, which is what marks it as
#     intent rather than oversight:
#
#       * `usePermissionGuard("staff_payroll")` finds no matching permission, so
#         /module/staff_payroll's `if (!hasPermission) return null` fires and its
#         effect pushes the browser to /unauthorized;
#       * the sidebar never offers it either — `SideNavigation.canShowSection`
#         requires one of `permissionsGate: ["staff_payroll", "payslips"]` and
#         `canShowItem` requires `permission: "staff_payroll"`, so the whole
#         "Payroll Module" section is absent for this role;
#       * and the register's gated routes (tax config, approve/reject, export,
#         SSNIT remittance) answer 403 on the permission half of
#         `utils.permissions.has_permission`.
#
#     Granting the Teacher role a `staff_payroll` permission to make a "view"
#     test pass would be granting a role permissions it does not have — a product
#     decision, not a defect fix. So nothing was granted.
#
# What the teacher's read-only surface actually is
#     `/module/my_payslips`, which `src/middleware.ts` maps onto this very module
#     (`MODULE_PATH_MAP.my_payslips = "staff_payroll"`). It is gated on the
#     school's *licence* only — `useModuleGuard("staff_payroll")` plus a role-name
#     check for "teacher"/"staff" — and it is served by the self-service endpoints
#     `GET /payroll/me/payslips[/{period}]`, which carry no `has_permission`
#     dependency and read `user.school_branch_id` and `user.id` off the token.
#     A teacher may therefore read their own pay and no one else's, which is
#     precisely what "view" means for this module and this role.
#
#     The route into it is the staff home page: `StaffView` renders
#     `RecentPayslips` when `hasModuleLicence("staff_payroll")`, and that card's
#     "View All Payslips" link is the only navigation the app offers to the full
#     history — there is no sidebar entry for it. The walkthrough uses it, so the
#     video shows how a real teacher gets there.
#
# Why the payslip is seeded over the API
#     A payslip is the *output* of the accountant's walkthrough: an employee
#     benefit, then a payroll calculation for the period, then an approval —
#     `GET /payroll/me/payslips` filters on `PayrollRun.is_approved`, so an
#     unapproved run is invisible to the teacher by design. Driving all three
#     through the register's UI would be the `manage.accountant` unit's video
#     wearing a different name, so they are posted straight to the API — the same
#     setup-only use of `api` that `school_provisioning._seed_fee_group` makes —
#     and every assertion is then made on what the teacher's own screens render.
#
# Why no figure below is hard-coded
#     Every test in the `finance_only` scenario shares one provisioned school, so
#     the branch's tax configuration and the teacher's benefits are not this
#     unit's private property — the accountant unit writes into the same branch.
#     The seed is therefore idempotent (it reuses whatever is already there) and
#     the expected amounts are read back from `/payroll/me/payslips` and asserted
#     against what the screen shows. That keeps the test honest about the one
#     thing it owns — that the teacher's payslip screens render the teacher's
#     payslip — instead of asserting arithmetic another unit can move.
#
# Deliberately NOT asserted: that any payroll route refuses this teacher.
#     `GET /payroll/runs` and `POST /payroll/{branch_id}/{period}` carry no
#     permission dependency at all (see the denial section's docstring above), so
#     a teacher is not in fact refused them. Asserting that they are would fail;
#     asserting that they are allowed would freeze an ungated route in place as
#     intended behaviour. The absence of the register from this teacher's
#     navigation is asserted instead, because that gate the app really does
#     implement.

VIEW_SCENARIO = "finance_only"
VIEW_EMPLOYEE_BENEFIT_MODULE = "employee_benefit"

# The month this unit books pay for. Fixed rather than "this month" so the run
# the assertions look for is the run this seed made, and so the caption in the
# video reads the same on every run. Deliberately not the accountant unit's
# MANAGE_PERIOD (2026-09): both units share one provisioned school, and a second
# calculate_payroll for the same period would write a second PayrollDetail row
# for the same person and month. May is also the one month whose short and long
# names are identical, so the home page card (`month: "short"`) and the payslip
# screens (`month: "long"`) can be matched with one pattern.
VIEW_PERIOD = "2026-05"
VIEW_PERIOD_SHOWN = re.compile(r"May\s+2026", re.I)

# What the seed puts on the payslip when the branch has none of it yet. TEST is
# what the orphan sweeper matches on; the run tag keeps parallel agents apart.
VIEW_TAG = run_tag()
VIEW_BASE_SALARY_ITEM = f"{TEST_PREFIX} Teaching Base Salary {VIEW_TAG}"
VIEW_BASE_SALARY_AMOUNT = 3600.0
VIEW_ALLOWANCE_ITEM = f"{TEST_PREFIX} Transport Allowance {VIEW_TAG}"
VIEW_ALLOWANCE_AMOUNT = 400.0
VIEW_SALARY_BAND = f"{TEST_PREFIX} Teaching Band {VIEW_TAG}"

# One employee-borne deduction, so the payslip has a breakdown to read rather
# than a column of zeros. The account codes are two of the ones
# `LedgerService.STANDARD_CHART` seeds for every school ("SSNIT Tier 1 Expense" /
# "SSNIT Tier 1 Payable") — approval posts a journal against them, and
# `PayrollConfigService._validate_tax_config_accounts` rejects codes the branch's
# chart does not carry.
VIEW_TAX_CONFIG_NAME = "SSNIT Tier 1"
VIEW_TAX_CONFIG_RATE = 0.055
VIEW_TAX_EXPENSE_ACCOUNT = "5121"
VIEW_TAX_LIABILITY_ACCOUNT = "2121"

# ── the copy these screens render ────────────────────────────────────────────
# Home: src/app/module/home/components/RecentPayslips.tsx
VIEW_RECENT_PAYSLIPS = re.compile(r"^\s*Recent Payslips\s*$", re.I)
VIEW_ALL_PAYSLIPS_LINK = re.compile(r"View All Payslips", re.I)

# List: src/app/module/my_payslips/page.tsx
VIEW_MY_PAYSLIPS_HEADING = re.compile(r"^\s*My Payslips\s*$", re.I)
VIEW_PAY_HISTORY = re.compile(r"^\s*Pay History\s*$", re.I)
VIEW_LATEST_NET_PAY_TILE = re.compile(r"^\s*Latest Net Pay\s*$", re.I)
VIEW_TOTAL_EARNED_TILE = re.compile(r"^\s*Total Earned \(YTD\)\s*$", re.I)
VIEW_TOTAL_DEDUCTIONS_TILE = re.compile(r"^\s*Total Deductions \(YTD\)\s*$", re.I)
VIEW_APPROVED_BADGE = re.compile(r"^\s*Approved\s*$", re.I)
VIEW_ROW_VIEW_LINK = re.compile(r"^\s*View\s*$", re.I)
VIEW_UNAUTHORIZED = re.compile(r"Unauthorized Access", re.I)
VIEW_LOAD_FAILURE = re.compile(r"Failed to load payslips", re.I)

# Detail: src/app/module/my_payslips/[period]/page.tsx
VIEW_NET_PAY_LABEL = re.compile(r"^\s*Net Pay\s*$", re.I)
VIEW_EMPLOYER_PANEL = re.compile(r"^\s*Employer\s*$", re.I)
VIEW_EMPLOYEE_PANEL = re.compile(r"^\s*Employee\s*$", re.I)
VIEW_EARNINGS_PANEL = re.compile(r"^\s*Earnings\s*$", re.I)
VIEW_DEDUCTIONS_PANEL = re.compile(r"^\s*Deductions\s*$", re.I)
VIEW_BASIC_SALARY_ROW = re.compile(r"^\s*Basic Salary\s*$", re.I)
VIEW_DETAILS_ERROR = re.compile(r"Error Loading Details", re.I)
VIEW_DOWNLOAD_PDF = re.compile(r"Download PDF", re.I)

# The register this teacher must NOT be offered (nav-config.tsx).
VIEW_PAYROLL_SECTION = re.compile(r"^\s*Payroll Module\s*$", re.I)
VIEW_STAFF_PAYROLL_LINK = re.compile(r"^\s*Staff Payroll\s*$", re.I)


@dataclass(frozen=True)
class TeacherPayslip:
    """The one approved payslip this unit puts in front of the teacher.

    The money fields are what ``GET /payroll/me/payslips`` serves for
    ``VIEW_PERIOD`` — i.e. what the screens are supposed to be showing — not what
    the seed asked for. See "Why no figure below is hard-coded" above.
    """

    branch_id: int
    user_id: int
    period: str
    gross_pay: float
    total_deductions: float
    net_pay: float
    details: dict[str, Any]


@pytest.fixture
def teacher_payslip(
    provisioned_school: SchoolContext, api: BackendAPI
) -> TeacherPayslip:
    """Give the provisioned teacher one approved payslip for ``VIEW_PERIOD``.

    Idempotent at every step: an existing tax configuration, employee benefit or
    payroll run for the period is reused rather than duplicated, because the
    ``finance_only`` school is shared with the accountant unit and a second
    ``calculate_payroll`` for the same period would write a second
    ``PayrollDetail`` row for the same person and month.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert STAFF_PAYROLL_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {STAFF_PAYROLL_MODULE!r} for "
        f"this unit — /module/my_payslips is gated on that licence by "
        f"useModuleGuard, so a teacher of an unlicensed school has no payslip "
        f"screen to read"
    )
    assert VIEW_EMPLOYEE_BENEFIT_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must also license "
        f"{VIEW_EMPLOYEE_BENEFIT_MODULE!r}: a payslip cannot exist without an "
        f"EmployeeBenefit (PayrollProcessor.load_employee_benefits raises 'No "
        f"benefit found for the user'), and every /employee-benefit route is "
        f"gated on that module"
    )
    assert ctx.teacher is not None, (
        "provisioning created no teacher for this school — phase C creates one "
        "from /module/staff's Teaching Staff tab, which needs the `staff` module "
        "on the pack"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch; every payroll route is "
        "scoped to one and /payroll/me/payslips reads it off the teacher's own "
        "account"
    )
    branch_id = int(ctx.branches[0].get("id") or -1)
    assert branch_id > 0, (
        "provisioning could not capture the branch id — re-run provisioning "
        "rather than guessing it"
    )

    teacher_token = api.login(ctx.teacher.email, ctx.teacher.password)["access_token"]
    admin_token = api.login(
        ctx.school_admin.email, ctx.school_admin.password
    )["access_token"]

    user_id = _teacher_user_id(api, admin_token, branch_id, ctx.teacher.email)

    if _my_payslip_for_period(api, teacher_token) is None:
        _ensure_tax_config(api, admin_token, branch_id)
        _ensure_employee_benefit(api, admin_token, branch_id, user_id)
        _ensure_approved_payroll_run(api, admin_token, branch_id)

    row = _my_payslip_for_period(api, teacher_token)
    assert row is not None, (
        f"after seeding, {ctx.teacher.email} still has no approved payslip for "
        f"{VIEW_PERIOD}. /payroll/me/payslips only returns rows whose PayrollRun "
        f"is approved, so either the calculation skipped this employee (no "
        f"EmployeeBenefit) or the approval did not land."
    )
    assert row.get("is_approved") is True, (
        f"the payslip for {VIEW_PERIOD} came back unapproved, which "
        f"/payroll/me/payslips is not supposed to return at all"
    )

    details = api.get(f"/payroll/me/payslips/{VIEW_PERIOD}", token=teacher_token)
    assert details.status_code == 200, (
        f"the payslip breakdown screen is served by "
        f"/payroll/me/payslips/{VIEW_PERIOD} and must answer its own owner — got "
        f"{details.status_code}: {details.text[:300]}"
    )

    return TeacherPayslip(
        branch_id=branch_id,
        user_id=user_id,
        period=VIEW_PERIOD,
        gross_pay=float(row["gross_pay"]),
        total_deductions=float(row["total_deductions"]),
        net_pay=float(row["net_pay"]),
        details=details.json(),
    )


@pytest.mark.teacher
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="payroll.staff_payroll.view.teacher",
    title="Staff Payroll",
    subtitle="Teacher views staff payroll",
)
def test_teacher_views_their_payslips(
    teacher_payslip: TeacherPayslip,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A teacher reads their own pay: the history, then one month's breakdown.

    Every figure asserted on screen is read back from the teacher's own payslip
    feed first, so a screen that renders a stale client-side list — or another
    employee's pay — cannot pass.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None  # narrowed for the type checker; the fixture asserts
    teacher = ctx.teacher
    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    slip = teacher_payslip

    with demo.step(
        f"Sign in as {teacher.full_name}, who teaches at {ctx.school_name}",
        dwell_ms=2500,
    ):
        login_as(page, base_url, teacher)

    with demo.step(
        "Their staff home page opens with their most recent pay statements",
        dwell_ms=2000,
    ):
        # StaffView only mounts RecentPayslips when the school is licensed for
        # staff_payroll, so this card is the licence made visible.
        expect(page.get_by_text(as_pattern(VIEW_RECENT_PAYSLIPS))).to_be_visible(
            timeout=30_000
        )
        expect(_payslip_row(page)).to_be_visible(timeout=20_000)

    with demo.step(
        "Follow 'View All Payslips' through to the full pay history", dwell_ms=1800
    ):
        # The only navigation the app offers to this screen — there is no sidebar
        # entry for My Payslips anywhere in nav-config.tsx.
        link = page.get_by_role("link", name=as_pattern(VIEW_ALL_PAYSLIPS_LINK)).first
        expect(link).to_be_visible(timeout=20_000)
        link.click()
        page.wait_for_url(re.compile(r"/module/my_payslips"), timeout=25_000)
        expect(
            page.get_by_role("heading", name=VIEW_MY_PAYSLIPS_HEADING)
        ).to_be_visible(timeout=25_000)
        # Neither refusal surface this page can render: the role check the page
        # makes for itself, and the failed fetch behind it.
        expect(page.get_by_text(VIEW_UNAUTHORIZED)).to_have_count(0)
        expect(page.get_by_text(VIEW_LOAD_FAILURE)).to_have_count(0)

    with demo.step(
        "Every approved month, with what was earned and what was taken off",
        dwell_ms=2500,
    ):
        expect(page.get_by_role("heading", name=VIEW_PAY_HISTORY)).to_be_visible(
            timeout=20_000
        )
        for tile in (
            VIEW_LATEST_NET_PAY_TILE,
            VIEW_TOTAL_EARNED_TILE,
            VIEW_TOTAL_DEDUCTIONS_TILE,
        ):
            expect(page.get_by_text(tile)).to_be_visible()

        row = _payslip_row(page)
        expect(row).to_be_visible(timeout=20_000)
        expect(row).to_contain_text(_amount_shown(slip.gross_pay))
        expect(row).to_contain_text(_amount_shown(slip.total_deductions))
        expect(row).to_contain_text(_amount_shown(slip.net_pay))
        # Only approved runs reach a teacher, so the badge can only read this.
        expect(row.get_by_text(VIEW_APPROVED_BADGE)).to_be_visible()

    with demo.step(
        f"Open {VIEW_PERIOD} to see how that month's pay was made up", dwell_ms=2000
    ):
        _payslip_row(page).get_by_role(
            "link", name=as_pattern(VIEW_ROW_VIEW_LINK)
        ).first.click()
        page.wait_for_url(
            re.compile(rf"/module/my_payslips/{re.escape(VIEW_PERIOD)}"), timeout=25_000
        )
        expect(page.get_by_role("heading", name=VIEW_PERIOD_SHOWN)).to_be_visible(
            timeout=25_000
        )
        expect(page.get_by_text(VIEW_DETAILS_ERROR)).to_have_count(0)

    with demo.step("Who paid whom, and for what job", dwell_ms=2200):
        details = slip.details
        expect(page.get_by_text(VIEW_EMPLOYER_PANEL).first).to_be_visible(timeout=20_000)
        expect(
            page.get_by_text(str(details["organization_details"]["name"])).first
        ).to_be_visible()
        expect(page.get_by_text(VIEW_EMPLOYEE_PANEL).first).to_be_visible()
        expect(page.get_by_text(str(details["employee_name"])).first).to_be_visible()
        if details.get("employee_job_title"):
            expect(
                page.get_by_text(str(details["employee_job_title"])).first
            ).to_be_visible()

    with demo.step(
        "Earnings on one side, deductions on the other — down to the net pay",
        dwell_ms=3000,
    ):
        details = slip.details
        expect(page.get_by_text(VIEW_EARNINGS_PANEL).first).to_be_visible()
        expect(page.get_by_text(VIEW_BASIC_SALARY_ROW).first).to_be_visible()
        expect(
            page.get_by_text(_amount_shown(float(details["base_salary"]))).first
        ).to_be_visible()
        for earning in details.get("earnings") or []:
            expect(page.get_by_text(str(earning["description"])).first).to_be_visible()

        expect(page.get_by_text(VIEW_DEDUCTIONS_PANEL).first).to_be_visible()
        for deduction in details.get("deductions") or []:
            expect(page.get_by_text(str(deduction["description"])).first).to_be_visible()

        # The banner figure is the one that has to agree with the list screen and
        # with the feed behind both.
        expect(page.get_by_text(VIEW_NET_PAY_LABEL).first).to_be_visible()
        expect(page.get_by_text(_amount_shown(slip.net_pay)).first).to_be_visible()
        expect(
            page.get_by_role("button", name=as_pattern(VIEW_DOWNLOAD_PDF)).first
        ).to_be_visible()

    with demo.step(
        "Teaching staff see their own pay — never the school's payroll register",
        dwell_ms=2500,
    ):
        # The gate the app really implements for this role: no staff_payroll
        # permission means SideNavigation renders neither the section nor its
        # items. Asserted here rather than by visiting /module/staff_payroll,
        # which would be the denied unit's job — and which for a Teacher is a
        # permission refusal, not a licensing one.
        expect(
            page.get_by_role("link", name=as_pattern(VIEW_STAFF_PAYROLL_LINK))
        ).to_have_count(0)
        expect(page.get_by_text(VIEW_PAYROLL_SECTION)).to_have_count(0)

    with demo.step(
        "Behind the screens, this feed answers the teacher for their own pay only",
        dwell_ms=2000,
    ):
        _expect_self_service_feed_agrees(api, ctx, slip)


# ────────────────────── helpers for the teacher view path ────────────────────


def _payslip_row(page: Page) -> Locator:
    """The table row for ``VIEW_PERIOD`` on whichever payslip table is on screen.

    Both the home card and the full history render one ``<tr>`` per period, and
    both label it with the same "May 2026" text, so one locator serves the two
    screens the walkthrough passes through.
    """
    return page.get_by_role("row").filter(has_text=VIEW_PERIOD_SHOWN).first


def _amount_shown(value: float) -> re.Pattern:
    """What ``formatCurrency`` puts on screen for ``value``, as a pattern.

    Both payslip screens render ``Intl.NumberFormat("en-GH", {style: "currency",
    currency: "GHS"})``, i.e. a "GH₵" prefix and grouped two-decimal digits. Only
    the digits are matched, and the group separator loosely, so neither the
    currency symbol nor a Chromium locale-data change reads as a lost figure.
    """
    shown = f"{value:,.2f}"
    return re.compile(
        r"[,\s\u00a0\u202f]?".join(re.escape(part) for part in shown.split(","))
    )


def _teacher_user_id(
    api: BackendAPI, admin_token: str, branch_id: int, email: str
) -> int:
    """The teacher's ``users.id``, looked up rather than inferred.

    ``SchoolContext.teacher.user_id`` cannot be trusted here: it is read off the
    ``POST /teacher/`` response, whose ``id`` is the *TeacherProfile* row, not the
    user — and ``EmployeeBenefit.user_id`` and ``PayrollDetail.user_id`` are both
    the user. ``/employee-benefit/employees/`` is the same list the Employee
    Benefits screen fills its picker from.
    """
    response = api.get(
        f"/employee-benefit/employees/?branch_id={branch_id}", token=admin_token
    )
    assert response.status_code == 200, (
        f"could not list the branch's employees: {response.status_code} "
        f"{response.text[:300]}"
    )
    for employee in response.json():
        if str(employee.get("email", "")).lower() == email.lower():
            return int(employee["id"])
    raise AssertionError(
        f"{email} is not in the employee list for branch {branch_id}, so the "
        f"teacher provisioning created is not attached to this branch — a payroll "
        f"run would skip them entirely"
    )


def _ensure_tax_config(api: BackendAPI, admin_token: str, branch_id: int) -> None:
    """Make sure the branch deducts something, so the payslip has a breakdown.

    Left alone when the branch already has any configuration: the accountant unit
    shares this school, and adding a second identical step would change the
    figures under a run it may already have generated.
    """
    existing = api.get(f"/payroll/tax-config?branch_id={branch_id}", token=admin_token)
    if existing.status_code == 200 and existing.json():
        return

    created = api.post(
        f"/payroll/tax-config?branch_id={branch_id}",
        token=admin_token,
        json={
            "name": VIEW_TAX_CONFIG_NAME,
            "mode": "flat_percent",
            "rate": VIEW_TAX_CONFIG_RATE,
            "tax_bearer": "Employee",
            "target": "base_salary",
            "expense_account": VIEW_TAX_EXPENSE_ACCOUNT,
            "liability_account": VIEW_TAX_LIABILITY_ACCOUNT,
        },
    )
    assert created.status_code < 400, (
        f"could not configure a payroll deduction for branch {branch_id}: "
        f"{created.status_code} {created.text[:300]}"
    )


def _ensure_employee_benefit(
    api: BackendAPI, admin_token: str, branch_id: int, user_id: int
) -> None:
    """Put the teacher on a salary band, which is what makes them payable.

    ``calculate_payroll`` only visits users that join ``EmployeeBenefit``, and
    ``PayrollProcessor.load_employee_benefits`` raises for anyone without one, so
    without this the run completes with the teacher in its error list and no
    payslip is ever written.
    """
    existing = api.get(f"/employee-benefit/{user_id}?branch_id={branch_id}",
                       token=admin_token)
    if existing.status_code == 200 and (existing.json() or {}).get("id"):
        return

    base_salary = _seed_row(
        api, admin_token,
        f"/employee-benefit/benefit-item?branch_id={branch_id}",
        {
            "name": VIEW_BASE_SALARY_ITEM,
            "code": "base_salary",
            "amount": VIEW_BASE_SALARY_AMOUNT,
            "description": "Monthly basic pay for teaching staff.",
            "is_taxable": True,
        },
        what="base salary benefit item",
    )
    allowance = _seed_row(
        api, admin_token,
        f"/employee-benefit/benefit-item?branch_id={branch_id}",
        {
            "name": VIEW_ALLOWANCE_ITEM,
            "code": "allowance",
            "amount": VIEW_ALLOWANCE_AMOUNT,
            "description": "Monthly commuting allowance, not taxed.",
            "is_taxable": False,
        },
        what="allowance benefit item",
    )
    band = _seed_row(
        api, admin_token,
        f"/employee-benefit/salary-band?branch_id={branch_id}",
        {
            "band_name": VIEW_SALARY_BAND,
            "benefits": [int(base_salary["id"]), int(allowance["id"])],
        },
        what="salary band",
    )
    _seed_row(
        api, admin_token,
        f"/employee-benefit/?branch_id={branch_id}",
        {
            "user_id": user_id,
            "benefit_band_id": int(band["id"]),
            "tax_relief": 0.0,
            "extra_benefits": [],
        },
        what="employee benefit",
    )


def _ensure_approved_payroll_run(
    api: BackendAPI, admin_token: str, branch_id: int
) -> None:
    """Calculate the month's payroll and approve it, unless it already exists.

    Approval is not optional decoration: ``list_my_payslips`` filters on
    ``PayrollRun.is_approved``, so an unapproved run is invisible to the very
    person it pays.
    """
    run = _payroll_run_for_period(api, admin_token, branch_id)
    if run is None:
        calculated = api.post(
            f"/payroll/{branch_id}/{VIEW_PERIOD}", token=admin_token
        )
        assert calculated.status_code < 400, (
            f"could not calculate payroll for {VIEW_PERIOD}: "
            f"{calculated.status_code} {calculated.text[:300]}"
        )
        run = _payroll_run_for_period(api, admin_token, branch_id)
        assert run is not None, (
            f"payroll was calculated for {VIEW_PERIOD} but no run for that period "
            f"came back from /payroll/runs"
        )

    if run.get("is_approved"):
        return

    approved = api.post(
        f"/payroll/runs/{int(run['id'])}/approve"
        f"?branch_id={branch_id}&remarks={TEST_PREFIX}+payslip+demo+{VIEW_TAG}",
        token=admin_token,
    )
    assert approved.status_code < 400, (
        f"could not approve the {VIEW_PERIOD} payroll run: {approved.status_code} "
        f"{approved.text[:300]}"
    )


def _payroll_run_for_period(
    api: BackendAPI, admin_token: str, branch_id: int
) -> dict[str, Any] | None:
    """The branch's run for ``VIEW_PERIOD``, or None. 404 means "no runs at all"."""
    response = api.get(f"/payroll/runs?branch_id={branch_id}", token=admin_token)
    if response.status_code == 404:
        return None
    assert response.status_code == 200, (
        f"could not list the branch's payroll runs: {response.status_code} "
        f"{response.text[:300]}"
    )
    for run in response.json():
        if str(run.get("period")) == VIEW_PERIOD:
            return run
    return None


def _my_payslip_for_period(
    api: BackendAPI, teacher_token: str
) -> dict[str, Any] | None:
    """The teacher's own row for ``VIEW_PERIOD`` from the self-service feed."""
    response = api.get("/payroll/me/payslips", token=teacher_token)
    assert response.status_code == 200, (
        f"the teacher's own payslip feed must answer them — got "
        f"{response.status_code}: {response.text[:300]}"
    )
    for row in response.json():
        if str(row.get("period")) == VIEW_PERIOD:
            return row
    return None


def _seed_row(
    api: BackendAPI, token: str, path: str, payload: dict[str, Any], *, what: str
) -> dict[str, Any]:
    """POST one setup row, failing loudly rather than leaving an empty screen."""
    response = api.post(path, token=token, json=payload)
    assert response.status_code < 400, (
        f"could not seed the {what}: {response.status_code} {response.text[:300]}"
    )
    return response.json()


def _expect_self_service_feed_agrees(
    api: BackendAPI, ctx: SchoolContext, slip: TeacherPayslip
) -> None:
    """The routes behind the screens answer this teacher, scoped to this teacher.

    Without this the UI half proves only that *a* table rendered. What matters
    about ``/payroll/me/payslips`` is that it reads ``user.id`` and
    ``user.school_branch_id`` off the caller's own token rather than taking either
    as a parameter — which is the whole reason a teacher may read here at all
    without holding a ``staff_payroll`` permission.
    """
    assert ctx.teacher is not None
    token = api.login(ctx.teacher.email, ctx.teacher.password)["access_token"]

    feed = api.get("/payroll/me/payslips", token=token)
    assert feed.status_code == 200, (
        f"the payslip feed must answer its owner — got {feed.status_code}: "
        f"{feed.text[:300]}"
    )
    rows = feed.json()
    assert any(str(row.get("period")) == slip.period for row in rows), (
        f"{slip.period} is missing from the teacher's own feed, so the screens "
        f"above were rendering something other than this payslip"
    )
    assert all(row.get("is_approved") is True for row in rows), (
        f"the feed returned an unapproved payslip: {rows!r}. list_my_payslips "
        f"filters on PayrollRun.is_approved precisely so that a run still awaiting "
        f"sign-off is never shown to the person it pays."
    )

    detail = api.get(f"/payroll/me/payslips/{slip.period}", token=token)
    assert detail.status_code == 200, (
        f"the breakdown for {slip.period} must answer its owner — got "
        f"{detail.status_code}: {detail.text[:300]}"
    )
    body = detail.json()
    assert body.get("employee_name") == slip.details.get("employee_name"), (
        f"the breakdown named a different employee on a second read: "
        f"{body.get('employee_name')!r} vs {slip.details.get('employee_name')!r}"
    )
    assert float(body["net_pay"]) == pytest.approx(slip.net_pay), (
        f"the breakdown's net pay ({body['net_pay']}) disagrees with the pay "
        f"history's ({slip.net_pay}) for the same month"
    )
