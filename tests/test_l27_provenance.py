# -*- coding: utf-8 -*-
"""
L27 이 숫자가 어디서 왔는가.

배포본이 기준호가로 계산한 5Y par 는 4.2400, 데스크 실시간은 4.7845 였습니다.
54bp, 100M 기준 약 24억 원 차이입니다. 트레이더가 그 둘을 구분하지 못하면
프라이서가 아니라 함정입니다.

여기서 막는 것은 세 가지입니다.

  - 피드가 끊겼는데도 스냅샷이 "LSEG Workspace (Tradeweb Composite =TWEB)" 을
    출처로 보고하던 문제. 그 문자열이 그대로 메신저 회신문에 실려, 하드코딩된
    기준호가가 LSEG Tradeweb 호가로 카운터파티에게 갔습니다.
  - 복사문이 출처를 모를 때 'LSEG Live' 를 기본값으로 쓰던 문제. 모르면
    실시간이라고 주장한 셈입니다.
  - 결과 패널의 경고가 '나이' 기준이라, 타임스탬프가 매번 새로 찍히는 기준호가
    에서는 영원히 뜨지 않던 문제.
"""
import io
import os
import sys

from harness import case, run_all

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def js():
    with io.open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as f:
        return f.read()


def snapshot_of(feed, live):
    """연결 상태를 강제로 바꿔 스냅샷을 받아온다."""
    saved = {}
    for attr in ("is_lseg_live_connected", "is_connected", "_is_live_connected"):
        if hasattr(feed, attr):
            saved[attr] = getattr(feed, attr)
            setattr(feed, attr, live)
    if not saved:
        raise AssertionError(f"{type(feed).__name__} 의 연결 플래그를 찾지 못함")
    try:
        return feed.get_snapshot()
    finally:
        for attr, value in saved.items():
            setattr(feed, attr, value)


@case("L27-1", "피드가 끊기면 출처가 실시간이라고 말하지 않는다")
def t_1():
    from server.tradition_feed import tradition_feed
    from server.crs_feed import crs_feed
    from server.krw_feed import krw_feed
    from server.kofr_feed import kofr_feed

    for name, feed in (("USD", tradition_feed), ("CRS", crs_feed),
                       ("KRW", krw_feed), ("KOFR", kofr_feed)):
        src = str(snapshot_of(feed, False).get("source") or "")
        if not src:
            raise AssertionError(f"{name}: 출처가 비어 있음")
        # 끊긴 상태에서 브로커·벤더 이름만 달랑 내보내면, 그 문자열이 그대로
        # RFQ 회신문에 "LSEG Workspace 기준" 으로 찍힙니다.
        if "LSEG" in src and "Baseline" not in src and "비실시간" not in src:
            raise AssertionError(
                f"{name}: 미연결인데 출처가 실시간을 주장 — {src!r}")


@case("L27-2", "연결되면 실제 출처를 그대로 말한다")
def t_2():
    # 반대 방향도 막습니다. 늘 "Baseline" 이라고 하면 안전하지만 쓸모가 없습니다.
    from server.tradition_feed import tradition_feed
    src = str(snapshot_of(tradition_feed, True).get("source") or "")
    if "LSEG" not in src:
        raise AssertionError(f"연결됐는데 실시간 출처를 말하지 않음: {src!r}")
    if "Baseline" in src or "비실시간" in src:
        raise AssertionError(f"연결됐는데 기준호가라고 표시: {src!r}")


@case("L27-3", "복사문이 출처를 모를 때 실시간이라고 주장하지 않는다")
def t_3():
    # 주석에 옛 동작을 적어두므로 문자열만 찾으면 안 됩니다 - 실제로 그 값을
    # 기본값으로 쓰는 코드 모양을 봅니다.
    import re
    src = js()
    bad = re.findall(r"\|\|\s*['\"]LSEG Live['\"]", src)
    if bad:
        raise AssertionError(
            f"복사문이 'LSEG Live' 를 기본값으로 씀 ({len(bad)}곳) — "
            f"모르면 실시간이라고 주장합니다")


@case("L27-4", "비실시간이면 복사문에 그 사실이 적힌다")
def t_4():
    src = js()
    i = src.find("function copySwapQuoteToClipboard")
    if i < 0:
        raise AssertionError("복사 함수를 찾지 못함")
    body = src[i:i + 4000]
    if "resultProvenance()" not in body:
        raise AssertionError("복사문이 출처 판정을 쓰지 않음")
    if "비실시간" not in body:
        raise AssertionError("비실시간일 때 복사문에 아무 표시가 없음")
    if "realtime" not in body:
        raise AssertionError("실시간 여부로 분기하지 않음")


