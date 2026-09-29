# -*- coding: utf-8 -*-
"""
휴대폰에서 쓸 수 있는가.

데스크톱 그리드는 1240px 에서 2열로 접히고 거기서 멈춥니다. 390px 화면에서는
시장 패널과 거래 패널이 195px 씩 나눠 가져, 호가표의 Bid/Ask/Mid 가 화면 밖으로
밀리고 헤더의 배지·탭·단축키 안내가 서로 겹쳤습니다. 문서 폭이 1018px 였습니다.

여기서 재는 것은 "예쁜가" 가 아니라 세 가지입니다.
  - 페이지가 가로로 넘치지 않는가 (문서 폭 == 뷰포트 폭)
  - 넘친 요소에 가로 스크롤 조상이 있는가. 없으면 영영 못 본다.
  - 손가락으로 프라이싱을 실행할 수 있는가. 레이아웃만 고치고 F9 를 못 누르면
    휴대폰에서는 읽기 전용 화면이 된다.

그리고 데스크톱이 그대로인지도 같이 봅니다 — 모바일 CSS 는 마지막에 로드되므로
범위를 잘못 잡으면 트레이더의 주 화면을 조용히 망가뜨립니다.

    python tests/ui_mobile_layout.py
"""
import os
import socket
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
PORT = 8129
PHONE = {"width": 390, "height": 844}       # iPhone 14/15
DESKTOP = {"width": 1680, "height": 1050}
# /m 이 생긴 뒤 좁은 화면에서 / 는 휴대폰 전용 화면으로 넘어갑니다. 여기서 재는
# 것은 그 화면이 아니라 PC 페이지 자체의 반응형 동작이므로, 넘어가지 않도록
# PC 를 명시합니다(전용 화면은 ui_mobile_page.py 가 봅니다).
PC_VIEW = "/?view=pc"

fails = []


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


def wait_port(port, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.4)
    return False


# 넘치는 요소마다 가로로 스크롤되는 조상을 찾는다. 있으면 의도된 것(호가표, 통화
# 탭 띠)이고, 없으면 트레이더가 영영 볼 수 없는 부분이다.
CLIPPED = """() => {
  const vw = document.documentElement.clientWidth, out = [];
  document.querySelectorAll('body *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (!(r.width > 0 && r.right > vw + 1)) return;
    // 움직이는 중인 요소는 제외합니다. 토스트는 translateX(100%) 에서 미끄러져
    // 들어오므로 0.2초 동안 화면 밖에 있습니다 - 그 순간을 재면 레이아웃이
    // 깨진 것처럼 보이지만, 멈추면 제자리입니다.
    if (el.getAnimations && el.getAnimations().some(function (an) {
            return an.playState === 'running'; })) return;
    let a = el.parentElement;
    while (a && a !== document.body) {
      const ov = getComputedStyle(a).overflowX;
      if ((ov === 'auto' || ov === 'scroll') && a.scrollWidth > a.clientWidth + 1) return;
      a = a.parentElement;
    }
    out.push(((el.id || el.className || el.tagName) + '').slice(0, 40)
             + ' -> ' + Math.round(r.right));
  });
  return out;
}"""


