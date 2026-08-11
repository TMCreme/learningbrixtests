"""/module/employee_benefit — the payroll register of what each employee is paid
in benefits.

This file is written one ledger unit at a time; each section below owns its own
constants (prefixed, never shared) so appending a unit can never silently rebind
a name an earlier section relies on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import TEST_PREFIX, run_tag
from tests.flows.school_provisioning import Credentials, SchoolContext
from tests.pages.base import as_pattern, goto, goto_module
from tests.pages.login import login_as
from tests.pages.payroll.employee_benefit import (
    CREATE_BUTTON,
    NAV_EMPLOYEE_BENEFITS,
    PAGE_HEADING,
    SEARCH_PLACEHOLDER,
    TABLE_HEADING,
    EmployeeBenefitsPage,
)
from tests.pages.school_admin.branches import BranchesPage

# ═══════════════ payroll.employee_benefit.manage.school_admin ═══════════════
#
# What "manage" means on this screen
#     A benefits package is an employee plus a *benefit band* (a named bundle of
#     benefit items — housing, transport, …) plus whatever extra items they get
#     on top, plus their tax relief. The walkthrough below puts a newly hired
#     teacher on the junior band, then re-opens the package and moves them to the
#     senior band with an extra item, which is the create and the edit half of
#     the unit against the same record. Every figure is read back off the
#     register, which renders the list the page refetched after each write — so
#     the assertions prove the package persisted, not that a form was filled in.
#
# Why the band and the items are seeded over the API
#     Benefit items live at /module/benefit_item and bands at /module/benefit_band
#     — two other screens, and two other ledger units. Driving them here would be
#     those units' walkthroughs wearing this one's name, so ``benefits_setup``
#     writes them straight to ``/employee-benefit/benefit-item`` and
#     ``/employee-benefit/salary-band``: the same setup-only use of ``api`` that
#     ``school_provisioning._seed_fee_group`` makes.
#
# Why an *existing* package is seeded too, and why that is not papering over a bug
#     The register cannot render an empty branch. ``GET /employee-benefit/``
#     raises 404 when the branch has no packages, its own ``except Exception``
#     re-raises that as a 400, and ``page.tsx`` turns any failure into a full-page
#     ``PageError`` — so on a branch with nothing on it the screen shows "Failed
#     to load employee benefits" and the EmptyState's own "Create Benefits" call
#     to action never renders. The same is true of the form: with no benefit items
#     and no band, ``GET /benefit-item/`` and ``GET /salary-band/`` answer the
#     same way and the form is replaced by "Failed to load form data".
#
#     That "empty collection is an error" convention runs through this backend
#     rather than being local to this module, and changing it would be a product
#     decision about what these endpoints answer — not a defect fix this unit may
#     make unattended. So the fixture puts the branch in the state the module is
#     designed to be used from (items, a band, and one colleague already on the
#     register) and the walkthrough manages a package inside it. What the fixture
#     seeds is deliberately *another* employee's package: everything this unit
#     asserts is about the one it creates through the UI.
#
# Selecting a branch is a prerequisite, not a nicety
#     A SchoolAdmin belongs to no branch. The sidebar's whole "Payroll Module"
#     section is ``branchOnly``, and every request behind both screens appends
#     ``branch_id`` from ``useBranchStore`` — which only the branch row's "View"
#     button fills. Without it there is no Employee Benefits link to click, the
#     register requests ``branch_id=undefined``, and the form refuses to submit
#     with "Branch ID is required for school admins".

MANAGE_SCENARIO = "finance_only"
MANAGE_MODULE = "employee_benefit"

# Everything this unit puts in the branch carries the "TEST" prefix the orphan
# sweeper matches on, plus the run tag so parallel agents never collide.
MANAGE_TAG = run_tag()

# ── seeded benefit items (BenefitCodeEnum: base_salary/bonus/allowance/
#    overtime/ssnit_base/other) ────────────────────────────────────────────────
MANAGE_HOUSING_ITEM = f"TEST Housing Allowance {MANAGE_TAG}"
MANAGE_TRANSPORT_ITEM = f"TEST Transport Allowance {MANAGE_TAG}"
MANAGE_MEDICAL_ITEM = f"TEST Medical Cover {MANAGE_TAG}"
MANAGE_TRAINING_ITEM = f"TEST Professional Development Grant {MANAGE_TAG}"

MANAGE_ITEMS: tuple[dict[str, Any], ...] = (
    {"name": MANAGE_HOUSING_ITEM, "code": "allowance", "amount": 1200,
     "description": "Monthly housing allowance", "is_taxable": True},
    {"name": MANAGE_TRANSPORT_ITEM, "code": "allowance", "amount": 450,
     "description": "Monthly transport allowance", "is_taxable": True},
    {"name": MANAGE_MEDICAL_ITEM, "code": "other", "amount": 300,
     "description": "Medical cover contribution", "is_taxable": False},
    {"name": MANAGE_TRAINING_ITEM, "code": "bonus", "amount": 600,
     "description": "Professional development grant", "is_taxable": True},
)

# ── seeded bands. The register prints the band's name and counts its items, so
#    the two bands differ in both. ─────────────────────────────────────────────
MANAGE_JUNIOR_BAND = f"TEST Junior Staff Band {MANAGE_TAG}"
MANAGE_JUNIOR_ITEMS = (MANAGE_HOUSING_ITEM, MANAGE_TRANSPORT_ITEM)
MANAGE_SENIOR_BAND = f"TEST Senior Staff Band {MANAGE_TAG}"
MANAGE_SENIOR_ITEMS = (MANAGE_HOUSING_ITEM, MANAGE_TRANSPORT_ITEM, MANAGE_MEDICAL_ITEM)

# The colleague already on the register, so the screen has something to render
# before this unit writes anything. Never asserted on.
MANAGE_SEEDED_TAX_RELIEF = 200

# ── what the walkthrough writes ─────────────────────────────────────────────
MANAGE_TAX_RELIEF = "350"
MANAGE_REVISED_TAX_RELIEF = "850"

# formatCurrency() is Intl en-US with two decimals, so 350 renders "350.00" and
# 850 "850.00". The group separator is matched loosely so a locale-data change in
# Chromium cannot read as a lost figure.
MANAGE_TAX_RELIEF_SHOWN = re.compile(r"350\.00")
MANAGE_REVISED_TAX_RELIEF_SHOWN = re.compile(r"850\.00")

# The "Total Benefits" badge is band items + extra items, and the Benefit Band
# cell grows a "+n extra" badge once the package carries extra items. Each is its
# own element, and each is matched *as* that element (``row.get_by_text``) rather
# than inside the row's text.
#
# That is not a stylistic preference. ``to_contain_text`` matches against the
# row's concatenated ``textContent``, where the band-name cell runs straight into
# the badge with no separator — "TEST Junior Staff Band 9d5b51" + "2 items"
# reads as "…9d5b512 items". The run tag ends in a digit roughly half the time,
# and when it does there is no word boundary in front of the count, so a
# ``\b2 items\b`` written against the row silently stops matching on those runs
# while the screen is perfectly correct. Anchoring each badge to its own element
# both removes that coupling and says which badge is being read.
MANAGE_ITEMS_BADGE = re.compile(r"^\s*2 items\s*$", re.I)
MANAGE_REVISED_ITEMS_BADGE = re.compile(r"^\s*4 items\s*$", re.I)
MANAGE_EXTRA_BADGE = re.compile(r"^\s*\+1 extra\s*$", re.I)


class BenefitsSeedError(RuntimeError):
    """A prerequisite for this unit could not be seeded."""


@dataclass
class BenefitsSetup:
    """The branch state the walkthrough manages a package inside."""

    branch_id: int
    branch_name: str
    employee: Credentials
    item_ids: dict[str, int] = field(default_factory=dict)
    band_ids: dict[str, int] = field(default_factory=dict)
    colleague_email: str = ""


@pytest.fixture
def benefits_setup(
    provisioned_school: SchoolContext, api: BackendAPI
) -> BenefitsSetup:
    """Give the branch its benefit items, two bands and one existing package.

    Requested *before* ``demo`` in the test signature so the seeding requests
    happen before the camera rolls, rather than as dead frames at the head of the
    video.
    """
    ctx = provisioned_school
    assert MANAGE_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {MANAGE_MODULE!r} for this "
        f"unit — it is the positive path"
    )
    assert ctx.teacher is not None and ctx.accountant is not None, (
        "provisioning created no staff for this school, so there is nobody to "
        "give a benefits package to — phase C creates a teacher and an "
        "accountant, which needs the `staff` module on the pack"
    )
    assert ctx.branches, "provisioning created no branch for this school"

    branch = ctx.branches[0]
    branch_id = int(branch.get("id") or -1)
    if branch_id <= 0:
        raise BenefitsSeedError(
            "provisioning captured no branch id, and every benefit read and "
            "write here is branch-scoped. Phase B creates the branch — check "
            "that it did."
        )

    token = _manage_token(api, ctx.school_admin)

    item_ids = {
        item["name"]: _seed_item(api, token, branch_id=branch_id, **item)
        for item in MANAGE_ITEMS
    }
    band_ids = {
        MANAGE_JUNIOR_BAND: _seed_band(
            api, token, branch_id=branch_id, name=MANAGE_JUNIOR_BAND,
            item_ids=[item_ids[name] for name in MANAGE_JUNIOR_ITEMS],
        ),
        MANAGE_SENIOR_BAND: _seed_band(
            api, token, branch_id=branch_id, name=MANAGE_SENIOR_BAND,
            item_ids=[item_ids[name] for name in MANAGE_SENIOR_ITEMS],
        ),
    }

    # The colleague who is already on the register. Without at least one package
    # the register renders PageError instead of a table — see the header note.
    _seed_package(
        api, token,
        branch_id=branch_id,
        user_id=_user_id(api, token, ctx.accountant, branch_id=branch_id),
        band_id=band_ids[MANAGE_JUNIOR_BAND],
        tax_relief=MANAGE_SEEDED_TAX_RELIEF,
    )

    # The employee this unit's walkthrough is about must still have no package:
    # the create half of the unit is what gives them one.
    teacher_id = _user_id(api, token, ctx.teacher, branch_id=branch_id)
    existing = api.get(
        f"/employee-benefit/{teacher_id}?branch_id={branch_id}", token=token
    )
    if existing.status_code < 400:
        raise BenefitsSeedError(
            f"{ctx.teacher.full_name} already has a benefits package at branch "
            f"{branch_id}, so this unit cannot create one for them. The school is "
            f"provisioned fresh per session — a leftover here means an earlier "
            f"attempt of this test got half way through."
        )

    return BenefitsSetup(
        branch_id=branch_id,
        branch_name=str(branch["name"]),
        employee=ctx.teacher,
        item_ids=item_ids,
        band_ids=band_ids,
        colleague_email=ctx.accountant.email,
    )


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="payroll.employee_benefit.manage.school_admin",
    title="Employee Benefits",
    subtitle="SchoolAdmin creates and manages employee benefits",
)
def test_school_admin_creates_and_manages_employee_benefits(
    benefits_setup: BenefitsSetup,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """An administrator puts a teacher on a benefit band, then promotes them."""
    ctx = provisioned_school
    setup = benefits_setup
    employee = setup.employee

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    benefits = EmployeeBenefitsPage(page, base_url)

    with demo.step(f"Sign in as the administrator of {ctx.school_name}"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Open {setup.branch_name}, the campus whose payroll is being "
                   f"set up"):
        BranchesPage(page, base_url).select_branch(setup.branch_name)

    with demo.step("Employee Benefits is waiting in the Payroll menu"):
        # Reached by route first, because "View" on the branch row routes to
        # /module/community — a module this school's pack does not license, so
        # the branch selection above lands on /auth/no-access, which renders no
        # sidebar at all. Coming back via the branches page is not an option
        # either: its mount effect calls clearBranch(). So the Payroll entry is
        # asserted from inside the module chrome, which is where an
        # administrator reads it anyway.
        benefits.open()
        benefits.expect_nav_entry()
        benefits.open_from_sidebar()
        benefits.expect_no_load_failure()
        benefits.expect_column_headers()
        benefits.expect_register()

    with demo.step(f"{employee.full_name} has just joined and has no package yet"):
        benefits.expect_no_row(employee.email)
        form = benefits.open_create_form()

    with demo.step(f"Put them on the junior staff band, with tax relief of GHC "
                   f"{MANAGE_TAX_RELIEF}"):
        form.select_employee(employee.full_name)
        form.select_band(MANAGE_JUNIOR_BAND)
        form.set_tax_relief(MANAGE_TAX_RELIEF)
        form.submit_create()

    with demo.step("The package lands on the register, band and relief and all",
                   dwell_ms=2000):
        benefits.expect_loaded()
        benefits.expect_register()
        benefits.search(employee.full_name)
        row = benefits.expect_row(employee.email)
        expect(row).to_contain_text(employee.full_name)
        expect(row).to_contain_text(MANAGE_JUNIOR_BAND)
        expect(row.get_by_text(as_pattern(MANAGE_ITEMS_BADGE)).first).to_be_visible()
        expect(row).to_contain_text(MANAGE_TAX_RELIEF_SHOWN)
        benefits.expect_no_load_failure()

    with demo.step("A promotion — reopen the package from the register"):
        form = benefits.open_edit_form(employee.email)
        # The form knows whose package it reopened, and says so in a field no
        # edit can change.
        form.expect_employee(employee.full_name)

    with demo.step("Move them up to the senior band and add a training grant",
                   dwell_ms=1800):
        form.select_band(MANAGE_SENIOR_BAND)
        form.select_extra_benefits(MANAGE_TRAINING_ITEM)
        form.set_tax_relief(MANAGE_REVISED_TAX_RELIEF)
        form.submit_update()

    with demo.step("The register now reads the new band, the extra item and the "
                   "revised relief", dwell_ms=3000):
        benefits.expect_loaded()
        benefits.expect_register()
        benefits.search(employee.full_name)
        revised = benefits.expect_row(employee.email)
        expect(revised).to_contain_text(MANAGE_SENIOR_BAND)
        expect(revised.get_by_text(as_pattern(MANAGE_EXTRA_BADGE)).first).to_be_visible()
        expect(
            revised.get_by_text(as_pattern(MANAGE_REVISED_ITEMS_BADGE)).first
        ).to_be_visible()
        expect(revised).to_contain_text(MANAGE_REVISED_TAX_RELIEF_SHOWN)
        # The edit replaced the package rather than adding a second one.
        expect(revised).not_to_contain_text(MANAGE_JUNIOR_BAND)
        expect(
            page.get_by_role("row").filter(has_text=re.compile(re.escape(employee.email), re.I))
        ).to_have_count(1)
        benefits.expect_no_load_failure()


# ─────────── setup-only seeding for this unit (never asserted) ──────────────


def _manage_token(api: BackendAPI, creds: Credentials) -> str:
    try:
        return str(api.login(creds.email, creds.password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise BenefitsSeedError(f"could not log in as {creds.email}: {exc}") from exc


def _rows(response: Any) -> list[dict]:
    """The rows a list endpoint answered with.

    Every collection route in this module raises rather than returning ``[]`` for
    an empty branch (404 inside a ``try``, re-raised as 400), so any error status
    is read here as "nothing seeded yet".
    """
    if response.status_code >= 400:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    return [row for row in payload if isinstance(row, dict)]


def _existing_id(
    api: BackendAPI, token: str, path: str, *, name: str, key: str
) -> int | None:
    """The id of a row already named ``name``, if the list endpoint offers one."""
    wanted = re.compile(rf"^\s*{re.escape(name)}\s*$", re.I)
    for row in _rows(api.get(path, token=token)):
        if wanted.match(str(row.get(key, ""))):
            return int(row["id"])
    return None


def _seed_item(
    api: BackendAPI,
    token: str,
    *,
    branch_id: int,
    name: str,
    code: str,
    amount: float,
    description: str,
    is_taxable: bool,
) -> int:
    """One benefit item — the smallest thing a band is built out of.

    Reused if it is already there: the whole batch shares one provisioned school,
    and two items of the same name would make the form's pickers ambiguous.
    """
    path = f"/employee-benefit/benefit-item/?branch_id={branch_id}&skip=0&limit=100"
    existing = _existing_id(api, token, path, name=name, key="name")
    if existing is not None:
        return existing

    response = api.post(
        f"/employee-benefit/benefit-item?branch_id={branch_id}",
        token=token,
        json={
            "name": name,
            "code": code,
            "amount": amount,
            "description": description,
            "is_taxable": is_taxable,
        },
    )
    if response.status_code >= 400:
        raise BenefitsSeedError(
            f"could not seed the benefit item {name!r} in branch {branch_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return int(response.json()["id"])


def _seed_band(
    api: BackendAPI, token: str, *, branch_id: int, name: str, item_ids: list[int]
) -> int:
    """A named bundle of benefit items — what the form's Benefit Band picker offers."""
    path = f"/employee-benefit/salary-band/?branch_id={branch_id}&skip=0&limit=100"
    existing = _existing_id(api, token, path, name=name, key="band_name")
    if existing is not None:
        return existing

    response = api.post(
        f"/employee-benefit/salary-band?branch_id={branch_id}",
        token=token,
        json={"band_name": name, "benefits": item_ids},
    )
    if response.status_code >= 400:
        raise BenefitsSeedError(
            f"could not seed the benefit band {name!r} in branch {branch_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return int(response.json()["id"])


def _user_id(
    api: BackendAPI, token: str, creds: Credentials, *, branch_id: int
) -> int:
    """The employee's user id, read back rather than assumed.

    ``capture_credentials`` records one for most creates, but the teaching-staff
    response carries the *teacher* row's id rather than the user's — so the id is
    resolved from the very list the form's Employee picker is built from
    (``GET /employee-benefit/employees/``), which is also proof the employee is
    eligible for a package at all.
    """
    response = api.get(
        f"/employee-benefit/employees/?branch_id={branch_id}", token=token
    )
    wanted = str(creds.email).strip().lower()
    for row in _rows(response):
        if str(row.get("email", "")).strip().lower() == wanted:
            return int(row["id"])
    raise BenefitsSeedError(
        f"{creds.email} is not among the employees branch {branch_id} offers "
        f"benefits to ({response.status_code}: {response.text[:300]}). Every "
        f"user of the branch except guardians and students should be."
    )


def _seed_package(
    api: BackendAPI,
    token: str,
    *,
    branch_id: int,
    user_id: int,
    band_id: int,
    tax_relief: float,
) -> int:
    """One employee's benefits package, so the register has a row to render."""
    existing = api.get(f"/employee-benefit/{user_id}?branch_id={branch_id}", token=token)
    if existing.status_code < 400:
        return int(existing.json()["id"])

    response = api.post(
        f"/employee-benefit/?branch_id={branch_id}",
        token=token,
        json={
            "user_id": user_id,
            "benefit_band_id": band_id,
            "extra_benefits": [],
            "tax_relief": tax_relief,
            "overtime_tax_eligible": False,
            "tax_exemptions": [],
        },
    )
    if response.status_code >= 400:
        raise BenefitsSeedError(
            f"could not seed a benefits package for user {user_id} in branch "
            f"{branch_id}: {response.status_code} {response.text[:300]}"
        )
    return int(response.json()["id"])


# ═══════════ payroll.employee_benefit.view.accountant — BLOCKED ══════════════
#
# The ledger unit ``payroll.employee_benefit.view.accountant`` (scenario
# ``finance_only``, role ``accountant``, intent ``view``) is recorded **BLOCKED**
# in ``state/blockers.md``. This test is the guard that stands in its place.
#
# The product question it is blocked on
#     Should the **Accountant** role be able to see employee benefits at all —
#     and if so, with what strength of access, given this module has no read-only
#     mode?
#
# Why the happy path cannot be written
#     The Accountant role holds no ``employee_benefit`` permission of any kind
#     (``newschoolapp/db/repository/permissions.py``; measured live below from
#     ``GET /roles/{id}``, not quoted from source). Its seeded set is the
#     back-office one: ``manage fees``, ``manage incomes_and_expenses``, reads on
#     home/dashboard/students/staff, and the messaging and change-request
#     baseline. ``employee_benefit`` and ``staff_payroll`` are given to
#     ``SchoolAdmin`` and to ``Admin`` (the branch admin) only.
#
#     So the accountant is refused in three places at once, none of them the
#     feature pack — this school *is* licensed for the module:
#
#       * **No way in.** The sidebar's "Payroll Module" section is gated on
#         ``permissionsGate: ["staff_payroll", "payslips"]`` and each of its
#         entries additionally on ``permission: "employee_benefit"``
#         (``SideNavigation/nav-config.tsx``), so neither the section nor the
#         Employee Benefits link is rendered for this role.
#       * **No page.** ``usePermissionGuard("employee_benefit")`` finds no
#         matching permission, so ``page.tsx`` returns ``null`` and the hook
#         pushes the browser to ``/unauthorized``.
#       * **No data.** Every route on ``api/routes/employee_benefit.py`` — the
#         reads included — is gated on ``has_permission("manage",
#         "employee_benefit")``, which answers 403 "You do not have permission to
#         perform this action" *before* it ever consults the feature pack
#         (``utils/permissions.py``).
#
#     Making this unit's happy path pass would mean granting the Accountant role
#     an ``employee_benefit`` permission, and there is no read-only one to grant:
#     the module defines only ``manage``, which is create/update over every
#     employee's package, band and benefit item. It would also need
#     ``staff_payroll`` on top, purely so the sidebar section that carries the
#     link renders at all. That is granting a role permissions it does not have —
#     a product decision about who may see and change payroll data, not a defect
#     fixable in place — so nothing was changed in either app.
#
#     Note that the seed was already corrected once, for a real defect: the
#     Accountant role shipped with *no* permissions whatsoever and could not open
#     even the finance module it is named after (see
#     ``tests/modules/account/test_incomes_and_expenses.py`` and
#     ``state/backend_patches.md``). That fix stopped deliberately at the finance
#     modules. Extending it to payroll is the question being escalated, not a
#     continuation of it.
#
# What this test asserts instead — the exact shape of the refusal, from both ends
#     1. The school **is** licensed for ``employee_benefit``, and a role at that
#        same school **does** hold ``manage employee_benefit``. So the module is
#        alive here; only this role is shut out. Without this the 403s below
#        would be indistinguishable from an unlicensed school.
#     2. The Accountant role's own permission set carries nothing for
#        ``employee_benefit`` or ``staff_payroll``, read live from the API.
#     3. The backend refuses this accountant on every route the two screens use,
#        with 403 **"You do not have permission to perform this action"** — the
#        *role* denial. A "Feature not available in your plan" here would mean
#        something else entirely (the pack), and would make this test a lie.
#     4. The UI never puts the register in front of them: no Payroll section and
#        no Employee Benefits link in the sidebar, and asking for
#        ``/module/employee_benefit`` by hand lands on ``/unauthorized`` with
#        none of the register's chrome on screen.
#     5. The same call the register makes succeeds for the SchoolAdmin of the
#        very same branch — the control that proves step 3 is about the caller.
#
#     Deep-linking at step 4 is the assertion, not a shortcut past the UI: for
#     this role there is no navigation path to deep-link past.
#
# Reading this test when it fails
#     * **Step 2 finding an ``employee_benefit`` permission on the Accountant
#       role** is the good failure: the product question was answered "yes", and
#       this unit should be rewritten as the ordinary read-only walkthrough the
#       ledger asked for — starting from the note in ``state/blockers.md``.
#     * **The sidebar offering Payroll, or the register rendering at step 4**,
#       with the role unchanged, means a frontend gate was dropped while the
#       backend still answers 403: a real defect, and the screen would be showing
#       an empty error page to a user who is not allowed there.
#     * **A 403 at step 5** means the SchoolAdmin lost the module too; that is
#       the manage unit's problem above, not this one's.

VIEW_SCENARIO = "finance_only"
VIEW_MODULE = "employee_benefit"
VIEW_PAYROLL_MODULE = "staff_payroll"
VIEW_ROUTE = "employee_benefit"
VIEW_ACCOUNTANT_ROLE = "Accountant"
VIEW_SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# High enough that no provisioned row could carry it: a 2xx on this id could
# never be mistaken for a real package being reached.
VIEW_UNREACHABLE_ID = 9_999_999

# newschoolapp/core/exceptions.py — the role denial, raised by has_permission
# before the feature-pack branch is reached.
VIEW_ROLE_403 = re.compile(
    r"^\s*You do not have permission to perform this action\s*$", re.I
)
# …and the denial this test must never see, which would mean the licence, not the
# role, is what refused (utils/permissions.py, feature-pack branch).
VIEW_PLAN_403 = re.compile(r"feature not available in your plan", re.I)

# Where usePermissionGuard sends a user whose role lacks the module, and the copy
# that page greets them with (src/app/unauthorized/page.tsx).
VIEW_UNAUTHORIZED_URL = re.compile(r"/unauthorized")
VIEW_ACCESS_DENIED = re.compile(r"^\s*Access Denied\s*$", re.I)
VIEW_UNAUTHORIZED_ACCESS = re.compile(r"^\s*Unauthorized Access\s*$", re.I)

# The sidebar (SideNavigation/nav-config.tsx). The Payroll section and all three
# of its benefit entries must be absent for this role…
VIEW_NAV_PAYROLL_SECTION = re.compile(r"^\s*Payroll Module\s*$", re.I)
VIEW_NAV_BENEFIT_ITEMS = re.compile(r"^\s*Benefit Items\s*$", re.I)
VIEW_NAV_BENEFIT_BAND = re.compile(r"^\s*Benefits Band\s*$", re.I)

# …while the Account section is present, which is what stops "nothing was
# rendered" from passing as "payroll was hidden". Both are gated the same way, on
# permissionsGate + per-item permission, so the pair reads the accountant's own
# permission set back off the screen. (`branchOnly` on both sections applies only
# to a SchoolAdmin — branch state is a SchoolAdmin-only concept.)
VIEW_NAV_ACCOUNT_SECTION = re.compile(r"^\s*Account Module\s*$", re.I)
VIEW_NAV_INCOME_AND_EXPENSES = re.compile(r"^\s*Income\s*&\s*Expenses\s*$", re.I)

VIEW_DENIAL_TIMEOUT_MS = 25_000


@pytest.mark.accountant
@pytest.mark.negative
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="payroll.employee_benefit.view.accountant",
    title="Employee Benefits",
    subtitle="BLOCKED — the Accountant role holds no key to employee benefits",
)
def test_employee_benefit_is_licensed_but_closed_to_the_accountant(
    provisioned_school: SchoolContext,
    api: BackendAPI,
    demo,
) -> None:
    """The accountant of a school licensed for benefits is refused them by role.

    Stands in for the blocked ledger unit
    ``payroll.employee_benefit.view.accountant``; see the section header for the
    product question and why the read-only walkthrough cannot be written.

    ``provisioned_school`` is requested *before* ``demo`` so that, when this test
    is the first of its scenario to run, the provisioning walkthrough happens
    before the camera rolls rather than as dead frames at the head of the video.
    """
    ctx = provisioned_school
    assert ctx.accountant is not None, (
        "provisioning created no accountant for this school — phase C creates "
        "one from /module/staff's Non-teaching Staff tab, which needs the "
        "`staff` module on the pack"
    )
    assert VIEW_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {VIEW_MODULE!r} for this "
        f"unit: the whole point is that the refusal below is the accountant's "
        f"role and not the school's plan"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch, and every benefit read is "
        "branch-scoped — phase B creates one for every scenario"
    )

    accountant = ctx.accountant
    branch_id = int(ctx.branches[0].get("id") or -1)
    assert branch_id > 0, (
        "provisioning could not capture the branch id — re-run provisioning "
        "rather than guessing it"
    )

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
            page.get_by_role("link", name=as_pattern(VIEW_NAV_INCOME_AND_EXPENSES)).first
        ).to_be_visible(timeout=25_000)
        expect(page.get_by_text(as_pattern(VIEW_NAV_ACCOUNT_SECTION)).first).to_be_visible()

    with demo.step("But there is no Payroll menu, and no Employee Benefits in it",
                   dwell_ms=2000):
        expect(page.get_by_text(as_pattern(VIEW_NAV_PAYROLL_SECTION))).to_have_count(0)
        for entry in (
            NAV_EMPLOYEE_BENEFITS, VIEW_NAV_BENEFIT_ITEMS, VIEW_NAV_BENEFIT_BAND
        ):
            expect(
                page.get_by_role("link", name=as_pattern(entry))
            ).to_have_count(0)

    with demo.step("Asking for the benefits register by hand is refused outright",
                   dwell_ms=2500):
        # Deep-linking is the assertion here, not a shortcut: this role is
        # offered no navigation path to the module at all.
        goto(page, base_url.rstrip("/") + f"/module/{VIEW_ROUTE}")
        _view_expect_denial_surface(page)

    with demo.step("The school does license benefits — it is the role that has no key",
                   dwell_ms=2200):
        _view_expect_school_is_licensed(api, ctx)
        _view_expect_accountant_role_holds_nothing(api)

    with demo.step("Every call behind the register answers this accountant 403",
                   dwell_ms=2200):
        _view_expect_backend_refuses(api, ctx, branch_id=branch_id)

    with demo.step("The same register opens for the administrator of that branch",
                   dwell_ms=2000):
        _view_expect_school_admin_gets_through(api, ctx, branch_id=branch_id)


