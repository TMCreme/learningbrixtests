"""The ``provisioned_school`` fixture — one provisioned school per scenario.

Registered as a plugin from the root ``conftest.py`` (``pytest_plugins``), so the
fixtures below are visible to every test without an import.

Scope
    Session, parametrised over ``config/feature_scenarios.yaml``. Five scenarios
    means five schools per run, each provisioned once and shared by every test
    that asks for ``provisioned_school`` — a per-test school would mean one full
    UI walkthrough per test, which the suite cannot afford.

Contexts
    Provisioning drives the UI itself, so it needs a page. It cannot use the
    function-scoped pytest-playwright ``page`` (narrower scope than this
    fixture), so it builds a dedicated context off the session-scoped ``browser``
    and closes it as soon as the walkthrough finishes. Tests then get their own
    fresh ``context``/``page`` and log in per role with the credentials on the
    yielded :class:`SchoolContext` (``ctx.teacher.email`` / ``.password``, …).
"""
from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import structlog
from playwright.sync_api import Browser

from config.scenarios import Scenario, load_scenarios
from config.settings import Settings, get_settings
from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import TEST_PREFIX
from tests.flows.school_provisioning import (
    SUPER_ADMIN_ROLE,
    Credentials,
    SchoolContext,
    provision_school,
    teardown_school,
)

log = structlog.get_logger(__name__)

SWEEP_OPTION = "--sweep-orphans"

# A school younger than this may belong to a run happening right now (this one,
# or a parallel agent's), so the sweeper leaves it alone. Anything older than the
# upper bound predates the window we are willing to claim responsibility for.
ORPHAN_MIN_AGE = timedelta(minutes=10)
ORPHAN_MAX_AGE = timedelta(hours=24)

_TEST_SCHOOL_NAME = re.compile(rf"^\s*{re.escape(TEST_PREFIX)}", re.I)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        SWEEP_OPTION,
        action="store_true",
        default=False,
        help=(
            "At session end, delete leftover 'TEST…' schools from crashed runs "
            "(older than 10 minutes, younger than 24 hours). Off by default."
        ),
    )


@pytest.fixture(scope="session")
def api(backend_api: BackendAPI) -> BackendAPI:
    """Short alias for ``backend_api``; the root conftest owns its lifecycle."""
    return backend_api


@pytest.fixture(
    scope="session",
    params=[s for s in load_scenarios(get_settings().scenarios_file)],
    ids=lambda s: s.id,
)
def provisioned_school(
    request: pytest.FixtureRequest,
    browser: Browser,
    settings: Settings,
    superadmin: Any,
    api: BackendAPI,
) -> Iterator[SchoolContext]:
    """Session-scoped: each scenario produces ONE school for the whole test
    session. All tests share these schools across all roles. The provisioning
    browser context is closed before any test starts, so tests get fresh
    contexts and do their own logins per role using the credentials stored in
    ``SchoolContext``.
    """
    scenario: Scenario = request.param
    super_admin_creds = Credentials(
        email=_credential(superadmin, "email"),
        password=_credential(superadmin, "password"),
        access_token=_credential(superadmin, "access_token", "token") or None,
        role_name=SUPER_ADMIN_ROLE,
        first_name=settings.superadmin_first_name,
        last_name=settings.superadmin_other_names,
        role=SUPER_ADMIN_ROLE,
    )

    context = browser.new_context(
        viewport={"width": settings.viewport_width, "height": settings.viewport_height},
        base_url=settings.frontend_base_url,
    )
    page = context.new_page()
    page.set_default_timeout(settings.default_timeout_ms)
    page.set_default_navigation_timeout(settings.navigation_timeout_ms)
    try:
        ctx = provision_school(page, settings, scenario, super_admin_creds, api)
    finally:
        context.close()  # provisioning is done; tests will create their own contexts

    yield ctx

    if settings.delete_on_failure or not request.session.testsfailed:
        teardown_school(api, ctx.school_id, _super_admin_token(api, super_admin_creds))
    else:
        log.warning(
            "provisioning.teardown.retained",
            scenario=ctx.scenario_id,
            school_id=ctx.school_id,
            school=ctx.school_name,
            reason="DELETE_ON_FAILURE=false and the session had failures",
        )


@pytest.fixture(scope="session", autouse=True)
def _sweep_orphan_schools(
    request: pytest.FixtureRequest, settings: Settings
) -> Iterator[None]:
    """Session-end sweep of schools left behind by earlier crashed runs.

    ``api``/``superadmin`` are pulled with ``getfixturevalue`` instead of being
    declared as parameters so that a run without ``--sweep-orphans`` — the
    default — never forces a backend connection or a SuperAdmin seed it has no
    other use for.
    """
    yield

    if not request.config.getoption(SWEEP_OPTION):
        return

    api: BackendAPI = request.getfixturevalue("api")
    superadmin: Any = request.getfixturevalue("superadmin")
    token = _super_admin_token(api, superadmin)
    if not token:
        log.warning("sweep.skipped", reason="no SuperAdmin token available")
        return

    now = datetime.now(timezone.utc)
    swept = 0
    for school in api.list_schools(token=token):
        school_id = school.get("id")
        name = str(school.get("name", ""))
        if not isinstance(school_id, int) or not _TEST_SCHOOL_NAME.match(name):
            continue

        created = _parse_timestamp(school.get("date_created"))
        if created is None:
            log.warning("sweep.unparseable_timestamp", school_id=school_id, name=name,
                        date_created=school.get("date_created"))
            continue

        age = now - created
        if not (ORPHAN_MIN_AGE < age < ORPHAN_MAX_AGE):
            continue

        log.info("sweep.deleting", school_id=school_id, name=name, age_minutes=int(age.total_seconds() // 60))
        teardown_school(api, school_id, token)
        swept += 1

    log.info("sweep.done", deleted=swept, backend=settings.backend_api_url)


# ───────────────────────────── internals ─────────────────────────────────────


def _credential(source: Any, *names: str) -> str:
    """Read a field from the ``superadmin`` fixture's value.

    Tolerates both shapes that have shipped: the ``Credentials`` dataclass the
    root conftest yields today, and the ``{email, password, token}`` mapping
    ``docs/plan.md`` §6 describes.
    """
    for name in names:
        value = source.get(name) if isinstance(source, Mapping) else getattr(source, name, None)
        if value:
            return str(value)
    return ""


def _super_admin_token(api: BackendAPI, superadmin: Any) -> str:
    """The SuperAdmin bearer token, logging in again if the fixture carries none."""
    token = _credential(superadmin, "access_token", "token")
    if token:
        return token
    email = _credential(superadmin, "email")
    password = _credential(superadmin, "password")
    try:
        return str(api.login(email, password).get("access_token", ""))
    except Exception as exc:  # noqa: BLE001 — cleanup never propagates
        log.warning("superadmin.token_refresh_failed", email=email, error=str(exc))
        return ""


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse the backend's ``date_created`` into an aware UTC datetime."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
