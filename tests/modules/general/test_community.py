"""/module/community — the school-wide feed a SchoolAdmin publishes to.

Manage path: the SchoolAdmin of the ``library_and_community`` school opens the
branch's Community feed, publishes an announcement to the whole school, opens it
in full, comments on it and then takes that comment back down
(``test_school_admin_publishes_and_manages_a_community_post``).

View path: a pupil of the same school signs in, opens Community from the General
menu, finds the school's notice in the feed and reads the thread on it —
offered no composer anywhere, because publishing to the school is the
administrator's privilege alone
(``test_student_reads_the_school_community_noticeboard``).

Negative path: the SchoolAdmin of the ``minimal`` school, whose pack holds only
``school_configuration`` and ``school_admin_dashboard``, gets no feed at all
(``test_community_denied_for_school_admin_when_module_disabled``). The comment
above that test records where the denial lives and what had to be fixed in the
backend for it to exist.

Three things about this module that are not obvious from the route, recorded
here so the next unit does not re-derive them:

* **Community is branch-gated for a SchoolAdmin, not module-gated.**
  ``SideNavigation.canShowSection`` hides the whole "General" section — Community
  included — from a SchoolAdmin while ``useBranchStore`` is empty, whatever the
  feature pack says. The store is filled only by the "View" button on a branch
  row (``BranchesPage.select_branch``), which conveniently routes to
  ``/module/community`` itself: opening the branch *is* how an admin arrives
  here, and that is the walkthrough's second step.

* **Only a SchoolAdmin gets a composer.** ``page.tsx`` renders the "Share
  something with the community…" card and the empty state's "Create the first
  post" button behind ``isSchoolAdmin``, and the backend agrees for the school's
  system group: ``GroupPermissionService.can_post`` returns True outright for a
  school admin of that group's school, while everyone else needs an explicit
  owner/admin membership. So publishing to the whole school is this role's
  privilege, which is why the manage unit belongs to it.

* **Nothing on this feed can be rewritten, and that is deliberate.** The comment
  "⋯" menu offers Edit, and it calls ``PUT /feed/comments/{id}``
  (``src/lib/handlers/feedCommentHandler.ts``) — a route
  ``newschoolapp/api/routes/feed.py`` does not declare and must not gain. Posts
  and comments here are immutable by design, like a tweet; the frontend's edit
  affordance is the dead end. So the "edit" half of this unit's manage intent is
  moderation: the administrator deletes the comment
  (``DELETE /feed/comments/{id}``, which the backend does implement) rather than
  rewriting it. Do not "fix" this by adding the update route.

* **The group the post is addressed to is the auto-seeded one.**
  ``api/routes/school.py`` calls ``ensure_school_community_group`` when the
  school is created, giving every school exactly one system group named
  "<school> Community". ``CreatePostModal`` deliberately excludes system groups
  from its type-ahead (``searchResults`` filters ``!g.is_system``) and pins that
  group to the top of the dropdown as "All / Everyone" instead — so a test that
  typed a group name would search forever. ``CommunityPage.create_post`` clicks
  the pinned row.

What the walkthrough proves
    The post id every later assertion hangs off comes from the
    ``POST /feed/posts`` response, and the detail page is then read back from
    ``GET /feed/posts/{id}`` — a separate request, on a separate route, that only
    answers with the content, the author and the comment count the server
    actually stored. The removal is asserted the same way: the delete is held to
    a 204 rather than to its toast, and the thread is then re-opened from the
    feed so the empty count comes from the server, not from the local state
    ``handleDeleteComment`` trimmed on its own.
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
from tests.pages.community.community import (
    COMPOSER_TRIGGER,
    LOAD_FAILURE,
    PAGE_HEADING,
    PAGE_SUBHEADING,
    REFRESH_BUTTON,
    SEARCH_FIELD,
    CommunityPage,
)
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

COMMUNITY_MODULE = "community"

# ─────────────── manage path: the SchoolAdmin runs the noticeboard ───────────
#
# ``library_and_community`` is the right plan for this: it licenses ``community``
# alongside messaging and the library, and excludes fees and the academics
# stack, so nothing this screen touches depends on a module the school lacks.
#
# The unit is deliberately one post's whole life on this screen — publish it,
# open it, comment on it, correct the comment — because each step is asserted
# against what the *next* screen loaded from the server rather than against the
# toast that announced it. A write the frontend reported but never stored fails
# on the following step instead of passing quietly.

MANAGE_SCENARIO = "library_and_community"

# Distinct from every other post in this school's feed. ``run_tag`` alone is not
# enough: the whole batch shares one provisioned school, so the view path's
# notice below carries the same tag and the searches would collide. The uuid is
# drawn once per process, which is once per selection of this test. Carries the
# "TEST" prefix the orphan sweeper matches on.
_STAMP = f"{run_tag()}-{uuid.uuid4().hex[:4]}"

POST_CONTENT = (
    f"TEST Reading Week starts on Monday {_STAMP}. The library opens at 7am all "
    f"week and every class gets a slot with the librarian."
)
COMMENT_TEXT = f"TEST Slot times go up on the noticeboard tomorrow {_STAMP}."


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="general.community.manage.school_admin",
    title="Community",
    subtitle="SchoolAdmin creates and manages community",
)
def test_school_admin_publishes_and_manages_a_community_post(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A SchoolAdmin announces something to the whole school, then manages it.

    Every claim is made against a screen the server refilled: the feed after its
    refetch, the detail page after ``GET /feed/posts/{id}``, and the comment
    thread after each write — never against the success toast alone.
    """
    ctx = provisioned_school
    assert COMMUNITY_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {COMMUNITY_MODULE!r} for the "
        f"manage path — a school without the module has no feed to manage"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — and a SchoolAdmin "
        "outside a branch is never offered the General menu Community lives in"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    community = CommunityPage(page, base_url)

    branch_name = str(ctx.branches[0]["name"])
    admin_name = ctx.school_admin.full_name

    with demo.step(f"Sign in as the school administrator at {ctx.school_name}"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Open {branch_name} — the branch console lands on its "
                   "Community feed"):
        # Mandatory, not scenic: the General menu (and with it Community) stays
        # hidden for a SchoolAdmin until this button fills the branch store.
        BranchesPage(page, base_url).select_branch(branch_name)
        community.expect_nav_entry()
        community.expect_loaded()
        community.expect_no_load_failure()

    with demo.step("Write an announcement and address it to the whole school"):
        community.open_composer()
        community.expect_comments_allowed()
        community.compose(POST_CONTENT)

    with demo.step("Publish it to the community"):
        post_id = community.publish()

    with demo.step("It is now in the feed, under the administrator's name"):
        # The feed refetched on publish; searching by the stamp narrows it to
        # this one post, which is also what makes the card's unnamed "⋯" menu
        # unambiguous. The stamp, not a prefix of the sentence: this school's
        # feed also carries the view path's notice, and both open "TEST …".
        community.search(_STAMP)
        community.expect_post(POST_CONTENT, author=admin_name)
        community.expect_no_load_failure()

    with demo.step("Open the post in full to see the conversation on it"):
        detail = community.open_post_details()
        detail.expect_loaded(post_id=post_id, content=POST_CONTENT)
        detail.expect_comment_count(0)

    with demo.step("Add a note to the thread"):
        detail.add_comment(COMMENT_TEXT)
        detail.expect_comment(COMMENT_TEXT)
        detail.expect_comment_count(1)

    with demo.step("Take the note back down again — moderating the thread is "
                   "the administrator's job"):
        # Deliberately delete rather than rewrite. The "⋯" menu also offers Edit,
        # but it calls PUT /feed/comments/{id}, which the backend does not
        # implement and is not meant to: posts and comments on this feed are
        # immutable by design. Removal is the correction this product supports,
        # and the page object asserts the 204 rather than the toast.
        detail.delete_comment()
        detail.expect_comment_absent(COMMENT_TEXT)

    with demo.step("Back to the feed — the announcement stands, its thread now "
                   "clear", dwell_ms=1500):
        # Re-read rather than trust the screen: handleDeleteComment empties the
        # thread from local state, so only a fresh GET /feed/posts/{id} proves
        # the comment is gone from the server as well.
        feed = detail.back_to_feed()
        feed.search(_STAMP)
        feed.expect_post(POST_CONTENT, author=admin_name)
        reopened = feed.open_post_details()
        reopened.expect_loaded(post_id=post_id, content=POST_CONTENT)
        reopened.expect_comment_count(0)
        reopened.expect_comment_absent(COMMENT_TEXT)