# 겹침은 넘침이 아니다. 폭 검사는 전부 통과하는데도, 줄바꿈된 툴바 버튼들이
# "Swap Cash Flow Schedule" 제목 위에 그대로 인쇄된 적이 있다. 화면 밖으로
# 나간 게 아니라 서로 포개진 것이라 폭으로는 잡히지 않았다.
#
# 그래서 눌러야 할 것들의 중심점을 실제로 히트테스트한다 - 그 자리에서 잡히는
# 요소가 자기 자신(또는 자손)이 아니면, 트레이더 손가락에도 안 잡힌다.
COVERED = """() => {
  const vh = window.innerHeight, out = [];
  const bar = document.getElementById('mobile-actions');
  const barTop = bar && bar.offsetParent !== null
      ? bar.getBoundingClientRect().top : Infinity;
  document.querySelectorAll('button, h1, h2, h3, .tab-btn, .btn-tb').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return;
    if (r.top < 0 || r.bottom > vh) return;          // 화면 안에 온전히 있는 것만
    if (bar && bar.contains(el)) return;
    if (r.bottom > barTop) return;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const hit = document.elementFromPoint(cx, cy);
    if (!hit) return;
    if (el.contains(hit) || hit.contains(el)) return;
    // 실행 막대가 위에 있는 건 정상이다 - 막대는 떠 있으라고 만든 것이고,
    // 그 아래로 스크롤하면 나온다(아래 별도 검사). 그 외의 겹침만 보고한다.
    if (bar && (bar === hit || bar.contains(hit))) return;
    out.push(((el.id || el.className || el.tagName) + '').slice(0, 34)
             + ' <- ' + ((hit.id || hit.className || hit.tagName) + '').slice(0, 34));
  });
  return out;
}"""

def settle(page, timeout_ms=6000):
    """
    측정 전에 화면이 멎기를 기다린다.

    토스트는 translateX(100%) 에서 미끄러져 들어와 몇 초 뒤 사라집니다. 그 사이를
    재면 화면 밖에 있는 것이 레이아웃 결함으로 잡힙니다 - 실제로 320px 검사가
    간헐적으로 실패했습니다. 애니메이션 제외만으로는 경계 순간이 남습니다.
    """
    waited = 0
    while waited < timeout_ms:
        if page.locator(".toast").count() == 0:
            return
        page.wait_for_timeout(250)
        waited += 250


def col_count(page):
    css = page.evaluate(
        "() => getComputedStyle(document.querySelector('.terminal-grid')).gridTemplateColumns")
    return len(css.split())


