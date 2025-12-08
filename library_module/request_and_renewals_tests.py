from playwright.sync_api import expect, Page


def test_no_access_requests(page: Page):
    expect(page.get_by_role("button", name="Returns & Renewals")).not_to_be_visible()

def test_read_requests(page):
    pass

def test_manage_requests(page):
    pass