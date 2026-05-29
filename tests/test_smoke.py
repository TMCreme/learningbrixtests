"""Phase 0/1 smoke tests — verify the scaffolding wires up.

These should run quickly against a live local backend + frontend:

  pytest tests/test_smoke.py -v

They do NOT exercise feature flows yet — that arrives in Phase 2+.
"""
from __future__ import annotations

import pytest

from config.scenarios import Scenario
from config.settings import Settings
from tests.fixtures.api_client import BackendAPI, Credentials
from tests.pages.login import LoginPage


pytestmark = pytest.mark.smoke


def test_settings_load(settings: Settings) -> None:
    assert settings.backend_base_url
    assert settings.frontend_base_url
    assert settings.superadmin_email
    assert settings.superadmin_password


def test_scenarios_load(scenarios: tuple[Scenario, ...]) -> None:
    assert len(scenarios) >= 1, "Define at least one scenario in feature_scenarios.yaml"
    ids = {s.id for s in scenarios}
    assert len(ids) == len(scenarios), "Scenario ids must be unique"


def test_backend_reachable(backend_api: BackendAPI) -> None:
    roles = backend_api.list_roles()
    role_names = {r.get("name") for r in roles}
    assert "SuperAdmin" in role_names, (
        f"Backend has no SuperAdmin role — found: {sorted(role_names)}. "
        f"Did backend startup seeding run?"
    )


def test_superadmin_bootstrap(superadmin: Credentials) -> None:
    assert superadmin.access_token, "SuperAdmin login did not return a token"
    assert superadmin.role_name == "SuperAdmin"
    assert superadmin.user_id is not None


def test_login_page_renders(page, frontend_base_url: str) -> None:
    LoginPage(page, frontend_base_url).open()
    assert "login" in page.url.lower()
