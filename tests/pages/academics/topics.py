"""Academics → Topics page object.

There is no ``/module/topics`` route. The ledger names one, but Next.js has no
such segment; the ``topics`` module's surfaces are three, and this object drives
all of them:

* ``/module/subjects`` — the **Topics tab** of "Manage Subjects & Topics". The
  register (search, subject filter, one row per topic) plus the two write
  launchers, "Add Topic" and "Reorder Topics", and a row menu carrying View
  details / Edit topic / Archive topic / Delete topic.
* ``/module/subjects/topics/add`` — the bulk composer. Topics are *staged* into
  a batch one at a time and posted together to ``POST /topics/bulk``.
* ``/module/subjects/topics/edit/{id}`` — the single-topic edit form.

The reorder editor (``/module/subject_topics/reorder_topics``) is deliberately
not driven here: it is a dnd-kit drag surface, and ``config/module_catalog.py``
records it only because it is the one page guarding on
``useModuleGuard("topics")``.

Selector families
    Every field on the two forms is **antd** — ``Input``, ``TextArea``,
    ``InputNumber`` and ``Select`` — laid out as ``<div><label>…</label><widget/></div>``
    with a bare ``<label>`` that carries no ``for`` (trap 5), so every text field
    here spells its placeholder as an alternation branch and every dropdown goes
    through ``BasePage.select_option_by_label``. No date picker exists anywhere
    in this module, so trap 1 never arises.

    Two controls carry no accessible name at all and are reached structurally:
    the composer's "+" stage button (its caption is a sibling ``<span>Add</span>``)
    and each row's "…" menu trigger (an icon button, the only button in its row).

Who may write here
    ``("manage", "topics")`` — which the seeded **Teacher** role holds, while
    holding only ``("read", "subjects")``. Both frontend surfaces used to read
    these affordances off the *subjects* permission and so hid them from exactly
    that role; see ``state/backend_patches.md``. On top of the permission,
    ``TopicService._assert_can_manage_subject`` lets a teacher author topics only
    for a subject they are the **subject teacher** of — being the *class* teacher
    grants reads and no writes at all (``can_manage_subject`` ignores
    ``class_ids``), so a test drives that assignment in first.

Register details the assertions here are built on
    * **The status badge is upper-cased in the DOM**, not in CSS
      (``{topic.status.toUpperCase()}``), unlike the syllabus register's. Status
      assertions are therefore spelled in upper case.
    * **Search is server-side.** ``search`` narrows the fetch itself after a
      500ms debounce. That box had always sent the parameter while
      ``GET /topics/`` declared none, so it did nothing until the patch recorded
      in ``state/backend_patches.md``.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.academics.subjects import NAV_SUBJECTS, PAGE_HEADING
from tests.pages.base import BasePage, as_pattern

# ── the three routes ─────────────────────────────────────────────────────────
# The register's own URL is anchored so it cannot also match the add/edit routes
# that live underneath it.
LIST_URL = re.compile(r"/module/subjects(?:$|[?#])")
ADD_URL = re.compile(r"/module/subjects/topics/add")
EDIT_URL = re.compile(r"/module/subjects/topics/edit/\d+")

# ── the register (subjects/page.tsx) ─────────────────────────────────────────
SUBJECTS_TAB = re.compile(r"^\s*Subjects\s*$", re.I)
TOPICS_TAB = re.compile(r"^\s*Topics\s*$", re.I)

SEARCH_PLACEHOLDER = re.compile(r"^\s*Search topic or subject\s*$", re.I)
SUBJECT_FILTER_ALL = re.compile(r"^\s*All Subjects\s*$", re.I)

ADD_TOPIC_BUTTON = re.compile(r"^\s*Add Topic\s*$", re.I)
REORDER_TOPICS_BUTTON = re.compile(r"^\s*Reorder Topics\s*$", re.I)

TOPICS_PANEL = re.compile(r"^\s*All Topics\s*$", re.I)
EMPTY_TABLE = re.compile(r"^\s*No topics found\s*$", re.I)
# PageError, mounted with this exact title when a list fetch is refused — it
# replaces the whole screen.
LOAD_FAILURE_TITLE = re.compile(r"Failed to load subjects data", re.I)

# Row "…" menu. Everything but the first is gated on the topics manage
# permission.
VIEW_ITEM = re.compile(r"^\s*View details\s*$", re.I)
EDIT_ITEM = re.compile(r"^\s*Edit topic\s*$", re.I)
ARCHIVE_ITEM = re.compile(r"^\s*Archive topic\s*$", re.I)
DELETE_ITEM = re.compile(r"^\s*Delete topic\s*$", re.I)

# Column order of the Topics table (page.tsx <TableHeader>); the last cell holds
# the row menu and no data.
COLUMN = {
    "name": 0,
    "subject": 1,
    "order": 2,
    "status": 3,
    "date_created": 4,
    "actions": 5,
}

# What the Status cell actually holds — the badge text is upper-cased in the DOM.
STATUS = {"active": "ACTIVE", "archived": "ARCHIVED"}

# ── the composer (topics/add/page.tsx) ───────────────────────────────────────
ADD_HEADING = re.compile(r"^\s*Add Topics\s*$", re.I)
CREATE_SUBMIT = re.compile(r"^\s*(Create Topics|Creating\.\.\.)\s*$", re.I)
CLEAR_ALL_BUTTON = re.compile(r"^\s*Clear All\s*$", re.I)
STAGED_HEADING = re.compile(r"^\s*Added Topics", re.I)
# antd renders it as `${n} topics added successfully!`.
CREATE_TOAST = re.compile(r"\d+\s+topics added successfully", re.I)

# ── the edit form (topics/edit/[id]/page.tsx) ────────────────────────────────
EDIT_HEADING = re.compile(r"^\s*Edit Topic\s*$", re.I)
UPDATE_SUBMIT = re.compile(r"^\s*(Update Topic|Saving\.\.\.)\s*$", re.I)
UPDATE_TOAST = re.compile(r"Topic updated successfully", re.I)

# ── fields, shared by both forms ─────────────────────────────────────────────
# Label first, placeholder second: the <label>s carry no `for`, so
# `BasePage.fill_labeled` falls through to the placeholder (trap 5).
SUBJECT_LABEL = re.compile(r"^\s*Target Subject\s*$", re.I)
NAME_FIELD = re.compile(r"^\s*Topic Name\s*$|Introduction to Algebra", re.I)
DESCRIPTION_FIELD = re.compile(
    r"^\s*Description\s*$|What will be covered in this topic", re.I
)
OUTCOMES_FIELD = re.compile(
    r"^\s*Learning Outcomes\s*$|What students will be able to do", re.I
)
OBJECTIVES_FIELD = re.compile(
    r"^\s*Objectives\s*$|Teaching objectives for this topic", re.I
)
RESOURCES_FIELD = re.compile(
    r"^\s*Resources\s*$|Textbooks, links, materials", re.I
)
DURATION_FIELD = re.compile(r"Duration \(Minutes\)|e\.g\. 40", re.I)

# ── the View details dialog ──────────────────────────────────────────────────
DETAILS_TITLE = re.compile(r"^\s*Topic Details\s*$", re.I)
DETAILS_DIALOG = re.compile(r"Topic Details", re.I)
DETAILS_CLOSE = re.compile(r"^\s*Close\s*$", re.I)

# The composer's "+" button has no accessible name; its caption is the sibling
# <span>Add</span> that sits under it.
STAGE_BUTTON = "xpath=//span[normalize-space()='Add']/preceding-sibling::button[1]"


class TopicsPage(BasePage):
    """The Topics tab of /module/subjects, plus its add and edit routes."""

    URL = "/module/subjects"

    # ────────────────────────── the register ───────────────────────

    def open(self) -> "TopicsPage":
        super().open()
        return self.expect_loaded()

    def open_from_nav(self) -> "TopicsPage":
        """Reach the screen the way a user does — the sidebar's "Subject & Topic".

        A demo video has to show how someone gets to the module rather than
        teleport there, so the recorded tests navigate with this; ``open`` stays
        the deep link for everything else.
        """
        link = self.page.get_by_role("link", name=as_pattern(NAV_SUBJECTS)).first
        expect(link).to_be_visible(timeout=25_000)
        link.click()
        return self.expect_loaded()

    def expect_loaded(self) -> "TopicsPage":
        """Assert the screen is through its guards, however it was reached.

        ``useModuleGuard``/``usePermissionGuard`` render ``null`` rather than an
        error, and a refused fetch swaps everything for ``PageError`` — so the
        heading being on screen is what says "this user got the register".
        """
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
            timeout=25_000
        )
        return self

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(LOAD_FAILURE_TITLE)).to_have_count(0)

    def show_topics(self) -> "TopicsPage":
        """Switch to the Topics tab and wait for its own fetch to settle.

        Both forms ``router.push("/module/subjects")`` on success and the screen
        always mounts on the Subjects tab, so this is called again after every
        write.
        """
        self.page.get_by_role("button", name=TOPICS_TAB).first.click()
        # The tab swap is what triggers fetchAllTopics/fetchSubjectsForTopics;
        # the search box is re-placeholdered in the same render.
        expect(self.page.get_by_placeholder(SEARCH_PLACEHOLDER).first).to_be_visible(
            timeout=25_000
        )
        self.wait_for_rows()
        return self

    def wait_for_rows(self, timeout_ms: int = 30_000) -> None:
        """Block until the table has settled on rows or on its empty state.

        The header renders immediately and the body swaps a spinner row for one
        of the two, so asserting on the heading alone would pass mid-flight. Only
        data rows carry a ``font-medium`` first cell.
        """
        body = self.page.locator("table tbody")
        settled = body.get_by_text(EMPTY_TABLE).first.or_(
            body.locator("td.font-medium").first
        )
        expect(settled.first).to_be_visible(timeout=timeout_ms)

    def search(self, query: str) -> None:
        """Narrow the register with its "Search topic or subject" box.

        Debounced 500ms, then refetched server-side against the topic's name and
        description and its subject's name. Preferred over the subject filter
        dropdown, which would need its options to have loaded first.
        """
        self.page.get_by_placeholder(SEARCH_PLACEHOLDER).first.fill(query)
        self.wait_for_rows()

    def find_row(self, name: str) -> Locator:
        """The register row for ``name``, matched on the row's whole text.

        Every topic these tests create carries the run tag, so a substring match
        is unambiguous.
        """
        return self.page.get_by_role("row").filter(
            has_text=as_pattern(re.escape(name))
        ).first

    def cell(self, name: str, column: int) -> Locator:
        """One cell of ``name``'s row, by column index (see ``COLUMN``)."""
        return self.find_row(name).get_by_role("cell").nth(column)

    def expect_row(self, name: str, timeout_ms: int = 30_000) -> None:
        expect(self.find_row(name)).to_be_visible(timeout=timeout_ms)

    def expect_absent(self, name: str, timeout_ms: int = 25_000) -> None:
        expect(self.find_row(name)).to_have_count(0, timeout=timeout_ms)

    def expect_subject(self, name: str, subject_name: str) -> None:
        """Assert the Subject cell — the pairing every topic is keyed on."""
        expect(self.cell(name, COLUMN["subject"])).to_have_text(
            _exact(subject_name), timeout=25_000
        )

    def expect_status(self, name: str, status: str) -> None:
        """Assert the Status badge. ``status`` is the stored, lower-case value;
        the badge text itself is upper-cased in the DOM."""
        expect(self.cell(name, COLUMN["status"])).to_have_text(
            _exact(STATUS[status]), timeout=25_000
        )

    def expect_teaching_order(self, *names: str) -> None:
        """Assert the register holds exactly ``names``, in that order.

        ``GET /topics/`` sorts on ``(subject_id, order_index, name)`` and the
        backend assigns ``order_index`` itself (``auto_increment_topic_order_index``
        on ``Topic``), so with the register narrowed to one subject this is the
        teaching sequence as the school will read it — and, since narrowing is
        what the search box does server-side, it also proves the search really
        filtered.

        Header rows are excluded by scoping to ``tbody``; ``get_by_role("row")``
        would count the ``<thead>`` row too.
        """
        rows = self.page.locator("table tbody tr")
        expect(rows).to_have_count(len(names), timeout=25_000)
        for index, name in enumerate(names):
            expect(rows.nth(index)).to_contain_text(name, timeout=15_000)

    # ──────────────────────────── row menu ─────────────────────────

    def open_row_menu(self, name: str) -> None:
        row = self.find_row(name)
        expect(row).to_be_visible(timeout=30_000)
        # The actions cell holds the only <button> in the row.
        row.get_by_role("button").last.click()
        expect(self.page.get_by_role("menuitem", name=VIEW_ITEM)).to_be_visible(
            timeout=15_000
        )

    def close_row_menu(self) -> None:
        """Dismiss an open Radix dropdown.

        It renders in a portal behind a modal overlay, so leaving it open makes
        the very next click on the page land on the overlay instead of its
        target.
        """
        self.page.keyboard.press("Escape")
        expect(self.page.get_by_role("menuitem", name=VIEW_ITEM)).to_have_count(0)

    def open_details(self, name: str) -> None:
        """Open the read-only "Topic Details" dialog from the row menu."""
        self.open_row_menu(name)
        self.page.get_by_role("menuitem", name=VIEW_ITEM).first.click()
        expect(self.page.get_by_role("heading", name=DETAILS_TITLE)).to_be_visible(
            timeout=20_000
        )

    def close_details(self) -> None:
        self._details().get_by_role("button", name=DETAILS_CLOSE).first.click()
        expect(self.page.get_by_role("heading", name=DETAILS_TITLE)).to_have_count(0)

    def expect_details_text(self, value: str) -> None:
        """Assert a value is rendered somewhere in the open details dialog."""
        expect(self._details().get_by_text(as_pattern(re.escape(value))).first
               ).to_be_visible(timeout=20_000)

    # ─────────────────────── the bulk composer ─────────────────────

    def open_add_form(self) -> None:
        """Follow "Add Topic" through to /module/subjects/topics/add.

        The trigger only renders for the topics manage permission, so a
        read-only role fails here as a missing control rather than as a refused
        POST.
        """
        self.page.get_by_role("button", name=ADD_TOPIC_BUTTON).first.click()
        self.page.wait_for_url(ADD_URL, timeout=25_000)
        expect(self.page.get_by_role("heading", name=ADD_HEADING)).to_be_visible(
            timeout=25_000
        )
        expect(self.page.get_by_placeholder(NAME_FIELD).first).to_be_visible(
            timeout=25_000
        )

    def choose_subject(self, subject_name: str) -> None:
        """Pick the batch's Target Subject.

        One selection covers the whole batch: ``POST /topics/bulk`` takes a
        single ``subject_id`` and a list of topics.

        Not ``BasePage.select_option_by_label``: that is written for the Radix
        selects the rest of the app uses, and this control is an **antd**
        ``Select``. antd renders two elements per option — the real
        ``.ant-select-item-option`` in the dropdown, and a visually hidden
        ``<div role="option" id="…_list_N">`` inside rc-virtual-list's
        accessibility mirror, which holds only the option's index as its text
        and carries the label on ``aria-label``. The mirror comes first in the
        DOM, so matching ``get_by_role("option", …).first`` resolves to an
        element that can never be clicked ("element is not visible"). The real
        option is matched instead, scoped to the dropdown that is actually open
        — antd leaves every dropdown it has ever rendered mounted-but-hidden.
        """
        group = self.page.locator("label").filter(
            has_text=as_pattern(SUBJECT_LABEL)
        ).first.locator("xpath=..")
        group.locator(".ant-select").first.click()

        option = self.page.locator(".ant-select-dropdown:visible").last.locator(
            ".ant-select-item-option"
        ).filter(has_text=_exact(subject_name)).first
        expect(option).to_be_visible(timeout=20_000)
        option.click()
        # The trigger carries the chosen subject once the dropdown has closed;
        # staging a topic before that would post the batch against subject_id 0
        # (``selectedSubjectId`` starts at 0 and handleAddToBatch rejects it).
        # Asserted on the field as a whole rather than on
        # ``.ant-select-selection-item``: with ``showSearch`` antd swaps which
        # node holds the label while the control has focus.
        expect(group).to_contain_text(subject_name, timeout=15_000)

    def stage_topic(
        self,
        *,
        name: str,
        description: str,
        learning_outcomes: str | None = None,
        objectives: str | None = None,
        resources: str | None = None,
        duration_minutes: int | None = None,
    ) -> None:
        """Fill the composer and add the topic to the pending batch.

        Nothing is posted here — "Add" only moves the staged values into the
        "Added Topics" list and blanks the form. ``handleAddToBatch`` rejects an
        empty name or description (and a missing subject) with a toast, so the
        batch entry appearing is what says the stage was accepted.
        """
        self.fill_labeled(NAME_FIELD, name)
        self.fill_labeled(DESCRIPTION_FIELD, description)
        if learning_outcomes is not None:
            self.fill_labeled(OUTCOMES_FIELD, learning_outcomes)
        if objectives is not None:
            self.fill_labeled(OBJECTIVES_FIELD, objectives)
        if resources is not None:
            self.fill_labeled(RESOURCES_FIELD, resources)
        if duration_minutes is not None:
            self.fill_labeled(DURATION_FIELD, str(duration_minutes))

        self.page.locator(STAGE_BUTTON).first.click()
        self.expect_staged(name)

    def expect_staged(self, name: str, timeout_ms: int = 15_000) -> None:
        """Assert a topic is sitting in the pending batch."""
        expect(self.page.get_by_role("heading", name=as_pattern(re.escape(name)))
               ).to_be_visible(timeout=timeout_ms)

    def expect_staged_count(self, count: int) -> None:
        """Assert the "Added Topics <n>" counter beside the batch heading."""
        expect(
            self.page.get_by_role("heading", name=STAGED_HEADING)
        ).to_contain_text(str(count), timeout=15_000)

    def submit_create(self) -> None:
        """Post the whole batch and follow the redirect back to the register."""
        self._submit(CREATE_SUBMIT, CREATE_TOAST)

    # ───────────────────────── the edit form ───────────────────────

    def open_edit_form(self, name: str) -> None:
        """Open ``name``'s row menu and follow "Edit topic"."""
        self.open_row_menu(name)
        self.page.get_by_role("menuitem", name=EDIT_ITEM).first.click()
        self.page.wait_for_url(EDIT_URL, timeout=25_000)
        expect(self.page.get_by_role("heading", name=EDIT_HEADING)).to_be_visible(
            timeout=25_000
        )
        # The whole route renders a spinner until GetATopic + fetchSubjects have
        # both answered; the name input only exists on the loaded form.
        expect(self.page.get_by_placeholder(NAME_FIELD).first).to_be_visible(
            timeout=25_000
        )

    def expect_field(self, field: re.Pattern[str], value: str) -> None:
        """Assert a form field reads back ``value``.

        Used on the edit form, where every input is prefilled from
        ``GET /topics/{id}`` — which makes it an assertion about what was
        *persisted*, not about what the previous form posted.
        """
        expect(self.page.get_by_placeholder(field).first).to_have_value(
            value, timeout=20_000
        )

    def fill_edit_form(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        learning_outcomes: str | None = None,
        objectives: str | None = None,
        resources: str | None = None,
        duration_minutes: int | None = None,
        subject_name: str | None = None,
    ) -> None:
        """Fill any subset of the edit form; unnamed fields are left alone."""
        if subject_name is not None:
            # Same antd Select as the composer's — see choose_subject.
            self.choose_subject(subject_name)
        if name is not None:
            self.fill_labeled(NAME_FIELD, name)
        if description is not None:
            self.fill_labeled(DESCRIPTION_FIELD, description)
        if learning_outcomes is not None:
            self.fill_labeled(OUTCOMES_FIELD, learning_outcomes)
        if objectives is not None:
            self.fill_labeled(OBJECTIVES_FIELD, objectives)
        if resources is not None:
            self.fill_labeled(RESOURCES_FIELD, resources)
        if duration_minutes is not None:
            self.fill_labeled(DURATION_FIELD, str(duration_minutes))

    def submit_update(self) -> None:
        """Save the topic and follow the redirect back to the register."""
        self._submit(UPDATE_SUBMIT, UPDATE_TOAST)

    # ───────────────────────── internals ───────────────────────────

    def _details(self) -> Locator:
        return self.page.get_by_role("dialog").filter(has_text=DETAILS_DIALOG).first

    def _submit(self, button: re.Pattern[str], toast: re.Pattern[str]) -> None:
        """Submit a form and land back on a settled Topics tab.

        Both forms ``router.push("/module/subjects")`` on success, so waiting for
        the toast *and* the route is what separates "the write was accepted" from
        "an error toast rendered and the form stayed put". Both also validate
        client-side first (``toast.error("Please fill in all required fields")``),
        which would otherwise look identical to a silent no-op. The screen always
        remounts on the Subjects tab, so the Topics tab is reselected here.
        """
        self.page.get_by_role("button", name=as_pattern(button)).first.click()
        self.expect_toast(toast, timeout_ms=25_000)
        self.page.wait_for_url(LIST_URL, timeout=25_000)
        self.expect_loaded()
        self.expect_no_load_failure()
        self.show_topics()


def _exact(value: str) -> re.Pattern[str]:
    return as_pattern(rf"^\s*{re.escape(value)}\s*$")
