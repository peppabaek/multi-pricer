# -*- coding: utf-8 -*-
"""
L32 이미 시작된 변동기간.

Murex 와 대사했더니 20bp 넘게 벌어졌고, leg2 첫 기간의 금리가 1.776992% 라는
설명되지 않는 값이었습니다.

거래조건서의 개시일이 오늘보다 앞서면 첫 변동기간은 이미 시작돼 있습니다.
그 기간의 금리를 선도금리 공식에 그대로 넣으면

    F = (DF(start) / DF(end) - 1) / tau

DF 는 과거 날짜에서 1.0 으로 잘리는데 tau 는 기간 전체를 세기 때문에, 분자는
오늘부터 끝까지만 자라고 분모는 처음부터 끝까지를 셉니다. 결과는 정확히

    실제 금리 x (남은 일수 / 전체 일수)

30일 중 13일이 지난 기간에서 2.832% 가 1.605% 로 나왔습니다. 첫 쿠폰이 그만큼
줄어드니 par 도 30bp 가까이 내려갑니다.

이미 시작된 기간의 금리는 사실 과거 고정일에 정해져 있습니다. 커브에는 없으니
주어진 fixing 을 먼저 쓰고, 없으면 같은 길이의 기간을 spot 에서 끊어 추정합니다.
"""
import datetime
import os
import sys

from harness import case, run_all

from fastapi.testclient import TestClient
from server.app import app

client = TestClient(app)

TODAY = datetime.date.today()
D = datetime.timedelta


def rows(n=4, span=30, started=13):
    """첫 기간이 오늘을 가로지르는 월별 일정표."""
    start = TODAY - D(started)
    out = []
    for i in range(n):
        a = start + D(span * i)
        out.append((a.isoformat(), (a + D(span)).isoformat()))
    return out


def sheet(rs, notional=2_500_000_000):
    body = "\n".join(f"{a}\t{b}\t{b}\t{notional}" for a, b in rs)
    return "Start date\tEnd date\tPay date\tNominal\n" + body


