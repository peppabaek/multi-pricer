# -*- coding: utf-8 -*-
"""
L26 홈 화면에 추가되는가.

트레이더가 매번 주소를 치고 인증을 넘기는 대신, 한 번 홈 화면에 얹어두고 앱처럼
여는 것이 실제 사용 방식입니다. 그러려면 manifest 와 아이콘이 있어야 하고 -
없으면 브라우저는 주소창이 붙은 스크린샷 하나를 아이콘으로 만들어 놓습니다 -
iOS 는 manifest 의 icons 를 보지 않으므로 apple-touch-icon 이 따로 필요합니다.

여기서 재는 것은 파일이 존재하는가가 아니라, 참조한 경로로 실제로 받아지는가
입니다. 링크만 걸고 파일이 없으면 아이콘 자리가 비고, 그건 배포 뒤에야 보입니다.
"""
import io
import json
import os
import re
import sys

from harness import case, run_all

from fastapi.testclient import TestClient
from server.app import app

client = TestClient(app)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC = os.path.join(ROOT, "static")


def m_html():
    with io.open(os.path.join(STATIC, "m.html"), encoding="utf-8") as f:
        return f.read()


@case("L26-1", "휴대폰 화면이 manifest 를 가리킨다")
def t_1():
    h = m_html()
    if 'rel="manifest"' not in h:
        raise AssertionError("manifest 링크가 없음 — 홈 화면에 추가해도 앱처럼 열리지 않음")
    if "apple-touch-icon" not in h:
        raise AssertionError("apple-touch-icon 이 없음 — iOS 아이콘이 빈 칸이 됨")
    if "theme-color" not in h:
        raise AssertionError("theme-color 가 없음")


@case("L26-2", "manifest 가 실제로 받아지고 내용이 맞다")
def t_2():
    r = client.get("/manifest.webmanifest")
    if r.status_code != 200:
        raise AssertionError(f"manifest HTTP {r.status_code}")
    m = json.loads(r.text)
    if m.get("display") != "standalone":
        raise AssertionError(f"display={m.get('display')} — 주소창이 남습니다")
    # 홈 화면에서 열면 PC 화면이 아니라 휴대폰 화면으로 가야 합니다.
    if not str(m.get("start_url", "")).startswith("/m"):
        raise AssertionError(f"start_url={m.get('start_url')} — 휴대폰 화면이 아님")
    if not m.get("icons"):
        raise AssertionError("icons 가 비어 있음")


@case("L26-3", "참조한 아이콘이 전부 실제로 받아진다")
def t_3():
    # 링크만 있고 파일이 없으면 배포 뒤에야 빈 칸으로 드러납니다.
    refs = set(re.findall(r'href="(/icons/[^"]+)"', m_html()))
    refs |= {i["src"] for i in json.loads(
        client.get("/manifest.webmanifest").text)["icons"]}
    if not refs:
        raise AssertionError("아이콘 참조가 하나도 없음")
    for src in sorted(refs):
        r = client.get(src)
        if r.status_code != 200:
            raise AssertionError(f"{src} HTTP {r.status_code} — 참조만 있고 파일이 없음")
        if not r.content.startswith(b"\x89PNG"):
            raise AssertionError(f"{src} 가 PNG 가 아님")


@case("L26-4", "iOS 홈 화면 아이콘이 180x180 이다")
def t_4():
    from PIL import Image
    r = client.get("/icons/icon-180.png")
    w, h = Image.open(io.BytesIO(r.content)).size
    if (w, h) != (180, 180):
        raise AssertionError(f"apple-touch-icon 이 {w}x{h} — iOS 는 180x180 을 씁니다")


@case("L26-5", "manifest 와 아이콘도 인증 뒤에 있다")
def t_5():
    # 새 경로를 열어놓고 잊지 않도록. 공개는 /healthz 하나뿐이어야 합니다.
    import server.access as access
    for path in ("/manifest.webmanifest", "/icons/icon-192.png", "/m"):
        if path in access.PUBLIC_PATHS:
            raise AssertionError(f"{path} 가 인증 없이 열려 있음")


@case("L26-6", "홈 화면에서 연 것처럼 열어도 화면이 뜬다")
def t_6():
    # standalone 으로 열리면 start_url 로 바로 들어옵니다. 그 경로가 살아 있어야
    # 아이콘을 눌렀을 때 빈 화면이 나오지 않습니다.
    r = client.get("/m")
    if r.status_code != 200:
        raise AssertionError(f"/m HTTP {r.status_code}")
    if "m.js" not in r.text:
        raise AssertionError("/m 이 휴대폰 화면을 돌려주지 않음")


@case("L26-7", "배포 설정이 실제 동작과 일치한다")
def t_7():
    # autoDeploy 가 false 인데 실제로는 매 push 마다 배포되고 있었습니다. 파일이
    # 지키지 않는 정책을 적어두면, 배포가 "저절로" 된 것처럼 보여 사고로 읽힙니다.
    with io.open(os.path.join(ROOT, "render.yaml"), encoding="utf-8") as f:
        y = f.read()
    m = re.search(r"^\s*autoDeploy:\s*(\w+)", y, re.M)
    if not m:
        raise AssertionError("render.yaml 에 autoDeploy 가 없음")
    if m.group(1) != "true":
        raise AssertionError(f"autoDeploy={m.group(1)} — 실제로는 자동 배포됩니다")


if __name__ == "__main__":
    print("\n=== L26 홈 화면 추가 ===")
    sys.exit(1 if run_all("L26") else 0)