# ─────────────────────── helpers for the blocked view unit ───────────────────


def _view_expect_denial_surface(page: Page) -> None:
    """The module must not render for this role, however the app says no.

    ``usePermissionGuard`` does two things at once: ``page.tsx`` renders ``null``
    because ``hasPermission`` is false, and the hook's effect pushes the browser
    to ``/unauthorized``. The redirect is the surface a user sees, so it is what
    is waited for — but a blank module page is a refusal too, and is accepted as
    long as none of the register's chrome came with it.
    """
    landed_on_unauthorized = False
    heading = page.get_by_role("heading", name=as_pattern(PAGE_HEADING)).first

    remaining = VIEW_DENIAL_TIMEOUT_MS
    while remaining > 0:
        if VIEW_UNAUTHORIZED_URL.search(page.url):
            landed_on_unauthorized = True
            break
        assert heading.count() == 0, (
            "the Employee Benefits register rendered for an Accountant, whose "
            "role holds no employee_benefit permission — the frontend gate has "
            "been dropped while the backend still answers 403, so this user is "
            "being shown a screen that can only fail to load"
        )
        page.wait_for_timeout(500)
        remaining -= 500

    # Nothing the register carries may be on screen, on either surface.
    expect(page.get_by_role("heading", name=as_pattern(PAGE_HEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(TABLE_HEADING))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(CREATE_BUTTON))).to_have_count(0)

    if landed_on_unauthorized:
        expect(page.get_by_text(as_pattern(VIEW_ACCESS_DENIED))).to_be_visible(
            timeout=15_000
        )
        expect(page.get_by_text(as_pattern(VIEW_UNAUTHORIZED_ACCESS))).to_be_visible()


