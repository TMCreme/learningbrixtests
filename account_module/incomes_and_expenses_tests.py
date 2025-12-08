from playwright.sync_api import Page

def add_income(page: Page):
    page.get_by_role("button", name="Income & Expenses").click()

def view_income(page: Page):
    pass

def edit_income(page: Page):
    pass

def delete_income(page: Page):
    pass

def add_expense(page: Page):
    page.get_by_role("button", name="Income & Expenses").click()

def view_expense(page: Page):
    pass

def edit_expense(page: Page):
    pass

def delete_expense(page: Page):
    pass

def test_no_access_incomes_and_expenses(page: Page):
    pass

def test_read_incomes_and_expenses(page: Page):
    pass

def test_manage_incomes_and_expenses(page: Page):
    pass