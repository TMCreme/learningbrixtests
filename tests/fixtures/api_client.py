"""Minimal backend HTTP client.

Used ONLY for setup operations the suite cannot reasonably perform through the
UI before any user exists — namely, seeding the SuperAdmin at session start and
sweeping orphaned schools after a crashed run.

All feature-level testing must go through the browser (per the test plan).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from config.settings import Settings


log = logging.getLogger(__name__)


@dataclass
class Credentials:
    email: str
    password: str
    user_id: int | None = None
    role_id: int | None = None
    role_name: str | None = None
    access_token: str | None = None


class BackendAPIError(Exception):
    pass


class BackendAPI:
    """Thin httpx wrapper around the backend's /api/v1 surface."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.backend_api_url,
            timeout=20.0,
            headers={"Accept": "application/json"},
        )

    # ───────────────────────── lifecycle ─────────────────────────

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BackendAPI":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ───────────────────────── raw HTTP ──────────────────────────

    def _req(self, method: str, path: str, *, token: str | None = None, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {}) or {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        res = self._client.request(method, path, headers=headers, **kwargs)
        if res.status_code >= 500:
            raise BackendAPIError(
                f"{method} {path} → {res.status_code}: {res.text[:300]}"
            )
        return res

    def get(self, path: str, *, token: str | None = None, **kw) -> httpx.Response:
        return self._req("GET", path, token=token, **kw)

    def post(self, path: str, *, token: str | None = None, **kw) -> httpx.Response:
        return self._req("POST", path, token=token, **kw)

    def put(self, path: str, *, token: str | None = None, **kw) -> httpx.Response:
        return self._req("PUT", path, token=token, **kw)

    def patch(self, path: str, *, token: str | None = None, **kw) -> httpx.Response:
        return self._req("PATCH", path, token=token, **kw)

    def delete(self, path: str, *, token: str | None = None, **kw) -> httpx.Response:
        return self._req("DELETE", path, token=token, **kw)

    # ────────────────────── high-level helpers ───────────────────

    def health_check(self) -> bool:
        """Returns True if the backend appears reachable."""
        try:
            # /roles/ is unauthenticated and cheap.
            res = self._client.get("/roles/")
            return res.status_code < 500
        except httpx.RequestError as e:
            log.warning("Backend unreachable at %s: %s", self._settings.backend_api_url, e)
            return False

    def list_roles(self) -> list[dict[str, Any]]:
        res = self.get("/roles/")
        res.raise_for_status()
        return res.json()

    def role_id_for(self, name: str) -> int:
        for role in self.list_roles():
            if role.get("name") == name:
                return int(role["id"])
        raise BackendAPIError(
            f"Role {name!r} not found. Available: "
            f"{[r.get('name') for r in self.list_roles()]}"
        )

    def login(self, email: str, password: str) -> dict[str, Any]:
        """OAuth2 password grant → returns the full login response."""
        res = self._client.post(
            "/users/login",
            data={"username": email.lower(), "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if res.status_code != 200:
            raise BackendAPIError(
                f"Login failed for {email}: {res.status_code} {res.text[:300]}"
            )
        return res.json()

    def try_login(self, email: str, password: str) -> dict[str, Any] | None:
        try:
            return self.login(email, password)
        except BackendAPIError:
            return None

    def register_user(self, *, email: str, password: str, role_id: int,
                      first_name: str, other_names: str = "",
                      gender: str = "Male", date_of_birth: str = "1990-01-01",
                      nationality: str = "Test", residential_address: str = "Test Address",
                      primary_phone: str = "+10000000000") -> dict[str, Any]:
        payload = {
            "first_name": first_name,
            "other_names": other_names,
            "email": email,
            "gender": gender,
            "date_of_birth": date_of_birth,
            "nationality": nationality,
            "residential_address": residential_address,
            "primary_phone": primary_phone,
            "password": password,
            "password_confirmation": password,
            "role_id": role_id,
            "is_active": True,
        }
        res = self.post("/users/register", json=payload)
        if res.status_code >= 400:
            raise BackendAPIError(
                f"Register {email} failed: {res.status_code} {res.text[:500]}"
            )
        return res.json()

    # ─────────────────── teardown / cleanup ──────────────────────

    def delete_school(self, school_id: int, *, token: str) -> bool:
        res = self.delete(f"/school_profile/{school_id}", token=token)
        if res.status_code >= 400:
            log.warning("delete_school(%s) → %s %s", school_id, res.status_code, res.text[:200])
            return False
        return True

    def list_schools(self, *, token: str) -> list[dict[str, Any]]:
        res = self.get("/school_profile/", token=token)
        if res.status_code >= 400:
            return []
        return res.json()