def _view_expect_school_is_licensed(api: BackendAPI, ctx: SchoolContext) -> None:
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
    assert VIEW_MODULE in (body.get("modules") or []), (
        f"{ctx.school_name!r} is not licensed for {VIEW_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack listing it, so every 403 below would be the "
        f"plan talking rather than the role"
    )


def _view_expect_accountant_role_holds_nothing(api: BackendAPI) -> None:
    """Measured, not quoted: the Accountant role's permission set is the blocker.

    Also checks that a role at the same school *does* hold
    ``manage employee_benefit``, so "nobody can use this module" can never pass
    as "the accountant cannot".
    """
    accountant_role = api.get(f"/roles/{api.role_id_for(VIEW_ACCOUNTANT_ROLE)}")
    assert accountant_role.status_code == 200, (
        f"could not read the {VIEW_ACCOUNTANT_ROLE} role — got "
        f"{accountant_role.status_code}: {accountant_role.text[:300]}"
    )
    held = {
        (str(p.get("name")), str(p.get("module")))
        for p in accountant_role.json().get("permissions", [])
    }
    payroll_held = {
        pair for pair in held
        if pair[1] in {VIEW_MODULE, VIEW_PAYROLL_MODULE}
    }
    assert not payroll_held, (
        f"the {VIEW_ACCOUNTANT_ROLE} role now holds {sorted(payroll_held)}. That "
        f"answers the product question this unit is BLOCKED on (state/"
        f"blockers.md): rewrite it as the read-only walkthrough the ledger asked "
        f"for — an accountant signing in, opening Payroll → Employee Benefits, "
        f"and reading the register — and delete this guard."
    )
    assert held, (
        f"the {VIEW_ACCOUNTANT_ROLE} role has no permissions at all, which is the "
        f"defect already fixed in newschoolapp/db/repository/permissions.py (see "
        f"state/backend_patches.md). It has regressed: every accountant now logs "
        f"in to an empty application, and this test's finding is the least of it."
    )

    admin_role = api.get(f"/roles/{api.role_id_for(VIEW_SCHOOL_ADMIN_ROLE)}")
    assert admin_role.status_code == 200, (
        f"could not read the {VIEW_SCHOOL_ADMIN_ROLE} role — got "
        f"{admin_role.status_code}: {admin_role.text[:300]}"
    )
    admin_held = {
        (str(p.get("name")), str(p.get("module")))
        for p in admin_role.json().get("permissions", [])
    }
    assert ("manage", VIEW_MODULE) in admin_held, (
        f"no seeded {VIEW_SCHOOL_ADMIN_ROLE} permission for {VIEW_MODULE!r} "
        f"either, so this module is closed to everybody and the accountant's "
        f"refusal says nothing about the accountant"
    )


