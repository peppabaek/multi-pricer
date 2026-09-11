# -*- coding: utf-8 -*-
"""
UI regression: the stale-data banner must clear when F9 reloads and re-prices.

Drives a real browser against a real server, so it exercises the same path a
trader does rather than asserting on the source.
"""
import sys, os, subprocess, time, socket

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PORT = 8078


def wait_port(port, timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def launch(p):
    try:
        return p.chromium.launch(channel="chromium")
    except Exception:
        return p.chromium.launch()


def main():
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failures = []
    try:
        if not wait_port(PORT):
            print("  FAIL  server did not start")
            return 1

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = launch(p)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            # Drive the browser's clock rather than reaching into app internals, so the
            # app has no idea it is being tested.
            page.clock.install()
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            banner = page.locator("#results-stale-banner")
            badge = page.locator("#staleness-badge")

            page.clock.fast_forward("07:00")   # seven minutes pass
            page.wait_for_timeout(1500)

            stale_text = badge.inner_text()
            if "STALE" not in stale_text.upper():
                failures.append(f"badge did not go stale after 7m: {stale_text!r}")
            if not banner.is_visible():
                failures.append("stale banner did not appear after 7m")

            if not failures:
                print(f"  PASS  banner appears when data ages ({stale_text})")

                page.keyboard.press("F9")
                page.wait_for_timeout(6000)

                after_badge = badge.inner_text()
                if banner.is_visible():
                    failures.append(f"banner still visible after F9 (badge={after_badge!r})")
                elif "LIVE" not in after_badge.upper():
                    failures.append(f"badge not LIVE after F9: {after_badge!r}")
                else:
                    print(f"  PASS  F9 cleared the banner and reset the clock ({after_badge})")

            if errors:
                failures.append(f"page errors: {errors[:3]}")
            browser.close()
    finally:
        srv.terminate()

    for f in failures:
        print(f"  FAIL  {f}")
    print(f"\n  {'0 failed' if not failures else str(len(failures)) + ' failed'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    print("\n=== UI: stale banner clears on F9 ===")
    sys.exit(main())
