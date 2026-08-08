"""/module/messages — direct messaging (inbox, sent, drafts, scheduled, trash).

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

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as

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
