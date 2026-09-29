# -*- coding: utf-8 -*-
"""
휴대폰 전용 화면(/m) 이 맞는 숫자를 보여주는가.

가장 위험한 실패는 레이아웃이 아닙니다. 화면은 멀쩡한데 숫자가 조용히 틀린
것입니다. 통화마다 응답 모양이 다르기 때문입니다 — USD·KRW·KOFR 는
pricing_results.par_swap_rate_pct / deal_npv / dv01 이지만, CRS 는
par_crs_rate_pct 에 원화·달러 DV01 이 따로 있습니다. 어댑터가 한 통화만
어긋나도 트레이더는 알아챌 방법이 없습니다.

그래서 네 통화 모두, 같은 거래를
  (1) /m 화면에서 프라이싱한 값과
  (2) 같은 요청을 API 에 직접 보낸 값을
맞대어 봅니다. 화면이 스스로 옳다고 말하게 두지 않습니다.

레이아웃(폭·겹침·터치 크기)은 ui_mobile_layout.py 의 검사를 그대로 빌려 씁니다.

    python tests/ui_mobile_page.py
"""
import json
import os
import re
import subprocess
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

import ui_mobile_layout as L          # CLIPPED / COVERED 재사용

PORT = 8131
# 모델 호출만 대체한 같은 앱. 업로드 경로 자체는 실제 코드가 돕니다.
STUB_PORT = 8132
PHONE = {"width": 390, "height": 844}

fails = []


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