# ─────────── negative path: the plan does not include the community ──────────
#
# Where the denial lives, and what had to be fixed for it to exist at all
#     Not in the sidebar, and not in a route guard. ``community`` is listed in
#     ``smsfrontend/src/utils/postAuthRedirect.ts::CORE_MODULES``, and both
#     ``middleware.ts`` and ``usePermissionGuard`` consult that list precisely to
#     *skip* their feature-flag check for it; the sidebar's "General" section
#     carries neither a ``permissionsGate`` nor a per-item ``module``, and
#     ``SideNavigation.canShowItem`` returns ``true`` outright for a SchoolAdmin
#     anyway. So the page really does mount for this role and really does start
#     fetching, exactly as in ``test_change_requests.py``.
#
#     What must refuse them is the backend — and it did not. Every route on
#     ``newschoolapp/api/routes/feed.py`` depended on ``get_current_user`` alone:
#     no ``has_permission``, no ``has_feature_access``. Yet
#     ``services/feature_pack_service.SYSTEM_MODULE_GROUPS`` offers ``community``
#     in its "general" group, so a pack can be built without it — as ``minimal``
#     is — which made that toggle decorative: an unlicensed school could still
#     read the whole feed, post to it, comment and react. ``feed_router`` now
#     declares ``dependencies=[Depends(has_feature_access("community"))]``, which
#     is a licence check only: who may do what *inside* the feed is still decided
#     per action by ``services/group_permission_service.py``, so every role keeps
#     the access it has today whenever the module is licensed, and a school with
#     no pack at all stays unrestricted. See ``state/backend_patches.md``.
#
#     The UI consequence follows from the 403's detail. The axios interceptor in
#     ``src/utils/handleErrorMessage.ts`` recognises "not available in your plan"
#     (``shouldRedirectToNoAccess``) and performs a hard ``window.location``
#     redirect to **/auth/no-access**, rejecting with ``FeatureNotAvailableError``
#     before ``useCommunityFeed``'s own ``catch`` can paint its PageError panel.
#     So the landing page, not an error panel, is the denial surface — which is
#     why "Failed to load posts" is asserted *absent* below rather than expected.
#
# Two things deliberately not asserted
#     1. That the sidebar hides the entry. It is hidden here, but for the wrong
#        reason: ``canShowSection`` drops the whole "General" section for a
#        SchoolAdmin who has not opened a branch (see the manage test above), so
#        its absence would say nothing about this school's licence.
#     2. That ``/module/groups`` is refused. ``groups`` is not a licensable
#        module — ``GroupService`` also backs class groups, which the academics
#        stack depends on — so the community licence has no claim over it.

