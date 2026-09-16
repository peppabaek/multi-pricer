# -*- coding: utf-8 -*-
"""
The term sheet path end to end, through the browser: upload, the review popup, and
what pressing 확인 does to the dashboard.

Nothing should reach the form before the trader confirms, and everything should reach
it afterwards - the conventions in the leg fields, the schedule in the boxes pricing
reads, and the priced periods in the table at the foot of the page.

The extract endpoint is stubbed with a canned response, so this exercises the
browser-side path - which is where the schedule was being lost - without spending
an API call or depending on a model being reachable.

    python tests/ui_termsheet_flow.py [--shot out.png] [--live]
"""
import sys, os, re, time, json, socket, subprocess

# The pass/fail lines carry Korean and check marks; a cp949 console would abort on them.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
PORT = 8081

SCHEDULE = "\n".join(
    f"{a}\t{b}\t{n}\t3.65" for a, b, n in [
        ("2026-09-15", "2027-09-15", 100000000),
        ("2027-09-15", "2028-09-15", 80000000),
        ("2028-09-15", "2029-09-15", 60000000),
        ("2029-09-15", "2030-09-15", 40000000),
        ("2030-09-15", "2031-09-15", 20000000),
    ])

STUB = {
    "status": "success",
    "data": {
        "supported": True,
        "demo_fallback": False,
        "doc_sha256": "0" * 64,
        "ticket_draft": {
            "product": "USD", "position": "Pay Fixed",
            "notionalDisplay": "100,000,000", "customTenorInput": "5Y",
            "selectedTenor": "5Y", "effectiveDate": "2026-09-15",
            "maturityDate": "2031-09-15", "coupon": "3.6500", "spreadBp": "0.0",
            "crsSwapType": "Vanilla", "usdFixedCoupon": "3.5000",
            "leg1DayCount": "Act/360", "leg1PaymentFreq": "12M",
            "leg1Convention": "Modified Following", "leg1Stub": "Short in arrears",
            "leg1Adjust": "Adjust", "leg1PayCal": "NYB",
            "leg2DayCount": "Act/360", "leg2PaymentFreq": "12M",
            "leg2Convention": "Modified Following", "leg2Stub": "Short in arrears",
            "leg2Adjust": "Adjust", "leg2Cal": "NYB", "fixDay": -2,
            "rawPasteText": SCHEDULE,
        },
        "inferred_fields": ["leg1_stub_rule", "leg2_stub_rule"],
        "unverified_fields": [],
        "provenance": [{"field": "fixed_coupon_pct", "source": "extracted",
                        "quote": "Fixed Rate:  3.6500%", "note": None}],
        "open_questions": ["Confirm the SOFR observation shift"],
        "warnings": [],
        "cross_validation": None,
        "adjudication": None,
        "redaction": {"counts": {"party": 2, "identifier": 1}, "leaks": []},
    },
}

# What the form should hold once the trader has confirmed, and must NOT hold before.
EXPECTED = {
    "param-day-count": "Act/360", "param-payment-freq": "12M",
    "param-convention": "Modified Following", "param-stub": "Short in arrears",
    "param-adjust": "Adjust", "param-pay-cal": "NYB",
    "leg2-day-count": "Act/360", "leg2-payment-freq": "12M",
    "notional-display": "100,000,000", "custom-tenor-input": "5Y",
    "effective-date": "2026-09-15", "maturity-date": "2031-09-15",
    "fixed-coupon": "3.6500",
}
NOTIONALS = ("100000000", "80000000", "60000000", "40000000", "20000000")

# Replacement char, or a lone '?' pressed against Hangul - the shape encoding damage takes.
MOJIBAKE = re.compile(r"[�]|[?][가-힣]|[가-힣][?]")


