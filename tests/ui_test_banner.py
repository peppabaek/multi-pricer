# -*- coding: utf-8 -*-
"""
시험 운영이라는 것이 화면에 드러나는가.

두 가지를 봅니다. 헤더의 TEST 표기는 늘 보여야 하고, 최초 접속 고지는 한 번
뜬 뒤 "오늘은 다시 보지 않기" 를 고르면 그날은 안 떠야 합니다.

고지가 떠 있는 동안에도 프라이서는 그대로 돌아야 합니다 - 고지는 알리는
것이지 막는 것이 아닙니다.

    python tests/ui_test_banner.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import ui_mobile_layout as L

PORT = 8179
fails = []


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


def check(browser, base, where, path, viewport, mobile):
    ctx = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
    pg = ctx.new_page()
    errs = []
    sent = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    # 리스너는 goto 전에 붙입니다. 뒤에 붙이면 최초 프라이싱을 놓치고
    # "멈췄다" 고 잘못 읽습니다.
    pg.on("request", lambda r: sent.append(r.url)
          if r.method == "POST" and "price" in r.url else None)
    pg.goto(base + path, wait_until="load", timeout=120000)
    pg.wait_for_timeout(5000)

    if errs:
        bad(f"{where}: 스크립트 오류 {errs[0][:120]}")

    tag = pg.locator(".test-tag").first
    if tag.count() == 0 or not tag.is_visible():
        bad(f"{where}: 헤더에 TEST 표기가 보이지 않음")
    else:
        box = tag.bounding_box()
        vp = pg.viewport_size
        if not box or box["x"] < 0 or box["x"] + box["width"] > vp["width"] + 1:
            bad(f"{where}: TEST 표기가 화면 밖 {box}")
        else:
            ok(f"{where}: 헤더 TEST 표기 (x {box['x']:.0f}, 글자 {tag.inner_text().strip()!r})")

    modal = pg.locator("#test-notice")
    if modal.count() == 0 or modal.is_hidden():
        bad(f"{where}: 최초 접속인데 고지가 뜨지 않음")
        ctx.close()
        return
    ok(f"{where}: 최초 접속에 고지가 뜸")

    # 고지가 떠 있어도 프라이서는 돌아야 합니다 - 알리는 것이지 막는 것이
    # 아닙니다. 고지가 아직 떠 있는 상태에서 확인합니다.
    pg.wait_for_timeout(5000)
    if modal.is_hidden():
        bad(f"{where}: 확인을 누르기도 전에 고지가 닫힘")
    if not sent:
        bad(f"{where}: 고지가 떠 있는 동안 프라이싱이 멈춤")
    else:
        ok(f"{where}: 고지 중에도 프라이싱 {len(sent)}건")

    pg.check("#test-notice-skip")
    pg.click("#test-notice-ok")
    pg.wait_for_timeout(1000)
    if modal.is_visible():
        bad(f"{where}: 확인을 눌러도 닫히지 않음")
    else:
        ok(f"{where}: 확인하면 닫힘")

    # 같은 브라우저(같은 저장소)로 다시 들어오면 그날은 안 떠야 합니다.
    pg2 = ctx.new_page()
    pg2.goto(base + path, wait_until="load", timeout=120000)
    pg2.wait_for_timeout(5000)
    again = pg2.locator("#test-notice")
    if again.count() and again.is_visible():
        bad(f"{where}: '오늘은 다시 보지 않기' 를 골랐는데 또 뜸")
    else:
        ok(f"{where}: 다시 들어와도 그날은 뜨지 않음")
    if pg2.locator(".test-tag").first.is_hidden():
        bad(f"{where}: 고지를 끈 뒤 TEST 표기까지 사라짐")
    else:
        ok(f"{where}: 고지를 꺼도 TEST 표기는 남음")
    ctx.close()


def main():
    import subprocess
    env = dict(os.environ, PRICER_NO_LOCAL_FEED="1")
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{PORT}"
    try:
        if not L.wait_port(PORT):
            print("  FAIL  서버가 뜨지 않음")
            return 1
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chromium")
            except Exception:
                browser = p.chromium.launch()
            print("\n--- 데스크톱 ---")
            check(browser, base, "데스크톱", "/?view=pc",
                  {"width": 1680, "height": 1050}, False)
            print("\n--- 휴대폰 /m ---")
            check(browser, base, "휴대폰", "/m", L.PHONE, True)
            browser.close()
    finally:
        srv.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: 시험 운영 고지와 표기 ===")
    sys.exit(main())
