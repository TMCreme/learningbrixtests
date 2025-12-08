from playwright.sync_api import expect, Page


def test_no_access_attendance(page: Page):
    expect().not_to_be_visible()

def test_manage_attendance(page: Page):
    expect().not_to_be_visible()


def test_read_attendance(page: Page):
    expect().not_to_be_visible()