"""People → Guardians — the parent/carer register (`guardians`).

Where this module lives
    ``/module/guardians`` (``smsfrontend/src/app/module/guardians/page.tsx``).
    The "Manage Guardians" workspace: a ModuleHeader stat strip over
    ``GET /statistics/guardian``, a paginated Name / Phone Number / Address /
    Marital Status / Email table over ``GET /guardian/``, a "Search Guardian by
    name / phone / email / address" box, an "Add Guardian" link into the
    three-step wizard at ``/module/guardians/add-guardians`` (``POST /guardian/``)
    and a "Send Fee Reminder" bulk action.

Manage path: a SchoolAdmin of the ``library_and_community`` school
(``test_school_admin_creates_and_manages_a_guardian``) — one guardian's whole
life on the screen: registered through the three-step wizard, read back off the
register and off their own profile, then corrected through the edit wizard.

Negative path: a SchoolAdmin of the ``minimal`` school
(``test_guardians_denied_for_school_admin_when_module_disabled``). That pack is
the floor case the feature-pack builder can actually produce — the locked
"people" and "governance" groups only, with ``guardians`` and ``families`` being
the two members of "people" that stay optional (BASIC_GROUPS in
``smsfrontend/src/app/module/feature_flag/{create,edit}/page.tsx``). So
``guardians`` really can be unlicensed, and this scenario is a school where it is.

Where the denial actually lives — and where it does NOT
    Not in the sidebar, not in the middleware, and not in either of the two
    guards ``page.tsx`` calls. All of them wave a SchoolAdmin through before the
    feature pack is consulted:

    * ``useModuleGuard("guardians")`` sets ``hasAccess = true`` for a SchoolAdmin
      *before* it ever reads the ``schoolModules`` cookie, so the
      ``hasModuleAccess === false`` branch — the one that returns ``null`` and
      pushes /auth/no-access — is unreachable for this role.
    * ``usePermissionGuard("guardians")`` returns early on
      ``isSchoolAdminRole(role)`` in its effect, and its ``hasAccess`` memo
      returns ``true`` on the same test, so ``if (!hasPermission) return null``
      never fires either.
    * ``src/middleware.ts`` excludes ``isSchoolAdmin`` from its module
      enforcement, so the route is never turned away before it mounts.

    What denies them is the backend. Every guardian route in
    ``newschoolapp/api/routes/guardian.py`` carries
    ``Depends(has_permission(<read|manage>, "guardians"))``; that dependency is
    solved before the path params are used and before any row is looked up, and
    the feature-pack half of ``utils.permissions.has_permission`` answers
    **403 "Feature not available in your plan"** for a school whose pack omits
    the module named in it. The gate module is ``guardians`` — the same key the
    pack, the nav entry and ``page.tsx`` all use — so the pack that omits it is
    exactly what produces the 403.

    The UI consequence follows from that 403. ``fetchGuardianData`` runs from the
    page's mount effect through ``apiGet`` (plain global axios), and the response
    interceptor in ``src/utils/handleErrorMessage.ts`` recognises the "not
    available in your plan" detail (``shouldRedirectToNoAccess``) and performs a
    hard ``window.location`` redirect to **/auth/no-access**. So the landing page
    — not the ``PageError`` panel this page renders for an ordinary fetch failure
    — is the denial surface, and that panel is asserted absent below for exactly
    that reason.

Why the branch is selected first, and why it is not incidental
    Both of this page's mount effects return early for a SchoolAdmin while
    ``currentSchoolAdminBranch?.branch_id`` is unset::

        const role = authUserProfile?.roles?.name?.toLowerCase() ?? "";
        if (role.includes("schooladmin") || role.includes("superadmin")) {
          if (!currentSchoolAdminBranch?.branch_id) {
            console.warn("Branch data not available for cross-branch admin …");
            return;
          }
        }

    With no branch in the store the page issues no request at all, so there is no
    403, no interceptor and no redirect — the screen simply renders an empty
    table. That would make every "the workspace is absent" assertion below pass
    for the wrong reason. ``BranchesPage.select_branch`` fills the store (see that
    method for why only the branch row's "View" button can), which is the same
    prerequisite every SchoolAdmin create has.

Deliberately *not* asserted: that the sidebar hides "Guardians"
    ``nav-config.tsx`` gives that entry ``permission: "guardians"``, and
    ``SideNavigation.canShowItem`` returns on the permission check *before* the
    module gate ("Permission check takes priority — having the permission implies
    the module is available"). The seeded SchoolAdmin holds
    ``("manage", "guardians")`` (``db/repository/permissions.py``), so the entry
    renders whatever the pack says. Its presence says nothing about this school's
    licence, so it is not asserted either way.

Deliberately *not* asserted: ``GET /guardian/{id}/wards``
    That one route is gated on ``has_permission("read", "home")``, not on
    ``guardians`` — it is what a signed-in Guardian's own home screen calls. A
    school without the guardians module is still licensed for ``home``, so the
    route answering is correct behaviour, not a licensing hole. Asserting a 403
    there would be asserting a gate the product does not have.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import (
    TEST_PREFIX,
    make_person,
    run_tag,
    unique_email,
)
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.people.guardians import GuardiansPage
from tests.pages.school_admin.branches import BranchesPage

GUARDIANS_MODULE = "guardians"

# config/module_catalog.py's route for this module.
GUARDIANS_ROUTE = "guardians"

DENIED_SCENARIO = "minimal"

# The role whose permissions are checked against the pack.
SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# The two denials utils/permissions.py can answer with. A school that holds the
# permission but not the module gets the first; one that holds neither gets the
# second. Either is a correct denial — anything else is not.
DENIAL_DETAIL = re.compile(
    r"Feature not available in your plan"
    r"|You do not have permission to perform this action",
    re.I,
)

# Where the frontend sends a user it has decided is not allowed in, and the copy
# it greets them with (src/app/auth/no-access/page.tsx).
NO_ACCESS_URL = re.compile(r"/auth/no-access")
ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)

# ── the guardians workspace's own chrome, none of which may reach this admin ──
# src/app/module/guardians/page.tsx.
GUARDIANS_HEADING = re.compile(r"^\s*Manage Guardians\s*$", re.I)
GUARDIANS_SUBHEADING = re.compile(
    r"Easily update Guardian information to ensure data accuracy", re.I
)
# Built through as_pattern: the literal placeholder carries "/" separators, which
# would close Playwright's /<source>/<flags> selector literal at the first one.
GUARDIANS_SEARCH_FIELD = as_pattern(r"^\s*Search Guardian by name / phone / email")
GUARDIANS_TABLE_CAPTION = re.compile(r"^\s*All Guardians\s*$", re.I)
ADD_GUARDIAN_BUTTON = re.compile(r"^\s*Add Guardian\s*$", re.I)
SEND_FEE_REMINDER_BUTTON = re.compile(r"^\s*Send Fee Reminder\b", re.I)
GUARDIANS_EMPTY_STATE = re.compile(r"^\s*No guardians found\s*$", re.I)
# The panel the page renders when a fetch fails for any *ordinary* reason
# (components/common/PageError). Seeing it would mean a licensing refusal had
# been handled as a plain error instead of as a denial.
GUARDIANS_LOAD_FAILURE = re.compile(r"Failed to load guardians", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_guardians_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With the module off the pack, a SchoolAdmin gets no guardian register at all."""
    ctx = provisioned_school
    if GUARDIANS_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {GUARDIANS_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had guardian rights anyway", which would make the 403s vacuous.
    # db/repository/permissions.py seeds this role with ("manage", "guardians"),
    # and has_permission lets manage stand in for read — so the permission half
    # of the gate passes outright for every route asserted below.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert GUARDIANS_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{GUARDIANS_MODULE!r} permission, which is the one every guardian route "
        f"is gated on. This test would then be asserting a denial the role gets "
        f"for free. Re-point it at the feature pack only, or fix the seed in "
        f"newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{GUARDIANS_MODULE!r} proves nothing about the gate. Provisioning "
        f"phase A assigns one — check that it did."
    )
    licensed = body.get("modules") or []
    assert GUARDIANS_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {GUARDIANS_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it. "
        f"Note that the pack builder locks the whole 'people' group in except for "
        f"guardians and families — those two are the optional members, so this "
        f"one genuinely can be off."
    )

    # ── 2. The denial itself: every guardian route is refused ─────────────────
    #
    # Both halves of the gate are covered — the reads the register performs
    # (has_permission("read", "guardians")) and the writes the "Add Guardian"
    # wizard, the profile screen and the Assign Ward modal perform
    # (has_permission("manage", "guardians")). The guardian id is deliberately
    # arbitrary: has_permission is a route-level dependency, solved before the
    # path params are used and long before any row is looked up, so a 404 here
    # would itself be the failure. The list read is asserted both with and
    # without the branch scope page.tsx appends, because the unscoped form is a
    # 400 BRANCH_ID_REQUIRED for a SchoolAdmin *inside* the handler — the licence
    # must be refused before that ever runs. For the same reason the create body
    # below never has to be creatable, but it carries the TEST prefix and a
    # generated learningbrix-qa.com address anyway, so a regression that *did*
    # let it through leaves a sweepable row rather than an orphan nobody can find.
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"?branch_id={branch_id}" if branch_id else ""
    tag = run_tag()

    refusals = {
        # What the register itself calls on mount, in both the shapes page.tsx
        # builds depending on whether a branch has been zoomed into.
        "list": api.get(f"/guardian/{branch_query}", token=token),
        "list_unscoped": api.get("/guardian/", token=token),
        "detail": api.get("/guardian/1", token=token),
        # …and the manage half: the add-guardians wizard, the edit screen, the
        # profile's delete, and the [guardianID] AssignWardModal.
        "create": api.post(
            "/guardian/",
            token=token,
            json={
                "occupation": f"{TEST_PREFIX} Denied Occupation",
                "relationship_type": "Parent",
                "student_ids": [],
                "user": {
                    "first_name": TEST_PREFIX,
                    "other_names": f"Denied Guardian {tag}",
                    "email": unique_email("denied-guardian", ctx.scenario_id),
                    "password": "123456789",
                    "password_confirmation": "123456789",
                    "school_branch_id": branch_id or 1,
                    "is_active": True,
                },
            },
        ),
        "update": api.put(
            "/guardian/1",
            token=token,
            json={"occupation": f"{TEST_PREFIX} Denied Update {tag}"},
        ),
        "delete": api.delete("/guardian/1", token=token),
        "link_ward": api.post("/guardian/1/wards/1", token=token),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{GUARDIANS_MODULE!r}, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a guardian register in front of them ────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Mandatory, and not merely the usual SchoolAdmin branch prerequisite: both of
    # this page's mount effects refuse to fetch anything until the branch store is
    # filled (see the module docstring), and with no fetch there is no 403 to deny
    # them with. Selecting the branch is what makes the denial observable.
    if ctx.branches:
        BranchesPage(page, frontend_base_url).select_branch(ctx.branches[0]["name"])

    # A SchoolAdmin is exempt from the middleware gate, from useModuleGuard and
    # from usePermissionGuard, so this route really does mount and really does
    # start fetching — and the axios interceptor turns the refusal into a hard
    # redirect. Waiting for the URL is therefore also what stops the "workspace is
    # absent" assertions below from passing merely because the page had not
    # finished loading.
    goto_module(page, frontend_base_url, GUARDIANS_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the workspace survives the redirect: not its heading, not its
    # toolbar, not the table, not a single row, and not the two bulk/write
    # actions. "Failed to load guardians" is asserted absent for the same reason
    # as the categories unit: rendering it would mean a licensing refusal had been
    # handled as an ordinary fetch error rather than as a denial.
    expect(
        page.get_by_role("heading", name=as_pattern(GUARDIANS_HEADING))
    ).to_have_count(0)
    expect(page.get_by_text(as_pattern(GUARDIANS_SUBHEADING))).to_have_count(0)
    expect(page.get_by_placeholder(GUARDIANS_SEARCH_FIELD)).to_have_count(0)
    expect(page.get_by_text(as_pattern(GUARDIANS_TABLE_CAPTION))).to_have_count(0)
    expect(page.get_by_text(as_pattern(ADD_GUARDIAN_BUTTON))).to_have_count(0)
    expect(page.get_by_text(as_pattern(SEND_FEE_REMINDER_BUTTON))).to_have_count(0)
    expect(page.get_by_text(as_pattern(GUARDIANS_EMPTY_STATE))).to_have_count(0)
    expect(page.get_by_text(as_pattern(GUARDIANS_LOAD_FAILURE))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)


# ───────────── manage path: the SchoolAdmin runs the guardian register ────────
#
# Constants below are prefixed rather than sharing the denial section's names:
# this module file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# The role this workspace is built for
#     A SchoolAdmin holds ("manage", "guardians") on the seeded role
#     (newschoolapp/db/repository/permissions.py), which is what
#     POST /guardian/ and PUT /guardian/{id} are declared with, and what the
#     screen's own ``isManage`` flag gates the "Add Guardian" link and the
#     profile's "Edit Profile" / "Assign Ward" buttons on.
#     ``library_and_community`` licenses the module, so the feature-pack half of
#     that dependency passes too and the school really does get the workspace.
#
# Why the branch is selected first, and why it is not cosmetic
#     Same reason as the denial unit above, plus two more. Both of the register's
#     mount effects return early for a SchoolAdmin whose branch store is empty,
#     so the table would never load; the sidebar's whole "People Module" section
#     is ``branchOnly`` (nav-config.tsx), so the "Guardians" entry the video walks
#     through is not even drawn; and the create wizard posts
#     ``school_branch_id: currentSchoolAdminBranch?.branch_id ?? 0``, which the
#     backend answers 404 "The Branch does not exist" for.
#
# "Manage" here is register → read back → correct
#     A guardian is not deleted at the end, and that is deliberate: nothing under
#     /module/guardians offers a delete (page.tsx has no row menu and the profile
#     screen has no destructive action), so retiring one would mean reaching for
#     DELETE /guardian/{id} over the API — a route no user of this module can
#     reach, which would make the test assert something the product does not do.
#     The guardian is left behind carrying the run tag in their generated email
#     address, which is what the orphan sweeper matches on, and the whole school
#     is torn down by the provisioning fixture anyway.
#
# What the edit wizard can actually change — and what it silently cannot
#     ``edit-guardian/[guardianID]/page.tsx`` builds its PUT body from
#     ``occupation``, ``additional_remarks``, ``relationship_type``,
#     ``work_address``, ``employer_name``, ``student_ids`` and a ``user`` block of
#     ``first_name``/``other_names``/``profile_pic``/``religion``. The gender,
#     date-of-birth, marital-status, nationality, address, location, phone and
#     email boxes its first two steps render are never sent at all, so this test
#     corrects the Admission Information step — the guardian-profile fields the
#     profile screen actually prints — and asserts each one on the reloaded
#     profile *and* on GET /guardian/{id}. Do not extend it to the first two
#     steps expecting them to stick; and do not "fix" that by widening the
#     payload, which is a product question (what a school may amend about a
#     person after the fact), not a defect anyone can settle from here.
#
#     Two other things this unit deliberately does not do:
#       * ``student_ids`` on the edit — ``GuardianService.update_guardian`` hands
#         it to a generic setattr loop and ``GuardianProfile`` has no such column
#         (the link lives on the ``guardian_students`` association), so the PUT
#         succeeds and changes nothing. Testing it would be a green test for a
#         write that never happened. See ``GuardiansPage.link_ward``.
#       * assigning the provisioned student as a ward — that student was admitted
#         against the provisioning guardian and so already belongs to a family,
#         and ``FamilyService.ensure_family`` refuses a second family with 400
#         "Student already belongs to a family". That refusal is the product
#         working (a student has at most one family), not a defect.

MANAGE_SCENARIO = "library_and_community"

# What the guardian is registered as. Every one of these boxes strips anything
# outside /[A-Za-z\s]/ on the way in (add-guardians/components/*.tsx), so the run
# tag — which is hex — must stay out of them; the generated email carries it
# instead, and that is what the orphan sweeper and the search box both match on.
MANAGE_RELATIONSHIP = "Father"
MANAGE_OCCUPATION = "Tailor"
MANAGE_LOCATION = "Accra"

# …and what the school corrects it to once the guardian changes jobs. Work
# Address is the one free-text field of the step (no letters-only filter), so it
# is written as a real address on purpose — it is also the only assertion below
# that would catch that filter being applied where it is not today.
MANAGE_NEW_OCCUPATION = "Head Chef"
MANAGE_NEW_RELATIONSHIP = "Stepfather"
MANAGE_EMPLOYER = "Bookworm Catering"
MANAGE_WORK_ADDRESS = "12 Ring Road East, Accra"
MANAGE_DESCRIPTION = "Reachable after four in the afternoon"

# Captions on the profile screen (guardians/[guardianID]/page.tsx). Anchored so
# "Phone Number" cannot resolve to "Secondary Phone Number", which sits directly
# beneath it, and so "Occupation" cannot resolve to anything the edit wizard left
# mounted.
MANAGE_DETAIL_RELATIONSHIP = re.compile(r"^\s*Relationship to Ward\(s\)\s*$", re.I)
MANAGE_DETAIL_OCCUPATION = re.compile(r"^\s*Occupation\s*$", re.I)
MANAGE_DETAIL_EMPLOYER = re.compile(r"^\s*Employer\s*$", re.I)
MANAGE_DETAIL_WORK_ADDRESS = re.compile(r"^\s*Work Address\s*$", re.I)
MANAGE_DETAIL_DESCRIPTION = re.compile(r"^\s*Description\s*$", re.I)
MANAGE_DETAIL_EMAIL = re.compile(r"^\s*Email\s*$", re.I)
MANAGE_DETAIL_PHONE = re.compile(r"^\s*Phone Number\s*$", re.I)
MANAGE_DETAIL_ADDRESS = re.compile(r"^\s*Residential Address\s*$", re.I)
# What the profile prints for a guardian-profile field that was never filled —
# but only for the ones it renders through ``||``. Work Address, Description and
# Relationship take that path; Occupation and Employer use ``??``, and the create
# wizard sends "" rather than null for every untouched field, so those two render
# blank instead.
MANAGE_NOT_PROVIDED = "Not provided"


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="people.guardians.manage.school_admin",
    title="Guardians",
    subtitle="SchoolAdmin creates and manages guardians",
)
def test_school_admin_creates_and_manages_a_guardian(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A SchoolAdmin registers a guardian, reads them back, then corrects them.

    Every claim is made against what the next person to open the screen would
    see — the register's own row, the guardian's profile, and the record as
    ``GET /guardian/{id}`` actually stores it — so a write the wizard toasted
    about but that never reached the database fails on the following step
    instead of passing quietly.
    """
    ctx = provisioned_school
    assert GUARDIANS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {GUARDIANS_MODULE!r} for the "
        f"manage path — an unlicensed school is denied the register outright "
        f"(see test_guardians_denied_for_school_admin_when_module_disabled)"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — phase B creates one for "
        "every scenario, and without one in the store this page issues no GET at "
        "all, the People sidebar section is not drawn, and the create wizard "
        "would post school_branch_id: 0"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    guardians = GuardiansPage(page, base_url)
    branch_name = str(ctx.branches[0]["name"])

    # Faker names, sanitised the same way the wizard's inputs sanitise them, so
    # the assertions look for the name the app will actually have stored rather
    # than the one that was typed.
    person = make_person("guardian-manage", ctx.scenario_id, gender="Male")
    first_name = _manage_letters(person.first_name)
    last_name = _manage_letters(person.last_name)
    full_name = f"{first_name} {last_name}"
    phone = _manage_digits(person.phone)

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Point the console at {branch_name}"):
        # Mandatory, not cosmetic: it fills the branch store the register's fetch
        # effects wait on, unlocks the branchOnly People menu, and is what the
        # create wizard reads school_branch_id from.
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Open Guardians from the People menu"):
        guardians.expect_nav_entry()
        guardians.open_from_nav()

    with demo.step("This is the register of parents and carers today"):
        guardians.expect_column_headers()
        expect(
            page.get_by_text(as_pattern(GUARDIANS_TABLE_CAPTION)).first
        ).to_be_visible(timeout=20_000)
        expect(
            page.get_by_role("button", name=as_pattern(ADD_GUARDIAN_BUTTON)).first
        ).to_be_visible()
        guardians.expect_no_load_failure()

    with demo.step(f"Register {full_name} as a new guardian"):
        # create_guardian walks all three steps, waiting for each Continue to
        # enable, and lands back on the register with the new row on screen.
        guardians.create_guardian(
            first_name=first_name,
            last_name=last_name,
            email=person.email,
            phone=phone,
            address=person.address,
            relationship=MANAGE_RELATIONSHIP,
            gender=person.gender,
            date_of_birth="1985-04-17",
            location=MANAGE_LOCATION,
            occupation=MANAGE_OCCUPATION,
        )

    with demo.step("The register now carries them, with their contact details"):
        # Name is asserted as "contains": the cell also holds the initials avatar
        # the page draws when a guardian has no photo.
        expect(guardians.cell(person.email, "name")).to_contain_text(full_name)
        expect(guardians.cell(person.email, "phone")).to_have_text(phone)
        expect(guardians.cell(person.email, "address")).to_contain_text(person.address)
        expect(guardians.cell(person.email, "email")).to_have_text(person.email)
        guardians.expect_no_load_failure()

    with demo.step("Open their profile — this is what the school holds on them"):
        guardian_id = guardians.open_detail(person.email)
        expect(guardians.detail_value(MANAGE_DETAIL_RELATIONSHIP)).to_have_text(
            MANAGE_RELATIONSHIP
        )
        expect(guardians.detail_value(MANAGE_DETAIL_OCCUPATION)).to_have_text(
            MANAGE_OCCUPATION
        )
        # Nothing was said about where they work yet, so the profile must say so
        # — otherwise the correction below would be asserting against fields that
        # were already full. Work Address and Description are the two the profile
        # prints through ``||``, so the empty string the create wizard sends for
        # every untouched field really does surface as "Not provided" (Employer
        # and Occupation use ``??``, which "" slips straight through, so the
        # employer box simply renders blank until the edit fills it).
        expect(guardians.detail_value(MANAGE_DETAIL_WORK_ADDRESS)).to_have_text(
            MANAGE_NOT_PROVIDED
        )
        expect(guardians.detail_value(MANAGE_DETAIL_DESCRIPTION)).to_have_text(
            MANAGE_NOT_PROVIDED
        )
        expect(guardians.detail_value(MANAGE_DETAIL_EMPLOYER)).to_have_text("")
        expect(guardians.detail_value(MANAGE_DETAIL_PHONE)).to_have_text(phone)
        expect(guardians.detail_value(MANAGE_DETAIL_EMAIL)).to_have_text(person.email)

    with demo.step("They have no wards yet — no student is linked to them"):
        guardians.open_wards_tab()
        guardians.expect_no_wards()

    with demo.step("They have changed jobs, so correct the profile"):
        guardians.edit_profile(
            occupation=MANAGE_NEW_OCCUPATION,
            employer=MANAGE_EMPLOYER,
            work_address=MANAGE_WORK_ADDRESS,
            relationship=MANAGE_NEW_RELATIONSHIP,
            description=MANAGE_DESCRIPTION,
        )

    with demo.step("The correction is what the school now holds", dwell_ms=2000):
        reopened = guardians.open_detail(person.email)
        assert reopened == guardian_id, (
            f"the register's row for {person.email!r} now links to guardian "
            f"{reopened} but the profile that was edited was {guardian_id} — the "
            f"edit created a second record instead of amending the first"
        )
        expect(guardians.detail_value(MANAGE_DETAIL_OCCUPATION)).to_have_text(
            MANAGE_NEW_OCCUPATION
        )
        expect(guardians.detail_value(MANAGE_DETAIL_EMPLOYER)).to_have_text(
            MANAGE_EMPLOYER
        )
        expect(guardians.detail_value(MANAGE_DETAIL_RELATIONSHIP)).to_have_text(
            MANAGE_NEW_RELATIONSHIP
        )
        expect(guardians.detail_value(MANAGE_DETAIL_WORK_ADDRESS)).to_have_text(
            MANAGE_WORK_ADDRESS
        )
        expect(guardians.detail_value(MANAGE_DETAIL_DESCRIPTION)).to_have_text(
            MANAGE_DESCRIPTION
        )
        # …and the correction touched only what it was asked to: the contact
        # details the first two steps of the wizard re-render (but never send)
        # are still the ones the guardian was registered with.
        expect(guardians.detail_value(MANAGE_DETAIL_PHONE)).to_have_text(phone)
        expect(guardians.detail_value(MANAGE_DETAIL_ADDRESS)).to_have_text(
            person.address
        )

        # Finally, straight off the record the backend stores — the screen renders
        # from the same GET, so this is what proves the PUT landed rather than the
        # profile having been repainted from local state.
        _manage_expect_stored(
            api,
            ctx,
            guardian_id,
            occupation=MANAGE_NEW_OCCUPATION,
            employer_name=MANAGE_EMPLOYER,
            work_address=MANAGE_WORK_ADDRESS,
            relationship_type=MANAGE_NEW_RELATIONSHIP,
            additional_remarks=MANAGE_DESCRIPTION,
            email=person.email,
            first_name=first_name,
            other_names=last_name,
            primary_phone=phone,
        )


def _manage_expect_stored(
    api: BackendAPI,
    ctx: SchoolContext,
    guardian_id: int,
    *,
    occupation: str,
    employer_name: str,
    work_address: str,
    relationship_type: str,
    additional_remarks: str,
    email: str,
    first_name: str,
    other_names: str,
    primary_phone: str,
) -> None:
    """Assert GET /guardian/{id} holds exactly what the profile screen showed."""
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    res = api.get(f"/guardian/{guardian_id}", token=token)
    assert res.status_code == 200, (
        f"GET /guardian/{guardian_id} answered {res.status_code} for the "
        f"SchoolAdmin of {ctx.school_name!r}, whose pack licenses "
        f"{GUARDIANS_MODULE!r} — the record the profile screen renders from is "
        f"unreadable. Body: {res.text[:300]}"
    )
    body = res.json()
    user = body.get("user") or {}
    stored = {
        "occupation": body.get("occupation"),
        "employer_name": body.get("employer_name"),
        "work_address": body.get("work_address"),
        "relationship_type": body.get("relationship_type"),
        "additional_remarks": body.get("additional_remarks"),
        "user.email": user.get("email"),
        "user.first_name": user.get("first_name"),
        "user.other_names": user.get("other_names"),
        "user.primary_phone": user.get("primary_phone"),
    }
    expected = {
        "occupation": occupation,
        "employer_name": employer_name,
        "work_address": work_address,
        "relationship_type": relationship_type,
        "additional_remarks": additional_remarks,
        "user.email": email,
        "user.first_name": first_name,
        "user.other_names": other_names,
        "user.primary_phone": primary_phone,
    }
    assert stored == expected, (
        f"guardian {guardian_id} is stored as {stored}, not {expected}. The edit "
        f"wizard's PUT /guardian/{{id}} sends occupation, additional_remarks, "
        f"relationship_type, work_address, employer_name and a user block of "
        f"first_name/other_names/profile_pic/religion; a field missing here is one "
        f"the screen displayed but the backend never took."
    )


def _manage_letters(value: str) -> str:
    """Name-ish inputs silently drop anything outside /^[A-Za-z\\s]*$/."""
    return re.sub(r"[^A-Za-z\s]", "", value).strip()


def _manage_digits(value: str) -> str:
    """The phone inputs strip non-digits and cap at 10 characters."""
    return re.sub(r"\D", "", value)[:10]
