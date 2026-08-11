"""Library → Returns & Renewals — the request desk (`requests_and_renewals`).

Where this module lives
    ``/module/requests_and_renewals``
    (``smsfrontend/src/app/module/requests_and_renewals/page.tsx``). The route
    picks a view by role: ``shouldShowAdminView()`` returns true for a role name
    containing "schooladmin", for "admin" holding a manage permission, and for
    anything reading "library"/"librarian", so a SchoolAdmin gets
    ``views/AdminView.tsx`` — the "Manage Requests" desk, three queues behind
    three tabs of one table (Book Requests, Book Returns / Renewals, Overdue
    Books). Every other role, a Student included, gets ``views/StudentView.tsx``:
    their own borrowings, with "Renew" and "Return" and nothing to decide.

Manage path: a SchoolAdmin of the ``library_and_community`` school
(``test_school_admin_works_the_library_request_desk``). That is the whole of
"manage" here — this desk creates nothing of its own. Every row on it was raised
by a *reader*, and the librarian's job is to decide it: hand a physical copy over
with a due date, turn a request down with a reason, or grant someone longer with
a book they already hold. So the walkthrough below decides one of each.

Read-only path: a Student of the same school
(``test_student_reviews_their_library_requests``). ``shouldShowAdminView()``
matches no part of "student", so the same route hands a pupil
``views/StudentView.tsx`` instead — their own borrowing record, read-only, with
every decision already taken for them. See the section comment above that test.

Negative path: a SchoolAdmin of the ``minimal`` school
(``test_requests_and_renewals_denied_for_school_admin_when_module_disabled``) —
the floor pack, which licenses neither ``requests_and_renewals`` nor
``catalogue``. Neither ``src/middleware.ts`` nor ``useModuleGuard`` turns this
role away, so the denial is the backend's: every circulation route is declared
with ``has_permission(<read|manage>, "catalogue")``, and the axios interceptor in
``utils/handleErrorMessage.ts`` turns its 403 into a hard redirect to
/auth/no-access. See the section comment above that test for why ``catalogue`` is
the module key that matters.

Why the queue is seeded over the API
    Raising the rows is the *reader's* screen, not this one: "Request Book" lives
    on ``/module/catalogue``'s reader view and "Renew" on this route's own
    StudentView, both as a different role. Driving those would be two more
    units' subjects walked through inside this one's video. They are seeded the
    same way ``school_provisioning._seed_fee_group`` seeds the fee group the Add
    Class dialog insists on — before the camera rolls, and never asserted.

    The books they are raised against are seeded for the same reason: shelving a
    book is ``library.catalogue.manage``'s walkthrough.

Why the branch is selected first, and why it is not scene-setting
    ``AdminView``'s fetch effect returns early for a SchoolAdmin while
    ``currentSchoolAdminBranch?.branch_id`` is unset::

        if (authUserProfile?.roles?.name?.toLowerCase().includes("schooladmin") …) {
          if (!currentSchoolAdminBranch?.branch_id) return;
        }

    With no branch in the store none of the three GETs is ever issued,
    ``isLoading`` never clears, and the screen sits on
    ``AdminRequestAndRenewalLoader`` forever. The backend agrees from the other
    side: ``list_book_requests`` answers 400 BRANCH_ID_REQUIRED for a SchoolAdmin
    whose request carries no ``branch_id``. ``BranchesPage.select_branch`` is
    what fills that store (see that method for why only the branch row's "View"
    button can), and the sidebar's whole "Library Module" section is
    ``branchOnly`` for this role besides.

Deliberately *not* asserted: the rejection reason on the details dialog
    ``AdminView``'s "Book Request Details" dialog renders a "Rejection Reason"
    panel from ``viewDetailsData.rejection_reason``. The reject *is* recorded —
    ``BookRequestService.handle_book_request`` writes
    ``book_request.rejection_reason`` and ``BookRequest.rejection_reason`` is a
    real column — but ``BookRequestResponse``
    (``api/api_models/book_request.py``) does not carry the field, so neither the
    list nor the by-id read ever hands it back and that panel cannot render for a
    book request. Whether the response should expose it is a product question,
    not a defect this unit may decide, so the test asserts only what the app
    does implement: the request's status, the manager recorded against it, and
    the row's decision menu closing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.api_client import Credentials as BaseCredentials
from tests.fixtures.data_factories import TEST_PREFIX, run_tag
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.library.requests_and_renewals import (
    DAYS_LEFT,
    NO_COPY_ASSIGNED,
    UNSPECIFIED_RETURN_DATE,
    StudentRequestsAndRenewalsPage,
)
from tests.pages.library.requests_and_renewals_admin import (
    APPROVE_ITEM,
    APPROVE_RENEWAL_ITEM,
    DESK_HEADING,
    DESK_SUBHEADING,
    NO_OVERDUE,
    NO_REQUESTS,
    NO_RETURN_REQUESTS,
    READER_SUBHEADING,
    REJECT_ITEM,
    REJECT_RENEWAL_ITEM,
    RENEWAL_COLUMNS,
    REQUEST_COLUMNS,
    SEARCH_PLACEHOLDER,
    TAB_BOOK_REQUESTS,
    TAB_OVERDUE,
    TAB_RETURNS_RENEWALS,
    VIEW_DETAILS_ITEM,
    RequestDeskPage,
)
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

DESK_SCENARIO = "library_and_community"
DESK_TAG = run_tag()

# One genre for the three seeded books. Named per run so nothing this test reads
# can have been left behind by another.
DESK_CATEGORY = f"{TEST_PREFIX} Set Texts {DESK_TAG}"
DESK_SHELF = "Shelf B-1"

# The three books, one per decision the walkthrough makes.
GRANTED_BOOK = f"{TEST_PREFIX} The Lion and the Jewel {DESK_TAG}"
REFUSED_BOOK = f"{TEST_PREFIX} Things Fall Apart {DESK_TAG}"
RENEWED_BOOK = f"{TEST_PREFIX} A Brief History of Time {DESK_TAG}"

DESK_AUTHORS = {
    GRANTED_BOOK: "Wole Soyinka",
    REFUSED_BOOK: "Chinua Achebe",
    RENEWED_BOOK: "Stephen Hawking",
}
DESK_ISBNS = {
    GRANTED_BOOK: "9780199110339",
    REFUSED_BOOK: "9780385474542",
    RENEWED_BOOK: "9780553380163",
}

# Dates the librarian sets on camera. Both pickers refuse the past — the approve
# dialog's disabledDate rules out anything at or before the end of today, the
# re-assign dialog's anything before the start of it — so both are comfortably
# ahead, and far enough apart that the renewal cannot be confused with the
# checkout it replaced.
DESK_TODAY = date.today()
GRANTED_RETURN_DATE = (DESK_TODAY + timedelta(days=14)).isoformat()
RENEWED_RETURN_DATE = (DESK_TODAY + timedelta(days=21)).isoformat()

# Seeded, not typed: the loan the reader then asks to extend.
SEEDED_LOAN_DAYS = 7

# The reader's own words on the renewal, shown read-only in the re-assign dialog.
RENEWAL_COMMENT = (
    "TEST I am still working through the chapter on time and need another week."
)
# The librarian's reason for turning a request down. Digit-free on purpose: the
# textarea strips every numeral as it is typed (AdminView's onChange), so a
# reason with a date or a shelf number in it would not survive the round trip.
REFUSAL_REASON = (
    "TEST Every copy is on loan to the exam class this term. Please try next term."
)

# Statuses as the API reports them, and as the table's badge renders them.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class RequestDeskSeedError(RuntimeError):
    """A prerequisite could not be seeded, so the desk would open empty."""


@dataclass(frozen=True)
class DeskQueue:
    """What is waiting on the librarian when the video starts."""

    branch_id: int
    branch_name: str
    student_name: str
    # Only the given name. The SchoolAdmin is created from the school-creation
    # form, whose names go in unsanitised, and every name input in this app
    # silently drops anything outside /[A-Za-z\s]/ — so a faker surname like
    # "O'Brien" is stored as "OBrien" and a full-name match would miss. The
    # authoritative identity check is the manager's *email*, asserted over the
    # API in ``_desk_expect_decisions_applied``.
    librarian_first_name: str
    granted_copy_name: str
    granted_request_id: int
    refused_request_id: int
    renewal_book_request_id: int
    renewal_request_id: int
    # The due date the seeded loan carried, exactly as the API renders it. The
    # closing check reads it back to prove the renewal *moved* it rather than
    # merely flipping a status.
    seeded_due_date: str


@pytest.fixture
def queued_library_requests(
    provisioned_school: SchoolContext, api: BackendAPI
) -> DeskQueue:
    """Put three books on the shelf and three readers' requests on the desk.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.

    All three requests are raised as the school's *student* — the role the desk
    exists to serve, and one that holds ``("manage", "catalogue")`` in
    ``db/repository/permissions.py``, which is the gate on
    ``POST /book-requests/create/``. The middle one is then approved over the
    API so the reader has something to ask an extension on; that approval is
    setup, and the renewal it makes possible is what the walkthrough decides.
    """
    ctx = provisioned_school
    assert ctx.student is not None, (
        "provisioning admitted no student at this school, so nobody is here to "
        "have asked the library for anything"
    )
    assert ctx.branches, "provisioning created no branch for this school"

    branch = ctx.branches[0]
    branch_id = int(branch.get("id") or -1)
    if branch_id <= 0:
        raise RequestDeskSeedError(
            "provisioning captured no branch id. This desk is branch-scoped on "
            "both sides — the frontend appends branch_id from useBranchStore and "
            "the backend refuses a SchoolAdmin request without one — so nothing "
            "could be shelved or queued."
        )

    librarian_token, librarian_id = _desk_login(api, ctx.school_admin)
    student_token, student_id = _desk_login(api, ctx.student)

    category_id = _desk_category_id(api, librarian_token, branch_id=branch_id)

    granted_book, granted_copies = _desk_seed_book(
        api, librarian_token, title=GRANTED_BOOK,
        branch_id=branch_id, category_id=category_id, copies=2,
    )
    refused_book, _ = _desk_seed_book(
        api, librarian_token, title=REFUSED_BOOK,
        branch_id=branch_id, category_id=category_id, copies=1,
    )
    renewed_book, renewed_copies = _desk_seed_book(
        api, librarian_token, title=RENEWED_BOOK,
        branch_id=branch_id, category_id=category_id, copies=1,
    )

    granted_request_id = _desk_request_book(
        api, student_token, book_id=granted_book, user_id=student_id,
        title=GRANTED_BOOK,
    )
    refused_request_id = _desk_request_book(
        api, student_token, book_id=refused_book, user_id=student_id,
        title=REFUSED_BOOK,
    )
    renewal_book_request_id = _desk_request_book(
        api, student_token, book_id=renewed_book, user_id=student_id,
        title=RENEWED_BOOK,
    )

    seeded_due_date = _desk_approve_over_api(
        api, librarian_token,
        request_id=renewal_book_request_id,
        book_copy_id=renewed_copies[0]["id"],
        managed_by=librarian_id,
    )
    renewal_request_id = _desk_ask_for_renewal(
        api, student_token,
        book_request_id=renewal_book_request_id,
        book_copy_id=renewed_copies[0]["id"],
        book_id=renewed_book,
        user_id=student_id,
    )

    _desk_assert_queued(
        api, librarian_token, branch_id=branch_id,
        book_requests={
            GRANTED_BOOK: STATUS_PENDING,
            REFUSED_BOOK: STATUS_PENDING,
            RENEWED_BOOK: STATUS_APPROVED,
        },
        renewal_request_id=renewal_request_id,
    )

    return DeskQueue(
        branch_id=branch_id,
        branch_name=str(branch["name"]),
        student_name=ctx.student.full_name,
        librarian_first_name=ctx.school_admin.first_name,
        granted_copy_name=str(granted_copies[0]["name"]),
        granted_request_id=granted_request_id,
        refused_request_id=refused_request_id,
        renewal_book_request_id=renewal_book_request_id,
        renewal_request_id=renewal_request_id,
        seeded_due_date=seeded_due_date,
    )


@pytest.mark.school_admin
@pytest.mark.scenario(DESK_SCENARIO)
@pytest.mark.demo(
    feature_id="library.requests_and_renewals.manage.school_admin",
    title="Requests & Renewals",
    subtitle="SchoolAdmin creates and manages requests & renewals",
)
def test_school_admin_works_the_library_request_desk(
    queued_library_requests: DeskQueue,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A school administrator works the library desk: one book lent, one request
    refused, one loan extended.

    Every decision is a real write, and the closing check reads all three back
    off the server rather than off the screen. Approving is not a status change:
    ``handle_book_request`` binds the chosen ``BookCopy`` to the request, stores
    the due date and marks that copy unavailable. Approving a renewal is not one
    either — ``process_checkout_request`` writes the new date back onto the
    original book request, which is why the seeded due date is captured up front
    and compared against.
    """
    ctx = provisioned_school
    queue = queued_library_requests

    page: Page = demo.page
    desk = RequestDeskPage(page, demo.frontend_base_url)

    with demo.step(f"Sign in as the administrator of {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.school_admin)

    with demo.step(f"Open {queue.branch_name} — the campus whose library this is"):
        # Mandatory, not scene-setting: the desk fetches nothing until a branch
        # is in the store, and the Library menu is hidden from a SchoolAdmin
        # until then. See the module docstring.
        BranchesPage(page, demo.frontend_base_url).select_branch(queue.branch_name)

    with demo.step("The Library menu offers Returns & Renewals — open the desk"):
        desk.expect_nav_entry()
        desk.open_from_sidebar().wait_for_table()
        desk.expect_desk_view()
        desk.expect_tabs()
        desk.expect_column_headers(REQUEST_COLUMNS)

    with demo.step(f"Two books {queue.student_name} asked for are still waiting "
                   f"on an answer"):
        desk.expect_request(
            GRANTED_BOOK,
            student=queue.student_name,
            status=STATUS_PENDING,
            return_date_set=False,
        )
        desk.expect_request(
            REFUSED_BOOK,
            student=queue.student_name,
            status=STATUS_PENDING,
            return_date_set=False,
        )

    with demo.step("Lend the Soyinka — choose the copy going off the shelf and "
                   "set the day it is due back"):
        desk.approve_request(
            GRANTED_BOOK,
            copy_name=queue.granted_copy_name,
            expected_return_date=GRANTED_RETURN_DATE,
        )
        desk.expect_request(
            GRANTED_BOOK,
            status=STATUS_APPROVED,
            manager=queue.librarian_first_name,
            return_date_set=True,
        )

    with demo.step("Turn the other one down — every copy is with the exam class, "
                   "and the reader is told why"):
        desk.reject_request(REFUSED_BOOK, reason=REFUSAL_REASON)
        desk.expect_request(
            REFUSED_BOOK,
            status=STATUS_REJECTED,
            manager=queue.librarian_first_name,
        )

    with demo.step("Over on Returns / Renewals, a reader wants longer with the "
                   "book they already have"):
        desk.open_tab(TAB_RETURNS_RENEWALS)
        desk.expect_column_headers(RENEWAL_COLUMNS)
        desk.expect_request(
            RENEWED_BOOK,
            columns=RENEWAL_COLUMNS,
            student=queue.student_name,
            status=STATUS_PENDING,
        )
        desk.expect_menu_items(
            RENEWED_BOOK,
            present=(APPROVE_RENEWAL_ITEM, REJECT_RENEWAL_ITEM),
        )

    with demo.step("Grant the extension, and the loan is re-dated on the spot"):
        desk.approve_renewal(RENEWED_BOOK, new_return_date=RENEWED_RETURN_DATE)
        desk.expect_request(
            RENEWED_BOOK,
            columns=RENEWAL_COLUMNS,
            status=STATUS_APPROVED,
            return_date_set=True,
        )

    with demo.step("Nothing on the desk is still waiting on a decision — and the "
                   "library's own records agree", dwell_ms=2000):
        desk.open_tab(TAB_BOOK_REQUESTS)
        desk.wait_for_table()
        # A decided row's menu keeps only its read-side items: AdminView renders
        # Approve/Reject solely while ``status === "pending"``, so this is the
        # screen's own account of both requests being settled.
        desk.expect_menu_items(
            GRANTED_BOOK,
            present=(VIEW_DETAILS_ITEM,),
            absent=(APPROVE_ITEM, REJECT_ITEM),
        )
        desk.expect_menu_items(
            REFUSED_BOOK,
            present=(VIEW_DETAILS_ITEM,),
            absent=(APPROVE_ITEM, REJECT_ITEM),
        )
        _desk_expect_decisions_applied(api, ctx, queue)


# ──────────── what the server was left holding (the real assertions) ─────────


def _desk_expect_decisions_applied(
    api: BackendAPI, ctx: SchoolContext, queue: DeskQueue
) -> None:
    """All three decisions reached the server, and each did its own work.

    The UI half above only shows badges changing, which a frontend that updated
    its own state optimistically would reproduce exactly. What is asserted here
    is what the backend stored: the copy bound to the approved loan, the manager
    recorded against both verdicts, and — for the renewal — the due date moved on
    the *original* book request, which is the only thing that makes an extension
    an extension.
    """
    token, _ = _desk_login(api, ctx.school_admin)

    requests = _desk_book_requests(api, token, branch_id=queue.branch_id)

    granted = requests.get(GRANTED_BOOK)
    assert granted is not None, (
        f"the branch's book-request queue no longer holds {GRANTED_BOOK!r} at "
        f"all — approving it must not remove it from the register"
    )
    assert granted.get("status") == STATUS_APPROVED, (
        f"{GRANTED_BOOK!r} was approved on screen but the server still reports "
        f"{granted.get('status')!r}"
    )
    assert granted.get("copy"), (
        f"{GRANTED_BOOK!r} is approved but no physical copy is bound to it. "
        f"handle_book_request sets book_copy_id from the dialog's selection, so "
        f"the loan would name no book on the shelf."
    )
    assert str(granted["copy"].get("name")) == queue.granted_copy_name, (
        f"the loan is bound to copy {granted['copy'].get('name')!r}, not to "
        f"{queue.granted_copy_name!r} — the copy the librarian chose"
    )
    assert granted["copy"].get("available") is False, (
        f"copy {queue.granted_copy_name!r} is out on loan but is still marked "
        f"available, so the library would lend it twice"
    )
    assert granted.get("expected_return_date"), (
        f"{GRANTED_BOOK!r} is on loan with no due date recorded"
    )
    assert _desk_manager_email(granted) == ctx.school_admin.email.lower(), (
        f"{GRANTED_BOOK!r} records "
        f"{_desk_manager_email(granted)!r} as the approver, not the "
        f"administrator who approved it ({ctx.school_admin.email.lower()!r})"
    )

    refused = requests.get(REFUSED_BOOK)
    assert refused is not None, (
        f"the branch's book-request queue no longer holds {REFUSED_BOOK!r}"
    )
    assert refused.get("status") == STATUS_REJECTED, (
        f"{REFUSED_BOOK!r} was rejected on screen but the server still reports "
        f"{refused.get('status')!r}"
    )
    assert not refused.get("copy"), (
        f"{REFUSED_BOOK!r} was refused, yet a copy is bound to it — a rejection "
        f"must not take a book off the shelf"
    )
    assert _desk_manager_email(refused) == ctx.school_admin.email.lower(), (
        f"{REFUSED_BOOK!r} records {_desk_manager_email(refused)!r} as the "
        f"decider, not the administrator who refused it"
    )

    renewal = _desk_renewal_request(
        api, token, branch_id=queue.branch_id, request_id=queue.renewal_request_id
    )
    assert renewal.get("status") == STATUS_APPROVED, (
        f"the renewal on {RENEWED_BOOK!r} was granted on screen but the server "
        f"still reports {renewal.get('status')!r}"
    )
    renewed_due = str((renewal.get("book_request") or {}).get("expected_return_date"))
    assert renewed_due and renewed_due != "None", (
        f"the renewed loan on {RENEWED_BOOK!r} carries no due date at all"
    )
    assert renewed_due != queue.seeded_due_date, (
        f"the renewal was approved but the loan is still due back on "
        f"{queue.seeded_due_date!r}. process_checkout_request writes the new "
        f"date onto the original book request — an extension that does not move "
        f"the date is not an extension."
    )


# ──────────── setup-only seeding for this unit (never asserted) ──────────────


def _desk_rows(payload: Any) -> list[dict]:
    """Some list endpoints answer a bare list, others a paginated envelope."""
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    return [row for row in payload if isinstance(row, dict)]


def _desk_login(api: BackendAPI, creds: BaseCredentials) -> tuple[str, int]:
    """Log in over the API and return ``(token, user id)``.

    The user id is taken from the login response's ``id`` — the *user's* id, per
    ``Token``/``SuperAdminToken`` in ``api/api_models/login.py``. Deliberately
    not ``Credentials.user_id``: that comes from the profile-create response,
    whose ``id`` is the student/teacher record's, not the user's, and
    ``book_request.user_id`` and ``managed_by`` are both user ids.
    """
    try:
        body = api.login(creds.email, creds.password)
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise RequestDeskSeedError(f"could not log in as {creds.email}: {exc}") from exc
    token = str(body.get("access_token") or "")
    user_id = body.get("id")
    if not token or not isinstance(user_id, int):
        raise RequestDeskSeedError(
            f"the login for {creds.email} answered without a token or a user id: "
            f"{sorted(body)}"
        )
    return token, user_id


def _desk_category_id(api: BackendAPI, token: str, *, branch_id: int) -> int:
    """Find or create the genre the seeded books are filed under.

    A SchoolAdmin must name the branch explicitly — ``list_book_categories``
    answers 400 BRANCH_ID_REQUIRED for them otherwise — while the create takes
    the branch in its body.
    """
    listed = api.get(f"/book/categories/?branch_id={branch_id}", token=token)
    if listed.status_code >= 400:
        raise RequestDeskSeedError(
            f"could not list book categories in branch {branch_id}: "
            f"{listed.status_code} {listed.text[:300]}"
        )
    for row in _desk_rows(listed.json()):
        # Case-insensitively: BookCategoryService stores
        # ``name.strip().capitalize()``, so a genre this seeded earlier in the
        # same session lists back as "Test set texts …" and a case-sensitive
        # match would try to create it again and be refused with a 400.
        if str(row.get("name", "")).casefold() == DESK_CATEGORY.casefold():
            return int(row["id"])

    created = api.post(
        "/book/categories/create/",
        token=token,
        json={
            "name": DESK_CATEGORY,
            "description": "Seeded so the request desk has books to lend.",
            "school_branch_id": branch_id,
        },
    )
    if created.status_code >= 400:
        raise RequestDeskSeedError(
            f"could not create the book category {DESK_CATEGORY!r}: "
            f"{created.status_code} {created.text[:300]}"
        )
    return int(created.json()["id"])


def _desk_seed_book(
    api: BackendAPI,
    token: str,
    *,
    title: str,
    branch_id: int,
    category_id: int,
    copies: int,
) -> tuple[int, list[dict]]:
    """One book plus the physical copies a loan is actually made of.

    ``BookService.create_book`` writes no copies of its own, and
    ``validate_book_request`` refuses a request for a book with no *available*
    copy — so a book seeded without them could not be requested, let alone lent.
    The copies are topped up rather than blindly added so a re-run against a
    school this session already stocked cannot double them.

    Returns the book id and its available copies, whose server-generated names
    (``"<title> <6 digits>"``) are what the approve dialog lists.
    """
    existing = _desk_find_book(api, token, branch_id=branch_id, title=title)
    if existing is None:
        created = api.post(
            "/books/create/",
            token=token,
            json={
                "title": title,
                "isbn": DESK_ISBNS[title],
                "publisher": f"{TEST_PREFIX} University Press",
                "description": "Seeded for the library request-desk unit.",
                "published_date": "2019-01-15",
                "number_of_pages": 208,
                "category_id": category_id,
                "author_names": [DESK_AUTHORS[title]],
                "school_branch_id": branch_id,
            },
        )
        if created.status_code >= 400:
            raise RequestDeskSeedError(
                f"could not seed the book {title!r}: "
                f"{created.status_code} {created.text[:300]}"
            )
        existing = created.json()

    book_id = int(existing["id"])
    shortfall = copies - int(existing.get("available_copies_count") or 0)
    if shortfall > 0:
        added = api.post(
            f"/book/copies/books/{book_id}/add-copies",
            token=token,
            json={
                "num_copies": shortfall,
                "physical_location": DESK_SHELF,
                "physical_condition": "new",
            },
        )
        if added.status_code >= 400:
            raise RequestDeskSeedError(
                f"could not add {shortfall} copies of {title!r}: "
                f"{added.status_code} {added.text[:300]}"
            )

    fresh = api.get(f"/books/{book_id}", token=token)
    if fresh.status_code >= 400:
        raise RequestDeskSeedError(
            f"could not read back the book {title!r}: "
            f"{fresh.status_code} {fresh.text[:300]}"
        )
    available = [
        row for row in (fresh.json().get("available_copies_list") or [])
        if isinstance(row, dict)
    ]
    if len(available) < copies:
        raise RequestDeskSeedError(
            f"{title!r} has {len(available)} available copies, not the {copies} "
            f"this unit needs — a book with none cannot be requested at all "
            f"(utils/validations/book_request.py)"
        )
    return book_id, available


def _desk_find_book(
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
    for row in _desk_rows(response.json()):
        if wanted.match(str(row.get("title", ""))):
            return row
    return None


def _desk_request_book(
    api: BackendAPI, student_token: str, *, book_id: int, user_id: int, title: str
) -> int:
    """Have the reader ask for a book, the way the catalogue's "Request Book" does.

    ``validate_book_request`` refuses a second *pending* request for the same
    book by the same reader, so an existing one is reused rather than treated as
    a failure — that is the same request, already waiting on this desk.
    """
    created = api.post(
        "/book-requests/create/",
        token=student_token,
        json={"request_type": "instant", "book_id": book_id, "user_id": user_id},
    )
    if created.status_code < 400:
        return int(created.json()["id"])

    existing = _desk_existing_request(
        api, student_token, user_id=user_id, book_id=book_id
    )
    if existing is not None:
        return existing
    raise RequestDeskSeedError(
        f"the student could not request {title!r}: "
        f"{created.status_code} {created.text[:300]}"
    )


def _desk_existing_request(
    api: BackendAPI, student_token: str, *, user_id: int, book_id: int
) -> int | None:
    listed = api.get(f"/book-requests/student/{user_id}", token=student_token)
    if listed.status_code >= 400:
        return None
    mine = [
        row for row in _desk_rows(listed.json())
        if int((row.get("book") or {}).get("id") or 0) == book_id
    ]
    # A still-pending one first: that is the request the create was refused for
    # ("The request for this book is pending"), and the only one this
    # walkthrough can go on to decide.
    for row in mine:
        if str(row.get("status")) == STATUS_PENDING:
            return int(row["id"])
    return int(mine[0]["id"]) if mine else None


def _desk_approve_over_api(
    api: BackendAPI,
    librarian_token: str,
    *,
    request_id: int,
    book_copy_id: int,
    managed_by: int,
) -> str:
    """Lend one book before the walkthrough starts, so it can be extended in it.

    A renewal can only be raised against an *approved* book request that has not
    been returned (``utils/validations/return_renewal_request.py``), so this is
    the prerequisite for the desk's third queue having anything in it.

    Returns the due date exactly as the API renders it (``dd-MM-yy HH:MM:SS``),
    which the closing check compares the renewed date against.
    """
    now = datetime.now(timezone.utc)
    response = api.put(
        f"/book-requests/{request_id}/approve/",
        token=librarian_token,
        json={
            "checkout_date": now.isoformat(),
            "expected_return_date": (
                now + timedelta(days=SEEDED_LOAN_DAYS)
            ).isoformat(),
            "book_copy_id": book_copy_id,
            "managed_by": managed_by,
        },
    )
    if response.status_code >= 400:
        raise RequestDeskSeedError(
            f"could not lend book request {request_id} over the API: "
            f"{response.status_code} {response.text[:300]}"
        )
    due = str(response.json().get("expected_return_date") or "")
    if not due:
        raise RequestDeskSeedError(
            f"book request {request_id} was approved but came back with no "
            f"expected_return_date, so the renewal would have nothing to move"
        )
    return due


def _desk_ask_for_renewal(
    api: BackendAPI,
    student_token: str,
    *,
    book_request_id: int,
    book_copy_id: int,
    book_id: int,
    user_id: int,
) -> int:
    """Have the reader ask for longer — StudentView's "Renew" dialog, over the API."""
    created = api.post(
        "/return-renewal-requests/create/",
        token=student_token,
        json={
            "request_type": "renewal",
            "comment": RENEWAL_COMMENT,
            "book_request_id": book_request_id,
            "book_copy_id": book_copy_id,
            "book_id": book_id,
            "user_id": user_id,
        },
    )
    if created.status_code >= 400:
        raise RequestDeskSeedError(
            f"the student could not ask to renew book request {book_request_id}: "
            f"{created.status_code} {created.text[:300]}"
        )
    return int(created.json()["id"])


def _desk_book_requests(
    api: BackendAPI, token: str, *, branch_id: int
) -> dict[str, dict]:
    """The branch's book-request register, keyed by book title."""
    response = api.get(f"/book-requests/?branch_id={branch_id}", token=token)
    if response.status_code >= 400:
        raise AssertionError(
            f"GET /book-requests/?branch_id={branch_id} → "
            f"{response.status_code}: {response.text[:300]}"
        )
    return {
        str((row.get("book") or {}).get("title", "")): row
        for row in _desk_rows(response.json())
    }


def _desk_renewal_request(
    api: BackendAPI, token: str, *, branch_id: int, request_id: int
) -> dict:
    response = api.get(f"/return-renewal-requests/?branch_id={branch_id}", token=token)
    if response.status_code >= 400:
        raise AssertionError(
            f"GET /return-renewal-requests/?branch_id={branch_id} → "
            f"{response.status_code}: {response.text[:300]}"
        )
    for row in _desk_rows(response.json()):
        if int(row.get("id") or 0) == request_id:
            return row
    raise AssertionError(
        f"return/renewal request {request_id} is not in branch {branch_id}'s "
        f"register at all — deciding it must not remove it"
    )


def _desk_manager_email(request_row: dict) -> str:
    return str((request_row.get("manager") or {}).get("email", "")).lower()


def _desk_assert_queued(
    api: BackendAPI,
    token: str,
    *,
    branch_id: int,
    book_requests: dict[str, str],
    renewal_request_id: int,
) -> None:
    """Fail here, loudly, rather than as an empty desk three steps into the video.

    Both registers are branch-scoped on the server (``list_book_requests`` joins
    ``Book.school_branch_id``), so a book seeded into a different branch than the
    one the walkthrough zooms into would leave the desk empty — a symptom that
    looks nothing like its cause once it reaches the browser.
    """
    queued = _desk_book_requests(api, token, branch_id=branch_id)
    for title, expected in book_requests.items():
        row = queued.get(title)
        if row is None:
            raise RequestDeskSeedError(
                f"{title!r} was seeded but is not on branch {branch_id}'s request "
                f"desk. The queue is scoped on the *book's* branch, so the book "
                f"and the branch the test zooms into have come apart."
            )
        if str(row.get("status")) != expected:
            raise RequestDeskSeedError(
                f"the seeded request for {title!r} is {row.get('status')!r}, not "
                f"{expected!r} — the walkthrough decides it on camera and would "
                f"find nothing to decide"
            )
    _desk_renewal_request(
        api, token, branch_id=branch_id, request_id=renewal_request_id
    )


# ════════ read-only path: a pupil checks on the books they asked for ═════════
#
# Constants below are prefixed rather than sharing the desk section's names: this
# module file is written one unit at a time, and a shared module-level name would
# silently rebind under whichever section is appended last. The few helpers that
# are genuinely the same job — logging in over the API, reading a list body,
# raising a request as the reader, lending one before the camera rolls — are
# reused from that section outright.
#
# Why a pupil gets a *different* screen from the same route
#     ``page.tsx``'s ``shouldShowAdminView()`` returns true only for a role name
#     of "schooladmin", for "admin" holding a manage permission, or for one
#     reading "library"/"librarian". "student" matches none of them, so the route
#     renders ``views/StudentView.tsx`` — the borrower's own record. That is the
#     whole of this unit: the library seen by the reader who borrows from it,
#     not by the person who runs it.
#
# Why the route is reachable for this role
#     Both halves of the gate pass. ``db/repository/permissions.py`` seeds the
#     Student role with ``("manage", "requests_and_renewals")``, which satisfies
#     ``usePermissionGuard("requests_and_renewals")`` in StudentView, and with
#     ``("manage", "catalogue")``, which is the key every route in
#     ``api/routes/book_request.py`` actually names; and the
#     ``library_and_community`` pack licenses both modules, which satisfies
#     ``useModuleGuard("requests_and_renewals")`` and the feature-pack half of
#     ``utils.permissions.has_permission``. The sidebar's "Library Module"
#     section is ``branchOnly``, but ``SideNavigation.canShowSection`` treats
#     branch state as a SchoolAdmin-only concept, so the entry is offered to a
#     pupil outright — and unlike the desk unit above, no branch has to be
#     selected first, because StudentView reads the borrower's own
#     ``school_branch_id`` on the server instead.
#
# Whose requests the pupil is shown
#     Their own, and they get no say in it: the view asks for
#     ``/book-requests/student/{authUserProfile.id}`` and the route overwrites
#     ``branch_id`` with ``user.school_branch_id`` for any non-admin before it
#     queries. So every row below could only have come from this pupil's own
#     borrowing record on their own campus.
#
# What "read-only" means here, precisely
#     Not that the pupil is denied anything — like the desk role they hold
#     ``manage``. It is the *view* that decides nothing: no tabs, no scanner, no
#     bulk reminder, and no row menu that approves, rejects, processes or
#     deletes. The two row buttons it does draw, "Renew" and "Return", merely
#     open a dialog, and they are disabled outright on any request the librarian
#     has not approved — which is what the walkthrough shows rather than sends.
#     Actually sending one is the borrower's own write flow and belongs to the
#     unit that covers it.
#
# The three requests are seeded, and decided, over the API for the same reason
# the desk unit's are: raising one is ``/module/catalogue``'s "Request Book" and
# deciding it is the desk this file's first unit already walks through — two
# other units' subjects, as two other roles, played out inside this one's video.

READER_SCENARIO = "library_and_community"
READER_TAG = run_tag()

# Two genres, so the category filter has something to narrow *to* and something
# to narrow away from. Named per run so nothing this test reads can have been
# left behind by another, and deliberately distinct from DESK_CATEGORY: both
# units may run against the same provisioned school and the same pupil.
READER_POETRY = f"{TEST_PREFIX} Poetry {READER_TAG}"
READER_HISTORY = f"{TEST_PREFIX} History {READER_TAG}"
READER_SHELF = "Shelf C-2"

# A 1×1 PNG — the shape the app's own Add Book dialog stores, which reads the
# chosen file with ``FileReader.readAsDataURL`` and refuses to submit without
# one. StudentView renders ``<Image src={request.book.thumbnail}>`` unguarded, so
# a book seeded without a thumbnail would take the whole table down with
# next/image's "missing required src property". That is a shape the librarian's
# dialog cannot produce, so it is not a defect for this unit to invent — the
# seeding just has to stop being less careful than the UI it stands in for.
READER_THUMBNAIL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGM4ceIEAAS0AlkWLoFAAAAAAElFTkSuQmCC"
)


@dataclass(frozen=True)
class ReaderRequest:
    """One book the pupil asked for, and the answer the library gave."""

    title: str
    author: str
    isbn: str
    category: str
    status: str


# One request per answer the library can have given, so the record on screen is
# the whole of what this view has to say.
ON_LOAN = ReaderRequest(
    title=f"{TEST_PREFIX} Song of Lawino {READER_TAG}",
    author="Okot pBitek",
    isbn="9789966469199",
    category=READER_POETRY,
    status=STATUS_APPROVED,
)
AWAITING = ReaderRequest(
    title=f"{TEST_PREFIX} Leaves of Grass {READER_TAG}",
    author="Walt Whitman",
    isbn="9780140421996",
    category=READER_POETRY,
    status=STATUS_PENDING,
)
REFUSED = ReaderRequest(
    title=f"{TEST_PREFIX} A History of West Africa {READER_TAG}",
    author="Basil Davidson",
    isbn="9780582585041",
    category=READER_HISTORY,
    status=STATUS_REJECTED,
)
READER_REQUESTS: tuple[ReaderRequest, ...] = (ON_LOAN, AWAITING, REFUSED)

# The librarian's reason for turning one down. Never rendered on this view —
# BookRequestResponse does not carry the field at all (see the module docstring)
# — but the reject route requires one.
READER_REFUSAL_REASON = (
    f"{TEST_PREFIX} Every copy is with the exam class this term."
)

# What the two undecided rows render where a loan would show its dates: an
# approval is the only thing that sets expected_return_date, and getRemainingDays
# answers "Not specified" for a null one.
READER_NO_DATES = UNSPECIFIED_RETURN_DATE
# The one word the Returned column can hold for a book still out.
READER_NOT_RETURNED = "No"
# ``request_type`` as StudentView prints it, straight off the row.
READER_REQUEST_TYPE = "instant"

# The status the pupil filters on, exactly as the dropdown labels it. Note it is
# title case in the dropdown and lower case in the row's badge — the filter
# compares them case-insensitively.
READER_APPROVED_FILTER = "Approved"


@dataclass(frozen=True)
class BorrowingRecord:
    """What the pupil's own record holds when the video starts."""

    # Every request this pupil has ever made, which is what the "All Books" badge
    # counts — read back from the API rather than assumed, because the desk unit
    # above may have queued some of its own against the same pupil first.
    total: int
    # The physical copy the librarian handed over, named by the server
    # ("<title> <6 digits>"), and the due date exactly as the table renders it.
    copy_name: str
    due_date: str


@pytest.fixture
def reader_borrowing_record(
    provisioned_school: SchoolContext, api: BackendAPI
) -> BorrowingRecord:
    """Give the pupil three books' worth of history: one lent, one waiting, one
    turned down.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.

    Every step is idempotent by (book, status): the whole batch shares one
    provisioned school, and a re-run must not leave the pupil holding two rows
    for the same book — the table would then have two rows matching one title and
    every per-row assertion below would be reading whichever came first.
    """
    ctx = provisioned_school
    assert ctx.student is not None, (
        "provisioning admitted no student at this school, so nobody is here to "
        "have borrowed anything"
    )
    assert ctx.branches, "provisioning created no branch for this school"

    branch_id = int((ctx.branches[0] or {}).get("id") or -1)
    if branch_id <= 0:
        raise RequestDeskSeedError(
            "provisioning captured no branch id. Every book is shelved in a "
            "branch and this view only ever shows the reader their own branch's "
            "requests, so nothing could be seeded where they would see it."
        )

    librarian_token, librarian_id = _desk_login(api, ctx.school_admin)
    student_token, student_id = _desk_login(api, ctx.student)

    categories = {
        name: _reader_category_id(api, librarian_token, branch_id=branch_id, name=name)
        for name in (READER_POETRY, READER_HISTORY)
    }

    for wanted in READER_REQUESTS:
        book_id, copies = _reader_seed_book(
            api, librarian_token, wanted,
            branch_id=branch_id, category_id=categories[wanted.category],
        )
        _reader_settle_request(
            api,
            librarian_token=librarian_token,
            librarian_id=librarian_id,
            student_token=student_token,
            student_id=student_id,
            wanted=wanted,
            book_id=book_id,
            copies=copies,
        )

    return _reader_assert_pupil_sees_them(
        api, student_token, student_id=student_id, email=ctx.student.email
    )


@pytest.mark.student
@pytest.mark.scenario(READER_SCENARIO)
@pytest.mark.demo(
    feature_id="library.requests_and_renewals.view.student",
    title="Requests & Renewals",
    subtitle="Student views requests & renewals",
)
def test_student_reviews_their_library_requests(
    reader_borrowing_record: BorrowingRecord,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A pupil opens their library record, reads the library's answer on each
    book they asked for, filters it two ways — and is never offered a way to
    decide any of it.

    Everything asserted is the server's answer rather than the browser's: the
    copy name was generated when the librarian added physical copies, the due
    date was written by ``handle_book_request`` on approval, the status is the
    verdict stored against the request, and the genre is the one the book was
    filed under. So a table matching them can only have rendered this pupil's own
    ``GET /book-requests/student/{id}`` answer.
    """
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"
    record = reader_borrowing_record

    page: Page = demo.page
    requests = StudentRequestsAndRenewalsPage(page, demo.frontend_base_url)
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

    with demo.step("The Library menu is waiting in their sidebar — open Returns "
                   "& Renewals"):
        requests.expect_nav_entry()
        requests.open_from_sidebar().wait_for_table()
        requests.expect_borrower_view()
        requests.expect_column_headers()
        requests.expect_toolbar()

    with demo.step("Every book they have asked the library for is here, with the "
                   "answer they were given"):
        requests.expect_total(record.total)
        requests.expect_request(
            ON_LOAN.title,
            category=ON_LOAN.category,
            request_type=READER_REQUEST_TYPE,
            status=STATUS_APPROVED,
        )
        requests.expect_request(
            AWAITING.title,
            copy=NO_COPY_ASSIGNED,
            category=AWAITING.category,
            status=STATUS_PENDING,
            expected_return=READER_NO_DATES,
            days_remaining=READER_NO_DATES,
        )
        requests.expect_request(
            REFUSED.title,
            copy=NO_COPY_ASSIGNED,
            category=REFUSED.category,
            status=STATUS_REJECTED,
            expected_return=READER_NO_DATES,
            days_remaining=READER_NO_DATES,
        )

    with demo.step("The one book actually in their hands names the copy they "
                   "were given, and how long is left on it"):
        requests.expect_request(
            ON_LOAN.title,
            copy=rf"^\s*{re.escape(record.copy_name)}\s*$",
            expected_return=rf"^\s*{re.escape(record.due_date)}\s*$",
            days_remaining=DAYS_LEFT,
            returned=READER_NOT_RETURNED,
        )

    with demo.step("Filtering by status leaves only what the librarian approved"):
        requests.filter_by_status(READER_APPROVED_FILTER)
        requests.expect_request(ON_LOAN.title, status=STATUS_APPROVED)
        requests.expect_request_absent(AWAITING.title)
        requests.expect_request_absent(REFUSED.title)
        # The badge counts the whole record, not the filtered rows — which is
        # what makes it the honest witness that nothing was dropped.
        requests.expect_total(record.total)

    with demo.step(f"Clear it, and filtering by genre leaves only {READER_HISTORY}"):
        requests.clear_status_filter()
        requests.filter_by_category(REFUSED.category)
        requests.expect_request(REFUSED.title, category=REFUSED.category)
        requests.expect_request_absent(ON_LOAN.title)
        requests.expect_request_absent(AWAITING.title)

    with demo.step("Only the loan in hand can be renewed or handed back; a "
                   "request nobody has answered offers neither"):
        requests.clear_category_filter()
        requests.expect_borrowing_controls_enabled(ON_LOAN.title)
        requests.expect_borrowing_controls_disabled(AWAITING.title)
        requests.expect_borrowing_controls_disabled(REFUSED.title)

    with demo.step("This is the reader's own record — nothing here decides "
                   "anything", dwell_ms=1500):
        requests.expect_librarian_controls_absent()
        requests.expect_no_failure_toast()


# ──────────── setup-only seeding for the reader unit (never asserted) ─────────


def _reader_category_id(
    api: BackendAPI, token: str, *, branch_id: int, name: str
) -> int:
    """Find or create one genre in the pupil's branch.

    A SchoolAdmin must name the branch explicitly — ``list_book_categories``
    answers 400 BRANCH_ID_REQUIRED for them otherwise — while the create takes
    the branch in its body.
    """
    listed = api.get(f"/book/categories/?branch_id={branch_id}", token=token)
    if listed.status_code >= 400:
        raise RequestDeskSeedError(
            f"could not list book categories in branch {branch_id}: "
            f"{listed.status_code} {listed.text[:300]}"
        )
    for row in _desk_rows(listed.json()):
        # Case-insensitively, for the reason given in ``_desk_category_id``.
        if str(row.get("name", "")).casefold() == name.casefold():
            return int(row["id"])

    created = api.post(
        "/book/categories/create/",
        token=token,
        json={
            "name": name,
            "description": "Seeded so the borrower's record has a genre to filter by.",
            "school_branch_id": branch_id,
        },
    )
    if created.status_code >= 400:
        raise RequestDeskSeedError(
            f"could not create the book category {name!r}: "
            f"{created.status_code} {created.text[:300]}"
        )
    return int(created.json()["id"])


def _reader_seed_book(
    api: BackendAPI,
    token: str,
    wanted: ReaderRequest,
    *,
    branch_id: int,
    category_id: int,
) -> tuple[int, list[dict]]:
    """One book plus the physical copy a loan is actually made of.

    ``BookService.create_book`` writes no copies of its own, and
    ``validate_book_request`` refuses a request for a book with no *available*
    copy — so a book seeded without them could not be asked for at all. Two
    copies, not one: approving binds one to the loan and marks it unavailable,
    and a re-run must still find one free to request against.
    """
    existing = _desk_find_book(api, token, branch_id=branch_id, title=wanted.title)
    if existing is None:
        created = api.post(
            "/books/create/",
            token=token,
            json={
                "title": wanted.title,
                "isbn": wanted.isbn,
                "publisher": f"{TEST_PREFIX} University Press",
                "description": "Seeded for the borrower's-record unit.",
                "published_date": "2018-05-04",
                "number_of_pages": 192,
                "category_id": category_id,
                "author_names": [wanted.author],
                "thumbnail": READER_THUMBNAIL,
                "school_branch_id": branch_id,
            },
        )
        if created.status_code >= 400:
            raise RequestDeskSeedError(
                f"could not seed the book {wanted.title!r}: "
                f"{created.status_code} {created.text[:300]}"
            )
        existing = created.json()

    book_id = int(existing["id"])
    shortfall = 2 - int(existing.get("available_copies_count") or 0)
    if shortfall > 0:
        added = api.post(
            f"/book/copies/books/{book_id}/add-copies",
            token=token,
            json={
                "num_copies": shortfall,
                "physical_location": READER_SHELF,
                "physical_condition": "new",
            },
        )
        if added.status_code >= 400:
            raise RequestDeskSeedError(
                f"could not add {shortfall} copies of {wanted.title!r}: "
                f"{added.status_code} {added.text[:300]}"
            )

    fresh = api.get(f"/books/{book_id}", token=token)
    if fresh.status_code >= 400:
        raise RequestDeskSeedError(
            f"could not read back the book {wanted.title!r}: "
            f"{fresh.status_code} {fresh.text[:300]}"
        )
    available = [
        row for row in (fresh.json().get("available_copies_list") or [])
        if isinstance(row, dict)
    ]
    if not available:
        raise RequestDeskSeedError(
            f"{wanted.title!r} has no available copy, so it could not be "
            f"requested at all (utils/validations/book_request.py)"
        )
    return book_id, available


def _reader_settle_request(
    api: BackendAPI,
    *,
    librarian_token: str,
    librarian_id: int,
    student_token: str,
    student_id: int,
    wanted: ReaderRequest,
    book_id: int,
    copies: list[dict],
) -> dict:
    """Raise the pupil's request and move it to the status this unit needs.

    Idempotent by (book, status): a request already sitting in the wanted state
    is this unit's row, not a stale one, and raising a second would leave two
    rows for one title. ``validate_book_request`` only refuses a duplicate while
    the first is still *pending*, so nothing else stops that happening.
    """
    already = _reader_existing_request(
        api, student_token, user_id=student_id, book_id=book_id, status=wanted.status
    )
    if already is not None:
        return already

    request_id = _desk_request_book(
        api, student_token, book_id=book_id, user_id=student_id, title=wanted.title
    )
    if wanted.status == STATUS_APPROVED:
        _desk_approve_over_api(
            api, librarian_token,
            request_id=request_id,
            book_copy_id=int(copies[0]["id"]),
            managed_by=librarian_id,
        )
    elif wanted.status == STATUS_REJECTED:
        refused = api.put(
            f"/book-requests/{request_id}/reject/",
            token=librarian_token,
            json={
                "managed_by": librarian_id,
                "rejection_reason": READER_REFUSAL_REASON,
            },
        )
        if refused.status_code >= 400:
            raise RequestDeskSeedError(
                f"could not turn down the request for {wanted.title!r}: "
                f"{refused.status_code} {refused.text[:300]}"
            )

    settled = _reader_existing_request(
        api, student_token, user_id=student_id, book_id=book_id, status=wanted.status
    )
    if settled is None:
        raise RequestDeskSeedError(
            f"the request for {wanted.title!r} was seeded but is not "
            f"{wanted.status!r} on the pupil's own record"
        )
    return settled


def _reader_existing_request(
    api: BackendAPI, student_token: str, *, user_id: int, book_id: int, status: str
) -> dict | None:
    """The pupil's own request for one book in one state, read as the pupil."""
    for row in _reader_requests(api, student_token, user_id):
        if (
            int((row.get("book") or {}).get("id") or 0) == book_id
            and str(row.get("status")) == status
        ):
            return row
    return None


def _reader_requests(api: BackendAPI, student_token: str, user_id: int) -> list[dict]:
    listed = api.get(f"/book-requests/student/{user_id}", token=student_token)
    if listed.status_code >= 400:
        raise RequestDeskSeedError(
            f"the pupil cannot read their own book requests at all: "
            f"{listed.status_code} {listed.text[:300]}"
        )
    return _desk_rows(listed.json())


def _reader_assert_pupil_sees_them(
    api: BackendAPI, student_token: str, *, student_id: int, email: str
) -> BorrowingRecord:
    """Fail here, loudly, rather than as an empty table three steps into the video.

    ``book_requests_by_user_id`` joins ``Book.school_branch_id``, so a book
    shelved in a different branch than the pupil belongs to would leave this
    screen empty — a symptom that looks nothing like its cause once it reaches
    the browser. Reading it back on the pupil's *own* token is what proves the
    branch the books went into is the branch they will be read from.
    """
    mine = _reader_requests(api, student_token, student_id)
    by_title = {str((row.get("book") or {}).get("title", "")): row for row in mine}

    for wanted in READER_REQUESTS:
        row = by_title.get(wanted.title)
        if row is None:
            raise RequestDeskSeedError(
                f"{wanted.title!r} is not on {email}'s borrowing record. The "
                f"record is scoped on the *book's* branch, so the book and the "
                f"pupil have come apart."
            )
        if str(row.get("status")) != wanted.status:
            raise RequestDeskSeedError(
                f"the seeded request for {wanted.title!r} is "
                f"{row.get('status')!r}, not {wanted.status!r} — the walkthrough "
                f"reads that verdict off the screen"
            )

    loan = by_title[ON_LOAN.title]
    copy_name = str((loan.get("copy") or {}).get("name") or "")
    if not copy_name:
        raise RequestDeskSeedError(
            f"{ON_LOAN.title!r} is approved but no physical copy is bound to it, "
            f"so the Book Copy column would read 'Copy not assigned'"
        )
    return BorrowingRecord(
        total=len(mine),
        copy_name=copy_name,
        due_date=_reader_display_date(loan.get("expected_return_date")),
    )


def _reader_display_date(raw: Any) -> str:
    """Render the API's due date the way ``StudentView`` renders it.

    ``BookRequestResponse`` serialises every datetime as ``dd-MM-yy HH:MM:SS``
    (its ``json_encoders``) and the view re-formats that with date-fns as
    ``MMM d, yyyy`` — as *local* wall clock, since ``parse`` never shifts a
    timezone. Derived from the server's own answer rather than from the date the
    seeding asked for, so the expectation cannot drift from what was stored.
    """
    text = str(raw or "")
    for fmt in ("%d-%m-%y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        return f"{parsed:%b} {parsed.day}, {parsed.year}"
    raise RequestDeskSeedError(
        f"the approved loan's expected_return_date is {text!r}, which is neither "
        f"shape this backend has served — the due date on screen cannot be "
        f"predicted from it"
    )


# ══════ negative path: the request desk is off the pack (denied) ══════════════
#
# Constants below are prefixed rather than sharing the two positive sections'
# names: this module file is written one unit at a time, and a shared
# module-level name would silently rebind under whichever section is appended
# last.
#
# Who is denied, and by what
#     A SchoolAdmin of the ``minimal`` school — the floor pack the product can
#     actually build (the locked "people" and "governance" groups and nothing
#     else), so no ``requests_and_renewals`` and no ``catalogue``.
#
#     The denial does NOT live in the frontend. ``page.tsx`` calls
#     ``useModuleGuard("requests_and_renewals")``, which returns ``true`` for a
#     SchoolAdmin before it ever reads the ``schoolModules`` cookie, and
#     ``src/middleware.ts`` exempts the role from its module enforcement — so the
#     route really does mount and ``AdminView`` really does start fetching. What
#     refuses them is the backend: every route in
#     ``api/routes/book_request.py`` and ``api/routes/return_renewal_requests.py``
#     carries ``Depends(has_permission(<read|manage>, "catalogue"))``, solved
#     before the handler runs, and the 403 it answers with is turned into a hard
#     redirect to /auth/no-access by the axios interceptor in
#     ``utils/handleErrorMessage.ts`` (``shouldRedirectToNoAccess``).
#
# Why the module key checked on the routes is ``catalogue``, not this module
#     Exactly as in the statistics unit: the circulation routes never name
#     ``requests_and_renewals`` at all. That is asserted explicitly below, so a
#     pack that ever licenses ``catalogue`` without this module fails loudly here
#     rather than serving the whole desk while the product considers it off.
#
# Why the branch is still selected first
#     Same reason as the desk walkthrough: ``AdminView``'s fetch effect returns
#     early for a SchoolAdmin whose ``useBranchStore`` is empty, so with no
#     branch nothing is ever requested, there is no 403, and the screen sits on
#     ``AdminRequestAndRenewalLoader`` for ever — a timeout that says nothing
#     about licensing. Selecting the branch is what makes the denial observable.

DENIED_SCENARIO = "minimal"
DENIED_MODULE = "requests_and_renewals"

# config/module_catalog.py's route for this module.
DENIED_ROUTE = "requests_and_renewals"

# The module key every circulation route is *actually* gated on — see above.
DENIED_GATE_MODULE = "catalogue"

# The role whose permissions are checked against the pack.
DENIED_ROLE = "SchoolAdmin"

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

# The line AdminView's own row menus would offer, and the loader the screen wears
# while a fetch is in flight. Both asserted absent: the redirect must have
# happened, not merely "the table was empty".
DENIED_TOTAL_OVERDUE = re.compile(r"^\s*Total Overdue\s*$", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_requests_and_renewals_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With the library group off the pack, a SchoolAdmin gets no request desk."""
    ctx = provisioned_school
    if DENIED_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {DENIED_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had library rights anyway", which would make the 403s vacuous.
    # db/repository/permissions.py seeds this role with ("manage", "catalogue"),
    # and has_permission lets manage stand in for read — so the permission half
    # of every gate asserted below passes outright, leaving the feature pack as
    # the only thing that can refuse.
    role = api.get(f"/roles/{api.role_id_for(DENIED_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {DENIED_ROLE} role — got {role.status_code}: "
        f"{role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert DENIED_GATE_MODULE in role_modules, (
        f"the seeded {DENIED_ROLE} role no longer holds a "
        f"{DENIED_GATE_MODULE!r} permission, which is the one every "
        f"/book-requests and /return-renewal-requests route is gated on. This "
        f"test would then be asserting a denial the role gets for free. Re-point "
        f"it at the feature pack only, or fix the seed in "
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
        f"{DENIED_MODULE!r} proves nothing about the gate. Provisioning phase A "
        f"assigns one — check that it did."
    )
    licensed = body.get("modules") or []
    assert DENIED_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {DENIED_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )
    assert DENIED_GATE_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {DENIED_GATE_MODULE!r}, which is "
        f"the module key every circulation route is gated on — so the request "
        f"desk is served in full even though {DENIED_MODULE!r} is off the pack. "
        f"That is a product decision about how the library group is licensed "
        f"(the routes never name {DENIED_MODULE!r}), not something this test can "
        f"assert around: escalate it rather than adding a gate."
    )

    # ── 2. The denial itself: every route the desk drives is refused ──────────
    #
    # Both halves of the gate are covered — the three reads AdminView fires on
    # mount (has_permission("read", "catalogue")) and the decisions its row menus
    # take (has_permission("manage", "catalogue")). Request ids are deliberately
    # arbitrary: has_permission is a route-level dependency, solved before the
    # path params are used and long before any row is looked up, so a 404 here
    # would itself be the failure. The list read is asserted unscoped as well,
    # because without a branch_id the *handler* answers 400 BRANCH_ID_REQUIRED —
    # the licence must be refused before that ever runs.
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"?branch_id={branch_id}" if branch_id else ""
    due = (date.today() + timedelta(days=7)).isoformat()

    refusals = {
        # The three queues, in the shape AdminView's handlers build them.
        "book_requests": api.get(f"/book-requests/{branch_query}", token=token),
        "return_renewals": api.get(
            f"/return-renewal-requests/{branch_query}", token=token
        ),
        "overdue_students": api.get(
            f"/book-requests/overdue/students{branch_query}", token=token
        ),
        # The licence is refused before the handler's own branch check.
        "book_requests_unscoped": api.get("/book-requests/", token=token),
        # …and the decisions the row menus take.
        "approve": api.put(
            "/book-requests/1/approve/",
            token=token,
            json={"book_copy_id": 1, "expected_return_date": due},
        ),
        "reject": api.put(
            "/book-requests/1/reject/",
            token=token,
            json={"rejection_reason": f"{TEST_PREFIX} denied {run_tag()}"},
        ),
        "process_return_renewal": api.patch(
            "/return-renewal-requests/1/process/",
            token=token,
            json={"status": "approved"},
        ),
        "remind_overdue": api.post(
            f"/book-requests/overdue/remind{branch_query}", token=token, json={}
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{DENIED_MODULE!r}/{DENIED_GATE_MODULE!r}, so the backend must "
            f"refuse with 403 — got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIED_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a request desk in front of them ─────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Mandatory, and not merely the usual SchoolAdmin branch prerequisite: with
    # an empty branch store AdminView's effect returns before issuing a single
    # request, so there would be no 403 to deny them with and the screen would
    # simply never leave its skeleton. Selecting the branch is what makes the
    # denial observable for the right reason.
    if ctx.branches:
        BranchesPage(page, frontend_base_url).select_branch(ctx.branches[0]["name"])

    # The route really does mount for this role (useModuleGuard and middleware.ts
    # both wave a SchoolAdmin through), so the redirect below is the backend's
    # refusal travelling back through the axios interceptor. Waiting for the URL
    # is therefore also what stops the "desk is absent" assertions from passing
    # merely because the page had not finished loading.
    goto_module(page, frontend_base_url, DENIED_ROUTE)
    page.wait_for_url(DENIED_NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(DENIED_ACCESS_RESTRICTED))).to_be_visible(
        timeout=15_000
    )
    expect(page.get_by_text(as_pattern(DENIED_ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of either workspace survives the redirect: not the desk's heading
    # or its search box, not one of the three tabs, not a table row, and not the
    # borrower's view the same route falls back to for every other role.
    expect(page.get_by_text(as_pattern(DESK_HEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(DESK_SUBHEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(READER_SUBHEADING))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(TAB_BOOK_REQUESTS))).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(TAB_RETURNS_RENEWALS))
    ).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(TAB_OVERDUE))).to_have_count(0)
    expect(page.get_by_text(as_pattern(DENIED_TOTAL_OVERDUE))).to_have_count(0)
    # The empty states are asserted absent too: an empty queue must not be how
    # this school experiences a module it has not bought.
    expect(page.get_by_text(as_pattern(NO_REQUESTS))).to_have_count(0)
    expect(page.get_by_text(as_pattern(NO_RETURN_REQUESTS))).to_have_count(0)
    expect(page.get_by_text(as_pattern(NO_OVERDUE))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)