def check_phone(page, base):
    page.goto(base + PC_VIEW, wait_until="load", timeout=120000)
    page.wait_for_timeout(4000)

    vw, doc = page.evaluate(
        "() => [document.documentElement.clientWidth, document.documentElement.scrollWidth]")
    if doc > vw + 1:
        bad(f"페이지가 가로로 넘침 — 뷰포트 {vw}px / 문서 {doc}px")
    else:
        ok(f"가로 넘침 없음 — 뷰포트 {vw}px == 문서 {doc}px")

    settle(page)
    clipped = page.evaluate(CLIPPED)
    if clipped:
        bad(f"스크롤할 수 없는 곳으로 잘린 요소 {len(clipped)}건: {clipped[:5]}")
    else:
        ok("잘려서 못 보는 요소 없음")

    n = col_count(page)
    if n != 1:
        bad(f"휴대폰에서 {n}열 — 한 열이어야 함")
    else:
        ok("한 열로 접힘")

    # 호가표는 지워지는 게 아니라 가로로 스크롤되어야 한다.
    tbl = page.locator("#quote-table")
    if not tbl.count():
        bad("호가표가 사라짐")
    else:
        sw, cw = page.evaluate(
            "() => { const w = document.querySelector('#quote-table').closest('.table-wrapper');"
            "return [w.scrollWidth, w.clientWidth]; }")
        if sw > cw + 1:
            ok(f"호가표가 가로 스크롤됨 ({cw}px 안에 {sw}px)")
        else:
            ok("호가표가 폭 안에 들어옴")

    # 패널을 하나씩 화면에 올려가며 겹친 것이 없는지 본다.
    covered = []
    for sel in (".panel-trade", ".panel-results", ".panel-market",
                ".panel-paste-schedule", ".panel-waterfall"):
        page.evaluate(f"() => {{ const e = document.querySelector('{sel}');"
                      f" if (e) e.scrollIntoView(); }}")
        page.wait_for_timeout(400)
        covered += [f"{sel}: {c}" for c in page.evaluate(COVERED)]
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(300)
    if covered:
        bad(f"다른 요소에 가려진 버튼/제목 {len(covered)}건: {covered[:4]}")
    else:
        ok("겹쳐서 가려진 버튼·제목 없음")

    bar = page.locator("#mobile-actions")
    if not bar.count() or not bar.is_visible():
        bad("휴대폰에서 실행 막대가 없음 — 프라이싱을 실행할 방법이 없다")
        return
    ok("실행 막대 표시됨")

    # 손가락이 닿는 크기인가. 44px 는 애플/구글이 함께 쓰는 최소 터치 타깃이다.
    small = []
    for bid in ("m-btn-reload", "m-btn-price", "m-btn-oneshot"):
        box = page.locator("#" + bid).bounding_box()
        if not box or box["height"] < 40:
            small.append(f"{bid}={box and round(box['height'])}px")
    if small:
        bad(f"손가락에 너무 작은 버튼: {small}")
    else:
        ok("세 버튼 모두 터치 가능한 높이(>=40px)")

    # 막대가 화면 안에 떠 있어야 한다. 아래로 스크롤해도 따라와야 의미가 있다.
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(600)
    box = page.locator("#m-btn-oneshot").bounding_box()
    if not box or box["y"] > PHONE["height"] or box["y"] + box["height"] < 0:
        bad("아래로 스크롤하면 실행 막대가 화면을 벗어남")
    else:
        ok("스크롤해도 실행 막대가 화면에 남음")

    # 떠 있는 막대는 끝까지 스크롤했을 때 마지막 줄을 영구히 가리면 안 된다.
    # body 의 아래 여백이 그 역할을 한다.
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(600)
    gap = page.evaluate(
        "() => { const p = document.querySelector('.panel-waterfall');"
        " const b = document.getElementById('mobile-actions');"
        " return b.getBoundingClientRect().top - p.getBoundingClientRect().bottom; }")
    if gap < 0:
        bad(f"끝까지 스크롤해도 막대가 마지막 패널을 {abs(round(gap))}px 가림")
    else:
        ok(f"막대 아래로 내용이 숨지 않음 (여백 {round(gap)}px)")

    # 레이아웃만 맞고 버튼이 아무것도 하지 않으면 읽기 전용 화면이다.
    before = page.locator("#res-par-rate").inner_text()
    page.locator("#m-btn-oneshot").click()
    page.wait_for_timeout(9000)
    after = page.locator("#res-par-rate").inner_text()
    status = page.locator("#calc-status").inner_text().strip().lower()
    if "error" in status or "fail" in status:
        bad(f"막대로 프라이싱 실패: {status!r}")
    elif not after.strip() or after.strip().startswith("--"):
        bad(f"막대를 눌렀는데 결과가 비어 있음: {before!r} -> {after!r}")
    else:
        ok(f"막대로 프라이싱 실행됨: {after.strip()} (상태 {status!r})")


def check_desktop(page, base):
    page.goto(base + PC_VIEW, wait_until="load", timeout=120000)
    page.wait_for_timeout(4000)

    vw, doc = page.evaluate(
        "() => [document.documentElement.clientWidth, document.documentElement.scrollWidth]")
    if doc > vw + 1:
        bad(f"데스크톱이 가로로 넘침 — {vw}px / {doc}px")
    else:
        ok(f"데스크톱 가로 넘침 없음 ({vw}px)")

    n = col_count(page)
    if n != 3:
        bad(f"데스크톱이 {n}열 — 모바일 CSS 가 주 화면까지 건드림")
    else:
        ok("데스크톱은 그대로 3열")

    bar = page.locator("#mobile-actions")
    if bar.count() and bar.is_visible():
        bad("데스크톱에 실행 막대가 보임 — 단축키와 기존 버튼이 이미 있다")
    else:
        ok("데스크톱에서는 실행 막대 숨김")

    if not page.locator(".shortcut-hints").is_visible():
        bad("데스크톱에서 단축키 안내가 사라짐")
    else:
        ok("데스크톱 단축키 안내 유지")


