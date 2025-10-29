import re

from playwright.sync_api import Page, expect


def test_add_teaching_staff(page: Page):
    """Adding a staff member"""
    page.get_by_role("button", name="Staff", exact=True).click()
    page.get_by_role("button", name="Add Teaching Staff").click()
    page.get_by_role("textbox", name="Enter first name").click()
    page.get_by_role("textbox", name="Enter first name").fill("James")
    page.get_by_role("textbox", name="Enter last name").click()
    page.get_by_role("textbox", name="Enter last name").fill("Doe")
    page.get_by_role("combobox").filter(has_text="Select gender").click()
    page.get_by_label("Female").get_by_text("Female").click()
    page.get_by_role("textbox", name="dd/mm/yyyy").click()
    page.get_by_role("textbox", name="dd/mm/yyyy").fill("03")
    page.get_by_title("-10-29").locator("div").click()
    page.get_by_title("-10-28").locator("div").click()
    page.get_by_title("-10-28").locator("div").click()
    page.get_by_role("textbox", name="Enter your nationality").click()
    page.get_by_role("textbox", name="Enter your nationality").fill("Ghanaian")
    page.get_by_role("combobox").filter(has_text="Select status").click()
    page.get_by_label("Divorced").get_by_text("Divorced").click()
    page.get_by_role("textbox", name="Enter your local dialect").click()
    page.get_by_role("textbox", name="Enter your local dialect").fill("Twi")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("textbox", name="Enter residential address").click()
    page.get_by_role("textbox", name="Enter residential address").fill("123 Avenue")
    page.get_by_role("textbox", name="Enter location").click()
    page.get_by_role("textbox", name="Enter location").fill("Ghana")
    page.locator("div").filter(has_text=re.compile(r"^Phone Number \*$")).get_by_placeholder(
        "Enter phone number").click()
    page.locator("div").filter(has_text=re.compile(r"^Phone Number \*$")).get_by_placeholder("Enter phone number").fill(
        "0208123482")
    page.get_by_role("textbox", name="Enter email address").click()
    page.get_by_role("textbox", name="Enter email address").fill("abc@gmail.com")
    page.locator("div").filter(has_text=re.compile(r"^Religion$")).click()
    page.get_by_role("textbox", name="Enter your religion").fill("Christianity")
    page.get_by_role("button", name="Continue").click()
    page.locator("div").filter(has_text=re.compile(r"^Job Title \*$")).click()
    page.get_by_role("textbox", name="Enter title").fill("Chemistry Teacher")
    page.get_by_role("combobox").filter(has_text="Select employment type").click()
    page.get_by_role("option", name="Contract").click()
    page.locator("div").filter(has_text=re.compile(r"^Admission Date \*$")).locator("div").first.click()
    page.get_by_text("9", exact=True).click()
    page.locator(".css-19bb58m").click()
    page.get_by_text("Assigned Class(es)Use Up and").click()
    page.get_by_text("Select assigned subject(s)").click()
    page.get_by_text("Basic InformationContact DetailsAdmission InformationZip CodeJob Title *").click()
    page.get_by_role("textbox", name="Enter field of study").click()
    page.get_by_role("combobox").filter(has_text="Select degree").click()
    page.get_by_label("Bachelor's Degree").get_by_text("Bachelor's Degree").click()
    page.get_by_role("textbox", name="Enter field of study").click()
    page.get_by_role("textbox", name="Enter field of study").fill("Science")
    page.get_by_role("button", name="Add Staff").click()

