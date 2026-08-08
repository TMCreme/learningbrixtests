"""Academics → Lessons page object (/module/lessons).

The module is three routes, not one screen:

* ``/module/lessons`` — the register: a filter bar, a client-side text search and
  a table with one row per lesson plan, each carrying a "…" menu.
* ``/module/lessons/add`` — the create form.
* ``/module/lessons/edit/{id}`` — the same form, pre-filled, plus a Status select
  that the create form deliberately omits (``LessonForm.tsx``: "new lessons
  always start planned").

Selector families on these routes
    The register's filter bar and the whole of ``LessonForm`` are **Radix**
    (``@/components/ui/select``), so their dropdowns expose ``role=option`` and
    ``BasePage.select_option_by_label`` works — the fields are laid out as
    ``<div><Label>…</Label><Select/></div>`` and the ``<Label>`` carries no
    ``for``, which is exactly what that helper anchors on.

    The two pickers are **antd** (``DatePicker`` / ``TimePicker``). The date one
    goes through ``BasePage.commit_date`` — this form is a bare ``<form
    onSubmit=…>`` whose submit handler *is* the create, so a stray Enter would
    post a half-filled plan. The time one has no calendar cell to click, so it is
    committed with the panel's own "OK" button for the same reason.

Cascading selects
    Class → Subject → Syllabus → Topic, each disabled until the one before it is
    set and each filled by a fetch that fires on that change
    (``GetClassSubjects``, ``getSyllabusTopic``, and a client-side filter of
    ``GetSyllabus()`` on both class *and* subject). ``fill_form`` therefore always
    sets them in that order; Playwright's own wait for an enabled trigger and a
    present option is what absorbs the fetches.

Who may write here
    ``("manage", "lessons")`` — which the seeded Teacher role holds — plus, for a
    teacher, being the **subject teacher** of the plan's (subject, class) pair
    (``LessonService.create_lesson`` → ``assert_subject_teacher``). A teacher who
    is not gets a 403 that surfaces as an error toast, not as a missing control,
    so tests seed that assignment first (``tests/flows/academics_seed.py``).

    A teacher's plans are also created **pending** approval, not approved — only
    an admin's are auto-approved — so "pending" in the Approval column is the
    expected outcome of a successful create, not a failure.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── headings, one per route ──────────────────────────────────────────────────
PAGE_HEADING = re.compile(r"^\s*Manage Lessons\s*$", re.I)
ADD_HEADING = re.compile(r"^\s*Add New Lesson\s*$", re.I)
EDIT_HEADING = re.compile(r"^\s*Edit Lesson\s*$", re.I)

# The register's own URL — anchored so it cannot also match /add or /edit/{id}.
LIST_URL = re.compile(r"/module/lessons(?:$|[?#])")
ADD_URL = re.compile(r"/module/lessons/add")
EDIT_URL = re.compile(r"/module/lessons/edit/\d+")
# The read-only detail route. ``\d+`` is what separates it from /add, /edit/{id},
# /weekly-plan and the attendance sub-routes, none of which end in an id.
DETAIL_URL = re.compile(r"/module/lessons/\d+(?:$|[?#])")

# ── the register (page.tsx) ──────────────────────────────────────────────────
SEARCH_PLACEHOLDER = re.compile(r"Search lessons", re.I)
EMPTY_TABLE = re.compile(r"No lessons found matching your criteria", re.I)
ADD_BUTTON = re.compile(r"^\s*Add Lesson\s*$", re.I)
# The other write affordance on the register's header bar; like "Add Lesson" it
# only renders for ``usePermission("lessons", "manage")``.
BULK_CREATE_BUTTON = re.compile(r"Bulk Create from Syllabus", re.I)
# Always offered, to every role that can reach the register at all.
WEEKLY_PLAN_BUTTON = re.compile(r"^\s*Weekly Plan\s*$", re.I)
# src/components/common/PageError.tsx, mounted with this exact title when the
# list fetch is refused — it replaces the entire register.
LOAD_FAILURE_TITLE = re.compile(r"Failed to load lessons", re.I)

# Row "…" menu items. "Edit lesson" and "Delete lesson" only render for a role
# holding ("manage", "lessons").
VIEW_ITEM = re.compile(r"^\s*View details\s*$", re.I)
EDIT_ITEM = re.compile(r"^\s*Edit lesson\s*$", re.I)
DELETE_ITEM = re.compile(r"^\s*Delete lesson\s*$", re.I)

# ── the read-only detail route (lessons/[id]/page.tsx) ───────────────────────
# Its header is the lesson's own title, so there is no fixed heading to match.
# The section cards below always render — an unfilled one shows "No … provided."
DETAIL_SECTION = {
    "objectives": re.compile(r"^\s*Learning Objectives\s*$", re.I),
    # "Overview & Description" — an ampersand, not a slash, so no as_pattern
    # escaping is needed here (trap 4 is about "/").
    "description": re.compile(r"^\s*Overview & Description\s*$", re.I),
    "structure": re.compile(r"^\s*Lesson Structure\s*$", re.I),
    "homework": re.compile(r"^\s*Homework\s*$", re.I),
}
# The detail page's own write affordance, gated on ("manage", "lessons") exactly
# as the register's row menu is.
DETAIL_EDIT_BUTTON = re.compile(r"^\s*Edit Lesson\s*$", re.I)

# Column order of the register's table, for LessonsPage.cell().
COLUMN = {
    "title": 0,
    "subject": 1,
    "class": 2,
    "teacher": 3,
    "schedule": 4,
    "type": 5,
    "status": 6,
    "approval": 7,
    "assessment": 8,
}

# ── the form (LessonForm.tsx) ────────────────────────────────────────────────
# Labels first, placeholder second: these are Radix <Label>s with no `for`, so
# `BasePage.fill_labeled` falls through to the placeholder (trap 5).
TITLE_FIELD = re.compile(r"Lesson Title|Enter lesson title", re.I)
OBJECTIVES_FIELD = re.compile(r"Learning Objectives|What will the students learn", re.I)
# "Overview / Description" carries a slash, so the placeholder is the safer
# branch to lead with; `fill_labeled` runs the whole pattern through
# `as_pattern` regardless (trap 4).
DESCRIPTION_FIELD = re.compile(r"Brief overview of the lesson|Overview . Description", re.I)
STRUCTURE_FIELD = re.compile(r"Lesson Structure|1\. Starter", re.I)
HOMEWORK_FIELD = re.compile(r"^\s*Homework\s*$|Homework assigned for this lesson", re.I)
DURATION_FIELD = re.compile(r"Duration \(minutes\)", re.I)

CLASS_LABEL = re.compile(r"^\s*Class\s*$", re.I)
SUBJECT_LABEL = re.compile(r"^\s*Subject\s*$", re.I)
SYLLABUS_LABEL = re.compile(r"^\s*Syllabus\s*$", re.I)
TOPIC_LABEL = re.compile(r"^\s*Topic\s*$", re.I)
STATUS_LABEL = re.compile(r"^\s*Status\s*$", re.I)

CREATE_SUBMIT = re.compile(r"^\s*Create Lesson\s*$", re.I)
UPDATE_SUBMIT = re.compile(r"^\s*Update Lesson\s*$", re.I)
CREATE_TOAST = re.compile(r"Lesson created successfully", re.I)
UPDATE_TOAST = re.compile(r"Lesson updated successfully", re.I)

# antd picker ids (the <Label htmlFor> on each names the same id).
DATE_INPUT = "input#scheduled_date"
TIME_INPUT = "input#scheduled_time"
OK_BUTTON = re.compile(r"^\s*OK\s*$", re.I)

# What the Status cell renders per stored status (STATUS_LABELS in page.tsx).
STATUS_LABELS = {
    "planned": "Planned",
    "in_progress": "In Progress",
    "completed": "Completed",
    "canceled": "Canceled",
}


class LessonsPage(BasePage):
    URL = "/module/lessons"

    # ────────────────────────── the register ───────────────────────

    def open(self) -> "LessonsPage":
        super().open()
        return self.expect_loaded()

    def expect_loaded(self) -> "LessonsPage":
        """Assert the register is through its guards — however it was reached.

        ``useModuleGuard``/``usePermissionGuard`` render ``null`` rather than an
        error, and a refused fetch swaps the whole page for ``PageError``, so the
        heading being present is what says "this user got the register".
        """
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
            timeout=25_000
        )
        return self

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(LOAD_FAILURE_TITLE)).to_have_count(0)

    def wait_for_rows(self, timeout_ms: int = 30_000) -> None:
        """Block until the table has settled on rows or on its empty state.

        The header renders immediately and the body swaps a "Loading lessons…"
        row for one of the two, so asserting on the header alone would pass
        mid-flight. Every data row leads with a ``font-medium`` title div.
        """
        body = self.page.locator("table tbody")
        settled = body.get_by_text(EMPTY_TABLE).first.or_(
            body.locator("div.font-medium").first
        )
        expect(settled.first).to_be_visible(timeout=timeout_ms)

    def search(self, query: str) -> None:
        """Narrow the register with its client-side text search.

        Deliberately used in preference to the Class/Subject filters for a
        teacher: those are filled by ``loadFilters``, whose ``Promise.all``
        includes ``fetchTeachingStaff`` — a call the Teacher role has no
        permission for — so the rejection leaves every filter dropdown empty
        while the table itself loads perfectly well.
        """
        self.page.get_by_placeholder(SEARCH_PLACEHOLDER).first.fill(query)

    def expect_empty(self, timeout_ms: int = 20_000) -> None:
        """Assert the table settled on its "nothing matched" state."""
        expect(
            self.page.locator("table tbody").get_by_text(EMPTY_TABLE)
        ).to_be_visible(timeout=timeout_ms)

    def find_row(self, title: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has=self.page.get_by_text(_exact(title))
        ).first

    def cell(self, title: str, column: int) -> Locator:
        """One cell of ``title``'s row, by column index (see ``COLUMN``)."""
        return self.find_row(title).get_by_role("cell").nth(column)

    def expect_row(self, title: str, timeout_ms: int = 30_000) -> None:
        expect(self.find_row(title)).to_be_visible(timeout=timeout_ms)

    def expect_status(self, title: str, status_label: str,
                      timeout_ms: int = 25_000) -> None:
        expect(self.cell(title, COLUMN["status"])).to_have_text(
            _exact(status_label), timeout=timeout_ms
        )

    def expect_approval(self, title: str, approval: str,
                        timeout_ms: int = 25_000) -> None:
        expect(self.cell(title, COLUMN["approval"])).to_have_text(
            _exact(approval), timeout=timeout_ms
        )

    def open_row_menu(self, title: str) -> None:
        """Open a row's "…" menu (View details / Edit / Delete / attendance)."""
        row = self.find_row(title)
        expect(row).to_be_visible(timeout=30_000)
        # The Actions cell holds the only <button> in the row.
        row.get_by_role("button").last.click()
        expect(self.page.get_by_role("menuitem", name=VIEW_ITEM)).to_be_visible(
            timeout=15_000
        )

    def close_row_menu(self) -> None:
        """Dismiss an open Radix dropdown.

        It renders in a portal with a modal overlay, so leaving it open makes the
        very next click on the page land on the overlay instead of its target.
        """
        self.page.keyboard.press("Escape")
        expect(self.page.get_by_role("menuitem", name=VIEW_ITEM)).to_have_count(0)

    def expect_row_is_read_only(self, title: str) -> None:
        """Assert ``title``'s row menu offers reading and nothing else.

        Both write items are gated on ``usePermission("lessons", "manage")``;
        "View details" is asserted present in the same breath so that "no Edit
        lesson" cannot pass on a menu that simply never opened.
        """
        self.open_row_menu(title)
        expect(self.page.get_by_role("menuitem", name=VIEW_ITEM)).to_be_visible()
        expect(self.page.get_by_role("menuitem", name=EDIT_ITEM)).to_have_count(0)
        expect(self.page.get_by_role("menuitem", name=DELETE_ITEM)).to_have_count(0)
        self.close_row_menu()

    def open_details(self, title: str) -> None:
        """Follow a row's "View details" through to /module/lessons/{id}.

        The detail page's header *is* the lesson title, so that heading being on
        screen is what says the fetch resolved rather than that the route merely
        changed.
        """
        self.open_row_menu(title)
        self.page.get_by_role("menuitem", name=VIEW_ITEM).first.click()
        self.page.wait_for_url(DETAIL_URL, timeout=25_000)
        expect(
            self.page.get_by_role("heading", name=_exact(title))
        ).to_be_visible(timeout=25_000)

    def expect_detail_section(self, section: str, content: str | re.Pattern) -> None:
        """Assert a detail card is on screen carrying ``content``.

        Every card renders whether or not its field was filled (an empty one
        shows "No … provided."), so the heading alone proves nothing — the text
        under it is the assertion.
        """
        heading = self.page.get_by_role("heading", name=DETAIL_SECTION[section])
        expect(heading).to_be_visible(timeout=20_000)
        card = self.page.locator("div.rounded-xl").filter(has=heading).last
        expect(card).to_contain_text(content, timeout=20_000)

    # ─────────────────────────── the forms ─────────────────────────

    def open_create_form(self) -> None:
        """Follow "Add Lesson" through to /module/lessons/add.

        The trigger only renders for ``usePermission("lessons", "manage")``, so a
        read-only role fails here as a missing control rather than as a rejected
        POST.
        """
        self.page.get_by_role("button", name=ADD_BUTTON).first.click()
        self.page.wait_for_url(ADD_URL, timeout=25_000)
        expect(self.page.get_by_role("heading", name=ADD_HEADING)).to_be_visible(
            timeout=25_000
        )

    def open_edit_form(self, title: str) -> None:
        """Open ``title``'s row menu and follow "Edit lesson"."""
        self.open_row_menu(title)
        self.page.get_by_role("menuitem", name=EDIT_ITEM).first.click()
        self.page.wait_for_url(EDIT_URL, timeout=25_000)
        expect(self.page.get_by_role("heading", name=EDIT_HEADING)).to_be_visible(
            timeout=25_000
        )
        # The form only mounts once GetLessonByID has answered; the title input
        # carrying the stored value is the proof that it did.
        expect(self.page.get_by_role("textbox").first).to_have_value(
            re.compile(r".+"), timeout=25_000
        )

    def fill_form(
        self,
        *,
        title: str | None = None,
        class_name: str | None = None,
        subject_name: str | None = None,
        syllabus_name: str | re.Pattern | None = None,
        topic_name: str | re.Pattern | None = None,
        scheduled_date: str | None = None,
        scheduled_time: str | None = None,
        duration_minutes: int | None = None,
        objectives: str | None = None,
        description: str | None = None,
        lesson_structure: str | None = None,
        homework: str | None = None,
        status: str | None = None,
    ) -> None:
        """Fill any subset of the lesson form; unnamed fields are left alone.

        The cascade is set in dependency order because each select is disabled
        until its parent has a value and is repopulated by the fetch that change
        fires. ``status`` only exists on the edit route — ``LessonForm`` hides it
        while creating, since a new plan always starts "planned" server-side.
        """
        if title is not None:
            self.fill_labeled(TITLE_FIELD, title)
        if class_name is not None:
            self.select_option_by_label(CLASS_LABEL, _exact(class_name))
        if subject_name is not None:
            self.select_option_by_label(SUBJECT_LABEL, _exact(subject_name))
        if syllabus_name is not None:
            # SYLLABUS_LABEL resolves to the <label>, not to the Lesson Type
            # trigger that also reads "Syllabus": the Syllabus field is earlier in
            # the DOM and `select_option_by_label` takes the first match.
            self.select_option_by_label(SYLLABUS_LABEL, syllabus_name)
        if topic_name is not None:
            self.select_option_by_label(TOPIC_LABEL, topic_name)
        if scheduled_date is not None:
            self.set_scheduled_date(scheduled_date)
        if scheduled_time is not None:
            self.set_scheduled_time(scheduled_time)
        if duration_minutes is not None:
            self.fill_labeled(DURATION_FIELD, str(duration_minutes))
        if objectives is not None:
            self.fill_labeled(OBJECTIVES_FIELD, objectives)
        if description is not None:
            self.fill_labeled(DESCRIPTION_FIELD, description)
        if lesson_structure is not None:
            self.fill_labeled(STRUCTURE_FIELD, lesson_structure)
        if homework is not None:
            self.fill_labeled(HOMEWORK_FIELD, homework)
        if status is not None:
            self.select_option_by_label(STATUS_LABEL, _exact(status))

    def set_scheduled_date(self, value: str) -> None:
        """Set the antd DatePicker without ever pressing Enter (trap 1).

        The picker sits inside the form whose ``onSubmit`` *is* the create, so a
        keyboard commit would post the plan half-filled. ``commit_date`` clicks
        the highlighted panel cell instead. The picker declares no ``format``, so
        antd's default ``YYYY-MM-DD`` is what gets typed.
        """
        self.commit_date(self._picker(DATE_INPUT, 0), value, display_format="%Y-%m-%d")

    def set_scheduled_time(self, value: str) -> None:
        """Set the antd TimePicker, committing with the panel's own "OK".

        ``commit_date`` cannot serve here: a time panel has no
        ``.ant-picker-cell`` to click, and it would fall back to blurring — which
        antd may or may not treat as a commit depending on ``changeOnBlur``. The
        OK button is the picker's documented, version-stable commit gesture, and
        (unlike Enter) it is a ``type="button"``, so it never reaches the form.
        """
        picker = self._picker(TIME_INPUT, 1)
        picker.click()
        picker.fill(value)
        panel = self.page.locator(".ant-picker-dropdown:visible").last
        ok = panel.get_by_role("button", name=OK_BUTTON).first
        if ok.count():
            ok.click()
        else:
            picker.blur()
        expect(picker).to_have_value(re.compile(rf"^\s*{re.escape(value)}"), timeout=10_000)

    def submit_create(self) -> None:
        self._submit(CREATE_SUBMIT, CREATE_TOAST)

    def submit_update(self) -> None:
        self._submit(UPDATE_SUBMIT, UPDATE_TOAST)

    # ───────────────────────── internals ───────────────────────────

    def _submit(self, button: re.Pattern, toast: re.Pattern) -> None:
        """Submit the form and follow the redirect back to the register.

        Both pages ``router.push("/module/lessons")`` on success, so waiting for
        the toast *and* the route is what separates "the POST was accepted" from
        "an error toast rendered and the form stayed put".
        """
        self.page.get_by_role("button", name=as_pattern(button)).first.click()
        self.expect_toast(toast, timeout_ms=25_000)
        self.page.wait_for_url(LIST_URL, timeout=25_000)
        self.expect_loaded()
        self.expect_no_load_failure()
        self.wait_for_rows()

    def _picker(self, selector: str, index: int) -> Locator:
        """The antd picker's input, by id where the id survived to the DOM.

        rc-picker forwards ``id`` to its ``<input>``, but that is an internal
        detail of the version in use — the positional fallback (date first, time
        second, in render order) keeps this working if it ever stops.
        """
        by_id = self.page.locator(selector)
        if by_id.count():
            return by_id.first
        return self.page.locator(".ant-picker input").nth(index)


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
