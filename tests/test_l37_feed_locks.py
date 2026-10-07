# -*- coding: utf-8 -*-
"""
L37 피드 락을 쥔 채 같은 락을 다시 잡지 않는다.

호스팅의 /api/fwd/market-snapshot 과 /api/crs/market-snapshot 이 응답을 멈췄고,
healthz·KRW 스냅샷·중계 push 는 그동안 전부 200 이었습니다. 예외도 OOM 도
재시작도 없었습니다. uvicorn 은 요청이 끝나야 기록하므로 로그에는 그 요청의
줄 자체가 없었습니다.

단계마다 표시를 남기는 감시 타이머를 붙여 잡았습니다:

    [FWD SNAPSHOT] 10초 경과 - 'kmbc' 에서 멈춰 있음
    [FWD SNAPSHOT] 30초 경과 - 'kmbc' 에서 멈춰 있음
    [FWD SNAPSHOT] 90초 경과 - 'kmbc' 에서 멈춰 있음

kmbc 다음은 crs_feed.get_snapshot() 입니다. 그 함수는 락만 잡고 사전을 만들
뿐이라, 누군가 락을 쥐고 놓지 않는다는 뜻이었습니다:

    def update_quote_manually(...):
        with self._lock:                      # 획득
            if tenor in ("SPOT", "FX", "SPOT_FX"):
                self.update_spot_fx_manually(mid)   # 같은 락을 또 획득 -> 영원히

threading.Lock 은 재진입이 안 됩니다. 중계가 SPOT_FX 를 보내기 시작하면서 이
가지가 처음 실행됐고, 그 뒤로 그 락을 기다리는 모든 요청이 멈췄습니다.
"""
import ast
import io
import os
import sys
import threading

from harness import case, run_all

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FEEDS = ("crs_feed.py", "krw_feed.py", "kofr_feed.py", "kmbc_fwd_feed.py",
         "tradition_feed.py")


def nested_lock_calls(path):
    """락을 쥔 채 같은 객체의 '락을 잡는 다른 메서드' 를 부르는 곳."""
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    locking = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.With) and any(
                        "_lock" in ast.unparse(i.context_expr) for i in sub.items):
                    locking.add(node.name)

    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name in locking):
            continue
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.With) and any(
                    "_lock" in ast.unparse(i.context_expr) for i in sub.items)):
                continue
            for call in ast.walk(sub):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "self"
                        and call.func.attr in locking):
                    found.append(f"{node.name}() 안에서 self.{call.func.attr}() "
                                 f"(줄 {call.lineno})")
    return found


@case("L37-1", "락을 쥔 채 같은 락을 다시 잡는 곳이 없다")
def t_1():
    bad = {}
    for name in FEEDS:
        hits = nested_lock_calls(os.path.join(ROOT, "server", name))
        if hits:
            bad[name] = hits
    if bad:
        raise AssertionError(f"교착 위험: {bad}")


@case("L37-2", "CRS 피드가 SPOT_FX 를 받고도 멈추지 않는다")
def t_2():
    """
    글로만 막으면 다음에 또 같은 모양을 만들 수 있습니다. 실제로 불러 봅니다 -
    멈추면 이 테스트가 끝나지 않으므로 시간을 재서 끊습니다.
    """
    from server.crs_feed import CRSFeed

    feed = CRSFeed()
    done = []

    def go():
        feed.update_quote_manually("SPOT_FX", 1338.47, 1338.36, 1338.58, source="Relay")
        done.append(True)

    th = threading.Thread(target=go, daemon=True)
    th.start()
    th.join(timeout=5.0)
    if not done:
        raise AssertionError("SPOT_FX 를 넣었는데 5초 안에 돌아오지 않음 - 교착")
    if abs(feed.spot_fx - 1338.47) > 1e-9:
        raise AssertionError(f"현물이 {feed.spot_fx}")

    # 그리고 그 뒤에 스냅샷이 정상으로 나와야 합니다. 락이 안 풀렸다면 여기서 멈춥니다.
    snap = []
    th = threading.Thread(target=lambda: snap.append(feed.get_snapshot()), daemon=True)
    th.start()
    th.join(timeout=5.0)
    if not snap:
        raise AssertionError("SPOT_FX 이후 get_snapshot 이 멈춤 - 락이 풀리지 않음")
    if abs(snap[0]["spot_fx"] - 1338.47) > 1e-9:
        raise AssertionError(f"스냅샷의 현물이 {snap[0]['spot_fx']}")


@case("L37-3", "update_spot_fx_manually 도 그대로 쓸 수 있다")
def t_3():
    """바깥에서 직접 부르는 길도 막히지 않아야 합니다."""
    from server.crs_feed import CRSFeed

    feed = CRSFeed()
    done = []
    th = threading.Thread(target=lambda: (feed.update_spot_fx_manually(1340.0),
                                          done.append(True)), daemon=True)
    th.start()
    th.join(timeout=5.0)
    if not done:
        raise AssertionError("update_spot_fx_manually 가 돌아오지 않음")
    if abs(feed.spot_fx - 1340.0) > 1e-9:
        raise AssertionError(f"현물이 {feed.spot_fx}")


@case("L37-4", "중계가 보내는 그대로 넣어도 멈추지 않는다")
def t_4():
    """
    실제로 멈춘 경로입니다. 중계는 통화마다 같은 read_local 을 쓰므로 CRS 에도
    SPOT_FX 가 섞여 들어갑니다.
    """
    from fastapi.testclient import TestClient
    from server.app import app

    c = TestClient(app)
    out = []

    def go():
        r = c.post("/api/quotes/push", json={"currency": "CRS", "quotes": [
            {"tenor": "SPOT_FX", "mid": 1338.47, "bid": 1338.36, "ask": 1338.58},
            {"tenor": "1Y", "mid": 3.46, "bid": 3.44, "ask": 3.48}]})
        out.append(r.status_code)
        out.append(c.get("/api/fwd/market-snapshot").status_code)

    th = threading.Thread(target=go, daemon=True)
    th.start()
    th.join(timeout=20.0)
    if len(out) < 2:
        raise AssertionError(f"20초 안에 끝나지 않음 (진행: {out})")
    if out != [200, 200]:
        raise AssertionError(f"응답이 {out}")


if __name__ == "__main__":
    print("\n=== L37 피드 락 교착 ===")
    sys.exit(1 if run_all("L37") else 0)
