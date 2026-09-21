# -*- coding: utf-8 -*-
"""
Render 배포를 커맨드라인에서 거는 도구.

키를 남에게 주지 않고 직접 배포하실 수 있도록 만든 스크립트입니다.
키는 .env 의 RENDER_API_KEY 에서 읽으며(.env 는 git 에서 제외됨), 화면에 출력하지
않습니다.

    python tools/render_deploy.py                # 서비스 목록과 상태
    python tools/render_deploy.py --env          # 설정된 환경변수 '이름'만 확인
    python tools/render_deploy.py --deploy       # 최신 커밋으로 배포
    python tools/render_deploy.py --deploy --watch   # 배포 후 끝날 때까지 확인
    python tools/render_deploy.py --check <URL>  # 배포된 주소 동작 확인

옵션 --service <이름|ID> 로 서비스를 고를 수 있습니다(기본: multipricer).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.render.com/v1"
DEFAULT_SERVICE = "multipricer"


def _load_key() -> str:
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(root, ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("RENDER_API_KEY=") and not line.startswith("#"):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not key:
        sys.exit("RENDER_API_KEY 가 없습니다 — .env 에 추가하거나 환경변수로 설정하세요.\n"
                 "발급: Render 대시보드 → Account Settings → API Keys")
    return key


def _call(path: str, key: str, method: str = "GET", body=None):
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key}",
                 "Accept": "application/json",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        # The key itself is never echoed back into the message.
        sys.exit(f"Render API 오류 {e.code}: {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"Render 에 연결하지 못했습니다: {e.reason}")


def _services(key):
    rows = _call("/services?limit=100", key)
    return [r.get("service", r) for r in rows]


def _pick(key, wanted):
    for svc in _services(key):
        if wanted in (svc.get("name"), svc.get("id")):
            return svc
    sys.exit(f"서비스 '{wanted}' 를 찾지 못했습니다. "
             f"목록: {[s.get('name') for s in _services(key)]}")


def cmd_list(key):
    rows = _services(key)
    if not rows:
        print("서비스가 없습니다. Render 대시보드에서 Blueprint 로 먼저 생성하세요.")
        return
    print(f"{'이름':<22} {'종류':<10} {'상태':<12} 주소")
    for s in rows:
        d = s.get("serviceDetails") or {}
        print(f"{s.get('name',''):<22} {s.get('type',''):<10} "
              f"{s.get('suspended','') or 'active':<12} {d.get('url','')}")


def cmd_env(key, name):
    """설정된 변수의 '이름'만 봅니다. 값은 가져오지 않습니다."""
    svc = _pick(key, name)
    rows = _call(f"/services/{svc['id']}/env-vars?limit=100", key)
    keys = sorted((r.get("envVar", r)).get("key", "") for r in rows)
    print(f"{svc['name']} 에 설정된 환경변수 {len(keys)}개:")
    for k in keys:
        print("   ", k)
    for needed in ("PRICER_AUTH_USER", "PRICER_AUTH_PASS"):
        if needed not in keys:
            print(f"  ※ {needed} 없음 — 대시보드가 503 으로 닫힙니다")


def cmd_deploy(key, name, watch=False):
    svc = _pick(key, name)
    dep = _call(f"/services/{svc['id']}/deploys", key, "POST", {"clearCache": "do_not_clear"})
    dep_id = dep.get("id", "")
    print(f"배포를 시작했습니다: {svc['name']}  (deploy {dep_id})")
    if not watch:
        print("진행 상황: Render 대시보드 → Logs")
        return

    seen = None
    for _ in range(120):                      # 최대 약 20분
        time.sleep(10)
        cur = _call(f"/services/{svc['id']}/deploys/{dep_id}", key)
        status = cur.get("status")
        if status != seen:
            print(f"  상태: {status}")
            seen = status
        if status in ("live", "build_failed", "update_failed", "canceled",
                      "deactivated", "pre_deploy_failed"):
            url = (svc.get("serviceDetails") or {}).get("url", "")
            if status == "live":
                print(f"배포 완료 — {url}")
            else:
                print(f"배포 실패({status}) — Render 대시보드의 Logs 를 확인하세요")
            return
    print("시간 내에 끝나지 않았습니다 — 대시보드에서 확인하세요")


def cmd_check(url):
    """키 없이도 실행됩니다: 배포된 주소가 제대로 응답하는지만 봅니다."""
    import base64
    url = url.rstrip("/")
    user = os.environ.get("PRICER_AUTH_USER", "")
    password = os.environ.get("PRICER_AUTH_PASS", "")

    def get(path, auth=False):
        req = urllib.request.Request(url + path)
        if auth and user:
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            req.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, r.read(400).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception as e:
            return 0, str(e)

    print(f"확인 대상: {url}")
    code, _ = get("/healthz")
    print(f"  healthz          : {code}   (200 이어야 함)")
    code, _ = get("/")
    print(f"  대시보드(무인증)  : {code}   "
          f"{'(401 이어야 정상 — 닫혀 있음)' if code == 401 else '(503 이면 인증 미설정)'}")
    if user:
        code, _ = get("/", auth=True)
        print(f"  대시보드(인증)    : {code}   (200 이어야 함)")
    else:
        print("  대시보드(인증)    : 건너뜀 — PRICER_AUTH_USER/PASS 를 환경변수로 주면 확인합니다")


def main():
    args = sys.argv[1:]
    if "--check" in args:
        idx = args.index("--check")
        if idx + 1 >= len(args):
            sys.exit("--check 뒤에 주소를 주세요")
        return cmd_check(args[idx + 1])

    name = DEFAULT_SERVICE
    if "--service" in args:
        name = args[args.index("--service") + 1]

    key = _load_key()
    if "--deploy" in args:
        return cmd_deploy(key, name, watch="--watch" in args)
    if "--env" in args:
        return cmd_env(key, name)
    return cmd_list(key)


if __name__ == "__main__":
    main()
