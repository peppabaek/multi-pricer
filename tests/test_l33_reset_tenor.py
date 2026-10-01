# -*- coding: utf-8 -*-
"""
L33 변동다리의 reset tenor 와 고시 기준.

Murex 와 flow 를 대사했더니 leg2 금리가 매 기간 6~16bp 낮았습니다. 마켓
데이터는 Murex 와 같았고(데스크가 O/N~5M 을 수기로 맞춤) 커브 구성도 같았으니
- 6M 미만은 O/N 과 3M CD 만 물리고 나머지는 보간, forecast 와 discount 는 같은
KRWIRS 커브 - 남는 것은 커브를 읽는 방법뿐이었습니다.

거꾸로 풀어 보면 분명합니다. Murex 의 월별 금리를 지급기간 선도금리로 읽으면
3M 이 3.3326% 인 커브가 나옵니다. 데스크가 넣은 값은 3.2200% 입니다:

    tenor   수기입력   Murex flow 가 함의
    3M      3.2200     3.3326   (+11.3bp)
    6M      3.4050     3.5316
    1Y      3.6675     3.8156

단일 커브에서 첫 세 달은 3M 필러 구간을 정확히 덮으므로, 그 선도금리들의
복리는 보간과 무관하게 3M 호가일 수밖에 없습니다. Murex 쪽은 그 관계 밖에
있었습니다.

데스크 확인 결과 Pay 1M / Reset 3M 이었습니다. 지급은 매달 하지만 금리는 매번
3개월 CD 로 고정됩니다. 그리고 flow 를 역산해 보니 발생이자는 30/360 인데
금리 자체는 Act/365 로 고시돼 있었습니다 - 둘을 같은 것으로 쓰면 연율 환산이
어긋나 쿠폰이 1.9% 틀어집니다.
"""
import datetime
import sys

from harness import case, run_all

from krw_pricer.krw_curve_engine import bootstrap_krw_curve
from krw_pricer.krw_swap_engine import KRWSwapPricer
from krw_pricer.krw_date_engine import apply_krw_convention, get_krw_spot_date
from server.calendar_manager import add_months

# 데스크가 Murex 에 맞춰 수기로 넣은 미드.
QUOTES = [
    ("ON", 3.1189), ("1M", 3.1522), ("2M", 3.1845), ("3M", 3.2200),
    ("4M", 3.2818), ("5M", 3.3414), ("6M", 3.405), ("9M", 3.5475),
    ("1Y", 3.6675), ("18M", 3.8425), ("2Y", 3.945), ("3Y", 4.0525),
    ("4Y", 4.1125), ("5Y", 4.15), ("6Y", 4.1725), ("7Y", 4.1925),
    ("8Y", 4.1975), ("9Y", 4.2075), ("10Y", 4.2175), ("12Y", 4.2275),
    ("15Y", 4.185), ("20Y", 4.06), ("25Y", 3.935), ("30Y", 3.77),
]
PD = datetime.date(2026, 10, 1)
ST = datetime.date(2026, 10, 2)
MAT = datetime.date(2027, 9, 30)
D = datetime.date

# 거래조건서 그대로 찍어 온 Murex 의 leg2 금리와 flow.
MUREX_RATE = [3.22, 3.315464128, 3.426865451, 3.608091585, 3.701821794,
              3.788002852, 3.844093381, 3.92109032, 3.985099937, 4.051242278,
              4.083879521, 4.107882895]
MUREX_FLOW = [5903333.33, 6078350.90, 6687914.83, 6188071.05, 6786673.29,
              6944671.90, 7517338.17, 6724880.71, 7306016.55, 7427277.51,
              7487112.46, 6802300.71]


def desk_curve(quotes=None):
    return bootstrap_krw_curve(PD, ST, quotes or QUOTES)


def desk_rows(day_count="Act/365", **kw):
    return KRWSwapPricer(desk_curve()).price_swap(
        notional=2_200_000_000.0, position="Pay Fixed", fixed_coupon_pct=3.654573,
        effective_date=ST, maturity_date=MAT, tenor_str="1Y", frequency_months=1,
        leg1_day_count="Act/365", leg2_day_count=day_count,
        leg1_frequency_months=1, leg2_frequency_months=1,
        calculate_greeks=False, **kw)["schedules"]["leg2_floating"]


