# -*- coding: utf-8 -*-
"""
배포된 대시보드 점검.

로컬 테스트가 통과해도 배포본은 다른 환경입니다 — 리눅스, 다른 파이썬 빌드,
LSEG 데스크톱 없음, 공개 URL. 여기서만 드러나는 것들을 봅니다.

    set PRICER_AUTH_USER=... & set PRICER_AUTH_PASS=...
    python tests/live_deploy_check.py https://multipricer.onrender.com

자격증명 없이 돌리면 인증이 필요 없는 항목만 검사합니다.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

USER = os.environ.get("PRICER_AUTH_USER", "")
PASS = os.environ.get("PRICER_AUTH_PASS", "")

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def call(base, path, auth=False, method="GET", body=None, data=None,
         content_type=None, timeout=180):
    """Returns (status, headers, body_bytes). Never raises on an HTTP error."""
    req = urllib.request.Request(base + path, method=method)
    if auth and USER:
        token = base64.b64encode(f"{USER}:{PASS}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    elif data is not None:
        payload = data
        if content_type:
            req.add_header("Content-Type", content_type)
    def lower(headers):
        # Header names are case-insensitive on the wire; Render sends them lowercased,
        # so looking one up by the spelling in the RFC found nothing.
        return {k.lower(): v for k, v in dict(headers).items()}

    try:
        with urllib.request.urlopen(req, payload, timeout=timeout) as r:
            return r.status, lower(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, lower(e.headers), e.read()
    except Exception as e:
        return 0, {}, str(e).encode()


def multipart(fields):
    """Build one multipart body: [(name, filename, content_type, bytes)]."""
    boundary = "----pricercheck" + str(int(time.time()))
    out = b""
    for name, filename, ctype, blob in fields:
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
        out += blob + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out, f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------- 시나리오
def s1_available(base):
    """S1 서비스가 떠 있고, 헬스체크는 자격증명 없이 응답한다."""
    t0 = time.time()
    code, _, body = call(base, "/healthz")
    took = time.time() - t0
    record("S1-1 헬스체크 응답", code == 200, f"HTTP {code}, {took:.1f}s")
    try:
        record("S1-2 헬스체크 본문", json.loads(body)["status"] == "ok")
    except Exception:
        record("S1-2 헬스체크 본문", False, body[:60].decode("utf-8", "replace"))


def s2_access(base):
    """S2 공개 URL이므로 닫혀 있어야 하고, 브라우저가 로그인을 띄울 수 있어야 한다."""
    code, headers, _ = call(base, "/")
    record("S2-1 무인증 접근 차단", code == 401, f"HTTP {code}")
    record("S2-2 브라우저 인증창 유도",
           "basic" in (headers.get("www-authenticate", "") or "").lower(),
           headers.get("www-authenticate", "없음"))

    if USER:
        saved = globals()["PASS"]
        globals()["PASS"] = saved + "x"
        code, _, _ = call(base, "/", auth=True)
        globals()["PASS"] = saved
        record("S2-3 틀린 비밀번호 거부", code == 401, f"HTTP {code}")
        code, _, _ = call(base, "/", auth=True)
        record("S2-4 올바른 자격증명 통과", code == 200, f"HTTP {code}")

    # 업로드 엔드포인트도 함께 닫혀 있어야 한다 - 문서가 들어가는 입구이므로.
    data, ctype = multipart([("file", "x.pdf", "application/pdf", b"%PDF-1.4 x")])
    code, _, _ = call(base, "/api/termsheet/extract", method="POST",
                      data=data, content_type=ctype)
    record("S2-5 업로드 입구도 차단", code == 401, f"HTTP {code}")


def s3_assets(base):
    """S3 캐시된 예전 화면이 다시 나오지 않도록 자산이 스탬프를 달고 나온다."""
    if not USER:
        return
    code, headers, body = call(base, "/", auth=True)
    if code != 200:
        record("S3 정적 자산", False, f"대시보드 HTTP {code}")
        return
    html = body.decode("utf-8", "replace")
    record("S3-1 페이지 캐시 금지",
           "no-store" in (headers.get("cache-control", "") or ""),
           headers.get("cache-control", "없음"))
    stamps = dict(re.findall(r'(?:href|src)="([\w.-]+\.(?:js|css))\?v=([^"]+)"', html))
    record("S3-2 자산 버전 스탬프", len(stamps) >= 3, ", ".join(sorted(stamps)))
    record("S3-3 검토 팝업 마크업 포함", 'id="ts-modal-backdrop"' in html)
    bad = re.findall(r"[�]|[?][가-힣]|[가-힣][?]", html)
    record("S3-4 한글 깨짐 없음", not bad, str(sorted(set(bad))[:5]) if bad else "")


def s4_market(base):
    """S4 LSEG 데스크톱이 없는 환경이므로, 실시간이라고 말하면 안 된다."""
    if not USER:
        return
    code, _, body = call(base, "/api/market-snapshot", auth=True)
    if code != 200:
        record("S4 시장 데이터", False, f"HTTP {code}")
        return
    d = json.loads(body)["data"]
    record("S4-1 스냅샷 응답", len(d.get("quotes", [])) > 20,
           f"{len(d.get('quotes', []))}개 테너")
    record("S4-2 실시간이라 주장하지 않음", d.get("is_live_connected") is False,
           f"is_live_connected={d.get('is_live_connected')}")


def s5_pricing(base):
    """S5 프라이서 본연의 기능: 표준 스왑과 상각 스케줄이 제대로 계산되는가."""
    if not USER:
        return
    code, _, body = call(base, "/api/price", auth=True, method="POST", body={
        "notional": 100000000, "tenor": "5Y",
        "effective_date": "2026-09-23", "maturity_date": "2031-09-23",
        "fixed_coupon_pct": 3.65, "position": "Pay Fixed"})
    if code != 200:
        record("S5-1 USD 5Y 프라이싱", False, f"HTTP {code} {body[:120]}")
    else:
        pr = json.loads(body)["data"]["pricing_results"]
        ok = pr.get("dv01", 0) > 0 and 0 < pr.get("par_swap_rate_pct", 0) < 20
        record("S5-1 USD 5Y 프라이싱", ok,
               f"par={pr.get('par_swap_rate_pct')} DV01={pr.get('dv01'):,.2f}")

    # 상각 스케줄: 명목금액이 기간별로 반영되는지가 핵심.
    sched = "\n".join([
        "Start date\tEnd date\tPay date\tNominal\tFixing date",
        "2026-09-23\t2027-09-23\t2027-09-23\t100000000\t2026-09-21",
        "2027-09-23\t2028-09-23\t2028-09-25\t80000000\t2027-09-21",
        "2028-09-23\t2029-09-24\t2029-09-24\t60000000\t2028-09-21",
        "2029-09-24\t2030-09-23\t2030-09-23\t40000000\t2029-09-20",
        "2030-09-23\t2031-09-23\t2031-09-23\t20000000\t2030-09-19",
    ])
    code, _, body = call(base, "/api/price", auth=True, method="POST", body={
        "notional": 100000000, "tenor": "5Y",
        "effective_date": "2026-09-23", "maturity_date": "2031-09-23",
        "fixed_coupon_pct": 3.65, "position": "Pay Fixed",
        "leg1_raw_paste_text": sched, "leg2_raw_paste_text": sched})
    if code != 200:
        record("S5-2 상각 스케줄 프라이싱", False, f"HTTP {code} {body[:120]}")
        return
    legs = json.loads(body)["data"]["schedules"]
    rows = legs.get("leg1_fixed") or legs.get("leg1_schedule") or []
    got = [round(p["notional"]) for p in rows]
    want = [100000000, 80000000, 60000000, 40000000, 20000000]
    record("S5-2 상각 스케줄 프라이싱", got == want, f"{len(rows)}기간 원금 {got}")


def s6_termsheet(base):
    """S6 터미시트 경로: 분석 가능 상태인지, 정책이 지켜지는지."""
    if not USER:
        return
    code, _, body = call(base, "/api/termsheet/status", auth=True)
    if code != 200:
        record("S6-1 분석 가능 상태", False, f"HTTP {code}")
        return
    d = json.loads(body)["data"]
    record("S6-1 분석 가능 상태", bool(d.get("ready")),
           f"{d.get('provider_label')} {d.get('model')}")
    record("S6-2 교차검증 상태 정직하게 보고",
           d.get("cross_check") is False,
           "단일 모델 (Groq 키 없음)" if not d.get("cross_check") else "켜짐")

    # 이미지: 마스킹이 불가능한 유일한 경로라 배포본에서는 꺼 둠.
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
    data, ctype = multipart([("file", "scan.png", "image/png", png)])
    code, _, body = call(base, "/api/termsheet/extract", auth=True, method="POST",
                         data=data, content_type=ctype)
    detail = body.decode("utf-8", "replace")
    record("S6-3 이미지 업로드 정책대로 차단",
           code == 400 and "TERMSHEET_ALLOW_IMAGE" in detail,
           f"HTTP {code}")

    # 읽을 수 없는 파일은 모델로 보내기 전에 로컬에서 거절.
    data, ctype = multipart([("file", "junk.bin", "application/octet-stream",
                              b"\x00\x01\x02" * 60)])
    code, _, _ = call(base, "/api/termsheet/extract", auth=True, method="POST",
                      data=data, content_type=ctype)
    record("S6-4 읽을 수 없는 파일 거절", code // 100 == 4, f"HTTP {code}")


def s7_secrets(base):
    """S7 공개 URL이므로, 응답에 키나 내부 경로가 섞여 나가면 안 된다."""
    if not USER:
        return
    leaked = []
    for path in ("/", "/api/termsheet/status", "/api/termsheet/diagnostics"):
        code, _, body = call(base, path, auth=True)
        text = body.decode("utf-8", "replace")
        for pat, label in ((r"AQ\.[A-Za-z0-9_\-]{20,}", "Gemini 키"),
                           (r"sk-[A-Za-z0-9]{20,}", "Anthropic 키"),
                           (r"gsk_[A-Za-z0-9]{20,}", "Groq 키"),
                           (r"[A-Z]:\\\\(?:project|Users)", "윈도우 경로")):
            if re.search(pat, text):
                leaked.append(f"{path}:{label}")
    record("S7-1 응답에 키·내부경로 없음", not leaked, ", ".join(leaked))


def main():
    base = (sys.argv[1] if len(sys.argv) > 1
            else "https://multipricer.onrender.com").rstrip("/")
    print(f"\n=== 배포 점검: {base} ===")
    print(f"    자격증명: {'있음 (' + USER + ')' if USER else '없음 — 인증 항목 건너뜀'}\n")

    for fn in (s1_available, s2_access, s3_assets, s4_market,
               s5_pricing, s6_termsheet, s7_secrets):
        print(f"[{fn.__doc__.splitlines()[0]}]")
        try:
            fn(base)
        except Exception as e:
            record(fn.__name__, False, f"{type(e).__name__}: {e}")
        print()

    failed = [n for n, ok, _ in results if not ok]
    print(f"  {len(results) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("  실패:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
