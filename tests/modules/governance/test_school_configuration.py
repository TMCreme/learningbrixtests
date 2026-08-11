"""/module/config — "School Configuration", the SchoolAdmin's own settings screen.

Manage path: a SchoolAdmin of the ``minimal`` school opens Configuration from
the Governance menu, corrects the school's address, phone and public email,
switches notifications from Email to SMS, saves, then signs out and back in to
prove the console reads those details back from the server
(``test_school_admin_manages_school_configuration``).

Licence path: the same ``minimal`` school proves the module cannot be switched
off — it is licensed, offered in the sidebar, mounts, and its gated API answers
even on the floor pack (``test_school_configuration_is_licensed_on_the_minimal_pack``).

Things about this screen that are not obvious from the route, recorded so the
next unit does not re-derive them:

* **"Manage" here is the edit half, and only the edit half.** The screen renders
  a *Save* button that POSTs ``/school_profile/`` when the auth store carries no
  ``school_config``, and an *Update* button that PUTs ``/school_profile/{id}``
  when it does. For a SchoolAdmin the store is never empty: ``auth.py`` looks the
  profile up by ``school_admin_id`` (falling back to ``SchoolAdminAssociation``)
  and returns it as ``school_config`` on every login, so this role always gets
  the Update branch. The create branch belongs to the SuperAdmin's
  "Create School" form, which provisioning phase A already exercises — there is
  no way to reach it here without deleting the school first.
  ``ConfigPage.save()`` accepts either button and either toast, so this test does
  not care which fired; it asserts on what the backend stored afterwards.

* **The scenario is deliberately ``minimal``.** ``school_configuration`` is the
  one module ``config/scenarios.py`` requires in *every* pack, so it is never
  negatively tested (see the header of ``config/feature_scenarios.yaml``) — which
  makes the floor scenario the most honest place to prove the positive path: a
  school with nothing else licensed can still be configured.

* **No branch may be selected first**, and that is the opposite of almost every
  other SchoolAdmin unit. The whole "Governance Module" section in
  ``nav-config.tsx`` is declared ``noBranchOnly: true``, and
  ``SideNavigation.canShowItem`` hides it for a SchoolAdmin the moment
  ``useBranchStore`` holds a branch. Calling ``BranchesPage.select_branch``
  before this test would therefore remove the very sidebar entry the video is
  meant to show. Nothing on the screen needs a branch: the payload is the school
  profile itself.

* **The currency dropdown is not asserted, on purpose.** ``page.tsx`` renders it
  as ``<Select onValueChange={setCurrency} defaultValue="GHC">`` — with a
  ``defaultValue`` and no ``value``, so it is uncontrolled and always reopens
  showing "GHC" no matter what the school actually stores, even though the
  component's own ``useEffect`` takes the trouble to seed ``currency`` from the
  store. A saved currency therefore cannot be read back off this screen. That is
  a display-binding quirk, not data loss (the value does reach the database), and
  fixing a shared page every scenario's provisioning drives is not this unit's
  risk to take — so the edit below stays on the fields that visibly round-trip,
  and the currency is left as provisioning set it.

* **Every input filters its own keystrokes**, which is why the values below look
  the way they do: the name accepts ``[A-Za-z\\s]`` only, the address
  ``[A-Za-z0-9\\s.,-/]``, the phone ``\\+?\\d{,15}``, and the email is dropped
  outright unless what lands in it is already a complete address. Playwright's
  ``fill`` sets the whole value in one input event, so a value that fails the
  field's own regex does not land partially — it simply never lands, and the
  screen quietly keeps the old one.

What this test does NOT change, and why: the school's **name** is left alone.
Teardown finds the school by id, but the orphan sweeper matches on the "TEST"
prefix and the other units sharing this session's ``minimal`` school read
``ctx.school_name``, so renaming it here would be a side effect on tests that
never asked for one.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from config.module_catalog import MANDATORY_MODULES
from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag, unique_email
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto
from tests.pages.login import login_as
from tests.pages.school_admin.config import (
    ADDRESS_FIELD,
    EMAIL_FIELD,
    HEADING,
    NAME_FIELD,
    PHONE_FIELD,
    SAVE_BUTTON,
    ConfigPage,
)

CONFIG_MODULE = "school_configuration"
CONFIG_ROUTE = "config"
MANAGE_SCENARIO = "minimal"

# The floor pack, and the module the floor pack really does exclude — asserted
# alongside the positive one so "school_configuration is licensed" cannot pass
# merely because the school ended up with everything licensed.
ALWAYS_LICENSED_SCENARIO = "minimal"
UNLICENSED_PROBE = "fees"

# Where the frontend sends anyone it decides is not allowed in
# (src/app/auth/no-access/page.tsx). Nothing on this path may reach it.
NO_ACCESS_URL = re.compile(r"/auth/no-access")

# The refusal utils/permissions.has_permission raises when a school's pack omits
# the module. Quoted only so a failure names what would have been wrong.
FEATURE_DENIAL = re.compile(r"Feature not available in your plan", re.I)

# The sidebar entry (nav-config.tsx, "Governance Module" group). Anchored, so it
# cannot resolve to "Notification Config" or "Tax Config".
NAV_CONFIGURATION = re.compile(r"^\s*Configuration\s*$", re.I)

# The strapline under the heading — proof the page mounted rather than merely
# that some heading with those words exists somewhere.
PAGE_STRAPLINE = re.compile(r"Customize the application to suit your school brand", re.I)

# What the SchoolAdmin changes. The address keeps to the characters the field
# accepts; the phone is digits only (the input strips anything else and caps at
# 15); the email is generated because the backend rejects reserved TLDs.
NEW_ADDRESS = "TEST New Campus Road Achimota"
NEW_PHONE = "0302555111"


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="governance.school_configuration.manage.school_admin",
    title="School Configuration",
    subtitle="SchoolAdmin creates and manages school configuration",
)
def test_school_admin_manages_school_configuration(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A SchoolAdmin edits their school's profile and it survives a fresh session.

    The proof is deliberately not the success toast. After saving, the browser's
    cookies and storage are dropped and the administrator signs in again — the
    auth store is rebuilt from the login response, which ``auth.py`` reads
    straight out of ``school_profile``. So the values the reopened screen shows
    are the values the database holds, and a save the frontend announced but
    never persisted fails here. The same record is read once over the API as
    well, so a failure says which field is wrong rather than only that a form
    looked stale.
    """
    ctx = provisioned_school
    assert CONFIG_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {CONFIG_MODULE!r} — "
        f"config/scenarios.py requires it in every pack, so a school without it "
        f"should not have provisioned at all"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    config = ConfigPage(page, base_url)

    new_email = unique_email("schoolmail", ctx.scenario_id)
    address = f"{NEW_ADDRESS} {run_tag()[:4]}"

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step("Open Configuration from the Governance menu"):
        # No branch is selected, and none may be: the Governance section is
        # noBranchOnly, so choosing a branch first would hide this very link.
        _open_configuration(page, config)

    with demo.step("The screen opens on the school exactly as onboarding left it"):
        expect(page.get_by_text(as_pattern(PAGE_STRAPLINE))).to_be_visible()
        expect(page.get_by_placeholder(NAME_FIELD)).to_have_value(
            re.compile(r"TEST", re.I)
        )
        expect(config.notification_checkbox("email")).to_be_checked()
        expect(config.notification_checkbox("sms")).not_to_be_checked()

    with demo.step("The school has moved — record the new address and phone line"):
        config.fill_labeled(ADDRESS_FIELD, address)
        config.fill_labeled(PHONE_FIELD, NEW_PHONE)

    with demo.step("Point the school's public email at the new front desk"):
        config.fill_labeled(EMAIL_FIELD, new_email)

    with demo.step("Send notifications by SMS instead of email from now on"):
        config.set_notification_preference("sms")
        expect(config.notification_checkbox("email")).not_to_be_checked()

    with demo.step("Save the configuration"):
        # Waits for the app's own "School Profile Successfully Updated" toast.
        config.save()

    with demo.step("Sign out completely, so nothing can be answered from cache"):
        _sign_out(page, base_url)

    with demo.step("Sign back in and reopen Configuration — the school kept the changes"):
        login_as(page, base_url, ctx.school_admin)
        _open_configuration(page, config)

        expect(page.get_by_placeholder(ADDRESS_FIELD)).to_have_value(address)
        expect(page.get_by_placeholder(PHONE_FIELD)).to_have_value(NEW_PHONE)
        # Case-insensitively: the backend's EmailStr round-trips the address it
        # was given, but nothing in the contract promises the casing back.
        expect(page.get_by_placeholder(EMAIL_FIELD)).to_have_value(
            re.compile(rf"^{re.escape(new_email)}$", re.I)
        )
        expect(config.notification_checkbox("sms")).to_be_checked()
        expect(config.notification_checkbox("email")).not_to_be_checked()

        # And the record itself, so a failure names the field rather than only
        # reporting that a form looked stale.
        token = api.login(
            ctx.school_admin.email, ctx.school_admin.password
        )["access_token"]
        stored = api.get(f"/school_profile/{ctx.school_id}", token=token)
        assert stored.status_code == 200, (
            f"a SchoolAdmin must be able to read their own school profile — got "
            f"{stored.status_code}: {stored.text[:300]}"
        )
        body = stored.json()
        assert body.get("address") == address, (
            f"the saved address never reached school_profile {ctx.school_id} — "
            f"stored {body.get('address')!r}, expected {address!r}"
        )
        assert body.get("phone_number") == NEW_PHONE, (
            f"the saved phone number never reached school_profile "
            f"{ctx.school_id} — stored {body.get('phone_number')!r}, expected "
            f"{NEW_PHONE!r}"
        )
        assert str(body.get("email", "")).lower() == new_email.lower(), (
            f"the saved school email never reached school_profile "
            f"{ctx.school_id} — stored {body.get('email')!r}, expected "
            f"{new_email!r}"
        )
        assert str(body.get("notification_preference", "")).lower() == "sms", (
            f"the school still notifies by "
            f"{body.get('notification_preference')!r}; the Update should have "
            f"switched it to 'sms'"
        )


