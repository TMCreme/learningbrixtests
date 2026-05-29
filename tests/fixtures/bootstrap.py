"""SuperAdmin bootstrap.

Tries to log in first; if the user doesn't exist, registers via /users/register
with the SuperAdmin role_id, then logs in. Idempotent — safe to run every
session.
"""
from __future__ import annotations

import logging

from config.settings import Settings
from tests.fixtures.api_client import BackendAPI, BackendAPIError, Credentials


log = logging.getLogger(__name__)

SUPERADMIN_ROLE_NAME = "SuperAdmin"


def ensure_superadmin(api: BackendAPI, settings: Settings) -> Credentials:
    email = settings.superadmin_email
    password = settings.superadmin_password

    existing = api.try_login(email, password)
    if existing:
        log.info("SuperAdmin %s already exists — using existing account", email)
        return _credentials_from_login(email, password, existing)

    log.info("SuperAdmin %s not found — creating via /users/register", email)
    role_id = api.role_id_for(SUPERADMIN_ROLE_NAME)
    api.register_user(
        email=email,
        password=password,
        role_id=role_id,
        first_name=settings.superadmin_first_name,
        other_names=settings.superadmin_other_names,
    )

    login_res = api.login(email, password)
    return _credentials_from_login(email, password, login_res)


def _credentials_from_login(email: str, password: str, login: dict) -> Credentials:
    return Credentials(
        email=email,
        password=password,
        user_id=login.get("id"),
        role_id=login.get("role_id"),
        role_name=SUPERADMIN_ROLE_NAME,
        access_token=login.get("access_token"),
    )
