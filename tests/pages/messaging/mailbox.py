"""/module/messages — the mailbox, its composer, and one message's detail view.

Three screens, one module

    ``MailboxPage`` is any of the five folders ``/module/messages/{inbox,sent,
    drafts,scheduled,trash}``: the folder rail plus "Compose" come from
    ``messages/layout.tsx``, and everything to the right of them — the folder
    heading, the "Search in mail" box and the message rows — from the shared
    ``components/messaging/FolderPage.tsx``. ``/module/messages`` itself only
    server-redirects to the inbox.

    ``ComposeMessage`` is ``components/messaging/ComposeModal.tsx``, which the
    "Compose" button mounts. ``MessageDetailPage`` is
    ``/module/messages/{id}?from={folder}``, which a row click routes to.

Four things about this module that are not obvious, recorded so the next unit
does not re-derive them:

* **A SchoolAdmin has to be inside a branch before Messages exists at all.**
  ``SideNavigation.canShowSection`` drops the whole "General" section — Messages
  with it — for a SchoolAdmin while ``useBranchStore`` is empty, and that store
  is filled only by the "View" button on a branch row
  (``BranchesPage.select_branch``). The item itself carries neither a
  ``permission`` nor a ``module`` gate, so the branch is the only thing standing
  between this role and the mailbox.

* **The composer is not a dialog.** ``ComposeModal`` is a plain positioned
  ``<div>`` — no ``role="dialog"``, no ``aria-modal`` — so ``BasePage.dialog()``
  finds nothing here. Every field is located by its own placeholder instead
  ("Search users…", "Subject", "Write your message here…"), each of which is
  unique on this route, and ``open`` is asserted through the body textarea:
  ``if (!open) return null`` means a closed composer is *unmounted*, not hidden.

* **The recipient picker only searches from the third character**, after a 300ms
  debounce, and only when the auth store carries a school
  (``getSchoolUsers(schoolId, …)`` → ``GET /school_profile/{id}/users``). It
  matches first name, other names or email, so :meth:`ComposeMessage.add_recipient`
  is given an email — the one thing about a provisioned person that is unique.

* **A message row is a ``<div>`` with an ``onClick``**, carrying no role, no
  link and no accessible name. Callers therefore narrow the folder with
  :meth:`MailboxPage.search` first — client-side over the rows already loaded —
  and then click the subject text itself, which bubbles to the row's handler.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, Response, expect

from tests.pages.base import BasePage, as_pattern, goto

# ── routes ───────────────────────────────────────────────────────────────────
FOLDERS = ("inbox", "sent", "drafts", "scheduled", "trash")
MESSAGE_DETAIL_URL = re.compile(r"/module/messages/\d+")

# The one write this page object waits on. Anchored so it cannot also match
# POST /messaging/messages/drafts, /messages/{id}/send or /messages/{id}/trash.
SEND_ENDPOINT = re.compile(r"/messaging/messages(?:\?|$)")

# ── sidebar (SideNavigation/nav-config.tsx, "General") ───────────────────────
# Anchored: "Messages" is the nav entry, and its presence is what proves the
# branch was selected — see the module docstring.
NAV_MESSAGES = re.compile(r"^\s*Messages\s*$", re.I)

# ── mailbox chrome (messages/layout.tsx + FolderPage.tsx) ────────────────────
COMPOSE_BUTTON = re.compile(r"^\s*Compose\s*$", re.I)
FOLDER_LINKS = re.compile(r"^\s*(Inbox|Sent|Drafts|Scheduled|Trash)\s*$", re.I)
MAIL_SEARCH_FIELD = re.compile(r"^\s*Search in mail\s*$", re.I)
NO_SEARCH_RESULTS = re.compile(r"^\s*No results found\s*$", re.I)

# ── the composer (components/messaging/ComposeModal.tsx) ─────────────────────
TO_LABEL = re.compile(r"^\s*To:\s*$", re.I)
USER_SEARCH_FIELD = re.compile(r"^\s*Search users", re.I)
SUBJECT_FIELD = re.compile(r"^\s*Subject\s*$", re.I)
BODY_FIELD = re.compile(r"^\s*Write your message here", re.I)
# CHANNELS in ComposeModal.tsx. Each is an <input type="checkbox"> wrapped by
# its own <label>, which is an association Playwright *does* resolve — unlike
# the bare, unassociated <label>s the rest of this app uses.
CHANNEL_IN_APP = re.compile(r"^\s*In-App\s*$", re.I)
CHANNEL_EMAIL = re.compile(r"^\s*Email\s*$", re.I)
CHANNEL_SMS = re.compile(r"^\s*SMS\s*$", re.I)
SEND_BUTTON = re.compile(r"^\s*(Send|Sending)", re.I)
SAVE_DRAFT_BUTTON = re.compile(r"^\s*(Save draft|Saving)", re.I)
MESSAGE_SENT_TOAST = re.compile(r"^\s*Message sent\s*$", re.I)
DRAFT_SAVED_TOAST = re.compile(r"^\s*Draft saved\s*$", re.I)

# ── one message (messages/[id]/page.tsx) ─────────────────────────────────────
BACK_BUTTON = re.compile(r"^\s*Back\s*$", re.I)
# The toolbar's destructive control is labelled "Delete" when the reader came
# from Sent and "Trash" everywhere else — same handler, same POST /trash.
TRASH_BUTTON = re.compile(r"^\s*(Delete|Trash|Deleting)", re.I)
TRASHED_TOAST = re.compile(r"^\s*Message moved to trash\s*$", re.I)
RECOVER_BUTTON = re.compile(r"^\s*(Recover|Recovering)", re.I)


class MailboxPage(BasePage):
    """One folder of the mailbox at /module/messages/{folder}."""

    URL = "/module/messages/inbox"

    def __init__(self, page: Page, frontend_base_url: str, folder: str = "inbox"):
        super().__init__(page, frontend_base_url)
        self.folder = folder

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "MailboxPage":
        """Go straight to this instance's folder.

        Deliberately not ``super().open()``: ``URL`` is a class attribute and
        the folder is per-instance, so the route is built here rather than by
        mutating shared state.
        """
        goto(self.page, self.absolute(f"/module/messages/{self.folder}"))
        self.expect_loaded()
        return self

    def open_from_sidebar(self) -> "MailboxPage":
        """Reach the mailbox the way a real user does — the General menu.

        Falls back to the route when the sidebar is collapsed (it is on narrow
        viewports); how the user got here is worth showing, but it is not what
        this page object asserts.
        """
        link = self.page.get_by_role("link", name=as_pattern(NAV_MESSAGES)).first
        if link.count():
            link.click()
        else:
            self.page.goto(self.absolute("/module/messages"))
        # /module/messages is a server redirect() to the inbox, so the URL the
        # click settles on is the folder's, never the bare module route.
        self.folder = "inbox"
        self.page.wait_for_url(re.compile(r"/module/messages/inbox"), timeout=25_000)
        self.expect_loaded()
        return self

    def expect_nav_entry(self) -> None:
        """The General → Messages entry is offered.

        Only true once the SchoolAdmin is inside a branch — see the module
        docstring — so this doubles as the check that the branch took.
        """
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_MESSAGES)).first
        ).to_be_visible(timeout=25_000)

    def open_folder(self, name: str) -> "MailboxPage":
        """Switch folders through the mailbox's own rail.

        Each folder is its own route, so this remounts ``FolderPage`` and
        refetches from the server — which is what makes "it is in Sent" and "it
        is no longer in Sent" claims about stored state rather than about a list
        the browser happened to be holding.
        """
        self.page.get_by_role("link", name=as_pattern(rf"^\s*{re.escape(name)}\s*$")).first.click()
        self.folder = name.strip().lower()
        self.page.wait_for_url(
            re.compile(rf"/module/messages/{self.folder}"), timeout=25_000
        )
        self.expect_loaded()
        return self

    def expect_loaded(self) -> None:
        """The folder's own toolbar is on screen, and so is the mailbox rail."""
        expect(
            self.page.get_by_role("heading", name=as_pattern(self._title())).first
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_role("button", name=as_pattern(COMPOSE_BUTTON)).first
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_placeholder(as_pattern(MAIL_SEARCH_FIELD)).first
        ).to_be_visible()

    def expect_folder_rail(self) -> None:
        """All five folders are offered (messages/layout.tsx's ``folders``)."""
        expect(
            self.page.get_by_role("link", name=as_pattern(FOLDER_LINKS))
        ).to_have_count(len(FOLDERS))

    def expect_no_load_failure(self) -> None:
        """``GET /messaging/{folder}`` did not fall into FolderPage's catch."""
        expect(
            self.page.get_by_text(as_pattern(rf"Failed to load {self.folder}"))
        ).to_have_count(0)

    def _title(self) -> str:
        return self.folder.capitalize()

    # ──────────────────────── the folder ─────────────────────────

    def list(self) -> Locator:
        """The message list — the only ``<main>`` on this route."""
        return self.page.get_by_role("main")

    def search(self, term: str) -> "MailboxPage":
        """Filter the folder by subject, preview or sender.

        Client-side over the rows already fetched (``FolderPage`` derives
        ``filtered`` inline), so this narrows what is on screen without
        refetching — which is what makes a row, which carries no accessible name
        of its own, unambiguous to click.
        """
        self.page.get_by_placeholder(as_pattern(MAIL_SEARCH_FIELD)).first.fill(term)
        return self

    def expect_message(
        self,
        subject: str,
        *,
        preview: str | None = None,
        recipients: int | None = None,
        status: str | None = None,
    ) -> None:
        """The message is in this folder, as the server described it.

        ``preview`` is the first 140 characters of the body the backend echoes
        back (``messaging.py::_preview``), ``recipients`` the row's "n
        recipient(s)" line and ``status`` its chip — all three rendered from the
        list response rather than from anything the composer left behind.

        ``status`` is matched against ``<span>``s only: the folder's own heading
        is an ``<h2>`` reading "Sent" and lives inside the same ``<main>``, so a
        text match would otherwise pass on the heading whether the row carried a
        chip or not.
        """
        rows = self.list()
        expect(
            rows.get_by_text(as_pattern(re.escape(subject))).first
        ).to_be_visible(timeout=25_000)
        if preview:
            expect(rows.get_by_text(as_pattern(re.escape(preview))).first).to_be_visible()
        if recipients is not None:
            expect(
                rows.get_by_text(
                    as_pattern(rf"^\s*{recipients}\s+recipients?\s*$")
                ).first
            ).to_be_visible()
        if status:
            chip = rows.locator("span").filter(
                has_text=as_pattern(rf"^\s*{re.escape(status)}\s*$")
            )
            expect(chip.first).to_be_visible(timeout=15_000)

    def expect_message_absent(self, subject: str) -> None:
        expect(self.list().get_by_text(as_pattern(re.escape(subject)))).to_have_count(0)

    def expect_no_results(self) -> None:
        """The search matched nothing — FolderPage's "No results found" state."""
        expect(
            self.list().get_by_text(as_pattern(NO_SEARCH_RESULTS)).first
        ).to_be_visible(timeout=15_000)

    def open_message(self, subject: str) -> "MessageDetailPage":
        """Open a message by clicking its subject.

        The row is an unnamed ``<div onClick>``, so the click lands on the
        subject span and bubbles to it. Callers narrow the folder with
        :meth:`search` first so exactly one row can match.
        """
        self.list().get_by_text(as_pattern(re.escape(subject))).first.click()
        self.page.wait_for_url(MESSAGE_DETAIL_URL, timeout=25_000)
        return MessageDetailPage(self.page, self.frontend_base_url, folder=self.folder)

    # ──────────────────────── composing ──────────────────────────

    def compose(self) -> "ComposeMessage":
        self.page.get_by_role("button", name=as_pattern(COMPOSE_BUTTON)).first.click()
        composer = ComposeMessage(self.page, self.frontend_base_url)
        composer.expect_open()
        return composer


