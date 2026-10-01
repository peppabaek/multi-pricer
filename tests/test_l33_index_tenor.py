# -*- coding: utf-8 -*-
"""
L33 변동지수가 덮는 기간.

Murex 와 flow 를 대사했더니 leg2 금리가 매 기간 6~16bp 낮았습니다. 시장
데이터는 Murex 와 맞춰 놓은 상태였고 날짜도 고정일도 전부 같았습니다.

Murex 의 Index 열은 KRW KRCD 3M 인데 지급은 월별이었습니다. CD 91D 스왑의
변동다리는 지급주기와 무관하게 매번 3개월 CD 금리로 한 번 고정됩니다. 지급
기간으로 선도금리를 읽으면 우상향 커브에서 매번 더 짧은 - 더 낮은 - 금리를
읽게 됩니다.

    기간선도(1M)   3.152607  3.209095  3.268017 ...
    3M 지수        3.220000  3.321710  3.442832 ...
    Murex          3.220000  3.315464  3.426865 ...

지급기간이 지수보다 길면(반기 지급 등) 그 안에서 고정이 여러 번 일어나 복리로
쌓이고, 그 결과는 지급기간 선도금리와 사실상 같습니다. 그래서 창을 늘리기만
하고 줄이지는 않습니다 - 줄이면 반기 거래가 8.5bp 어긋납니다.
"""
import datetime
import sys

from harness import case, run_all

from krw_pricer.krw_curve_engine import bootstrap_krw_curve
from krw_pricer.krw_swap_engine import KRWSwapPricer
from krw_pricer.krw_date_engine import get_krw_spot_date
from server.calendar_manager import add_months, apply_convention

# 대사 당시 중계 호가. Murex 와 맞춰 놓은 그 화면입니다.
QUOTES = [
    ("ON", 3.1189), ("1M", 3.1522), ("2M", 3.1845), ("3M", 3.22),
    ("4M", 3.281), ("5M", 3.3398), ("6M", 3.405), ("9M", 3.5475),
    ("1Y", 3.6675), ("18M", 3.8425), ("2Y", 3.945), ("3Y", 4.0525),
    ("4Y", 4.1125), ("5Y", 4.15), ("6Y", 4.1725), ("7Y", 4.1925),
    ("8Y", 4.1975), ("9Y", 4.2075), ("10Y", 4.2175), ("12Y", 4.2275),
    ("15Y", 4.185), ("20Y", 4.06), ("25Y", 3.935), ("30Y", 3.77),
]
PD = datetime.date(2026, 10, 1)
ST = datetime.date(2026, 10, 2)
MAT = datetime.date(2027, 9, 30)

# 거래조건서 그대로 찍어 온 Murex 의 leg2 금리.
MUREX = [3.22, 3.315464128, 3.426865451, 3.608091585, 3.701821794, 3.788002852,
         3.844093381, 3.92109032, 3.985099937, 4.051242278, 4.083879521, 4.107882895]


def desk_pricer():
    return KRWSwapPricer(bootstrap_krw_curve(PD, ST, QUOTES))


def desk_trade(index_months):
    return desk_pricer().price_swap(
        notional=2_200_000_000.0, position="Pay Fixed", fixed_coupon_pct=3.654573,
        effective_date=ST, maturity_date=MAT, tenor_str="1Y",
        frequency_months=1, day_count="Act/365", leg1_frequency_months=1,
        leg2_frequency_months=1, leg2_index_tenor_months=index_months,
        calculate_greeks=False)


def gap_bp(rows):
    d = [abs(r["fwd_sofr_pct"] - m) * 100.0 for r, m in zip(rows, MUREX)]
    return sum(d) / len(d), max(d)


@case("L33-1", "월별 지급이라도 3개월 CD 금리로 고정된다")
def t_1():
    rows = desk_trade(3)["schedules"]["leg2_floating"]
    if len(rows) != len(MUREX):
        raise AssertionError(f"{len(MUREX)}개 기간을 기대했는데 {len(rows)}개")
    for r in rows:
        if r["index_end_date"] <= r["end_date"]:
            raise AssertionError(
                f"{r['start_date']}: 지수 구간이 지급기간({r['end_date']})을 "
                f"넘지 않음 - {r['index_end_date']}")
    # 첫 기간은 spot 에서 끊은 3개월이라 3M CD 호가와 같아야 합니다.
    if abs(rows[0]["fwd_sofr_pct"] - 3.22) > 1e-6:
        raise AssertionError(f"첫 기간이 3M CD 호가 3.22 가 아닌 {rows[0]['fwd_sofr_pct']}")


@case("L33-2", "Murex 대사 오차가 평균 3bp 안에 든다")
def t_2():
    mean, worst = gap_bp(desk_trade(3)["schedules"]["leg2_floating"])
    if mean > 3.0 or worst > 6.0:
        raise AssertionError(f"평균 {mean:.2f}bp, 최대 {worst:.2f}bp")


