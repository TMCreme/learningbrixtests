"""Change requests — the approval workflow a read-only role uses to ask for a
change they cannot make themselves, and the log they track it in.

The module has two screens, and which one you get is the whole point
    ``/module/change_request`` is "My Change Requests": everything *you* have
    asked for, and what became of it. ``/module/pending_requests`` is the
    approver's queue. ``SideNavigation.canShowItem`` hides the second from anyone
    whose role holds only ``read change_requests``
    (``isChangeRequestManage``), and the backend agrees — every route on
    ``/pending-changes`` that decides anything is behind
    ``has_permission("manage", "change_requests")``. A Teacher is granted
    ``("read", "change_requests")`` and nothing more
    (``db/repository/permissions.py``), so this unit is the requester's half of
    the workflow: raise elsewhere, track here, decide never.

Why the requests are seeded over the API
    Nothing on this screen authors a request, and nothing a *teacher* can reach
    does either: the only "Request Change" modals in the frontend live under
    ``/module/fees`` and ``/module/income_and_expenses``, neither of which the
    ``library_and_community`` pack licenses and neither of which a teaching role
    may open. The workflow's model registry is finance-only too
    (``PendingChangeService.MODEL_REGISTRY``), so an ``Income`` create is the
    honest shape of a request whatever role files it —
    ``POST /pending-changes/request`` is deliberately gated on *read*, precisely
    so a user without manage rights can ask.

    So the two requests below are seeded the same setup-only way
    ``school_provisioning._seed_fee_group`` seeds the fee group the Add Class
    dialog insists on: over HTTP, before the camera rolls, as the very teacher
    whose log they will appear in (``my-requests`` filters on ``requested_by``).
    One is left pending; the other is rejected by the SchoolAdmin so the log has
    both a still-open request and a decided one to show. Rejection is used rather
    than approval on purpose — approving *applies* the change, which would write a
    real Income row into a school whose pack does not even include the module.

What the walkthrough proves
    Every value asserted was stored server-side and handed back by
    ``GET /pending-changes/my-requests``: the request ids, the module and model
    each was filed against, the status each is now in, the summary and requested
    values inside the detail modal, and the reviewer's remarks on the rejected
    one. None of it could have been produced by the browser on its own.

The approver's half: a SchoolAdmin working the queue
    ``test_school_admin_approves_and_rejects_change_requests`` drives
    ``/module/pending_requests``, the only screen in the app that *decides*
    anything. Two requests are filed over the API by the school's accountant —
    the role that holds ``read change_requests`` and would really raise them —
    and the administrator then approves one and refuses the other through the row
    menu's antd modals.

    They are ``SchoolFee`` creates rather than the ``Income`` creates the
    requester path uses, because an approval **applies** the change: it runs the
    stored payload through ``SchoolFeeService`` for real. A fee needs only the
    branch's academic year and term (both provisioned, both licensed here), while
    an income needs an ``IncomeType`` row this school has no licensed way to
    create — so the fee is the one shape whose approval can actually land. That
    it landed is asserted at the end, by reading the new fee back out of
    ``GET /fees/``: approving is not a status change, and this unit refuses to
    prove only half of it.

    Two preconditions worth naming. The queue is branch-scoped
    (``GetPendingChangesHandler`` appends ``branch_id`` from ``useBranchStore``,
    and the backend's ``branch_id_required`` refuses a SchoolAdmin request that
    carries none), so ``BranchesPage.select_branch`` comes first — without it the
    "Change Request Module" group is not even in the sidebar, since it is
    ``branchOnly``. And ``approve_change``/``reject_change`` each check manage
    rights on the request's own ``module_name`` on top of the route's own gate;
    the seeded SchoolAdmin role holds ``("manage", "fees")``, which is what makes
    them the right approver for a fee request.

    The queue is deliberately never asserted to be *empty* afterwards: the whole
    batch shares one provisioned school, and the requester walkthrough above
    leaves a request of its own pending in the same branch. Only the two rows
    this unit seeded are asserted present, then gone.

A backend defect this unit uncovered (fixed in place, newschoolapp is dirty)
    ``PendingChangeService._apply_school_fee_change`` called
    ``SchoolFeeService.create_fee(fee_data, approver, branch_id)`` and
    ``update_fee(record_id, fee_data, approver)``, but neither service method
    takes an approver — so every approval of a ``SchoolFee`` request raised
    ``TypeError`` inside ``approve_pending_change``, which the route turned into a
    flat 400. The calls now match the signatures, and this test is what holds
    that shut.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI, Credentials
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern
from tests.pages.change_requests.change_request import (
    STATUS_ALL,
    STATUS_REJECTED,
    ChangeRequestsPage,
)
from tests.pages.change_requests.pending_requests import (
    ALL_PENDING_TAB,
    EMPTY_TITLE as PENDING_EMPTY_TITLE,
    HEADING as PENDING_HEADING,
    LOAD_FAILURE as PENDING_LOAD_FAILURE,
    PendingRequestsPage,
)
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

CHANGE_REQUESTS_SCENARIO = "library_and_community"

# The only shape the approval workflow accepts today: its model registry is
# finance-only, and module_name is the free-text key the *approver's* permissions
# are later checked against (api/routes/pending_changes.py::reject_change).
REQUEST_MODULE = "incomes_and_expenses"
REQUEST_MODEL = "Income"
REQUEST_ACTION = "create"

# Named with the "TEST" prefix the orphan sweeper matches on. The description is
# what the detail modal renders verbatim under "New Values (Requested)" — the
# amount is stored as a number and reformatted by the browser, so the string is
# the reliable thing to assert on.
OPEN_SUMMARY = "TEST Reimburse the Year 6 field trip float"
OPEN_DESCRIPTION = "TEST Year 6 field trip float"
OPEN_AMOUNT = 250

DECIDED_SUMMARY = "TEST Record the book fair takings for the library"
DECIDED_DESCRIPTION = "TEST Book fair takings"
DECIDED_AMOUNT = 480

# The reject route requires a reason of at least 10 characters.
REJECTION_REMARKS = "TEST Already recorded by the bursar on the day of the fair."

# Statuses as the badges render them (page.tsx::getStatusBadge).
BADGE_PENDING = "Pending"
BADGE_REJECTED = "Rejected"

# An income type is never resolved while a request is only pending — the payload
# is validated against IncomeCreate and stored as JSON, and nothing dereferences
# this until an approval applies it, which this unit deliberately never does.
PLACEHOLDER_INCOME_TYPE_ID = 1


class ChangeRequestSeedError(RuntimeError):
    """A request could not be seeded, so the log would render empty."""


@dataclass
class SeededRequests:
    """The two requests the teacher is expected to find in their log."""

    open_id: int
    decided_id: int


@pytest.fixture
def teacher_change_requests(
    provisioned_school: SchoolContext, api: BackendAPI
) -> SeededRequests:
    """File two change requests as the teacher, and have one of them rejected.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.

    Idempotent by change summary: the whole batch shares one provisioned school,
    and a second copy of either request would make the log ambiguous to assert on.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.branches, "provisioning created no branch for this school"

    branch_id = int(ctx.branches[0]["id"])
    teacher_token = _seed_login(api, ctx.teacher)

    open_id = _seed_request(
        api,
        teacher_token,
        summary=OPEN_SUMMARY,
        description=OPEN_DESCRIPTION,
        amount=OPEN_AMOUNT,
        branch_id=branch_id,
    )
    decided_id = _seed_request(
        api,
        teacher_token,
        summary=DECIDED_SUMMARY,
        description=DECIDED_DESCRIPTION,
        amount=DECIDED_AMOUNT,
        branch_id=branch_id,
    )

    _reject(api, ctx, request_id=decided_id, teacher_token=teacher_token)

    return SeededRequests(open_id=open_id, decided_id=decided_id)