class ComposeMessage(BasePage):
    """The compose panel ComposeModal.tsx mounts over the mailbox.

    Not a ``role="dialog"`` — see the module docstring — so every locator here
    is anchored on a placeholder or a button label rather than on a dialog
    scope. Each is unique to this panel on the messages route.
    """

    def expect_open(self) -> None:
        expect(
            self.page.get_by_placeholder(as_pattern(BODY_FIELD)).first
        ).to_be_visible(timeout=15_000)

    def expect_closed(self) -> None:
        """``if (!open) return null`` — a dismissed composer is unmounted."""
        expect(self.page.get_by_placeholder(as_pattern(BODY_FIELD))).to_have_count(
            0, timeout=15_000
        )

    # ───────────────────────── recipients ────────────────────────

    def add_recipient(self, search_text: str, *, name: str | None = None) -> "ComposeMessage":
        """Pick a recipient out of the school's directory.

        ``search_text`` is matched server-side against first name, other names
        and email (``GET /school_profile/{id}/users``), so an email address is
        the reliable thing to pass: two provisioned people can share a first
        name, never an address. The lookup needs three characters and a 300ms
        debounce before it fires, which is why the result is waited for rather
        than asserted immediately.
        """
        self.page.get_by_placeholder(as_pattern(USER_SEARCH_FIELD)).first.fill(search_text)
        option = self.page.get_by_role("button").filter(
            has_text=as_pattern(re.escape(search_text))
        ).first
        expect(option).to_be_visible(timeout=30_000)
        option.click()
        if name:
            self.expect_recipient(name)
        return self

    def recipients(self) -> Locator:
        """The "To:" row — its label's parent, which holds the chips."""
        return self.page.get_by_text(as_pattern(TO_LABEL)).first.locator("xpath=..")

    def expect_recipient(self, name: str) -> None:
        expect(
            self.recipients().get_by_text(as_pattern(re.escape(name))).first
        ).to_be_visible(timeout=15_000)

    # ─────────────────────────── content ─────────────────────────

    def write(self, *, subject: str, body: str) -> "ComposeMessage":
        self.page.get_by_placeholder(as_pattern(SUBJECT_FIELD)).first.fill(subject)
        self.page.get_by_placeholder(as_pattern(BODY_FIELD)).first.fill(body)
        return self

    def channel(self, label: str | re.Pattern) -> Locator:
        return self.page.get_by_label(as_pattern(label)).first

    def expect_channels(self, *, checked: tuple = (), unchecked: tuple = ()) -> None:
        """Assert which delivery channels are armed.

        ComposeModal initialises ``channels`` to ``["inapp"]``, so the in-app
        box is ticked before anyone touches it. Worth asserting rather than
        assuming: email and SMS are the two channels a test must never send on
        (QA mode suppresses mail, and there is no SMS gateway), and a default
        that changed would otherwise be discovered by a bounced message.
        """
        for label in checked:
            expect(self.channel(label)).to_be_checked()
        for label in unchecked:
            expect(self.channel(label)).not_to_be_checked()

    # ──────────────────────────── writes ─────────────────────────

    def send(self) -> int:
        """Send the composed message; returns the id the backend assigned it.

        The id comes from the ``POST /messaging/messages`` response, so
        everything a caller later asserts about the Sent folder and the detail
        page is anchored on a record the server really created rather than on
        the toast that announced it.
        """
        with self.page.expect_response(_is_send_response, timeout=45_000) as info:
            self.page.get_by_role("button", name=as_pattern(SEND_BUTTON)).first.click()
        response = info.value

        self.expect_toast(MESSAGE_SENT_TOAST, timeout_ms=20_000)
        self.expect_closed()
        return _message_id_from(response)

    def save_draft(self) -> None:
        self.page.get_by_role("button", name=as_pattern(SAVE_DRAFT_BUTTON)).first.click()
        self.expect_toast(DRAFT_SAVED_TOAST, timeout_ms=20_000)
        self.expect_closed()


