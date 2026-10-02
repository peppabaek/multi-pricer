# -*- coding: utf-8 -*-
"""
L36 지나간 기간은 그날 실제로 고시된 금리로 계산한다.

개시일이 오늘보다 앞선 거래조건서를 올리면 첫 몇 기간은 이미 시작돼 있고,
그 금리는 과거 고시일에 정해져 있습니다. 커브에는 없습니다 - 커브는 오늘
이후만 말합니다. 지금까지는 같은 길이의 구간을 spot 에서 끊어 추정했고
(rate_source "Estimated"), 실제 고시치와는 당연히 달랐습니다.

실제 거래조건서(IRS-Pay-CD-260918)의 첫 변동금리결정일은 2026-09-17 이고,
그날 KOFIA 가 고시한 CD 91D 는 3.20 입니다. 추정치가 아니라 그 값을 써야
합니다.

찾는 순서는 하나뿐입니다:

    거래조건서/trader 가 준 fixing  >  고시 이력  >  커브 추정  >  선도금리
         "Fixing"                     "Historical"   "Estimated"   "Forward"
"""
import datetime
import os
import shutil
import sys
import tempfile

# 캐시 파일을 테스트용으로 격리합니다. 데스크의 진짜 이력을 건드리면 안 되고,
# 반대로 그 이력에 기대서도 안 됩니다 - 기계마다 다릅니다.
_TMP = tempfile.mkdtemp(prefix="l36-fixings-")
os.environ["PRICER_DATA_DIR"] = _TMP

from harness import case, run_all

from server.fixing_history import fixing_history, lookup
from server.calendar_manager import floating_rate_for_period

D = datetime.date
TODAY = D.today()


def reset(seed=None):
    fixing_history._cache = {}
    fixing_history._loaded = True
    if seed:
        fixing_history.put("KRW_CD_91D", seed)


class Curve:
    """오늘 이후는 3%, 그 전은 커브가 말하지 않는다."""
    pricing_date = TODAY
    settle_date = TODAY + datetime.timedelta(days=1)

    @staticmethod
    def rate_fn(a, b):
        return 0.03


@case("L36-1", "넣은 고시치를 그대로 돌려준다")
def t_1():
    reset({"2026-09-17": 3.20, "2026-09-18": 3.21})
    rate, used = fixing_history.get("KRW_CD_91D", D(2026, 9, 17))
    if rate != 3.20 or used != "2026-09-17":
        raise AssertionError(f"{rate} / {used}")
    if fixing_history.get("KRW_CD_91D", D(2026, 9, 18))[0] != 3.21:
        raise AssertionError("두 번째 날짜를 못 읽음")


@case("L36-2", "이미 가진 날짜는 덮지 않는다")
def t_2():
    """
    한 번 고시된 값은 바뀌지 않습니다. 덮어쓰기를 허용하면 중계가 한 번
    잘못 보낸 값이 진실이 돼 버립니다.
    """
    reset({"2026-09-17": 3.20})
    added = fixing_history.put("KRW_CD_91D", {"2026-09-17": 9.99, "2026-09-18": 3.21})
    if added != 1:
        raise AssertionError(f"새로 들어간 날짜가 {added}개 (기대 1)")
    if fixing_history.get("KRW_CD_91D", D(2026, 9, 17))[0] != 3.20:
        raise AssertionError("기존 값이 덮임")


@case("L36-3", "고시일이 비면 직전 영업일로 거슬러 간다")
def t_3():
    """고시일이 휴일로 잡히는 일이 있습니다. 다만 한없이 거슬러 가지는 않습니다."""
    reset({"2026-09-17": 3.20})
    rate, used = fixing_history.get("KRW_CD_91D", D(2026, 9, 19))   # 이틀 뒤
    if rate != 3.20 or used != "2026-09-17":
        raise AssertionError(f"직전 값을 못 찾음: {rate} / {used}")
    if fixing_history.get("KRW_CD_91D", D(2026, 10, 1))[0] is not None:
        raise AssertionError("2주 전 값을 끌어옴 - 데이터가 없는 것으로 봐야 합니다")


@case("L36-4", "말이 안 되는 입력은 받지 않는다")
def t_4():
    reset()
    added = fixing_history.put("KRW_CD_91D", {
        "2026-09-17": 3.20, "어제": 3.1, "2026-13-45": 3.1, "2026-09-18": "삼점이"})
    if added != 1:
        raise AssertionError(f"{added}개가 들어감 - 날짜·숫자만 받아야 합니다")


