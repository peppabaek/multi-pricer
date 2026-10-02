# -*- coding: utf-8 -*-
"""
서버가 JSON 이 아닌 것을 돌려줄 때 화면이 무엇을 말하는가.

휴대폰에서 "unexpected token" 과 fetch 오류가 났다는 보고. 두 화면 모두
resp.json() 을 먼저 부르고 resp.ok 는 그 다음에 봤습니다. 무료 플랜이
깨어나는 동안의 502 페이지, 인증이 풀렸을 때의 로그인 화면, 프록시가 끊은
요청은 전부 HTML 이라 거기서 SyntaxError 가 납니다 - 트레이더에게는
"Unexpected token '<'" 만 보이고, 무엇이 잘못됐는지도 다시 눌러야 하는지도
알 수 없습니다.

세 가지를 실제로 서버 대신 돌려주고 화면에 뜨는 글을 봅니다:
HTML 502, HTML 401, 그리고 아예 끊긴 연결.

    python tests/ui_bad_response.py
"""
import json
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

PORT = 8149
fails = []

BAD = {
    "502 HTML": dict(status=502, content_type="text/html",
                     body="<html><head><title>502 Bad Gateway</title></head>"
                          "<body><h1>Application failed to respond</h1></body></html>"),
    "401 HTML": dict(status=401, content_type="text/html",
                     body="<html><body>Sign in</body></html>"),
}


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


def shown(page, selectors, seconds=10):
    """토스트는 잠깐 떴다 사라지므로 계속 들여다본다."""
    seen = []
    for _ in range(seconds * 4):
        for sel in selectors:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                # inner_text 는 사라지는 중인 토스트에서 아이콘만 돌려줄 때가
                # 있습니다. 글자가 실제로 그려지는지는 따로 재 봤습니다.
                t = (loc.first.text_content() or "").strip()
                if t and t not in seen:
                    seen.append(t)
        page.wait_for_timeout(250)
    return " | ".join(seen)


def run_case(browser, base, where, path, viewport, mobile, trigger, readouts):
    for label, resp in list(BAD.items()) + [("연결 끊김", None)]:
        pg = browser.new_page(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + path, wait_until="load", timeout=120000)
        pg.wait_for_timeout(5000)

        if resp is None:
            pg.route("**/api/krw/price", lambda r, *_: r.abort())
            pg.route("**/api/price", lambda r, *_: r.abort())
        else:
            pg.route("**/api/krw/price", lambda r, *_, x=resp: r.fulfill(**x))
            pg.route("**/api/price", lambda r, *_, x=resp: r.fulfill(**x))

        trigger(pg)
        text = shown(pg, readouts)
        if "nexpected token" in text or "SyntaxError" in text:
            bad(f"{where} · {label}: 화면에 파서 오류가 그대로 — {text[:90]}")
        elif not text:
            bad(f"{where} · {label}: 아무 말도 하지 않음")
        else:
            ok(f"{where} · {label}: \"{text.splitlines()[0][:70]}\"")

        parser = [e for e in errs if "nexpected token" in e or "SyntaxError" in e]
        if parser:
            bad(f"{where} · {label}: 콘솔에 파서 오류 — {parser[0][:90]}")
        pg.close()


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

            print("\n--- 휴대폰 /m ---")
            run_case(browser, base, "휴대폰", "/m", L.PHONE, True,
                     lambda pg: pg.click("#btn-price"),
                     ["#notice", "#toast"])

            print("\n--- 데스크톱 ---")
            run_case(browser, base, "데스크톱", "/?view=pc",
                     {"width": 1680, "height": 1050}, False,
                     lambda pg: pg.click("#btn-calc-price"),
                     ["#toast-container .toast", "#calc-status"])
            browser.close()
    finally:
        srv.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: JSON 이 아닌 응답을 받았을 때 ===")
    sys.exit(main())
