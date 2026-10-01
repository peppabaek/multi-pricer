# -*- coding: utf-8 -*-
"""
L33 일정표와 마켓 데이터만으로 계산하는 변동다리.

Murex 와 flow 를 대사했더니 leg2 금리가 매 기간 6~16bp 낮았습니다. 원인을
찾다가 커브에서 두 가지가 나왔습니다.

하나는 진짜 고장입니다. 6M 미만 필러가 ON 과 3M CD 둘뿐이고 그 사이가
직선이었습니다. 데스크가 손으로 넣는 O/N~5M 호가 중 1M·2M·4M·5M 은 커브에
들어가지 않아, 전부에 200bp 를 더해도 가격이 1원도 움직이지 않았습니다.

다른 하나는 고장이 아닙니다. 일정표의 첫 세 달(2026-10-02 ~ 2027-01-04)은
3M CD 구간을 정확히 덮습니다. 그러니 그 세 기간의 선도금리를 복리로 쌓으면
3M CD 호가가 그대로 나와야 하고, 실제로 나옵니다:

    커브 선도금리  3.152200  3.209285  3.268228  ->  94일 환산 3.220000%
    Murex          3.220000  3.315464  3.426865  ->  94일 환산 3.332561%
    3M CD 호가                                                  3.220000%

일정표와 마켓 데이터만으로 계산하면 3.220000% 말고 다른 값이 나올 수 없습니다.
Murex 쪽 11.3bp 는 그 관계 밖에 있어 커브 보간으로는 메울 수 없습니다. 맞추려면
leg2_index_tenor 로 투영 구간을 명시해야 하며, 기본값은 지급기간 - 일정표
그대로입니다.
"""
import datetime
import sys

from harness import case, run_all

from krw_pricer.krw_curve_engine import bootstrap_krw_curve
from krw_pricer.krw_swap_engine import KRWSwapPricer
from krw_pricer.krw_date_engine import apply_krw_convention, get_krw_spot_date
from server.calendar_manager import add_months

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
D = datetime.date


def desk_curve(quotes=None):
    return bootstrap_krw_curve(PD, ST, quotes or QUOTES)


def desk_rows(curve, index_months=None):
    return KRWSwapPricer(curve).price_swap(
        notional=2_200_000_000.0, position="Pay Fixed", fixed_coupon_pct=3.654573,
        effective_date=ST, maturity_date=D(2027, 9, 30), tenor_str="1Y",
        frequency_months=1, day_count="Act/365", leg1_frequency_months=1,
        leg2_frequency_months=1, leg2_index_tenor_months=index_months,
        calculate_greeks=False)["schedules"]["leg2_floating"]


@case("L33-1", "3개월 안쪽 기간들이 3M CD 호가로 정확히 복리된다")
def t_1():
    """
    일정표와 마켓 데이터만으로 계산한다는 것이 무슨 뜻인지의 전부입니다.
    첫 세 달이 3M CD 구간을 정확히 덮으므로, 그 세 선도금리를 쌓은 값은
    3M CD 호가와 같아야 합니다. 어긋나면 커브 안에 차익거래가 있는 겁니다.
    """
    c = desk_curve()
    mat3m = apply_krw_convention(add_months(ST, 3), "Modified Following", None)
    periods = [(D(2026, 10, 2), D(2026, 11, 2)), (D(2026, 11, 2), D(2026, 12, 2)),
               (D(2026, 12, 2), mat3m)]
    g = 1.0
    for a, b in periods:
        g *= 1.0 + c.get_forward_rate(a, b, "Act/365") * ((b - a).days / 365.0)
    implied = (g - 1.0) * 365.0 / (mat3m - ST).days * 100.0
    if abs(implied - 3.22) > 1e-6:
        raise AssertionError(f"3M CD 3.2200% 여야 하는데 {implied:.6f}% - 커브에 차익거래")


