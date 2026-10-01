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


@case("L22-9", "app.py 를 직접 실행해도 열린다")
def t_9():
    """
    `python server/app.py` 는 43행의 `from server import relay` 에서 죽었습니다.
    스크립트를 직접 실행하면 sys.path[0] 이 프로젝트 루트가 아니라 server/ 가
    되기 때문입니다. 파일 끝의 __main__ 블록은 직접 실행을 의도한 코드인데
    도달조차 못 했습니다 - 쓰라고 써 둔 문이 잠겨 있었습니다.
    """
    import socket
    import urllib.request

    port = 8117
    env = dict(os.environ, PRICER_NO_LOCAL_FEED="1", PORT=str(port))
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "server", "app.py")],
                         cwd=ROOT, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    try:
        deadline = time.time() + 90
        up = False
        while time.time() < deadline and p.poll() is None:
            with socket.socket() as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    up = True
                    break
            time.sleep(0.5)
        if p.poll() is not None:
            out = (p.stdout.read() or "")[-500:]
            raise AssertionError(f"직접 실행이 죽음:\n{out}")
        if not up:
            raise AssertionError("직접 실행했으나 포트가 열리지 않음")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=30) as r:
            if r.status != 200:
                raise AssertionError(f"/healthz {r.status}")
    finally:
        p.terminate()
        try:
            p.wait(timeout=15)
        except Exception:
            p.kill()


@case("L22-10", "데스크에서 포트를 바꿔도 사내망에 열리지 않는다")
def t_10():
    """
    전에는 PORT 가 설정됐는지로 호스팅 여부를 판단했습니다. 포트 충돌을 피하려고
    PORT=8001 을 준 데스크 PC 가 0.0.0.0 에 붙어 사내망에 열립니다 - 직접 실행이
    불가능할 때는 무해했지만, 이제는 실제로 갈 수 있는 길입니다.
    """
    with io.open(os.path.join(ROOT, "server", "app.py"), encoding="utf-8") as f:
        src = f.read()
    tail = src[src.index('if __name__ == "__main__":'):]
    if 'bool(os.environ.get("PORT"))' in tail:
        raise AssertionError("PORT 설정 여부로 호스팅을 판단 — 포트만 바꿔도 0.0.0.0")
    if "is_hosted" not in tail:
        raise AssertionError("호스팅 판정에 is_hosted() 를 쓰지 않음")

    # 판정 자체도 확인합니다: PORT 만으로는 호스팅이 아닙니다.
    import server.access as access
    saved = {k: os.environ.get(k) for k in ("PORT", "RENDER", "PRICER_HOSTED")}
    try:
        for k in ("RENDER", "PRICER_HOSTED"):
            os.environ.pop(k, None)
        os.environ["PORT"] = "8001"
        if access.is_hosted():
            raise AssertionError("PORT 만 설정했는데 호스팅으로 판정")
        os.environ["RENDER"] = "true"
        if not access.is_hosted():
            raise AssertionError("RENDER 인데 호스팅이 아니라고 판정")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@case("L22-11", "자동 리로드는 기본으로 꺼져 있다")
def t_11():
    """
    uvicorn 의 reload 는 파일을 감시하는 부모와 서빙하는 자식, 두 프로세스로
    돕니다. 데스크에서 창을 닫거나 부모가 죽으면 자식이 살아남아 포트를 계속
    붙듭니다. 그러면 자동 실행 스크립트가 "이미 실행 중" 으로 건너뛰고, 아무도
    관리하지 않는 고아가 호가를 서빙합니다.

    실제로 그렇게 됐습니다: 부모 PID 는 사라졌는데 8000 은 리스닝 중이었고,
    자식(multiprocessing.spawn)이 남아 있었습니다.
    """
    with io.open(os.path.join(ROOT, "server", "app.py"), encoding="utf-8") as f:
        src = f.read()
    tail = src[src.index('if __name__ == "__main__":'):]
    if "reload=not hosted" in tail:
        raise AssertionError("데스크에서 리로더가 기본으로 켜짐 — 고아 프로세스가 생깁니다")
    if "PRICER_RELOAD" not in tail:
        raise AssertionError("리로드를 켤 방법이 없음")

    # 환경변수가 없으면 꺼져 있어야 합니다.
    saved = os.environ.pop("PRICER_RELOAD", None)
    try:
        val = os.environ.get("PRICER_RELOAD", "").strip().lower() in ("1", "true", "yes")
        if val:
            raise AssertionError("기본값이 켜짐")
    finally:
        if saved is not None:
            os.environ["PRICER_RELOAD"] = saved


