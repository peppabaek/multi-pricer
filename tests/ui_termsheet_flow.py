# -*- coding: utf-8 -*-
"""
What the trader actually sees after a term sheet upload: the amortising schedule
landing in the boxes pricing reads from, and no mojibake anywhere on screen.

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
            errors, console = [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text))

            if not live:
                page.route("**/api/termsheet/extract",
                           lambda route: route.fulfill(
                               status=200, content_type="application/json",
                               body=json.dumps(STUB, ensure_ascii=False)))

            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(4000)

            body = page.locator("body").inner_text()
            bad = sorted(set(m.group(0) for m in MOJIBAKE.finditer(body)))
            if bad:
                fails.append(f"초기 화면 글자 깨짐: {bad[:6]}")
            else:
                print("  PASS  초기 화면 글자 깨짐 없음")

            page.set_input_files("#ts-file-input", ts_path)
            try:
                page.wait_for_selector("#ts-review:not([hidden])",
                                       timeout=240000 if live else 20000)
            except Exception:
                fails.append("검토 패널이 나타나지 않음")
                for f in fails:
                    print(f"  FAIL  {f}")
                browser.close()
                return 1
            page.wait_for_timeout(2000)
            print("  PASS  업로드 후 검토 패널 표시됨")

            leg1 = page.locator("#rc-paste-input-leg1").input_value()
            lines = [l for l in leg1.splitlines() if l.strip()]
            if len(lines) != 5:
                fails.append(f"Leg1 스케줄 {len(lines)}개 기간 (5개여야 함)")
            else:
                print(f"  PASS  Leg1 스케줄 {len(lines)}개 기간 반영됨")
                flat = leg1.replace(",", "")
                missing = [n for n in ("100000000", "80000000", "60000000",
                                       "40000000", "20000000") if n not in flat]
                if missing:
                    fails.append(f"상각 원금 누락: {missing}")
                else:
                    print("  PASS  상각 원금 5단계 모두 반영됨")

            # The conventions have to land in the form the trader reads and pricing
            # sends, not only in the review panel.
            EXPECTED = {
                "param-day-count": "Act/360", "param-payment-freq": "12M",
                "param-convention": "Modified Following", "param-stub": "Short in arrears",
                "param-adjust": "Adjust", "param-pay-cal": "NYB",
                "leg2-day-count": "Act/360", "leg2-payment-freq": "12M",
                "notional-display": "100,000,000", "custom-tenor-input": "5Y",
                "effective-date": "2026-09-15", "maturity-date": "2031-09-15",
                "fixed-coupon": "3.6500",
            }
            wrong = []
            for el, want in EXPECTED.items():
                loc = page.locator("#" + el)
                got = loc.input_value() if loc.count() else "<없음>"
                if got != want:
                    wrong.append(f"{el}: {got!r} (기대 {want!r})")
            if wrong:
                fails.append("거래조건 미반영 — " + "; ".join(wrong))
            else:
                print(f"  PASS  거래조건 {len(EXPECTED)}개 항목 폼에 반영됨")

            # Badges are how the trader confirms the schedule is live before F9.
            badge = page.locator("#schedule-mode-badge")
            btxt = badge.inner_text() if badge.count() else ""
            if "custom" not in btxt.lower():   # the badge is CSS-uppercased
                fails.append(f"스케줄 모드 배지가 커스텀으로 바뀌지 않음: {btxt!r}")
            else:
                print(f"  PASS  스케줄 모드 배지: {btxt!r}")
            summary = page.locator("#rc-active-summary")
            if summary.count() and summary.is_visible():
                print(f"  PASS  스케줄 활성 표시: {summary.inner_text()!r}")
            else:
                fails.append("스케줄 활성 표시가 보이지 않음")

            content = page.locator("#paste-schedule-content")
            if content.count() == 0:
                fails.append("스케줄 카드(#paste-schedule-content)를 찾지 못함")
            elif not content.is_visible():
                fails.append("스케줄 카드가 접혀 있어 트레이더가 볼 수 없음")
            else:
                print("  PASS  스케줄 카드 펼쳐짐")

            body2 = page.locator("body").inner_text()
            bad2 = sorted(set(m.group(0) for m in MOJIBAKE.finditer(body2)))
            if bad2:
                fails.append(f"업로드 후 글자 깨짐: {bad2[:8]}")
            else:
                print("  PASS  업로드 후 글자 깨짐 없음")

            alias = page.locator("#ticket-alias-input").input_value()
            if MOJIBAKE.search(alias) or "쨌" in alias:
                fails.append(f"티켓 별칭 글자 깨짐: {alias!r}")
            else:
                print(f"  PASS  티켓 별칭 정상: {alias!r}")

            fields = page.locator(".ts-field").count()
            print(f"  --    검토 필드 {fields}개")

            if shot:
                page.screenshot(path=shot, full_page=False)
                print(f"  --    스크린샷: {shot}")

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
    print("\n=== UI: Term Sheet 업로드 → 스케줄 반영 / 글자 깨짐 ===")
    sys.exit(main())
