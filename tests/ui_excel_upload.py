# -*- coding: utf-8 -*-
"""
Uploading an Excel term sheet through the browser, the way a trader does it.

The file picker used to reject anything but a PDF before the request was ever made,
so this drives the real control rather than the endpoint: pick the .xlsx, wait for the
popup, and check the amortising schedule is in it.

    python tests/ui_excel_upload.py [--shot out.png] [--live]
"""
import sys, os, json, time, socket, subprocess

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
PORT = 8089

from ui_termsheet_flow import STUB, wait_port          # noqa: E402
from sample_formats import xlsx_bytes, png_bytes       # noqa: E402

NOTIONALS = ("100000000", "80000000", "60000000", "40000000", "20000000")


def main():
    shot = sys.argv[sys.argv.index("--shot") + 1] if "--shot" in sys.argv else None
    live = "--live" in sys.argv

    paths = {}
    for name, blob in (("ts.xlsx", xlsx_bytes()), ("ts.png", png_bytes())):
        paths[name] = os.path.join(HERE, "_" + name)
        with open(paths[name], "wb") as f:
            f.write(blob)

    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
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

            for label, fname in (("Excel", "ts.xlsx"), ("이미지", "ts.png")):
                page = browser.new_page(viewport={"width": 1680, "height": 1050})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                if not live:
                    page.route("**/api/termsheet/extract",
                               lambda route: route.fulfill(
                                   status=200, content_type="application/json",
                                   body=json.dumps(STUB, ensure_ascii=False)))
                page.goto(f"http://127.0.0.1:{PORT}/", wait_until="load", timeout=60000)
                page.wait_for_timeout(3500)

                # The upload zone must not be sitting in its "unavailable" state, which
                # is what a stale dashboard is now told to show.
                if page.locator("#ts-idle.ts-unavailable").count():
                    fails.append(f"{label}: 업로드 영역이 비활성 상태 "
                                 f"({page.locator('#ts-idle').inner_text()[:60]!r})")

                page.set_input_files("#ts-file-input", paths[fname])
                try:
                    page.wait_for_selector("#ts-modal-backdrop", state="visible",
                                           timeout=240000 if live else 20000)
                except Exception:
                    toast = page.locator(".toast, #toast-container").inner_text() \
                        if page.locator(".toast, #toast-container").count() else ""
                    fails.append(f"{label}: 팝업이 열리지 않음 {toast[:120]!r}")
                    page.close()
                    continue
                page.wait_for_timeout(1500)
                ok(f"{label} 업로드 후 팝업 열림")

                rows = page.locator(".ts-sched-table tbody tr")
                if rows.count() != 5:
                    fails.append(f"{label}: 팝업 스케줄 {rows.count()}행 (5행이어야 함)")
                else:
                    flat = page.locator(".ts-sched-table").inner_text().replace(",", "")
                    missing = [n for n in NOTIONALS if n not in flat]
                    if missing:
                        fails.append(f"{label}: 상각 원금 누락 {missing}")
                    else:
                        ok(f"{label} 팝업에 상각 5단계 스케줄 표시")

                chip = page.locator("#ts-redaction").inner_text()
                unredacted = "마스킹 없이" in chip
                if label == "이미지" and live and not unredacted:
                    fails.append(f"이미지인데 마스킹 안내가 없음: {chip!r}")
                elif label == "Excel" and unredacted:
                    fails.append(f"Excel인데 마스킹 없음으로 표시됨: {chip!r}")
                else:
                    ok(f"{label} 처리 표시: {chip!r}")

                if shot:
                    out = shot.replace(".png", f"_{label}.png")
                    page.screenshot(path=out)
                    print(f"  --    스크린샷: {out}")

                if errors:
                    fails.append(f"{label}: JS 오류 {errors[:2]}")
                page.close()
            browser.close()
    finally:
        srv.terminate()
        for pth in paths.values():
            if os.path.exists(pth):
                os.remove(pth)

    for f in fails:
        print(f"  FAIL  {f}")
    print(f"\n  {len(fails)} failed\n")
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: Excel / 이미지 업로드 → 팝업 ===")
    sys.exit(main())
