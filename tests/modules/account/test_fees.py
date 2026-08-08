"""Fees — the money screens, and who the app is willing to show them to.

This file is written one ledger unit at a time; each section below owns its own
constants (prefixed, never shared) so appending a unit can never silently rebind
a name an earlier section relies on.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.credentials import CredentialCaptureError
from tests.fixtures.data_factories import make_person, run_tag, unique_email
from tests.flows.school_provisioning import Credentials, SchoolContext
from tests.pages.account.fees import (
    DELETE_FEE_ITEM,
    EDIT_FEE_ITEM,
    REQUEST_DELETE_ITEM,
    FeesPage,
)
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.people.guardian_home import GuardianHomePage
from tests.pages.school_admin.branches import BranchesPage


# ═════════════════════ account.fees.view.guardian ═══════════════════════════
#
# What the ledger asked for, and what the app actually implements
#     The unit is filed as a *view* — "Guardian views fees". The app has no such
#     screen, and that is a deliberate design rather than a gap:
#
#       • The Guardian role is seeded with exactly six permissions —
#         ``home, messaging, lessons, student_scores, families, reports``
#         (newschoolapp/db/repository/permissions.py). ``fees`` is not among
#         them, for either "read" or "manage".
#       • Every screen and endpoint the fees module is made of is gated on that
#         permission. ``/module/fees`` calls ``usePermissionGuard("fees")``,
#         which pushes the caller to ``/unauthorized``; the sidebar's whole
#         "Account Module" section carries ``permissionsGate: ["fees",
#         "incomes_and_expenses"]`` and is therefore not rendered at all; and the
#         two requests the dashboard makes — ``GET /fee-payment/history`` and
#         ``GET /fees/fee/statistics`` — both sit behind
#         ``has_permission("read", "fees")``.
#
#     Granting the role that permission would not "fix" anything: the fee
#     endpoints are *branch*-scoped, not guardian-scoped
#     (``payment_history`` filters on ``Class_Model.school_branch_id`` and
#     nothing else), so a parent holding ``read fees`` would be served every
#     child's fee record at the campus. Making a genuine parent-facing fee view
#     therefore means a new, ward-scoped endpoint — a product change, not a
#     defect fix. So what this unit pins is the behaviour that exists: the fee
#     ledger is closed to parents.
#
# Why that is worth a test rather than a shrug
#     ``finance_only`` licenses ``fees``. So the school's *plan* is not what
#     refuses this parent — ``utils/permissions.has_permission`` checks the
#     caller's role first and short-circuits, and the pack half is never
#     reached. That makes the assertion below a statement about *who the user
#     is*, which is exactly the interesting one: buying the finance module must
#     not hand the parent body a branch-wide fee ledger. The pack half is
#     covered separately by ``account.fees.denied`` against ``minimal``.
#
# Why the guardian has to be seeded here
#     ``finance_only``'s pack omits ``guardians``, so provisioning phase C skips
#     guardian creation entirely and ``ctx.guardian`` is ``None`` — there is no
#     parent at this school to ask the question with. One is therefore seeded
#     over the API as the SuperAdmin, who is the only role ``has_permission``
#     exempts from feature-pack enforcement outright. This is setup, never an
#     assertion, and it is the same setup-only use of ``api`` as
#     ``school_provisioning._seed_fee_group``.
#
#     ``UserService.create_user`` honours an explicit ``school_branch_id`` when
#     the creator is a SuperAdmin or SchoolAdmin, which is what puts the seeded
#     parent inside this school — without it they would resolve to no school at
#     all and every refusal below would read "User is not associated with a
#     school", which would prove nothing about fees.
#
# Why the HTTP half runs in the fixture
#     The fixture is requested *before* ``demo`` in the test signature, so its
#     requests happen before the camera rolls rather than as dead frames at the
#     head of the video. It only collects; the test body does the asserting, so
#     a real denial regression is reported as a failure and not as a fixture
#     error.

GUARDIAN_FEES_SCENARIO = "finance_only"
GUARDIAN_FEES_MODULE = "fees"
GUARDIAN_FEES_ROUTE = "fees"
GUARDIAN_ROLE_NAME = "Guardian"

# The seeded parent. Names are the app's own faker shapes; the address must use
# TEST_EMAIL_DOMAIN because the backend answers 422 for reserved TLDs.
GUARDIAN_DOB = "1988-04-02"
GUARDIAN_GENDER = "Female"
GUARDIAN_LOCATION = "Accra"
GUARDIAN_OCCUPATION = "TEST Parent"
GUARDIAN_RELATIONSHIP = "Parent"

# The two denials utils/permissions.py can answer with. The role half runs first
# and short-circuits, so a role that holds no `fees` permission never reaches the
# pack half and never sees the plan message — which is the whole point here,
# since this school *is* licensed for fees.
GUARDIAN_ROLE_DENIAL = re.compile(
    r"You do not have permission to perform this action", re.I
)
GUARDIAN_PLAN_DENIAL = re.compile(r"Feature not available in your plan", re.I)

# Sidebar (SideNavigation/nav-config.tsx). "Home" is the honest non-vacuous
# anchor: it is the one entry a Guardian's permissions do earn, so finding it
# proves the sidebar rendered before the Account entries are declared missing.
GUARDIAN_NAV_HOME = re.compile(r"^\s*Home\s*$", re.I)
GUARDIAN_NAV_SECTION = re.compile(r"^\s*Account Module\s*$", re.I)
GUARDIAN_NAV_FEE_MANAGEMENT = re.compile(r"^\s*Fee Management\s*$", re.I)
GUARDIAN_NAV_FEE_REPORT = re.compile(r"^\s*Fee Report\s*$", re.I)

# Where the frontend sends someone whose role does not hold the permission
# (usePermissionGuard → router.push("/unauthorized")), and the copy that page
# renders (src/app/unauthorized/page.tsx).
GUARDIAN_UNAUTHORIZED_URL = re.compile(r"/unauthorized")
GUARDIAN_ACCESS_DENIED = re.compile(r"^\s*Access Denied\s*$", re.I)
GUARDIAN_UNAUTHORIZED_ACCESS = re.compile(r"^\s*Unauthorized Access\s*$", re.I)

# Chrome that only exists on a rendered fees dashboard
# (src/app/module/fees/page.tsx). None of it may appear anywhere.
GUARDIAN_FEES_HEADING = re.compile(r"^\s*Manage Fees\s*$", re.I)
GUARDIAN_FEES_TOTAL = re.compile(r"Total Fees", re.I)
GUARDIAN_FEES_OUTSTANDING = re.compile(r"Total Outstanding", re.I)
GUARDIAN_FEES_CONFIGURE = re.compile(r"^\s*Configure Fees\s*$", re.I)
GUARDIAN_FEES_SEARCH = re.compile(r"Search student by name", re.I)

GUARDIAN_DENIAL_TIMEOUT_S = 30.0


class GuardianSeedError(RuntimeError):
    """A prerequisite for this unit could not be seeded."""


@dataclass
class GuardianFeeAccess:
    """Everything the walkthrough needs, plus what the API already answered.

    ``refusals`` maps a label to the ``(status, detail)`` the backend gave the
    seeded parent for one of the two requests the fees dashboard makes. It is
    collected here and asserted in the test body so a regression is a failure
    rather than a fixture error.
    """

    credentials: Credentials
    branch_id: int
    licensed_modules: list[str] = field(default_factory=list)
    role_modules: set[str] = field(default_factory=set)
    refusals: dict[str, tuple[int, str]] = field(default_factory=dict)


@pytest.fixture
def fees_guardian(
    provisioned_school: SchoolContext, api: BackendAPI, superadmin: Any
) -> GuardianFeeAccess:
    """Seed a parent at the finance school and ask the fee API as them."""
    ctx = provisioned_school
    super_token = _super_admin_token(api, superadmin)
    branch_id = _branch_id(api, super_token, ctx)

    # make_person already draws the address from unique_email(), which uses
    # TEST_EMAIL_DOMAIN — the backend answers 422 for reserved TLDs, so an
    # address is never written by hand here.
    person = make_person("fees-guardian", ctx.school_id, gender=GUARDIAN_GENDER)
    guardian = _seed_guardian(
        api,
        super_token,
        person=person,
        branch_id=branch_id,
        role_id=api.role_id_for(GUARDIAN_ROLE_NAME),
    )

    access = GuardianFeeAccess(credentials=guardian, branch_id=branch_id)

    # What the school is licensed for, read as the SchoolAdmin — the same
    # account the sibling denial unit reads it with.
    admin_token = api.login(
        ctx.school_admin.email, ctx.school_admin.password
    )["access_token"]
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=admin_token)
    if features.status_code != 200:
        raise GuardianSeedError(
            f"could not read {ctx.school_name!r}'s features: "
            f"{features.status_code} {features.text[:300]}"
        )
    body = features.json()
    if body.get("pack_assigned") is not True:
        raise GuardianSeedError(
            f"{ctx.school_name!r} has no feature pack assigned, so this unit "
            f"could not tell a role denial from a licence one. Provisioning "
            f"phase A assigns one — check that it did."
        )
    access.licensed_modules = list(body.get("modules") or [])

    # What the Guardian role itself holds, read back rather than assumed.
    role = api.get(f"/roles/{api.role_id_for(GUARDIAN_ROLE_NAME)}")
    if role.status_code != 200:
        raise GuardianSeedError(
            f"could not read the {GUARDIAN_ROLE_NAME} role: "
            f"{role.status_code} {role.text[:300]}"
        )
    access.role_modules = {
        str(p.get("module")) for p in (role.json().get("permissions") or [])
    }

    # The two requests src/app/module/fees/page.tsx makes on mount. Asked as the
    # parent, with the branch named, so a refusal cannot be blamed on a missing
    # scope parameter.
    guardian_token = api.login(guardian.email, guardian.password)["access_token"]
    for label, path in (
        ("payment_history", f"/fee-payment/history?skip=0&limit=10&branch_id={branch_id}"),
        ("fee_statistics", f"/fees/fee/statistics?branch_id={branch_id}"),
    ):
        response = api.get(path, token=guardian_token)
        access.refusals[label] = (response.status_code, _detail_of(response))

    return access


@pytest.mark.guardian
@pytest.mark.scenario(GUARDIAN_FEES_SCENARIO)
@pytest.mark.demo(
    feature_id="account.fees.view.guardian",
    title="Fees",
    subtitle="A guardian is not shown the school's fee records",
)
def test_guardian_is_not_shown_the_schools_fee_records(
    fees_guardian: GuardianFeeAccess,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A parent at a fee-licensed school reaches no part of the fees module.

    Every leg is asserted against a school whose pack *does* include ``fees``,
    so nothing below can be explained away by the licence: it is the Guardian
    role, and only the role, that is being refused.
    """
    ctx = provisioned_school
    access = fees_guardian
    guardian = access.credentials

    # ── 1. The licence is not what refuses them ──────────────────────────────
    assert GUARDIAN_FEES_MODULE in access.licensed_modules, (
        f"{ctx.school_name!r} is not licensed for {GUARDIAN_FEES_MODULE!r} "
        f"(pack modules: {sorted(access.licensed_modules)}), so a refusal below "
        f"would say nothing about the Guardian role. The {ctx.scenario_id!r} "
        f"scenario is supposed to switch fees on."
    )

    # ── 2. …their role is ────────────────────────────────────────────────────
    #
    # Read back rather than hard-coded. If someone ever grants the Guardian role
    # `fees`, this unit must fail loudly rather than quietly keep asserting a
    # denial: the fee endpoints are branch-scoped, so that grant would serve
    # every child's record at the campus to every parent.
    assert GUARDIAN_FEES_MODULE not in access.role_modules, (
        f"the seeded {GUARDIAN_ROLE_NAME} role now holds "
        f"{GUARDIAN_FEES_MODULE!r} ({sorted(access.role_modules)}). The fee "
        f"endpoints are scoped to a branch and not to a ward "
        f"(fee_payment.payment_history filters only on "
        f"Class_Model.school_branch_id), so this grant exposes every student's "
        f"fee record to every parent at the campus."
    )

    # ── 3. The backend refuses both requests the dashboard makes ─────────────
    for label, (status, detail) in access.refusals.items():
        assert status == 403, (
            f"{label}: a {GUARDIAN_ROLE_NAME} at {ctx.school_name!r} must be "
            f"refused the fee ledger — got {status}: {detail[:300]}"
        )
        assert GUARDIAN_ROLE_DENIAL.search(detail), (
            f"{label}: 403 is right, but not for the reason this school implies. "
            f"The pack licenses {GUARDIAN_FEES_MODULE!r}, so the refusal must "
            f"come from the role half of has_permission, matching "
            f"{GUARDIAN_ROLE_DENIAL.pattern!r} — got {detail!r}. A "
            f"{GUARDIAN_PLAN_DENIAL.pattern!r} here would mean the licence "
            f"lapsed rather than the role being refused."
        )

    # ── 4. …and the browser tells the same story ─────────────────────────────
    page: Page = demo.page
    home = GuardianHomePage(page, demo.frontend_base_url)

    with demo.step(f"Sign in as {guardian.full_name}, a parent at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, guardian)

    with demo.step("A parent lands on their own home page, and nowhere else"):
        home.expect_loaded()
        expect(
            page.get_by_text(as_pattern(re.escape(guardian.email))).first
        ).to_be_visible(timeout=30_000)

    with demo.step("This school pays for the finance module — but their menu "
                   "has no Account section in it"):
        expect(
            page.get_by_role("link", name=as_pattern(GUARDIAN_NAV_HOME)).first
        ).to_be_visible(timeout=30_000)
        expect(page.get_by_text(as_pattern(GUARDIAN_NAV_SECTION))).to_have_count(0)
        expect(
            page.get_by_role("link", name=as_pattern(GUARDIAN_NAV_FEE_MANAGEMENT))
        ).to_have_count(0)
        expect(
            page.get_by_role("link", name=as_pattern(GUARDIAN_NAV_FEE_REPORT))
        ).to_have_count(0)

    with demo.step("So try the fee ledger's address by hand instead"):
        goto_module(page, demo.frontend_base_url, GUARDIAN_FEES_ROUTE)

    surface = _wait_for_fees_denial(page)

    with demo.step("The app turns them away: Access Denied"):
        if surface == "unauthorized":
            expect(
                page.get_by_text(as_pattern(GUARDIAN_ACCESS_DENIED)).first
            ).to_be_visible(timeout=15_000)
            expect(
                page.get_by_text(as_pattern(GUARDIAN_UNAUTHORIZED_ACCESS)).first
            ).to_be_visible(timeout=15_000)
        else:
            # The guard has not redirected (yet), but the screen itself renders
            # nothing for a role without the permission — asserted rather than
            # tolerated, so a build that started drawing the dashboard here
            # could not slip through as "a slow redirect".
            expect(
                page.get_by_text(as_pattern(GUARDIAN_FEES_HEADING))
            ).to_have_count(0)

    with demo.step("Not one figure from the school's fee ledger reaches a parent",
                   dwell_ms=1500):
        # Invariant under both surfaces. These five are the only things the fees
        # dashboard puts on screen, so none of them may exist anywhere.
        for absent in (
            GUARDIAN_FEES_HEADING,
            GUARDIAN_FEES_TOTAL,
            GUARDIAN_FEES_OUTSTANDING,
            GUARDIAN_FEES_SEARCH,
        ):
            expect(page.get_by_text(as_pattern(absent))).to_have_count(0)
        expect(
            page.get_by_role("button", name=as_pattern(GUARDIAN_FEES_CONFIGURE))
        ).to_have_count(0)
        expect(page.locator("table")).to_have_count(0)


def _wait_for_fees_denial(page: Page) -> str:
    """Wait for whichever denial surface /module/fees reaches, and name it.

    Today ``usePermissionGuard("fees")`` pushes a Guardian to ``/unauthorized``
    once the persisted role permissions have rehydrated. Until they have, the
    page renders ``null`` — also a denial, and the fallback this accepts. Only
    "the dashboard appeared" is a failure, which the caller's assertions catch.
    """
    deadline = time.monotonic() + GUARDIAN_DENIAL_TIMEOUT_S
    while time.monotonic() < deadline:
        if GUARDIAN_UNAUTHORIZED_URL.search(page.url):
            return "unauthorized"
        page.wait_for_timeout(250)
    return "blank"


# ─────────── setup-only seeding for this unit (never asserted) ──────────────


def _super_admin_token(api: BackendAPI, superadmin: Any) -> str:
    """The SuperAdmin bearer token — the one role the feature-pack gate exempts."""
    token = getattr(superadmin, "access_token", None)
    if token:
        return str(token)
    email = getattr(superadmin, "email", "")
    password = getattr(superadmin, "password", "")
    try:
        return str(api.login(email, password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise GuardianSeedError(
            f"could not log in as the SuperAdmin {email!r}: {exc}"
        ) from exc


def _branch_id(api: BackendAPI, token: str, ctx: SchoolContext) -> int:
    """The campus the seeded parent belongs to.

    Provisioning normally captures this from ``POST /branch/``; when that
    response could not be read it stores ``-1``, so fall back to listing the
    school's branches as the SuperAdmin.
    """
    if ctx.branches:
        captured = ctx.branches[0].get("id")
        if isinstance(captured, int) and captured > 0:
            return captured

    response = api.get(f"/branch/?school_id={ctx.school_id}&limit=100", token=token)
    if response.status_code >= 400:
        raise GuardianSeedError(
            f"could not list branches of school {ctx.school_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    rows = [row for row in response.json() if isinstance(row, dict)]
    if not rows:
        raise GuardianSeedError(
            f"{ctx.school_name!r} has no branch, so a parent cannot be scoped to "
            f"it. Provisioning phase B creates one — check that it did."
        )
    return int(rows[0]["id"])


def _seed_guardian(
    api: BackendAPI,
    token: str,
    *,
    person: Any,
    branch_id: int,
    role_id: int,
) -> Credentials:
    """Create one parent at ``branch_id`` as the SuperAdmin.

    A SchoolAdmin cannot do this here: ``POST /guardian/`` is gated on
    ``has_permission("manage", "guardians")`` and the ``finance_only`` pack omits
    ``guardians``, so their request is refused by the pack half. The SuperAdmin
    is exempt from that gate outright.

    The password is server-generated and only ever emailed, so it is read out of
    the backend's QA mode — the same ``X-Test-Mode`` channel
    ``tests.fixtures.credentials`` reads through Playwright, taken off the httpx
    response here because there is no page driving this request.
    """
    payload = {
        "occupation": GUARDIAN_OCCUPATION,
        "relationship_type": GUARDIAN_RELATIONSHIP,
        "additional_remarks": "Seeded so this school has a parent to ask with.",
        "student_ids": [],
        "user": {
            "first_name": person.first_name,
            "other_names": person.last_name,
            "email": person.email,
            "gender": GUARDIAN_GENDER,
            "date_of_birth": GUARDIAN_DOB,
            "nationality": person.nationality,
            "residential_address": person.address,
            "location": GUARDIAN_LOCATION,
            "primary_phone": person.phone,
            "school_branch_id": branch_id,
            "role_id": role_id,
            # Overwritten by GuardianService with the generated guardian_id
            # before the user is created; sent only because the schema requires
            # it. The real password comes back through QA mode below.
            "password": "seeded-by-qa",
            "password_confirmation": "seeded-by-qa",
            "is_active": True,
        },
    }
    response = api.post("/guardian/", token=token, json=payload)
    if response.status_code >= 400:
        raise GuardianSeedError(
            f"could not seed a guardian in branch {branch_id}: "
            f"{response.status_code} {response.text[:400]}"
        )

    return Credentials(
        email=person.email,
        password=_qa_password(response),
        role_name=GUARDIAN_ROLE_NAME,
        first_name=person.first_name,
        last_name=person.last_name,
        role=GUARDIAN_ROLE_NAME,
    )


def _detail_of(response: Any) -> str:
    """The FastAPI ``detail`` string, or the raw body when there is none."""
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 — non-JSON bodies are reported verbatim
        return response.text
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return response.text


def _qa_password(response: Any) -> str:
    """The generated password QA mode attached to this response.

    Mirrors ``tests.fixtures.credentials.read_test_mode`` for an httpx response:
    the header first (it is present on every response, whatever the body shape),
    then the ``test_mode`` key in the body.
    """
    block: dict[str, Any] = {}
    header = response.headers.get("x-test-mode")
    if header:
        try:
            block = json.loads(header)
        except json.JSONDecodeError:
            block = {}
    if not block:
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = None
        if isinstance(body, dict) and isinstance(body.get("test_mode"), dict):
            block = body["test_mode"]

    if not block:
        raise CredentialCaptureError(
            f"No test_mode data on {response.status_code} {response.url}.\n"
            f"QA mode is not enabled on the backend. Enable it with:\n"
            f"  touch <backend-repo>/.qa_mode_enabled\n"
            f"(or set QA_MODE=1), then wait for uvicorn --reload to pick it up."
        )

    password = block.get("initial_password")
    if not password:
        passwords = block.get("passwords") or []
        password = passwords[0] if passwords else None
    if not password:
        raise CredentialCaptureError(
            f"test_mode present on {response.url} but carried no password: "
            f"{sorted(block)}"
        )
    return str(password)


# ═════════════════════ account.fees.view.school_admin ═══════════════════════
#
# The other side of the unit above: the role the fee ledger *is* built for.
#
# What the walkthrough reads
#     /module/fees is the bursar's dashboard — three totals the backend computes
#     (``GET /fees/fee/statistics``) over a ledger of every student the branch
#     bills (``GET /fee-payment/history``) — and /module/fees/fees_config is what
#     the school charges: the "Fee Group" tab lists the bundles a class is billed
#     under (``GET /fees/groups``) and the "Fees" tab the individual line items
#     (``GET /fees/``). All four requests are reads; this unit presses none of the
#     module's write controls.
#
# Why the student ledger is expected to be empty here
#     ``finance_only`` licenses ``students`` but not ``guardians``, and the
#     admission wizard's guardian picker is the only working way to link a pupil
#     to a parent — so provisioning phase C skips the admission entirely (see
#     ``school_provisioning._phase_c_create_users``) and this branch has nobody to
#     bill. That is the honest state of the scenario, so the ledger assertion
#     accepts rows *or* FeesTable's own "No students found" empty state: what it
#     pins is that the panel finished loading and that ``PageError`` did not
#     replace the screen. The figures worth asserting for real are on the
#     configuration side — what the school charges, rather than who has paid.
#
# What is seeded, and why over the API
#     Both configuration tabs only read. What they read — a fee, and a group that
#     bundles fees — is this module's *manage* half, a different unit's
#     walkthrough. ``configured_fees`` therefore creates two fees and one group
#     over the API, the same setup-only use of ``api`` as
#     ``school_provisioning._seed_fee_group`` (which does not run for this
#     scenario: it is gated on ``classes_and_timetables``, which ``finance_only``
#     omits).
#
#     Everything the test then matches is derived from the server's answer rather
#     than from the browser's own state — the group's "Amount Payable" is
#     ``calculateTotalAmount`` over the fees the *backend* attached to the group,
#     and each fee's Academic Year/Term columns come from the relationships
#     ``FeeResponse`` joins in — so the assertions prove the screens really
#     fetched this branch's configuration.
#
# Selecting a branch is a prerequisite, not a nicety
#     A SchoolAdmin belongs to no branch. The sidebar's whole "Account Module"
#     section is ``branchOnly``, and every fetch behind both screens appends
#     ``branch_id`` from ``useBranchStore`` — which only the branch row's "View"
#     button fills. Without it there is no Fee Management link to click and no
#     branch to scope the reads to.

ADMIN_FEES_SCENARIO = "finance_only"
ADMIN_FEES_MODULE = "fees"

# What this unit puts in front of the bursar. Carries the "TEST" prefix the
# orphan sweeper matches on, and is deliberately named apart from provisioning's
# own "TEST Tuition" so the search assertion below cannot be satisfied by a
# leftover from another scenario's seeding.
ADMIN_TUITION_FEE = "TEST Term Tuition"
ADMIN_TUITION_AMOUNT = 250
ADMIN_TUITION_DESCRIPTION = "Teaching and classroom costs for the term"

ADMIN_LIBRARY_FEE = "TEST Library Levy"
ADMIN_LIBRARY_AMOUNT = 50
ADMIN_LIBRARY_DESCRIPTION = "Borrowing rights for the term"

ADMIN_FEE_GROUP = "TEST Termly Fee Structure"
# feeGroup.tsx sums the group's fees client-side and prints "GHC 300.00".
ADMIN_FEE_GROUP_TOTAL = r"^\s*GHC\s*300\.00\s*$"

# The Amount column prints the Decimal exactly as the API serialised it, which is
# "250.00" today but need not stay that precise.
ADMIN_AMOUNT_CELL = {
    ADMIN_TUITION_FEE: rf"^\s*{ADMIN_TUITION_AMOUNT}(?:\.\d+)?\s*$",
    ADMIN_LIBRARY_FEE: rf"^\s*{ADMIN_LIBRARY_AMOUNT}(?:\.\d+)?\s*$",
}

# What a bursar would type to pull one line item out of the list.
ADMIN_FEE_SEARCH_TERM = "Library Levy"


class FeesConfigSeedError(RuntimeError):
    """A prerequisite could not be seeded, so the configuration would be empty."""


@dataclass
class ConfiguredFees:
    """The fee structure the walkthrough is expected to read back."""

    branch_id: int
    branch_name: str
    academic_year: str
    academic_term: str
    fee_ids: dict[str, int]
    group_id: int


@pytest.fixture
def configured_fees(
    provisioned_school: SchoolContext, api: BackendAPI
) -> ConfiguredFees:
    """Give the branch two fees and one group that bundles them.

    Requested *before* ``demo`` in the test signature so the seeding requests
    happen before the camera rolls, rather than as dead frames at the head of the
    video.
    """
    ctx = provisioned_school
    assert ADMIN_FEES_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {ADMIN_FEES_MODULE!r} for "
        f"this unit — it is the positive path"
    )
    assert ctx.branches, "provisioning created no branch for this school"

    branch = ctx.branches[0]
    branch_id = int(branch.get("id") or -1)
    if branch_id <= 0:
        raise FeesConfigSeedError(
            "provisioning captured no branch id, and every fee read here is "
            "branch-scoped. Phase B creates the branch — check that it did."
        )

    token = _admin_token(api, ctx.school_admin)
    year, term = _view_year_and_term(api, token, school_id=ctx.school_id)

    fee_ids = {
        ADMIN_TUITION_FEE: _seed_view_fee(
            api, token,
            branch_id=branch_id,
            name=ADMIN_TUITION_FEE,
            amount=ADMIN_TUITION_AMOUNT,
            description=ADMIN_TUITION_DESCRIPTION,
            year_id=int(year["id"]),
            term_id=int(term["id"]),
        ),
        ADMIN_LIBRARY_FEE: _seed_view_fee(
            api, token,
            branch_id=branch_id,
            name=ADMIN_LIBRARY_FEE,
            amount=ADMIN_LIBRARY_AMOUNT,
            description=ADMIN_LIBRARY_DESCRIPTION,
            year_id=int(year["id"]),
            term_id=int(term["id"]),
        ),
    }

    return ConfiguredFees(
        branch_id=branch_id,
        branch_name=str(branch["name"]),
        academic_year=str(year["name"]),
        academic_term=str(term["name"]),
        fee_ids=fee_ids,
        group_id=_seed_view_group(
            api, token,
            branch_id=branch_id,
            name=ADMIN_FEE_GROUP,
            fee_ids=sorted(fee_ids.values()),
        ),
    )


@pytest.mark.school_admin
@pytest.mark.scenario(ADMIN_FEES_SCENARIO)
@pytest.mark.demo(
    feature_id="account.fees.view.school_admin",
    title="Fees",
    subtitle="SchoolAdmin views fees",
)
def test_school_admin_views_fees(
    configured_fees: ConfiguredFees,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A school administrator reads the branch's fees, and changes nothing.

    The read *is* the feature. "Record Payment", "Create Fee" and "Create fee
    group" are deliberately not asserted absent — the seeded SchoolAdmin role
    holds ``("manage", "fees")``, so those controls are expected to be on screen.
    This walkthrough simply never presses them.
    """
    ctx = provisioned_school
    page: Page = demo.page
    fees_page = FeesPage(page, demo.frontend_base_url)

    with demo.step(f"Sign in as the administrator of {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.school_admin)

    with demo.step(f"Open {configured_fees.branch_name}, the campus whose books "
                   f"are being reviewed"):
        BranchesPage(page, demo.frontend_base_url).select_branch(
            configured_fees.branch_name
        )

    with demo.step("Fee Management is waiting in the Account menu"):
        # Reached by route first, because "View" on the branch row routes to
        # /module/community — a module this school's pack does not license, so
        # the branch selection above lands on /auth/no-access, which renders no
        # sidebar at all. Coming back via the branches page is not an option
        # either: its mount effect calls clearBranch(). So the Account entry is
        # asserted from inside the module chrome, which is where a bursar reads
        # it anyway.
        fees_page.open()
        fees_page.expect_nav_entry()
        fees_page.open_from_sidebar()
        fees_page.expect_no_load_failure()

    with demo.step("The campus totals: billed, collected, and still outstanding"):
        fees_page.expect_stats()
        fees_page.expect_no_load_failure()

    with demo.step("Below them sits every student the campus bills, searchable "
                   "by name or by class"):
        fees_page.expect_ledger()
        fees_page.expect_filters()
        fees_page.expect_no_load_failure()

    with demo.step("Step into Configure Fees to see what this school charges"):
        config = fees_page.open_fee_configuration()
        config.open_fee_groups_tab()
        config.expect_fee_group_headers()
        config.expect_fee_group_count()
        config.wait_for_fee_groups()

    with demo.step(f"{ADMIN_FEE_GROUP} bundles tuition and the library levy into "
                   f"a single bill"):
        config.expect_fee_group(
            ADMIN_FEE_GROUP,
            amount_payable=ADMIN_FEE_GROUP_TOTAL,
            includes=(ADMIN_TUITION_FEE, ADMIN_LIBRARY_FEE),
        )

    with demo.step(f"The Fees tab breaks that bill into its parts, each billed "
                   f"for {configured_fees.academic_term}, "
                   f"{configured_fees.academic_year}"):
        config.open_fees_tab()
        config.expect_fee_headers()
        config.wait_for_fees()
        config.expect_fee(
            ADMIN_TUITION_FEE,
            amount=ADMIN_AMOUNT_CELL[ADMIN_TUITION_FEE],
            description=ADMIN_TUITION_DESCRIPTION,
            academic_year=configured_fees.academic_year,
            academic_term=configured_fees.academic_term,
        )
        config.expect_fee(
            ADMIN_LIBRARY_FEE,
            amount=ADMIN_AMOUNT_CELL[ADMIN_LIBRARY_FEE],
            description=ADMIN_LIBRARY_DESCRIPTION,
            academic_year=configured_fees.academic_year,
            academic_term=configured_fees.academic_term,
        )

    with demo.step("Searching narrows the list to the one levy — a read, with "
                   "nothing rewritten", dwell_ms=1500):
        config.search_fees(ADMIN_FEE_SEARCH_TERM)
        config.expect_fee(
            ADMIN_LIBRARY_FEE, amount=ADMIN_AMOUNT_CELL[ADMIN_LIBRARY_FEE]
        )
        config.expect_fee_absent(ADMIN_TUITION_FEE)


# ─────────── setup-only seeding for this unit (never asserted) ──────────────


def _admin_token(api: BackendAPI, creds: Credentials) -> str:
    try:
        return str(api.login(creds.email, creds.password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise FeesConfigSeedError(
            f"could not log in as {creds.email}: {exc}"
        ) from exc


def _view_rows(payload: Any) -> list[dict]:
    """Some list endpoints answer a bare list, others a paginated envelope."""
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    return [row for row in payload if isinstance(row, dict)]


def _view_year_and_term(
    api: BackendAPI, token: str, *, school_id: int
) -> tuple[dict, dict]:
    """The calendar a fee has to be billed against.

    ``FeeCreate`` requires both ids, and the Fees tab prints their names straight
    back out — so this is also where the year and term the test asserts on come
    from, rather than from constants that could drift from the provisioned school.
    """
    years = api.get(
        f"/academic-year/?skip=0&limit=100&school_id={school_id}", token=token
    )
    if years.status_code >= 400:
        raise FeesConfigSeedError(
            f"could not list academic years: {years.status_code} {years.text[:300]}"
        )
    rows = _view_rows(years.json())
    year = next((y for y in rows if y.get("is_active")), rows[0] if rows else None)
    if not year:
        raise FeesConfigSeedError(
            "the school has no academic year, so no fee can be billed against "
            "one — provisioning phase B creates it."
        )

    terms = api.get(f"/academic-term/by-year/{year['id']}", token=token)
    if terms.status_code >= 400:
        raise FeesConfigSeedError(
            f"could not list terms for academic year {year['id']}: "
            f"{terms.status_code} {terms.text[:300]}"
        )
    term_rows = _view_rows(terms.json())
    term = next(
        (t for t in term_rows if t.get("is_active")),
        term_rows[0] if term_rows else None,
    )
    if not term:
        raise FeesConfigSeedError(
            f"academic year {year.get('name')!r} has no term, so no fee can be "
            f"billed against one — provisioning phase B creates it."
        )
    return year, term


def _seed_view_fee(
    api: BackendAPI,
    token: str,
    *,
    branch_id: int,
    name: str,
    amount: int,
    description: str,
    year_id: int,
    term_id: int,
) -> int:
    """One line item on the school's bill, reused if it is already there.

    The whole batch shares one provisioned school, and two fees of the same name
    would make the configuration table ambiguous to assert on.
    """
    existing = _view_existing_id(
        api, token, f"/fees/?skip=0&limit=100&branch_id={branch_id}", name=name
    )
    if existing is not None:
        return existing

    response = api.post(
        f"/fees/?branch_id={branch_id}",
        token=token,
        json={
            "name": name,
            "amount": amount,
            "description": description,
            "academic_year_id": year_id,
            "academic_term_id": term_id,
            "school_branch_id": branch_id,
        },
    )
    if response.status_code >= 400:
        raise FeesConfigSeedError(
            f"could not seed the fee {name!r} in branch {branch_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return int(response.json()["id"])


def _seed_view_group(
    api: BackendAPI,
    token: str,
    *,
    branch_id: int,
    name: str,
    fee_ids: list[int],
) -> int:
    """The bundle a class is billed under — the "Fee Group" tab's whole content."""
    existing = _view_existing_id(
        api, token, f"/fees/groups?skip=0&limit=100&branch_id={branch_id}", name=name
    )
    if existing is not None:
        return existing

    response = api.post(
        f"/fees/group?branch_id={branch_id}",
        token=token,
        json={"name": name, "school_fees_ids": fee_ids},
    )
    if response.status_code >= 400:
        raise FeesConfigSeedError(
            f"could not seed the fee group {name!r} in branch {branch_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return int(response.json()["id"])


def _view_existing_id(
    api: BackendAPI, token: str, path: str, *, name: str
) -> int | None:
    """The id of a row already named ``name``, if the list endpoint offers one."""
    response = api.get(path, token=token)
    if response.status_code >= 400:
        return None
    wanted = re.compile(rf"^\s*{re.escape(name)}\s*$", re.I)
    for row in _view_rows(response.json()):
        if wanted.match(str(row.get("name", ""))):
            return int(row["id"])
    return None


# ═══════════════════════ account.fees.denied ════════════════════════════════
#
# The pack half of the gate, on the same route the guardian unit above proves the
# *role* half of. A SchoolAdmin of the ``minimal`` school holds every fees
# permission the app defines and is still refused, because their school is not
# licensed for the module.
#
# Where the denial actually lives
#     Not in the sidebar, and not in a route guard. ``src/middleware.ts`` makes
#     ``!isSchoolAdmin`` a condition of its module redirect, and
#     ``useModuleGuard`` hands a SchoolAdmin ``hasAccess = true`` before it ever
#     reads the ``schoolModules`` cookie — so ``/module/fees`` really does mount
#     for this admin. The seeded SchoolAdmin role also *holds* ``("manage",
#     "fees")`` (newschoolapp/db/repository/permissions.py), so
#     ``usePermissionGuard`` lets them through and the permission half of the
#     backend gate passes as well.
#
#     What denies them is the feature-pack half of
#     ``utils.permissions.has_permission``: it resolves the caller's school, asks
#     ``FeaturePackService`` for its module list, and answers **403 "Feature not
#     available in your plan"** when the module is missing. Every gated route on
#     ``api/routes/fees.py`` and ``api/routes/fee_payment.py`` carries that
#     dependency, and it is solved before the request body is validated — which
#     is why the ids and payloads below are deliberately arbitrary. A 404 or a
#     422 in their place would itself be the failure.
#
#     The UI consequence follows from it. ``FeeDashboard``'s fetch effect calls
#     ``GET /fee-payment/history`` and ``GET /fees/fee/statistics``, both gated,
#     and the axios response interceptor in ``src/utils/handleErrorMessage.ts``
#     recognises that particular detail (``shouldRedirectToNoAccess``) and
#     performs a hard ``window.location`` redirect to **/auth/no-access**,
#     rejecting with ``FeatureNotAvailableError``. That redirect races the page's
#     own ``catch``, which renders the "Failed to load fees data" ``PageError``
#     panel — so both surfaces are accepted below.
#
#     Note this is a *different* denial surface from the guardian unit above:
#     that one is refused by role and lands on ``/unauthorized``; this one is
#     refused by plan and lands on ``/auth/no-access``. Asserting the wrong page
#     would silently prove the wrong thing.
#
#     Unlike the topics and lessons denials, this UI half really is
#     *fees*-specific: the only other request the screen makes on mount is
#     ``GET /classes/``, and that route carries no ``has_permission`` dependency
#     at all, so it cannot be the thing that fired the redirect.
#
# Three honesty notes about what this test does and does not claim
#     1. Selecting the branch first is mandatory, not a convenience. A
#        SchoolAdmin belongs to no branch, and ``page.tsx`` returns early from
#        its fetch effect while ``useBranchStore`` is empty ("if (…schooladmin…)
#        && !currentSchoolAdminBranch?.branch_id) return"). Without the branch
#        the screen renders its chrome and requests *nothing* — an empty ledger
#        that would prove nothing about the plan.
#     2. Deliberately *not* asserted: that the sidebar hides "Fee Management".
#        ``nav-config.tsx`` gates that entry on ``permission: "fees"``, and
#        ``SideNavigation`` lets the permission check take priority over the
#        module gate — so for a SchoolAdmin its presence says nothing about the
#        school's pack. (For the Guardian above it does, which is why that unit
#        asserts it and this one does not.)
#     3. Deliberately *not* asserted: that ``/module/fees/fees_config``
#        redirects. Its two tabs read ``GET /fees/groups`` and ``GET /fees/`` —
#        the only two fee reads whose ``has_permission`` dependency is commented
#        out in ``api/routes/fees.py`` (untouched upstream product state, not
#        drift), so that page mounts and lists nothing rather than being refused.
#        Its *writes* — create fee, create fee group, rename, delete — are all
#        gated, and are asserted route by route in the API half below, which is
#        where that claim belongs.

DENIED_FEES_SCENARIO = "minimal"
DENIED_FEES_MODULE = "fees"
DENIED_FEES_ROUTE = "fees"
DENIED_SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# Path ids for the gated routes. High enough that no provisioned row could carry
# one, so a 2xx here could never be mistaken for a real record being reached.
DENIED_UNREACHABLE_ID = 9_999_999

# The two denials utils/permissions.py can answer with. A school that holds the
# permission but not the module gets the first; one that holds neither gets the
# second. Either is a correct denial — anything else is not.
DENIED_DETAIL = re.compile(
    r"Feature not available in your plan"
    r"|You do not have permission to perform this action",
    re.I,
)

# Where the frontend sends a user whose *plan* excludes the module, and the copy
# it greets them with (src/app/auth/no-access/page.tsx).
DENIED_NO_ACCESS_URL = re.compile(r"/auth/no-access")
DENIED_ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
DENIED_ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)

# The fees workspace's own chrome (src/app/module/fees/page.tsx and
# components/FeesTable.tsx), none of which may put a usable ledger on screen.
DENIED_FEES_HEADING = re.compile(r"^\s*Manage Fees\s*$", re.I)
DENIED_FEES_SEARCH = re.compile(r"^\s*Search student by name\s*$", re.I)
DENIED_FEES_CONFIGURE = re.compile(r"^\s*Configure Fees\s*$", re.I)
DENIED_LEDGER_EMPTY = re.compile(r"^\s*No students found\s*$", re.I)
DENIED_LOAD_FAILURE = re.compile(r"^\s*Failed to load fees data\s*$", re.I)
# ModuleHeader's three tiles, which must stay at the zeroed defaults the refused
# statistics read left behind.
DENIED_STAT_TILES = (
    "Total Fees (GHC)",
    "Total Paid (GHC)",
    "Total Outstanding (GHC)",
)

DENIED_SETTLE_TIMEOUT_MS = 40_000


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_FEES_SCENARIO)
def test_fees_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `fees` off the pack, a SchoolAdmin can neither read a fee ledger nor
    write a fee, a fee group, a payment or an arrear."""
    ctx = provisioned_school
    if DENIED_FEES_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {DENIED_FEES_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    assert ctx.branches, (
        "provisioning left this school with no branch, so there is no scope to "
        "read fees for — phase B creates one for every scenario"
    )
    branch = ctx.branches[0]
    branch_id = int(branch["id"]) if branch.get("id") else 0
    branch_query = f"?branch_id={branch_id}" if branch_id else ""

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ─────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had fees rights anyway", which would make the 403s vacuous.
    role = api.get(f"/roles/{api.role_id_for(DENIED_SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {DENIED_SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert DENIED_FEES_MODULE in role_modules, (
        f"the seeded {DENIED_SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{DENIED_FEES_MODULE!r} permission, so this test would be asserting a "
        f"denial the role gets for free. Re-point it at the feature pack only, "
        f"or fix the seed in newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    features_body = features.json()
    assert features_body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{DENIED_FEES_MODULE!r} proves nothing about the gate. Provisioning "
        f"phase A assigns one — check that it did."
    )
    assert DENIED_FEES_MODULE not in (features_body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {DENIED_FEES_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every gated fees route is refused ──────────────
    #
    # Reads and writes alike, across both routers, so the gate cannot regress
    # into being merely read-only or merely cosmetic. The two ungated fee reads
    # (GET /fees/groups and GET /fees/) are excluded on purpose — see honesty
    # note 3 above.
    denied_fee_name = f"TEST Unlicensed Fee {run_tag()}"
    denied_group_name = f"TEST Unlicensed Fee Group {run_tag()}"

    refusals = {
        # ── api/routes/fees.py ──
        # What the fees_config "Fees" tab posts, renames and deletes.
        "create_fee": api.post(
            f"/fees/{branch_query}",
            token=token,
            json={
                "name": denied_fee_name,
                "amount": 100,
                "academic_year_id": 1,
                "academic_term_id": 1,
                "school_branch_id": branch_id,
            },
        ),
        "read_fee": api.get(f"/fees/{DENIED_UNREACHABLE_ID}", token=token),
        "update_fee": api.put(
            f"/fees/manage/{DENIED_UNREACHABLE_ID}",
            token=token,
            json={"name": denied_fee_name, "amount": 150},
        ),
        # DELETE /fees/{id} resolves to delete_fee_group — it is declared first.
        "delete_fee_group": api.delete(f"/fees/{DENIED_UNREACHABLE_ID}", token=token),
        # What the "Create fee group" screen posts, and the group editor updates.
        "create_fee_group": api.post(
            f"/fees/group{branch_query}",
            token=token,
            json={"name": denied_group_name, "school_fees_ids": []},
        ),
        "update_fee_group": api.put(
            f"/fees/{DENIED_UNREACHABLE_ID}",
            token=token,
            json={"name": denied_group_name, "school_fees_ids": []},
        ),
        # The three ModuleHeader tiles on /module/fees.
        "fee_statistics": api.get(f"/fees/fee/statistics{branch_query}", token=token),
        # The bulk importer and the three reminder dispatchers.
        "bulk_assign": api.post(
            "/fees/bulk-assign/",
            token=token,
            files={"file": ("fees.csv", b"student_id,amount\n", "text/csv")},
        ),
        "remind_all": api.post(f"/fees/remind{branch_query}", token=token, json={}),
        "remind_selected": api.post(
            f"/fees/remind/selected{branch_query}",
            token=token,
            json={"guardian_ids": [DENIED_UNREACHABLE_ID]},
        ),
        "remind_students": api.post(
            f"/fees/remind/students{branch_query}",
            token=token,
            json={"student_ids": [DENIED_UNREACHABLE_ID]},
        ),
        # ── api/routes/fee_payment.py ──
        # The ledger the /module/fees table is built from.
        "payment_history": api.get(
            f"/fee-payment/history?skip=0&limit=10"
            f"{f'&branch_id={branch_id}' if branch_id else ''}",
            token=token,
        ),
        # PaymentModal's save, and the row menu's delete.
        "create_payment": api.post(
            f"/fee-payment/{branch_query}",
            token=token,
            json={
                "student_id": DENIED_UNREACHABLE_ID,
                "amount_paid": 50,
                "school_branch_id": branch_id,
            },
        ),
        "delete_payment": api.delete(
            f"/fee-payment/{DENIED_UNREACHABLE_ID}", token=token
        ),
        # The arrears half of the same workspace.
        "list_arrears": api.get(
            f"/fee-payment/arrears/student/{DENIED_UNREACHABLE_ID}{branch_query}",
            token=token,
        ),
        "create_arrear": api.post(
            f"/fee-payment/arrears{branch_query}",
            token=token,
            json={
                "student_id": DENIED_UNREACHABLE_ID,
                "original_amount": 100,
                "description": "Must never be created — the pack excludes fees.",
            },
        ),
        "update_arrear": api.put(
            f"/fee-payment/arrears/{DENIED_UNREACHABLE_ID}",
            token=token,
            json={"amount": 10},
        ),
        "pay_arrear": api.post(
            f"/fee-payment/arrears/{DENIED_UNREACHABLE_ID}/pay",
            token=token,
            json={"amount": 10},
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{DENIED_FEES_MODULE!r}, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIED_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a working fee ledger in front of them ──────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Mandatory before the ledger reads anything at all — see honesty note 1.
    BranchesPage(page, frontend_base_url).select_branch(str(branch["name"]))
    _settle_branch_selection(page)

    # Deliberately not goto_module: the response is needed. A redirect still in
    # flight from the previous screen would abort this navigation, and the settle
    # loop below would then read a /auth/no-access this module never caused — a
    # denial test passing for somebody else's denial.
    response = page.goto(
        frontend_base_url.rstrip("/") + f"/module/{DENIED_FEES_ROUTE}"
    )
    assert response is not None and DENIED_FEES_ROUTE in response.url, (
        f"the browser never landed on /module/{DENIED_FEES_ROUTE} — it is at "
        f"{page.url!r} instead. Whatever redirect the assertions below would "
        f"have read came from the previous screen, not from this module."
    )

    surface = _wait_for_settled_fees_surface(page)

    if surface == "redirected":
        # The strongest denial the app can give: the interceptor recognised the
        # plan restriction and took the browser off the module entirely.
        expect(page.get_by_text(as_pattern(DENIED_ACCESS_RESTRICTED))).to_be_visible(
            timeout=15_000
        )
        expect(page.get_by_text(as_pattern(DENIED_ACTIVATION_REQUIRED))).to_be_visible()
        expect(
            page.get_by_role("heading", name=as_pattern(DENIED_FEES_HEADING))
        ).to_have_count(0)
        expect(page.get_by_placeholder(as_pattern(DENIED_FEES_SEARCH))).to_have_count(0)
        expect(
            page.get_by_role("button", name=as_pattern(DENIED_FEES_CONFIGURE))
        ).to_have_count(0)
        return

    if surface == "page_error":
        # The page's own catch won the race with the redirect. Still a refusal —
        # and stronger than an empty ledger, because PageError renders the
        # backend's own detail rather than a blank table.
        expect(page.get_by_text(as_pattern(DENIED_LOAD_FAILURE))).to_be_visible()
        expect(page.get_by_role("row")).to_have_count(0)
        return

    # The ledger mounted — assert it mounted *empty*, and that no total survived
    # the refused statistics read.
    expect(
        page.get_by_role("heading", name=as_pattern(DENIED_FEES_HEADING))
    ).to_be_visible()
    expect(page.get_by_text(as_pattern(DENIED_LEDGER_EMPTY))).to_be_visible()
    expect(page.get_by_role("row")).to_have_count(0)
    for tile in DENIED_STAT_TILES:
        # ModuleHeader renders "<dt>{name}</dt><dd>{stat}</dd>", so a tile's
        # value is its label's next sibling. Asserted on the <dd> rather than on
        # the card, whose "0% vs last year" delta would satisfy a looser match
        # even if the total itself were non-zero.
        value = page.get_by_text(
            as_pattern(rf"^\s*{re.escape(tile)}\s*$")
        ).first.locator("xpath=following-sibling::dd[1]")
        expect(value).to_have_text(re.compile(r"^\s*0\s*$"))


def _settle_branch_selection(page: Page, timeout_ms: int = 20_000) -> None:
    """Let the branch row's side-effect navigation finish before moving on.

    ``BranchesPage.select_branch`` lands on ``/module/community`` — and in the
    ``minimal`` scenario *community* is unlicensed too, so that screen fires its
    own refused fetch and the interceptor bounces the browser to
    ``/auth/no-access``. Navigating away while that bounce is still in flight
    would abort the next ``page.goto`` and hand this test a redirect it did not
    cause. Waiting for it to land first means the only redirect the assertions
    can see is the one *this* module provoked.

    Returns quietly if it never comes: a scenario that does license community
    simply stays put, and there is then nothing in flight to steal anything.
    """
    remaining = timeout_ms
    step = 250
    while remaining > 0 and not DENIED_NO_ACCESS_URL.search(page.url):
        page.wait_for_timeout(step)
        remaining -= step


def _wait_for_settled_fees_surface(
    page: Page, timeout_ms: int = DENIED_SETTLE_TIMEOUT_MS
) -> str:
    """Wait until /module/fees has stopped loading.

    Returns which of the three surfaces it settled on — ``"redirected"``,
    ``"page_error"`` or ``"empty_ledger"``. Waiting for one of them first is what
    stops the "no fee rows" assertions from passing merely because
    ``StudentFeeHistoryLoader`` was still on screen.
    """
    failure = page.get_by_text(as_pattern(DENIED_LOAD_FAILURE)).first
    empty = page.get_by_text(as_pattern(DENIED_LEDGER_EMPTY)).first

    remaining = timeout_ms
    step = 500
    while remaining > 0:
        if DENIED_NO_ACCESS_URL.search(page.url):
            return "redirected"
        if failure.count() > 0:
            return "page_error"
        if empty.count() > 0:
            return "empty_ledger"
        page.wait_for_timeout(step)
        remaining -= step

    raise AssertionError(
        "/module/fees neither redirected to a no-access page, nor rendered its "
        "load-failure panel, nor settled on the empty ledger within "
        f"{timeout_ms}ms — current url {page.url!r}. If the ledger listed "
        "students and their fees instead, the feature-pack gate is not being "
        "enforced for this school."
    )


# ═════════════════════ account.fees.manage.accountant ═══════════════════════
#
# The write half of the module, driven by the role it exists for: the Accountant
# of the ``finance_only`` school adds a line item to what the school charges and
# then corrects it.
#
# Why the Accountant could not do this until the seed was fixed
#     ``Accountant`` is a first-class role — ``app.py``'s ``lifespan`` creates it
#     on every boot and the non-teaching staff wizard offers it in its "Non
#     teaching Staff Role" dropdown, which is how provisioning's accountant gets
#     it — but ``db/repository/permissions.py`` had no ``"Accountant"`` key in
#     ``role_permissions`` at all, so the role was seeded with *zero*
#     permissions. Every accountant in the product therefore logged in to an
#     empty application: the sidebar's Account section failed its
#     ``permissionsGate``, ``usePermissionGuard("fees")`` rendered nothing at
#     /module/fees, and ``has_permission("manage", "fees")`` answered 403 to
#     every write. The role the finance module is named after could not open the
#     finance module.
#
#     That seed is fixed in place (``newschoolapp`` is left dirty; see
#     ``state/backend_patches.md``), and this test is one of the two guards on
#     the fix — it fails at step two, with no Fee Management link to click, if
#     the seed regresses. ``test_accountant_creates_and_manages_income`` is the
#     other.
#
# Where "manage" actually lives on this screen
#     Not in whether the controls are rendered. "Create Fee" and the row menu's
#     "Edit" are offered to *every* role that can see the tab; what changes is
#     what they open. ``handleCreateClick``/``handleEdit`` branch on
#     ``usePermission("fees", "manage")`` and hand anyone without it
#     ``FeeChangeRequestModal`` — a request for somebody else to make the change
#     — instead of the editable modal. The destructive row item switches too:
#     "Delete" for a manager, "Request Delete" for everyone else.
#
#     So the assertions that this accountant *manages* fees rather than petitions
#     about them are the modal titles ("Create New Fee", "Edit Fee") and the row
#     menu offering Delete rather than Request Delete — not the presence of the
#     buttons.
#
# No branch to select, unlike the SchoolAdmin unit above
#     An Accountant is a branch user: ``create_fee`` and ``list_fees`` both
#     overwrite the ``branch_id`` query parameter with ``user.school_branch_id``
#     for anyone who is not a SuperAdmin or SchoolAdmin, and the sidebar's
#     ``branchOnly`` flags are explicitly SchoolAdmin-only. The Account menu is
#     therefore on screen straight after login, and every fee written here is
#     scoped to the campus the accountant belongs to without anything being
#     chosen first.
#
# Where the fee is read back from
#     ``handleCreate`` appends the API's response to local state, so the row that
#     appears immediately after saving proves only that the POST was accepted.
#     The last step reloads the register, which refetches ``GET /fees/`` — that
#     is the step that proves the corrected figure is what the school will
#     actually bill.

MANAGE_FEES_MODULE = "fees"
MANAGE_FEES_SCENARIO = "finance_only"
MANAGE_ACCOUNTANT_ROLE = "Accountant"

# Everything this unit creates carries the "TEST" prefix the orphan sweeper
# matches on, plus the run tag so parallel agents never collide — and so it can
# never be confused with the fees the view unit above seeds on the same school.
MANAGE_TAG = run_tag()
MANAGE_FEE_NAME = f"TEST Sports Levy {MANAGE_TAG}"
MANAGE_FEE_DESCRIPTION = "Inter-house athletics: kit, officials and travel"
MANAGE_FEE_AMOUNT = 120

MANAGE_REVISED_AMOUNT = 145
MANAGE_REVISED_DESCRIPTION = (
    "Inter-house athletics: kit, officials and travel to the regional finals"
)

# The Amount column prints the Decimal exactly as the API serialised it, which is
# "120.0" for a Float column today but need not stay that precise.
MANAGE_AMOUNT_CELL = rf"^\s*{MANAGE_FEE_AMOUNT}(?:\.\d+)?\s*$"
MANAGE_REVISED_AMOUNT_CELL = rf"^\s*{MANAGE_REVISED_AMOUNT}(?:\.\d+)?\s*$"


@pytest.mark.accountant
@pytest.mark.scenario(MANAGE_FEES_SCENARIO)
@pytest.mark.demo(
    feature_id="account.fees.manage.accountant",
    title="Fees",
    subtitle="Accountant creates and manages fees",
)
def test_accountant_creates_and_manages_fees(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """An accountant adds a levy to the school's fee structure, then corrects it."""
    ctx = provisioned_school
    assert ctx.accountant is not None, (
        "provisioning created no accountant for this school — phase C creates "
        "one from the non-teaching staff form, which needs the `staff` module"
    )
    assert MANAGE_FEES_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {MANAGE_FEES_MODULE!r} for "
        f"this unit — an accountant refused the module has no fees to manage"
    )
    assert ctx.academic_year and ctx.current_term, (
        "a fee is billed against an academic year and term, and both selects in "
        "the Create Fee modal are required — provisioning phase B creates them, "
        "so an empty SchoolContext.academic_year/current_term means this school "
        "has no calendar to bill against"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    accountant = ctx.accountant
    fees_page = FeesPage(page, base_url)

    with demo.step(
        f"Sign in as {accountant.full_name}, who keeps the books at "
        f"{ctx.school_name}"
    ):
        login_as(page, base_url, accountant)

    with demo.step("Fee Management is waiting in their Account menu"):
        fees_page.expect_nav_entry()
        fees_page.open_from_sidebar()
        fees_page.expect_no_load_failure()
        fees_page.expect_stats()

    with demo.step("Configure Fees is where the school sets what it charges"):
        config = fees_page.open_fee_configuration()
        config.open_fees_tab()
        config.expect_fee_headers()
        config.wait_for_fees()

    with demo.step(
        f"Add a sports levy, billed for {ctx.current_term} of {ctx.academic_year}"
    ):
        # The editable modal, not FeeChangeRequestModal: this accountant writes
        # the fee themselves rather than asking somebody else to.
        modal = config.open_create_fee_modal()
        config.fill_fee_form(
            modal,
            name=MANAGE_FEE_NAME,
            amount=MANAGE_FEE_AMOUNT,
            description=MANAGE_FEE_DESCRIPTION,
            academic_year=ctx.academic_year,
            academic_term=ctx.current_term,
        )

    with demo.step("Save it — the levy joins the school's fee structure",
                   dwell_ms=1500):
        config.submit_fee_create(modal)
        config.search_fees(MANAGE_FEE_NAME)
        config.expect_fee(
            MANAGE_FEE_NAME,
            amount=MANAGE_AMOUNT_CELL,
            description=MANAGE_FEE_DESCRIPTION,
            academic_year=ctx.academic_year,
            academic_term=ctx.current_term,
        )

    with demo.step("Their row menu edits the fee outright — no change request "
                   "to file"):
        config.open_fee_row_menu(MANAGE_FEE_NAME)
        expect(
            page.get_by_role("menuitem", name=as_pattern(EDIT_FEE_ITEM))
        ).to_be_visible(timeout=15_000)
        # The manage/read fork made visible: a role without ("manage", "fees")
        # is offered "Request Delete" here instead.
        expect(
            page.get_by_role("menuitem", name=as_pattern(DELETE_FEE_ITEM))
        ).to_be_visible()
        expect(
            page.get_by_role("menuitem", name=as_pattern(REQUEST_DELETE_ITEM))
        ).to_have_count(0)
        config.close_fee_row_menu()

    with demo.step("The regional finals push the levy up — correct it in place",
                   dwell_ms=1500):
        config.edit_fee(
            name=MANAGE_FEE_NAME,
            amount=MANAGE_REVISED_AMOUNT,
            description=MANAGE_REVISED_DESCRIPTION,
        )

    with demo.step("Reload the register: the revised levy is what the school "
                   "will bill", dwell_ms=2500):
        # Saving only appends the API's answer to local state, so this refetch is
        # what proves the correction was persisted rather than merely posted.
        page.reload()
        config.expect_loaded()
        config.open_fees_tab()
        config.wait_for_fees()
        config.search_fees(MANAGE_FEE_NAME)
        config.expect_fee(
            MANAGE_FEE_NAME,
            amount=MANAGE_REVISED_AMOUNT_CELL,
            description=MANAGE_REVISED_DESCRIPTION,
            academic_year=ctx.academic_year,
            academic_term=ctx.current_term,
        )