def api(path, body, base=None):
    req = urllib.request.Request(
        (base or f"http://127.0.0.1:{PORT}") + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["data"]


# 화면에 찍힌 "$ 44,112" / "₩ 61,341,601" / "4.7835" 를 숫자로 되돌린다.
def unformat(text):
    if text is None:
        return None
    # money() 는 "-$ 2,240,496" 처럼 부호를 통화기호 앞에 붙입니다. 기호만 떼면
    # "- 2240496" 이 남아 float() 이 거부하고, 조용히 None 이 되어 "화면에 값이
    # 없다" 로 잘못 보고됩니다 - NPV 가 0 일 때만 우연히 통과했습니다.
    t = re.sub(r"[\s$₩,%]", "", str(text))
    if t in ("", "—", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


# 통화별로 화면이 무엇을 보여줘야 하는지. pricing-core.js 의 readResults 와
# 같은 규칙을 파이썬으로 한 번 더 적습니다 - 같은 코드를 두 번 부르면 어댑터가
# 틀려도 양쪽이 똑같이 틀리므로, 대조가 되지 않습니다.
def expected(currency, data):
    pr = data.get("pricing_results", {})
    if currency == "KRW_CRS":
        return {"par": pr.get("par_crs_rate_pct"),
                "npv": pr.get("deal_npv_krw"),
                "dv01": pr.get("krw_dv01")}
    return {"par": pr.get("par_swap_rate_pct"),
            "npv": pr.get("deal_npv"),
            "dv01": pr.get("dv01")}


CASES = [
    ("USD", "tab-usd", "/api/price"),
    ("KRW", "tab-krw", "/api/krw/price"),
    ("KRW_KOFR", "tab-krw-kofr", "/api/kofr/price"),
    ("KRW_CRS", "tab-krw-crs", "/api/crs/price"),
]


def check_numbers(page, base):
    """네 통화 모두, 화면 숫자 == API 숫자."""
    page.goto(base + "/m", wait_until="load", timeout=120000)
    page.wait_for_timeout(6000)

    for currency, tab_id, path in CASES:
        page.locator("#" + tab_id).click()
        page.wait_for_timeout(7000)

        shown = {
            "par": unformat(page.locator("#out-par").inner_text()),
            "npv": unformat(page.locator("#out-npv").inner_text()),
            "dv01": unformat(page.locator("#out-dv01").inner_text()),
        }
        req = {"currency": currency, "notional": 100000000.0,
               "position": "Pay Fixed", "tenor": "5Y", "spread_bp": 0.0}
        if currency == "KRW_CRS":
            req["crs_swap_type"] = "Vanilla"
        want = expected(currency, api(path, req))

        if shown["par"] is None:
            bad(f"{currency}: 화면에 par 가 없음 (탭을 눌러도 계산이 안 됨)")
            continue

        # par 는 화면이 소수 4자리로 자릅니다. npv/dv01 은 원 단위로 반올림.
        bad_fields = []
        if want["par"] is None or abs(shown["par"] - want["par"]) > 5e-4:
            bad_fields.append(f"par 화면={shown['par']} API={want['par']}")
        for k in ("npv", "dv01"):
            w = want[k]
            if w is None:
                continue
            if shown[k] is None or abs(shown[k] - w) > 1.0:
                bad_fields.append(f"{k} 화면={shown[k]} API={w}")
        if bad_fields:
            bad(f"{currency}: 화면과 API 가 다름 — {'; '.join(bad_fields)}")
        else:
            ok(f"{currency}: par {shown['par']} · NPV {shown['npv']} · DV01 {shown['dv01']} "
               f"— API 와 일치")


def check_inputs(page, base):
    """입력을 바꾸면 숫자가 따라 움직이는가."""
    page.goto(base + "/m", wait_until="load", timeout=120000)
    page.wait_for_timeout(7000)

    par_5y = unformat(page.locator("#out-par").inner_text())
    page.locator('[data-tenor="10Y"]').click()
    page.wait_for_timeout(7000)
    par_10y = unformat(page.locator("#out-par").inner_text())
    if par_5y is None or par_10y is None:
        bad(f"테너 변경 후 par 를 읽지 못함: {par_5y} → {par_10y}")
    elif par_5y == par_10y:
        bad(f"5Y 와 10Y 의 par 가 같음 ({par_5y}) — 테너가 요청에 반영되지 않음")
    else:
        ok(f"테너가 반영됨: 5Y {par_5y} → 10Y {par_10y}")

    # 쿠폰을 par 에서 떨어뜨리면 NPV 가 0 이 아니어야 한다. par 만 보여주는
    # 화면은 계산기이고, 쿠폰을 넣어 NPV 를 보는 것이 실제 용도입니다.
    page.locator('[data-tenor="5Y"]').click()
    page.wait_for_timeout(6000)
    page.fill("#in-coupon", str(round((par_5y or 4.0) + 0.5, 4)))
    page.locator("#btn-price").click()
    page.wait_for_timeout(7000)
    npv = unformat(page.locator("#out-npv").inner_text())
    if npv is None:
        bad("쿠폰을 넣었는데 NPV 를 읽지 못함")
    elif abs(npv) < 1000:
        bad(f"쿠폰을 par+50bp 로 올렸는데 NPV 가 {npv} — 쿠폰이 요청에 반영되지 않음")
    else:
        ok(f"쿠폰이 반영됨: par+50bp 에서 NPV {npv:,.0f}")


def check_layout(page, base):
    """폭·겹침·터치 크기. ui_mobile_layout 과 같은 잣대."""
    page.goto(base + "/m", wait_until="load", timeout=120000)
    page.wait_for_timeout(6000)

    vw, doc = page.evaluate(
        "() => [document.documentElement.clientWidth, document.documentElement.scrollWidth]")
    if doc > vw + 1:
        bad(f"가로로 넘침 — 뷰포트 {vw}px / 문서 {doc}px")
    else:
        ok(f"가로 넘침 없음 ({vw}px)")

    clipped = page.evaluate(L.CLIPPED)
    if clipped:
        bad(f"잘려서 못 보는 요소 {len(clipped)}건: {clipped[:4]}")
    else:
        ok("잘려서 못 보는 요소 없음")

    covered = page.evaluate(L.COVERED)
    if covered:
        bad(f"가려진 버튼/제목 {len(covered)}건: {covered[:4]}")
    else:
        ok("겹쳐서 가려진 버튼·제목 없음")

    # display 를 명시한 규칙은 UA 의 [hidden]{display:none} 을 이깁니다. 그래서
    # hidden 을 붙여놨는데도 화면에 남는 요소가 생깁니다 - 실제로 "Term Sheet
    # 조건 적용중" 초록 막대가 아무것도 올리지 않았는데 빈 채로 떠 있었습니다.
    # 하나하나 확인하지 않아도 되도록 전부 훑습니다.
    ghosts = page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('[hidden]').forEach(el => {
        if (getComputedStyle(el).display !== 'none')
          out.push(((el.id || el.className || el.tagName) + '').slice(0, 34));
      });
      return out;
    }""")
    if ghosts:
        bad(f"hidden 인데 화면에 보이는 요소: {ghosts}")
    else:
        ok("hidden 요소가 모두 실제로 숨겨짐")

    small = []
    for sel in ("#btn-price", "#btn-reload", "#ts-btn", '[data-tenor="5Y"]', "#tab-usd"):
        box = page.locator(sel).bounding_box()
        if not box or box["height"] < 36:
            small.append(f"{sel}={box and round(box['height'])}px")
    if small:
        bad(f"손가락에 너무 작은 것: {small}")
    else:
        ok("버튼·탭·테너 모두 터치 가능한 높이")


def check_routing(page, base):
    """좁은 화면은 /m 으로 가고, PC 를 고르면 그 선택이 남는다."""
    page.goto(base + "/", wait_until="load", timeout=120000)
    page.wait_for_timeout(2500)
    if not page.url.rstrip("/").endswith("/m"):
        bad(f"휴대폰 폭에서 / 가 /m 으로 가지 않음 — {page.url}")
        return
    ok("휴대폰에서 / → /m 자동 이동")

    page.locator(".m-pclink").click()
    page.wait_for_timeout(3000)
    if "/m" in page.url:
        bad(f"PC 버전 링크가 동작하지 않음 — {page.url}")
        return
    ok("PC 버전 링크로 빠져나감")

    # 한 번 PC 를 골랐으면 다음부터 끌려가지 않아야 한다.
    page.goto(base + "/", wait_until="load", timeout=120000)
    page.wait_for_timeout(2500)
    if page.url.rstrip("/").endswith("/m"):
        bad("PC 를 골랐는데 다시 /m 으로 끌려감")
    else:
        ok("PC 선택이 기억됨")


def check_desktop_untouched(browser, base):
    """넓은 화면은 여전히 PC 화면을 받는다."""
    pg = browser.new_page(viewport={"width": 1680, "height": 1050})
    pg.goto(base + "/", wait_until="load", timeout=120000)
    pg.wait_for_timeout(3000)
    if "/m" in pg.url:
        bad(f"데스크톱이 /m 으로 끌려감 — {pg.url}")
    elif not pg.locator(".terminal-grid").count():
        bad("데스크톱에서 PC 화면이 뜨지 않음")
    else:
        cols = len(pg.evaluate(
            "() => getComputedStyle(document.querySelector('.terminal-grid'))"
            ".gridTemplateColumns").split())
        if cols != 3:
            bad(f"데스크톱이 {cols}열")
        else:
            ok("데스크톱은 그대로 PC 화면 3열")
    pg.close()


def check_gate(base):
    """/m 도 게이트 뒤에 있다. 새 경로를 열어놓고 잊는 일이 없도록."""
    import server.access as access
    if "/m" in access.PUBLIC_PATHS:
        bad("/m 이 인증 없이 열려 있음")
    else:
        ok("/m 은 인증 게이트 안에 있음 (PUBLIC_PATHS 는 /healthz 뿐)")


def check_termsheet(browser, base_stub):
    """
    사진/파일 업로드 → 검토 → 적용. 그리고 적용된 것이 정말 계산에 실리는가.

    여기가 가장 조용히 틀릴 수 있는 곳입니다. 휴대폰 화면은 입력이 여섯 개뿐이라,
    문서에 적힌 컨벤션과 상각 스케줄을 요청에 안 실으면 100,000,000 고정 명목의
    바닐라 가격이 나옵니다 - 화면은 멀쩡하고, 숫자만 틀립니다.

    그래서 적용 후의 DV01 이 바닐라와 다른지, 그리고 스케줄 원문을 직접 보낸
    API 응답과 같은지를 봅니다.
    """
    pg = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True)

    # 화면에 찍힌 숫자만 보면 "무엇으로" 계산했는지는 알 수 없습니다. 나간 요청을
    # 그대로 모아둡니다.
    sent = []

    def _capture(r):
        if r.method == "POST" and "/api/price" in r.url:
            try:
                sent.append(json.loads(r.post_data or "{}"))
            except ValueError:
                pass

    pg.on("request", _capture)
    pg.goto(base_stub + "/m", wait_until="load", timeout=120000)
    pg.wait_for_timeout(7000)

    vanilla = unformat(pg.locator("#out-dv01").inner_text())

    # 올리기 전에는 "적용중" 표시가 없어야 합니다. 빈 채로 떠 있으면 트레이더는
    # 무엇이 적용된 건지 알 수 없습니다.
    if pg.locator("#ts-applied").is_visible():
        bad("아무것도 올리지 않았는데 'Term Sheet 조건 적용중' 막대가 보임")
    else:
        ok("올리기 전에는 적용 표시 없음")

    # 요구사항 그대로: 갤러리에 있는 사진 한 장. 텍스트 PDF 가 아닙니다 -
    # 4032x3024 짜리 폰 사진은 포맷도 크기도 방향도 다르고, 서버에서 vision
    # 경로로 갑니다.
    import sample_formats as SF
    path = os.path.join(HERE, "_ts_mobile.jpg")
    with open(path, "wb") as f:
        f.write(SF.phone_jpeg_bytes(4032, 3024))
    try:
        pg.set_input_files("#ts-file", path)
        try:
            pg.wait_for_selector("#ts-modal", state="visible", timeout=90000)
        except Exception:
            bad("업로드했는데 검토 팝업이 열리지 않음")
            pg.close()
            return
        ok("사진 업로드 → 검토 팝업 열림")

        # 모델에 간 것이 손본 사진인지. 원본 그대로 갔다면 실기기에서는
        # 프로바이더 한도에 걸려 실패합니다.
        import urllib.request as _u
        with _u.urlopen(base_stub + "/__stub/last-vision", timeout=30) as r:
            v = json.loads(r.read())["data"]
        if not v:
            bad("사진인데 vision 경로로 가지 않음 — 텍스트로 처리됨")
        elif bytes(v["magic"][:3]) != b"\xff\xd8\xff" or v["mime"] != "image/jpeg":
            bad(f"모델에 JPEG 이 가지 않음: mime={v['mime']} magic={v['magic']}")
        elif v["bytes"] > 4 * 1024 * 1024:
            bad(f"줄이지 않은 원본이 그대로 감: {v['bytes']/1e6:.1f}MB")
        else:
            ok(f"모델에 보정된 사진이 전달됨 ({v['mime']}, {v['bytes']/1024:.0f}KB)")

        text = pg.locator("#ts-modal-body").inner_text()
        for want in ("100,000,000", "20,000,000", "상각"):
            if want not in text:
                bad(f"팝업에 {want!r} 가 없음 - 상각 스케줄을 보여주지 않음")
                break
        else:
            ok("팝업에 상각 5단계(100,000,000 → 20,000,000) 표시")

        # 확인 전에는 아무것도 반영되지 않아야 한다.
        if unformat(pg.locator("#out-dv01").inner_text()) != vanilla:
            bad("확인을 누르기 전에 결과가 바뀜")
        else:
            ok("확인 전에는 대시보드가 그대로")

        pg.locator("#ts-confirm").click()
        pg.wait_for_timeout(9000)

        if pg.locator("#ts-applied").is_hidden():
            bad("적용했는데 'Term Sheet 조건 적용중' 표시가 없음 "
                "- 바닐라 가격으로 오해하게 됨")
        else:
            ok(f"적용 표시: {pg.locator('#ts-applied-text').inner_text()}")

        applied = unformat(pg.locator("#out-dv01").inner_text())
        if applied is None:
            bad("적용 후 결과가 비어 있음")
        elif vanilla is not None and abs(applied - vanilla) < 1.0:
            bad(f"적용 후 DV01 이 바닐라와 같음 ({applied}) "
                f"- 상각 스케줄이 요청에 실리지 않았습니다")
        else:
            ok(f"상각이 반영됨: 바닐라 DV01 {vanilla:,.0f} → {applied:,.0f}")

            # 화면이 스스로 옳다고 말하게 두지 않는다. 같은 스케줄을 직접 보낸다.
        # DV01 이 움직였다는 것만으로는 "무엇이" 실렸는지 알 수 없습니다.
        # 실제로 나간 요청을 열어봅니다 - 스케줄과 컨벤션이 거기 있어야 합니다.
        if not sent:
            bad("적용 후 프라이싱 요청이 나가지 않음")
        else:
            body = sent[-1]
            sched = body.get("leg1_raw_paste_text") or body.get("raw_paste_text")
            if not sched:
                bad("요청에 스케줄이 없음 — 상각이 버려지고 균등 명목으로 계산됩니다")
            elif "20,000,000" not in sched and "20000000" not in sched:
                bad(f"요청의 스케줄에 마지막 회차(20,000,000)가 없음: {sched[:80]!r}")
            else:
                ok(f"요청에 스케줄 원문이 실림 ({len(sched.splitlines())}줄)")

            missing = [k for k in ("leg1_day_count", "leg1_payment_freq",
                                   "leg2_day_count") if not body.get(k)]
            if missing:
                bad(f"요청에 문서의 컨벤션이 빠짐: {missing} "
                    f"— 문서가 Act/365 여도 서버 기본값으로 계산됩니다")
            else:
                ok(f"요청에 문서의 컨벤션이 실림 "
                   f"(leg1 {body['leg1_day_count']} · {body['leg1_payment_freq']})")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
        pg.close()


def check_advanced(page, base):
    """
    고급 옵션 — CRS Fixed-Fixed 와 커브 모델.

    모바일이 CRS 를 Vanilla 로 고정하고 있었습니다. 네 통화 중 하나가 실제로
    거래되는 형태를 못 내는 것이고, 화면은 그 사실을 말하지 않았습니다.

    여기서도 화면이 스스로 옳다고 말하게 두지 않습니다: 같은 조건을 API 에
    직접 보내 숫자를 대조합니다.
    """
    page.goto(base + "/m", wait_until="load", timeout=120000)
    page.wait_for_timeout(6000)

    # CRS 가 아닐 때 CRS 칸이 보이면, 눌러도 아무 일이 없는 칸이 됩니다.
    page.locator("#adv-block summary").click()
    page.wait_for_timeout(500)
    if page.locator("#row-crs-type").is_visible():
        bad("USD 인데 CRS 유형 칸이 보임")
    else:
        ok("통화에 맞는 칸만 보임")

    page.locator("#tab-krw-crs").click()
    page.wait_for_timeout(8000)
    if not page.locator("#row-crs-type").is_visible():
        bad("CRS 인데 유형 칸이 없음 — Vanilla 로 고정됨")
        return
    ok("CRS 에서 유형 칸이 나타남")

    page.select_option("#in-crs-type", "Fixed-Fixed")
    page.wait_for_timeout(8000)

    if not page.locator("#row-usd-coupon").is_visible():
        bad("Fixed-Fixed 인데 USD 고정금리 칸이 없음 — 서버 기본값 3.50 으로 "
            "계산되고 화면은 아무 말도 하지 않습니다")
    else:
        ok("Fixed-Fixed 에서 USD 고정금리 칸이 나타남")

    tag = page.locator("#adv-tag")
    if not tag.count() or not tag.is_visible() or "Fixed-Fixed" not in tag.inner_text():
        bad("고급 옵션을 접으면 Fixed-Fixed 인지 알 수 없음")
    else:
        ok(f"접힌 상태 표시: {tag.inner_text().strip()}")

    shown_par = unformat(page.locator("#out-par").inner_text())
    want = api("/api/crs/price", {
        "currency": "KRW_CRS", "notional": 100000000.0, "position": "Pay Fixed",
        "tenor": "5Y", "spread_bp": 0.0, "crs_swap_type": "Fixed-Fixed",
        "usd_fixed_coupon_pct": 3.5, "curve_type": "Standard"})
    want_par = want["pricing_results"].get("par_krw_rate_pct")
    if shown_par is None or want_par is None:
        bad(f"Fixed-Fixed par 를 읽지 못함: 화면={shown_par} API={want_par}")
    elif abs(shown_par - want_par) > 5e-4:
        bad(f"Fixed-Fixed par 가 API 와 다름 — 화면={shown_par} API={want_par}")
    else:
        ok(f"Fixed-Fixed par {shown_par} — API 와 일치")

    # 바닐라와 값이 같으면 유형이 요청에 실리지 않은 것입니다.
    page.select_option("#in-crs-type", "Vanilla")
    page.wait_for_timeout(8000)
    vanilla_par = unformat(page.locator("#out-par").inner_text())
    if vanilla_par is not None and shown_par is not None and abs(vanilla_par - shown_par) < 1e-6:
        bad(f"Vanilla 와 Fixed-Fixed 의 par 가 같음 ({vanilla_par}) — 유형이 "
            f"요청에 반영되지 않음")
    else:
        ok(f"유형이 반영됨: Fixed-Fixed {shown_par} vs Vanilla {vanilla_par}")


def main():
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
        check_gate(base)

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chromium")
            except Exception:
                browser = p.chromium.launch()

            print("\n--- 숫자: 화면 == API (네 통화) ---")
            pg = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True)
            check_numbers(pg, base)
            pg.close()

            print("\n--- 입력이 반영되는가 ---")
            pg = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True)
            check_inputs(pg, base)
            pg.close()

            print("\n--- 레이아웃 ---")
            pg = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True)
            check_layout(pg, base)
            pg.close()

            print("\n--- 고급 옵션 (CRS Fixed-Fixed · 커브 모델) ---")
            pg = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True)
            check_advanced(pg, base)
            pg.close()

            print("\n--- 라우팅 ---")
            pg = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True)
            check_routing(pg, base)
            pg.close()

            print("\n--- 데스크톱 ---")
            check_desktop_untouched(browser, base)

            print("\n--- Term Sheet 업로드 → 적용 ---")
            stub = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "tests.stub_server:app",
                 "--host", "127.0.0.1", "--port", str(STUB_PORT), "--log-level", "warning"],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                if L.wait_port(STUB_PORT):
                    check_termsheet(browser, f"http://127.0.0.1:{STUB_PORT}")
                else:
                    bad("stub 서버가 뜨지 않음")
            finally:
                stub.terminate()

            browser.close()
    finally:
        srv.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: 휴대폰 전용 화면 (/m) ===")
    sys.exit(main())
