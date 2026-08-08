"""Proves the demo-video pipeline end-to-end.

Not a feature test — this exists so a broken recording/rendering path is caught
here rather than halfway through an autonomous run. It records the shortest
real flow there is: a SuperAdmin logging in through the UI.
"""
from __future__ import annotations

import pytest

from tests.fixtures.api_client import Credentials
from tests.pages.login import LoginPage


@pytest.mark.smoke
@pytest.mark.demo(
    feature_id="platform.auth.superadmin_login",
    title="Authentication",
    subtitle="SuperAdmin signs in",
)
def test_superadmin_login_demo(demo, superadmin: Credentials) -> None:
    login = LoginPage(demo.page, demo.frontend_base_url)

    with demo.step("Open the LearningBrix sign-in page"):
        login.open()

    with demo.step(f"Sign in as {superadmin.email}"):
        login.login(superadmin.email, superadmin.password)

    with demo.step("Land on the authenticated dashboard", dwell_ms=1200):
        assert "/module/" in demo.page.url, f"unexpected landing URL: {demo.page.url}"
