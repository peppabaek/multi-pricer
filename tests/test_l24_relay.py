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
    # 이 PC 에는 Workspace 가 떠 있어서, 스냅샷을 읽는 순간 _warm_once 가 LSEG
    # 에서 다시 당겨와 방금 밀어넣은 값을 덮습니다. 그게 옳은 동작입니다 -
    # 로컬에 실물 피드가 있으면 그쪽이 낫습니다. 중계가 반영되는지만 보려면
    # 그 조회를 막아야 합니다.
    #
    # 전에는 이 검사가 우연히 통과했습니다: 중계 푸시가 호가를 '수기 입력' 으로
    # 표시하는 바람에 LSEG 조회가 그 테너를 건너뛰었기 때문입니다. 그 표시는
    # 버그였고(중계 한 틱 뒤 커브가 통째로 얼어붙음), 고치고 나니 드러났습니다.
    import server.app as app_module
    warmed = set(app_module._WARMED)
    app_module._WARMED.add("usd")
    relay.clear("USD")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    r = push(src=now)
    if r.status_code != 200:
        raise AssertionError(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.json()["data"]["applied"] != 3:
        raise AssertionError(f"반영 건수: {r.json()['data']}")

    d = client.get("/api/market-snapshot").json()["data"]
    got = {q["tenor"]: q["mid"] for q in d["quotes"] if q["tenor"] in ("1Y", "5Y")}
    app_module._WARMED.intersection_update(warmed)
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


@case("L24-17", "PowerShell 스크립트가 BOM 을 갖고 있다")
def t_17():
    """
    Windows PowerShell 5.1 은 BOM 이 없는 .ps1 을 UTF-8 이 아니라 ANSI(CP949)로
    읽습니다. 한글 주석이 깨지면서 따옴표 짝이 어긋나 파서가 통째로 죽었습니다:

        + Write-Log "?꾨즺"
        The string is missing the terminator

    로그온 때 조용히 실패하는 종류라, 몇 주 뒤 "왜 BASE 지" 로 발견됩니다.
    """
    import codecs
    for name in ("desk_autostart.ps1", "install_autostart.ps1"):
        path = os.path.join(ROOT, "tools", name)
        if not os.path.exists(path):
            raise AssertionError(f"{name} 이 없음")
        with open(path, "rb") as f:
            head = f.read(3)
        if head != codecs.BOM_UTF8:
            raise AssertionError(
                f"{name} 에 UTF-8 BOM 이 없음 — PowerShell 5.1 이 CP949 로 읽어 "
                f"한글 주석에서 파서가 죽습니다")


@case("L24-18", "자동 실행에서 인자 없이 떠야 하므로 설정을 .env 에서 읽는다")
def t_18():
    # 작업 스케줄러 인자에 비밀번호를 넣으면 작업 속성과 프로세스 목록에 평문으로
    # 남습니다. 그래서 대상 주소도 자격증명도 .env 에서 읽습니다.
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib
    dr = importlib.import_module("desk_relay")

    if not hasattr(dr, "load_env_file"):
        raise AssertionError("에이전트가 .env 를 읽지 않음 — 자동 실행 시 인자가 필요해짐")

    with io.open(os.path.join(ROOT, "tools", "desk_relay.py"), encoding="utf-8") as f:
        src = f.read()
    if 'required=True' in src:
        raise AssertionError("--target 이 필수라 인자 없이 뜨지 못함")
    for var in ("PRICER_RELAY_TARGET", "PRICER_RELAY_PASS"):
        if var not in src:
            raise AssertionError(f"{var} 를 읽지 않음")

    # 이미 설정된 환경변수를 .env 가 덮어쓰면 손으로 실행할 때 제어가 안 됩니다.
    saved = os.environ.get("PRICER_RELAY_TARGET")
    os.environ["PRICER_RELAY_TARGET"] = "http://sentinel.invalid"
    try:
        dr.load_env_file()
        if os.environ["PRICER_RELAY_TARGET"] != "http://sentinel.invalid":
            raise AssertionError(".env 가 이미 설정된 환경변수를 덮어씀")
    finally:
        if saved is None:
            os.environ.pop("PRICER_RELAY_TARGET", None)
        else:
            os.environ["PRICER_RELAY_TARGET"] = saved


@case("L24-19", ".env 를 읽어도 로컬 대시보드에 인증이 켜지지 않는다")
def t_19():
    """
    중계 자격증명을 PRICER_AUTH_USER/PASS 로 .env 에 넣었더니, term sheet 업로드가
    load_env_file() 을 부르는 순간 그 값이 서버 프로세스의 환경변수로 들어가고
    access.auth_required() 가 그걸 "이 서버가 요구할 자격증명"으로 읽어, 로컬
    대시보드가 갑자기 비밀번호를 묻기 시작했습니다.

    실사용으로는 이렇게 보입니다: localhost 에서 잘 쓰다가 문서 하나 올리면
    그때부터 로그인 창이 뜬다. 원인과 증상이 멀어서 찾기 어려운 종류입니다.

    중계가 원격에 제시하는 자격증명과, 이 서버가 요구하는 자격증명은 다른
    것입니다. 이름을 나눠 둡니다.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib
    import server.access as access
    dr = importlib.import_module("desk_relay")

    # 서버 쪽 이름을 비운 상태에서 .env 를 읽어도 게이트가 켜지면 안 됩니다.
    saved = {k: os.environ.get(k)
             for k in ("PRICER_AUTH_USER", "PRICER_AUTH_PASS", "RENDER",
                       "PRICER_HOSTED", "PRICER_AUTH_DISABLED")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        if access.auth_required():
            raise AssertionError("시작부터 인증이 켜져 있음 - 검사가 무의미")
        dr.load_env_file()
        if access.auth_required():
            raise AssertionError(
                ".env 를 읽자 로컬 대시보드에 인증이 켜짐 — 중계 자격증명이 "
                "PRICER_AUTH_* 라는 이름을 쓰고 있습니다")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    with io.open(os.path.join(ROOT, "tools", "desk_relay.py"), encoding="utf-8") as f:
        src = f.read()
    for bad in ('os.environ.get("PRICER_AUTH_USER"', 'os.environ.get("PRICER_AUTH_PASS"'):
        if bad in src:
            raise AssertionError(f"중계가 서버의 인증 변수를 읽음: {bad}")


@case("L24-20", "중계가 보낸 bid/ask 가 그대로 반영된다")
def t_20():
    """
    LSEG 의 KRWQMCD1Y=PREA 는 3.7050/3.7400 인데 배포본은 3.7125/3.7325 를
    보여줬습니다. mid 만 우연히 같았습니다.

    KRW/KOFR/FWD 의 update_quote 가 mid 만 받아서, _apply_quote 의 네 인자
    호출이 TypeError 로 떨어진 뒤 두 인자로 다시 불렸고, 진짜 양방 호가가
    버려진 채 피드가 ±1bp 를 지어냈습니다. 트레이더가 보는 스프레드가 실제의
    절반이 됩니다 - 마케터가 한쪽을 부를 때 쓰는 숫자입니다.
    """
    import time as _t
    from fastapi.testclient import TestClient
    from server.app import app
    client = TestClient(app)

    cases = [("USD", "5Y", 4.5, 4.48, 4.52),
             ("KRW", "1Y", 3.7225, 3.705, 3.74),
             ("KOFR", "1Y", 3.10, 3.085, 3.115),
             ("CRS", "1Y", 3.60, 3.58, 3.62)]
    paths = {"USD": "/api/market-snapshot", "KRW": "/api/krw/market-snapshot",
             "KOFR": "/api/kofr/market-snapshot", "CRS": "/api/crs/market-snapshot"}

    # 이 PC 에는 Workspace 가 떠 있어서, 스냅샷을 읽는 순간 _warm_once 가 LSEG
    # 에서 다시 당겨와 방금 밀어넣은 값을 덮습니다. 중계가 반영되는지 보려면
    # 그 조회를 막아야 합니다.
    import server.app as app_module
    warmed_before = set(app_module._WARMED)
    app_module._WARMED.update({"usd", "krw", "kofr", "crs", "fwd"})

    for ccy, tenor, mid, bid, ask in cases:
        r = client.post("/api/quotes/push", json={
            "currency": ccy, "origin": "desk-test",
            "source_epoch_ms": _t.time() * 1000,
            "quotes": [{"tenor": tenor, "mid": mid, "bid": bid, "ask": ask}]})
        if r.status_code != 200:
            raise AssertionError(f"{ccy} push {r.status_code}: {r.text[:120]}")

        body = client.get(paths[ccy]).json()
        quotes = body.get("quotes") or (body.get("data") or {}).get("quotes") or []
        row = next((q for q in quotes if str(q.get("tenor")).upper() == tenor), None)
        if row is None:
            raise AssertionError(f"{ccy} {tenor} 호가를 찾지 못함")
        if abs(float(row["bid"]) - bid) > 1e-6 or abs(float(row["ask"]) - ask) > 1e-6:
            app_module._WARMED.intersection_update(warmed_before)
            raise AssertionError(
                f"{ccy} {tenor}: 보낸 {bid}/{ask} 가 {row['bid']}/{row['ask']} 로 바뀜 "
                f"— 스프레드가 지어내졌습니다")
    app_module._WARMED.intersection_update(warmed_before)


@case("L24-21", "bid/ask 없이 보내도 mid 는 반영된다")
def t_21():
    # 양방을 못 구하는 피드도 있습니다. 그때까지 막으면 안 됩니다.
    import time as _t
    from fastapi.testclient import TestClient
    from server.app import app
    client = TestClient(app)
    r = client.post("/api/quotes/push", json={
        "currency": "KRW", "origin": "desk-test", "source_epoch_ms": _t.time() * 1000,
        "quotes": [{"tenor": "2Y", "mid": 3.91}]})
    if r.status_code != 200 or r.json()["data"]["applied"] != 1:
        raise AssertionError(f"mid 만 보냈는데 반영 실패: {r.text[:120]}")


@case("L24-22", "모든 피드가 네 인자 갱신을 받는다")
def t_22():
    # 하나라도 mid 전용이면 _apply_quote 가 조용히 두 인자로 되돌아가 양방을
    # 버립니다. 그 되돌아가는 길을 없앴으므로, 여기서 서명을 고정합니다.
    import inspect
    from server.tradition_feed import tradition_feed
    from server.krw_feed import krw_feed
    from server.kofr_feed import kofr_feed
    from server.crs_feed import crs_feed
    from server.kmbc_fwd_feed import kmbc_fwd_feed_instance as kmbc_fwd_feed

    for name, feed in (("USD", tradition_feed), ("KRW", krw_feed),
                       ("KOFR", kofr_feed), ("CRS", crs_feed), ("FWD", kmbc_fwd_feed)):
        fn = getattr(feed, "update_quote", None) or getattr(feed, "update_quote_manually")
        params = list(inspect.signature(fn).parameters)
        if len(params) < 3:
            raise AssertionError(f"{name}: {params} — bid/ask 를 받지 못합니다")


@case("L24-23", "중계가 수기 입력을 덮지 않는다")
def t_23():
    """
    LSEG 재조회는 is_overridden 을 보고 건너뛰는데 중계만 그냥 썼습니다.
    데스크에서는 남던 O/N~5M 수기 입력이 배포본에서는 30초마다 사라졌습니다.
    """
    import time as _t
    from fastapi.testclient import TestClient
    from server.app import app
    import server.app as app_module
    client = TestClient(app)

    warmed = set(app_module._WARMED)
    app_module._WARMED.add("krw")
    try:
        def mid_of(tenor):
            qs = client.get("/api/krw/market-snapshot").json().get("quotes") or []
            row = next((q for q in qs if q["tenor"] == tenor), {})
            return row.get("mid"), row.get("is_overridden")

        client.post("/api/krw/quotes/update", json={"tenor": "3M", "mid": 9.9999})
        if mid_of("3M")[0] != 9.9999:
            raise AssertionError("수기 입력이 들어가지 않음")

        r = client.post("/api/quotes/push", json={
            "currency": "KRW", "origin": "desk-test",
            "source_epoch_ms": _t.time() * 1000,
            "quotes": [{"tenor": "3M", "mid": 3.21, "bid": 3.20, "ask": 3.22},
                       {"tenor": "1Y", "mid": 3.7225, "bid": 3.705, "ask": 3.74}]})
        if r.status_code != 200:
            raise AssertionError(f"push {r.status_code}: {r.text[:120]}")
        d = r.json()["data"]

        got, over = mid_of("3M")
        if got != 9.9999:
            raise AssertionError(f"중계가 수기 입력을 덮음: {got}")
        if not over:
            raise AssertionError("수기 표시가 풀림")
        if d.get("held_manual") != 1:
            raise AssertionError(f"지킨 건수를 보고하지 않음: {d}")
        # 사유를 뭉뚱그리면 로그가 "피드가 모르는 테너" 라고 거짓말합니다.
        if any("모르는 테너" in x for x in d.get("skipped") or []):
            raise AssertionError(f"수기 유지를 '모르는 테너'로 보고: {d['skipped']}")

        # 누르지 않은 테너는 그대로 갱신되어야 합니다.
        qs = client.get("/api/krw/market-snapshot").json().get("quotes") or []
        one_y = next((q for q in qs if q["tenor"] == "1Y"), {})
        if abs(float(one_y.get("bid", 0)) - 3.705) > 1e-6:
            raise AssertionError(f"수기가 아닌 1Y 까지 막힘: {one_y.get('bid')}")
    finally:
        app_module._WARMED.intersection_update(warmed)


@case("L24-24", "전 구간을 수기로 눌러도 중계가 끊긴 것이 되지 않는다")
def t_24():
    # applied 가 0 이라고 거절하면 중계 기록이 남지 않아 화면이 BASE 로
    # 떨어집니다 - 데스크는 멀쩡한데 트레이더는 연결이 끊긴 줄 압니다.
    import time as _t
    from fastapi.testclient import TestClient
    from server.app import app
    client = TestClient(app)
    client.post("/api/krw/quotes/update", json={"tenor": "3M", "mid": 8.8888})
    r = client.post("/api/quotes/push", json={
        "currency": "KRW", "origin": "desk-test", "source_epoch_ms": _t.time() * 1000,
        "quotes": [{"tenor": "3M", "mid": 3.21}]})
    if r.status_code != 200:
        raise AssertionError(f"수기뿐인 푸시를 거절함: {r.status_code} {r.text[:120]}")
    if not (r.json()["data"].get("relay") or {}).get("active"):
        raise AssertionError("중계가 기록되지 않음")


@case("L24-25", "수기로 눌러둔 호가가 화면에 표시된다")
def t_25():
    # 갱신이 덮지 않는 값이라면, 그 사실이 보여야 합니다. 안 그러면 시장이
    # 움직이는 동안 얼어붙은 숫자를 시세로 읽습니다.
    with io.open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as f:
        js = f.read()
    if "is_overridden" not in js:
        raise AssertionError("화면이 수기 여부를 보지 않음")
    if "manual-hold" not in js:
        raise AssertionError("수기 호가를 구분해 표시하지 않음")
    with io.open(os.path.join(ROOT, "static", "styles.css"), encoding="utf-8") as f:
        if "manual-hold" not in f.read():
            raise AssertionError("표시 스타일이 없음")


@case("L24-27", "서버는 현물환을 받을 수 있다")
def t_27():
    """
    아웃라이트 = 현물 + 스왓포인트 입니다. 포인트만 올리면 클라우드의
    현물은 기준호가(1343.50)에 머물고 전 구간이 통째로 틀어집니다.

    다만 지금은 중계가 현물을 보내지 않습니다 - 보내기 시작한 직후부터
    호스팅의 /api/fwd/market-snapshot 이 응답을 멈췄고, 같은 페이로드를
    로컬에 넣으면 0.03초에 돌아와 아직 재현하지 못했습니다. 화면을 살려
    두고 원인을 찾는 중입니다(desk_relay.read_local 의 주석).

    받는 쪽은 그대로 두었습니다. 원인을 찾으면 보내는 줄 하나만 다시
    켜면 되도록, 여기서 그 길이 막히지 않았는지를 지킵니다.
    """
    from fastapi.testclient import TestClient
    from server.app import app

    c = TestClient(app)
    r = c.post("/api/quotes/push", json={"currency": "FWD", "quotes": [
        {"tenor": "SPOT_FX", "mid": 1338.47, "bid": 1338.36, "ask": 1338.58}]})
    if r.status_code != 200 or r.json()["data"]["applied"] != 1:
        raise AssertionError(f"현물을 받지 못함: {r.status_code} {r.text[:140]}")


@case("L24-28", "서버가 현물환 중계를 받아 반영한다")
def t_28():
    """
    현물은 테너 목록에 없어서 '피드가 모르는 테너' 로 거부되고 있었습니다.
    중계는 보냈다고 세고 서버는 버리는, 가장 알아채기 어려운 모양입니다.
    """
    from fastapi.testclient import TestClient
    from server.app import app

    c = TestClient(app)
    r = c.post("/api/quotes/push", json={"currency": "FWD", "quotes": [
        {"tenor": "SPOT_FX", "mid": 1338.47, "bid": 1338.36, "ask": 1338.58}]})
    if r.status_code != 200:
        raise AssertionError(f"HTTP {r.status_code}: {r.text[:140]}")
    if r.json()["data"]["applied"] != 1:
        raise AssertionError(f"반영되지 않음: {r.json()['data']}")

    d = c.get("/api/fwd/market-snapshot").json()["data"]
    if abs(d["spot_fx"] - 1338.47) > 1e-9:
        raise AssertionError(f"현물이 {d['spot_fx']}")
    if abs(d["spot_fx_bid"] - 1338.36) > 1e-9 or abs(d["spot_fx_ask"] - 1338.58) > 1e-9:
        raise AssertionError(f"현물 양방이 {d['spot_fx_bid']}/{d['spot_fx_ask']} "
                             "- mid 만 받으면 아웃라이트 양방이 틀어집니다")
    if "Relay" not in str(d.get("spot_fx_tick")):
        raise AssertionError(f"출처가 {d.get('spot_fx_tick')!r}")


@case("L24-29", "호가가 움직여도 커브 캐시가 무한히 늘지 않는다")
def t_29():
    """
    캐시 키에 호가와 현물이 통째로 들어갑니다. 현물을 중계하기 전에는 호스팅
    쪽 현물이 기준호가에 멈춰 있어 키가 거의 바뀌지 않았고, 그래서 드러나지
    않았습니다. 30초마다 커브 하나씩 쌓이면 512MB 인스턴스가 버티지 못합니다.
    """
    from fastapi.testclient import TestClient
    from server.app import app, _CURVE_CACHE, _CURVE_CACHE_MAX

    c = TestClient(app)
    for i in range(_CURVE_CACHE_MAX * 2):
        spot = round(1300.0 + i * 0.37, 2)
        c.post("/api/quotes/push", json={"currency": "FWD", "quotes": [
            {"tenor": "SPOT_FX", "mid": spot, "bid": spot - 0.1, "ask": spot + 0.1}]})
        r = c.get("/api/fwd/market-snapshot")
        if r.status_code != 200:
            raise AssertionError(f"{i}회에서 HTTP {r.status_code}")
    if len(_CURVE_CACHE) > _CURVE_CACHE_MAX:
        raise AssertionError(f"캐시가 {len(_CURVE_CACHE)}개 - 상한 {_CURVE_CACHE_MAX}")


if __name__ == "__main__":
    print("\n=== L24 데스크 → 클라우드 중계 ===")
    sys.exit(1 if run_all("L24") else 0)