def _view_expect_backend_refuses(
    api: BackendAPI, ctx: SchoolContext, *, branch_id: int
) -> None:
    """Every route the two benefit screens use answers this accountant 403.

    The reads are included deliberately: this module defines no ``read``
    permission — ``api/routes/employee_benefit.py`` gates even ``GET`` on
    ``manage`` — which is exactly why "let the accountant look, but not touch"
    is not something this test may arrange for itself.
    """
    token = api.login(ctx.accountant.email, ctx.accountant.password)["access_token"]

    refusals = {
        # The one call the register makes (lib/handlers/employeeBenefitsHandler.ts).
        "list_benefits": api.get(
            "/employee-benefit/?skip=0&limit=100", token=token
        ),
        "read_benefit": api.get(
            f"/employee-benefit/{VIEW_UNREACHABLE_ID}", token=token
        ),
        # The three the create/edit form fetches.
        "list_employees": api.get(
            f"/employee-benefit/employees/?branch_id={branch_id}", token=token
        ),
        "list_benefit_items": api.get(
            f"/employee-benefit/benefit-item/?branch_id={branch_id}&skip=0&limit=100",
            token=token,
        ),
        "list_salary_bands": api.get(
            f"/employee-benefit/salary-band/?branch_id={branch_id}&skip=0&limit=100",
            token=token,
        ),
        # And the write, because the only permission this module defines is
        # "manage": granting the read would grant this too.
        "create_benefit": api.post(
            f"/employee-benefit/?branch_id={branch_id}",
            token=token,
            json={
                "user_id": VIEW_UNREACHABLE_ID,
                "benefit_band_id": VIEW_UNREACHABLE_ID,
                "extra_benefits": [],
                "tax_relief": 100,
                "overtime_tax_eligible": False,
                "tax_exemptions": [],
            },
        ),
    }

    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: the {VIEW_ACCOUNTANT_ROLE} role holds no {VIEW_MODULE!r} "
            f"permission, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert VIEW_ROLE_403.search(detail), (
            f"{label}: 403 is right but the reason is not the role — got "
            f"{detail!r}"
        )
        assert not VIEW_PLAN_403.search(detail), (
            f"{label}: refused for the school's plan rather than the caller's "
            f"role. {ctx.school_name!r} is licensed for {VIEW_MODULE!r}, so this "
            f"test would be reporting somebody else's denial — got {detail!r}"
        )


