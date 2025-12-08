from playwright.sync_api import Page


def test_add_fee(page: Page):
    """Add a fee."""
    page.get_by_role("button", name="Fee Management").click()
    page.get_by_role("button", name="Configure Fees").click()
    page.get_by_role("button", name="Fees").click()
    page.get_by_role("button", name="Create Fee").click()
    page.get_by_role("textbox", name="Enter fee name").fill("Lunch fee")
    page.get_by_placeholder("Enter amount").fill("0100")
    page.get_by_role("textbox", name="Enter description (optional)").fill("Fees for lunch for the week")
    page.get_by_role("combobox").filter(has_text="Select academic year").click()
    page.get_by_role("option", name="2027 (inactive)").click()
    page.get_by_role("combobox").filter(has_text="Select academic term").click()
    page.get_by_role("option", name="First Term").click()
    page.get_by_role("button", name="Create", exact=True).click()
    page.locator("div").filter(has_text="Fee created successfully").nth(2).click()


def test_add_fee_group(page: Page):
    pass


def test_read_fees(page: Page):
    pass


def test_view_fee_group(page: Page):
    pass


def test_edit_fee(page: Page):
    pass


def test_edit_fee_group(page: Page):
    pass


def test_manage_fees(page: Page):
    pass

def test_no_access_fees(page: Page):
    pass