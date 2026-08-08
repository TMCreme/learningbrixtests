"""Root conftest — session-scoped fixtures + hooks.

Per-test browser fixtures live in tests/conftest.py.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest
import structlog

# Make the repo root importable so `config.*` and `tests.*` work without
# pip-installing the project.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings, get_settings  # noqa: E402
from config.scenarios import Scenario, load_scenarios, coverage_warnings  # noqa: E402
from tests.fixtures.api_client import BackendAPI, Credentials  # noqa: E402
from tests.fixtures.bootstrap import ensure_superadmin  # noqa: E402

# pytest 8 only honours pytest_plugins in the rootdir conftest.
pytest_plugins = ("tests.fixtures.video", "tests.fixtures.provisioned_school")


# ──────────────────────────── logging ────────────────────────────

def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
    )


_configure_logging()
log = structlog.get_logger(__name__)


# ─────────────────────── session fixtures ────────────────────────

@pytest.fixture(scope="session")
def settings() -> Settings:
    s = get_settings()
    log.info("settings_loaded",
             backend=s.backend_api_url,
             frontend=s.frontend_base_url,
             headless=s.headless)
    return s


@pytest.fixture(scope="session")
def scenarios(settings: Settings) -> tuple[Scenario, ...]:
    items = load_scenarios(settings.scenarios_file)
    for warn in coverage_warnings(items):
        log.warning("scenario_coverage", message=warn)
    log.info("scenarios_loaded", count=len(items), ids=[s.id for s in items])
    return items


@pytest.fixture(scope="session")
def backend_api(settings: Settings):
    with BackendAPI(settings) as api:
        if not api.health_check():
            pytest.exit(
                f"Backend not reachable at {settings.backend_api_url}. "
                f"Start it before running the suite.",
                returncode=2,
            )
        yield api


@pytest.fixture(scope="session")
def superadmin(backend_api: BackendAPI, settings: Settings) -> Credentials:
    """SuperAdmin credentials, guaranteed to exist on the backend."""
    creds = ensure_superadmin(backend_api, settings)
    log.info("superadmin_ready", email=creds.email, user_id=creds.user_id)
    return creds


# ─────────────────── pytest-playwright config ────────────────────

@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, settings: Settings):
    """Override pytest-playwright's launch args from .env."""
    return {
        **browser_type_launch_args,
        "headless": settings.headless,
        "slow_mo": settings.slow_mo_ms,
    }


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, settings: Settings):
    """Default viewport + base_url."""
    return {
        **browser_context_args,
        "viewport": {
            "width": settings.viewport_width,
            "height": settings.viewport_height,
        },
        "base_url": settings.frontend_base_url,
    }


# ──────────────────── screenshot-on-failure ──────────────────────

@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Capture a screenshot and the DOM when a test fails.

    A demo test drives ``demo.page`` — a page on the recorder's own browser
    context, *not* pytest-playwright's ``page`` fixture, which such a test never
    navigates. Screenshotting ``page`` there yields a blank frame that hides the
    failure, so the demo's page wins whenever the test used one.

    The DOM is written beside the image because most failures here are "a
    selector matched nothing", and the answer to those is in the markup rather
    than in the pixels.
    """
    outcome = yield
    report = outcome.get_result()

    if report.when != "call" or report.passed:
        return

    # Tell the `demo` fixture the test failed, so the renderer skips its video —
    # a published demo must only ever show a feature that actually works.
    item._demo_failed = True

    demo = item.funcargs.get("demo")
    page = getattr(demo, "page", None) or item.funcargs.get("page")
    if page is None:
        return

    artifacts_dir = ROOT / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    safe_name = (item.nodeid
                 .replace("::", "__")
                 .replace("/", "_")
                 .replace("[", "_")
                 .replace("]", "_"))
    path = artifacts_dir / f"{safe_name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        try:
            (artifacts_dir / f"{safe_name}.html").write_text(
                page.content(), encoding="utf-8"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("dom_dump_failed", test=item.nodeid, error=str(e))
        log.warning("screenshot_saved", test=item.nodeid, path=str(path))
        # Attach into the HTML report if pytest-html is loaded.
        if hasattr(report, "extras"):
            try:
                from pytest_html import extras  # type: ignore
                report.extras.append(extras.image(str(path)))
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        log.warning("screenshot_failed", test=item.nodeid, error=str(e))
