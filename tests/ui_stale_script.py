# -*- coding: utf-8 -*-
"""Does the page notice when the browser hands it a stale app.js?"""
import sys, os, time, socket, subprocess
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass
ROOT = r"C:\project\test1"; HERE = os.path.join(ROOT, "tests")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
from ui_termsheet_flow import wait_port
PORT = 8087
BANNER = "최신이 아닙니다"

srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--host",
                        "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
                       cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
fails = []
try:
    wait_port(PORT)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()

        pg = b.new_page()
        pg.goto(f"http://127.0.0.1:{PORT}/", wait_until="load", timeout=60000)
        pg.wait_for_timeout(3000)
        if BANNER in pg.locator("body").inner_text():
            fails.append("최신 스크립트인데 경고 배너가 떴음")
        else:
            print("  PASS  최신 스크립트에는 배너 없음")
        pg.close()

        # A browser holding a pre-stamp app.js: serve one that never sets the marker.
        pg2 = b.new_page()
        pg2.route("**/app.js*", lambda r: r.fulfill(
            status=200, content_type="application/javascript",
            body="/* pretend this is the cached old build */"))
        pg2.goto(f"http://127.0.0.1:{PORT}/", wait_until="load", timeout=60000)
        pg2.wait_for_timeout(2000)
        if BANNER not in pg2.locator("body").inner_text():
            fails.append("낡은 스크립트인데 아무 안내도 없음")
        else:
            print("  PASS  낡은 스크립트를 감지해 새로고침 안내 표시")
        pg2.close()
        b.close()
finally:
    srv.terminate()
for f in fails: print(f"  FAIL  {f}")
print(f"\n  {len(fails)} failed\n")
sys.exit(1 if fails else 0)