def test_add_non_teaching_staff(page: Page):
    """Adding a non-teaching staff member"""
    page.get_by_role("button", name="Staff", exact=True).click()
    page.get_by_role("button", name="Non-teaching Staff").click()
    page.get_by_role("button", name="Add Non-teaching Staff").click()
    page.get_by_role("textbox", name="Enter first name").click()
    page.get_by_role("textbox", name="Enter first name").fill("Gordon")
    page.get_by_role("textbox", name="Enter first name").press("Tab")
    page.get_by_role("textbox", name="Enter last name").fill("Ramsay3")
    page.get_by_role("textbox", name="dd/mm/yyyy").click()
    page.get_by_role("textbox", name="dd/mm/yyyy").fill("03/05/2002")
    page.get_by_text("9", exact=True).click()
    page.get_by_role("combobox").filter(has_text="Select gender").click()
    page.get_by_role("option", name="Male", exact=True).click()
    page.get_by_role("textbox", name="Enter your nationality").click()
    page.get_by_role("textbox", name="Enter your nationality").fill("American")
    page.get_by_role("combobox").filter(has_text="Select status").click()
    page.get_by_role("option", name="Married").click()
    page.get_by_role("textbox", name="Enter your local dialect").click()
    page.get_by_role("textbox", name="Enter your local dialect").fill("Ewe")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("textbox", name="Enter residential address").click()
    page.get_by_role("textbox", name="Enter residential address").fill("21 Jump Street")
    page.get_by_role("textbox", name="Enter location").click()
    page.get_by_role("textbox", name="Enter location").fill("Ghana")
    page.locator("div").filter(has_text=re.compile(r"^Phone Number \*$")).get_by_placeholder(
        "Enter phone number").click()
    page.locator("div").filter(has_text=re.compile(r"^Phone Number \*$")).get_by_placeholder("Enter phone number").fill(
        "0289123423")
    page.get_by_role("textbox", name="Enter email address").click()
    page.get_by_role("textbox", name="Enter email address").fill("ame@gmail.com")
    page.get_by_role("textbox", name="Enter your religion").click()
    page.get_by_role("textbox", name="Enter your religion").fill("Christian")
    page.get_by_text("Residential Address *Location").click()
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("combobox").filter(has_text=re.compile(r"^$")).click()
    page.get_by_role("option", name="Student").click()
    page.get_by_role("textbox", name="Enter title").click()
    page.get_by_role("combobox").filter(has_text="Student").click()
    page.locator("html").click()
    page.get_by_role("textbox", name="Enter title").click()
    page.get_by_role("textbox", name="Enter title").fill("Student")
    page.get_by_role("combobox").filter(has_text="Select employment type").click()
    page.get_by_role("option", name="Full-time").click()
    page.get_by_role("textbox", name="dd/mm/yyyy").click()
    page.get_by_text("16").click()
    page.get_by_role("button", name="Add Non-teaching Staff").click()
    page.goto("https://smsfrontend2.vercel.app/module/staff")
    expect(page.locator("div").filter(has_text="Non-teaching staff added").nth(2)).to_be_visible()



def test_view_staff(page: Page):
    """Viewing staff members"""
    page.get_by_role("button", name="Staff", exact=True).click()
    page.get_by_role("cell", name="Profile Picture James Doe").locator("span").click()
    expect(page.get_by_role("heading", name="James Doe").click()).to_be_visible()

def test_view_non_teaching_staff(page: Page):
    """Viewing non-teaching staff members"""
    page.get_by_role("button", name="Staff", exact=True).click()
    page.get_by_role("button", name="Non-teaching Staff").click()
    page.get_by_role("cell", name="Profile Picture Gordon Ramsay").locator("span").click()
    expect(page.get_by_role("heading", name="Gordon Ramsay")).to_be_visible()

def test_edit_staff(page: Page):
    """Editing staff members"""
    page.get_by_role("button", name="Staff", exact=True).click()
    page.get_by_role("cell", name="Profile Picture James Doe").locator("span").click()
    page.get_by_role("heading", name="James Doe").click()
    page.get_by_role("button", name="Staff", exact=True).click()
    page.get_by_role("cell", name="Profile Picture James Doe").locator("span").click()
    page.get_by_role("button", name="Edit Profile").click()
    page.get_by_role("textbox", name="Enter last name").dblclick()
    page.get_by_role("textbox", name="Enter last name").fill("Downy")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Update Staff").click()
    expect(page.locator("div").filter(has_text="Staff updated successfully!").nth(2)).to_be_visible()
    page.get_by_role("cell", name="Profile Picture James Downy").click()
    expect(page.get_by_role("heading", name="James Downy")).to_be_visible()

def test_edit_non_teaching_staff(page: Page):
    """Editing non-teaching staff members"""
    page.get_by_role("button", name="Staff", exact=True).click()
