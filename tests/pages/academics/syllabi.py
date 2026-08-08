"""Academics → Syllabus page object (``/module/syllabus``).

The ledger calls this module ``syllabi`` (that is the permission/feature-pack
key, and the backend prefix is ``/syllabi``), but the *route* is singular:
``/module/syllabus``, ``/module/syllabus/add``, ``/module/syllabus/edit/{id}``.
The sidebar entry reads "Syllabus".

Three routes, one feature
    * ``/module/syllabus`` — the register: a filter bar, a search box and a table
      of one row per syllabus, each carrying a "…" menu (View details / Download
      PDF / Edit / Publish / Archive / Delete).
    * ``/module/syllabus/add`` — the create form. Class, Subject, Academic Year
      and Academic Term are chosen here and **nowhere else**: the edit route
      renders them as read-only "Fixed Context".
    * ``/module/syllabus/edit/{id}`` — name, status, description and topic
      coverage only.

Selector families
    Every dropdown on these routes is **Radix** (``@/components/ui/select``), so
    ``BasePage.select_option_by_label`` works: each field is laid out as
    ``<div><label>…</label><Select/></div>`` and the ``<label>`` carries no
    ``for`` (trap 5). There is no date picker anywhere in this module, so trap 1
    never arises.

    The academic-year options read "2026/2027 (Active)" — a slash, so every
    option pattern is built with :func:`tests.pages.base.as_pattern` (trap 4).
    ``select_option_by_label`` does *not* normalise the option pattern for the
    caller, only the label, so that has to happen here.

    The topic list is a stack of antd ``Checkbox``es with no accessible name of
    their own: the topic's title sits in a sibling ``<p>``. Each is therefore
    reached through the card that holds both.

Two register details the assertions here are built on
    * **The status badge is capitalised in CSS, not in the DOM.**
      ``class="capitalize"`` renders "Draft" while ``textContent`` is still
      ``draft``, so every status assertion here is spelled in lower case.
    * **Search is server-side and paginated at 10 rows.** ``search`` narrows the
      fetch itself, so ``find_row`` is only reliable on a register that has been
      searched (or filtered) down — exactly as on ``/module/lessons``.

      This is also a backend defect this unit uncovered and fixed in place: the
      box had always sent ``search=…`` but ``GET /syllabi/`` declared no such
      parameter, so FastAPI dropped it and typing did nothing. See
      ``state/backend_patches.md``.

Who may write here
    ``("manage", "syllabi")`` — which the seeded Teacher role holds — plus, for a
    teacher, being the **subject teacher** of the syllabus's (subject, class)
    pair (``SyllabusService._assert_can_manage``, applied on create, update,
    delete and publish alike). Class-teacher-only visibility grants reads and no
    writes, so a test drives that assignment in first.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── the three routes ─────────────────────────────────────────────────────────
# Anchored so the register's own URL cannot also match /add or /edit/{id}.
LIST_URL = re.compile(r"/module/syllabus(?:$|[?#])")
ADD_URL = re.compile(r"/module/syllabus/add")
EDIT_URL = re.compile(r"/module/syllabus/edit/\d+")

PAGE_HEADING = re.compile(r"^\s*Syllabus Management\s*$", re.I)
ADD_HEADING = re.compile(r"^\s*Create New Syllabus\s*$", re.I)
EDIT_HEADING = re.compile(r"^\s*Edit Syllabus\s*$", re.I)

# ── the register (page.tsx) ──────────────────────────────────────────────────
CREATE_BUTTON = re.compile(r"^\s*Create Syllabus\s*$", re.I)
SEARCH_PLACEHOLDER = re.compile(r"Search syllabus", re.I)
EMPTY_TABLE = re.compile(r"^\s*No syllabi found\s*$", re.I)
# src/components/common/PageError.tsx, mounted with this exact title when the
# list fetch is refused — it replaces the entire register.
LOAD_FAILURE_TITLE = re.compile(r"Failed to load syllabus data", re.I)

# Row "…" menu items. Everything but the first two is gated on
# ``usePermission("syllabi", "manage")``; "Publish" additionally only renders
# while the syllabus is not already published.
VIEW_ITEM = re.compile(r"^\s*View details\s*$", re.I)
DOWNLOAD_ITEM = re.compile(r"^\s*Download PDF\s*$", re.I)
EDIT_ITEM = re.compile(r"^\s*Edit syllabus\s*$", re.I)
PUBLISH_ITEM = re.compile(r"^\s*Publish\s*$", re.I)
ARCHIVE_ITEM = re.compile(r"^\s*Archive\s*$", re.I)
DELETE_ITEM = re.compile(r"^\s*Delete\s*$", re.I)

# Column order of the register's table, for SyllabiPage.cell().
COLUMN = {
    "name": 0,      # name + description
    "context": 1,   # class + subject
    "period": 2,    # academic year + term
    "status": 3,
    "actions": 4,
}

# What the Status cell actually holds. The badge is capitalised by CSS only.
STATUS = {"draft": "draft", "published": "published", "archived": "archived"}

# ── the create form (add/page.tsx) ───────────────────────────────────────────
# Labels first, placeholder second: these are bare <label>s with no `for`, so
# `BasePage.fill_labeled` falls through to the placeholder (trap 5).
# The create and edit routes give the name input different placeholders, so both
# are alternation branches — `fill_labeled` only ever reaches one of them.
NAME_FIELD = re.compile(
    r"Syllabus Name|E\.g\. Mathematics 1st Term Syllabus|Enter syllabus name", re.I
)
DESCRIPTION_FIELD = re.compile(
    r"^\s*Description\s*$|Briefly describe the syllabus purpose", re.I
)

CLASS_LABEL = re.compile(r"^\s*Class\s*\*?\s*$", re.I)
SUBJECT_LABEL = re.compile(r"^\s*Subject\s*\*?\s*$", re.I)
YEAR_LABEL = re.compile(r"^\s*Academic Year\s*\*?\s*$", re.I)
TERM_LABEL = re.compile(r"^\s*Academic Term\s*\*?\s*$", re.I)

# antd renders each topic toggle as <label class="ant-checkbox-wrapper">, whose
# own text is empty — the topic's name lives in a sibling <p>.
TOPIC_CARD = "div.rounded-xl"
TOPIC_CHECKBOX = "label.ant-checkbox-wrapper"

# Both action bars render the same labels (a desktop one in the header and a
# `sm:hidden` sticky bar); at the demo viewport only the desktop one is visible,
# and it is first in the DOM. "Saving …" is the in-flight caption.
CREATE_SUBMIT = re.compile(r"^\s*Sav(e|ing) Syllabus\s*$", re.I)
UPDATE_SUBMIT = re.compile(r"^\s*Sav(e|ing) Changes\s*$", re.I)

CREATE_TOAST = re.compile(r"Syllabus created successfully", re.I)
UPDATE_TOAST = re.compile(r"Syllabus updated successfully", re.I)
PUBLISH_TOAST = re.compile(r"Syllabus published", re.I)

# ── the edit form (edit/[id]/page.tsx) ───────────────────────────────────────
# Status is a row of three plain <button>s, not a select.
STATUS_BUTTON = {
    "draft": re.compile(r"^\s*draft\s*$", re.I),
    "published": re.compile(r"^\s*published\s*$", re.I),
    "archived": re.compile(r"^\s*archived\s*$", re.I),
}
FIXED_CONTEXT = re.compile(r"^\s*Fixed Context\s*$", re.I)

# ── the View details dialog ──────────────────────────────────────────────────
DETAILS_TITLE = re.compile(r"^\s*Syllabus Details\s*$", re.I)
# Unanchored: used to pick the dialog out by its *whole* text, not by a heading.
DETAILS_DIALOG = re.compile(r"Syllabus Details", re.I)
DETAILS_CLOSE = re.compile(r"^\s*Close\s*$", re.I)


class SyllabiPage(BasePage):
    URL = "/module/syllabus"

    # ────────────────────────── the register ───────────────────────

    def open(self) -> "SyllabiPage":
        super().open()
        return self.expect_loaded()

    def expect_loaded(self) -> "SyllabiPage":
        """Assert the register is through its guards — however it was reached.

        ``useModuleGuard``/``usePermissionGuard`` render ``null`` rather than an
        error and a refused fetch swaps the whole page for ``PageError``, so the
        heading being on screen is what says "this user got the register".
        """
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
            timeout=25_000
        )
        return self

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(LOAD_FAILURE_TITLE)).to_have_count(0)

    def wait_for_rows(self, timeout_ms: int = 30_000) -> None:
        """Block until the table has settled on rows or on its empty state.

        The header renders immediately and the body swaps a "Loading syllabi…"
        row for one of the two, so asserting on the heading alone would pass
        mid-flight. Only data rows carry a ``font-medium`` first cell.
        """
        body = self.page.locator("table tbody")
        settled = body.get_by_text(EMPTY_TABLE).first.or_(
            body.locator("td.font-medium").first
        )
        expect(settled.first).to_be_visible(timeout=timeout_ms)

    def find_row(self, name: str) -> Locator:
        """The register row for ``name``.

        Matched on the row's whole text rather than on an exact cell: the name
        shares its cell with the description, so no element's text *is* the name.
        Every syllabus these tests create carries the run tag, so a substring
        match is unambiguous.
        """
        return self.page.get_by_role("row").filter(
            has_text=as_pattern(re.escape(name))
        ).first

    def cell(self, name: str, column: int) -> Locator:
        """One cell of ``name``'s row, by column index (see ``COLUMN``)."""
        return self.find_row(name).get_by_role("cell").nth(column)

    def expect_row(self, name: str, timeout_ms: int = 30_000) -> None:
        expect(self.find_row(name)).to_be_visible(timeout=timeout_ms)

    def expect_status(self, name: str, status: str, timeout_ms: int = 25_000) -> None:
        """Assert the Status badge. ``status`` is the stored, lower-case value —
        the badge only *looks* capitalised (``class="capitalize"``)."""
        expect(self.cell(name, COLUMN["status"])).to_have_text(
            _exact(STATUS[status]), timeout=timeout_ms
        )

    def expect_context(self, name: str, *, class_name: str, subject_name: str) -> None:
        """Assert the Class & Subject cell, which is the pairing the whole
        module is keyed on and the one thing the edit route cannot change."""
        context = self.cell(name, COLUMN["context"])
        expect(context).to_contain_text(class_name, timeout=25_000)
        expect(context).to_contain_text(subject_name)

    def expect_period(self, name: str, *, year: str, term: str) -> None:
        period = self.cell(name, COLUMN["period"])
        expect(period).to_contain_text(year, timeout=25_000)
        expect(period).to_contain_text(term)

    def expect_description(self, name: str, description: str) -> None:
        """The description renders under the name, in the same cell."""
        expect(self.cell(name, COLUMN["name"])).to_contain_text(
            description, timeout=25_000
        )

    def search(self, query: str) -> None:
        """Narrow the register with its search box.

        Debounced 500ms, then refetched server-side against name and
        description. Preferred over the Class/Subject filter dropdowns, which
        re-fetch on every change and would need the option to have loaded first.
        """
        self.page.get_by_placeholder(SEARCH_PLACEHOLDER).first.fill(query)
        self.wait_for_rows()

    def expect_empty(self, timeout_ms: int = 20_000) -> None:
        """Assert the table settled on its "nothing matched" state."""
        expect(
            self.page.locator("table tbody").get_by_text(EMPTY_TABLE)
        ).to_be_visible(timeout=timeout_ms)

    # ──────────────────────────── row menu ─────────────────────────

    def open_row_menu(self, name: str) -> None:
        row = self.find_row(name)
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

    def publish(self, name: str) -> None:
        """Publish from the row menu.

        ``SyllabusService.publish_syllabus`` refuses a syllabus with no topics
        ("Cannot publish syllabus without topics"), so this is only ever called
        on one that carries some.
        """
        self.open_row_menu(name)
        self.page.get_by_role("menuitem", name=PUBLISH_ITEM).first.click()
        self.expect_toast(PUBLISH_TOAST, timeout_ms=25_000)
        self.wait_for_rows()

    def open_details(self, name: str) -> None:
        """Open the read-only "Syllabus Details" dialog from the row menu."""
        self.open_row_menu(name)
        self.page.get_by_role("menuitem", name=VIEW_ITEM).first.click()
        expect(self.page.get_by_role("heading", name=DETAILS_TITLE)).to_be_visible(
            timeout=20_000
        )

    def close_details(self) -> None:
        self.page.get_by_role("button", name=DETAILS_CLOSE).first.click()
        expect(self.page.get_by_role("heading", name=DETAILS_TITLE)).to_have_count(0)

    def expect_details_topic(self, topic_name: str) -> None:
        """Assert a topic is listed under "Teaching Sequence" in the dialog.

        The dialog fetches ``/syllabi/{id}/topics`` on open, so this doubles as
        the assertion that the ordering really was persisted rather than merely
        posted.
        """
        dialog = self.page.get_by_role("dialog").filter(has_text=DETAILS_DIALOG).first
        expect(dialog.get_by_text(_exact(topic_name)).first).to_be_visible(
            timeout=20_000
        )

    # ─────────────────────────── the forms ─────────────────────────

    def open_create_form(self) -> None:
        """Follow "Create Syllabus" through to /module/syllabus/add.

        The trigger only renders for ``usePermission("syllabi", "manage")``, so a
        read-only role fails here as a missing control rather than as a refused
        POST.
        """
        self.page.get_by_role("button", name=CREATE_BUTTON).first.click()
        self.page.wait_for_url(ADD_URL, timeout=25_000)
        expect(self.page.get_by_role("heading", name=ADD_HEADING)).to_be_visible(
            timeout=25_000
        )
        # The form is behind a skeleton until fetchClasses/fetchSubjects/
        # fetchAcademicYears/GetTopics have all answered; the name input is the
        # first thing the real form renders.
        expect(self.page.get_by_placeholder(NAME_FIELD).first).to_be_visible(
            timeout=25_000
        )

    def open_edit_form(self, name: str) -> None:
        """Open ``name``'s row menu and follow "Edit syllabus"."""
        self.open_row_menu(name)
        self.page.get_by_role("menuitem", name=EDIT_ITEM).first.click()
        self.page.wait_for_url(EDIT_URL, timeout=25_000)
        expect(self.page.get_by_role("heading", name=EDIT_HEADING)).to_be_visible(
            timeout=25_000
        )
        # The whole route renders a spinner until GetSyllabusById has answered;
        # "Fixed Context" only exists on the loaded form.
        expect(self.page.get_by_text(FIXED_CONTEXT)).to_be_visible(timeout=25_000)

    def fill_create_form(
        self,
        *,
        name: str | None = None,
        class_name: str | None = None,
        subject_name: str | None = None,
        academic_year: str | None = None,
        academic_term: str | None = None,
        description: str | None = None,
    ) -> None:
        """Fill any subset of the create form; unnamed fields are left alone.

        Order matters twice over. Academic Term's trigger is ``disabled`` until a
        year is chosen and its options are fetched by that change, and the whole
        Topics panel stays behind a "No Subject Selected" placeholder until a
        subject is chosen — so year precedes term, and subject precedes any call
        to :meth:`select_topic`.

        Year and term options are matched on their leading name only: the app
        appends " (Active)" to whichever is current, and the year's own name
        ("2026/2027") carries a slash that has to survive selector serialisation
        (trap 4).
        """
        if name is not None:
            self.fill_labeled(NAME_FIELD, name)
        if class_name is not None:
            self.select_option_by_label(CLASS_LABEL, _exact(class_name))
        if subject_name is not None:
            self.select_option_by_label(SUBJECT_LABEL, _exact(subject_name))
        if academic_year is not None:
            self.select_option_by_label(YEAR_LABEL, _starts_with(academic_year))
        if academic_term is not None:
            self.select_option_by_label(TERM_LABEL, _starts_with(academic_term))
        if description is not None:
            self.fill_labeled(DESCRIPTION_FIELD, description)

    def fill_edit_form(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> None:
        """Fill any subset of the edit form.

        Class/subject/year/term are deliberately absent: the edit route renders
        them as read-only "Fixed Context", because changing them would move the
        syllabus into a (class, term, year, subject) slot the create path guards
        for uniqueness.
        """
        if name is not None:
            self.fill_labeled(NAME_FIELD, name)
        if description is not None:
            self.fill_labeled(DESCRIPTION_FIELD, description)
        if status is not None:
            self.page.get_by_role("button", name=STATUS_BUTTON[status]).first.click()

    def select_topic(self, topic_name: str) -> None:
        """Tick a topic on either form.

        The checkbox is an antd ``Checkbox`` with no accessible name; the topic's
        title is a sibling ``<p>``, so the card holding both is what anchors it.
        ``.last`` picks the innermost matching card if the markup ever nests.
        """
        card = self._topic_card(topic_name)
        expect(card).to_be_visible(timeout=25_000)
        card.locator(TOPIC_CHECKBOX).first.click()
        # Ticking reveals the per-topic Order/Optional controls, which is the
        # cheapest proof the toggle registered rather than the click missing.
        expect(card.locator("input[type='number']")).to_be_visible(timeout=10_000)

    def set_topic_order(self, topic_name: str, order: int) -> None:
        """Set a ticked topic's position in the teaching sequence."""
        self._topic_card(topic_name).locator("input[type='number']").first.fill(
            str(order)
        )

    def expect_topics_selected(self, count: int) -> None:
        """Assert the create form's "N Topics Selected" badge."""
        expect(
            self.page.get_by_text(re.compile(rf"{count}\s+Topics Selected", re.I))
        ).to_be_visible(timeout=15_000)

    def expect_topics_included(self, count: int) -> None:
        """Assert the edit form's "N Topics Included" badge."""
        expect(
            self.page.get_by_text(re.compile(rf"{count}\s+Topics Included", re.I))
        ).to_be_visible(timeout=15_000)

    def submit_create(self) -> None:
        self._submit(CREATE_SUBMIT, CREATE_TOAST)

    def submit_update(self) -> None:
        self._submit(UPDATE_SUBMIT, UPDATE_TOAST)

    # ───────────────────────── internals ───────────────────────────

    def _topic_card(self, topic_name: str) -> Locator:
        return self.page.locator(TOPIC_CARD).filter(
            has=self.page.get_by_text(_exact(topic_name))
        ).last

    def _submit(self, button: re.Pattern, toast: re.Pattern) -> None:
        """Submit and follow the redirect back to the register.

        Both forms ``router.push("/module/syllabus")`` on success, so waiting for
        the toast *and* the route is what separates "the write was accepted" from
        "an error toast rendered and the form stayed put". Both also validate
        client-side first (``toast.error("Please fill in all required fields")``),
        which would otherwise look identical to a silent no-op.
        """
        self.page.get_by_role("button", name=as_pattern(button)).first.click()
        self.expect_toast(toast, timeout_ms=25_000)
        self.page.wait_for_url(LIST_URL, timeout=25_000)
        self.expect_loaded()
        self.expect_no_load_failure()
        self.wait_for_rows()


def _exact(value: str) -> re.Pattern[str]:
    return as_pattern(rf"^\s*{re.escape(value)}\s*$")


def _starts_with(value: str) -> re.Pattern[str]:
    """Match an option by its leading name, ignoring an " (Active)" suffix."""
    return as_pattern(rf"^\s*{re.escape(value)}\b")