DENIED_SCENARIO = "minimal"

# ``config/module_catalog.py``'s route for this module — the same one
# ``CommunityPage.URL`` drives on the manage path.
COMMUNITY_ROUTE = "community"

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

# Where the frontend sends a user it has decided is not allowed in, and the copy
# it greets them with (src/app/auth/no-access/page.tsx).
NO_ACCESS_URL = re.compile(r"/auth/no-access")
ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)

# The feed's own chrome, none of which may reach them. PAGE_HEADING …
# LOAD_FAILURE are the same patterns the manage path drives the screen with, so
# the two units cannot drift apart on what "the Community page" looks like.
# These three belong to CommunitySidebar.tsx and page.tsx's empty state.
MY_GROUPS_CARD = re.compile(r"^\s*My Groups\s*$", re.I)
SUGGESTED_GROUPS_CARD = re.compile(r"^\s*Suggested Groups\s*$", re.I)
COMMUNITY_GUIDELINES_CARD = re.compile(r"^\s*Community Guidelines\s*$", re.I)
EMPTY_FEED = re.compile(r"^\s*No posts yet\s*$", re.I)

# Bodies for the write refusals. The 403 lands before the body is validated, so
# valid ones simply remove 422 as a possible explanation for a pass.
UNLICENSED_POST = "TEST post that must never reach an unlicensed school's feed."
UNLICENSED_COMMENT = "TEST comment that must never be accepted."


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_community_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `community` off the pack, there is no feed to read and none to post to."""
    ctx = provisioned_school
    if COMMUNITY_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {COMMUNITY_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had community rights anyway", which would make the 403s
    # vacuous.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert COMMUNITY_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{COMMUNITY_MODULE!r} permission, so this test would be asserting a "
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
        f"{COMMUNITY_MODULE!r} proves nothing about the gate — an unassigned "
        f"school is unrestricted by design. Provisioning phase A assigns one; "
        f"check that it did."
    )
    assert COMMUNITY_MODULE not in (body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {COMMUNITY_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every /feed route is refused ────────────────────
    #
    # Reads and writes alike, so the gate cannot regress into being merely
    # read-only or merely cosmetic. The ids are deliberately arbitrary: the
    # dependency is declared on the router, solved before the path/query/body
    # params are validated and long before any row is looked up, so a 404 or a
    # 422 here would itself be the failure.
    refusals = {
        # What the feed itself calls on mount — school_id and all
        # (src/lib/handlers/feedHandler.ts::getPosts).
        "list_posts": api.get(
            f"/feed/posts?limit=20&cursor=&school_id={ctx.school_id}", token=token
        ),
        # The detail page behind a card's "View details".
        "post_detail": api.get("/feed/posts/1?comments_limit=10", token=token),
        "list_comments": api.get("/feed/posts/1/comments?limit=20", token=token),
        # Publishing — the composer's own call, and its media upload.
        "create_post": api.post(
            "/feed/posts",
            token=token,
            json={
                "content": UNLICENSED_POST,
                "group_ids": [1],
                "allow_comments": True,
                "school_id": ctx.school_id,
            },
        ),
        "upload_media": api.post("/feed/posts/upload-media", token=token),
        "delete_post": api.delete("/feed/posts/1", token=token),
        # The comment thread.
        "create_comment": api.post(
            "/feed/posts/1/comments", token=token, json={"content": UNLICENSED_COMMENT}
        ),
        "delete_comment": api.delete("/feed/comments/1", token=token),
        # And every reaction control on both a post and a comment.
        "react_to_post": api.put(
            "/feed/posts/1/reactions", token=token, json={"type": "react"}
        ),
        "unreact_post": api.delete("/feed/posts/1/reactions?type=react", token=token),
        "react_to_comment": api.put(
            "/feed/comments/1/reactions", token=token, json={"type": "react"}
        ),
        "unreact_comment": api.delete(
            "/feed/comments/1/reactions?type=react", token=token
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{COMMUNITY_MODULE!r}, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a community feed in front of them ───────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Straight to the route, not via the branch row's "View" button. That button
    # is how a real admin arrives here (see the manage path) but it is no use as
    # a probe on *this* school: it routes to /module/community and the
    # interceptor bounces straight off it again, so
    # ``BranchesPage.select_branch``'s own ``wait_for_url`` would be racing the
    # redirect it is supposed to be proving. Nothing on this screen needs the
    # branch store anyway — ``useCommunityFeed`` scopes the feed by
    # ``school_config.id``, which login already put in the auth store.
    goto_module(page, frontend_base_url, COMMUNITY_ROUTE)
    # The redirect is a hard window.location assignment made by the axios
    # interceptor once the feed's own fetch is refused, so waiting for the URL is
    # also what stops the "workspace is absent" assertions below from passing
    # merely because the page had not finished loading.
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    expect(page.get_by_role("heading", name=as_pattern(PAGE_HEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(PAGE_SUBHEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(COMPOSER_TRIGGER))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(SEARCH_FIELD))).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(REFRESH_BUTTON))).to_have_count(0)
    expect(page.get_by_text(as_pattern(MY_GROUPS_CARD))).to_have_count(0)
    expect(page.get_by_text(as_pattern(SUGGESTED_GROUPS_CARD))).to_have_count(0)
    expect(page.get_by_text(as_pattern(COMMUNITY_GUIDELINES_CARD))).to_have_count(0)
    # Not even the feed's own "nothing here yet" copy: an empty feed would say
    # the fetch succeeded and returned nothing, which is not the denial.
    expect(page.get_by_text(as_pattern(EMPTY_FEED))).to_have_count(0)
    # Nor its error panel — the interceptor redirects before the catch renders it.
    expect(page.get_by_text(as_pattern(LOAD_FAILURE))).to_have_count(0)


# ──────────── view path: a pupil reads the school's noticeboard ──────────────
#
# The same school and the same screen as the manage path, from the other side of
# it. What the pupil is entitled to is *everything except authorship*:
#
# * **They reach it in one step.** The "General" section is dropped only for a
#   SuperAdmin, a Guardian, and a SchoolAdmin who has not opened a branch
#   (``SideNavigation.canShowSection``); the Community entry inside it carries
#   neither a ``permission`` nor a ``module`` gate. So unlike the administrator,
#   a pupil is offered the link the moment they log in — which is the whole of
#   their navigation story and why this walkthrough is the short one.
#
# * **The feed they get is their school's.** ``useCommunityFeed`` only sends
#   ``school_id`` for an admin role; for everyone else the parameter is omitted
#   and ``FeedService.list_posts`` pins the query to the caller's own school via
#   ``resolve_school_id_for_user``. The pupil therefore cannot be shown another
#   school's noticeboard even by accident, and the notice they do find is one the
#   server matched to their account.
#
# * **They belong to the school group without ever joining it.** The seeded
#   "<school> Community" group is an auto-group, and
#   ``GroupService.is_user_in_auto_group`` resolves membership from the branch on
#   the user record — so it is already under "My Groups" in the rail. Asserting
#   that is asserting a server-side derivation, not a rendering.
#
# * **They are offered nothing to write with.** No composer bar, no "Create the
#   first post", and no "⋯" menu on a comment that is not theirs. That is the
#   read-only half of the same ``isSchoolAdmin`` / ``isAuthor`` pair the manage
#   path exercises from the writing side.
#
# The notice is seeded over the API rather than by depending on the manage test
# having run first — the same setup-only use of ``api`` as
# ``school_provisioning._seed_fee_group``. Two units sharing one session-scoped
# school must not also share an execution order: this one has to pass when it is
# the only test selected.

VIEW_SCENARIO = MANAGE_SCENARIO

# Its own stamp, distinct from the manage path's: both posts live in the same
# school's feed, and the pupil's search has to narrow the feed to exactly one
# card before its unnamed "⋯" menu can be clicked unambiguously.
_VIEW_STAMP = f"{run_tag()}-view-{uuid.uuid4().hex[:4]}"

ANNOUNCEMENT = (
    f"TEST Library Week opens on Monday {_VIEW_STAMP}. The reading room stays "
    f"open until 5pm every day and each class gets a slot with the librarian."
)
ANNOUNCEMENT_REPLY = (
    f"TEST Slot times are posted outside the library {_VIEW_STAMP} — check "
    f"yours before Monday."
)


class AnnouncementSeedError(RuntimeError):
    """The notice the pupil is meant to read could not be seeded."""


@dataclass
class Announcement:
    """The seeded notice, as the pupil should find it."""

    post_id: int
    content: str
    reply: str
    author: str
    group_name: str


@pytest.fixture
def announcement(provisioned_school: SchoolContext, api: BackendAPI) -> Announcement:
    """Put one administrator's notice, with one reply on it, in the school feed.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls rather than as dead frames at the
    head of the video.

    Idempotent by content: the fixture is function-scoped but the school is
    session-scoped, so a rerun in the same process must reuse the notice rather
    than leave two the feed search cannot tell apart.
    """
    ctx = provisioned_school
    assert COMMUNITY_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {COMMUNITY_MODULE!r} for the "
        f"view path — a school without the module has no feed to read"
    )
    assert ctx.student is not None, (
        "provisioning admitted no student for this school, so there is no pupil "
        "to read the noticeboard as"
    )

    try:
        token = api.login(ctx.school_admin.email, ctx.school_admin.password)[
            "access_token"
        ]
    except Exception as exc:  # noqa: BLE001 — a prerequisite, not the thing under test
        raise AnnouncementSeedError(
            f"could not sign the school administrator in to seed the notice: {exc}"
        ) from exc

    group = _school_community_group(api, token, ctx)
    post_id = _existing_post_id(api, token, ctx) or _create_announcement(
        api, token, ctx, group_id=int(group["id"])
    )
    _ensure_reply(api, token, post_id)

    return Announcement(
        post_id=post_id,
        content=ANNOUNCEMENT,
        reply=ANNOUNCEMENT_REPLY,
        author=ctx.school_admin.full_name,
        group_name=str(group["name"]),
    )


@pytest.mark.student
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="general.community.view.student",
    title="Community",
    subtitle="Student views community",
)
def test_student_reads_the_school_community_noticeboard(
    announcement: Announcement,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A pupil signs in, opens Community and reads what the school posted.

    Everything asserted is the server's answer rather than the browser's: the
    feed came back from ``GET /feed/posts`` scoped to this pupil's own school,
    the group in the rail from ``GET /groups/group/my-groups``, and the thread
    from ``GET /feed/posts/{id}`` on the id the notice was actually created
    under.
    """
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    community = CommunityPage(page, base_url)
    pupil = ctx.student.full_name

    with demo.step(f"Sign in as {pupil}, a pupil at {ctx.school_name}"):
        login_as(page, base_url, ctx.student)

    with demo.step("Open Community from the General menu"):
        # A pupil needs no branch and no extra rights to be offered this — see
        # the section comment above.
        community.expect_nav_entry()
        community.open_from_sidebar()
        community.expect_no_load_failure()

    with demo.step("The school's noticeboard, as a pupil sees it — theirs to "
                   "read, not to write to"):
        community.expect_composer_absent()

    with demo.step(f"They already belong to {announcement.group_name}, the "
                   "group the whole school shares"):
        community.expect_my_group(announcement.group_name)

    with demo.step("Look up the notice the school put out about Library Week"):
        community.search(_VIEW_STAMP)
        community.expect_post(announcement.content, author=announcement.author)

    with demo.step("Open it in full to read the whole notice"):
        detail = community.open_post_details()
        detail.expect_loaded(post_id=announcement.post_id, content=announcement.content)
        detail.expect_author(announcement.author)

    with demo.step("The school's own follow-up is waiting on the thread"):
        detail.expect_comment_count(1)
        detail.expect_comment(announcement.reply)
        # Nothing here is this pupil's to change: the comment "⋯" menu is the
        # page's only route to Edit or Delete, and it renders for its author.
        detail.expect_write_controls_absent()

    with demo.step("Back to the feed, where the notice stays put", dwell_ms=1500):
        feed = detail.back_to_feed()
        feed.search(_VIEW_STAMP)
        feed.expect_post(announcement.content, author=announcement.author)
        feed.expect_composer_absent()