def wait_port(port, timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def scan_mojibake(page):
    return sorted(set(m.group(0) for m in MOJIBAKE.finditer(page.locator("body").inner_text())))


def main():
    shot = sys.argv[sys.argv.index("--shot") + 1] if "--shot" in sys.argv else None
    live = "--live" in sys.argv

    from sample_termsheets import pdf
    ts_path = os.path.join(HERE, "_ts_upload.pdf")
    with open(ts_path, "wb") as f:
        f.write(pdf("TS-B"))

    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fails = []

    def ok(msg):
        print(f"  PASS  {msg}")

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
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            if not live:
                page.route("**/api/termsheet/extract",
                           lambda route: route.fulfill(
                               status=200, content_type="application/json",
                               body=json.dumps(STUB, ensure_ascii=False)))

            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(4000)

            baseline = {k: (page.locator("#" + k).input_value()
                            if page.locator("#" + k).count() else None)
                        for k in EXPECTED}

            bad = scan_mojibake(page)
            if bad:
                fails.append(f"초기 화면 글자 깨짐: {bad[:6]}")
            else:
                ok("초기 화면 글자 깨짐 없음")

            # ---- upload -> popup ------------------------------------------------
            page.set_input_files("#ts-file-input", ts_path)
            try:
                page.wait_for_selector("#ts-modal-backdrop", state="visible",
                                       timeout=240000 if live else 20000)
            except Exception:
                fails.append("검토 팝업이 열리지 않음")
                for f in fails:
                    print(f"  FAIL  {f}")
                browser.close()
                return 1
            page.wait_for_timeout(1200)
            ok("업로드 후 검토 팝업 열림")

            rows = page.locator("#ts-groups .ts-row")
            if rows.count() < 15:
                fails.append(f"팝업 거래조건 항목 {rows.count()}개 (15개 이상이어야 함)")
            else:
                ok(f"팝업에 거래조건 {rows.count()}개 항목 표시")

            sched_rows = page.locator(".ts-sched-table tbody tr")
            if sched_rows.count() != 5:
                fails.append(f"팝업 스케줄 {sched_rows.count()}행 (5행이어야 함)")
            else:
                ok("팝업에 스케줄 5개 기간 표시")
                shown = page.locator(".ts-sched-table").inner_text().replace(",", "")
                missing = [n for n in NOTIONALS if n not in shown]
                if missing:
                    fails.append(f"팝업 스케줄 원금 누락: {missing}")
                else:
                    ok("팝업 스케줄에 상각 원금 5단계 표시")

            summary = page.locator("#ts-sched-summary").inner_text()
            if "상각" not in summary:
                fails.append(f"스케줄 요약이 상각을 알리지 않음: {summary!r}")
            else:
                ok(f"스케줄 요약: {summary!r}")

            # Nothing may reach the dashboard before the trader presses 확인.
            leaked = [k for k in EXPECTED
                      if page.locator("#" + k).count()
                      and page.locator("#" + k).input_value() != baseline[k]]
            if page.locator("#rc-paste-input-leg1").input_value().strip():
                leaked.append("rc-paste-input-leg1")
            if leaked:
                fails.append(f"확인 전에 이미 대시보드에 반영됨: {leaked}")
            else:
                ok("확인 전에는 대시보드가 바뀌지 않음")

            bad = scan_mojibake(page)
            if bad:
                fails.append(f"팝업 글자 깨짐: {bad[:8]}")
            else:
                ok("팝업 글자 깨짐 없음")

            if shot:
                page.screenshot(path=shot, full_page=False)
                print(f"  --    스크린샷(팝업): {shot}")

            # ---- confirm -> dashboard -------------------------------------------
            page.click("#ts-confirm")
            page.wait_for_selector("#ts-modal-backdrop", state="hidden", timeout=10000)
            page.wait_for_timeout(3500)
            ok("확인 후 팝업 닫힘")

            wrong = [f"{k}: {page.locator('#' + k).input_value()!r} (기대 {v!r})"
                     for k, v in EXPECTED.items()
                     if page.locator("#" + k).count()
                     and page.locator("#" + k).input_value() != v]
            if wrong:
                fails.append("거래조건 미반영 — " + "; ".join(wrong))
            else:
                ok(f"거래조건 {len(EXPECTED)}개 항목 폼에 반영됨")

            leg1 = page.locator("#rc-paste-input-leg1").input_value()
            lines = [l for l in leg1.splitlines() if l.strip()]
            if len(lines) != 5:
                fails.append(f"Leg1 스케줄 {len(lines)}개 기간 (5개여야 함)")
            else:
                ok(f"Leg1 스케줄 {len(lines)}개 기간 반영됨")
                flat = leg1.replace(",", "")
                missing = [n for n in NOTIONALS if n not in flat]
                if missing:
                    fails.append(f"상각 원금 누락: {missing}")
                else:
                    ok("상각 원금 5단계 모두 반영됨")

            badge = page.locator("#schedule-mode-badge")
            btxt = badge.inner_text() if badge.count() else ""
            if "custom" not in btxt.lower():   # the badge is CSS-uppercased
                fails.append(f"스케줄 모드 배지가 커스텀으로 바뀌지 않음: {btxt!r}")
            else:
                ok(f"스케줄 모드 배지: {btxt!r}")

            # The point of the whole flow: the approved schedule, priced, at the foot
            # of the dashboard.
            body_rows = page.locator("#dual-table-body tr:not(.total-row)")
            if body_rows.count() != 5:
                fails.append(f"하단 스케줄 {body_rows.count()}행 (5행이어야 함)")
            else:
                ok("하단 Dual-Leg 스케줄에 5개 기간 적용됨")
                txt = page.locator("#dual-table-body").inner_text().replace(",", "")
                missing = [n for n in NOTIONALS if n not in txt]
                if missing:
                    fails.append(f"하단 스케줄 원금 누락: {missing}")
                else:
                    ok("하단 스케줄에 상각 원금 5단계 반영됨")

            alias = page.locator("#ticket-alias-input").input_value()
            if MOJIBAKE.search(alias) or "쨌" in alias:
                fails.append(f"티켓 별칭 글자 깨짐: {alias!r}")
            else:
                ok(f"티켓 별칭 정상: {alias!r}")

            bad = scan_mojibake(page)
            if bad:
                fails.append(f"적용 후 글자 깨짐: {bad[:8]}")
            else:
                ok("적용 후 글자 깨짐 없음")

            if shot:
                after = shot.replace(".png", "_applied.png")
                page.screenshot(path=after, full_page=False)
                print(f"  --    스크린샷(적용 후): {after}")

            if errors:
                fails.append(f"JS 오류: {errors[:3]}")
            browser.close()
    finally:
        srv.terminate()
        if os.path.exists(ts_path):
            os.remove(ts_path)

    for f in fails:
        print(f"  FAIL  {f}")
    print(f"\n  {len(fails)} failed\n")
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: Term Sheet 업로드 → 검토 팝업 → 확인 → 대시보드 적용 ===")
    sys.exit(main())