@case("L22-12", "자동 실행이 포트가 아니라 응답으로 판단한다")
def t_12():
    # 죽은 부모의 소켓과 고아 자식이 8000 을 붙들고 있어도 TCP 연결은 됩니다.
    # 포트만 보고 건너뛰면 그 좀비를 정상으로 취급합니다.
    path = os.path.join(ROOT, "tools", "desk_autostart.ps1")
    with io.open(path, encoding="utf-8-sig") as f:
        ps = f.read()
    if "Net.Sockets.TcpClient" in ps:
        raise AssertionError("아직 TCP 연결만으로 판단 — 좀비를 걸러내지 못합니다")
    if "/healthz" not in ps:
        raise AssertionError("살아 있는지 묻지 않음")


@case("L22-13", "자동 실행 창이 보이지 않는다")
def t_13():
    """
    출력은 전부 logs\ 로 보내면서 창은 최소화로 띄웠더니, 부팅할 때마다
    아무것도 찍히지 않는 도스창 두 개가 떴습니다. 고장난 것처럼 보이니 닫게
    되고, 닫으면 프라이서와 중계가 같이 죽어 배포본이 BASE 로 떨어졌습니다.
    """
    path = os.path.join(ROOT, "tools", "desk_autostart.ps1")
    with io.open(path, encoding="utf-8-sig") as f:
        ps = f.read()
    if "-WindowStyle Minimized" in ps:
        raise AssertionError("빈 창이 뜹니다 — 출력은 파일로 가는데 창만 남습니다")
    if ps.count("-WindowStyle Hidden") < 2:
        raise AssertionError("프라이서와 중계 둘 다 숨기지 않음")


@case("L22-14", "포트가 막혀 있으면 한눈에 읽히게 말한다")
def t_14():
    """
    `python server/app.py` 는 거의 항상 포트 충돌로 실패합니다 - 로그온 시
    자동 실행된 프라이서가 이미 8000 을 잡고 있고, 창을 숨겨 놓았으니 돌고
    있는 줄 모르기 쉽습니다.

    그대로 두면 uvicorn 이 nest_asyncio 를 거쳐 asyncio 로 올라가는 25줄짜리
    트레이스백을 뱉고 SystemExit: 1 로 끝납니다. 우리 코드는 한 줄도 없는데
    터미널에는 크래시처럼 보이고, 진짜 이유인 [Errno 10048] 은 맨 위로 밀려
    올라갑니다.
    """
    import socket

    port = 8207
    env = dict(os.environ, PRICER_NO_LOCAL_FEED="1", PORT=str(port))
    first = subprocess.Popen([sys.executable, os.path.join(ROOT, "server", "app.py")],
                             cwd=ROOT, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            with socket.socket() as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.5)
        else:
            raise AssertionError("첫 번째가 뜨지 않아 검사할 수 없음")

        second = subprocess.run(
            [sys.executable, os.path.join(ROOT, "server", "app.py")],
            cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120)
    finally:
        first.terminate()
        try:
            first.wait(timeout=15)
        except Exception:
            first.kill()

    out = (second.stdout or "") + (second.stderr or "")
    if second.returncode == 0:
        raise AssertionError("포트가 막혔는데 성공으로 끝남")
    if "Traceback" in out:
        raise AssertionError(f"트레이스백이 그대로 노출됨:\n{out[-400:]}")
    if str(port) not in out:
        raise AssertionError(f"어느 포트인지 말하지 않음:\n{out[-300:]}")
    if "PORT=" not in out:
        raise AssertionError(f"어떻게 하라는 안내가 없음:\n{out[-300:]}")
    # 길면 다시 묻히게 됩니다.
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if len(lines) > 12:
        raise AssertionError(f"출력이 {len(lines)}줄 — 원인이 또 묻힙니다")


if __name__ == "__main__":
    print("\n=== L22 기동 로그 ===")
    sys.exit(1 if run_all("L22") else 0)
