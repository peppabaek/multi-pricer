# -*- coding: utf-8 -*-
"""
L21 업로드 중에도 서버가 살아 있어야 한다.

터미시트 한 건을 읽는 데 모델이 45~60초를 씁니다. 그 호출을 async 엔드포인트
안에서 그냥 부르면 **이벤트 루프가 그동안 멈춥니다.** 서버는 아무 요청에도
답하지 못하고, 헬스체크까지 실패하니 호스트는 인스턴스가 죽은 것으로 보고
재시작합니다 — 배포본에서 본 502가 그것입니다.

데스크 PC에서는 아무도 헬스체크를 하지 않아 드러나지 않았습니다.
"""
import sys
import threading
import time

from harness import case, run_all

from fastapi.testclient import TestClient
import server.termsheet as tsmod
from server.app import app
from test_l10_termsheet import _MINIMAL_PDF, _fake_trade

client = TestClient(app)

SLOW = 3.0          # 실제 모델의 45~60초를 대신하는 시간
PORT = 8095


def _wait_port(port, timeout=45):
    import socket
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as sk:
            sk.settimeout(1)
            if sk.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.4)
    return False


@case("L21-1", "느린 업로드 중에도 서버가 다른 요청에 답한다")
def t_1():
    # 반드시 실제 uvicorn 이어야 한다. TestClient 는 요청마다 자체 이벤트 루프를
    # 돌리므로, 한 요청이 다른 요청을 굶기는 상황 자체가 재현되지 않는다 —
    # 이 테스트의 첫 판은 결함이 있는 코드에서도 통과했다.
    import os as _os
    import subprocess
    import urllib.request

    root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
    env = dict(_os.environ, STUB_EXTRACT_DELAY=str(SLOW))
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.stub_server:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    health = {"codes": [], "worst": 0.0}
    upload = {"code": None}

    try:
        if not _wait_port(PORT):
            raise AssertionError("테스트 서버가 뜨지 않음")

        base = f"http://127.0.0.1:{PORT}"

        def do_upload():
            boundary = "----l21"
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                    f"filename=\"t.pdf\"\r\nContent-Type: application/pdf\r\n\r\n"
                    ).encode() + _MINIMAL_PDF + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(
                base + "/api/termsheet/extract", data=body, method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            try:
                with urllib.request.urlopen(req, timeout=SLOW + 30) as r:
                    upload["code"] = r.status
            except Exception as e:
                upload["code"] = f"{type(e).__name__}: {e}"

        worker = threading.Thread(target=do_upload, daemon=True)
        worker.start()
        time.sleep(0.4)                      # 업로드가 모델 호출에 들어가도록

        deadline = time.time() + SLOW - 0.5
        while time.time() < deadline:
            t0 = time.time()
            try:
                with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
                    health["codes"].append(r.status)
            except Exception:
                health["codes"].append(0)
            health["worst"] = max(health["worst"], time.time() - t0)
            time.sleep(0.2)
        worker.join(timeout=SLOW + 30)
    finally:
        srv.terminate()

    if upload["code"] != 200:
        raise AssertionError(f"업로드 자체가 실패: {upload['code']}")
    if not health["codes"]:
        raise AssertionError("헬스체크를 한 번도 보내지 못함")
    bad = [c for c in health["codes"] if c != 200]
    if bad:
        raise AssertionError(
            f"업로드가 서버를 막음 — 헬스체크 {len(bad)}/{len(health['codes'])}회 실패")
    if health["worst"] > 1.5:
        raise AssertionError(
            f"헬스체크가 {health['worst']:.1f}초 지연됨 — 이벤트 루프가 막히고 있음")


@case("L21-2", "업로드 엔드포인트가 모델 호출을 스레드풀로 넘긴다")
def t_2():
    import inspect
    from server.app import extract_termsheet
    src = inspect.getsource(extract_termsheet)
    if "run_in_threadpool" not in src:
        raise AssertionError(
            "async 엔드포인트가 process_termsheet 를 직접 호출 — 이벤트 루프가 막힌다")


@case("L21-3", "연결이 없으면 상태 문구가 준비됐다고 말하지 않는다")
def t_3():
    d = client.get("/api/market-snapshot").json()["data"]
    if d.get("is_live_connected"):
        return          # 데스크에서 실제 연결된 경우는 검사 대상이 아니다
    msg = (d.get("status_message") or "")
    for claim in ("Ready", "ready", "Live", "Connected"):
        if claim in msg:
            raise AssertionError(f"연결이 없는데 '{claim}' 이라고 보고: {msg!r}")
    if not msg:
        raise AssertionError("상태 문구가 비어 있어 트레이더가 판단할 수 없음")


@case("L21-4", "LIVE 배지는 기본으로 꺼져 있다")
def t_4():
    import os, re
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    m = re.search(r'<span[^>]*id="live-connected-badge"[^>]*>', html)
    if not m:
        raise AssertionError("LIVE 배지를 찾지 못함")
    if "hidden" not in m.group(0):
        raise AssertionError(
            "LIVE 배지가 마크업에 켜진 채로 있음 — 피드가 없어도 LIVE 로 보인다")

    with open(os.path.join(root, "static", "app.js"), encoding="utf-8") as f:
        js = f.read()
    if "setFeedBadge" not in js:
        raise AssertionError("배지를 끄는 경로가 없음")


if __name__ == "__main__":
    print("\n=== L21 업로드 중 응답성 ===")
    sys.exit(1 if run_all("L21") else 0)