class MessageDetailPage(BasePage):
    """One message at /module/messages/{id}?from={folder}."""

    def __init__(self, page: Page, frontend_base_url: str, folder: str = "inbox"):
        super().__init__(page, frontend_base_url)
        self.folder = folder

    def expect_loaded(self, *, message_id: int, subject: str, body: str) -> None:
        """This is the message the send returned, refetched from the server.

        The page renders nothing until ``GET /messaging/messages/{id}`` answers
        (``if (!message) return null``), so a subject on screen at this URL is
        the stored subject, not the composer's leftovers.
        """
        expect(self.page).to_have_url(
            re.compile(rf"/module/messages/{message_id}(?:$|[?#])"), timeout=25_000
        )
        expect(
            self.page.get_by_role("heading", name=as_pattern(re.escape(subject))).first
        ).to_be_visible(timeout=25_000)
        expect(
            self.page.get_by_text(as_pattern(re.escape(body))).first
        ).to_be_visible()

    def expect_sender(self, *, name: str | None = None, email: str | None = None) -> None:
        if name:
            expect(
                self.page.get_by_text(as_pattern(re.escape(name))).first
            ).to_be_visible(timeout=15_000)
        if email:
            expect(
                self.page.get_by_text(as_pattern(re.escape(email))).first
            ).to_be_visible(timeout=15_000)

    def expect_channel(self, channel: str) -> None:
        """The channel chip — rendered from ``MessageOut.channels``.

        The chip is uppercased by CSS only, so the text node itself is the
        backend's own lowercase key ("inapp").
        """
        expect(
            self.page.get_by_text(as_pattern(rf"^\s*{re.escape(channel)}\s*$")).first
        ).to_be_visible(timeout=15_000)

    def trash(self) -> MailboxPage:
        """Move this message to Trash and follow the page back to its folder."""
        self.page.get_by_role("button", name=as_pattern(TRASH_BUTTON)).first.click()
        self.expect_toast(TRASHED_TOAST, timeout_ms=20_000)
        self.page.wait_for_url(
            re.compile(rf"/module/messages/{self.folder}"), timeout=25_000
        )
        mailbox = MailboxPage(self.page, self.frontend_base_url, folder=self.folder)
        mailbox.expect_loaded()
        return mailbox

    def back(self) -> MailboxPage:
        self.page.get_by_role("button", name=as_pattern(BACK_BUTTON)).first.click()
        self.page.wait_for_url(
            re.compile(rf"/module/messages/{self.folder}"), timeout=25_000
        )
        mailbox = MailboxPage(self.page, self.frontend_base_url, folder=self.folder)
        mailbox.expect_loaded()
        return mailbox


def _is_send_response(response: Response) -> bool:
    return (
        response.request.method == "POST"
        and SEND_ENDPOINT.search(response.url) is not None
    )


def _message_id_from(response: Response) -> int:
    """The new message's id, from the ``MessageOut`` the send returns."""
    if not response.ok:
        raise AssertionError(
            f"POST /messaging/messages failed: {response.status} "
            f"{response.text()[:300]}"
        )
    payload = response.json()
    if not isinstance(payload, dict) or "id" not in payload:
        raise AssertionError(f"POST /messaging/messages returned no message: {payload!r}")
    return int(payload["id"])
