# -*- coding: utf-8 -*-
"""
L22 기동 로그.

서버를 켤 때마다 eikon 핸드셰이크 실패가 여섯 줄씩 쏟아지고 있었습니다.
그 자체로 기능이 깨지지는 않지만, **진짜 오류가 그 속에 묻힙니다** — 배포본에서
502를 쫓을 때 로그가 조용했다면 훨씬 빨리 찾았을 것입니다.

원인은 두 가지였습니다. `set_app_key()` 가 그 자리에서 핸드셰이크를 하는데
`set_port_number()` 를 그 뒤에 부르고 있었고(그래서 포트가 None),
Workspace 가 떠 있는지 확인하지도 않고 시도했습니다.
"""
import io
import os
import re
import subprocess
import sys
import time

from harness import case, run_all

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@case("L22-1", "포트를 먼저 설정한 뒤에 앱키를 설정한다")
def t_1():
    # set_app_key 는 즉시 핸드셰이크한다. 포트가 아직 없으면
    # http://127.0.0.1:None/api/handshake 를 만들어 InvalidURL 로 실패한다.
    for name in ("eikon_rate_limiter.py", "crs_feed.py"):
        with io.open(os.path.join(ROOT, "server", name), encoding="utf-8") as f:
            src = f.read()
        key_at = src.find("set_app_key(")
        port_at = src.find("set_port_number(")
        if key_at < 0 or port_at < 0:
            continue
        if port_at > key_at:
            raise AssertionError(
                f"{name}: set_app_key 가 set_port_number 보다 먼저 호출됨 — "
                f"포트 없이 핸드셰이크한다")


@case("L22-2", "Workspace 가 없으면 핸드셰이크를 시도조차 하지 않는다")
def t_2():
    from server.eikon_rate_limiter import workspace_listening

    # 아무것도 듣고 있지 않을 포트.
    if workspace_listening(9, timeout=0.2):
        raise AssertionError("닫힌 포트를 열려 있다고 판단")
    if workspace_listening(0, timeout=0.2):
        raise AssertionError("포트 0 을 열려 있다고 판단")

    # 실제로 듣고 있으면 참이어야 한다.
    import socket
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        if not workspace_listening(port, timeout=1.0):
            raise AssertionError("열린 포트를 닫혀 있다고 판단")
    finally:
        srv.close()


@case("L22-3", "Workspace 없이 켜도 기동 로그가 조용하다")
def t_3():
    # 별도 프로세스로 임포트해야 의미가 있다: 이 테스트 프로세스는 이미
    # 임포트를 마쳤으므로 그때의 출력은 다시 나오지 않는다.
    out = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, '.'); import server.app"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180)
    noise = out.stdout + out.stderr

    for phrase in ("no proxy address identified",
                   "Invalid port: 'None'",
                   "Port number was not identified",
                   "Error on handshake"):
        if phrase in noise:
            raise AssertionError(f"기동 로그에 여전히 남아 있음: {phrase!r}")
    if "DeprecationWarning" in noise:
        raise AssertionError(f"기동 시 DeprecationWarning: {noise[:200]}")
    if out.returncode != 0:
        raise AssertionError(f"임포트 실패: {noise[-300:]}")


@case("L22-4", "startup 훅을 lifespan 으로 옮겼다")
def t_4():
    with io.open(os.path.join(ROOT, "server", "app.py"), encoding="utf-8") as f:
        src = f.read()
    if '@app.on_event(' in src:
        raise AssertionError("on_event 가 남아 있음 — FastAPI 에서 제거 예정")
    if "lifespan" not in src:
        raise AssertionError("lifespan 핸들러가 없음")


