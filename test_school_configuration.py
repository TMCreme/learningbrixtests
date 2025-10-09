from playwright.sync_api import expect


def test_school_configuration(page):
    page.get_by_role("button", name="Configuration").click()
    page.get_by_role("textbox", name="Enter school address").click()
    page.get_by_role("textbox", name="Enter school address").fill("Tamal")
    page.get_by_role("button", name="Update").click()
    expect(page.get_by_text("School Profile Successfully")).to_be_visible()