def _view_expect_school_admin_gets_through(
    api: BackendAPI, ctx: SchoolContext, *, branch_id: int
) -> None:
    """The control: the same call, the same branch, a role that holds the module.

    Only the permission gate is under test here, so the assertion is "not 403"
    rather than "200": ``GET /employee-benefit/`` raises 404 for a branch with no
    packages on it and its own ``except Exception`` re-raises that as a 400 (see
    this file's header), and whether this shared school has one by now depends on
    which unit ran first.
    """
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    res = api.get(
        f"/employee-benefit/?skip=0&limit=100&branch_id={branch_id}", token=token
    )
    assert res.status_code != 403, (
        f"the {VIEW_SCHOOL_ADMIN_ROLE} of {ctx.school_name!r} was refused the "
        f"branch's benefits register too ({res.status_code}: {res.text[:300]}), "
        f"so the accountant's 403 is not about the accountant. That is the "
        f"manage unit's ground, and it has moved."
    )


# ═══════════════════════ payroll.employee_benefit.denied ═══════════════════════
#
# The floor case: a SchoolAdmin of the ``minimal`` school, whose feature pack is
# the most restricted one the pack builder can actually produce — the locked
# "people" and "governance" groups and nothing else, so no ``employee_benefit``.
#
# Where the denial lives, and where it does NOT
#     Not in any frontend guard. Every gate ``/module/employee_benefit`` passes
#     through waves a SchoolAdmin past *before* the feature pack is consulted:
#     ``src/middleware.ts`` skips its module enforcement for the role outright,
#     ``useModuleGuard("employee_benefit")`` returns ``true`` for a SchoolAdmin
#     before it ever reads the ``schoolModules`` cookie, and
#     ``usePermissionGuard("employee_benefit")`` does the same on
#     ``isSchoolAdminRole``. The sidebar entry is not hidden either —
#     ``SideNavigation.canShowItem`` answers on the *permission* check first, and
#     ``db/repository/permissions.py`` seeds SchoolAdmin with
#     ``("manage", "employee_benefit")``.
#
#     What denies them is the backend: *every* route in
#     ``api/routes/employee_benefit.py`` — all fourteen — carries
#     ``Depends(has_permission("manage", "employee_benefit"))``, and the
#     feature-pack branch of ``utils.permissions.has_permission`` answers 403
#     "Feature not available in your plan" for a school whose pack omits the
#     module. Unlike Staff Payroll (see test_staff_payroll.py, where the list and
#     calculate routes carry no gate at all and the denial is therefore invisible
#     in the UI), that leaves the register with nothing it may fetch — so the
#     denial *is* observable end-to-end: the page mounts, its single mount fetch
#     is refused, and the axios interceptor in ``src/utils/handleErrorMessage.ts``
#     turns exactly that detail into a hard redirect to /auth/no-access. Both
#     halves are asserted below.

