# -*- coding: utf-8 -*-
"""
L24 데스크 → 클라우드 호가 중계.

Workspace 데스크톱 API 는 그 PC 에서만 동작하므로, 배포된 프라이서가 LSEG 에
직접 붙을 방법은 없습니다. 대신 Workspace 가 떠 있는 데스크 PC 가 호가를 밀어
넣습니다.

이 기능에서 가장 위험한 것은 **나이**입니다. 스냅샷의 timestamp 는 데이터를
받은 시각이 아니라 읽는 시각이라, 중계에 그대로 쓰면 데스크 PC 가 꺼진 뒤에도
호가가 계속 '방금 것'으로 보입니다. 트레이더가 어제 호가로 오늘 가격을 냅니다.
그래서 여기 있는 검사의 절반은 나이에 관한 것입니다.
"""
import datetime
import io
import os
import sys

from harness import case, run_all

from fastapi.testclient import TestClient
from server.app import app
from server import relay

client = TestClient(app)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def quotes(n=3, mid=4.1234):
    return [{"tenor": t, "mid": mid + i * 0.01}
            for i, t in enumerate(["1Y", "5Y", "10Y"][:n])]


def push(currency="USD", src=None, origin="desk-test", qs=None):
    return client.post("/api/quotes/push", json={
        "currency": currency,
        "quotes": qs if qs is not None else quotes(),
        "source_timestamp": src,
        "origin": origin,
    })


