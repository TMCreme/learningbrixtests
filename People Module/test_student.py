from playwright.sync_api import Page, expect


def test_add_student(page: Page):
    """Adding a student"""
    page.get_by_role("button", name="Students").click()
    page.get_by_role("button", name="Admit Student").click()
    page.get_by_role("textbox", name="Enter first name").fill("Naana")
    page.get_by_role("textbox", name="Enter last name").fill("Boamah")
    page.get_by_role("textbox", name="dd/mm/yyyy").click()
    page.get_by_role("textbox", name="dd/mm/yyyy").fill("03/04/2008")
    page.get_by_role("combobox").click()
    page.get_by_role("option", name="Female").click()
    page.get_by_role("textbox", name="Enter email").fill("nanab@gmail.com")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("textbox", name="Enter residential address").fill("123 Avenue")
    page.get_by_role("textbox", name="Enter location").fill("Spintex")
    page.get_by_text("Select a guardian").click()
    page.get_by_title("Constance Amenuvor (ID:").locator("div").click()
    page.get_by_text("Residential Address *Location").click()
    page.get_by_role("textbox", name="Enter previous school").fill("Alsyd Academy")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("combobox").filter(has_text="Select class").click()
    page.locator("html").click()
    page.get_by_role("combobox").filter(has_text="Select blood type").click()
    page.get_by_role("option", name="O+").click()
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Add Student").click()
    expect(page.locator("div").filter(has_text=": Class student record not found").nth(2)).to_be_visible() # change this