DENIED_SCENARIO = "minimal"
DENIED_MODULE = "employee_benefit"
DENIED_ROUTE = "employee_benefit"
DENIED_SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# The two denials utils/permissions.py can answer with. A school that holds the
# permission but not the module gets the first; one that holds neither gets the
# second. Either is a correct denial — anything else is not.
DENIED_DETAIL = re.compile(
    r"Feature not available in your plan"
    r"|You do not have permission to perform this action",
    re.I,
)

# Where the frontend sends a user it has decided is not allowed in, and the copy
# it greets them with (src/app/auth/no-access/page.tsx).
DENIED_NO_ACCESS_URL = re.compile(r"/auth/no-access")
DENIED_ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
DENIED_ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)

# The register's own chrome, none of which may reach this admin. PAGE_HEADING,
# SEARCH_PLACEHOLDER, TABLE_HEADING and CREATE_BUTTON are the page object's, so
# the negative path and the manage path can never drift apart on what the screen
# is. The last one is the panel page.tsx renders when a fetch fails for any
# *ordinary* reason (components/common/PageError): seeing it would mean a
# licensing refusal had been handled as a plain error instead of as a denial.
DENIED_SUBHEADING = re.compile(
    r"Manage and monitor employee benefits packages", re.I
)
DENIED_LOAD_FAILURE = re.compile(r"Failed to load employee benefits", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_employee_benefit_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With the module off the pack, a SchoolAdmin gets no benefits register."""
    ctx = provisioned_school
    if DENIED_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {DENIED_MODULE!r}; the denial "
            f"path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had benefits rights anyway", which would make the 403s vacuous.
    role = api.get(f"/roles/{api.role_id_for(DENIED_SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {DENIED_SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert DENIED_MODULE in role_modules, (
        f"the seeded {DENIED_SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{DENIED_MODULE!r} permission, which is the one every route in "
        f"api/routes/employee_benefit.py is gated on. This test would then be "
        f"asserting a denial the role gets for free. Re-point it at the feature "
        f"pack only, or fix the seed in newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{DENIED_MODULE!r} proves nothing about the gate — has_permission treats "
        f"an unpacked school as unrestricted. Provisioning phase A assigns one; "
        f"check that it did."
    )
    licensed = body.get("modules") or []
    assert DENIED_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {DENIED_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every screen behind the module is refused ───────
    #
    # The register's own read, the three collections the create/edit form loads,
    # and the writes its two buttons perform. Ids are deliberately arbitrary:
    # has_permission is a route-level dependency, solved before the path params
    # are used and long before any row is looked up, so a 404 here would itself be
    # the failure. The branch id is real so that a regression which *did* let one
    # through fails on its own merits rather than on a 400 BRANCH_ID_REQUIRED
    # raised inside the handler. For the same reason the create bodies never have
    # to be creatable, but they carry the TEST prefix anyway, so a regression that
    # stored one leaves a sweepable row.
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"?branch_id={branch_id}" if branch_id else ""
    tag = run_tag()

    refusals = {
        # /module/employee_benefit's single mount fetch, in both the shapes
        # GetEmployeeBenefits builds depending on whether a branch is in the
        # store — the unscoped one is a 400 inside the handler, so the licence
        # must be refused before that ever runs.
        "register": api.get(
            f"/employee-benefit/?skip=0&limit=100{branch_query.replace('?', '&')}",
            token=token,
        ),
        "register_unscoped": api.get("/employee-benefit/", token=token),
        "package_detail": api.get(f"/employee-benefit/1{branch_query}", token=token),
        # …the three collections create-benefits/page.tsx loads to build its form,
        "eligible_employees": api.get(
            f"/employee-benefit/employees/{branch_query}", token=token
        ),
        "benefit_items": api.get(
            f"/employee-benefit/benefit-item/{branch_query}", token=token
        ),
        "salary_bands": api.get(
            f"/employee-benefit/salary-band/{branch_query}", token=token
        ),
        # …and the manage half behind "Create Benefits" and the Benefit Items /
        # Benefits Band screens beside it.
        "create_package": api.post(
            f"/employee-benefit/{branch_query}",
            token=token,
            json={
                "user_id": 1,
                "benefit_band_id": 1,
                "extra_benefits": [],
                "tax_relief": 0.0,
            },
        ),
        "update_package": api.patch(
            f"/employee-benefit/1{branch_query}",
            token=token,
            json={"tax_relief": 1.0},
        ),
        "create_benefit_item": api.post(
            f"/employee-benefit/benefit-item{branch_query}",
            token=token,
            json={
                "name": f"{TEST_PREFIX} Denied Allowance {tag}",
                "code": f"DENIED_{tag}".upper(),
                "amount": 1.0,
                "is_taxable": False,
            },
        ),
        "create_salary_band": api.post(
            f"/employee-benefit/salary-band{branch_query}",
            token=token,
            json={
                "band_name": f"{TEST_PREFIX} Denied Band {tag}",
                "benefits": [],
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{DENIED_MODULE!r}, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIED_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a benefits register in front of them ────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Mandatory, not scene-setting: the whole "Payroll Module" section is
    # branchOnly and every request behind this screen appends branch_id from
    # useBranchStore, which only the branch row's "View" button fills.
    if ctx.branches:
        BranchesPage(page, frontend_base_url).select_branch(ctx.branches[0]["name"])

    # A SchoolAdmin is exempt from the middleware gate, from useModuleGuard and
    # from usePermissionGuard, so this route really does mount and really does
    # start fetching — and the axios interceptor turns the refusal into a hard
    # redirect. Waiting for the URL is therefore also what stops the "register is
    # absent" assertions below from passing merely because the page had not
    # finished loading.
    goto_module(page, frontend_base_url, DENIED_ROUTE)
    page.wait_for_url(DENIED_NO_ACCESS_URL, timeout=25_000)
    expect(
        page.get_by_text(as_pattern(DENIED_ACCESS_RESTRICTED))
    ).to_be_visible(timeout=15_000)
    expect(page.get_by_text(as_pattern(DENIED_ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the workspace survives the redirect: not its heading, not its
    # toolbar, not the table, not a single row, and not its create action.
    expect(page.get_by_role("heading", name=as_pattern(PAGE_HEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(DENIED_SUBHEADING))).to_have_count(0)
    expect(page.get_by_placeholder(SEARCH_PLACEHOLDER)).to_have_count(0)
    expect(page.get_by_text(as_pattern(TABLE_HEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(CREATE_BUTTON))).to_have_count(0)
    expect(page.get_by_text(as_pattern(DENIED_LOAD_FAILURE))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)