@case("L27-5", "비실시간 복사는 한 번 묻는다")
def t_5():
    src = js()
    i = src.find("function copySwapQuoteToClipboard")
    body = src[i:i + 4000]
    j = body.find("clipboard.writeText")
    if j < 0:
        raise AssertionError("클립보드 쓰기를 찾지 못함")
    if "confirm(" not in body[:j]:
        raise AssertionError("확인 없이 바로 복사됨 — 실수로 나갈 수 있습니다")


@case("L27-6", "결과 패널이 나이가 아니라 출처를 보여준다")
def t_6():
    # 기존 배너는 '나이' 기준이라, 스냅샷마다 타임스탬프가 새로 찍히는 기준호가
    # 에서는 절대 뜨지 않았습니다. 그래서 출처 배지를 따로 둡니다.
    with io.open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    if 'id="result-source-badge"' not in html:
        raise AssertionError("결과 패널에 출처 배지가 없음")

    src = js()
    if "function resultProvenance" not in src:
        raise AssertionError("출처 판정 함수가 없음")
    if "paintResultProvenance" not in src:
        raise AssertionError("배지를 그리는 곳이 없음")
    # 비실시간이면 숫자가 살아 있는 값처럼 보이면 안 됩니다.
    with io.open(os.path.join(ROOT, "static", "styles.css"), encoding="utf-8") as f:
        css = f.read()
    if ".panel-results.not-live" not in css:
        raise AssertionError("비실시간일 때 결과를 구분하는 스타일이 없음")


@case("L27-7", "휴대폰 화면도 출처를 숫자 옆에 적는다")
def t_7():
    with io.open(os.path.join(ROOT, "static", "m.js"), encoding="utf-8") as f:
        m = io.StringIO(f.read()).getvalue()
    i = m.find("function paintResults")
    if i < 0:
        raise AssertionError("모바일 결과 렌더링을 찾지 못함")
    body = m[i:i + 3000]
    if "snap.source" not in body:
        raise AssertionError("모바일이 출처를 표시하지 않음 — 헤더 배지는 "
                             "스크롤하면 사라집니다")


@case("L27-8", "끝에서 끝까지: 미연결 스냅샷이 프라이싱 응답까지 그대로 전달된다")
def t_8():
    # 화면이 아무리 잘 그려도, 응답에 근거가 없으면 표시할 것이 없습니다.
    from fastapi.testclient import TestClient
    from server.app import app
    from server.tradition_feed import tradition_feed

    saved = tradition_feed.is_lseg_live_connected
    tradition_feed.is_lseg_live_connected = False
    try:
        client = TestClient(app)
        r = client.post("/api/price", json={
            "currency": "USD", "notional": 100000000.0,
            "position": "Pay Fixed", "tenor": "5Y"})
        if r.status_code != 200:
            raise AssertionError(f"프라이싱 HTTP {r.status_code}")
        info = r.json()["data"].get("snapshot_info") or {}
        src = str(info.get("source") or "")
        if "LSEG" in src and "Baseline" not in src and "비실시간" not in src:
            raise AssertionError(
                f"미연결로 계산한 결과가 LSEG 출처를 달고 나감: {src!r}")
    finally:
        tradition_feed.is_lseg_live_connected = saved


@case("L27-9", "FX FWD 복사문도 출처를 함께 보낸다")
def t_9():
    # 여기는 거짓말을 하지는 않았지만 아무 말도 하지 않았습니다. 기준호가로
    # 뽑은 스왑포인트가 아무 표시 없이 카운터파티에게 나갔습니다.
    src = js()
    i = src.find("function copyFwdQuotesForMessenger")
    if i < 0:
        raise AssertionError("FWD 복사 함수를 찾지 못함")
    body = src[i:i + 4000]
    if "resultProvenance()" not in body:
        raise AssertionError("FWD 복사문이 출처 판정을 쓰지 않음")
    j = body.find("clipboard.writeText")
    if "confirm(" not in body[:j]:
        raise AssertionError("FWD 도 비실시간일 때 확인 없이 복사됨")


if __name__ == "__main__":
    print("\n=== L27 이 숫자가 어디서 왔는가 ===")
    sys.exit(1 if run_all("L27") else 0)
