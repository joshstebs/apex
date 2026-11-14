"""Playwright check for the operations dashboard. Local server only. No provider calls."""
import os
import socket
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "browser-admin-token"


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    port = free_port()
    env = os.environ.copy()
    env.update({
        "APEX_ADMIN_TOKEN": TOKEN,
        "APEX_ENVIRONMENT": "local",
        "APEX_TELEPHONY_PROVIDER": "signalwire",
        "RECEPTIONIST_ENABLED": "false",
        "UPSTASH_REDIS_REST_URL": "",
        "UPSTASH_REDIS_REST_TOKEN": "",
        "ELEVENLABS_API_KEY": "",
        "HUGGINGFACE_API_KEY": "",
        "SIGNALWIRE_API_TOKEN": "",
        "SIGNALWIRE_SIGNING_KEY": "",
    })
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = "http://127.0.0.1:%s" % port
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError(server.stdout.read().decode("utf-8", "replace")[-2000:])
                time.sleep(0.1)
        else:
            raise RuntimeError("dashboard server did not start")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(base + "/operations", wait_until="networkidle")
            page.get_by_role("heading", name="Budget").wait_for()
            page.get_by_role("heading", name="Live call").wait_for()
            page.get_by_role("heading", name="Recent calls").wait_for()
            page.get_by_role("heading", name="Messages").wait_for()
            page.get_by_role("heading", name="Errors").wait_for()
            health = page.locator("#health")
            health.get_by_text("receptionist_enabled").wait_for(timeout=10000)
            assert "false" in health.inner_text()
            assert TOKEN not in page.content()
            page.locator("#token").fill(TOKEN)
            page.locator("#connect").click()
            page.locator("#budget").get_by_text("Spend").wait_for()
            page.locator("#live-call").get_by_text("No live call").wait_for()
            page.locator("#messages").get_by_text("No recent messages").wait_for()
            assert TOKEN not in page.locator("#budget").inner_text()
            page.locator("#disconnect").click()
            page.locator("#error").get_by_text("Token cleared").wait_for()
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
    print("PASS: browser operations dashboard")


if __name__ == "__main__":
    main()
