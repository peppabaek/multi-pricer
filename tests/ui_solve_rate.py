# -*- coding: utf-8 -*-
"""
목표 MtM 을 넣으면 두 화면 모두 금리를 돌려주는가.

마케터가 태핑할 때 묻는 것은 "이 금리면 얼마냐" 가 아니라 "얼마를 받으려면
금리가 몇이냐" 입니다.

화면이 스스로 옳다고 말하게 두지 않습니다: 화면이 채운 쿠폰을 그대로 API 에
넣어 정말 그 MtM 이 나오는지 확인합니다. 숫자를 그럴듯하게 그려놓고 실제로는
다른 금액이 나오는 것이, 여기서 제일 비싼 실수입니다.

    python tests/ui_solve_rate.py
"""
import json
import os
import re
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import ui_mobile_layout as L          # wait_port, PHONE

PORT = 8139
TARGET = 2_000_000.0

fails = []


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


def num(text):
    """'4.318352 %' 또는 '$ 2,000,001' 에서 숫자만."""
    if text is None:
        return None
    m = re.search(r"-?[\d,]+\.?\d*", str(text).replace(",", ""))
    return float(m.group(0)) if m else None


def priced_npv(base, sent, coupon):
    """
    그 쿠폰으로 실제 프라이싱했을 때의 NPV.

    화면이 보낸 요청을 그대로 재사용합니다. 조건을 손으로 다시 적으면 화면과
    다른 거래를 재게 됩니다 - 처음에 그렇게 해서 par 가 4.2319 대 4.2400 으로
    갈렸습니다.
    """
    body = dict(sent)
    body.pop("target_mtm", None)
    body["fixed_coupon_pct"] = coupon
    req = urllib.request.Request(base + "/api/price", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        pr = json.loads(r.read())["data"]["pricing_results"]
        v = pr.get("deal_npv")
        return pr.get("deal_npv_krw") if v is None else v


def check(page, base, where, sel_input, sel_button, sel_out, sel_coupon):
    # 화면이 실제로 무엇을 물었는지 붙잡아 둡니다.
    sent = {}
    page.on("request", lambda r: sent.update(json.loads(r.post_data or "{}"))
            if r.method == "POST" and "/api/solve-rate" in r.url else None)
    page.wait_for_timeout(3000)
    page.fill(sel_input, "2000000")
    page.click(sel_button)
    page.wait_for_timeout(12000)

    out = page.locator(sel_out)
    if not out.count() or out.is_hidden():
        bad(f"{where}: 결과가 표시되지 않음")
        return
    text = out.inner_text()
    if "실패" in text:
        bad(f"{where}: {text[:90]}")
        return
    ok(f"{where}: {text.splitlines()[0][:60]}")

    # 쿠폰 칸에 실제로 들어갔는가. 숫자만 띄우고 끝나면 손으로 옮겨 적어야 합니다.
    filled = num(page.input_value(sel_coupon))
    shown = num(text)
    if filled is None:
        bad(f"{where}: 쿠폰 칸이 비어 있음")
        return
    if shown is None or abs(filled - shown) > 1e-4:
        bad(f"{where}: 표시 {shown} 와 쿠폰 칸 {filled} 이 다름")
        return
    ok(f"{where}: 쿠폰 칸에 {filled} 반영")

    # 그 쿠폰으로 정말 목표 MtM 이 나오는가.
    if not sent:
        bad(f"{where}: /api/solve-rate 요청을 잡지 못함")
        return
    got = priced_npv(base, sent, filled)
    if abs(got - TARGET) > 50.0:
        bad(f"{where}: 쿠폰 {filled} 로 프라이싱하면 {got:,.0f} — 목표 {TARGET:,.0f}")
    else:
        ok(f"{where}: 그 쿠폰으로 실제 {got:,.2f} (목표 {TARGET:,.0f})")


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
            pg = browser.new_page(viewport=L.PHONE, is_mobile=True, has_touch=True)
            pg.goto(base + "/m", wait_until="load", timeout=120000)
            pg.wait_for_timeout(6000)
            check(pg, base, "휴대폰", "#in-target-mtm", "#btn-solve",
                  "#solve-out", "#in-coupon")
            pg.close()

            print("\n--- 데스크톱 ---")
            pg = browser.new_page(viewport={"width": 1680, "height": 1050})
            pg.goto(base + "/?view=pc", wait_until="load", timeout=120000)
            pg.wait_for_timeout(6000)
            check(pg, base, "데스크톱", "#target-mtm", "#btn-solve-rate",
                  "#solve-rate-out", "#fixed-coupon")
            pg.close()
            browser.close()
    finally:
        srv.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: 목표 MtM → 금리 역산 ===")
    sys.exit(main())
