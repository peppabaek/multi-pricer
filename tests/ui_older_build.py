# -*- coding: utf-8 -*-
"""
A dashboard that is one build behind must still work.

The build stamp added to app.js was used, for one commit, to refuse uploads from a
page that did not send it - which caught dashboards that had the review popup and
were working perfectly. This drives that exact page: the current markup with a script
that predates the stamp, uploading an Excel term sheet.

    python tests/ui_older_build.py [--live]
"""
import sys, os, re, json, socket, subprocess

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
PORT = 8091

from ui_termsheet_flow import STUB, wait_port      # noqa: E402
from sample_formats import xlsx_bytes              # noqa: E402

NOTIONALS = ("100000000", "80000000", "60000000", "40000000", "20000000")


def script_without_stamp() -> str:
    """The shipped app.js with the build stamp and its fetch wrapper removed."""
    with open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as f:
        src = f.read()
    src = src.replace('window.__PRICER_BUILD__ = "termsheet-popup";',
                      'window.__PRICER_BUILD_REMOVED__ = 1;', 1)
    # Drop the wrapper that sets the header, leaving fetch untouched.
    src = re.sub(r"\(function stampOwnRequests\(\) \{.*?\}\)\(\);", "", src,
                 count=1, flags=re.S)
    return src


def main():
    live = "--live" in sys.argv   # the model is stubbed either way here
    xl = os.path.join(HERE, "_older.xlsx")
    with open(xl, "wb") as f:
        f.write(xlsx_bytes())

    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.stub_server:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fails = []

    def ok(m):
        print(f"  PASS  {m}")

    try:
        if not wait_port(PORT):
            print("  FAIL  server did not start")
            return 1

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chromium")
            except Exception:
                browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1680, "height": 1050})
            errors, refused = [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("response", lambda r: refused.append((r.url, r.status))
                    if "/api/termsheet/extract" in r.url and r.status >= 400 else None)

            older = script_without_stamp()
            page.route("**/app.js*", lambda route: route.fulfill(
                status=200, content_type="application/javascript", body=older))
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="load", timeout=60000)
            page.wait_for_timeout(3500)

            # Behind, so it may be told - but not made to look switched off.
            if page.locator("#ts-idle.ts-unavailable").count():
                fails.append("한 빌드 뒤처진 페이지가 '분석 비활성'으로 표시됨: "
                             + repr(page.locator("#ts-idle").inner_text()[:80]))
            else:
                ok("뒤처진 빌드여도 업로드 영역이 비활성화되지 않음")

            page.set_input_files("#ts-file-input", xl)
            try:
                page.wait_for_selector("#ts-modal-backdrop", state="visible",
                                       timeout=240000 if live else 20000)
            except Exception:
                fails.append(f"엑셀 업로드에서 팝업이 열리지 않음 (거부된 요청: {refused})")
                browser.close()
                for f in fails:
                    print(f"  FAIL  {f}")
                print(f"\n  {len(fails)} failed\n")
                return 1
            page.wait_for_timeout(1500)
            ok("뒤처진 빌드에서도 엑셀 업로드 → 팝업 열림")

            if refused:
                fails.append(f"업로드가 서버에서 거부됨: {refused}")
            else:
                ok("업로드가 버전 때문에 거부되지 않음")

            rows = page.locator(".ts-sched-table tbody tr")
            if rows.count() != 5:
                fails.append(f"팝업 스케줄 {rows.count()}행 (5행이어야 함)")
            else:
                flat = page.locator(".ts-sched-table").inner_text().replace(",", "")
                missing = [n for n in NOTIONALS if n not in flat]
                if missing:
                    fails.append(f"상각 원금 누락 {missing}")
                else:
                    ok("팝업에 상각 5단계 스케줄 표시")

            if errors:
                fails.append(f"JS 오류 {errors[:2]}")
            browser.close()
    finally:
        srv.terminate()
        if os.path.exists(xl):
            os.remove(xl)

    for f in fails:
        print(f"  FAIL  {f}")
    print(f"\n  {len(fails)} failed\n")
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: 한 빌드 뒤처진 대시보드에서 엑셀 업로드 ===")
    sys.exit(main())