@case("L24-1", "한 번에 여러 호가를 받아 반영한다")
def t_1():
    relay.clear("USD")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    r = push(src=now)
    if r.status_code != 200:
        raise AssertionError(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.json()["data"]["applied"] != 3:
        raise AssertionError(f"반영 건수: {r.json()['data']}")

    d = client.get("/api/market-snapshot").json()["data"]
    got = {q["tenor"]: q["mid"] for q in d["quotes"] if q["tenor"] in ("1Y", "5Y")}
    if abs(got.get("5Y", 0) - 4.1334) > 1e-6:
        raise AssertionError(f"밀어넣은 호가가 반영되지 않음: {got}")


@case("L24-2", "나이는 도착 시각이 아니라 원본 시각으로 센다")
def t_2():
    # 이 검사가 이 기능의 핵심이다. 도착 시각으로 재면 끊긴 중계가 영원히
    # 새 것으로 보인다.
    relay.clear("USD")
    old = (datetime.datetime.now() - datetime.timedelta(minutes=10)
           ).strftime("%Y-%m-%d %H:%M:%S")
    push(src=old)
    st = client.get("/api/market-snapshot").json()["data"]["relay"]
    if st["age_seconds"] < 550:
        raise AssertionError(
            f"10분 전 호가인데 나이가 {st['age_seconds']}초 — 도착 시각으로 재고 있다")
    if not st["stale"]:
        raise AssertionError("10분 지난 호가를 최신으로 표시")


@case("L24-3", "갓 받은 호가는 오래되지 않았다고 표시한다")
def t_3():
    relay.clear("USD")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    push(src=now)
    st = client.get("/api/market-snapshot").json()["data"]["relay"]
    if st["stale"]:
        raise AssertionError(f"방금 받은 호가를 오래됐다고 표시: {st}")
    if st["age_seconds"] > 5:
        raise AssertionError(f"나이 계산이 이상함: {st['age_seconds']}")


@case("L24-4", "원본 시각을 주지 않으면 그 사실을 감추지 않는다")
def t_4():
    relay.clear("USD")
    push(src=None)
    st = client.get("/api/market-snapshot").json()["data"]["relay"]
    if st["source_time_supplied"]:
        raise AssertionError("주지 않은 원본 시각을 받았다고 표시")
    if "도착 시각" not in relay.describe("USD"):
        raise AssertionError(f"근거가 약하다는 사실이 문구에 없음: {relay.describe('USD')!r}")


@case("L24-5", "중계는 직접 연결(LIVE)이라고 주장하지 않는다")
def t_5():
    relay.clear("USD")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    push(src=now)
    d = client.get("/api/market-snapshot").json()["data"]
    # 이 서버가 LSEG 에 직접 붙은 것은 아니다. 중계를 LIVE 로 보이게 하면
    # 데스크가 꺼진 뒤에도 실시간처럼 읽힌다.
    if d["relay"]["active"] and d.get("is_live_connected") and not d.get("has_app_key"):
        raise AssertionError("중계만 받고 있는데 직접 연결됐다고 보고")


@case("L24-6", "빈 호가와 모르는 통화는 거절한다")
def t_6():
    r = push(qs=[])
    if r.status_code // 100 != 4:
        raise AssertionError(f"빈 호가를 받아들임: {r.status_code}")
    r = push(currency="XXX")
    if r.status_code // 100 != 4:
        raise AssertionError(f"모르는 통화를 받아들임: {r.status_code}")


@case("L24-7", "통화별로 따로 기록된다")
def t_7():
    relay.clear("USD")
    relay.clear("KRW")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    push(currency="USD", src=now, origin="desk-A")
    st = client.get("/api/quotes/relay-status").json()["data"]
    if "USD" not in st or st["USD"]["origin"] != "desk-A":
        raise AssertionError(f"USD 중계가 기록되지 않음: {st}")
    if st.get("KRW", {}).get("active"):
        raise AssertionError("보내지 않은 통화가 중계중으로 표시")


@case("L24-8", "화면이 LIVE·RELAY·BASE 를 구분한다")
def t_8():
    with io.open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as f:
        js = f.read()
    if "relay-badge" not in js:
        raise AssertionError("중계 배지를 다루는 코드가 없음")
    # RELAY 가 LIVE 보다 우선하면 안 된다: 직접 연결이 있으면 그것이 사실이다.
    if "rly.hidden = isLive" not in js:
        raise AssertionError("직접 연결 시 중계 배지를 감추지 않음")
    with io.open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    for bid in ("live-connected-badge", "relay-badge", "base-quote-badge"):
        if f'id="{bid}"' not in html:
            raise AssertionError(f"{bid} 배지가 없음")
        seg = html[html.index(f'id="{bid}"') - 80: html.index(f'id="{bid}"') + 40]
        if "hidden" not in seg:
            raise AssertionError(f"{bid} 가 기본으로 켜져 있음")


@case("L24-9", "에이전트는 로컬이 미연결이면 기준호가를 중계하지 않는다")
def t_9():
    # 기준호가를 중계하면 클라우드에는 '데스크 중계'로 보이는데 실제로는 아무
    # 근거가 없는 숫자다 - 아무것도 없는 것보다 나쁘다.
    #
    # 전에는 소스에 특정 문자열이 있는지만 봤다. 문자열은 그대로인데 필드 이름이
    # 맞지 않아 실제로는 건너뛰던 결함(L24-9b)을 그래서 놓쳤다. 이제 실제로
    # 보내는지 본다.
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib
    dr = importlib.import_module("desk_relay")

    quotes = [{"tenor": "5Y", "mid": 4.5, "bid": None, "ask": None}]
    pushed = []
    saved_read, saved_call = dr.read_local, dr.call
    dr.call = lambda url, body=None, auth=None, **kw: pushed.append(url) or {"data": {}}
    try:
        dr.read_local = lambda local, cur: ({"is_live_connected": False,
                                             "status_message": "기준호가"}, quotes)
        dr.push_once("http://x", "http://y", None, ["USD"], "desk-t")
        if pushed:
            raise AssertionError(f"미연결인데 전송함: {pushed}")

        dr.read_local = lambda local, cur: ({"is_live_connected": True}, quotes)
        dr.push_once("http://x", "http://y", None, ["USD"], "desk-t")
        if not pushed:
            raise AssertionError("연결돼 있는데 전송하지 않음")
    finally:
        dr.read_local, dr.call = saved_read, saved_call


@case("L24-9b", "피드마다 다른 연결 필드 이름을 모두 읽는다")
def t_9b():
    # 소스를 grep 하는 L24-9 만으로는 부족했다. 문자열은 그대로 있는데, FWD 만
    # 이 값을 is_connected 라고 불러서 살아 있는 피드가 조용히 건너뛰어졌다.
    # 로그에는 "미연결" 이라면서 괄호 안에 "● LIVE" 가 찍혔다.
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib
    dr = importlib.import_module("desk_relay")

    cases = [
        ({"is_live_connected": True}, True, "스왑 피드 연결됨"),
        ({"is_live_connected": False}, False, "스왑 피드 미연결"),
        ({"is_connected": True}, True, "FWD 연결됨"),
        ({"is_connected": False}, False, "FWD 미연결"),
        ({}, False, "알 수 없으면 보내지 않는다"),
    ]
    for body, want, why in cases:
        got = dr.feed_is_live(body)
        if got != want:
            raise AssertionError(f"{why}: {body} → {got}, 기대 {want}")


@case("L24-10", "에이전트가 App Key 를 밖으로 내보내지 않는다")
def t_10():
    with io.open(os.path.join(ROOT, "tools", "desk_relay.py"), encoding="utf-8") as f:
        src = f.read()
    for leak in ("app_key", "appkey", "lseg_config"):
        if leak in src.lower():
            raise AssertionError(f"에이전트가 앱키를 다룸: {leak}")
    # 비밀번호도 명령 이력에 남지 않아야 한다.
    if "--password" in src:
        raise AssertionError("비밀번호를 인자로 받으면 명령 이력에 남는다")


@case("L24-11", "데스크와 서버의 시간대가 달라도 나이가 맞다")
def t_11():
    # 실제 배포에서 데스크는 서울(UTC+9), 서버는 UTC 였다. 벽시계 문자열을 그대로
    # 빼니 원본 시각이 9시간 미래가 되어 나이가 영원히 0 이었고, 끊긴 중계가
    # 계속 최신으로 보였다. 같은 PC 에서 하던 테스트로는 잡을 수 없던 결함이다.
    import time as _t
    relay.clear("USD")
    seoul_wall = (datetime.datetime.now()
                  + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    r = client.post("/api/quotes/push", json={
        "currency": "USD", "quotes": quotes(), "origin": "desk-seoul",
        "source_timestamp": seoul_wall,
        "source_epoch_ms": (_t.time() - 300) * 1000,   # 실제로는 5분 전
    })
    if r.status_code != 200:
        raise AssertionError(f"HTTP {r.status_code}")
    st = client.get("/api/market-snapshot").json()["data"]["relay"]
    if not (290 < st["age_seconds"] < 320):
        raise AssertionError(
            f"시간대 차이가 나이에 섞였다: {st['age_seconds']}s (300s 이어야 함)")
    if not st["stale"]:
        raise AssertionError("5분 지난 호가를 최신으로 표시")


@case("L24-12", "원본 시각이 미래면 최신이라고 하지 않는다")
def t_12():
    # 0 으로 깎아 '방금'으로 보이게 하면, 시계가 어긋난 채로 끊긴 중계가 영원히
    # 새 것이 된다. 모를 때는 신선하다고 하지 않는다.
    import time as _t
    relay.clear("USD")
    client.post("/api/quotes/push", json={
        "currency": "USD", "quotes": quotes(), "origin": "desk-skew",
        "source_epoch_ms": (_t.time() + 3600) * 1000,
    })
    st = client.get("/api/market-snapshot").json()["data"]["relay"]
    if not st.get("clock_skewed"):
        raise AssertionError(f"미래 시각을 정상으로 받아들임: {st}")
    if not st["stale"]:
        raise AssertionError("시계가 어긋났는데 최신으로 표시")
    if "시계" not in relay.describe("USD"):
        raise AssertionError(f"원인을 알려주지 않음: {relay.describe('USD')!r}")


@case("L24-13", "에이전트가 절대 시각을 함께 보낸다")
def t_13():
    with io.open(os.path.join(ROOT, "tools", "desk_relay.py"), encoding="utf-8") as f:
        src = f.read()
    if "source_epoch_ms" not in src:
        raise AssertionError("에이전트가 벽시계 문자열만 보낸다 — 시간대가 어긋난다")


@case("L24-14", "다섯 통화 모두 중계가 반영된다")
def t_14():
    # 피드마다 갱신 메서드의 이름과 인자 수가 달랐다. USD 만 (tenor, mid, bid, ask)
    # 를 받고 KRW/KOFR/FWD 는 (tenor, mid), CRS 는 이름이 update_quote_manually 다.
    # 맞추지 않았을 때 USD 만 들어오고 나머지 넷은 매 주기마다 전부 실패했다.
    import time as _t
    for cur, tenor in (("USD", "5Y"), ("KRW", "5Y"), ("KOFR", "5Y"),
                       ("CRS", "5Y"), ("FWD", "1M")):
        relay.clear(cur)
        r = client.post("/api/quotes/push", json={
            "currency": cur, "origin": "desk-test",
            "source_epoch_ms": _t.time() * 1000,
            "quotes": [{"tenor": tenor, "mid": 4.0, "bid": 3.99, "ask": 4.01}]})
        if r.status_code != 200:
            raise AssertionError(f"{cur}: HTTP {r.status_code} {r.text[:150]}")
        if r.json()["data"]["applied"] != 1:
            raise AssertionError(f"{cur}: 반영 {r.json()['data']}")


@case("L24-15", "한 건도 반영 못 하면 중계중이라고 기록하지 않는다")
def t_15():
    # 0건인데 기록하면 대시보드가 '데스크 중계 중' 이라고 표시하면서 실제로는
    # 기준호가를 보여준다. 아무것도 안 온 것보다 나쁘다 - 연결됐다고 믿게 된다.
    import time as _t
    relay.clear("USD")
    r = client.post("/api/quotes/push", json={
        "currency": "USD", "origin": "desk-bad",
        "source_epoch_ms": _t.time() * 1000,
        "quotes": [{"tenor": "존재하지않는테너", "mid": 4.0}]})
    if r.status_code == 200 and r.json()["data"]["applied"] == 0:
        raise AssertionError("0건 반영을 성공으로 처리")
    if relay.status("USD").get("active"):
        raise AssertionError("아무것도 반영하지 못했는데 중계중으로 기록")


@case("L24-16", "에이전트가 다섯 통화를 모두 대상으로 한다")
def t_16():
    with io.open(os.path.join(ROOT, "tools", "desk_relay.py"), encoding="utf-8") as f:
        src = f.read()
    for cur in ("USD", "KRW", "KOFR", "CRS", "FWD"):
        if f'"{cur}"' not in src:
            raise AssertionError(f"에이전트에 {cur} 경로가 없음")
    # KRW 는 호가가 응답 최상위에 있어, 메타데이터만 보면 '호가 없음' 이 된다.
    if 'payload.get("quotes")' not in src:
        raise AssertionError("KRW 처럼 호가가 최상위에 있는 응답을 읽지 못한다")


if __name__ == "__main__":
    print("\n=== L24 데스크 → 클라우드 중계 ===")
    sys.exit(1 if run_all("L24") else 0)
