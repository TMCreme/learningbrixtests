"""/module/messages — direct messaging (inbox, sent, drafts, scheduled, trash).

Manage path: the SchoolAdmin of the ``library_and_community`` school opens the
branch's mailbox, writes to a member of staff, sends the message in-app, finds
it in Sent under the recipient count the server recorded, reads it back on its
own page and then clears it into Trash
(``test_school_admin_sends_and_manages_a_message``). Each folder is its own
route, so every claim lands on a list ``FolderPage`` had just refetched rather
than on the toast that announced the write.

View path: a teacher of the ``library_and_community`` school opens Messages from
the General menu, finds the school office's notice waiting unread in their
inbox, reads it, and watches the mailbox record that it has been read — while
Sent and Drafts stay empty, because reading is all this walkthrough does
(``test_teacher_reads_a_message_in_their_inbox``).

Guardian view path: the same licensed school and the same read-only shape, from
the role the sidebar deliberately never offers Messages to
(``test_guardian_reads_a_message_in_their_inbox``). A parent reaches the mailbox
by its address — ``SideNavigation.canShowSection`` drops the whole "General"
section for a Guardian outright — and everything after that is identical to the
teacher's walkthrough. See the section comment above that test for why the
missing menu entry is a product decision rather than selector drift.

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack
licenses only ``school_configuration`` and ``school_admin_dashboard``
(``test_messaging_denied_for_school_admin_when_module_disabled``).

Where the denial actually lives
    Not in the sidebar, and not in a route guard.

    * ``nav-config.tsx`` puts "Messages" in the **General** section, and every
      item in that section is declared with neither ``permission`` nor
      ``module``. ``SideNavigation.canShowItem`` therefore falls through to
      ``!item.module || …`` and returns true for *every* role — and for a
      SchoolAdmin it never even reaches that line ("SchoolAdmin bypasses the
      module gate"). The only thing that hides the entry from this role is an
      empty ``useBranchStore``, which is about branch context, not about the
      licence. So the sidebar says nothing about the pack and is deliberately
      not asserted here.
    * ``middleware.ts`` skips the feature-flag gate twice over: ``messages`` is
      listed in ``postAuthRedirect.ts::CORE_MODULES`` (so the check is bypassed
      for *every* role), and the redirect condition carries ``!isSchoolAdmin``
      besides. ``/module/messages`` does not call ``useModuleGuard`` at all —
      and that hook would return ``true`` for this role anyway. So the route
      mounts.
    * The seeded ``SchoolAdmin`` role *holds* ``("manage", "messaging")``
      (newschoolapp/db/repository/permissions.py), so the permission half of the
      backend gate passes too. The test asserts that first, so the 403s below
      can never be read as "this role never had messaging rights anyway".

    What denies them is the **feature-pack licence**, checked on the router:
    ``messaging_router`` carries ``Depends(has_feature_access("messaging"))``,
    so every ``/messaging`` route answers 403 "Feature not available in your
    plan". That 403 is what this test is built on.

    The UI consequence follows from it. ``FolderPage`` asks for the folder on
    mount (``getInbox``); the refusal is recognised by ``shouldRedirectToNoAccess``
    in ``src/utils/handleErrorMessage.ts``, which performs a hard
    ``window.location`` redirect to **/auth/no-access** and rejects with
    ``FeatureNotAvailableError`` before the component's own ``catch`` can put
    "Failed to load inbox" on screen. So the landing page, not an error panel, is
    the denial surface — a school that is *permitted* but not *licensed* is
    thrown out of the module entirely.

A backend defect this unit uncovered (fixed in place, newschoolapp is dirty)
    ``messaging`` is offered as a licensable module — ``SYSTEM_MODULE_GROUPS``
    lists it in the "general" group beside ``community``, and three of the five
    scenarios in ``config/feature_scenarios.yaml`` build packs without it — but
    ``api/routes/messaging.py`` declared no licence check on any of its twenty
    routes. An unlicensed school could read its inbox, compose, send and
    schedule mail exactly as a licensed one could; the module was sellable in
    name only. ``messaging_router`` now carries the same router-level
    ``has_feature_access`` dependency that ``feed_router`` carries for
    ``community``, which is what this test asserts. Deliberately
    ``has_feature_access`` and not ``has_permission``: this is a licence check
    only, and every role that may use messaging when it *is* licensed — Student
    and Guardian included — keeps exactly the access it has today.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.messaging.mailbox import (
    CHANNEL_EMAIL,
    CHANNEL_IN_APP,
    CHANNEL_SMS,
    MailboxPage,
)
from tests.pages.school_admin.branches import BranchesPage

MESSAGING_MODULE = "messaging"
# /module/messages itself only server-redirects here; going straight to the
# folder saves a hop and is the URL the sidebar's "Messages" link resolves to.
MESSAGING_ROUTE = "messages/inbox"
DENIED_SCENARIO = "minimal"

# The role whose permissions are checked against the pack below.
SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# The one refusal utils/permissions.has_feature_access can answer with for a
# user who *is* attached to a school. Anything else (a 403 for an unresolved
# school, say) would be a different bug wearing the same status code.
DENIAL_DETAIL = re.compile(r"Feature not available in your plan", re.I)

# Where the axios interceptor sends a user it has decided is not licensed, and
# the copy it greets them with (src/app/auth/no-access/page.tsx).
NO_ACCESS_URL = re.compile(r"/auth/no-access")
ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)

# The messaging chrome, none of which may survive the redirect. All three come
# from the module's own files: "Compose" and the folder links from
# messages/layout.tsx, the heading and the search box from
# components/messaging/FolderPage.tsx.
COMPOSE_BUTTON = re.compile(r"^\s*Compose\s*$", re.I)
INBOX_HEADING = re.compile(r"^\s*Inbox\s*$", re.I)
MAIL_SEARCH_PLACEHOLDER = re.compile(r"^\s*Search in mail\s*$", re.I)
FOLDER_LINKS = re.compile(r"^\s*(Inbox|Sent|Drafts|Scheduled|Trash)\s*$", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_messaging_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `messaging` off the pack, a SchoolAdmin gets no mailbox and no data."""
    ctx = provisioned_school
    if MESSAGING_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {MESSAGING_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had messaging rights anyway", which would make the 403s
    # vacuous.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert MESSAGING_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{MESSAGING_MODULE!r} permission, so this test would be asserting a "
        f"denial the role gets for free. Re-point it at the feature pack only, "
        f"or fix the seed in newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{MESSAGING_MODULE!r} proves nothing about the gate. Provisioning phase "
        f"A assigns one — check that it did."
    )
    assert MESSAGING_MODULE not in (body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {MESSAGING_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every messaging route is refused ────────────────
    #
    # One per surface the mailbox actually offers — the folder each sidebar link
    # opens, plus both write paths — so a gate that covered only reads, or only
    # the folder the test happens to land on, fails here.
    refusals = {
        # What /module/messages/inbox calls on mount.
        "inbox": api.get("/messaging/inbox?limit=30", token=token),
        "sent": api.get("/messaging/sent?limit=30", token=token),
        "drafts": api.get("/messaging/drafts?limit=30", token=token),
        "scheduled": api.get("/messaging/scheduled?limit=30", token=token),
        "trash": api.get("/messaging/trash?limit=30", token=token),
        # And the write half, so the gate is not merely read-only. The payload
        # is well-formed on purpose: a 422 here would prove nothing about the
        # licence. Recipient 1 is whoever the seed created first — the licence
        # check runs on the router, before the body is ever looked at.
        "send": api.post(
            "/messaging/messages",
            token=token,
            json={
                "subject": "TEST Unlicensed Message",
                "body": "Must never be sent — the pack excludes messaging.",
                "recipient_user_ids": [1],
                "channels": ["inapp"],
            },
        ),
        "draft": api.post(
            "/messaging/messages/drafts",
            token=token,
            json={
                "subject": "TEST Unlicensed Draft",
                "body": "Must never be saved — the pack excludes messaging.",
                "recipient_user_ids": [1],
                "channels": ["inapp"],
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{MESSAGING_MODULE!r}, so the backend must refuse with 403 — "
            f"got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not the licence — got "
            f"{detail!r}. 'User is not associated with a school' here would mean "
            f"the SchoolAdmin→school lookup broke, not that the pack denied them."
        )

    # ── 3. …and the UI never puts a mailbox in front of them ──────────────────
    login_as(page, frontend_base_url, ctx.school_admin)
    goto_module(page, frontend_base_url, MESSAGING_ROUTE)

    # A SchoolAdmin is exempt from both frontend route guards and /module/messages
    # declares neither, so the folder really does mount and really does ask for
    # the inbox — which is refused… and the axios interceptor turns that answer
    # into a hard redirect long before FolderPage's own catch could show "Failed
    # to load inbox" (see the module docstring). Waiting for the URL is therefore
    # also what stops the "mailbox is absent" assertions below from passing
    # merely because the page had not finished loading.
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(
        timeout=15_000
    )
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the mailbox came with them.
    expect(page.get_by_role("button", name=as_pattern(COMPOSE_BUTTON))).to_have_count(0)
    expect(page.get_by_role("heading", name=as_pattern(INBOX_HEADING))).to_have_count(0)
    expect(
        page.get_by_placeholder(as_pattern(MAIL_SEARCH_PLACEHOLDER))
    ).to_have_count(0)
    expect(page.get_by_role("link", name=as_pattern(FOLDER_LINKS))).to_have_count(0)


# ───────────── view path: a teacher reads their own inbox ────────────────────
#
# The same module as the negative path, from a school that *is* licensed for it
# (``library_and_community`` lists ``messaging`` alongside ``community`` and the
# library) and from the role that only ever reads: a class teacher.
#
# What this walkthrough is built on, recorded so the next unit does not
# re-derive it:
#
# * **A teacher reaches Messages in one click.** ``nav-config.tsx`` puts
#   "Messages" in the "General" section with neither a ``permission`` nor a
#   ``module`` gate, and ``SideNavigation.canShowSection`` drops that section
#   only for a SuperAdmin, a Guardian, and a SchoolAdmin who has not opened a
#   branch. So — unlike the administrator, who must select a branch first — a
#   teacher is offered the link the moment they log in, and that is the whole of
#   their navigation story. ``/module/messages`` then server-redirects to
#   ``/module/messages/inbox`` (``messages/page.tsx``).
#
# * **Nothing about messaging is per-role.** Every ``/messaging`` route depends
#   on ``get_current_user`` plus the router-level ``has_feature_access``
#   licence check and nothing else; who may read what is decided by ownership
#   inside ``MessageService`` (``_get_recipient`` → "Message not found in your
#   inbox"). So a teacher of a licensed school has a real mailbox, and this test
#   asserts what is in it rather than whether they may open it.
#
# * **The notice is sent by the branch administrator, not the SchoolAdmin.**
#   ``MessageService._sender_school_id`` takes the school from the sender's own
#   branch, and only falls back to a payload ``school_id`` (plus a
#   ``SchoolAdminAssociation`` lookup) for a sender with no branch at all. The
#   branch admin provisioning creates has ``school_branch_id`` set
#   (``user_service.add_admin``), which makes them the sender with the fewest
#   moving parts — and puts them in the same school as the teacher, which
#   ``_expand_recipients`` insists on ("Cannot message users outside your
#   school").
#
# * **Channel ``inapp`` only.** ``_deliver_external`` returns immediately unless
#   the message carries ``email``/``sms``, so seeding cannot trip over the
#   suppressed mailer (see the run notes on the Gmail quota). The recipient still
#   gets the real in-app row, which is the only thing this screen renders.
#
# * **"Read" is server state, not a CSS class.** ``getMessage`` is called with
#   ``mark_read=true``, which writes ``MessageRecipient.read_at``; the inbox's
#   "Unread only" checkbox filters on the ``read_at`` the *next* ``GET
#   /messaging/inbox`` returns. Asserting through that checkbox — the notice
#   survives it before the read and disappears from it after — is therefore
#   asserting a receipt the server stored, not the unread dot's styling.
#
# Seeded over the API rather than by driving a second role through the composer:
# the same setup-only use of ``api`` as ``school_provisioning._seed_fee_group``
# and ``test_community.announcement``. The subject carries a fresh stamp on every
# execution, so a rerun in the same process (the school is session-scoped) always
# reads a message that is genuinely unread rather than one it read last time.

VIEW_SCENARIO = "library_and_community"

# ── the sidebar entry (SideNavigation/nav-config.tsx, "General") ─────────────
NAV_MESSAGES = re.compile(r"^\s*Messages\s*$", re.I)

# ── routes (messages/layout.tsx's folder hrefs) ──────────────────────────────
INBOX_URL = re.compile(r"/module/messages/inbox")
SENT_URL = re.compile(r"/module/messages/sent")
DRAFTS_URL = re.compile(r"/module/messages/drafts")

# ── the folder rail and the reader (layout.tsx, messages/[id]/page.tsx) ──────
SENT_LINK = re.compile(r"^\s*Sent\s*$", re.I)
DRAFTS_LINK = re.compile(r"^\s*Drafts\s*$", re.I)
BACK_BUTTON = re.compile(r"^\s*Back\s*$", re.I)

# ── FolderPage.tsx: the toolbar filter and one empty state per folder ────────
UNREAD_ONLY_FILTER = re.compile(r"^\s*Unread only\s*$", re.I)
SENT_EMPTY = re.compile(r"^\s*Nothing sent yet\s*$", re.I)
DRAFTS_EMPTY = re.compile(r"^\s*No saved drafts\s*$", re.I)
# handleErrorMessage's fallback for this screen — `Failed to load ${folder}`.
INBOX_LOAD_FAILURE = re.compile(r"Failed to load inbox", re.I)

# Everything the mailbox offers, which the licensed school must show in full.
FOLDER_COUNT = 5


class NoticeSeedError(RuntimeError):
    """The message the teacher is meant to read could not be sent."""


@dataclass
class Notice:
    """The seeded message, as the teacher should find it."""

    message_id: int
    subject: str
    body: str
    sender_name: str
    sender_email: str


@pytest.fixture
def notice(provisioned_school: SchoolContext, api: BackendAPI) -> Notice:
    """Put one unread message from the branch office in the teacher's inbox.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert MESSAGING_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {MESSAGING_MODULE!r} for the "
        f"view path — a school without the module has no mailbox to read"
    )
    assert ctx.teacher is not None, (
        "provisioning created no teacher for this school, so there is no "
        "mailbox to read as"
    )
    assert ctx.branch_admin is not None, (
        "provisioning created no branch administrator, and they are the sender "
        "of the notice the teacher is meant to find"
    )

    stamp = f"{run_tag()}-{uuid.uuid4().hex[:6]}"
    subject = f"TEST Staff briefing {stamp}"
    body = (
        f"TEST Reading Week starts on Monday {stamp}. Please bring your class "
        f"to the library for their slot and collect the reading logs from the "
        f"front office before Friday."
    )

    try:
        token = api.login(ctx.branch_admin.email, ctx.branch_admin.password)[
            "access_token"
        ]
    except Exception as exc:  # noqa: BLE001 — a prerequisite, not the thing under test
        raise NoticeSeedError(
            f"could not sign the branch administrator in to send the notice: {exc}"
        ) from exc

    recipient_id = _teacher_user_id(api, token, ctx)
    res = api.post(
        "/messaging/messages",
        token=token,
        json={
            "subject": subject,
            "body": body,
            "recipient_user_ids": [recipient_id],
            # inapp only: see the section comment — anything else would try to
            # reach the suppressed mailer.
            "channels": ["inapp"],
            "school_id": ctx.school_id,
        },
    )
    if res.status_code >= 400:
        raise NoticeSeedError(
            f"POST /messaging/messages → {res.status_code}: {res.text[:300]}"
        )
    payload = res.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
        raise NoticeSeedError(f"POST /messaging/messages returned no id: {payload!r}")

    return Notice(
        message_id=int(payload["id"]),
        subject=subject,
        body=body,
        sender_name=ctx.branch_admin.full_name,
        sender_email=ctx.branch_admin.email,
    )


def _teacher_user_id(api: BackendAPI, token: str, ctx: SchoolContext) -> int:
    """The teacher's *user* id — what ``recipient_user_ids`` is expressed in.

    Deliberately looked up rather than taken from ``ctx.teacher.user_id``: that
    id comes from the ``POST /staff/teacher/`` response, whose ``id`` is the
    teacher record's, not the user's. This is the same list the compose modal's
    recipient picker reads (``messagingHandler.getSchoolUsers``).
    """
    assert ctx.teacher is not None
    return _school_user_id(api, token, ctx, ctx.teacher.email)


def _school_user_id(
    api: BackendAPI, token: str, ctx: SchoolContext, email: str
) -> int:
    """The *user* id behind a provisioned person's address.

    Every profile create (``/staff/teacher/``, ``/guardian/``, …) answers with
    the profile's own id, never the user's, and ``recipient_user_ids`` is
    expressed in user ids — so the address, which is the one unique thing a
    provisioned person carries, is looked up against the school directory
    instead. This is the same list the compose modal's recipient picker reads
    (``messagingHandler.getSchoolUsers``).
    """
    res = api.get(
        f"/school_profile/{ctx.school_id}/users",
        token=token,
        params={"limit": 100, "search": email},
    )
    if res.status_code >= 400:
        raise NoticeSeedError(
            f"GET /school_profile/{ctx.school_id}/users → {res.status_code}: "
            f"{res.text[:300]}"
        )
    wanted = email.strip().lower()
    for user in res.json() or []:
        if str(user.get("email", "")).strip().lower() == wanted:
            return int(user["id"])
    raise NoticeSeedError(
        f"{email!r} is not among the users of school {ctx.school_id} — "
        f"provisioning phase C created them, so either the branch lookup or "
        f"the create that made them is broken"
    )


@pytest.mark.teacher
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="general.messaging.view.teacher",
    title="Messaging",
    subtitle="Teacher views messaging",
)
def test_teacher_reads_a_message_in_their_inbox(
    notice: Notice,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A teacher opens Messages, reads the office's briefing, and is marked read.

    Every claim is made against what the server sent back: the inbox row comes
    from ``GET /messaging/inbox``, the reader from ``GET /messaging/messages/{id}``
    on the id the notice was actually created under, and the read receipt from
    the ``read_at`` the *next* inbox fetch returns — never from the unread dot's
    styling alone.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    teacher_name = ctx.teacher.full_name

    # Lazily evaluated, so each assertion re-reads whatever is on screen then.
    briefing = page.get_by_text(notice.subject)
    unread_only = page.get_by_role("checkbox")

    with demo.step(f"Sign in as {teacher_name}, a teacher at {ctx.school_name}"):
        login_as(page, base_url, ctx.teacher)

    with demo.step("Open Messages from the General menu"):
        # One click, no branch to choose first — see the section comment.
        nav_entry = page.get_by_role("link", name=as_pattern(NAV_MESSAGES)).first
        expect(nav_entry).to_be_visible()
        nav_entry.click()
        # /module/messages redirects straight to the inbox.
        page.wait_for_url(INBOX_URL, timeout=25_000)
        expect(
            page.get_by_role("heading", name=as_pattern(INBOX_HEADING))
        ).to_be_visible(timeout=20_000)
        expect(page.get_by_text(as_pattern(INBOX_LOAD_FAILURE))).to_have_count(0)

    with demo.step("The whole mailbox is theirs — inbox, sent, drafts, "
                   "scheduled and trash"):
        expect(
            page.get_by_role("link", name=as_pattern(FOLDER_LINKS))
        ).to_have_count(FOLDER_COUNT)
        expect(
            page.get_by_placeholder(as_pattern(MAIL_SEARCH_PLACEHOLDER))
        ).to_be_visible()

    with demo.step("The school office's briefing is waiting, still unread"):
        expect(briefing.first).to_be_visible(timeout=20_000)
        expect(page.get_by_text(notice.sender_name).first).to_be_visible()
        # Proof it is unread, and the server's word for it: the filter keeps
        # only rows whose read_at came back null from GET /messaging/inbox.
        expect(page.get_by_text(as_pattern(UNREAD_ONLY_FILTER))).to_be_visible()
        unread_only.first.check()
        expect(briefing.first).to_be_visible()
        unread_only.first.uncheck()

    with demo.step("Open it and read the whole briefing"):
        briefing.first.click()
        page.wait_for_url(
            re.compile(rf"/module/messages/{notice.message_id}\b"), timeout=25_000
        )
        expect(page.get_by_role("heading", name=notice.subject)).to_be_visible(
            timeout=20_000
        )
        expect(page.get_by_text(notice.sender_name).first).to_be_visible()
        expect(page.get_by_text(notice.sender_email).first).to_be_visible()
        expect(page.get_by_text(notice.body).first).to_be_visible()

    with demo.step("Back in the inbox, the mailbox has recorded it as read"):
        page.get_by_role("button", name=as_pattern(BACK_BUTTON)).first.click()
        page.wait_for_url(INBOX_URL, timeout=25_000)
        # The list refetched on the way back, so this row carries the read_at
        # the reader wrote — which is what drops it out of the filter below.
        expect(briefing.first).to_be_visible(timeout=20_000)
        unread_only.first.check()
        expect(briefing).to_have_count(0)
        unread_only.first.uncheck()
        expect(briefing.first).to_be_visible()

    with demo.step("Sent is empty — this teacher has written to nobody"):
        page.get_by_role("link", name=as_pattern(SENT_LINK)).first.click()
        page.wait_for_url(SENT_URL, timeout=25_000)
        expect(page.get_by_text(as_pattern(SENT_EMPTY))).to_be_visible(timeout=20_000)
        expect(briefing).to_have_count(0)

    with demo.step("…and so is Drafts. Reading the post is all today asked for",
                   dwell_ms=1500):
        page.get_by_role("link", name=as_pattern(DRAFTS_LINK)).first.click()
        page.wait_for_url(DRAFTS_URL, timeout=25_000)
        expect(page.get_by_text(as_pattern(DRAFTS_EMPTY))).to_be_visible(timeout=20_000)


# ────────── manage path: the SchoolAdmin writes to a member of staff ─────────
#
# The same licensed school as the view path, from the writing side: one
# message's whole life on this screen — composed, sent, found in Sent, read back
# on its own page, then cleared into Trash.
#
# Why this role and this scenario
#     ``library_and_community`` is the pack that licenses ``messaging`` while
#     excluding fees and most of the academics stack, so nothing this screen
#     touches depends on a module the school lacks. And unlike the teacher, the
#     SchoolAdmin has to earn their way in: ``SideNavigation.canShowSection``
#     drops the whole "General" section — Messages with it — for a SchoolAdmin
#     whose ``useBranchStore`` is empty, and only the branch row's "View" button
#     fills it (``BranchesPage.select_branch``). Opening the branch is therefore
#     step two of the walkthrough rather than a setup detail.
#
# Three things the walkthrough leans on, all recorded in
# ``tests/pages/messaging/mailbox.py``'s docstring: the composer is not a
# ``role="dialog"``; its recipient picker searches the school directory
# server-side from the third character (which is why it is given the teacher's
# address, the one unique thing about a provisioned person); and a message row
# is an unnamed ``<div onClick>``, so the folder is narrowed by search before
# anything is clicked.
#
# Why each assertion is a claim about stored state
#     ``message_id`` comes from the ``POST /messaging/messages`` response, so the
#     reader is opened on a record the server really created. Every folder is its
#     own route, so switching to Sent, then to Trash, remounts ``FolderPage`` and
#     refetches — "it is in Sent", "it is no longer in Sent" and "it is in Trash"
#     are three separate answers from ``MessageService``, not one list the
#     browser was holding. The recipient count and the "sent" chip on that row
#     are rendered from ``SentItemOut``, and the channel chip on the reader from
#     ``MessageOut.channels``.
#
# Channel ``inapp`` only, and asserted rather than assumed: ``_deliver_external``
# returns immediately unless the message carries ``email``/``sms``, so this
# cannot trip over the suppressed mailer (see the run notes on the Gmail quota).

MANAGE_SCENARIO = "library_and_community"

# Unique per execution, not merely per run: the whole batch shares one
# provisioned school, so a rerun in the same process must not leave two messages
# the folder search cannot tell apart. Carries the "TEST" prefix the orphan
# sweeper matches on.
_MANAGE_STAMP = f"{run_tag()}-manage-{uuid.uuid4().hex[:4]}"

MANAGE_SUBJECT = f"TEST Library Week notice {_MANAGE_STAMP}"
# Deliberately under 140 characters: that is where ``messaging.py::_preview``
# truncates, so the folder row shows the body verbatim and can be asserted
# against it in full.
MANAGE_BODY = (
    f"TEST Library Week starts on Monday {_MANAGE_STAMP}. Please bring your "
    f"class to the library for their slot."
)


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="general.messaging.manage.school_admin",
    title="Messaging",
    subtitle="SchoolAdmin creates and manages messaging",
)
def test_school_admin_sends_and_manages_a_message(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A SchoolAdmin writes to a member of staff, then manages what they sent."""
    ctx = provisioned_school
    assert MESSAGING_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {MESSAGING_MODULE!r} for the "
        f"manage path — a school without the module has no mailbox to write from"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — and a SchoolAdmin "
        "outside a branch is never offered the General menu Messages lives in"
    )
    assert ctx.teacher is not None, (
        "provisioning created no teacher for this school, so there is nobody in "
        "the directory to address the message to"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    mailbox = MailboxPage(page, base_url)

    branch_name = str(ctx.branches[0]["name"])
    teacher = ctx.teacher
    admin = ctx.school_admin

    with demo.step(f"Sign in as the school administrator at {ctx.school_name}"):
        login_as(page, base_url, admin)

    with demo.step(f"Open {branch_name} — an administrator works inside a branch"):
        # Mandatory, not scenic: the General menu (and with it Messages) stays
        # hidden for a SchoolAdmin until this button fills the branch store.
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Open Messages from the General menu"):
        mailbox.expect_nav_entry()
        mailbox.open_from_sidebar()
        mailbox.expect_folder_rail()
        mailbox.expect_no_load_failure()

    with demo.step(f"Write to {teacher.full_name}, found by address in the "
                   "school directory"):
        composer = mailbox.compose()
        composer.add_recipient(teacher.email, name=teacher.full_name)
        composer.write(subject=MANAGE_SUBJECT, body=MANAGE_BODY)
        # In-app is the only channel armed — nothing here goes near the mailer.
        composer.expect_channels(
            checked=(CHANNEL_IN_APP,), unchecked=(CHANNEL_EMAIL, CHANNEL_SMS)
        )

    with demo.step("Send it to their mailbox"):
        message_id = composer.send()

    with demo.step("It is in Sent, delivered to one recipient"):
        sent = mailbox.open_folder("Sent")
        sent.search(_MANAGE_STAMP)
        sent.expect_message(
            MANAGE_SUBJECT, preview=MANAGE_BODY, recipients=1, status="sent"
        )

    with demo.step("Open it and read back exactly what the school stored"):
        detail = sent.open_message(MANAGE_SUBJECT)
        detail.expect_loaded(
            message_id=message_id, subject=MANAGE_SUBJECT, body=MANAGE_BODY
        )
        detail.expect_sender(name=admin.full_name, email=admin.email)
        detail.expect_channel("inapp")

    with demo.step("Tidy the mailbox — it leaves Sent and turns up in Trash",
                   dwell_ms=1500):
        sent = detail.trash()
        sent.search(_MANAGE_STAMP)
        sent.expect_message_absent(MANAGE_SUBJECT)
        sent.expect_no_results()

        trash = sent.open_folder("Trash")
        trash.search(_MANAGE_STAMP)
        trash.expect_message(MANAGE_SUBJECT)


# ────────── view path: a guardian reads the office's note about their ward ────
#
# The same licensed school and the same read-only shape as the teacher's
# walkthrough above, from the role furthest from the staffroom: a parent.
#
# Why a guardian has a mailbox at all
#     ``db/repository/permissions.py`` seeds the Guardian role with
#     ``("manage", "messaging")``, and every ``/messaging`` route depends on
#     ``get_current_user`` plus the router-level ``has_feature_access`` licence
#     check and nothing else — who may read which message is decided by
#     ownership inside ``MessageService`` (``_get_recipient`` → "Message not
#     found in your inbox"). So a guardian of a *licensed* school has exactly
#     the mailbox a teacher has, and this test asserts what is in it.
#
# How they get there, which is the one thing that differs from the teacher
#     They type it. ``SideNavigation.canShowSection`` drops the whole "General"
#     section — Community, Groups, Messages and Notifications with it — for a
#     Guardian outright::
#
#         if (currentRoleName?.toLowerCase() === "guardian") return false;
#
#     and no other surface in the app links to ``/module/messages`` (the only
#     other reference is ``MessageRow``'s own row click). ``messages`` is in
#     ``postAuthRedirect.ts::CORE_MODULES``, so ``middleware.ts`` lets the route
#     through and the page mounts and loads normally — the entry is missing from
#     the menu, not from the product.
#
#     That exclusion is a deliberate line of product code, not selector drift,
#     so this test navigates by address rather than "fixing" the sidebar: adding
#     Messages to a guardian's menu would be a behaviour change, and it is
#     flagged for the product owner instead. Nothing here asserts the absence —
#     a guardian who *is* later offered the entry should not fail a test about
#     reading their mail.
#
# Everything else is asserted the same way as the teacher path, and for the same
# reasons: the row comes from ``GET /messaging/inbox``, the reader from
# ``GET /messaging/messages/{id}`` on the id the seed was created under, and
# "read" is the ``read_at`` the *next* inbox fetch returns rather than the unread
# dot's styling. Channel ``inapp`` only, so nothing goes near the suppressed
# mailer.

GUARDIAN_VIEW_SCENARIO = "library_and_community"

# The parent-facing empty state for a mailbox nobody has written from
# (FolderPage.tsx's FOLDER_EMPTY).
INBOX_EMPTY = re.compile(r"^\s*Your inbox is empty\s*$", re.I)


@pytest.fixture
def guardian_notice(provisioned_school: SchoolContext, api: BackendAPI) -> Notice:
    """Put one unread note from the branch office in the guardian's inbox.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls rather than as dead frames at the
    head of the video.

    The sender is the branch administrator for the same reason as the teacher's
    notice: ``MessageService._sender_school_id`` takes the school from the
    sender's own branch, and ``_expand_recipients`` refuses anyone outside it
    ("Cannot message users outside your school"). The guardian was created by
    phase C with the branch selected, so both sit in the same branch.
    """
    ctx = provisioned_school
    assert MESSAGING_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {MESSAGING_MODULE!r} for the "
        f"view path — a school without the module has no mailbox to read"
    )
    assert ctx.guardian is not None, (
        "provisioning created no guardian for this school, so there is no "
        "mailbox to read as"
    )
    assert ctx.branch_admin is not None, (
        "provisioning created no branch administrator, and they are the sender "
        "of the note the guardian is meant to find"
    )

    stamp = f"{run_tag()}-{uuid.uuid4().hex[:6]}"
    subject = f"TEST Parents evening {stamp}"
    # Under 140 characters on purpose: that is where messaging.py::_preview
    # truncates, so the inbox row shows the note verbatim.
    body = (
        f"TEST Parents evening is on Thursday {stamp}. Your ward's class "
        f"teacher will be in the library from four o'clock."
    )

    try:
        token = api.login(ctx.branch_admin.email, ctx.branch_admin.password)[
            "access_token"
        ]
    except Exception as exc:  # noqa: BLE001 — a prerequisite, not the thing under test
        raise NoticeSeedError(
            f"could not sign the branch administrator in to send the note: {exc}"
        ) from exc

    recipient_id = _school_user_id(api, token, ctx, ctx.guardian.email)
    res = api.post(
        "/messaging/messages",
        token=token,
        json={
            "subject": subject,
            "body": body,
            "recipient_user_ids": [recipient_id],
            # inapp only: anything else would reach the suppressed mailer.
            "channels": ["inapp"],
            "school_id": ctx.school_id,
        },
    )
    if res.status_code >= 400:
        raise NoticeSeedError(
            f"POST /messaging/messages → {res.status_code}: {res.text[:300]}"
        )
    payload = res.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
        raise NoticeSeedError(f"POST /messaging/messages returned no id: {payload!r}")

    return Notice(
        message_id=int(payload["id"]),
        subject=subject,
        body=body,
        sender_name=ctx.branch_admin.full_name,
        sender_email=ctx.branch_admin.email,
    )


@pytest.mark.guardian
@pytest.mark.scenario(GUARDIAN_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="general.messaging.view.guardian",
    title="Messaging",
    subtitle="Guardian views messaging",
)
def test_guardian_reads_a_message_in_their_inbox(
    guardian_notice: Notice,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A guardian opens their mailbox, reads the school's note, and is marked read.

    Read-only throughout: the guardian never composes, and Sent and Drafts are
    asserted empty at the end to say so.
    """
    ctx = provisioned_school
    assert ctx.guardian is not None, "provisioning created no guardian for this school"

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    note = guardian_notice
    guardian_name = ctx.guardian.full_name

    mailbox = MailboxPage(page, base_url)
    # Lazily evaluated, so each assertion re-reads whatever is on screen then.
    briefing = page.get_by_text(note.subject)
    unread_only = page.get_by_role("checkbox")

    with demo.step(f"Sign in as {guardian_name}, a parent at {ctx.school_name}"):
        login_as(page, base_url, ctx.guardian)

    with demo.step("Open Messages — a guardian reaches the mailbox by its address"):
        # /module/messages server-redirects to the inbox, which is the same
        # landing every other role's "Messages" link resolves to. Guardians are
        # simply not offered that link — see the section comment.
        goto_module(page, base_url, "messages")
        page.wait_for_url(INBOX_URL, timeout=25_000)
        mailbox.expect_loaded()
        mailbox.expect_no_load_failure()

    with demo.step("The whole mailbox is theirs — inbox, sent, drafts, "
                   "scheduled and trash"):
        mailbox.expect_folder_rail()
        expect(page.get_by_text(as_pattern(INBOX_EMPTY))).to_have_count(0)

    with demo.step("The school office's note about their ward is waiting, unread"):
        mailbox.expect_message(note.subject, preview=note.body)
        expect(page.get_by_text(note.sender_name).first).to_be_visible()
        # Proof it is unread, and the server's word for it: the filter keeps
        # only rows whose read_at came back null from GET /messaging/inbox.
        expect(page.get_by_text(as_pattern(UNREAD_ONLY_FILTER))).to_be_visible()
        unread_only.first.check()
        expect(briefing.first).to_be_visible()
        unread_only.first.uncheck()

    with demo.step("Open it and read the whole note"):
        detail = mailbox.open_message(note.subject)
        detail.expect_loaded(
            message_id=note.message_id, subject=note.subject, body=note.body
        )
        detail.expect_sender(name=note.sender_name, email=note.sender_email)
        # In-app is the only channel it was sent on — nothing here went near
        # the suppressed mailer.
        detail.expect_channel("inapp")

    with demo.step("Back in the inbox, the mailbox has recorded it as read"):
        mailbox = detail.back()
        # The list refetched on the way back, so this row carries the read_at
        # the reader wrote — which is what drops it out of the filter below.
        expect(briefing.first).to_be_visible(timeout=20_000)
        unread_only.first.check()
        expect(briefing).to_have_count(0)
        unread_only.first.uncheck()
        expect(briefing.first).to_be_visible()

    with demo.step("Sent is empty — this parent has written to nobody"):
        mailbox = mailbox.open_folder("Sent")
        expect(page.get_by_text(as_pattern(SENT_EMPTY))).to_be_visible(timeout=20_000)
        expect(briefing).to_have_count(0)

    with demo.step("…and so is Drafts. Reading the school's note is all today "
                   "asked for", dwell_ms=1500):
        mailbox.open_folder("Drafts")
        expect(page.get_by_text(as_pattern(DRAFTS_EMPTY))).to_be_visible(timeout=20_000)