# ───────────────────── seeding the notice (setup only) ───────────────────────


def _school_community_group(
    api: BackendAPI, token: str, ctx: SchoolContext
) -> dict:
    """The school's auto-seeded system group — the one "All / Everyone" means.

    ``GET /groups/`` returns every group in the SchoolAdmin's school, and
    ``ensure_school_community_group`` guarantees exactly one system group per
    school (``is_system``, no branch, no class), named "<school> Community".
    """
    res = api.get("/groups/", token=token)
    if res.status_code >= 400:
        raise AnnouncementSeedError(
            f"GET /groups/ → {res.status_code}: {res.text[:300]}"
        )
    groups = res.json() or []
    system = [g for g in groups if g.get("is_system")]
    if not system:
        raise AnnouncementSeedError(
            f"{ctx.school_name!r} has no system community group — "
            f"api/routes/school.py seeds one on create. Groups seen: "
            f"{[g.get('name') for g in groups]}"
        )
    return system[0]


def _existing_post_id(api: BackendAPI, token: str, ctx: SchoolContext) -> int | None:
    """The notice's id if a previous run in this process already posted it."""
    res = api.get(f"/feed/posts?limit=100&school_id={ctx.school_id}", token=token)
    if res.status_code >= 400:
        return None
    for item in (res.json() or {}).get("items", []):
        if str(item.get("content", "")).strip() == ANNOUNCEMENT:
            return int(item["id"])
    return None