@pytest.mark.teacher
@pytest.mark.scenario(CHANGE_REQUESTS_SCENARIO)
@pytest.mark.demo(
    feature_id="change_requests.change_requests.view.teacher",
    title="Change Requests",
    subtitle="Teacher views change requests",
)
def test_teacher_views_their_change_requests(
    teacher_change_requests: SeededRequests,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A teacher signs in and tracks the changes they have asked for.

    The log is theirs alone — ``my-requests`` filters on ``requested_by`` — and it
    is read-only in the sense that matters: the screen offers no way to raise a
    request and no way to decide one, only to follow what happens to the ones
    already filed.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"

    page: Page = demo.page
    requests_page = ChangeRequestsPage(page, demo.frontend_base_url)
    seeded = teacher_change_requests
    teacher = ctx.teacher

    with demo.step(f"Sign in as {teacher.full_name}, a teacher at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, teacher)
        expect(
            page.get_by_text(as_pattern(re.escape(teacher.email))).first
        ).to_be_visible(timeout=30_000)

    with demo.step("Their menu offers Change Request — but not the approvers' queue"):
        requests_page.expect_nav_entry()
        requests_page.expect_approver_queue_absent()

    with demo.step("Open it to see every change they have asked for"):
        requests_page.open_from_sidebar().wait_for_table()
        requests_page.expect_loaded()
        requests_page.expect_no_load_failure()
        requests_page.expect_headers()

    with demo.step("Two requests, and the state each one is in"):
        requests_page.expect_request(
            seeded.open_id,
            module=REQUEST_MODULE,
            model=REQUEST_MODEL,
            action=REQUEST_ACTION,
            status=BADGE_PENDING,
        )
        requests_page.expect_request(
            seeded.decided_id,
            module=REQUEST_MODULE,
            model=REQUEST_MODEL,
            action=REQUEST_ACTION,
            status=BADGE_REJECTED,
        )
        # Only a request nobody has ruled on yet may still be withdrawn.
        requests_page.expect_withdraw_offered(seeded.open_id)
        requests_page.expect_withdraw_offered(seeded.decided_id, offered=False)

    with demo.step("The one still waiting spells out exactly what was asked for"):
        requests_page.open_details(seeded.open_id)
        requests_page.expect_details(
            seeded.open_id,
            module=REQUEST_MODULE,
            change_summary=OPEN_SUMMARY,
            new_value_text=OPEN_DESCRIPTION,
            # A "create" request has no before-picture to compare against.
            old_values_empty=True,
        )
        requests_page.close_details()

    with demo.step("Narrow the log down to what was turned down"):
        requests_page.filter_by_status(STATUS_REJECTED)
        requests_page.expect_request(seeded.decided_id, status=BADGE_REJECTED)
        requests_page.expect_request_absent(seeded.open_id)

    with demo.step("And the reviewer's reason is recorded against it"):
        requests_page.open_details(seeded.decided_id)
        requests_page.expect_details(
            seeded.decided_id,
            module=REQUEST_MODULE,
            change_summary=DECIDED_SUMMARY,
            new_value_text=DECIDED_DESCRIPTION,
        )
        requests_page.expect_review_outcome(REJECTION_REMARKS)
        requests_page.close_details()

    with demo.step("Back to the full log — a teacher tracks requests here, "
                   "never raises or rules on them", dwell_ms=1500):
        requests_page.filter_by_status(STATUS_ALL)
        requests_page.expect_request(seeded.open_id, status=BADGE_PENDING)
        requests_page.expect_request(seeded.decided_id, status=BADGE_REJECTED)
        requests_page.expect_no_authoring_controls()
        requests_page.expect_approver_queue_absent()


# ──────────── setup-only seeding for this unit (never asserted) ──────────────


def _seed_login(api: BackendAPI, creds: Credentials) -> str:
    try:
        return str(api.login(creds.email, creds.password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise ChangeRequestSeedError(
            f"could not log in as {creds.email}: {exc}"
        ) from exc


def _my_requests(api: BackendAPI, token: str) -> list[dict]:
    response = api.get("/pending-changes/my-requests?limit=100", token=token)
    if response.status_code >= 400:
        raise ChangeRequestSeedError(
            f"could not read the requester's own change requests: "
            f"{response.status_code} {response.text[:300]}"
        )
    items = response.json().get("items") or []
    return [row for row in items if isinstance(row, dict)]


def _existing(api: BackendAPI, token: str, *, summary: str) -> dict | None:
    """Reuse a request an earlier test in this scenario already filed."""
    wanted = re.compile(rf"^\s*{re.escape(summary)}\s*$", re.I)
    for row in _my_requests(api, token):
        if wanted.match(str(row.get("change_summary") or "")):
            return row
    return None


def _seed_request(
    api: BackendAPI,
    token: str,
    *,
    summary: str,
    description: str,
    amount: int,
    branch_id: int,
) -> int:
    """One change request, filed by the teacher themselves.

    ``POST /pending-changes/request`` is gated on ``read change_requests``
    precisely so a role without manage rights can ask for a change — which is why
    the teacher's own token files it, and why the row then belongs to their log.
    """
    found = _existing(api, token, summary=summary)
    if found is not None:
        return int(found["id"])

    response = api.post(
        "/pending-changes/request",
        token=token,
        json={
            "model_name": REQUEST_MODEL,
            "module_name": REQUEST_MODULE,
            "action": REQUEST_ACTION,
            # A create request names no existing record; the backend rejects one
            # that does ("CREATE action should not have a record_id").
            "record_id": None,
            "new_values": {
                "amount": amount,
                "description": description,
                "income_type_id": PLACEHOLDER_INCOME_TYPE_ID,
                "school_branch_id": branch_id,
            },
            "change_summary": summary,
            "branch_id": branch_id,
        },
    )
    if response.status_code >= 400:
        raise ChangeRequestSeedError(
            f"could not file the change request {summary!r}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return int(response.json()["id"])


def _reject(
    api: BackendAPI,
    ctx: SchoolContext,
    *,
    request_id: int,
    teacher_token: str,
) -> None:
    """Have the SchoolAdmin turn one request down, so the log shows a verdict.

    Rejected rather than approved on purpose: approving *applies* the change,
    which would write a real Income row into a school whose feature pack does not
    include that module. Rejection only records the outcome.

    ``reject_change`` needs manage rights on ``change_requests`` (which the
    seeded SchoolAdmin role holds) *and* on the request's own ``module_name``
    (likewise) — see ``api/routes/pending_changes.py``.
    """
    already = _existing(api, teacher_token, summary=DECIDED_SUMMARY)
    if already is not None and str(already.get("status")) == "rejected":
        return

    admin_token = _seed_login(api, ctx.school_admin)
    response = api.patch(
        f"/pending-changes/{request_id}/reject",
        token=admin_token,
        params={"remarks": REJECTION_REMARKS},
    )
    if response.status_code >= 400:
        raise ChangeRequestSeedError(
            f"the SchoolAdmin could not reject change request {request_id}: "
            f"{response.status_code} {response.text[:300]}"
        )


# ════════════ approver path: a SchoolAdmin works the pending queue ═══════════
#
# Constants below are prefixed rather than sharing the requester section's
# names: this module file is written one unit at a time, and a shared
# module-level name would silently rebind under whichever section is appended
# last.

# A fee request rather than an income one: approving *applies* the change, and a
# SchoolFee needs only the branch's academic year and term, both of which this
# school has. See the module docstring.
QUEUE_MODULE = "fees"
QUEUE_MODEL = "SchoolFee"
QUEUE_ACTION = "create"

# Both fees carry the "TEST" prefix the orphan sweeper matches on. The approved
# one is read back out of GET /fees/ at the end — that read is what proves the
# approval did more than flip a status.
APPROVED_SUMMARY = "TEST Add the termly library levy to the fee schedule"
APPROVED_FEE_NAME = "TEST Termly Library Levy"
APPROVED_FEE_AMOUNT = 60
APPROVED_FEE_DESCRIPTION = "Borrowing rights for the term"

REFUSED_SUMMARY = "TEST Add a weekend excursion charge to the fee schedule"
REFUSED_FEE_NAME = "TEST Weekend Excursion Charge"
REFUSED_FEE_AMOUNT = 120
REFUSED_FEE_DESCRIPTION = "Coach hire and entry for a weekend excursion"

# Both remarks travel as a ``remarks`` query param that the frontend
# interpolates straight into the URL (changeRequestHandler.ts), so they stay to
# letters, spaces, commas and full stops. The reject route additionally declares
# ``min_length=10``.
APPROVAL_REMARKS = "TEST Agreed at the last board meeting. Bill it this term."
REFUSAL_REMARKS = "TEST Excursions are billed per trip, not on the termly schedule."

# Statuses as GET /pending-changes/my-requests reports them.
STATUS_VALUE_PENDING = "pending"
STATUS_VALUE_APPROVED = "approved"
STATUS_VALUE_REJECTED = "rejected"


@dataclass
class QueuedRequests:
    """The two requests waiting in the administrator's queue."""

    approved_id: int
    refused_id: int
    branch_id: int
    branch_name: str


@pytest.fixture
def queued_fee_requests(
    provisioned_school: SchoolContext, api: BackendAPI
) -> QueuedRequests:
    """Have the school's accountant ask for two fees to be added.

    Filed over the API, before the camera rolls, as the *bursar* rather than as
    the administrator: ``POST /pending-changes/request`` is gated on ``read
    change_requests`` precisely so a role that cannot make a change itself can
    ask for one, and the Accountant role holds exactly that
    (``db/repository/permissions.py``). The frontend's own "Request Change"
    modals live under ``/module/fees`` and ``/module/income_and_expenses``,
    neither of which the ``library_and_community`` pack licenses — so the API is
    the only way to put anything in this queue at this school.

    Idempotent by change summary, since the whole batch shares one provisioned
    school; a request that has already been decided is a hard error rather than
    something to reuse, because this unit is the thing that decides them.
    """
    ctx = provisioned_school
    assert ctx.accountant is not None, (
        "provisioning created no accountant for this school, so nobody without "
        "manage rights is here to raise a change request"
    )
    assert ctx.branches, "provisioning created no branch for this school"

    branch = ctx.branches[0]
    branch_id = int(branch.get("id") or -1)
    if branch_id <= 0:
        raise ChangeRequestSeedError(
            "provisioning captured no branch id. The approver's queue is "
            "branch-scoped on both sides — the frontend appends branch_id from "
            "useBranchStore and the backend refuses a SchoolAdmin request "
            "without one — so nothing could be queued or listed."
        )

    admin_token = _seed_login(api, ctx.school_admin)
    year_id, term_id = _active_year_and_term(
        api, admin_token, school_id=ctx.school_id
    )

    bursar_token = _seed_login(api, ctx.accountant)
    approved_id = _seed_fee_request(
        api,
        bursar_token,
        summary=APPROVED_SUMMARY,
        fee_name=APPROVED_FEE_NAME,
        amount=APPROVED_FEE_AMOUNT,
        description=APPROVED_FEE_DESCRIPTION,
        branch_id=branch_id,
        year_id=year_id,
        term_id=term_id,
    )
    refused_id = _seed_fee_request(
        api,
        bursar_token,
        summary=REFUSED_SUMMARY,
        fee_name=REFUSED_FEE_NAME,
        amount=REFUSED_FEE_AMOUNT,
        description=REFUSED_FEE_DESCRIPTION,
        branch_id=branch_id,
        year_id=year_id,
        term_id=term_id,
    )

    return QueuedRequests(
        approved_id=approved_id,
        refused_id=refused_id,
        branch_id=branch_id,
        branch_name=str(branch["name"]),
    )


@pytest.mark.school_admin
@pytest.mark.scenario(CHANGE_REQUESTS_SCENARIO)
@pytest.mark.demo(
    feature_id="change_requests.change_requests.manage.school_admin",
    title="Change Requests",
    subtitle="SchoolAdmin creates and manages change requests",
)
def test_school_admin_approves_and_rejects_change_requests(
    queued_fee_requests: QueuedRequests,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A school administrator works the queue: one request in, one turned down.

    Both halves of "manage" are here. Approving is not a status change — it runs
    the request's stored payload through the fee service, so the closing check
    reads the new fee back out of the branch's fee list. Rejecting records a
    reason against the request and applies nothing, which is checked the same
    way: the refused fee must be nowhere in that list.
    """
    ctx = provisioned_school
    seeded = queued_fee_requests

    page: Page = demo.page
    queue = PendingRequestsPage(page, demo.frontend_base_url)

    with demo.step(f"Sign in as the administrator of {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.school_admin)

    with demo.step(f"Open {seeded.branch_name}, the campus these requests belong to"):
        # Mandatory, not scene-setting: the queue is branch-scoped, and the
        # sidebar's whole "Change Request Module" group is branchOnly.
        BranchesPage(page, demo.frontend_base_url).select_branch(seeded.branch_name)

    with demo.step("Their menu offers the approvers' queue — open Pending Requests"):
        queue.expect_nav_entry()
        queue.open_from_sidebar().wait_for_table()
        queue.expect_loaded()
        queue.expect_no_load_failure()
        queue.expect_tabs()
        queue.expect_headers()

    with demo.step("Two fee changes the bursar has asked for, neither decided yet"):
        queue.expect_request(
            seeded.approved_id,
            module=QUEUE_MODULE,
            model=QUEUE_MODEL,
            action=QUEUE_ACTION,
        )
        queue.expect_request(
            seeded.refused_id,
            module=QUEUE_MODULE,
            model=QUEUE_MODEL,
            action=QUEUE_ACTION,
        )

    with demo.step("Approve the library levy, with a note on why it was allowed"):
        queue.approve(seeded.approved_id, APPROVAL_REMARKS)
        queue.expect_request_absent(seeded.approved_id)
        queue.expect_no_load_failure()

    with demo.step("Turn the excursion charge down, and the reason is kept with it"):
        queue.reject(seeded.refused_id, REFUSAL_REMARKS)
        queue.expect_request_absent(seeded.refused_id)
        queue.expect_no_load_failure()

    with demo.step("Nothing is waiting on the administrator now — and the levy "
                   "the school approved is on its fee schedule", dwell_ms=2000):
        # Not an empty-queue assertion: the whole batch shares this school, and
        # the requester walkthrough leaves a request of its own pending here.
        queue.wait_for_table()
        queue.expect_request_absent(seeded.approved_id)
        queue.expect_request_absent(seeded.refused_id)
        _expect_decisions_applied(api, ctx, seeded)


def _expect_decisions_applied(
    api: BackendAPI, ctx: SchoolContext, seeded: QueuedRequests
) -> None:
    """Both verdicts reached the server, and the approved one was carried out.

    The UI half above only shows rows leaving a queue, which a frontend that
    optimistically dropped them would reproduce exactly. What is asserted here
    is what the server did: the status and remarks it stored against each
    request, and — for the approval — the fee that ``approve_change`` created by
    replaying the request's payload through ``SchoolFeeService``.
    """
    assert ctx.accountant is not None

    bursar_token = _seed_login(api, ctx.accountant)
    filed = {int(row["id"]): row for row in _my_requests(api, bursar_token)}

    approved = filed.get(seeded.approved_id)
    assert approved is not None, (
        f"change request #{seeded.approved_id} is no longer in the bursar's own "
        f"log, so the approval did something other than decide it; the log holds "
        f"{sorted(filed)}"
    )
    assert str(approved.get("status")) == STATUS_VALUE_APPROVED, (
        f"the administrator approved change request #{seeded.approved_id}, so the "
        f"server must hold it as {STATUS_VALUE_APPROVED!r} — got "
        f"{approved.get('status')!r}"
    )
    assert APPROVAL_REMARKS in str(approved.get("remarks") or ""), (
        f"the note typed into the approval modal is what the requester is owed "
        f"as an explanation, and it must be stored against the request — got "
        f"{approved.get('remarks')!r}"
    )

    refused = filed.get(seeded.refused_id)
    assert refused is not None, (
        f"change request #{seeded.refused_id} is missing from the bursar's log; "
        f"it holds {sorted(filed)}"
    )
    assert str(refused.get("status")) == STATUS_VALUE_REJECTED, (
        f"the administrator refused change request #{seeded.refused_id}, so the "
        f"server must hold it as {STATUS_VALUE_REJECTED!r} — got "
        f"{refused.get('status')!r}"
    )
    assert REFUSAL_REMARKS in str(refused.get("remarks") or ""), (
        f"reject_change requires a reason and stores it verbatim — got "
        f"{refused.get('remarks')!r}"
    )

    admin_token = _seed_login(api, ctx.school_admin)
    fees = api.get(
        f"/fees/?branch_id={seeded.branch_id}&skip=0&limit=100", token=admin_token
    )
    assert fees.status_code == 200, (
        f"could not read {seeded.branch_name}'s fee schedule back, so whether the "
        f"approval was applied cannot be told — got {fees.status_code}: "
        f"{fees.text[:300]}"
    )
    charged = {str(row.get("name") or "").strip() for row in fees.json()}
    assert APPROVED_FEE_NAME in charged, (
        f"approving a change request must *apply* it — PendingChangeService."
        f"_apply_school_fee_change replays the payload through SchoolFeeService "
        f"— so {APPROVED_FEE_NAME!r} should now be one of "
        f"{seeded.branch_name}'s fees; got {sorted(charged)}"
    )
    assert REFUSED_FEE_NAME not in charged, (
        f"{REFUSED_FEE_NAME!r} was refused, and a rejection must apply nothing; "
        f"the branch charges {sorted(charged)}"
    )


# ─────── setup-only seeding for the approver path (never asserted) ───────────


def _active_year_and_term(
    api: BackendAPI, token: str, *, school_id: int
) -> tuple[int, int]:
    """The active academic year and term a fee has to be filed under.

    Read the same setup-only way ``school_provisioning._seed_fee_group`` reads
    them; ``FeeCreate`` requires both, and a request whose payload cannot be
    validated is refused at the point it is raised.
    """
    years = api.get(
        f"/academic-year/?skip=0&limit=100&school_id={school_id}", token=token
    )
    if years.status_code >= 400:
        raise ChangeRequestSeedError(
            f"could not read the school's academic years: "
            f"{years.status_code} {years.text[:300]}"
        )
    year_rows = [row for row in years.json() if isinstance(row, dict)]
    if not year_rows:
        raise ChangeRequestSeedError(
            "the school has no academic year, so no fee can be filed against one. "
            "Provisioning phase B creates one when the scenario licenses "
            "academic_year_and_term."
        )
    year = next((row for row in year_rows if row.get("is_active")), year_rows[0])

    terms = api.get(f"/academic-term/by-year/{year['id']}", token=token)
    if terms.status_code >= 400:
        raise ChangeRequestSeedError(
            f"could not read the terms of academic year {year.get('name')!r}: "
            f"{terms.status_code} {terms.text[:300]}"
        )
    term_rows = [row for row in terms.json() if isinstance(row, dict)]
    if not term_rows:
        raise ChangeRequestSeedError(
            f"academic year {year.get('name')!r} has no term, and FeeCreate "
            f"requires one"
        )
    term = next((row for row in term_rows if row.get("is_active")), term_rows[0])

    return int(year["id"]), int(term["id"])


def _seed_fee_request(
    api: BackendAPI,
    token: str,
    *,
    summary: str,
    fee_name: str,
    amount: int,
    description: str,
    branch_id: int,
    year_id: int,
    term_id: int,
) -> int:
    """One "please add this fee" request, filed by whoever holds ``token``.

    ``branch_id`` is what puts the request in that branch's queue —
    ``get_pending_changes_for_approval`` filters on it — and it is repeated
    inside ``new_values`` because ``SchoolFeeService.create_fee`` will read the
    branch off the pending change when the request is eventually applied.
    """
    found = _existing(api, token, summary=summary)
    if found is not None:
        status = str(found.get("status"))
        if status != STATUS_VALUE_PENDING:
            raise ChangeRequestSeedError(
                f"change request {summary!r} has already been {status} in this "
                f"school (#{found.get('id')}). This unit is what decides it, so "
                f"there is nothing left to demonstrate — re-run against a freshly "
                f"provisioned school."
            )
        return int(found["id"])

    response = api.post(
        "/pending-changes/request",
        token=token,
        json={
            "model_name": QUEUE_MODEL,
            "module_name": QUEUE_MODULE,
            "action": QUEUE_ACTION,
            # A create request names no existing record; the backend rejects one
            # that does ("CREATE action should not have a record_id").
            "record_id": None,
            "new_values": {
                "name": fee_name,
                "amount": amount,
                "description": description,
                "academic_year_id": year_id,
                "academic_term_id": term_id,
                "school_branch_id": branch_id,
            },
            "change_summary": summary,
            "branch_id": branch_id,
        },
    )
    if response.status_code >= 400:
        raise ChangeRequestSeedError(
            f"could not file the change request {summary!r}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return int(response.json()["id"])


# ═══════════════ change_requests.change_requests.denied ═════════════════════
#
# The negative path for this module: the SchoolAdmin of the ``minimal`` school,
# whose feature pack licenses only ``school_configuration`` and
# ``school_admin_dashboard``. They hold both permissions the module defines —
# ``read`` and ``manage`` — and are still refused, because their school is not
# licensed for it.
#
# Where the denial actually lives
#     Not in the sidebar, and not in a route guard. ``useModuleGuard`` hands a
#     SchoolAdmin ``hasAccess = true`` before it ever reads the ``schoolModules``
#     cookie, and ``src/middleware.ts`` makes ``!isSchoolAdmin`` a condition of
#     its module redirect — so ``/module/pending_requests`` really does mount for
#     this admin, and ``usePermissionGuard("change_requests")`` lets them through
#     as well, since the seeded SchoolAdmin role holds
#     ``("manage", "change_requests")`` (db/repository/permissions.py).
#
#     What denies them is the feature-pack half of
#     ``utils.permissions.has_permission``: it resolves the caller's school, asks
#     ``FeaturePackService`` for its module list, and answers **403 "Feature not
#     available in your plan"** when the module is missing. Every route on
#     ``api/routes/pending_changes.py`` carries that dependency — the ``read``
#     ones a requester uses and the ``manage`` ones an approver uses alike — and
#     it is solved before the endpoint body runs, which is why the ids and
#     payloads below are deliberately arbitrary. A 400 ``BRANCH_ID_REQUIRED`` or
#     a 404 in place of a 403 would itself be the failure: it would mean the body
#     ran before the licence was consulted.
#
#     The UI consequence follows from it. ``PendingRequests`` asks for both tabs
#     on mount (``GetPendingChangesHandler`` and ``GetMyRequestsHandler``), and
#     the axios response interceptor in ``src/utils/handleErrorMessage.ts``
#     recognises that particular detail (``shouldRedirectToNoAccess``) and
#     performs a hard ``window.location`` redirect to **/auth/no-access**,
#     rejecting with ``FeatureNotAvailableError``. That redirect races the page's
#     own ``catch``, which sets ``pendingError`` and renders the "Failed to load
#     pending requests" ``PageError`` panel — so both surfaces are accepted below.
#
# Two honesty notes about what this test does and does not claim
#     1. The branch is selected first even though nothing here depends on it, and
#        for one reason only: ``GetPendingChangesHandler`` appends ``branch_id``
#        from ``useBranchStore`` for a SchoolAdmin, and without it the queue's own
#        call would be one the backend could refuse with 400
#        ``BRANCH_ID_REQUIRED`` for a reason that has nothing to do with the
#        plan. Selecting it removes that as an explanation for the refusal.
#     2. Deliberately *not* asserted: that the sidebar hides "Pending Requests".
#        ``SideNavigation.canShowItem`` gates that entry on the role's
#        ``manage change_requests`` permission, which this admin holds — so its
#        presence or absence says nothing about the school's pack.
#     3. Deliberately *not* asserted: ``/module/change_request``, the requester's
#        own log. ``nav-config.tsx`` excludes Admin and SchoolAdmin from it
#        outright, so a SchoolAdmin being kept off it would prove a role rule, not
#        a licence one. Its data half — ``GET /pending-changes/my-requests`` — is
#        asserted in the API block below, where the claim belongs.

DENIED_CHANGE_REQUESTS_MODULE = "change_requests"
DENIED_CHANGE_REQUESTS_SCENARIO = "minimal"
DENIED_CHANGE_REQUESTS_ROUTE = "pending_requests"
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

DENIED_SETTLE_TIMEOUT_MS = 40_000


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_CHANGE_REQUESTS_SCENARIO)
def test_change_requests_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `change_requests` off the pack, a SchoolAdmin can neither work the
    approval queue nor file a request of their own."""
    ctx = provisioned_school
    if DENIED_CHANGE_REQUESTS_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables "
            f"{DENIED_CHANGE_REQUESTS_MODULE!r}; the denial path only applies "
            f"when the feature pack omits it"
        )

    assert ctx.branches, (
        "provisioning left this school with no branch, and the approval queue is "
        "branch-scoped — phase B creates one for every scenario"
    )
    branch = ctx.branches[0]
    branch_id = int(branch.get("id") or 0)
    assert branch_id > 0, (
        "provisioning could not capture the branch id, and GET /pending-changes/ "
        "is scoped to one — re-run provisioning rather than guessing it"
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ─────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had change-request rights anyway", which would make the 403s
    # vacuous. Both halves are checked: the queue is gated on ``manage`` and the
    # requester routes on ``read``, so a role holding only one of them would make
    # half the refusals below prove nothing.
    role = api.get(f"/roles/{api.role_id_for(DENIED_SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {DENIED_SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_permissions = {
        (p.get("name"), p.get("module")) for p in role.json().get("permissions", [])
    }
    assert ("manage", DENIED_CHANGE_REQUESTS_MODULE) in role_permissions, (
        f"the seeded {DENIED_SCHOOL_ADMIN_ROLE} role no longer holds "
        f"('manage', {DENIED_CHANGE_REQUESTS_MODULE!r}), so the queue refusals "
        f"below would be a denial the role gets for free. Re-point this test at "
        f"the feature pack only, or fix the seed in "
        f"newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    features_body = features.json()
    assert features_body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{DENIED_CHANGE_REQUESTS_MODULE!r} proves nothing about the gate — an "
        f"unassigned school is unrestricted by design. Provisioning phase A "
        f"assigns one; check that it did."
    )
    assert DENIED_CHANGE_REQUESTS_MODULE not in (features_body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {DENIED_CHANGE_REQUESTS_MODULE!r} "
        f"despite the {ctx.scenario_id!r} pack "
        f"({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every /pending-changes route is refused ────────
    #
    # The approver's half and the requester's half alike, so the gate cannot
    # regress into covering only the screen this admin happens to open.
    refusals = {
        # ── the approver's queue (manage) ──
        "list_queue": api.get(
            f"/pending-changes/?branch_id={branch_id}&skip=0&limit=50", token=token
        ),
        "approve": api.patch(
            f"/pending-changes/{DENIED_UNREACHABLE_ID}/approve"
            f"?remarks=TEST+must+never+be+approved",
            token=token,
        ),
        "reject": api.patch(
            f"/pending-changes/{DENIED_UNREACHABLE_ID}/reject"
            f"?remarks=TEST+must+never+be+rejected",
            token=token,
        ),
        "delete": api.delete(
            f"/pending-changes/{DENIED_UNREACHABLE_ID}", token=token
        ),
        # ── the requester's half (read) ──
        "my_requests": api.get(
            "/pending-changes/my-requests?skip=0&limit=50", token=token
        ),
        "read_request": api.get(
            f"/pending-changes/{DENIED_UNREACHABLE_ID}", token=token
        ),
        "module_names": api.get("/pending-changes/module-names", token=token),
        "model_names": api.get(
            f"/pending-changes/model-names?module={REQUEST_MODULE}", token=token
        ),
        "model_schema": api.get(
            f"/pending-changes/schema/{REQUEST_MODEL}?action={REQUEST_ACTION}",
            token=token,
        ),
        # Filing one. The body is well-formed on purpose: a 422 here would prove
        # nothing about the licence.
        "create_request": api.post(
            "/pending-changes/request",
            token=token,
            json={
                "module_name": REQUEST_MODULE,
                "model_name": REQUEST_MODEL,
                "action": REQUEST_ACTION,
                "change_summary": (
                    "TEST request that must never be filed — the pack excludes "
                    "change_requests."
                ),
                "school_branch_id": branch_id,
                "new_values": {
                    "amount": 100,
                    "description": "TEST unlicensed change request",
                    "income_type_id": PLACEHOLDER_INCOME_TYPE_ID,
                    "school_branch_id": branch_id,
                },
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{DENIED_CHANGE_REQUESTS_MODULE!r}, so the backend must refuse with "
            f"403 — got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIED_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts an approval queue in front of them ─────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Not a data precondition — see honesty note 1 — but it removes the missing
    # branch_id as a competing explanation for what the queue's own call returns.
    BranchesPage(page, frontend_base_url).select_branch(str(branch["name"]))
    _settle_branch_selection(page)

    # The response is checked rather than discarded: a redirect still in flight
    # from the previous screen would abort this navigation, and the settle loop
    # below would then read a /auth/no-access this module never caused — a denial
    # test passing for somebody else's denial.
    response = page.goto(
        frontend_base_url.rstrip("/") + f"/module/{DENIED_CHANGE_REQUESTS_ROUTE}"
    )
    assert response is not None and DENIED_CHANGE_REQUESTS_ROUTE in response.url, (
        f"the browser never landed on /module/{DENIED_CHANGE_REQUESTS_ROUTE} — it "
        f"is at {page.url!r} instead. Whatever redirect the assertions below "
        f"would have read came from the previous screen, not from this module."
    )

    surface = _wait_for_settled_queue_surface(page)

    if surface == "redirected":
        # The strongest denial the app can give: the interceptor recognised the
        # plan restriction and took the browser off the module entirely.
        expect(page.get_by_text(as_pattern(DENIED_ACCESS_RESTRICTED))).to_be_visible(
            timeout=15_000
        )
        expect(page.get_by_text(as_pattern(DENIED_ACTIVATION_REQUIRED))).to_be_visible()
        expect(
            page.get_by_role("heading", name=as_pattern(PENDING_HEADING))
        ).to_have_count(0)
        expect(
            page.get_by_role("button", name=as_pattern(ALL_PENDING_TAB))
        ).to_have_count(0)
        # Not even the queue's own "nothing here yet" copy: an empty queue would
        # say the fetch succeeded and returned nothing, which is not the denial.
        expect(page.get_by_text(as_pattern(PENDING_EMPTY_TITLE))).to_have_count(0)
        return

    # The page's own catch won the race with the redirect. Still a refusal — and
    # stronger than an empty queue, because PageError renders the backend's own
    # detail rather than a blank table.
    expect(page.get_by_text(as_pattern(PENDING_LOAD_FAILURE)).first).to_be_visible()
    expect(page.get_by_text(as_pattern(PENDING_EMPTY_TITLE))).to_have_count(0)


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


def _wait_for_settled_queue_surface(
    page: Page, timeout_ms: int = DENIED_SETTLE_TIMEOUT_MS
) -> str:
    """Wait until /module/pending_requests has stopped loading.

    Returns which of the two refusal surfaces it settled on — ``"redirected"`` or
    ``"page_error"``. Waiting for one of them is what stops the assertions above
    from passing merely because the queue had not finished mounting; reaching the
    timeout means the queue rendered normally, which for an unlicensed school is
    itself the failure.
    """
    failure = page.get_by_text(as_pattern(PENDING_LOAD_FAILURE)).first

    remaining = timeout_ms
    step = 500
    while remaining > 0:
        if DENIED_NO_ACCESS_URL.search(page.url):
            return "redirected"
        if failure.count() > 0:
            return "page_error"
        page.wait_for_timeout(step)
        remaining -= step

    raise AssertionError(
        "/module/pending_requests neither redirected to a no-access page nor "
        f"rendered its load-failure panel within {timeout_ms}ms — current url "
        f"{page.url!r}. If the approval queue mounted instead, the feature-pack "
        "gate is not being enforced for this school."
    )