@case("L36-5", "찾는 순서: 주어진 fixing > 고시 이력 > 추정")
def t_5():
    past = TODAY - datetime.timedelta(days=13)
    end = TODAY + datetime.timedelta(days=17)
    reset({past.isoformat(): 3.55})
    fn = lookup("KRW_CD_91D")

    # 1. 주어진 fixing 이 가장 세다
    r, src = floating_rate_for_period(Curve, past, end, Curve.rate_fn,
                                      fixing=0.04, history_fn=fn,
                                      fixing_date=past, scale=0.01)
    if src != "Fixing" or abs(r - 0.04) > 1e-12:
        raise AssertionError(f"{src} {r}")

    # 2. 없으면 고시 이력
    r, src = floating_rate_for_period(Curve, past, end, Curve.rate_fn,
                                      history_fn=fn, fixing_date=past, scale=0.01)
    if src != "Historical" or abs(r - 0.0355) > 1e-12:
        raise AssertionError(f"{src} {r} - 고시 3.55% 를 소수로 바꿔 써야 합니다")

    # 3. 이력에도 없으면 추정
    reset()
    r, src = floating_rate_for_period(Curve, past, end, Curve.rate_fn,
                                      history_fn=fn, fixing_date=past, scale=0.01)
    if src != "Estimated":
        raise AssertionError(f"이력이 비었는데 {src}")


@case("L36-6", "오늘 이후 시작하는 기간은 선도금리 그대로다")
def t_6():
    """
    아직 고시되지 않은 기간에 과거 값을 끌어다 쓰면 안 됩니다.
    """
    fut = TODAY + datetime.timedelta(days=5)
    reset({(TODAY - datetime.timedelta(days=1)).isoformat(): 9.99})
    r, src = floating_rate_for_period(Curve, fut, fut + datetime.timedelta(days=30),
                                      Curve.rate_fn, history_fn=lookup("KRW_CD_91D"),
                                      fixing_date=fut, scale=0.01)
    if src != "Forward":
        raise AssertionError(f"미래 기간인데 {src} {r}")


@case("L36-7", "이력이 있으면 프라이싱이 그 값을 쓴다")
def t_7():
    """엔진까지 실제로 닿는가. 모듈만 맞고 연결이 빠지면 아무 소용이 없습니다."""
    from fastapi.testclient import TestClient
    from server.app import app

    start = TODAY - datetime.timedelta(days=13)
    fix_on = start - datetime.timedelta(days=1)
    reset({fix_on.isoformat(): 3.55})

    rows = [(start, start + datetime.timedelta(days=30)),
            (start + datetime.timedelta(days=30), start + datetime.timedelta(days=60))]
    text = "Start date\tEnd date\tPay date\tNominal\n" + "\n".join(
        f"{a}\t{b}\t{b}\t2500000000" for a, b in rows)
    d = TestClient(app).post("/api/krw/price", json={
        "currency": "KRW", "notional": 2_500_000_000, "position": "Pay Fixed",
        "tenor": "2M", "leg1_day_count": "Act/365", "leg1_payment_freq": "1M",
        "leg2_payment_freq": "1M", "fixed_coupon_pct": 3.3,
        "raw_paste_text": text, "leg1_raw_paste_text": text,
        "leg2_raw_paste_text": text}).json()["data"]
    first = d["schedules"]["leg2_floating"][0]
    if first.get("rate_source") != "Historical":
        raise AssertionError(f"첫 기간 출처가 {first.get('rate_source')}")
    if abs(first["fwd_sofr_pct"] - 3.55) > 1e-6:
        raise AssertionError(f"고시 3.55 인데 {first['fwd_sofr_pct']}")
    if d["schedules"]["leg2_floating"][1].get("rate_source") != "Forward":
        raise AssertionError("둘째 기간까지 이력으로 덮임")


@case("L36-8", "데스크가 올린 고시치를 서버가 받는다")
def t_8():
    """호스팅에는 Workspace 가 없습니다. 호가와 같은 길로 받아야 합니다."""
    from fastapi.testclient import TestClient
    from server.app import app

    reset()
    c = TestClient(app)
    r = c.post("/api/fixings/push", json={
        "index": "KRW_CD_91D", "fixings": {"2026-09-17": 3.20, "2026-09-18": 3.21}})
    if r.status_code != 200 or r.json()["data"]["added"] != 2:
        raise AssertionError(f"{r.status_code} {r.text[:120]}")
    again = c.post("/api/fixings/push", json={
        "index": "KRW_CD_91D", "fixings": {"2026-09-17": 9.99}}).json()["data"]
    if again["added"] != 0:
        raise AssertionError("다시 보낸 값이 덮였습니다")
    cov = c.get("/api/fixings/status?index=KRW_CD_91D").json()["data"]
    if cov["count"] != 2 or cov["first"] != "2026-09-17":
        raise AssertionError(f"보유 구간이 {cov}")


if __name__ == "__main__":
    print("\n=== L36 지나간 기간의 고시치 ===")
    code = 1 if run_all("L36") else 0
    shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(code)
