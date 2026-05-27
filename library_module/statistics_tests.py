from playwright.sync_api import expect, Page


def test_no_access_statistics(page: Page):
    expect().not_to_be_visible()

def test_manage_statistics(page):
    pass

def test_read_statistics(page):
    pass