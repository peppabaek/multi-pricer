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

비밀번호는 PRICER_RELAY_PASS 환경변수에서 읽습니다. 인자로 받지 않는 것은
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
    # KRW 는 메타데이터가 snapshot_info 에, 호가는 최상위에 있다.
    "KRW":  ("/api/krw/market-snapshot", "snapshot_info"),
    "KOFR": ("/api/kofr/market-snapshot", "data"),
    "CRS":  ("/api/crs/market-snapshot", "data"),
    "FWD":  ("/api/fwd/market-snapshot", "data"),
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
    # 응답 모양이 통화마다 다르다. KRW 는 호가가 최상위에 있어, 메타데이터만 보고
    # "호가 없음" 으로 건너뛰고 있었다.
    quotes = body.get("quotes") or payload.get("quotes") or []
    return body, [
        {"tenor": q.get("tenor"), "mid": q.get("mid"),
         "bid": q.get("bid"), "ask": q.get("ask")}
        for q in quotes if q.get("tenor") and q.get("mid") is not None
    ]


def load_env_file():
    """
    루트의 .env 에서 아직 설정되지 않은 값만 채운다.

    부팅 시 자동 실행하려면 비밀번호가 어딘가에 있어야 하는데, 작업 스케줄러의
    인자로 넣으면 작업 속성과 프로세스 목록에 평문으로 남습니다. .env 는 이미
    git 에서 제외돼 있고 API 키들이 사는 곳이니 같이 둡니다.

    이미 환경변수로 준 값은 건드리지 않습니다 - 손으로 실행할 때 덮어쓸 수
    있어야 합니다.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key and key not in os.environ:
                    os.environ[key] = value.strip().strip('"').strip("'")
    except OSError:
        pass


def feed_is_live(body):
    """
    이 피드가 정말 LSEG 에 붙어 있는가.

    기준호가를 중계하면 클라우드에는 '데스크 중계'로 보이는데 실제로는 아무 근거가
    없는 숫자가 됩니다 - 아무것도 없는 것보다 나쁩니다. 그래서 확실할 때만 참을
    돌려줍니다.

    피드마다 이름이 다릅니다: 스왑 피드들은 is_live_connected, FWD 는 is_connected
    입니다. 한쪽만 보면 살아 있는 FWD 를 미연결로 판정해 조용히 건너뜁니다 -
    로그에 "미연결" 이라면서 괄호 안에는 "● LIVE" 가 찍히는 모순으로 드러났습니다.
    """
    for key in ("is_live_connected", "is_connected"):
        if key in body:
            return bool(body[key])
    return False


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
        if not feed_is_live(body):
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
                # 벽시계 문자열만 보내면 데스크(서울)와 서버(UTC)의 9시간 차이가
                # 그대로 나이 계산에 들어간다. 절대 시각을 함께 보낸다.
                "source_epoch_ms": body.get("epoch_ms"),
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
    load_env_file()
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", default="http://127.0.0.1:8000",
                    help="Workspace 가 붙어 있는 이 PC 의 프라이서")
    # 자동 실행(작업 스케줄러)에서는 인자 없이 떠야 하므로 .env 의
    # PRICER_RELAY_TARGET 을 기본값으로 씁니다. 손으로 줄 때는 그게 이깁니다.
    ap.add_argument("--target", default=os.environ.get("PRICER_RELAY_TARGET", ""),
                    help="배포된 프라이서 주소 (.env 의 PRICER_RELAY_TARGET)")
    # PRICER_AUTH_* 가 아니라 PRICER_RELAY_* 입니다. 이름을 같이 쓰면, .env 를
    # 읽는 순간(예: term sheet 업로드) 서버의 access 게이트가 그 값을 "이 서버가
    # 요구할 자격증명"으로 읽고 로컬 대시보드에 인증을 켜버립니다. 중계가
    # 원격에 제시하는 자격증명과 이 서버가 요구하는 자격증명은 다른 것입니다.
    ap.add_argument("--user", default=os.environ.get("PRICER_RELAY_USER", ""))
    ap.add_argument("--interval", type=int, default=30, help="전송 주기(초)")
    ap.add_argument("--currencies", default="USD,KRW,KOFR,CRS,FWD")
    # 배포본 배지에 "데스크 PC(...) 중계" 로 찍히는 이름. 컴퓨터명이 기본이지만
    # 31503918-B6BF 같은 자산번호라 알아보기 어려워, .env 로 덮을 수 있게 합니다.
    ap.add_argument("--origin", default=(os.environ.get("PRICER_RELAY_ORIGIN")
                                         or os.environ.get("COMPUTERNAME", "desk")))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not a.target:
        sys.exit("배포된 주소가 없습니다 — --target 을 주거나 .env 에 "
                 "PRICER_RELAY_TARGET 을 설정하세요")

    password = os.environ.get("PRICER_RELAY_PASS", "")
    auth = (a.user, password) if a.user else None
    if a.user and not password:
        sys.exit("PRICER_RELAY_PASS 환경변수를 설정하세요 (인자로 받지 않습니다)")

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
