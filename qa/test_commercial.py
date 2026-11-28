"""Browser tests for PR #7, served entirely through Playwright route fixtures."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect
import pytest

from qa.call_harness import ADMIN, BASE_URL

COMMERCIAL = "/static/commercial/"
STATIC_TYPES = {
    "onboarding.html": "text/html",
    "dashboard.html": "text/html",
    "demo.html": "text/html",
    "templates.json": "application/json",
}


@pytest.fixture
def shop(page, request):
    root = Path(request.config.getoption("--commercial-root")).resolve()
    for name in STATIC_TYPES:
        assert (root / name).is_file(), f"Missing {name} under {root}"
    seen = []
    errors = []
    unexpected = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route_request(route):
        url = urlsplit(route.request.url)
        name = url.path.removeprefix(COMMERCIAL)
        if f"{url.scheme}://{url.netloc}" == BASE_URL and name in STATIC_TYPES:
            assert route.request.method == "GET"
            route.fulfill(path=root / name, content_type=STATIC_TYPES[name])
        elif f"{url.scheme}://{url.netloc}" == BASE_URL and url.path in {
            "/api/health", "/api/dashboard", "/api/receptionist/messages",
        }:
            token = route.request.headers.get("authorization")
            seen.append((route.request.method, url.path, token))
            if url.path == "/api/health":
                route.fulfill(json={"status": "ok", "staging": True})
            elif token != f"Bearer {ADMIN}":
                route.fulfill(status=401, json={"detail": "Unauthorized"})
            else:
                route.fulfill(json={"messages": [], "recent_calls": [], "budget": {"spend_usd": 0}})
        else:
            unexpected.append(route.request.url)
            route.abort()

    page.route("**/*", route_request)
    yield seen
    assert not errors
    assert not unexpected


def send(page, *turns):
    for turn in turns:
        entry = page.locator("#userInput")
        entry.fill(turn)
        entry.press("Enter")


def test_mobile_onboarding_validates_resumes_and_exports(page, shop):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(BASE_URL + COMMERCIAL + "onboarding.html")
    expect(page.locator("#templateStatus")).to_contain_text("Templates loaded")
    page.locator("#nextBtn").click()
    expect(page.locator("#formError")).to_have_text("Business name is required.")
    page.locator("#businessName").fill("Synthetic QA Business")
    page.locator("#contactPhone").fill("+12025550101")
    page.locator("#contactEmail").fill("qa@example.invalid")
    page.locator("#templateId").select_option("plumbing-hvac")
    page.reload()
    expect(page.locator("#resumeBox")).to_contain_text("Draft found")
    expect(page.locator("#businessName")).to_have_value("Synthetic QA Business")
    for _ in range(6):
        page.locator("#nextBtn").click()
    expect(page.locator("#review")).to_be_visible()
    with page.expect_download() as pending:
        page.locator("#downloadBtn").click()
    config = json.loads(Path(pending.value.path()).read_text())
    assert config["businessName"] == "Synthetic QA Business"
    assert config["bookingPrefs"]["approvalRequired"] is True
    assert config["transferRules"]["enabled"] is False
    assert config["templateId"] == "plumbing-hvac"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not shop


def test_dashboard_admin_auth_and_empty_state(page, shop):
    page.goto(BASE_URL + COMMERCIAL + "dashboard.html")
    expect(page.locator("#healthStatus")).to_contain_text("Health endpoint responded")
    assert shop == [("GET", "/api/health", None)]
    page.locator("#token").fill("synthetic-incorrect")
    page.locator("#connectBtn").click()
    expect(page.locator("#connectStatus")).to_contain_text("401")
    page.locator("#token").fill(ADMIN)
    page.locator("#connectBtn").click()
    expect(page.locator("#connectStatus")).to_contain_text("Connected")
    expect(page.locator("#calls")).to_have_text("No calls yet.")
    expect(page.locator("#messages")).to_have_text("No messages yet.")
    expect(page.locator("#appointments")).to_contain_text("No appointments endpoint exists yet")
    assert ("GET", "/api/dashboard", f"Bearer {ADMIN}") in shop
    assert ("GET", "/api/receptionist/messages", f"Bearer {ADMIN}") in shop
    assert ADMIN not in page.evaluate("JSON.stringify([localStorage, sessionStorage, document.cookie])")
    page.locator("#disconnectBtn").click()
    expect(page.locator("#token")).to_have_value("")
    page.reload()
    expect(page.locator("#calls")).to_have_text("Connect to load recent calls.")
    expect(page.locator("#token")).to_have_value("")


def test_demo_booking_download_is_request_only(page, shop):
    page.goto(BASE_URL + COMMERCIAL + "demo.html")
    expect(page.locator("#tplStatus")).to_contain_text("Templates loaded")
    page.get_by_role("button", name="Book an appointment", exact=True).click()
    send(page, "Test Caller", "Routine inspection", "2026-12-04 10:00", "+12025550101")
    expect(page.locator("#chat")).to_contain_text("Nothing was booked")
    with page.expect_download() as pending:
        page.locator("#chat").get_by_role("button", name="Download .ics file").click()
    result = pending.value
    assert result.suggested_filename == "appointment-request.ics"
    calendar = Path(result.path()).read_text()
    assert "BEGIN:VCALENDAR" in calendar
    assert "Appointment REQUEST only" in calendar
    assert not shop


def test_demo_emergency_and_message_remain_simulated(page, shop):
    page.goto(BASE_URL + COMMERCIAL + "demo.html")
    expect(page.locator("#tplStatus")).to_contain_text("Templates loaded")
    page.get_by_role("button", name="Book an appointment", exact=True).click()
    send(page, "I smell a gas smell at the property.")
    expect(page.locator("#chat")).to_contain_text("call 911 now")
    expect(page.locator("#preview")).to_contain_text("No booking requests or messages yet")
    page.get_by_role("button", name="Leave a message", exact=True).click()
    send(page, "Test Caller", "+12025550101", "Please call me about business hours.", "Morning")
    expect(page.locator("#preview")).to_contain_text("Message taken (simulated)")
    expect(page.locator("#chat")).to_contain_text("Nothing was sent.")
    assert not shop


def test_each_demo_calendar_control_has_a_unique_id(page, shop, request):
    page.goto(BASE_URL + COMMERCIAL + "demo.html")
    expect(page.locator("#tplStatus")).to_contain_text("Templates loaded")
    page.get_by_role("button", name="Book an appointment", exact=True).click()
    send(page, "Test Caller", "Routine inspection", "2026-12-04 10:00", "+12025550101")
    ids = page.get_by_role("button", name="Download .ics file").evaluate_all(
        "(buttons) => buttons.map(button => button.id)"
    )
    assert len(ids) == 2 and all(ids)
    if len(set(ids)) != len(ids):
        if request.config.getoption("--commercial-snapshot"):
            pytest.xfail("PR #7 renders duplicate calendar button IDs")
        pytest.fail("The booking download controls must have unique IDs")