@pytest.mark.school_admin
@pytest.mark.scenario(ALWAYS_LICENSED_SCENARIO)
def test_school_configuration_is_licensed_on_the_minimal_pack(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """School Configuration survives the most restricted pack the product can make.

    This is the counterpart to a module's ``denied`` unit, and it exists because
    ``school_configuration`` has no denial path to test: the feature-pack builder
    locks the "governance" and "people" groups into every pack (``BASIC_GROUPS``
    in ``smsfrontend/src/app/module/feature_flag/{create,edit}/page.tsx``, with
    only ``guardians`` and ``families`` optional inside them). Governance being
    core and always on is intended product behaviour, confirmed 2026-08-09 — see
    ``config/module_catalog.MANDATORY_MODULES``. So the assertion here is
    reachability, and reachability is the whole assertion: nothing below tries to
    prove a gate exists, and none of it should ever be "fixed" by adding one.

    Three independent facts, because any one alone could be true for the wrong
    reason:

    1. **The licence itself.** ``GET /school_profile/{id}/features`` — the same
       read the sidebar makes on mount — lists ``school_configuration`` for a
       school whose pack is the floor scenario. ``fees`` is checked in the same
       breath and must be *absent*: that is what proves the school really is on a
       restricted pack rather than an accidentally-unrestricted one, which would
       make the positive half vacuous.
    2. **The API answers.** ``GET /school_profile/{id}`` is guarded by
       ``has_permission("read", "school_configuration")``, and that dependency
       enforces the feature pack as well as the role (``utils/permissions.py``) —
       so a 403 "Feature not available in your plan" is exactly what a school
       that had lost the module would get. It must be a 200.
    3. **The screen is offered and mounts.** The Governance entry "Configuration"
       is present in the sidebar and leads to ``/module/config``, which renders
       its own workspace instead of redirecting to ``/auth/no-access``.

    A SchoolAdmin is exempt from both *frontend* guards (``useModuleGuard``
    returns true for the role outright, and ``SideNavigation.canShowItem`` lets a
    SchoolAdmin past the module gate), so the UI half is deliberately not the
    evidence for the licence — fact 1 and fact 2 are. What the UI half proves is
    the user-visible half of the claim: the way in is still there.

    No branch is selected, and none may be: the whole Governance section is
    ``noBranchOnly``, so picking a branch first would hide the very link this
    test asserts on.
    """
    ctx = provisioned_school

    assert CONFIG_MODULE in MANDATORY_MODULES, (
        f"{CONFIG_MODULE!r} is no longer listed in "
        f"config/module_catalog.MANDATORY_MODULES, so this unit's premise — that "
        f"no pack can exclude it — no longer holds. Either the catalog drifted or "
        f"the product decision changed; this test is not the place to decide which."
    )
    assert ctx.scenario_id == ALWAYS_LICENSED_SCENARIO, (
        f"this unit is written against the floor pack {ALWAYS_LICENSED_SCENARIO!r}; "
        f"got {ctx.scenario_id!r}"
    )
    assert CONFIG_MODULE in ctx.feature_modules, (
        f"the {ctx.scenario_id!r} scenario should still declare {CONFIG_MODULE!r} "
        f"(config/feature_scenarios.yaml requires it in every pack)"
    )
    assert UNLICENSED_PROBE not in ctx.feature_modules, (
        f"{UNLICENSED_PROBE!r} is now part of the {ctx.scenario_id!r} pack, so it "
        f"can no longer serve as the proof that this school is restricted. Pick "
        f"another module the floor pack omits."
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The pack is the floor, and it still licenses this module ───────────
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so it proves "
        f"nothing about what a pack can exclude. Provisioning phase A assigns "
        f"one — check that it did."
    )
    licensed = body.get("modules") or []
    assert CONFIG_MODULE in licensed, (
        f"{ctx.school_name!r} is on the floor pack {body.get('pack_name')!r} and "
        f"has LOST {CONFIG_MODULE!r} — licensed modules are {sorted(licensed)}. "
        f"Governance is core and cannot be excluded by any pack; the regression "
        f"is in the pack builder or in FeaturePackService.get_school_modules, not "
        f"in this test."
    )
    assert UNLICENSED_PROBE not in licensed, (
        f"{ctx.school_name!r} is licensed for {UNLICENSED_PROBE!r} even though the "
        f"{ctx.scenario_id!r} pack omits it, so this school is not restricted at "
        f"all and the assertion above proves nothing — licensed modules are "
        f"{sorted(licensed)}."
    )

    # ── 2. The module's own API answers, licence gate and all ─────────────────
    profile = api.get(f"/school_profile/{ctx.school_id}", token=token)
    assert profile.status_code == 200, (
        f"GET /school_profile/{ctx.school_id} is gated by "
        f"has_permission('read', {CONFIG_MODULE!r}), which enforces the feature "
        f"pack as well as the role — a school on the floor pack must still be "
        f"allowed to read its own configuration. Got {profile.status_code}: "
        f"{profile.text[:300]}"
        + (
            "  ← that is the unlicensed-module refusal; the pack has dropped a "
            "module no pack may drop."
            if FEATURE_DENIAL.search(profile.text) else ""
        )
    )
    assert profile.json().get("id") == ctx.school_id, (
        f"GET /school_profile/{ctx.school_id} answered with a different school: "
        f"{profile.json().get('id')!r}"
    )

    # ── 3. The screen is offered in the sidebar and really mounts ─────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    link = page.get_by_role("link", name=NAV_CONFIGURATION).first
    expect(link).to_be_visible(timeout=20_000)
    link.click()

    page.wait_for_url(re.compile(rf"/module/{CONFIG_ROUTE}\b"), timeout=20_000)
    expect(page.get_by_role("heading", name=HEADING)).to_be_visible(timeout=20_000)
    expect(page.get_by_text(as_pattern(PAGE_STRAPLINE))).to_be_visible()

    # The workspace itself, not just the header: both guards in page.tsx bail by
    # returning null, so a form that is actually rendered is what says the page
    # decided the user belongs here.
    expect(page.get_by_placeholder(NAME_FIELD)).to_be_visible()
    expect(page.get_by_role("button", name=SAVE_BUTTON).first).to_be_visible()

    # useModuleGuard redirects from an effect, so give it the chance it would
    # have taken before calling the mount a success.
    page.wait_for_timeout(1_500)
    assert not NO_ACCESS_URL.search(page.url), (
        f"/module/{CONFIG_ROUTE} bounced a SchoolAdmin of {ctx.school_name!r} to "
        f"{page.url} — School Configuration must stay reachable on every pack."
    )
    expect(page.get_by_role("heading", name=HEADING)).to_be_visible()


# ───────────────────────────── internals ─────────────────────────────────────


def _open_configuration(page: Page, config: ConfigPage) -> None:
    """Walk the sidebar into /module/config, the way a real user reaches it.

    The link is preferred over a direct navigation because the video has to show
    how the screen is found. It is not *required*, though: the sidebar collapses
    on narrow viewports, and the workspace — not the way in — is what this unit
    asserts on, so a missing link falls back to opening the route.

    The wait matters. ``SideNavigation`` renders an empty shell until the
    persisted zustand store has rehydrated (``if (!_hasHydrated)``), so a bare
    ``count()`` the instant after login is 0 for reasons that have nothing to do
    with the entry being absent — and the fallback would then silently deep-link,
    which is exactly the shortcut the video must not take. Only a genuine timeout
    falls through.
    """
    link = page.get_by_role("link", name=NAV_CONFIGURATION).first
    try:
        link.wait_for(state="visible", timeout=20_000)
    except PlaywrightTimeoutError:
        config.open()
        return
    link.click()
    page.wait_for_url(re.compile(rf"/module/{CONFIG_ROUTE}\b"), timeout=20_000)
    expect(page.get_by_role("heading", name=HEADING)).to_be_visible(timeout=20_000)


def _sign_out(page: Page, base_url: str) -> None:
    """End the session and land back on the login screen.

    Deliberately not ``tests.pages.login.logout``: this build ships no logout
    control in the module chrome at all (nothing in ``src/components`` renders
    one — only ``/auth/no-access`` does), so that helper would always fall
    through to its own AssertionError. Dropping the cookies the Next.js
    middleware reads plus the localStorage the zustand auth store persists is
    what actually empties ``school_config``, which is the point: the values the
    next screen shows can then only have come back from the server.
    """
    page.context.clear_cookies()
    page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    goto(page, base_url.rstrip("/") + "/auth/login")
