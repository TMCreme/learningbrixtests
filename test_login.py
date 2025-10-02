from playwright.sync_api import Page, expect
import pytest, os


@pytest.mark.no_login
def test_positive_login(page: Page):
    """Positive test for login."""
    page.goto("https://smsfrontend2.vercel.app/auth/login")

    page.fill("input[name='email']", os.getenv("TEST_EMAIL"))
    page.fill("input[name='password']", os.getenv("TEST_PASSWORD"))
    page.click("button[type='submit']")

    heading = page.locator("h2:has-text('MST Talent School')")
    expect(heading).to_have_text("MST Talent School")

@pytest.mark.no_login
def test_negative_login(page: Page):
    """Negative test for login."""
    page.goto("https://smsfrontend2.vercel.app/auth/login")
    page.fill("input[name='email']", os.getenv("TEST_EMAIL"))
    page.fill("input[name='password']", os.getenv("TEST_PASSWORD"))
    page.click("button[type='submit']")

    expect(page.locator("p", has_text="Provide your credentials to get access")).to_be_visible()

@pytest.mark.no_login
def test_email_required(page: Page):
    """Test for login without email."""
    page.goto("https://smsfrontend2.vercel.app/auth/login")

    page.fill("input[name='password']", "Passwd12**")
    page.click("button[type='submit']")
    page.locator("div.form-wrapper").click()

    expect(page.locator("p", has_text="Email is required.")).to_be_visible()

@pytest.mark.no_login
def test_password_required(page: Page):
    """Test for login without a password."""
    page.goto("https://smsfrontend2.vercel.app/auth/login")

    page.fill("input[name='email']", "doltitarzu@necub.com")
    page.click("button[type='submit']")

    page.locator("div.form-wrapper").click()

    expect(page.locator("p", has_text="Password is required")).to_be_visible()
