# -*- coding: utf-8 -*-
"""
L30 가격을 주고 금리를 묻기.

마케터가 태핑할 때 묻는 것은 "이 금리면 얼마냐" 가 아니라 "얼마를 받으려면
금리가 몇이냐" 입니다. 지금까지는 쿠폰을 바꿔가며 여러 번 눌러 맞춰야 했습니다.

반복이 필요 없습니다. NPV 는 쿠폰에 대해 선형입니다 - 실측:

    par 4.7685 · DV01 44,139 · 명목 1억
    쿠폰을 par+50bp 로 주면 NPV -2,206,980
    예측  -0.005 x 4.41396 x 1e8 = -2,206,980

annuity x notional 이 아니라 DV01 을 쓰는 이유는 CRS 입니다. CRS 는 원화 다리
명목이 "USD 명목 x 환율" 이라, 요청에 실린 notional 을 곱하면 자릿수가 어긋나
금리 594%, NPV -3.6조가 나왔습니다. DV01 은 1bp 당 NPV 변화라 명목도 환율도
이미 반영돼 있습니다.
"""
import sys

from harness import case, run_all

from fastapi.testclient import TestClient
from server.app import app

client = TestClient(app)
NOTIONAL = 100_000_000.0


def solve(currency, position="Pay Fixed", target=0.0, **extra):
    body = {"currency": currency, "notional": NOTIONAL, "position": position,
            "tenor": "5Y", "target_mtm": target}
    body.update(extra)
    r = client.post("/api/solve-rate", json=body)
    if r.status_code != 200:
        raise AssertionError(f"{currency} {position} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["data"]


def price(currency, coupon, position="Pay Fixed", **extra):
    path = {"USD": "/api/price", "KRW": "/api/krw/price",
            "KRW_KOFR": "/api/kofr/price", "KRW_CRS": "/api/crs/price"}[currency]
    body = {"currency": currency, "notional": NOTIONAL, "position": position,
            "tenor": "5Y", "fixed_coupon_pct": coupon}
    body.update(extra)
    pr = client.post(path, json=body).json()["data"]["pricing_results"]
    v = pr.get("deal_npv")
    return pr.get("deal_npv_krw") if v is None else v


# CRS 는 요청 모양이 조금 다릅니다.
# CRS 는 spot_fx 가 호출 사이에 움직입니다. 환율을 고정하지 않으면 두 번째
# 프라이싱이 다른 시장을 보게 되어, 수식이 맞아도 값이 어긋납니다.
CASES = [("USD", {}), ("KRW", {}), ("KRW_KOFR", {}),
         ("KRW_CRS", {"crs_swap_type": "Vanilla", "spot_fx": 1360.0})]


@case("L30-1", "MtM 0 을 요구하면 par 가 나온다")
def t_1():
    for ccy, extra in CASES:
        d = solve(ccy, target=0.0, **extra)
        if abs(d["coupon_pct"] - d["par_swap_rate_pct"]) > 1e-4:
            raise AssertionError(
                f"{ccy}: MtM 0 인데 par 가 아님 — {d['coupon_pct']} vs par {d['par_swap_rate_pct']}")


@case("L30-2", "돌려준 금리로 실제 그 MtM 이 나온다")
def t_2():
    # 화면이 스스로 옳다고 말하게 두지 않습니다. 받은 금리를 프라이서에 다시
    # 넣어 확인합니다.
    for ccy, extra in CASES:
        for target in (2_000_000.0, -1_500_000.0):
            d = solve(ccy, target=target, **extra)
            got = price(ccy, d["coupon_pct"], **extra)
            # 허용오차는 임의로 정하지 않고 호가 자리수에서 나옵니다. 쿠폰을
            # 소수 6자리로 돌려주므로 마지막 자리 하나가 DV01 x 1e-4 만큼
            # 움직입니다 - CRS 는 DV01 이 1bp 당 6,190만원이라 그 한 자리가
            # 6,192원입니다. 그보다 정확히 맞히는 것은 불가능하고, 더 많은
            # 자리수를 돌려주는 것은 없는 정밀도를 주장하는 일입니다.
            step = abs(d["dv01"]) * 1e-4
            tol = max(10.0, step)
            if abs(got - target) > tol:
                raise AssertionError(
                    f"{ccy} 목표 {target:,.0f} → 금리 {d['coupon_pct']} → "
                    f"실제 {got:,.2f} (허용 {tol:,.0f})")


@case("L30-3", "포지션에 따라 금리가 반대편으로 간다")
def t_3():
    # 고정을 지급하면 쿠폰이 낮아야 이익이고, 수취하면 높아야 이익입니다.
    # 부호를 뒤집으면 값은 나오는데 방향이 반대인, 눈에 안 띄는 종류의 오류입니다.
    for ccy, extra in CASES:
        if ccy == "KRW_CRS":
            continue          # 원금교환이 있어 부호 관계가 단순하지 않습니다
        pay = solve(ccy, "Pay Fixed", 2_000_000.0, **extra)
        rec = solve(ccy, "Rec Fixed", 2_000_000.0, **extra)
        par = pay["par_swap_rate_pct"]
        if not (pay["coupon_pct"] < par < rec["coupon_pct"]):
            raise AssertionError(
                f"{ccy}: 이익을 내려면 Pay 는 par 아래, Rec 는 par 위여야 함 — "
                f"pay {pay['coupon_pct']} / par {par} / rec {rec['coupon_pct']}")


@case("L30-4", "잔차를 숨기지 않는다")
def t_4():
    # 닫힌 식이지만 완전히 선형이 아닌 통화가 있습니다(KOFR 는 복리). 검산 결과를
    # 함께 돌려줘야, 맞지 않을 때 화면이 그 사실을 말할 수 있습니다.
    d = solve("USD", target=2_000_000.0)
    for field in ("target_mtm", "achieved_mtm", "residual", "dv01",
                  "par_swap_rate_pct", "spread_vs_par_bp"):
        if field not in d:
            raise AssertionError(f"{field} 가 응답에 없음")
    if d["residual"] is None:
        raise AssertionError("검산을 하지 않음")
    if abs(d["residual"]) > 10.0:
        raise AssertionError(f"잔차가 큼: {d['residual']}")


@case("L30-5", "par 대비 스프레드를 bp 로 알려준다")
def t_5():
    d = solve("USD", target=-2_000_000.0)
    want = (d["coupon_pct"] - d["par_swap_rate_pct"]) * 100.0
    if abs(d["spread_vs_par_bp"] - want) > 1e-6:
        raise AssertionError(f"스프레드가 맞지 않음: {d['spread_vs_par_bp']} vs {want}")
    # Pay Fixed 에서 손실을 내려면 par 보다 높게 내야 합니다.
    if d["spread_vs_par_bp"] <= 0:
        raise AssertionError("방향이 반대")


@case("L30-6", "상각 스케줄이 걸려 있어도 맞는다")
def t_6():
    # DV01 이 이미 스케줄을 반영하므로 식은 그대로지만, 실제로 그런지 봅니다.
    sched = "\n".join(
        f"{a}\t{b}\t{n}" for a, b, n in [
            ("2026-09-15", "2027-09-15", 100000000),
            ("2027-09-15", "2028-09-15", 80000000),
            ("2028-09-15", "2029-09-15", 60000000),
            ("2029-09-15", "2030-09-15", 40000000),
            ("2030-09-15", "2031-09-15", 20000000)])
    extra = {"leg1_raw_paste_text": sched, "raw_paste_text": sched,
             "effective_date": "2026-09-15", "maturity_date": "2031-09-15"}
    flat = solve("USD", target=1_000_000.0)
    amort = solve("USD", target=1_000_000.0, **extra)
    if abs(amort["dv01"] - flat["dv01"]) < 1.0:
        raise AssertionError("상각인데 DV01 이 그대로 — 스케줄이 반영되지 않음")
    got = price("USD", amort["coupon_pct"], **extra)
    if abs(got - 1_000_000.0) > 10.0:
        raise AssertionError(f"상각 거래에서 목표를 못 맞춤: {got:,.2f}")


@case("L30-7", "명목이 없으면 계산하지 않는다")
def t_7():
    r = client.post("/api/solve-rate", json={
        "currency": "USD", "notional": 0, "position": "Pay Fixed",
        "tenor": "5Y", "target_mtm": 1_000_000.0})
    if r.status_code == 200:
        raise AssertionError("명목 0 인데 금리를 돌려줌")


if __name__ == "__main__":
    print("\n=== L30 MtM → 금리 역산 ===")
    sys.exit(1 if run_all("L30") else 0)
