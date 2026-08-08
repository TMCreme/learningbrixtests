"""People → the guardian's landing page, /module/home.

``src/app/module/home/page.tsx`` picks a view per role; a Guardian gets
``ViewsComponents/GuardianView.tsx`` — a "Your Ward(s)" table of the children
they look after, each row offering **View** (the ward's profile) and
**Impersonate**.

Why the Impersonate button matters beyond this page
    It is the only route a guardian has into the learner-facing screens. Pages
    like /module/student_timetables read ``user_profile.student_profile.id``
    straight off the auth store and have no student picker at all, so a guardian
    — who has a ``guardian_profile`` and no ``student_profile`` — sees an error
    state there, not a grid. "Impersonate" calls
    ``POST /users/guardian/impersonate-ward/{student_id}`` (which the backend
    allows only for a *direct* ward), then swaps the ward's profile, token and
    role permissions into the same stores the rest of the app reads, and
    hard-navigates to /module/home. From that point the guardian sees exactly
    what their child sees, with a standing amber banner saying so.

``view_as_ward`` deliberately waits on that banner rather than on the redirect:
the redirect is a bare ``window.location.href`` to a page a guardian can also
reach without impersonating, so the URL alone proves nothing.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

HOME_URL = re.compile(r"/module/home(?:$|[?#])")

# GuardianView.tsx — "Your Ward(s)", rendered whether or not any ward exists.
WARDS_HEADING = re.compile(r"Your Ward", re.I)
NO_WARDS = re.compile(r"^\s*No Wards Found\s*$", re.I)

# The row action, and the "Loading..." label it swaps to while the token mints.
IMPERSONATE_BUTTON = re.compile(r"^\s*Impersonate\s*$", re.I)

# NavigationHeader.tsx — the standing banner that says whose eyes you are using.
IMPERSONATION_BANNER = re.compile(r"You are currently impersonating", re.I)
EXIT_IMPERSONATION = re.compile(r"^\s*Exit\s*$", re.I)


class GuardianHomePage(BasePage):
    URL = "/module/home"

    def open(self) -> "GuardianHomePage":
        super().open()
        return self

    # ───────────────────────── the wards table ───────────────────

    def expect_loaded(self) -> "GuardianHomePage":
        expect(
            self.page.get_by_role("heading", name=as_pattern(WARDS_HEADING))
        ).to_be_visible(timeout=30_000)
        return self

    def ward_row(self, ward_name: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has_text=as_pattern(re.escape(ward_name))
        ).first

    def expect_ward(self, ward_name: str) -> None:
        expect(self.page.get_by_text(as_pattern(NO_WARDS))).to_have_count(0)
        expect(self.ward_row(ward_name)).to_be_visible(timeout=30_000)

    # ─────────────────────── ward impersonation ──────────────────

    def view_as_ward(self, ward_name: str) -> None:
        """Click a ward's "Impersonate" and wait until the swap has landed.

        The click mints an impersonation token, fetches the ward's role
        permissions and only then hard-navigates, so the wait has to outlast two
        round trips — and it waits on the banner, which is the one thing on
        screen that cannot be true unless the identity really was swapped.
        """
        self.ward_row(ward_name).get_by_role(
            "button", name=as_pattern(IMPERSONATE_BUTTON)
        ).first.click()
        self.expect_viewing_as(ward_name)

    def expect_viewing_as(self, ward_name: str, timeout_ms: int = 40_000) -> None:
        expect(
            self.page.get_by_text(as_pattern(IMPERSONATION_BANNER)).first
        ).to_be_visible(timeout=timeout_ms)
        expect(
            self.page.get_by_text(as_pattern(re.escape(ward_name))).first
        ).to_be_visible(timeout=timeout_ms)

    def exit_ward_view(self) -> None:
        """Hand the session back to the guardian's own identity."""
        self.page.get_by_role(
            "button", name=as_pattern(EXIT_IMPERSONATION)
        ).first.click()
        expect(
            self.page.get_by_text(as_pattern(IMPERSONATION_BANNER))
        ).to_have_count(0, timeout=25_000)
