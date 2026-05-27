from playwright.sync_api import expect, Page

def test_add_exams(page: Page):
    pass


def test_read_exams(page: Page):
    pass


def test_no_access_exams(page: Page):
    expect().not_to_be_visible()

def test_manage_exams(page: Page):
    pass