def compound_over_first_quarter(curve, cd_quote):
    """첫 세 달을 복리로 쌓아 94일 단순금리로 환산한 값."""
    mat3m = apply_krw_convention(add_months(ST, 3), "Modified Following", None)
    periods = [(D(2026, 10, 2), D(2026, 11, 2)), (D(2026, 11, 2), D(2026, 12, 2)),
               (D(2026, 12, 2), mat3m)]
    g = 1.0
    for a, b in periods:
        g *= 1.0 + curve.get_forward_rate(a, b, "Act/365") * ((b - a).days / 365.0)
    return (g - 1.0) * 365.0 / (mat3m - ST).days * 100.0


@case("L33-1", "3개월 안쪽 기간들이 3M CD 호가로 정확히 복리된다")
def t_1():
    """
    일정표와 마켓 데이터만으로 계산한다는 것이 무슨 뜻인지의 전부입니다.
    어긋나면 커브 안에 차익거래가 있는 겁니다.
    """
    got = compound_over_first_quarter(desk_curve(), 3.22)
    if abs(got - 3.22) > 1e-6:
        raise AssertionError(f"3M CD 3.2200% 여야 하는데 {got:.6f}% - 커브에 차익거래")


@case("L33-2", "호가 모양이 달라져도 같은 관계가 성립한다")
def t_2():
    for cd in (1.50, 3.22, 5.75):
        c = desk_curve([(t, cd if t == "3M" else m) for t, m in QUOTES])
        got = compound_over_first_quarter(c, cd)
        if abs(got - cd) > 1e-6:
            raise AssertionError(f"3M CD {cd}% 인데 복리가 {got:.6f}%")


@case("L33-3", "6M 미만 필러는 O/N 과 3M 뿐이다")
def t_3():
    """
    Murex 의 KRWIRS 커브가 그렇게 구성돼 있습니다. 한 번 1M·2M·4M·5M 을
    전부 필러로 세워 봤지만, 실제 호가로는 이 거래 선도금리가 0.1bp 도
    움직이지 않았고 Murex 와의 차이도 그대로였습니다.
    """
    short = [p["tenor"] for p in desk_curve().pillars if p["months"] <= 5]
    if short != ["ON", "3M"]:
        raise AssertionError(f"6M 미만 필러가 O/N·3M 이 아님: {short}")


@case("L33-4", "기본 reset tenor 는 3개월이다")
def t_4():
    """Murex Reset 3M / Pay 1M. 월별 지급이어도 금리는 3개월짜리입니다."""
    rows = desk_rows()
    if rows[0].get("reset_tenor_months") != 3:
        raise AssertionError(f"기본 reset tenor 가 3 이 아님: {rows[0].get('reset_tenor_months')}")
    short = [r["start_date"] for r in rows if r["reset_end_date"] <= r["end_date"]]
    if short:
        raise AssertionError(f"월별인데 reset 창이 지급기간을 넘지 않음: {short[:3]}")
    if abs(rows[0]["fwd_sofr_pct"] - 3.22) > 1e-6:
        raise AssertionError(f"첫 기간이 3M CD 호가가 아닌 {rows[0]['fwd_sofr_pct']}")


@case("L33-5", "Murex 금리와 평균 3bp 안에 든다")
def t_5():
    rows = desk_rows()
    g = [abs(r["fwd_sofr_pct"] - m) * 100.0 for r, m in zip(rows, MUREX_RATE)]
    mean, worst = sum(g) / len(g), max(g)
    if mean > 3.0 or worst > 6.0:
        raise AssertionError(f"평균 {mean:.2f}bp, 최대 {worst:.2f}bp")


@case("L33-6", "지급기간으로 읽으면 Murex 와 크게 벌어진다")
def t_6():
    """고친 것이 실제로 이 차이를 메운 것인지 - 늘 통과하면 안 됩니다."""
    rows = desk_rows(leg2_reset_tenor_months=None)
    g = [abs(r["fwd_sofr_pct"] - m) * 100.0 for r, m in zip(rows, MUREX_RATE)]
    if sum(g) / len(g) < 6.0:
        raise AssertionError(
            f"지급기간 선도금리인데 Murex 와 {sum(g) / len(g):.2f}bp 뿐 - 고장을 못 잡습니다")


