"""/module/community — the school-wide feed, and one post's detail page.

Two screens, one module

    ``CommunityPage`` is ``/module/community``: the feed on the left, "My
    Groups" / "Suggested Groups" on the right, and — for a SchoolAdmin only —
    the inline composer above it (``page.tsx`` renders that card behind
    ``isSchoolAdmin``, read from ``useRolePermissionsStore``). ``PostDetailPage``
    is ``/module/community/posts/{id}``, which the post's "⋯ → View details"
    menu routes to and where the full comment thread lives.

Two things about this route that are not obvious, recorded so the next unit does
not re-derive them:

* **A SchoolAdmin has to be inside a branch before Community exists at all.**
  ``SideNavigation.canShowSection`` drops the whole "General" section for a
  SchoolAdmin while ``useBranchStore`` is empty, and that store is only filled by
  the "View" button on a branch row (``BranchesPage.select_branch``). Convenient
  side effect: that same button routes to ``/module/community``, so selecting the
  branch *is* the way a real admin arrives here.

* **The composer's group picker searches everything except the group you
  actually want.** ``CreatePostModal.searchResults`` filters ``!g.is_system``,
  and the one group a freshly provisioned school has is the system group
  ``"<school> Community"`` that ``api/routes/school.py`` seeds on create. It is
  offered instead as the pinned row at the top of the dropdown, labelled "All /
  Everyone" — which is why :meth:`CommunityPage.create_post` clicks that row
  rather than typing a group name that would never match.

Locating things without test ids
    The post card and each comment carry an icon-only "⋯" trigger with no
    accessible name. Both are Radix ``DropdownMenu.Trigger``s, so they are found
    by ``aria-haspopup="menu"`` — scoped to the page's ``<main>`` (the feed
    column, and the only ``<main>`` on either route), which keeps the topbar's
    own menus out of the match. Each caller first narrows the feed to a single
    post — see :meth:`CommunityPage.search` — and asserts the trigger count is 1
    before clicking, so "the first menu" is provably the post's own.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, Response, expect

from tests.pages.base import BasePage, as_pattern

# ── routes ───────────────────────────────────────────────────────────────────
FEED_URL = re.compile(r"/module/community(?:$|[?#])")
POST_DETAIL_URL = re.compile(r"/module/community/posts/(\d+)")

# The one write this module makes. Anchored so it cannot also match
# POST /feed/posts/upload-media or POST /feed/posts/{id}/comments.
CREATE_POST_ENDPOINT = re.compile(r"/feed/posts(?:\?|$)")

# ── sidebar (SideNavigation/nav-config.tsx, "General") ───────────────────────
# Anchored: "Community" is also the feed's own <h2>, and the sidebar entry is
# what proves the module was licensed and the branch chosen.
NAV_COMMUNITY = re.compile(r"^\s*Community\s*$", re.I)

# ── feed chrome (community/page.tsx) ─────────────────────────────────────────
PAGE_HEADING = re.compile(r"^\s*Community\s*$", re.I)
PAGE_SUBHEADING = re.compile(r"Share updates, ask questions", re.I)
COMPOSER_TRIGGER = re.compile(r"Share something with the community", re.I)
# The empty state's second way in — also rendered behind ``isSchoolAdmin``, so a
# reader has to be shown neither.
CREATE_FIRST_POST = re.compile(r"^\s*Create the first post\s*$", re.I)
SEARCH_FIELD = re.compile(r"Search posts", re.I)
REFRESH_BUTTON = re.compile(r"^\s*Refresh\s*$", re.I)
LOAD_FAILURE = re.compile(r"^\s*Failed to load posts\s*$", re.I)
END_OF_FEED = re.compile(r"reached the end of the feed", re.I)

# ── the right-hand rail (components/CommunitySidebar.tsx) ────────────────────
MY_GROUPS_HEADING = re.compile(r"^\s*My Groups\s*$", re.I)
NO_GROUPS_JOINED = re.compile(r"haven.t joined any groups yet", re.I)

# ── the create-post modal (components/feed/CreatePostModal.tsx) ──────────────
CREATE_POST_TITLE = re.compile(r"^\s*Create Post\s*$", re.I)
CONTENT_FIELD = re.compile(r"Share an update, ask a question", re.I)
# The input is `disabled` while the groups fetch is in flight, and its
# placeholder says so — either spelling is the same box.
GROUP_SEARCH_FIELD = re.compile(r"(Search|Loading) groups", re.I)
# The pinned system-group row renders BOTH labels in one `div[role="button"]`:
# "All" on the left, "Everyone" on the right. `filter(has_text=…)` matches the
# row's whole text, so the pattern must not be anchored to "Everyone" alone —
# that is the right-hand span's text, never the row's. Playwright joins the two
# spans with no separator, so the row reads "AllEveryone" — a `\b` in front of
# "Everyone" would not match either. Bare "Everyone" is still unique to this
# row: every search result ends in "Public"/"Private" instead.
EVERYONE_ROW = re.compile(r"Everyone", re.I)
SELECTED_ALL_CHIP = re.compile(r"^\s*All\s*$", re.I)
ALLOW_COMMENTS_TOGGLE = re.compile(r"^\s*Allow comments\s*$", re.I)
PUBLISH_BUTTON = re.compile(r"^\s*(Publish Post|Publishing)", re.I)
POST_PUBLISHED_TOAST = re.compile(r"^\s*Post published\s*$", re.I)

# ── the post card's menu (components/feed/PostCard.tsx) ──────────────────────
MENU_TRIGGER = 'button[aria-haspopup="menu"]'
VIEW_DETAILS_ITEM = re.compile(r"^\s*View details\s*$", re.I)

# ── the detail page (community/posts/[id]/page.tsx) ──────────────────────────
BACK_BUTTON = re.compile(r"^\s*Back\s*$", re.I)
COMMENTS_HEADING = re.compile(r"^\s*Comments\b", re.I)
COMMENT_FIELD = re.compile(r"Write a comment", re.I)
COMMENT_SUBMIT = re.compile(r"^\s*(Comment|Posting)", re.I)
COMMENT_ADDED_TOAST = re.compile(r"^\s*Comment added\s*$", re.I)
EDIT_ITEM = re.compile(r"^\s*Edit\s*$", re.I)
SAVE_EDIT_BUTTON = re.compile(r"^\s*Sav(e|ing)", re.I)
COMMENT_UPDATED_TOAST = re.compile(r"^\s*Comment updated\s*$", re.I)
EDITED_MARKER = re.compile(r"·\s*edited", re.I)


class CommunityPage(BasePage):
    """The school-wide feed at /module/community."""

    URL = "/module/community"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "CommunityPage":
        super().open()
        self.expect_loaded()
        return self

    def open_from_sidebar(self) -> "CommunityPage":
        """Reach the feed the way a real user does — the General menu.

        Falls back to the route when the sidebar is collapsed (it is on narrow
        viewports); how the user got here is worth showing, but it is not what
        this page object asserts.
        """
        link = self.page.get_by_role("link", name=as_pattern(NAV_COMMUNITY)).first
        if link.count():
            link.click()
            self.page.wait_for_url(FEED_URL, timeout=25_000)
        else:
            self.page.goto(self.absolute(self.URL))
        self.expect_loaded()
        return self

    def expect_nav_entry(self) -> None:
        """The General → Community entry is offered.

        Only true once the SchoolAdmin is inside a branch — see the module
        docstring — so this doubles as the check that the branch took.
        """
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_COMMUNITY)).first
        ).to_be_visible(timeout=25_000)

    def expect_loaded(self) -> None:
        expect(
            self.page.get_by_role("heading", name=as_pattern(PAGE_HEADING)).first
        ).to_be_visible(timeout=25_000)
        expect(self.page.get_by_text(as_pattern(PAGE_SUBHEADING)).first).to_be_visible()
        expect(
            self.page.get_by_role("button", name=as_pattern(REFRESH_BUTTON)).first
        ).to_be_visible(timeout=25_000)

    def expect_no_load_failure(self) -> None:
        """``GET /feed/posts`` did not fall into the page's PageError panel."""
        expect(self.page.get_by_text(as_pattern(LOAD_FAILURE))).to_have_count(0)

    # ───────────────────────── the feed ──────────────────────────

    def feed(self) -> Locator:
        """The feed column — the only ``<main>`` on this route."""
        return self.page.get_by_role("main")

    def search(self, term: str) -> "CommunityPage":
        """Filter the feed by post content or author.

        Client-side over the posts already loaded (``useCommunityFeed`` derives
        ``filteredPosts`` in a ``useMemo``), so this narrows what is on screen
        without refetching — which is exactly what the callers below want: one
        post on screen makes its icon-only "⋯" trigger unambiguous.
        """
        self.page.get_by_placeholder(as_pattern(SEARCH_FIELD)).first.fill(term)
        return self

    def expect_post(self, content: str, *, author: str | None = None) -> None:
        """The post is in the feed, under the name of whoever wrote it.

        Scoped to the feed column: the signed-in user's own name is rendered in
        the topbar too, so a page-wide match on ``author`` would pass whether the
        card carried it or not.
        """
        feed = self.feed()
        expect(
            feed.get_by_text(as_pattern(re.escape(content))).first
        ).to_be_visible(timeout=25_000)
        if author:
            expect(feed.get_by_text(as_pattern(re.escape(author))).first).to_be_visible()

    def expect_post_absent(self, content: str) -> None:
        expect(self.feed().get_by_text(as_pattern(re.escape(content)))).to_have_count(0)

    # ─────────────────── what a reader is offered ────────────────

    def expect_composer_absent(self) -> None:
        """This account may read the feed but not write to it.

        Both ways into the Create Post modal — the "Share something with the
        community…" bar above the feed and the empty state's "Create the first
        post" button — are rendered behind ``isSchoolAdmin`` in ``page.tsx``, so
        for every other role neither exists. Asserted as a count of zero rather
        than as "not visible": the elements are not merely hidden, they are never
        rendered, and a count would still fail if that ever changed.
        """
        expect(
            self.page.get_by_role("button", name=as_pattern(COMPOSER_TRIGGER))
        ).to_have_count(0)
        expect(
            self.page.get_by_role("button", name=as_pattern(CREATE_FIRST_POST))
        ).to_have_count(0)

    def sidebar(self) -> Locator:
        """The right-hand rail — the only ``<aside>`` on this route.

        It is ``hidden … lg:flex``, so it is only on screen from the ``lg``
        breakpoint (1024px) up; the demo viewport is wider than that.
        """
        return self.page.locator("aside").first

    def expect_my_group(self, name: str) -> None:
        """``name`` is listed under "My Groups" in the rail.

        The list comes from ``GET /groups/group/my-groups``, which for a pupil or
        a teacher resolves through ``GroupService.is_user_in_auto_group`` — i.e.
        the school's auto-seeded "<school> Community" group is theirs by virtue
        of the branch their account belongs to, not by anything the browser
        decided.
        """
        rail = self.sidebar()
        expect(
            rail.get_by_role("heading", name=as_pattern(MY_GROUPS_HEADING)).first
        ).to_be_visible(timeout=25_000)
        expect(rail.get_by_text(as_pattern(NO_GROUPS_JOINED))).to_have_count(0)
        expect(
            rail.get_by_text(as_pattern(re.escape(name))).first
        ).to_be_visible(timeout=25_000)

    # ──────────────────── writing a post ─────────────────────────

    def open_composer(self) -> "CommunityPage":
        """Open the Create Post modal from the inline composer.

        Clicks the "Share something with the community…" bar rather than the
        "Post" button beside it: the button's label is ``hidden sm:inline``, so
        on a narrow viewport it has no accessible name at all, while the bar
        always carries its text.
        """
        self.page.get_by_role("button", name=as_pattern(COMPOSER_TRIGGER)).first.click()
        expect(self.dialog()).to_be_visible(timeout=15_000)
        expect(
            self.dialog().get_by_role("heading", name=as_pattern(CREATE_POST_TITLE))
        ).to_be_visible()
        return self

    def compose(self, content: str) -> "CommunityPage":
        """Type the post and address it to the whole school."""
        dialog = self.dialog()
        dialog.get_by_placeholder(as_pattern(CONTENT_FIELD)).first.fill(content)
        self._choose_everyone()
        return self

    def publish(self) -> int:
        """Publish the composed post; returns the id the backend assigned it.

        The id comes from the ``POST /feed/posts`` response, so everything a
        caller later asserts about the detail page is anchored on a record the
        server really created rather than on the browser's own optimism.
        """
        dialog = self.dialog()
        with self.page.expect_response(_is_create_post_response, timeout=45_000) as info:
            dialog.get_by_role("button", name=as_pattern(PUBLISH_BUTTON)).first.click()
        response = info.value

        self.expect_toast(POST_PUBLISHED_TOAST, timeout_ms=20_000)
        expect(dialog).to_be_hidden(timeout=15_000)
        return _post_id_from(response)

    def create_post(self, content: str) -> int:
        """Compose and publish in one call; returns the new post's id."""
        self.open_composer().compose(content)
        return self.publish()

    def expect_comments_allowed(self) -> None:
        """The modal offers comments on by default — the thread this unit later
        writes into is a choice the author made, not an accident."""
        expect(
            self.dialog().get_by_text(as_pattern(ALLOW_COMMENTS_TOGGLE)).first
        ).to_be_visible()

    def _choose_everyone(self) -> None:
        """Pick the pinned "All / Everyone" row — the school's system group.

        Waiting for the search box to become *enabled* is how the group fetch is
        waited on: ``CreatePostModal`` disables it while ``groupsLoading``, and
        the pinned row is only rendered once a system group came back.
        """
        dialog = self.dialog()
        search = dialog.get_by_placeholder(as_pattern(GROUP_SEARCH_FIELD)).first
        expect(search).to_be_enabled(timeout=30_000)
        search.click()

        row = dialog.locator('div[role="button"]').filter(
            has_text=as_pattern(EVERYONE_ROW)
        ).first
        expect(row).to_be_visible(timeout=15_000)
        row.click()

        # The dropdown closes on selection and the choice becomes a chip.
        expect(dialog.get_by_text(as_pattern(SELECTED_ALL_CHIP)).first).to_be_visible(
            timeout=10_000
        )

    # ─────────────────── opening one post ────────────────────────

    def open_post_details(self) -> "PostDetailPage":
        """Open the only post on screen via its "⋯ → View details" menu.

        Deliberately takes no post argument: the trigger is icon-only and
        unnamed, so instead of guessing which one belongs to which card, this
        asserts the feed has been narrowed (see :meth:`search`) to exactly one
        post before clicking.
        """
        triggers = self.feed().locator(MENU_TRIGGER)
        expect(triggers).to_have_count(1, timeout=25_000)
        triggers.first.click()
        self.page.get_by_role("menuitem", name=as_pattern(VIEW_DETAILS_ITEM)).click()
        self.page.wait_for_url(POST_DETAIL_URL, timeout=25_000)
        return PostDetailPage(self.page, self.frontend_base_url)


