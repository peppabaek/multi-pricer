# -*- coding: utf-8 -*-
"""
휴대폰 거래조건서 검토 팝업에서 확인 버튼에 손이 닿는가.

상각 스왑은 휴대폰에서 안 된다는 보고. 추출도 프라이싱도 양쪽이 똑같이
도는 것을 확인했으니 남은 것은 화면입니다.

검토 팝업은 읽어 들인 항목을 전부 세로로 쌓습니다. 바닐라 스왑은 몇 줄이라
확인 버튼이 바로 보이지만, 상각 스케줄이 붙으면 그만큼 길어집니다. 버튼이
화면 밖으로 밀리고 그 영역이 스크롤되지 않으면 트레이더는 누를 방법이
없습니다 - 화면은 멀쩡히 떠 있고 아무 오류도 나지 않습니다.

Playwright 의 click 은 알아서 스크롤해 주므로 그것만으로는 안 잡힙니다.
버튼이 뷰포트 안에 있는지, 그 좌표를 실제로 집었을 때 버튼이 잡히는지,
그리고 길이가 넘칠 때 스크롤이 되는지를 따로 봅니다.

    python tests/ui_mobile_ts_reach.py
"""
import io
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
import ui_mobile_amortising as A

PORT = 8145
fails = []


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


def open_review(page, base, payload):
    page.route("**/api/termsheet/extract",
               lambda route: route.fulfill(status=200,
                                           content_type="application/json",
                                           body=json.dumps(payload)))
    page.goto(base + "/m", wait_until="load", timeout=120000)
    page.wait_for_timeout(4000)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    page.set_input_files("#ts-file", {"name": "ts.png", "mimeType": "image/png",
                                      "buffer": png})
    page.wait_for_timeout(4000)


def probe(page, label):
    """버튼이 보이는가, 그 자리를 집으면 버튼이 잡히는가."""
    btn = page.locator("#ts-confirm")
    if btn.count() == 0 or btn.is_hidden():
        bad(f"{label}: 확인 버튼이 없음")
        return
    vp = page.viewport_size
    box = btn.bounding_box()
    if box is None:
        bad(f"{label}: 확인 버튼에 좌표가 없음")
        return

    within = 0 <= box["y"] and box["y"] + box["height"] <= vp["height"]
    if not within:
        bad(f"{label}: 확인 버튼이 화면 밖 "
            f"(y {box['y']:.0f}~{box['y'] + box['height']:.0f}, 화면 높이 {vp['height']})")
    else:
        ok(f"{label}: 확인 버튼이 화면 안 (y {box['y']:.0f})")

    # 좌표를 실제로 집어 본다. 다른 것이 위에 덮고 있으면 여기서 드러납니다.
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    if 0 <= cy <= vp["height"]:
        hit = page.evaluate(
            "([x, y]) => { const e = document.elementFromPoint(x, y);"
            " return e ? (e.id || e.className || e.tagName) : null; }", [cx, cy])
        if hit != "ts-confirm" and not page.evaluate(
                "([x, y]) => { const e = document.elementFromPoint(x, y);"
                " return !!(e && e.closest('#ts-confirm')); }", [cx, cy]):
            bad(f"{label}: 확인 버튼 자리를 집으면 {hit!r} 가 잡힘")
        else:
            ok(f"{label}: 확인 버튼이 그 자리에서 잡힘")

    # 넘치면 스크롤로 닿을 수 있어야 합니다.
    reach = page.evaluate(
        "() => { const b = document.getElementById('ts-confirm'); if (!b) return null;"
        " let n = b.parentElement, scrollable = false;"
        " while (n && n !== document.body) {"
        "   const s = getComputedStyle(n);"
        "   if ((s.overflowY === 'auto' || s.overflowY === 'scroll')"
        "       && n.scrollHeight > n.clientHeight + 1) { scrollable = true; break; }"
        "   n = n.parentElement; }"
        " const m = document.getElementById('ts-modal');"
        " return { scrollable,"
        "          modalOverflows: m ? m.scrollHeight > window.innerHeight + 1 : false,"
        "          pageScrolls: document.documentElement.scrollHeight"
        "                       > window.innerHeight + 1 }; }")
    if reach and not within and not (reach["scrollable"] or reach["pageScrolls"]):
        bad(f"{label}: 화면 밖인데 스크롤도 되지 않음 {reach}")
    elif reach:
        ok(f"{label}: 스크롤 상태 {reach}")


def main():
    import subprocess
    env = dict(os.environ, PRICER_NO_LOCAL_FEED="1")
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{PORT}"

    long_ts = A.extract_payload()
    short = json.loads(json.dumps(long_ts))
    short["data"]["ticket_draft"]["rawPasteText"] = ""
    short["data"]["schedule_preview"] = []

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
            for label, payload, vp in (
                    ("바닐라(스케줄 없음)", short, L.PHONE),
                    ("상각 스케줄", long_ts, L.PHONE),
                    ("상각 · iPhone SE", long_ts, {"width": 320, "height": 568})):
                pg = browser.new_page(viewport=vp, is_mobile=True, has_touch=True)
                open_review(pg, base, payload)
                probe(pg, label)
                pg.close()
            browser.close()
    finally:
        srv.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: 휴대폰 거래조건서 검토 팝업 도달성 ===")
    sys.exit(main())
