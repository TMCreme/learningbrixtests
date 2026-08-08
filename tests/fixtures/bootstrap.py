"""SuperAdmin bootstrap.

The obvious approach — POST /users/register with the SuperAdmin role_id — does
not work: the backend rejects it with

    403 {"detail": "Cannot self-register with super admin privileges."}

and its own ``scripts/seed_superadmin.py`` sets a *random* password and emails a
reset link, which is useless to an unattended suite. So the fallback seeds the
user by running the backend's own SessionLocal + get_password_hash inside the
backend container, which keeps the password hashing scheme authoritative
instead of reimplementing bcrypt here.

Order of attempts (idempotent — safe to run every session):
  1. Log in via the API. If that works, we are done.
  2. Seed/repair the SuperAdmin via `docker exec <container> python -`.
  3. Log in again.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

from config.settings import Settings
from tests.fixtures.api_client import BackendAPI, BackendAPIError, Credentials


log = logging.getLogger(__name__)

SUPERADMIN_ROLE_NAME = "SuperAdmin"

# Runs inside the backend container. `import app` first: importing a single
# model module leaves SQLAlchemy's mapper registry half-populated and blows up
# with "expression 'Family' failed to locate a name".
_SEED_SCRIPT = """
import app  # noqa: F401 — registers every model mapper
from db.database import SessionLocal
from db.models.roles import Role
from db.models.user import User
from utils.utils import get_password_hash

EMAIL = {email!r}
PASSWORD = {password!r}
FIRST = {first!r}
OTHER = {other!r}

db = SessionLocal()
try:
    role = db.query(Role).filter(Role.name == "SuperAdmin").first()
    if role is None:
        raise SystemExit("SEED_FAIL: no SuperAdmin role — has the app seeded roles?")

    user = db.query(User).filter(User.email == EMAIL).first()
    if user is None:
        user = User(
            first_name=FIRST, other_names=OTHER, email=EMAIL, gender="Other",
            date_of_birth="1970-01-01", nationality="N/A", residential_address="N/A",
            primary_phone="0000000000", password=get_password_hash(PASSWORD),
            role_id=role.id, is_active=True, is_super=True,
        )
        db.add(user)
        action = "CREATED"
    else:
        user.password = get_password_hash(PASSWORD)
        user.is_active = True
        user.is_super = True
        user.role_id = role.id
        action = "UPDATED"
    db.commit()
    db.refresh(user)
    print("SEED_OK", action, user.id)
finally:
    db.close()
"""


class BootstrapError(Exception):
    pass


def ensure_superadmin(api: BackendAPI, settings: Settings) -> Credentials:
    email = settings.superadmin_email
    password = settings.superadmin_password

    existing = api.try_login(email, password)
    if existing:
        log.info("SuperAdmin %s already usable — reusing", email)
        return _credentials_from_login(email, password, existing)

    log.info("SuperAdmin %s cannot log in — seeding via backend container", email)
    _seed_via_container(settings)

    login_res = api.try_login(email, password)
    if login_res is None:
        raise BootstrapError(
            f"Seeded SuperAdmin {email} but login still fails. Check that "
            f"BACKEND_CONTAINER={settings.backend_container!r} points at the same "
            f"backend serving {settings.backend_api_url}."
        )
    return _credentials_from_login(email, password, login_res)


def _seed_via_container(settings: Settings) -> None:
    container = settings.backend_container.strip()
    if not container:
        raise BootstrapError(
            "SuperAdmin login failed and BACKEND_CONTAINER is unset, so the "
            "suite cannot seed one (the backend forbids SuperAdmin "
            "self-registration). Set BACKEND_CONTAINER in .env, or create the "
            "SuperAdmin manually and put its credentials in .env."
        )
    if shutil.which("docker") is None:
        raise BootstrapError(
            "BACKEND_CONTAINER is set but `docker` is not on PATH."
        )

    script = _SEED_SCRIPT.format(
        email=settings.superadmin_email,
        password=settings.superadmin_password,
        first=settings.superadmin_first_name,
        other=settings.superadmin_other_names,
    )
    proc = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if "SEED_OK" not in proc.stdout:
        raise BootstrapError(
            f"SuperAdmin seed failed in container {container!r}.\n"
            f"stdout: {proc.stdout[-800:]}\nstderr: {proc.stderr[-800:]}"
        )
    log.info("SuperAdmin seed: %s", proc.stdout.strip().splitlines()[-1])


def _credentials_from_login(email: str, password: str, login: dict) -> Credentials:
    return Credentials(
        email=email,
        password=password,
        user_id=login.get("id"),
        role_id=login.get("role_id"),
        role_name=SUPERADMIN_ROLE_NAME,
        access_token=login.get("access_token"),
    )
