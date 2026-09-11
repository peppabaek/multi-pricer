# -*- coding: utf-8 -*-
import sys, os, subprocess, time, socket

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PORT = 8079


def wait_port(port, timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


srv = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
     "--port", str(PORT), "--log-level", "warning"],
    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    wait_port(PORT)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chromium")
        except Exception:
            b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 1000})
        reqs, errs, logs = [], [], []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.on("response", lambda r: reqs.append((r.status, r.url.split("/api/")[-1]))
                if "/api/" in r.url else None)

        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(6000)

        print("API calls:")
        for s, u in reqs:
            print(f"  {s}  {u[:80]}")
        print("\npage errors:", errs[:5] or "none")
        print("console:", [l for l in logs if "error" in l.lower()][:5] or "none")
        print("\nbadge:", page.locator("#staleness-badge").inner_text())
        print("calc status:", page.locator("#calc-status").inner_text())
        print("quote rows:", page.locator("#quote-table-body tr").count())
        print("par rate:", page.locator("#res-par-rate").inner_text())
        b.close()
finally:
    srv.terminate()