# res-dv01 안의 "/ bp" 라벨은 이 작업 이전부터 1680px 풀데스크톱에서도 한결같이
# 잘려 있다. 반응형 문제가 아니므로 여기서 막지 않는다 — 다만 새로 생기는 것을
# 놓치지 않도록 이름으로만 제외한다.
KNOWN = ("unit -> ",)


def sweep(browser, base):
    """휴대폰부터 데스크톱까지, 중간 폭에서 깨지는 곳이 없는가.

    820px 하나만 맞추면 그 바로 위의 태블릿 가로보기가 조용히 깨진다.
    경계 양쪽(820/821)을 같이 본다.
    """
    for w, h, label in [(320, 568, "iPhone SE"), (390, 844, "iPhone 14"),
                        (430, 932, "Pro Max"), (768, 1024, "iPad 세로"),
                        (820, 1180, "경계 아래"), (821, 1180, "경계 위"),
                        (1024, 768, "iPad 가로"), (1280, 800, "노트북"),
                        (1680, 1050, "데스크")]:
        pg = browser.new_page(viewport={"width": w, "height": h})
        pg.goto(base + PC_VIEW, wait_until="load", timeout=120000)
        pg.wait_for_timeout(2500)
        settle(pg)
        vw, doc = pg.evaluate(
            "() => [document.documentElement.clientWidth, document.documentElement.scrollWidth]")
        clipped = [c for c in pg.evaluate(CLIPPED)
                   if not any(c.startswith(k) for k in KNOWN)]
        pg.close()
        if doc > vw + 1:
            bad(f"{w}px({label}) 가로로 넘침 — 문서 {doc}px")
        elif clipped:
            bad(f"{w}px({label}) 잘린 요소 {len(clipped)}건: {clipped[:3]}")
        else:
            ok(f"{w}px ({label})")


def check_modal(page, base):
    """Term Sheet 팝업은 휴대폰에서 전체 화면이어야 한다.

    데스크톱용 중앙 카드 크기 그대로면 390px 안에서 거래조건 표와 확인 버튼이
    동시에 들어가지 않는다 — 검토하고 누르라는 창인데.
    """
    page.goto(base + PC_VIEW, wait_until="load", timeout=120000)
    page.wait_for_timeout(3000)
    page.evaluate("() => { document.getElementById('ts-modal-backdrop').style.display = 'flex'; }")
    page.wait_for_timeout(400)
    box = page.locator("#ts-modal-backdrop .ts-modal").bounding_box()
    if not box:
        bad("팝업을 표시하지 못함")
        return
    if box["width"] < PHONE["width"] * 0.95:
        bad(f"팝업이 화면 폭을 안 채움: {round(box['width'])}px / {PHONE['width']}px")
    elif box["x"] + box["width"] > PHONE["width"] + 1:
        bad(f"팝업이 화면 밖으로 나감: right={round(box['x'] + box['width'])}px")
    else:
        ok(f"팝업이 전체 화면으로 열림 ({round(box['width'])}x{round(box['height'])})")


def main():
    env = dict(os.environ, PRICER_NO_LOCAL_FEED="1")
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{PORT}"
    try:
        if not wait_port(PORT):
            print("  FAIL  서버가 뜨지 않음")
            return 1
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chromium")
            except Exception:
                browser = p.chromium.launch()

            print("\n--- 휴대폰 390x844 ---")
            pg = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True,
                                  device_scale_factor=3)
            check_phone(pg, base)
            pg.close()

            print("\n--- Term Sheet 팝업 (휴대폰) ---")
            pg = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True)
            check_modal(pg, base)
            pg.close()

            print("\n--- 폭 훑기 320px → 1680px ---")
            sweep(browser, base)

            print("\n--- 데스크톱 1680x1050 ---")
            pg = browser.new_page(viewport=DESKTOP)
            check_desktop(pg, base)
            pg.close()
            browser.close()
    finally:
        srv.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: 모바일 레이아웃 ===")
    sys.exit(main())
