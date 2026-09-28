# -*- coding: utf-8 -*-
"""
트레이더가 웹에서 실시간 프라이싱을 할 수 있는가 — 두 경우를 모두 본다.

  시나리오 A: 데스크 PC 가 켜져 있고 중계가 돌 때
  시나리오 B: 데스크 PC 가 꺼졌을 때

B 가 더 중요합니다. 중계가 끊겨도 마지막 호가는 남아 있으므로, 트레이더가
그 사실을 **화면에서 알 수 있는지**가 관건입니다. 모르면 어제 호가로 오늘
가격을 냅니다.

API 값이 아니라 브라우저 화면을 봅니다 — 트레이더가 보는 것이 그것이므로.

    python tests/relay_scenarios.py                    # 로컬 대역으로 재현
    python tests/relay_scenarios.py --cloud <URL> --user peppa   # 실제 배포본
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

DESK_PORT = 8000
CLOUD_PORT = 8121
STALE_AFTER = 20          # 시나리오 B 를 빨리 관찰하기 위한 값

fails = []


def ok(msg):
    print(f"  PASS  {msg}")


def bad(msg):
    fails.append(msg)
    print(f"  FAIL  {msg}")


def wait_port(port, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.4)
    return False


def get(url, auth=None, timeout=120):
    req = urllib.request.Request(url)
    if auth:
        import base64
        req.add_header("Authorization", "Basic " + base64.b64encode(
            f"{auth[0]}:{auth[1]}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return 0, {}


def relay_once(desk, cloud, auth):
    env = dict(os.environ)
    if auth:
        env["PRICER_AUTH_PASS"] = auth[1]
    cmd = [sys.executable, os.path.join(ROOT, "tools", "desk_relay.py"),
           "--local", desk, "--target", cloud, "--currencies", "USD",
           "--origin", "desk-test", "--once"]
    if auth:
        cmd += ["--user", auth[0]]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env, timeout=300)
    return out.stdout + out.stderr


def badge_text(page):
    """트레이더가 헤더에서 실제로 보는 것."""
    seen = []
    for bid, label in (("live-connected-badge", "LIVE"),
                       ("relay-badge", "RELAY"),
                       ("base-quote-badge", "BASE")):
        el = page.locator(f"#{bid}")
        if el.count() and el.is_visible():
            seen.append((label, el.inner_text().strip(),
                         "stale" in (el.get_attribute("class") or "")))
    return seen


def main():
    args = sys.argv[1:]
    cloud_url = None
    auth = None
    if "--cloud" in args:
        cloud_url = args[args.index("--cloud") + 1].rstrip("/")
    if "--user" in args:
        user = args[args.index("--user") + 1]
        pw = os.environ.get("PRICER_AUTH_PASS", "")
        if not pw:
            sys.exit("PRICER_AUTH_PASS 환경변수를 설정하세요")
        auth = (user, pw)

    procs = []
    desk = f"http://127.0.0.1:{DESK_PORT}"
    try:
        # 데스크 역할: Workspace 가 붙어 있는 이 PC 의 프라이서
        if not wait_port(DESK_PORT, timeout=2):
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "server.app:app", "--host",
                 "127.0.0.1", "--port", str(DESK_PORT), "--log-level", "warning"],
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            wait_port(DESK_PORT)

        if cloud_url is None:
            cloud_url = f"http://127.0.0.1:{CLOUD_PORT}"
            # 같은 PC 라 대역 서버도 Workspace 에 붙어버린다. 그러면 LIVE 가 떠서
            # 중계 표시를 가리고, 클라우드를 재현하지 못한다.
            env = dict(os.environ, RELAY_STALE_SECONDS=str(STALE_AFTER),
                       PRICER_NO_LOCAL_FEED="1")
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "server.app:app", "--host",
                 "127.0.0.1", "--port", str(CLOUD_PORT), "--log-level", "warning"],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL))
            wait_port(CLOUD_PORT)
            print(f"클라우드 대역: {cloud_url}  (stale {STALE_AFTER}s)")
        else:
            print(f"실제 배포본: {cloud_url}")
        print(f"데스크      : {desk}\n")

        # 중계 기능이 그 쪽에 있는지 먼저 본다.
        code, _ = get(f"{cloud_url}/api/quotes/relay-status", auth)
        if code == 404:
            bad("배포본에 중계 기능이 없습니다 — 최신 커밋으로 배포한 뒤 다시 실행하세요")
            return 1

        # 데스크가 LSEG 에 붙어 있는지 확인. 안 붙어 있으면 시나리오 A 가 성립하지
        # 않는다 - 무엇을 보고 있는지 모르는 채로 통과시키지 않는다.
        code, body = get(f"{desk}/api/market-snapshot?reload=true")
        live = (body.get("data") or {}).get("is_live_connected")
        if not live:
            bad(f"데스크가 LSEG 에 연결돼 있지 않습니다 — Workspace 를 켜고 다시 실행하세요")
            return 1
        ref = {q["tenor"]: q["mid"] for q in body["data"]["quotes"]}
        print(f"데스크 LSEG 연결 확인 · 5Y = {ref.get('5Y')}\n")

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chromium")
            except Exception:
                browser = p.chromium.launch()
            ctx = browser.new_context(
                http_credentials=({"username": auth[0], "password": auth[1]}
                                  if auth else None),
                viewport={"width": 1680, "height": 1050})
            page = ctx.new_page()

            # ---------------- 시나리오 A ----------------
            print("=== 시나리오 A: 데스크 PC 가 켜져 있고 중계가 돌 때 ===")
            log = relay_once(desk, cloud_url, auth)
            if "전송" not in log:
                bad(f"중계가 전송되지 않음: {log.strip()[-160:]}")
            else:
                ok("데스크가 호가를 전송함")

            page.goto(cloud_url + "/", wait_until="load", timeout=180000)
            page.wait_for_timeout(5000)

            badges = badge_text(page)
            names = [b[0] for b in badges]
            if "RELAY" in names:
                b = [x for x in badges if x[0] == "RELAY"][0]
                ok(f"트레이더 화면 배지: {b[1]!r}" + (" (오래됨)" if b[2] else ""))
                if b[2]:
                    bad("방금 중계했는데 '오래됨'으로 표시")
            elif "LIVE" in names:
                ok("배지: LIVE — 이 서버가 LSEG 에 직접 연결됨(대역 테스트에서만 가능)")
            else:
                bad(f"중계했는데 RELAY 배지가 없음: {names or '배지 없음'}")

            # 비교 기준은 중계가 실제로 보낸 값이어야 한다. 중계 전에 읽어두면
            # 그 사이 시세가 움직여 불일치로 오보한다 - 실제로 한 번 그랬고,
            # 그 다음 판은 시세가 가만히 있어 통과했다. 둘 다 검사가 아니다.
            # reload 없이 읽으면 중계가 방금 보낸 그 스냅샷이 그대로 나온다.
            _, desk_body = get(f"{desk}/api/market-snapshot")
            sent = {q["tenor"]: q["mid"]
                    for q in (desk_body.get("data") or {}).get("quotes", [])}
            want5 = sent.get("5Y", ref.get("5Y"))

            code, body = get(f"{cloud_url}/api/market-snapshot", auth)
            d = body.get("data") or {}
            got5 = {q["tenor"]: q["mid"] for q in d.get("quotes", [])}.get("5Y")
            if got5 is not None and want5 is not None and abs(got5 - want5) < 1e-9:
                ok(f"웹의 5Y 호가가 데스크와 일치: {got5}")
            else:
                bad(f"호가 불일치 — 데스크 {want5} vs 웹 {got5}")

            # 웹에서 실제로 가격이 나오는가
            page.keyboard.press("Enter")
            page.wait_for_timeout(6000)
            par = page.locator("#par-swap-rate, .par-rate-value").first
            par_txt = par.inner_text().strip() if par.count() else ""
            rows = page.locator("#dual-table-body tr:not(.total-row)").count()
            if rows > 0:
                ok(f"웹에서 프라이싱 수행됨 · par {par_txt or '-'} · 스케줄 {rows}기간")
            else:
                bad("웹에서 프라이싱 결과가 나오지 않음")

            # ---------------- 시나리오 B ----------------
            # 기다릴 시간은 서버가 정한다. 로컬 대역은 20초로 띄우지만 배포본은
            # 90초가 기본이라, 테스트가 자기 상수를 고집하면 아직 오래되지 않은
            # 것을 결함으로 보고한다 - 실제로 그렇게 오보했다.
            code, body = get(f"{cloud_url}/api/market-snapshot", auth)
            st0 = (body.get("data") or {}).get("relay") or {}
            limit = st0.get("stale_after_seconds", STALE_AFTER)
            already = st0.get("age_seconds", 0)
            wait = max(5, limit - already + 6)
            print(f"\n=== 시나리오 B: 데스크 PC 를 끈 뒤 (서버 기준 {limit}s) ===")
            print(f"  중계를 멈추고 {int(wait)}초 기다립니다…")
            time.sleep(wait)

            page.reload(wait_until="load", timeout=180000)
            page.wait_for_timeout(5000)

            badges = badge_text(page)
            relay_b = [x for x in badges if x[0] == "RELAY"]
            if not relay_b:
                bad(f"중계가 끊겼는데 상태 표시가 사라짐: {[b[0] for b in badges]}")
            elif not relay_b[0][2]:
                bad(f"중계가 끊겼는데 여전히 정상으로 표시: {relay_b[0][1]!r}")
            else:
                ok(f"트레이더 화면에 오래됨으로 표시: {relay_b[0][1]!r}")

            code, body = get(f"{cloud_url}/api/market-snapshot", auth)
            st = (body.get("data") or {}).get("relay") or {}
            if not st.get("stale"):
                bad(f"서버가 오래됨을 인식하지 못함: {st}")
            else:
                ok(f"서버도 오래됨으로 판정 (나이 {st.get('age_seconds')}s)")

            # 끊겨도 마지막 호가로 계산은 되어야 한다 - 다만 오래됨이 보이는 채로.
            page.keyboard.press("Enter")
            page.wait_for_timeout(6000)
            rows = page.locator("#dual-table-body tr:not(.total-row)").count()
            if rows > 0:
                ok("중계가 끊겨도 마지막 호가로 프라이싱은 가능 (오래됨 표시 유지)")
            else:
                bad("중계가 끊기자 프라이싱 자체가 불가")

            browser.close()
    finally:
        for pr in procs:
            pr.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== 트레이더 웹 실시간 프라이싱 — 두 시나리오 ===\n")
    sys.exit(main())
