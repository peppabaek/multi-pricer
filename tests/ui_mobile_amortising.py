# -*- coding: utf-8 -*-
"""
상각 스케줄이 휴대폰에서도 프라이싱되는가.

데스크톱에서는 되는데 /m 에서는 안 된다는 보고. AI 호출 없이 재현하려고
/api/termsheet/extract 응답을 가로채 실제 거래조건서(IRS-Pay-CD-260918)의
24행짜리 상각 스케줄을 돌려주고, 두 화면의 실제 UI 경로를 그대로 태웁니다.

화면이 스스로 옳다고 말하게 두지 않습니다: 화면이 보낸 요청과 받은 응답을
직접 붙잡아, 스케줄이 요청에 실렸는지와 프라이싱이 그 행 수로 돌아왔는지를
봅니다.

    python tests/ui_mobile_amortising.py
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

import ui_mobile_layout as L          # wait_port, PHONE

PORT = 8143
ROWS = [
    ("2026-09-18", "2026-10-18", 2_500_000_000), ("2026-10-18", "2026-10-19", 138_904_000),
    ("2026-10-18", "2026-11-18", 2_361_096_000), ("2026-11-18", "2026-12-18", 2_222_208_000),
    ("2026-12-18", "2027-01-18", 2_083_320_000), ("2027-01-18", "2027-02-18", 1_944_432_000),
    ("2027-02-18", "2027-03-18", 1_805_544_000), ("2027-03-18", "2027-04-18", 1_666_656_000),
    ("2027-04-18", "2027-04-19", 138_888_000), ("2027-04-18", "2027-05-18", 1_527_768_000),
    ("2027-05-18", "2027-06-18", 1_388_880_000), ("2027-06-18", "2027-07-18", 1_249_992_000),
    ("2027-07-18", "2027-07-20", 138_888_000), ("2027-07-18", "2027-08-18", 1_111_104_000),
    ("2027-08-18", "2027-09-18", 972_216_000), ("2027-09-18", "2027-09-20", 138_888_000),
    ("2027-09-18", "2027-10-18", 833_328_000), ("2027-10-18", "2027-11-18", 694_440_000),
    ("2027-11-18", "2027-12-18", 555_552_000), ("2027-12-18", "2027-12-20", 138_888_000),
    ("2027-12-18", "2028-01-18", 416_664_000), ("2028-01-18", "2028-02-18", 277_776_000),
    ("2028-02-18", "2028-03-18", 138_888_000), ("2028-03-18", "2028-03-20", 138_888_000),
]
fails = []


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


REAL = os.environ.get("REAL_TS_JSON")


def extract_payload():
    if REAL:
        with io.open(REAL, encoding="utf-8") as f:
            return json.load(f)

    from server.termsheet import (ExtractedTrade, SchedulePeriod, to_ticket_draft,
                                  schedule_preview)
    t = ExtractedTrade(
        supported=True, currency="KRW", position="Pay Fixed", notional=2_500_000_000.0,
        effective_date="2026-09-18", maturity_date="2028-03-20", tenor="18M",
        fixed_coupon_pct=None, leg1_day_count="Act/365", leg1_payment_freq="1M",
        leg2_day_count="Act/365", leg2_payment_freq="1M", leg1_calendar="SEB",
        leg1_custom_schedule=[SchedulePeriod(start_date=a, end_date=b, notional=float(n))
                              for a, b, n in ROWS])
    d = to_ticket_draft(t)
    return {"status": "success", "data": {
        "supported": True, "ticket_draft": d["draft"],
        "inferred_fields": d["inferred_fields"],
        "schedule_preview": schedule_preview(d["draft"]),
        "open_questions": [], "provenance": [], "warnings": [],
        "doc_sha256": "t" * 64, "demo_fallback": False}}


def data_lines(raw):
    """기간 행만. 모델이 머리글을 붙여 오면 빼고 셉니다."""
    lines = [x for x in (raw or "").splitlines() if x.strip()]
    if lines and not lines[0][:4].isdigit():
        lines = lines[1:]
    return lines


def expected_rows():
    return len(data_lines(extract_payload()["data"]["ticket_draft"].get("rawPasteText")))


def drive(page, base, where, upload_sel, confirm_sel, price_url_part):
    """거래조건서를 올리고 확인을 누른 뒤, 나간 요청과 들어온 응답을 붙잡는다."""
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    sent, got = {}, {}

    def on_req(r):
        if r.method == "POST" and price_url_part in r.url:
            try:
                sent.clear()
                sent.update(json.loads(r.post_data or "{}"))
            except Exception:
                pass

    def on_resp(r):
        if price_url_part in r.url and r.request.method == "POST":
            try:
                got.clear()
                got.update(r.json())
            except Exception:
                pass

    page.on("request", on_req)
    page.on("response", on_resp)
    page.route("**/api/termsheet/extract",
               lambda route: route.fulfill(status=200,
                                           content_type="application/json",
                                           body=json.dumps(extract_payload())))
    page.wait_for_timeout(4000)

    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    page.set_input_files(upload_sel, {"name": "termsheet.png",
                                      "mimeType": "image/png", "buffer": png})
    page.wait_for_timeout(5000)
    if page.locator(confirm_sel).count() == 0 or page.locator(confirm_sel).is_hidden():
        bad(f"{where}: 검토 팝업이 뜨지 않음")
        return None, None, errs
    page.click(confirm_sel)
    page.wait_for_timeout(12000)
    return sent, got, errs


def check(where, sent, got, errs):
    if sent is None:
        return
    if errs:
        bad(f"{where}: 스크립트 오류 {errs[0][:140]}")
    if not sent:
        bad(f"{where}: 프라이싱 요청을 보내지 않음")
        return
    want = expected_rows()
    raw = sent.get("leg1_raw_paste_text") or sent.get("raw_paste_text") or ""
    n = len(data_lines(raw))
    if n != want:
        bad(f"{where}: 요청에 실린 스케줄이 {n}행 (초안은 {want}행)")
    else:
        ok(f"{where}: 요청에 {n}행 스케줄 포함")

    if not got:
        bad(f"{where}: 프라이싱 응답을 받지 못함")
        return
    data = got.get("data") or {}
    pr = (data.get("pricing_results") or {})
    rows = ((data.get("schedules") or {}).get("leg1_fixed") or [])
    if len(rows) < 2:
        bad(f"{where}: 프라이싱 스케줄이 {len(rows)}행 — 스케줄이 적용되지 않음")
    else:
        ok(f"{where}: 프라이싱이 {len(rows)}행으로 돌아옴")
    par = pr.get("par_swap_rate_pct")
    if not par:
        bad(f"{where}: par 가 비어 있음 — {json.dumps(got)[:200]}")
    else:
        ok(f"{where}: par {par}")
    # 상각이 반영됐는가. 전액으로 계산하면 명목이 전부 25억입니다.
    notionals = {round(r.get("notional", 0)) for r in rows}
    if len(notionals) <= 1:
        bad(f"{where}: 명목이 한 가지뿐 — 상각이 반영되지 않음 {notionals}")
    else:
        ok(f"{where}: 명목이 {len(notionals)}가지로 상각 반영됨")


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
            pg = browser.new_page(viewport={"width": 1680, "height": 1050})
            pg.goto(base + "/?view=pc", wait_until="load", timeout=120000)
            check("데스크톱", *drive(pg, base, "데스크톱", "#ts-file-input",
                                  "#ts-confirm", "/api/krw/price"))
            pg.close()

            print("\n--- 휴대폰 /m ---")
            pg = browser.new_page(viewport=L.PHONE, is_mobile=True, has_touch=True)
            pg.goto(base + "/m", wait_until="load", timeout=120000)
            check("휴대폰", *drive(pg, base, "휴대폰", "#ts-file",
                                 "#ts-confirm", "/api/krw/price"))
            pg.close()
            browser.close()
    finally:
        srv.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: 상각 스케줄 프라이싱 (데스크톱 vs 휴대폰) ===")
    sys.exit(main())
