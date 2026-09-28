# -*- coding: utf-8 -*-
"""
중계 배지가 스스로 흘러가는가.

배지를 한 번 그리고 말면, 트레이더가 화면을 열어둔 채 자리를 비운 사이 데스크가
멈춰도 배지는 처음 값에 얼어붙습니다. 10분 전 호가를 `RELAY (2s)` 로 보게 됩니다 —
나이를 보여주는 목적 자체가 사라집니다.

    python tests/ui_relay_badge.py
"""
import os
import socket
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
PORT = 8123
# 폴링 주기(20초)보다 넉넉해야 한다. 기준이 더 짧으면 새 중계를 집어오는
# 시점에 이미 기준을 넘어, 회복을 확인할 창이 없다.
STALE_AFTER = 45

fails = []


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


def wait_port(port, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.4)
    return False


def badge(page):
    el = page.locator("#relay-badge")
    if not el.count() or not el.is_visible():
        return None, False
    return el.inner_text().strip(), "stale" in (el.get_attribute("class") or "")


def age_of(text):
    """'● RELAY (12s)' -> 12"""
    import re
    m = re.search(r"\((\d+)([sm])\)", text or "")
    if not m:
        return None
    n = int(m.group(1))
    return n * 60 if m.group(2) == "m" else n


def main():
    import json
    import urllib.request

    env = dict(os.environ, RELAY_STALE_SECONDS=str(STALE_AFTER),
               PRICER_NO_LOCAL_FEED="1")
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{PORT}"

    def push():
        body = json.dumps({
            "currency": "USD", "origin": "desk-badge",
            "source_epoch_ms": time.time() * 1000,
            "quotes": [{"tenor": "5Y", "mid": 4.5}],
        }).encode()
        req = urllib.request.Request(base + "/api/quotes/push", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status

    try:
        if not wait_port(PORT):
            print("  FAIL  서버가 뜨지 않음")
            return 1
        push()

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chromium")
            except Exception:
                browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1680, "height": 1050})
            page.goto(base + "/", wait_until="load", timeout=120000)
            page.wait_for_timeout(5000)

            first, first_stale = badge(page)
            if not first:
                bad("중계를 보냈는데 RELAY 배지가 없음")
                browser.close()
                return 1
            ok(f"배지 표시: {first!r}")
            if first_stale:
                bad("방금 보낸 중계가 오래됨으로 표시")

            # 아무것도 누르지 않고 기다린다. 배지가 혼자 흘러가야 한다.
            a0 = age_of(first)
            page.wait_for_timeout(8000)
            second, _ = badge(page)
            a1 = age_of(second)
            if a0 is None or a1 is None:
                bad(f"배지에서 나이를 읽지 못함: {first!r} -> {second!r}")
            elif a1 <= a0:
                bad(f"배지가 멈춰 있음 — {a0}s 에서 {a1}s (8초 경과)")
            else:
                ok(f"배지가 스스로 흘러감: {a0}s → {a1}s")

            # 기준을 넘기면, 새로고침 없이도 오래됨으로 바뀌어야 한다.
            page.wait_for_timeout((STALE_AFTER - 10) * 1000)
            third, third_stale = badge(page)
            if not third_stale:
                bad(f"{STALE_AFTER}s 가 지났는데 정상으로 표시: {third!r}")
            else:
                ok(f"새로고침 없이 오래됨으로 전환: {third!r}")

            # 데스크가 다시 보내면, 트레이더가 아무것도 하지 않아도 회복해야 한다.
            push()
            page.wait_for_timeout(23000)          # 폴링 주기 20초
            fourth, fourth_stale = badge(page)
            if fourth_stale:
                bad(f"새 중계가 왔는데 여전히 오래됨: {fourth!r}")
            else:
                ok(f"새 중계를 자동으로 집어옴: {fourth!r}")

            browser.close()
    finally:
        srv.terminate()

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== UI: 중계 배지가 스스로 갱신되는가 ===\n")
    sys.exit(main())
