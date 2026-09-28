# -*- coding: utf-8 -*-
"""
L23 LSEG 연동 상태 표시.

Key 창은 쓰기 전용이었습니다. 열면 빈 입력칸과
`Status: Desktop Proxy Running on 127.0.0.1:9000` 이라는 **고정 문자열**만
나왔습니다 — 프록시가 돌든 말든, 키가 있든 없든 똑같이.

헤더의 LIVE 배지와 같은 종류의 거짓말입니다. 앱키가 적용됐는지 확인하려고 여는
창이 확인해주지 못하면 그 창은 의미가 없습니다.
"""
import io
import os
import sys

from harness import case, run_all

from fastapi.testclient import TestClient
from server.app import app
import server.eikon_rate_limiter as erl

client = TestClient(app)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def status():
    r = client.get("/api/lseg/status")
    if r.status_code != 200:
        raise AssertionError(f"상태 조회 HTTP {r.status_code}")
    return r.json()["data"]


@case("L23-1", "키 설정 여부와 연결 여부를 각각 알려준다")
def t_1():
    d = status()
    for field in ("configured", "port_open", "is_live_connected", "verdict",
                  "quote_count", "port"):
        if field not in d:
            raise AssertionError(f"상태에 {field} 없음")
    if not isinstance(d["verdict"], str) or not d["verdict"].strip():
        raise AssertionError("사람이 읽을 판정 문구가 비어 있음")


@case("L23-2", "앱키 전체는 절대 돌려주지 않는다")
def t_2():
    # 공개 URL 에서도 열리는 창이다. 어느 키인지 알아볼 만큼만 나와야 한다.
    d = status()
    blob = str(d)
    cfg = os.path.join(ROOT, "lseg_config.json")
    if os.path.exists(cfg):
        import json
        with io.open(cfg, encoding="utf-8") as f:
            c = json.load(f)
        key = c.get("lseg_app_key") or c.get("app_key") or ""
        if key and key not in ("YOUR_APP_KEY",) and key in blob:
            raise AssertionError("앱키 전체가 응답에 들어 있음")
    hint = d.get("key_hint") or ""
    if hint and len(hint.replace("…", "")) > 12:
        raise AssertionError(f"key_hint 가 너무 많이 노출: {hint!r}")


@case("L23-3", "포트가 닫혀 있으면 연동됐다고 하지 않는다")
def t_3():
    saved = erl.workspace_listening
    erl.workspace_listening = lambda *a, **k: False
    try:
        d = status()
        if d["port_open"]:
            raise AssertionError("닫힌 포트를 열렸다고 보고")
        if "연동됨" in d["verdict"]:
            raise AssertionError(f"프록시가 없는데 연동됐다고 표시: {d['verdict']!r}")
        if d["configured"] and "미실행" not in d["verdict"]:
            raise AssertionError(f"원인을 짚어주지 않음: {d['verdict']!r}")
    finally:
        erl.workspace_listening = saved


@case("L23-4", "키가 없으면 무엇을 해야 하는지 말해준다")
def t_4():
    import json as _json
    cfg = os.path.join(ROOT, "lseg_config.json")
    backup = None
    if os.path.exists(cfg):
        with io.open(cfg, encoding="utf-8") as f:
            backup = f.read()
    try:
        with io.open(cfg, "w", encoding="utf-8") as f:
            _json.dump({"app_key": "YOUR_APP_KEY", "port": 9000}, f)
        d = status()
        if d["configured"]:
            raise AssertionError("자리표시자를 설정된 키로 인식")
        if "APPKEY" not in d["verdict"]:
            raise AssertionError(f"발급 방법을 알려주지 않음: {d['verdict']!r}")
        if d.get("key_hint"):
            raise AssertionError("키가 없는데 힌트를 냄")
    finally:
        if backup is None:
            if os.path.exists(cfg):
                os.remove(cfg)
        else:
            with io.open(cfg, "w", encoding="utf-8") as f:
                f.write(backup)


@case("L23-5", "창을 열면 실제 상태를 조회한다")
def t_5():
    # 고정 문자열로 돌아가지 않도록. 이전에는 마크업에 박혀 있었다.
    with io.open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    if "Desktop Proxy Running on" in html:
        raise AssertionError("연결 여부와 무관한 고정 문구가 마크업에 남아 있음")

    with io.open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as f:
        js = f.read()
    if "/api/lseg/status" not in js:
        raise AssertionError("창을 열 때 상태를 조회하지 않음")
    if "showLsegStatus()" not in js:
        raise AssertionError("조회 함수가 열기 동작에 연결되지 않음")


@case("L23-6", "호스팅 인스턴스는 고칠 수 없는 것을 고치라고 하지 않는다")
def t_6():
    # 클라우드에는 Workspace 가 있을 수 없다. 거기서 "Workspace 미실행" 은
    # 실제로 해야 할 일 - 데스크 중계를 띄우는 것 - 을 가린다. 화면이 BASE 만
    # 보여주고 원인을 말하지 않아, 중계가 안 도는 것을 알아채는 데 시간이 걸렸다.
    from server import relay
    saved_env = os.environ.get("PRICER_NO_LOCAL_FEED")
    os.environ["PRICER_NO_LOCAL_FEED"] = "1"
    relay.clear("USD")
    try:
        v = status()["verdict"]
        if "desk_relay" not in v:
            raise AssertionError(f"무엇을 해야 하는지 말하지 않음: {v!r}")
        if "Workspace 미실행" in v:
            raise AssertionError(f"클라우드에서 고칠 수 없는 것을 지시: {v!r}")
    finally:
        if saved_env is None:
            os.environ.pop("PRICER_NO_LOCAL_FEED", None)
        else:
            os.environ["PRICER_NO_LOCAL_FEED"] = saved_env


@case("L23-7", "중계가 들어오면 그 상태를 그대로 보여준다")
def t_7():
    import time as _t
    from server import relay
    relay.clear("USD")
    client.post("/api/quotes/push", json={
        "currency": "USD", "quotes": [{"tenor": "5Y", "mid": 4.5}],
        "origin": "desk-x", "source_epoch_ms": _t.time() * 1000})
    v = status()["verdict"]
    if "데스크 중계" not in v or "desk-x" not in v:
        raise AssertionError(f"중계 상태가 반영되지 않음: {v!r}")
    relay.clear("USD")


if __name__ == "__main__":
    print("\n=== L23 LSEG 연동 상태 표시 ===")
    sys.exit(1 if run_all("L23") else 0)