@case("L33-7", "reset 창은 지급기간을 줄이지 않는다")
def t_7():
    """
    지급기간이 reset 보다 길면 그 안에서 고정이 여러 번 일어나 복리로 쌓이고,
    그 결과는 지급기간 선도금리와 사실상 같습니다. 3개월을 강제하면 반기
    거래가 8.5bp 어긋납니다.
    """
    today = datetime.date.today()
    pr = KRWSwapPricer(bootstrap_krw_curve(today, get_krw_spot_date(today)))

    def par(freq, reset):
        return pr.price_swap(
            notional=1e10, position="Pay Fixed", fixed_coupon_pct=None,
            tenor_str="5Y", frequency_months=freq, leg1_frequency_months=freq,
            leg2_frequency_months=freq, leg2_reset_tenor_months=reset,
            calculate_greeks=False)["pricing_results"]["par_swap_rate_pct"]

    for freq, label in ((3, "분기"), (6, "반기")):
        a, b = par(freq, None), par(freq, 3)
        if abs(a - b) > 1e-6:
            raise AssertionError(
                f"{label} 가 reset 3M 으로 {(b - a) * 100:+.2f}bp 움직임 - 창이 줄어듦")


@case("L33-8", "이자를 30/360 으로 붙여도 금리는 Act/365 로 고시된다")
def t_8():
    """
    Murex 의 첫 flow 5,903,333.33 = 2.2e9 x 3.22% x 30/360 입니다. 금리는
    Act/365 고시치 그대로이고 30/360 은 이자를 붙이는 쪽에만 걸립니다.
    둘을 같은 것으로 쓰면 3.22% 가 다른 숫자로 환산돼 버립니다.
    """
    rows = desk_rows(day_count="30/360")
    if abs(rows[0]["fwd_sofr_pct"] - 3.22) > 1e-6:
        raise AssertionError(
            f"이자 기준을 30/360 으로 바꿨더니 금리가 {rows[0]['fwd_sofr_pct']} 로 변함")
    if abs(rows[0]["cash_flow"] - MUREX_FLOW[0]) > 0.01:
        raise AssertionError(
            f"첫 flow {rows[0]['cash_flow']:,.2f} vs Murex {MUREX_FLOW[0]:,.2f}")

    # 고시 기준을 억지로 바꾸면 달라져야 합니다 - 분리가 실제로 동작하는지.
    forced = desk_rows(day_count="30/360", leg2_index_day_count="30/360")
    if abs(forced[0]["fwd_sofr_pct"] - rows[0]["fwd_sofr_pct"]) < 1e-6:
        raise AssertionError("고시 기준을 바꿨는데 금리가 그대로 - 분리가 안 됨")


@case("L33-9", "요청에서 reset tenor 와 고시 기준을 고를 수 있다")
def t_9():
    from server.app import _resolve_reset_months as f

    for given, want in {None: 3, "3M": 3, "1M": 1, "6M": 6, "1Y": 12,
                        "": None, "Period": None, "뭐라고": None}.items():
        if f(given) != want:
            raise AssertionError(f"{given!r} -> {f(given)!r}, 기대 {want!r}")

    from fastapi.testclient import TestClient
    from server.app import app
    body = {"currency": "KRW", "notional": 2_200_000_000, "position": "Pay Fixed",
            "tenor": "1Y", "fixed_coupon_pct": 3.65, "leg1_payment_freq": "1M",
            "leg2_payment_freq": "1M", "leg1_day_count": "Act/365"}
    c = TestClient(app)
    rows = c.post("/api/krw/price", json=body).json()["data"]["schedules"]["leg2_floating"]
    if rows[0]["reset_end_date"] <= rows[0]["end_date"]:
        raise AssertionError("기본 reset 3M 인데 창이 길어지지 않음")
    rows = c.post("/api/krw/price", json=dict(body, leg2_reset_tenor="Period")
                  ).json()["data"]["schedules"]["leg2_floating"]
    if rows[0]["reset_end_date"] != rows[0]["end_date"]:
        raise AssertionError("Period 를 줬는데 창이 지급기간과 다름")


@case("L33-10", "분기 거래의 par 는 호가를 되돌려준다")
def t_10():
    """부트스트랩이나 투영이 흔들리면 여기서 먼저 틀어집니다."""
    pr = KRWSwapPricer(desk_curve())
    quoted = dict(QUOTES)
    for tenor in ("1Y", "5Y", "10Y"):
        par = pr.price_swap(
            notional=1e10, position="Pay Fixed", fixed_coupon_pct=None,
            effective_date=ST, tenor_str=tenor, frequency_months=3,
            leg1_frequency_months=3, leg2_frequency_months=3,
            calculate_greeks=False)["pricing_results"]["par_swap_rate_pct"]
        if abs(par - quoted[tenor]) > 0.01:
            raise AssertionError(f"{tenor} par {par:.4f} 가 호가 {quoted[tenor]} 와 다름")


if __name__ == "__main__":
    print("\n=== L33 reset tenor 와 고시 기준 ===")
    sys.exit(1 if run_all("L33") else 0)
