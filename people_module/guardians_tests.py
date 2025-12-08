import re

from playwright.sync_api import Page, expect


def test_add_guardian(page: Page):
    """Adding a guardian"""
    page.get_by_role("button", name="Guardians").click()
    page.get_by_role("button", name="Add Guardian").click()
    page.get_by_role("textbox", name="Enter first name").fill("Constance")
    page.get_by_role("textbox", name="Enter last name").fill("Amenuvor")
    page.get_by_role("combobox").filter(has_text="Select gender").click()
    page.get_by_role("option", name="Female").click()
    page.locator("div").filter(has_text=re.compile(r"^Date of Birth \*$")).locator("div").first.click()
    page.get_by_role("textbox", name="dd/mm/yyyy").fill("19/09/1998")
    page.get_by_role("combobox").filter(has_text="Select status").click()
    page.get_by_role("option", name="Single").click()
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("textbox", name="Enter residential address").fill("Gbawe")
    page.get_by_role("textbox", name="Enter location").fill("Gbawe")
    page.get_by_role("textbox", name="Enter residential address").fill("Gbawe Junction")
    page.locator("div").filter(has_text=re.compile(r"^Phone Number \*$")).get_by_placeholder(
        "Enter phone number").click()
    page.locator("div").filter(has_text=re.compile(r"^Phone Number \*$")).get_by_placeholder("Enter phone number").fill(
        "0252349623")
    page.get_by_role("textbox", name="Enter email address").fill("constance@gmail.com")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("textbox", name="Enter occupation").fill("Shop Manager")
    page.get_by_text("Occupation *EmployerWork").click()
    page.get_by_role("button", name="Add Guardian").click()
    expect(page.get_by_text("Guardian added successfully!")).to_be_visible()

def test_read_guardians(page: Page):
    """Viewing guardian"""
    page.get_by_role("button", name="Guardians").click()
    page.get_by_role("table").get_by_text("Constance Amenuvor").click()
    expect(page.get_by_role("heading", name="Constance Amenuvor")).to_be_visible()

def test_edit_guardian(page: Page):
    """Editing guardian"""
    page.get_by_role("button", name="Guardians").click()
    page.get_by_role("table").get_by_text("Constance Amenuvor").click()
    page.get_by_role("button", name="Edit Profile").click()
    page.get_by_role("textbox", name="Enter your nationality (e.g:").fill("Ghanaian")
    page.get_by_role("button", name="Continue").click()
    expect(page.get_by_text("Guardian updated successfully")).to_be_visible()

def test_no_access_guardians(page: Page):
    expect(page.get_by_role("button", name="Guardians")).not_to_be_visible()


def test_manage_guardians(page: Page):
    test_add_guardian(page)
    test_read_guardians(page)
    test_edit_guardian(page)