class PostDetailPage(BasePage):
    """One post at /module/community/posts/{id}, with its comment thread."""

    def expect_loaded(self, *, post_id: int, content: str) -> None:
        expect(self.page).to_have_url(
            re.compile(rf"/module/community/posts/{post_id}(?:$|[?#])"), timeout=25_000
        )
        expect(
            self.page.get_by_text(as_pattern(re.escape(content))).first
        ).to_be_visible(timeout=25_000)

    def expect_comment_count(self, count: int) -> None:
        """The "Comments (n)" header, which counts what the server returned."""
        expect(
            self.page.get_by_role("heading", name=as_pattern(COMMENTS_HEADING)).first
        ).to_contain_text(as_pattern(rf"\(\s*{count}\s*\)"), timeout=25_000)

    def add_comment(self, text: str) -> None:
        self.page.get_by_placeholder(as_pattern(COMMENT_FIELD)).first.fill(text)
        self.page.get_by_role("button", name=as_pattern(COMMENT_SUBMIT)).first.click()
        self.expect_toast(COMMENT_ADDED_TOAST, timeout_ms=20_000)

    def expect_comment(self, text: str, *, edited: bool = False) -> None:
        thread = self.page.get_by_role("main")
        expect(
            thread.get_by_text(as_pattern(re.escape(text))).first
        ).to_be_visible(timeout=25_000)
        if edited:
            expect(thread.get_by_text(as_pattern(EDITED_MARKER)).first).to_be_visible()

    def expect_author(self, name: str) -> None:
        """The post is attributed to ``name``.

        Scoped to the thread column: the signed-in user's own name is rendered in
        the topbar, so a page-wide match would say nothing about the card.
        """
        expect(
            self.page.get_by_role("main").get_by_text(as_pattern(re.escape(name))).first
        ).to_be_visible(timeout=25_000)

    def expect_write_controls_absent(self) -> None:
        """Nothing on this thread is this account's to change.

        The comment "⋯" menu — the page's only ``DropdownMenu``, and the only
        route to Edit or Delete — is rendered behind ``isAuthor``, so a reader
        looking at someone else's thread is offered no trigger at all.
        """
        expect(self.page.get_by_role("main").locator(MENU_TRIGGER)).to_have_count(0)

    def expect_comment_absent(self, text: str) -> None:
        expect(
            self.page.get_by_role("main").get_by_text(as_pattern(re.escape(text)))
        ).to_have_count(0)

    def edit_comment(self, new_text: str) -> None:
        """Rewrite the only comment on the page through its "⋯ → Edit" menu.

        The edit box is the *last* textbox in the thread column: the composer
        stays mounted above it, and the inline editor carries no placeholder of
        its own to match on. Only the comment's own author is offered the menu
        (``isAuthor``), so a trigger found here is provably on this user's
        comment.
        """
        thread = self.page.get_by_role("main")
        triggers = thread.locator(MENU_TRIGGER)
        expect(triggers).to_have_count(1, timeout=25_000)
        triggers.first.click()
        self.page.get_by_role("menuitem", name=as_pattern(EDIT_ITEM)).click()

        editor = thread.get_by_role("textbox").last
        expect(editor).to_be_visible(timeout=15_000)
        editor.fill(new_text)

        self.page.get_by_role("button", name=as_pattern(SAVE_EDIT_BUTTON)).first.click()
        self.expect_toast(COMMENT_UPDATED_TOAST, timeout_ms=20_000)

    def back_to_feed(self) -> CommunityPage:
        self.page.get_by_role("button", name=as_pattern(BACK_BUTTON)).first.click()
        self.page.wait_for_url(FEED_URL, timeout=25_000)
        feed = CommunityPage(self.page, self.frontend_base_url)
        feed.expect_loaded()
        return feed


def _is_create_post_response(response: Response) -> bool:
    return (
        response.request.method == "POST"
        and CREATE_POST_ENDPOINT.search(response.url) is not None
    )


def _post_id_from(response: Response) -> int:
    """The new post's id, from the ``List[PostBriefOut]`` the create returns.

    One post per group is written (``FeedService.create_post`` fans a single
    submission out across the groups it was addressed to), so a post addressed
    to "All" alone comes back as a one-element list.
    """
    if not response.ok:
        raise AssertionError(
            f"POST /feed/posts failed: {response.status} {response.text()[:300]}"
        )
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise AssertionError(f"POST /feed/posts returned no post: {payload!r}")
    return int(payload[0]["id"])
