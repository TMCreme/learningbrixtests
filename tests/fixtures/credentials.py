"""Capture credentials for users the app creates during a UI flow.

Every user this backend creates gets a server-generated password that is only
ever sent by email, which an unattended suite cannot read. The backend therefore
runs with QA mode enabled (see newschoolapp/utils/qa_mode.py), which attaches
the generated secrets to the response:

  * dict responses carry them under a ``test_mode`` key in the body
  * every response also carries them in the ``X-Test-Mode`` header, which is
    what makes list- and null-bodied endpoints (forgot-password) readable

Usage — wrap the UI action that triggers the create:

    creds = capture_credentials(
        page,
        lambda: staff_page.create_teaching_staff(**person),
        url_substring="/teacher/",
        email=person["email"],
    )
    # creds.password is now usable for a real login

If QA mode is off, this raises with the exact remedy rather than silently
returning a password that does not work.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from playwright.sync_api import Page, Response


DEFAULT_STATUSES = (200, 201)


class CredentialCaptureError(RuntimeError):
    pass


@dataclass
class CapturedUser:
    email: str
    password: str
    body: dict[str, Any]
    test_mode: dict[str, Any]

    @property
    def user_id(self) -> int | None:
        for key in ("id", "user_id"):
            value = self.body.get(key)
            if isinstance(value, int):
                return value
        user = self.body.get("user")
        if isinstance(user, dict) and isinstance(user.get("id"), int):
            return user["id"]
        return None


def read_test_mode(response: Response) -> dict[str, Any]:
    """Pull the test_mode block from a response body or its header."""
    block: dict[str, Any] = {}

    header = response.header_value("x-test-mode")
    if header:
        try:
            block = json.loads(header)
        except json.JSONDecodeError:
            block = {}

    if not block:
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 — non-JSON responses are simply not it
            body = None
        if isinstance(body, dict) and isinstance(body.get("test_mode"), dict):
            block = body["test_mode"]

    return block


def _body_of(response: Response) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


def capture_credentials(
    page: Page,
    action: Callable[[], Any],
    *,
    url_substring: str,
    email: str,
    statuses: Iterable[int] = DEFAULT_STATUSES,
    timeout_ms: int = 25_000,
) -> CapturedUser:
    """Run a UI action that creates a user and return its login credentials."""
    statuses = tuple(statuses)
    with page.expect_response(
        lambda r: url_substring in r.url and r.status in statuses,
        timeout=timeout_ms,
    ) as info:
        action()

    response = info.value
    test_mode = read_test_mode(response)
    if not test_mode:
        raise CredentialCaptureError(
            f"No test_mode data on {response.status} {response.url}.\n"
            f"QA mode is not enabled on the backend. Enable it with:\n"
            f"  touch <backend-repo>/.qa_mode_enabled\n"
            f"(or set QA_MODE=1), then wait for uvicorn --reload to pick it up."
        )

    password = test_mode.get("initial_password")
    if not password:
        passwords = test_mode.get("passwords") or []
        password = passwords[0] if passwords else None
    if not password:
        raise CredentialCaptureError(
            f"test_mode present on {response.url} but carried no password: "
            f"{sorted(test_mode)}. If this endpoint does not hash a password, "
            f"capture the credential where the user is actually created."
        )

    return CapturedUser(
        email=email,
        password=str(password),
        body=_body_of(response),
        test_mode=test_mode,
    )


def capture_link(
    page: Page,
    action: Callable[[], Any],
    *,
    url_substring: str,
    kind: str = "reset",
    statuses: Iterable[int] = DEFAULT_STATUSES,
    timeout_ms: int = 25_000,
) -> str:
    """Run an action that triggers an email and return the link inside it."""
    statuses = tuple(statuses)
    with page.expect_response(
        lambda r: url_substring in r.url and r.status in statuses,
        timeout=timeout_ms,
    ) as info:
        action()

    test_mode = read_test_mode(info.value)
    link = test_mode.get(f"{kind}_link")
    if not link:
        links = test_mode.get("links") or []
        link = next((ln for ln in links if kind in ln.lower()), None) or (
            links[0] if links else None
        )
    if not link:
        raise CredentialCaptureError(
            f"No {kind} link in test_mode from {info.value.url}: {sorted(test_mode)}"
        )
    return str(link)
