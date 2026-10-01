# -*- coding: utf-8 -*-
"""
거래조건서에서 읽은 최초 변동금리가 실제로 프라이싱까지 가는가.

개시일이 지난 거래의 첫 변동기간은 이미 고정돼 있습니다. 그 값을 AI 가 읽어도
화면이 요청에 싣지 않으면 서버는 커브에서 추정하고, Murex 와 다시 벌어집니다.

화면이 스스로 옳다고 말하게 두지 않습니다: 화면이 실제로 보낸 요청을 가로채
first_fixing_pct 가 들어 있는지, 그리고 그 값으로 서버가 돌려준 첫 변동행이
"Fixing" 이라고 말하는지 봅니다.

    python tests/ui_first_fixing.py
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

import ui_mobile_layout as L          # wait_port, PHONE

PORT = 8141
fails = []


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


def watch(page, where):
    """스크립트가 깨지면 그 아래는 전부 조용히 안 돌아갑니다."""
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    return errs


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

            # ---------------------------------------------------- 데스크톱
            pg = browser.new_page(viewport={"width": 1680, "height": 1050})
            errs = watch(pg, "데스크톱")
            sent = []
            pg.on("request", lambda r: sent.append(json.loads(r.post_data or "{}"))
                  if r.method == "POST" and r.url.endswith("/api/price") else None)
            pg.goto(base + "/?view=pc", wait_until="load", timeout=120000)
            pg.wait_for_timeout(8000)

            if errs:
                bad(f"데스크톱 스크립트 오류: {errs[0][:140]}")
            else:
                ok("데스크톱 스크립트 오류 없음")

            if not sent:
                bad("데스크톱이 /api/price 를 부르지 않음")
            elif "first_fixing_pct" not in sent[-1]:
                bad("데스크톱 요청에 first_fixing_pct 가 없음 - 티켓 값이 버려짐")
            else:
                ok(f"데스크톱 요청에 first_fixing_pct 포함 (={sent[-1]['first_fixing_pct']})")

            # 과거에 시작한 일정표를 넣으면 추정치라고 표시되는가.
            import datetime
            T = datetime.date.today()
            rows = []
            for i in range(4):
                a = T - datetime.timedelta(days=13) + datetime.timedelta(days=30 * i)
                b = a + datetime.timedelta(days=30)
                rows.append("\t".join([str(a), str(b), str(b), "2500000000"]))
            pg.fill("#rc-paste-input-leg1", "\n".join(rows))
            pg.click("#btn-rc-calc-now")
            pg.wait_for_timeout(9000)

            tags = pg.locator(".rate-src")
            if not tags.count():
                bad("과거에 시작한 기간인데 출처 표시가 없음")
            else:
                first = tags.first
                label = first.inner_text().strip()
                if label != "추정":
                    bad(f"출처 표시가 '추정' 이 아닌 '{label}'")
                else:
                    ok(f"첫 변동행에 '{label}' 표시 ({tags.count()}개)")
                # 배지가 금리 숫자를 가리면 더 나빠집니다.
                cell = first.locator("xpath=..")
                box = cell.bounding_box()
                num_box = cell.locator("strong").bounding_box()
                if box and num_box and (num_box["x"] + num_box["width"]) > (box["x"] + box["width"]) + 1:
                    bad("출처 배지가 금리 숫자를 칸 밖으로 밀어냄")
                else:
                    ok("금리 숫자가 칸 안에 남아 있음")
                if errs:
                    bad(f"스케줄 적용 중 오류: {errs[0][:140]}")

            pg.close()

            # ---------------------------------------------------- 휴대폰
            pg = browser.new_page(viewport=L.PHONE, is_mobile=True, has_touch=True)
            errs = watch(pg, "휴대폰")
            pg.goto(base + "/m", wait_until="load", timeout=120000)
            pg.wait_for_timeout(8000)
            if errs:
                bad(f"휴대폰 스크립트 오류: {errs[0][:140]}")
            else:
                ok("휴대폰 스크립트 오류 없음")
            got = pg.evaluate("() => window.PricingCore.TS_FIELD_KEY.firstFixing")
            if got != "first_fixing_pct":
                bad(f"휴대폰 TS_FIELD_KEY 에 firstFixing 이 없음: {got!r}")
            else:
                ok("휴대폰 TS_FIELD_KEY 에 firstFixing 등록")
            # pricing-core 는 휴대폰 페이지만 싫니다.
            got = pg.evaluate("() => window.PricingCore.overridesFromTicket"
                              "({ firstFixing: '3.5500' }).first_fixing_pct")
            if got != 3.55:
                bad(f"공용 매핑이 firstFixing 을 넘기지 못함: {got!r}")
            else:
                ok("공용 매핑 firstFixing -> first_fixing_pct = 3.55")
            # 빈 칸은 지어내지 않고 빼야 합니다.
            got = pg.evaluate("() => 'first_fixing_pct' in"
                              " window.PricingCore.overridesFromTicket({ firstFixing: '' })")
            if got:
                bad("빈 firstFixing 을 그대로 실음")
            else:
                ok("빈 firstFixing 은 요청에서 빠짐")
            pg.close()
            browser.close()
    finally:
        srv.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: 최초 변동금리 자동 반영 ===")
    sys.exit(main())
