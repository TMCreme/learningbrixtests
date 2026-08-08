"""Go/no-go check on the provisioning playbook (docs/plan.md §7).

One test, one scenario. If this fails, no module test is worth reading — the
schools they run against were never built. The ``provisioning_smoke_only``
marker collapses the parametrised ``provisioned_school`` fixture down to the
``full_access`` scenario (see ``tests/conftest.py``); proving the playbook runs
does not need one full UI walkthrough per feature pack.

The assertions are the four phases in order: the school (A), its branch (B),
its users (C), its academic structure (D).
"""
from __future__ import annotations

import pytest

from tests.flows.school_provisioning import (
    BRANCH_NAME,
    CLASS_NAME,
    SUBJECT_NAME,
    SchoolContext,
)


@pytest.mark.provisioning
@pytest.mark.smoke
@pytest.mark.provisioning_smoke_only
def test_provision_full_access_scenario(provisioned_school: SchoolContext) -> None:
    ctx = provisioned_school

    assert ctx.school_id > 0, (
        f"Phase A never captured a school id for {ctx.school_name!r} "
        f"(teardown cannot run without it)."
    )
    assert ctx.school_admin.email, "Phase A captured no SchoolAdmin credentials."

    assert ctx.teacher is not None and ctx.teacher.email, (
        "Phase C created no teacher — the class teacher picker in phase D "
        "depends on one."
    )
    assert ctx.student is not None and ctx.student.email, (
        "Phase C admitted no student."
    )

    assert BRANCH_NAME in [b["name"] for b in ctx.branches], (
        f"Phase B created no {BRANCH_NAME!r} branch; got {ctx.branches!r}."
    )
    assert any(c["name"] == CLASS_NAME for c in ctx.classes), (
        f"Phase D created no {CLASS_NAME!r} class; got {ctx.classes!r}."
    )
    assert any(s["name"] == SUBJECT_NAME for s in ctx.subjects), (
        f"Phase D created no {SUBJECT_NAME!r} subject; got {ctx.subjects!r}."
    )
