# -*- coding: utf-8 -*-
"""
데스크 PC 의 LSEG 호가를 배포된 프라이서로 중계합니다.

Workspace 데스크톱 API 는 Workspace 가 떠 있는 그 PC 에서만 동작합니다. 그래서
클라우드 인스턴스는 LSEG 에 직접 붙을 수 없고, 대신 이 스크립트가 데스크 PC 에서
돌면서 호가를 밀어 넣습니다.

  트레이더 브라우저 ──> 클라우드 프라이서 <── 이 스크립트 <── 로컬 프라이서 <── Workspace

App Key 는 이 PC 를 벗어나지 않습니다. 나가는 것은 호가 숫자뿐입니다.

    python tools/desk_relay.py --target https://multipricer.onrender.com \
        --user peppa --interval 30

  --once        한 번만 보내고 종료 (설정 확인용)
  --currencies  기본 USD,KRW,KOFR,CRS
  --dry-run     보내지 않고 무엇을 보낼지만 출력

비밀번호는 PRICER_AUTH_PASS 환경변수에서 읽습니다. 인자로 받지 않는 것은
명령 이력에 남기지 않기 위해서입니다.
"""
import argparse
import base64
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 로컬 프라이서의 통화별 스냅샷 경로와, 그 응답에서 호가가 들어 있는 키.
SOURCES = {
    "USD":  ("/api/market-snapshot", "data"),
    "KRW":  ("/api/krw/market-snapshot", "snapshot_info"),
    "KOFR": ("/api/kofr/market-snapshot", "data"),
    "CRS":  ("/api/crs/market-snapshot", "data"),
}


def call(url, payload=None, auth=None, timeout=120):
    req = urllib.request.Request(url, method="POST" if payload is not None else "GET")
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, body, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def read_local(local, currency):
    """로컬 프라이서에서 호가를 읽는다. reload=true 로 Workspace 를 실제로 조회."""
    path, key = SOURCES[currency]
    sep = "&" if "?" in path else "?"
    payload = call(f"{local}{path}{sep}reload=true")
    body = payload.get("data") or payload.get(key) or {}
    quotes = body.get("quotes") or []
    return body, [
        {"tenor": q.get("tenor"), "mid": q.get("mid"),
         "bid": q.get("bid"), "ask": q.get("ask")}
        for q in quotes if q.get("tenor") and q.get("mid") is not None
    ]


def push_once(local, target, auth, currencies, origin, dry_run=False):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    for cur in currencies:
        try:
            body, quotes = read_local(local, cur)
        except Exception as e:
            print(f"  [{stamp}] {cur:5} 로컬 읽기 실패: {e}")
            continue

        if not quotes:
            print(f"  [{stamp}] {cur:5} 호가 없음 — 건너뜀")
            continue

        # 로컬이 LSEG 에 실제로 붙어 있지 않으면 보내지 않는다. 기준호가를
        # 중계하면 클라우드에는 '데스크 중계'로 보이는데 실제로는 아무 근거가
        # 없는 숫자가 된다 - 없는 것보다 나쁘다.
        if not body.get("is_live_connected"):
            print(f"  [{stamp}] {cur:5} 로컬이 LSEG 미연결 — 보내지 않음 "
                  f"({body.get('status_message', '')[:40]})")
            continue

        if dry_run:
            print(f"  [{stamp}] {cur:5} {len(quotes)}건 (전송 안 함) "
                  f"예: {quotes[0]['tenor']}={quotes[0]['mid']}")
            continue

        try:
            res = call(f"{target}/api/quotes/push", {
                "currency": cur,
                "quotes": quotes,
                "source_timestamp": body.get("timestamp"),
                "origin": origin,
            }, auth=auth)
            d = res.get("data", {})
            print(f"  [{stamp}] {cur:5} {d.get('applied', 0)}건 전송"
                  + (f" · 실패 {d.get('skipped')}" if d.get("skipped") else ""))
        except urllib.error.HTTPError as e:
            print(f"  [{stamp}] {cur:5} 전송 실패 HTTP {e.code}: "
                  f"{e.read().decode('utf-8', 'replace')[:120]}")
        except Exception as e:
            print(f"  [{stamp}] {cur:5} 전송 실패: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", default="http://127.0.0.1:8000",
                    help="Workspace 가 붙어 있는 이 PC 의 프라이서")
    ap.add_argument("--target", required=True, help="배포된 프라이서 주소")
    ap.add_argument("--user", default=os.environ.get("PRICER_AUTH_USER", ""))
    ap.add_argument("--interval", type=int, default=30, help="전송 주기(초)")
    ap.add_argument("--currencies", default="USD,KRW,KOFR,CRS")
    ap.add_argument("--origin", default=os.environ.get("COMPUTERNAME", "desk"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    password = os.environ.get("PRICER_AUTH_PASS", "")
    auth = (a.user, password) if a.user else None
    if a.user and not password:
        sys.exit("PRICER_AUTH_PASS 환경변수를 설정하세요 (인자로 받지 않습니다)")

    currencies = [c.strip().upper() for c in a.currencies.split(",") if c.strip()]
    unknown = [c for c in currencies if c not in SOURCES]
    if unknown:
        sys.exit(f"알 수 없는 통화: {unknown} (가능: {', '.join(SOURCES)})")

    print(f"데스크 중계 시작")
    print(f"  읽기 : {a.local}")
    print(f"  보내기: {a.target}  ({a.origin})")
    print(f"  통화 : {', '.join(currencies)} · {a.interval}초 주기"
          + ("  [DRY RUN]" if a.dry_run else ""))
    print()

    while True:
        push_once(a.local, a.target.rstrip("/"), auth, currencies,
                  a.origin, a.dry_run)
        if a.once:
            return
        time.sleep(max(5, a.interval))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n중계를 중지했습니다. 클라우드의 호가는 곧 '오래됨'으로 표시됩니다.")
