import pytest, os
from playwright.sync_api import sync_playwright, Browser
from dotenv import load_dotenv

load_dotenv()
@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        yield browser
        browser.close()

@pytest.fixture
def page(request, browser: Browser):
    context = browser.new_context()
    page = context.new_page()

    # Skip login if the test is marked with `no_login`
    if not request.node.get_closest_marker("no_login"):
        page.goto("https://smsfrontend2.vercel.app/auth/login")
        page.fill("input[name='email']", os.getenv("TEST_EMAIL"))
        page.fill("input[name='password']", os.getenv("TEST_PASSWORD"))
        page.click("button[type='submit']")
        page.wait_for_selector("text=Dashboard")  # adjust for post-login page

    yield page
    context.close()