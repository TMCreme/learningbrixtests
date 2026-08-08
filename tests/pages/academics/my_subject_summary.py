"""Academics → My Subject Summary (/module/subjects/my-subject-summary).

A teacher-only read-only screen, reached from the "My Subject Summary" button on
``/module/subjects`` (page.tsx renders that button on the role name, not on a
permission). It answers the one question the Subjects register cannot: *which
classes* does this teacher take each of their subjects for.

What fills it
    ``GET /teacher-views/my-subjects-summary`` reads
    ``teacher_subject_class_association`` and nothing else — being the *class*
    teacher of a class does not put its subjects here, even though it does put
    them on the Subjects register (``SubjectService.list_subjects`` widens a
    teacher's scope by their class teacher classes; this endpoint does not). So a
    teacher with no subject assignment sees an empty summary, and the tests seed
    the assignment rather than relying on provisioning's class-teacher link.

The year/term filters default to the school's active pair, so the screen loads
its data without being told anything.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage

HEADING = re.compile(r"^\s*My Subject Summary\s*$", re.I)
BACK_BUTTON = re.compile(r"^\s*Back to Subjects\s*$", re.I)

# Tabs, both plain <button>s.
SUBJECTS_TAB = re.compile(r"^\s*Subjects\s*$", re.I)
SPECIAL_STUDENTS_TAB = re.compile(r"^\s*Special Students\b", re.I)

# Panel headers, each a <span> above its own table.
ASSIGNED_SUBJECTS_PANEL = re.compile(r"^\s*Assigned Subjects\s*$", re.I)
SPECIAL_STUDENTS_PANEL = re.compile(r"^\s*Special Students\s*$", re.I)

SEARCH_FIELD = re.compile(r"^\s*Search subjects\.\.\.\s*$", re.I)

EMPTY_TITLE = re.compile(r"^\s*No subjects found\s*$", re.I)
LOAD_FAILURE_TITLE = re.compile(r"^\s*Failed to load subject summary\s*$", re.I)

# The year/term filters. Their <label>s carry no htmlFor, so the combobox is
# reached through BasePage.select_option_by_label, which anchors on the label's
# parent.
ACADEMIC_YEAR_FIELD = re.compile(r"^\s*Academic Year\s*$", re.I)
ACADEMIC_TERM_FIELD = re.compile(r"^\s*Academic Term\s*$", re.I)

# Columns of the Assigned Subjects table, in render order.
SUBJECT_COLUMNS = {"name": 0, "classes": 1}


class MySubjectSummaryPage(BasePage):
    URL = "/module/subjects/my-subject-summary"

    def expect_loaded(self) -> None:
        """Wait for the summary itself, not merely for the shell.

        The heading renders while ``GET /teacher-views/my-subjects-summary`` is
        still in flight (the table area shows "Loading summary..."), so the panel
        header is what says the data has actually arrived.
        """
        expect(self.page.get_by_role("heading", name=HEADING)).to_be_visible(timeout=20_000)
        expect(self.page.get_by_text(ASSIGNED_SUBJECTS_PANEL).first).to_be_visible(
            timeout=30_000
        )

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(LOAD_FAILURE_TITLE)).to_have_count(0)

    def expect_teacher(self, full_name: str) -> None:
        """The subheading naming whose summary this is ("Teacher: <name>").

        ``.first`` because the name sits in its own ``<span>`` inside the
        paragraph: the pattern spans both, so the paragraph *and* every ancestor
        whose text contains it are candidates, and a bare locator would trip
        strict mode.
        """
        expect(
            self.page.get_by_text(
                re.compile(rf"Teacher:\s*{re.escape(full_name)}", re.I)
            ).first
        ).to_be_visible(timeout=20_000)

    def find_row(self, subject_name: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has=self.page.get_by_text(_exact(subject_name))
        ).first

    def cell(self, subject_name: str, column: str) -> Locator:
        return self.find_row(subject_name).get_by_role("cell").nth(SUBJECT_COLUMNS[column])

    def search(self, query: str) -> None:
        """Filter the table. Client-side here — the whole summary is one payload."""
        self.page.get_by_placeholder(SEARCH_FIELD).first.fill(query)

    def show_special_students(self) -> None:
        self.click_button(SPECIAL_STUDENTS_TAB)


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
