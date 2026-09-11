# -*- coding: utf-8 -*-
"""Render the dashboard headlessly and capture it, reporting any console errors."""
import sys, os, subprocess, time, socket

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dashboard.png")
PORT = 8077


def wait_port(port, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


srv = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "server.app:app",
     "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    if not wait_port(PORT):
        print("server did not start"); sys.exit(1)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # The separate headless-shell build isn't installed; use the full Chromium.
        try:
            browser = p.chromium.launch(channel="chromium")
        except Exception:
            browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1680, "height": 1050})
        errors, console = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}")
                if m.type in ("error", "warning") else None)

        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)
        page.screenshot(path=OUT, full_page=False)
        print(f"screenshot -> {OUT}")

        # Is the term sheet busy row hidden with nothing uploaded?
        busy = page.locator("#ts-busy")
        print("ts-busy visible (should be False):", busy.is_visible())
        print("ts-idle visible (should be True):", page.locator("#ts-idle").is_visible())
        print("upload label:", page.locator("#ts-idle strong").inner_text())

        for label, sel in (("header", ".app-header"), ("market", ".panel-market"),
                           ("trade", ".panel-trade"), ("results", ".panel-results")):
            box = page.locator(sel).first.bounding_box()
            print(f"{label:8s} box:", {k: round(v) for k, v in box.items()} if box else None)

        print("page errors:", errors or "none")
        print("console errors/warnings:", console[:8] or "none")
        browser.close()
finally:
    srv.terminate()