@case("L22-5", "기동 후 스케줄러가 실제로 돌고 프라이싱이 된다")
def t_5():
    # lifespan 으로 옮기면서 startup 작업이 조용히 사라질 수 있다.
    from fastapi.testclient import TestClient
    from server.app import app

    with TestClient(app) as client:          # with 로 열어야 lifespan 이 실행된다
        r = client.get("/api/calendar/status")
        if r.status_code != 200:
            raise AssertionError(f"캘린더 상태 HTTP {r.status_code}")
        if not r.json()["data"]["updater_status"]["is_scheduler_active"]:
            raise AssertionError("lifespan 전환 후 휴일 스케줄러가 시작되지 않음")

        p = client.post("/api/price", json={
            "notional": 100000000, "tenor": "5Y",
            "effective_date": "2026-09-25", "maturity_date": "2031-09-25",
            "fixed_coupon_pct": 3.65, "position": "Pay Fixed"})
        if p.status_code != 200:
            raise AssertionError(f"프라이싱 HTTP {p.status_code}")
        if p.json()["data"]["pricing_results"]["dv01"] <= 0:
            raise AssertionError("프라이싱 결과가 비정상")


@case("L22-6", "조용해진 것이 기능을 꺼서가 아닌지 확인한다")
def t_6():
    # L22-3 은 기동 로그가 조용한지만 봤고, 그래서 통과했다 — 이전 수정이
    # EikonManager 의 메서드를 전부 날려 피드를 죽였는데도. 로그가 조용해진 이유가
    # '연결을 안 해서'가 아니라 '연결할 것이 없어서'여야 한다.
    from server.eikon_rate_limiter import EikonManager, eikon_manager

    for name in ("_ensure_init", "get_data"):
        if not hasattr(eikon_manager, name):
            raise AssertionError(
                f"EikonManager 에 {name} 이 없음 — 클래스 본문이 끊겼다")
        if not callable(getattr(eikon_manager, name)):
            raise AssertionError(f"{name} 이 호출 가능하지 않음")

    # 인스턴스가 아니라 클래스에 붙어 있어야 한다.
    if "get_data" not in vars(EikonManager):
        raise AssertionError("get_data 가 EikonManager 의 메서드가 아님")


@case("L22-7", "모든 시장 피드가 메서드를 온전히 갖고 있다")
def t_7():
    # 같은 사고가 다른 모듈에서 반복되지 않도록, 피드 객체들이 실제로 쓰이는
    # 메서드를 갖고 있는지 본다. 없으면 AttributeError 가 상태 문구에 묻혀
    # "Offline" 으로만 보인다 — 연결이 없는 것과 구별되지 않는다.
    from server.tradition_feed import tradition_feed
    from server.crs_feed import crs_feed
    from server.kofr_feed import kofr_feed
    from server.krw_feed import krw_feed
    from server.kmbc_fwd_feed import kmbc_fwd_feed_instance

    feeds = {
        "tradition_feed": tradition_feed,
        "crs_feed": crs_feed,
        "kofr_feed": kofr_feed,
        "krw_feed": krw_feed,
        "kmbc_fwd_feed": kmbc_fwd_feed_instance,
    }
    for name, feed in feeds.items():
        methods = [m for m in dir(type(feed))
                   if not m.startswith("__") and callable(getattr(type(feed), m, None))]
        if len(methods) < 2:
            raise AssertionError(
                f"{name}: 메서드가 {methods} 뿐 — 클래스 본문이 끊겼을 가능성")


@case("L22-8", "연결 실패 사유가 '없어서'인지 '고장나서'인지 드러난다")
def t_8():
    # 'object has no attribute' 는 연결 없음이 아니라 코드 결함이다. 그것이
    # Offline 문구에 섞여 들어가면 원인을 구별할 수 없다.
    from fastapi.testclient import TestClient
    from server.app import app

    with TestClient(app) as client:
        d = client.get("/api/market-snapshot").json()["data"]
    msg = (d.get("status_message") or "")
    for bug in ("has no attribute", "AttributeError", "TypeError", "NameError"):
        if bug in msg:
            raise AssertionError(
                f"연결 상태 문구에 코드 결함이 섞여 있음: {msg!r}")


if __name__ == "__main__":
    print("\n=== L22 기동 로그 ===")
    sys.exit(1 if run_all("L22") else 0)