@case("L33-2", "1M·2M·4M·5M 호가가 커브에 실제로 들어간다")
def t_2():
    """
    데스크가 손으로 넣은 값이 아무 데도 쓰이지 않았습니다. 필러가 ON 과 3M
    둘뿐이라, 1M 에 얼마를 넣든 그 사이는 직선이었습니다.
    """
    c = desk_curve()
    short = [p["tenor"] for p in c.pillars if p["months"] <= 5]
    for t in ("1M", "2M", "3M", "4M", "5M"):
        if t not in short:
            raise AssertionError(f"{t} 가 커브 필러에 없음: {short}")

    bumped = [(t, m + 2.0 if t in ("1M", "2M", "4M", "5M") else m) for t, m in QUOTES]
    a = desk_curve().get_forward_rate(D(2026, 11, 2), D(2026, 12, 2), "Act/365")
    b = desk_curve(bumped).get_forward_rate(D(2026, 11, 2), D(2026, 12, 2), "Act/365")
    if abs(b - a) < 1e-4:
        raise AssertionError(
            f"1M·2M·4M·5M 에 200bp 를 더했는데 선도금리가 {(b - a) * 10000:.2f}bp 움직임")


@case("L33-3", "단기 필러를 더해도 호가 재현은 그대로다")
def t_3():
    """
    4M·5M 은 보간 매듭점으로만 들어갑니다. 분기 부트스트랩의 쿠폰 누적에
    끼면 이미 체결된 장기 거래의 평가가 전부 움직입니다.
    """
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


@case("L33-4", "기본값은 일정표의 지급기간이다")
def t_4():
    rows = desk_rows(desk_curve())
    off = [r["start_date"] for r in rows if r["index_end_date"] != r["end_date"]]
    if off:
        raise AssertionError(f"기본값인데 지수 구간이 지급기간과 다름: {off[:3]}")
    if rows[0].get("index_tenor_months") is not None:
        raise AssertionError(f"기본 지수 기간이 비어 있지 않음: {rows[0]['index_tenor_months']}")


@case("L33-5", "지수 기간을 명시하면 창이 길어진다")
def t_5():
    """데스크가 Murex 에 맞추기로 결정하면 쓰는 길입니다. 기본 동작은 아닙니다."""
    c = desk_curve()
    per = [r["fwd_sofr_pct"] for r in desk_rows(c)]
    idx3 = [r["fwd_sofr_pct"] for r in desk_rows(c, 3)]
    if abs(idx3[0] - 3.22) > 1e-6:
        raise AssertionError(f"3M 을 줬는데 첫 기간이 3M CD 호가가 아닌 {idx3[0]}")
    if not all(b > a for a, b in zip(per, idx3)):
        raise AssertionError("우상향 커브인데 3M 투영이 지급기간 투영보다 높지 않음")


@case("L33-6", "지수 창은 지급기간을 줄이지 않는다")
def t_6():
    """
    지급기간이 지수보다 길면 그 안에서 고정이 여러 번 일어나 복리로 쌓이고,
    그 결과는 지급기간 선도금리와 사실상 같습니다. 3개월을 강제하면 반기
    거래가 8.5bp 어긋납니다.
    """
    today = datetime.date.today()
    pr = KRWSwapPricer(bootstrap_krw_curve(today, get_krw_spot_date(today)))

    def par(freq, idx):
        return pr.price_swap(
            notional=1e10, position="Pay Fixed", fixed_coupon_pct=None,
            tenor_str="5Y", frequency_months=freq, leg1_frequency_months=freq,
            leg2_frequency_months=freq, leg2_index_tenor_months=idx,
            calculate_greeks=False)["pricing_results"]["par_swap_rate_pct"]

    for freq, label in ((3, "분기"), (6, "반기")):
        a, b = par(freq, None), par(freq, 3)
        if abs(a - b) > 1e-6:
            raise AssertionError(
                f"{label} 가 3M 지수로 {(b - a) * 100:+.2f}bp 움직임 - 창이 줄어듦")


@case("L33-7", "요청에서 지수 기간을 고를 수 있다")
def t_7():
    from server.app import _resolve_index_months as f

    for given, want in {None: None, "3M": 3, "1M": 1, "6M": 6, "1Y": 12,
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
    if rows[0]["index_end_date"] != rows[0]["end_date"]:
        raise AssertionError("기본인데 지수 구간이 지급기간과 다름")
    rows = c.post("/api/krw/price", json=dict(body, leg2_index_tenor="3M")
                  ).json()["data"]["schedules"]["leg2_floating"]
    if rows[0]["index_end_date"] <= rows[0]["end_date"]:
        raise AssertionError("3M 을 줬는데 창이 길어지지 않음")


if __name__ == "__main__":
    print("\n=== L33 일정표와 마켓 데이터만으로 ===")
    sys.exit(1 if run_all("L33") else 0)