def price(path, ccy, rs, **extra):
    text = sheet(rs)
    body = {"currency": ccy, "notional": 2_500_000_000, "position": "Pay Fixed",
            "tenor": "4M", "leg1_day_count": "Act/365", "leg1_payment_freq": "1M",
            "leg2_payment_freq": "1M", "fixed_coupon_pct": 3.3,
            "raw_paste_text": text, "leg1_raw_paste_text": text,
            "leg2_raw_paste_text": text}
    body.update(extra)
    r = client.post(path, json=body)
    if r.status_code != 200:
        raise AssertionError(f"{ccy} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["data"]


ENGINES = (("/api/krw/price", "KRW"), ("/api/price", "USD"),
           ("/api/kofr/price", "KRW_KOFR"))


@case("L32-1", "이미 시작된 첫 기간이 남은일수/전체일수 만큼 깎이지 않는다")
def t_1():
    rs = rows()
    span, started = 30, 13
    for path, ccy in ENGINES:
        leg2 = price(path, ccy, rs)["schedules"]["leg2_floating"]
        first = leg2[0]["fwd_sofr_pct"]
        nxt = leg2[1]["fwd_sofr_pct"]
        # 깎인 값은 이웃 기간의 (30-13)/30 = 0.567 배 언저리에 내려앉습니다.
        if first < nxt * 0.80:
            raise AssertionError(
                f"{ccy}: 첫 기간 {first}% 가 다음 기간 {nxt}% 에 비해 깎임 "
                f"(남은일수 비율 {(span - started) / span:.3f})")


@case("L32-2", "시작된 기간은 추정치라고 밝힌다")
def t_2():
    rs = rows()
    for path, ccy in ENGINES:
        leg2 = price(path, ccy, rs)["schedules"]["leg2_floating"]
        if leg2[0].get("rate_source") != "Estimated":
            raise AssertionError(f"{ccy}: 첫 기간 출처 {leg2[0].get('rate_source')}")
        if leg2[1].get("rate_source") != "Forward":
            raise AssertionError(f"{ccy}: 둘째 기간 출처 {leg2[1].get('rate_source')}")


@case("L32-3", "주어진 first fixing 을 그대로 쓴다")
def t_3():
    rs = rows()
    for path, ccy in ENGINES:
        leg2 = price(path, ccy, rs, first_fixing_pct=3.55)["schedules"]["leg2_floating"]
        if abs(leg2[0]["fwd_sofr_pct"] - 3.55) > 1e-4:
            raise AssertionError(f"{ccy}: fixing 3.55 를 줬는데 {leg2[0]['fwd_sofr_pct']}")
        if leg2[0].get("rate_source") != "Fixing":
            raise AssertionError(f"{ccy}: 출처 {leg2[0].get('rate_source')}")
        # 둘째 기간까지 덮어쓰면 안 됩니다.
        if abs(leg2[1]["fwd_sofr_pct"] - 3.55) < 1e-6:
            raise AssertionError(f"{ccy}: fixing 이 둘째 기간까지 번짐")


@case("L32-4", "fixing 은 par 를 실제로 움직인다")
def t_4():
    """첫 쿠폰 하나가 par 를 수십 bp 움직입니다 - 조용히 무시되면 안 됩니다."""
    rs = rows()
    lo = price("/api/krw/price", "KRW", rs,
               first_fixing_pct=1.60)["pricing_results"]["par_swap_rate_pct"]
    hi = price("/api/krw/price", "KRW", rs,
               first_fixing_pct=3.55)["pricing_results"]["par_swap_rate_pct"]
    gap_bp = (hi - lo) * 100.0
    if gap_bp < 20.0:
        raise AssertionError(f"fixing 195bp 차이가 par 를 {gap_bp:.2f}bp 밖에 못 움직임")


@case("L32-5", "오늘 이후에 시작하는 스왑은 건드리지 않는다")
def t_5():
    """spot 시작 표준 스왑의 par 는 이 수정 전후로 같아야 합니다."""
    r = client.post("/api/krw/price", json={
        "currency": "KRW", "notional": 10_000_000_000, "position": "Pay Fixed",
        "tenor": "1Y", "fixed_coupon_pct": 3.72})
    d = r.json()["data"]
    leg2 = d["schedules"]["leg2_floating"]
    if any(p.get("rate_source") != "Forward" for p in leg2):
        raise AssertionError(
            f"spot 시작인데 추정으로 표시: {[p.get('rate_source') for p in leg2]}")
    par = d["pricing_results"]["par_swap_rate_pct"]
    if abs(par - 3.5075) > 1e-4:
        raise AssertionError(f"baseline 1Y par 가 3.5075 에서 {par} 로 움직임")


@case("L32-6", "기간별 fixing 을 커스텀 스케줄에서 받는다")
def t_6():
    from server.calendar_manager import floating_rate_for_period

    class Curve:
        pricing_date = TODAY
        settle_date = TODAY + D(1)

        def get_forward_rate(self, a, b, dc=None):
            return 0.03

    c = Curve()
    past = TODAY - D(13)
    fut = TODAY + D(17)

    rate, src = floating_rate_for_period(c, past, fut,
                                         lambda a, b: c.get_forward_rate(a, b))
    if src != "Estimated":
        raise AssertionError(f"과거 시작인데 {src}")
    rate, src = floating_rate_for_period(c, TODAY + D(1), fut,
                                         lambda a, b: c.get_forward_rate(a, b))
    if src != "Forward":
        raise AssertionError(f"미래 시작인데 {src}")
    rate, src = floating_rate_for_period(c, past, fut,
                                         lambda a, b: c.get_forward_rate(a, b),
                                         fixing=0.0355)
    if src != "Fixing" or abs(rate - 0.0355) > 1e-12:
        raise AssertionError(f"fixing 을 줬는데 {src} {rate}")


@case("L32-7", "추정 구간은 같은 길이의 기간을 spot 에서 읽는다")
def t_7():
    """
    추정치는 '오늘부터 끝까지' 가 아니라 '기간과 같은 길이' 여야 합니다.
    남은 토막으로 읽으면 커브가 가파를 때 또 어긋납니다.
    """
    from server.calendar_manager import floating_rate_for_period

    seen = {}

    class Curve:
        pricing_date = TODAY
        settle_date = TODAY + D(1)

    def rate_fn(a, b):
        seen["span"] = (b - a).days
        seen["start"] = a
        return 0.03

    c = Curve()
    floating_rate_for_period(c, TODAY - D(13), TODAY + D(17), rate_fn)
    if seen["span"] != 30:
        raise AssertionError(f"기간 길이 30일이 아닌 {seen['span']}일로 읽음")
    if seen["start"] != c.settle_date:
        raise AssertionError(f"spot({c.settle_date}) 가 아닌 {seen['start']} 에서 읽음")


if __name__ == "__main__":
    print("\n=== L32 이미 시작된 변동기간 ===")
    sys.exit(1 if run_all("L32") else 0)