def _create_announcement(
    api: BackendAPI, token: str, ctx: SchoolContext, *, group_id: int
) -> int:
    """Publish the notice to the whole school, exactly as the composer does."""
    res = api.post(
        "/feed/posts",
        token=token,
        json={
            "content": ANNOUNCEMENT,
            "group_ids": [group_id],
            "allow_comments": True,
            "school_id": ctx.school_id,
        },
    )
    if res.status_code >= 400:
        raise AnnouncementSeedError(
            f"POST /feed/posts → {res.status_code}: {res.text[:300]}"
        )
    payload = res.json()
    if not isinstance(payload, list) or not payload:
        raise AnnouncementSeedError(f"POST /feed/posts returned no post: {payload!r}")
    return int(payload[0]["id"])


def _ensure_reply(api: BackendAPI, token: str, post_id: int) -> None:
    """Give the notice the one follow-up the pupil is expected to find."""
    detail = api.get(f"/feed/posts/{post_id}?comments_limit=100", token=token)
    if detail.status_code >= 400:
        raise AnnouncementSeedError(
            f"GET /feed/posts/{post_id} → {detail.status_code}: {detail.text[:300]}"
        )
    comments = (detail.json().get("top_level_comments") or {}).get("items") or []
    if any(str(c.get("content", "")).strip() == ANNOUNCEMENT_REPLY for c in comments):
        return

    res = api.post(
        f"/feed/posts/{post_id}/comments",
        token=token,
        json={"content": ANNOUNCEMENT_REPLY},
    )
    if res.status_code >= 400:
        raise AnnouncementSeedError(
            f"POST /feed/posts/{post_id}/comments → {res.status_code}: "
            f"{res.text[:300]}"
        )