@case("L33-3", "지급기간으로 읽으면 Murex 와 크게 벌어진다")
def t_3():
    """고친 것이 실제로 이 차이를 메운 것인지 - 테스트가 늘 통과하면 안 됩니다."""
    mean, _ = gap_bp(desk_trade(None)["schedules"]["leg2_floating"])
    if mean < 6.0:
        raise AssertionError(
            f"지급기간 선도금리인데 Murex 와 {mean:.2f}bp 밖에 차이가 없음 - "
            "이 테스트가 고장을 못 잡습니다")


@case("L33-4", "분기·반기 거래는 그대로다")
def t_4():
    """
    표준 분기 CD 스왑은 지급기간이 곧 3개월이라 달라질 것이 없습니다. 여기서
    값이 움직이면 이미 체결된 거래의 평가가 바뀝니다.
    """
    pr = KRWSwapPricer(bootstrap_krw_curve(PD, get_krw_spot_date(PD)))

    def par(freq, idx):
        r = pr.price_swap(notional=1e10, position="Pay Fixed", fixed_coupon_pct=None,
                          tenor_str="5Y", frequency_months=freq,
                          leg1_frequency_months=freq, leg2_frequency_months=freq,
                          leg2_index_tenor_months=idx, calculate_greeks=False)
        return r["pricing_results"]["par_swap_rate_pct"], r["schedules"]["leg2_floating"]

    for freq, label in ((3, "분기"), (6, "반기")):
        before, _ = par(freq, None)
        after, rows = par(freq, 3)
        if abs(after - before) > 1e-6:
            raise AssertionError(
                f"{label} par 가 {before:.6f} 에서 {after:.6f} 로 움직임 "
                f"({(after - before) * 100:+.2f}bp)")
        off = [r["start_date"] for r in rows if r["index_end_date"] != r["end_date"]]
        if off:
            raise AssertionError(f"{label}: 지수 구간이 지급기간과 다른 기간 {off[:3]}")


@case("L33-5", "지수 구간은 조정 전 롤날짜에 걸린다")
def t_5():
    """
    조정된 시작일에서 3개월을 더하면, 시작일이 휴일로 밀린 기간마다 창도 같이
    밀립니다. 분기 거래인데 창이 지급기간과 어긋나던 이유입니다 - 20개 기간 중
    3개가 그랬습니다.
    """
    pr = KRWSwapPricer(bootstrap_krw_curve(PD, get_krw_spot_date(PD)))
    rows = pr.price_swap(notional=1e10, position="Pay Fixed", fixed_coupon_pct=None,
                         tenor_str="5Y", frequency_months=3, leg1_frequency_months=3,
                         leg2_frequency_months=3, leg2_index_tenor_months=3,
                         calculate_greeks=False)["schedules"]["leg2_floating"]
    drift = [r for r in rows
             if r["start_date"] != r["pay_date"] and r["index_end_date"] != r["end_date"]]
    if drift:
        raise AssertionError(f"조정된 시작일에서 창이 밀림: {drift[0]['start_date']}")


@case("L33-6", "요청에서 지수 기간을 고를 수 있다")
def t_6():
    from server.app import _resolve_index_months as f

    expected = {None: 3, "3M": 3, "1M": 1, "6M": 6, "1Y": 12,
                "": None, "Period": None, "뭐라고": None}
    for given, want in expected.items():
        got = f(given)
        if got != want:
            raise AssertionError(f"{given!r} -> {got!r}, 기대 {want!r}")


@case("L33-7", "지수 기간이 스케줄까지 전달된다")
def t_7():
    from fastapi.testclient import TestClient
    from server.app import app

    client = TestClient(app)
    body = {"currency": "KRW", "notional": 2_200_000_000, "position": "Pay Fixed",
            "tenor": "1Y", "fixed_coupon_pct": 3.65, "leg1_payment_freq": "1M",
            "leg2_payment_freq": "1M", "leg1_day_count": "Act/365"}
    rows = client.post("/api/krw/price", json=body).json()["data"]["schedules"]["leg2_floating"]
    if rows[0].get("index_tenor_months") != 3:
        raise AssertionError(f"기본값이 3M 이 아님: {rows[0].get('index_tenor_months')}")
    if rows[0]["index_end_date"] <= rows[0]["end_date"]:
        raise AssertionError("월별인데 지수 구간이 지급기간과 같음")

    rows = client.post("/api/krw/price", json=dict(body, leg2_index_tenor="Period")
                       ).json()["data"]["schedules"]["leg2_floating"]
    if rows[0]["index_end_date"] != rows[0]["end_date"]:
        raise AssertionError("Period 를 줬는데 지수 구간이 지급기간과 다름")


if __name__ == "__main__":
    print("\n=== L33 변동지수가 덮는 기간 ===")
    sys.exit(1 if run_all("L33") else 0)
