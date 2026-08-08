"""Proves QA-mode credential capture works through a real browser flow.

Not a feature test — this is the gate for everything else. If the backend's QA
mode stops returning secrets, every test that logs in as a created user breaks,
and the failure would otherwise surface as a confusing "invalid credentials"
deep inside a provisioning flow. Failing here says exactly what is wrong.
"""
from __future__ import annotations

import re

import pytest

from tests.fixtures.api_client import BackendAPI, Credentials
from tests.fixtures.credentials import capture_link, read_test_mode
from tests.fixtures.data_factories import make_person
from tests.pages.base import BasePage


pytestmark = pytest.mark.smoke


def test_qa_mode_returns_password_on_user_creation(
    backend_api: BackendAPI, settings
) -> None:
    """A created user's generated password comes back on the response."""
    person = make_person("qaprobe")
    role_id = backend_api.role_id_for("Admin")
    res = backend_api.post("/users/register", json={
        "first_name": person.first_name,
        "other_names": person.last_name,
        "email": person.email,
        "gender": person.gender,
        "date_of_birth": "1990-01-01",
        "nationality": person.nationality,
        "residential_address": person.address,
        "primary_phone": person.phone,
        "password": "ProbePass!2026",
        "password_confirmation": "ProbePass!2026",
        "role_id": role_id,
        "is_active": True,
    })
    assert res.status_code < 400, f"register failed: {res.status_code} {res.text[:300]}"

    body = res.json()
    assert isinstance(body, dict) and "test_mode" in body, (
        "No test_mode block on the register response. QA mode is off — run: "
        "touch <backend-repo>/.qa_mode_enabled"
    )
    assert body["test_mode"].get("initial_password") == "ProbePass!2026"

    # The captured password must actually work.
    assert backend_api.try_login(person.email, "ProbePass!2026") is not None


def test_qa_mode_returns_reset_link_through_the_ui(
    page, frontend_base_url: str, superadmin: Credentials
) -> None:
    """A UI-triggered email exposes its link via the X-Test-Mode header.

    forgot-password returns a null body, so this specifically exercises the
    header path — the one that makes non-dict responses readable.
    """
    base = BasePage(page, frontend_base_url)
    page.goto(f"{frontend_base_url}/auth/forgot_password")

    page.get_by_role("textbox").first.fill(superadmin.email)

    link = capture_link(
        page,
        lambda: page.get_by_role("button", name=re.compile(r"send|reset|submit", re.I)).first.click(),
        url_substring="/users/forgot-password",
        kind="reset",
    )

    assert "token=" in link, f"reset link carried no token: {link}"


def test_read_test_mode_prefers_header_then_body() -> None:
    """The reader must tolerate either transport."""

    class FakeResponse:
        def __init__(self, header=None, body=None):
            self._header, self._body = header, body

        def header_value(self, name):
            return self._header

        def json(self):
            if self._body is None:
                raise ValueError("no body")
            return self._body

    assert read_test_mode(FakeResponse(header='{"initial_password": "h"}')) == {
        "initial_password": "h"
    }
    assert read_test_mode(
        FakeResponse(body={"test_mode": {"initial_password": "b"}})
    ) == {"initial_password": "b"}
    assert read_test_mode(FakeResponse()) == {}
