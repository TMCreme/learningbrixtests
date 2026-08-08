"""Per-test fixtures for the browser layer.

Session-scoped fixtures (settings, scenarios, superadmin, backend_api) live in
the root conftest.py.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

from config.scenarios import Scenario
from config.settings import Settings

SMOKE_ONLY_MARKER = "provisioning_smoke_only"
SMOKE_ONLY_SCENARIO_ID = "full_access"
SCENARIO_MARKER = "scenario"


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Collapse the parametrised ``provisioned_school`` fixture where asked.

    ``provisioned_school`` is parametrised over every scenario, and each param
    costs one full UI walkthrough. Two markers narrow that:

    ``provisioning_smoke_only``
        A test that only proves the playbook itself runs needs exactly one
        school, so the rest are deselected rather than provisioned.
    ``scenario("<id>", …)``
        A feature test is written against one feature-pack mix — the module is
        either on (positive path) or off (negative path), and running it against
        the other three schools asserts nothing the ledger asked for.

    A test with neither marker still runs against every scenario.
    """
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        scenario = _school_scenario(item)
        if scenario is None:
            kept.append(item)
            continue

        smoke_only = item.get_closest_marker(SMOKE_ONLY_MARKER) is not None
        wanted = _wanted_scenarios(item)
        if smoke_only and scenario.id != SMOKE_ONLY_SCENARIO_ID:
            deselected.append(item)
        elif wanted and scenario.id not in wanted:
            deselected.append(item)
        else:
            kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


def _wanted_scenarios(item: pytest.Item) -> frozenset[str]:
    """Scenario ids named by ``@pytest.mark.scenario(...)``; empty means "any"."""
    ids: set[str] = set()
    for marker in item.iter_markers(name=SCENARIO_MARKER):
        ids.update(str(arg) for arg in marker.args)
    return frozenset(ids)


def _school_scenario(item: pytest.Item) -> Scenario | None:
    """The scenario this item's ``provisioned_school`` param carries, if any."""
    callspec = getattr(item, "callspec", None)
    if callspec is None:
        return None
    param = callspec.params.get("provisioned_school")
    return param if isinstance(param, Scenario) else None


@pytest.fixture(autouse=True)
def _apply_default_timeouts(page: Page, settings: Settings) -> None:
    """Push our default action/navigation timeouts onto every page."""
    page.set_default_timeout(settings.default_timeout_ms)
    page.set_default_navigation_timeout(settings.navigation_timeout_ms)


@pytest.fixture
def frontend_base_url(settings: Settings) -> str:
    return settings.frontend_base_url
