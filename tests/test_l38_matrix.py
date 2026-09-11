"""L3 - date / schedule parameter matrix.  L8 - API contract and error handling."""
from harness import case, approx, run_all
from test_l2_pricing import client, price, pr, freeze_market, PRODUCTS

freeze_market()

USD = "/api/price"


# ---------------------------------------------------------------- L3 schedules
@case("L3-1", "all 4 stub rules price on both legs")
def t_l3_1():
    for stub in ("Short upfront", "Long upfront", "Short in arrears", "Long in arrears"):
        res = price(USD, tenor="15M", fixed_coupon_pct=4.0,
                    leg1_stub_rule=stub, leg2_stub_rule=stub)
        rows = res["schedules"]["leg1_fixed"]
        if not rows:
            raise AssertionError(f"stub {stub}: empty schedule")
        for r in rows:
            if r["end_date"] <= r["start_date"]:
                raise AssertionError(f"stub {stub}: bad period {r['start_date']}..{r['end_date']}")


@case("L3-2", "payment frequency drives the period count")
def t_l3_2():
    expected = {"12M": 5, "6M": 10, "3M": 20}
    for freq, n in expected.items():
        res = price(USD, tenor="5Y", fixed_coupon_pct=4.0, leg1_payment_freq=freq)
        got = len(res["schedules"]["leg1_fixed"])
        if got != n:
            raise AssertionError(f"freq {freq}: expected {n} periods, got {got}")


@case("L3-3", "day count conventions produce distinct accrual fractions")
def t_l3_3():
    seen = {}
    for dc in ("Act/360", "Act/365", "30/360"):
        res = price(USD, tenor="5Y", fixed_coupon_pct=4.0, leg1_day_count=dc)
        seen[dc] = round(res["schedules"]["leg1_fixed"][0]["day_count_fraction"], 8)
    if seen["Act/360"] == seen["Act/365"]:
        raise AssertionError(f"Act/360 and Act/365 identical: {seen}")
    if not (0.9 < seen["Act/360"] / seen["30/360"] < 1.1):
        raise AssertionError(f"30/360 fraction implausible: {seen}")


@case("L3-4", "business day conventions shift dates differently")
def t_l3_4():
    dates = {}
    for conv in ("Modified Following", "Following", "Preceding"):
        res = price(USD, tenor="5Y", fixed_coupon_pct=4.0, leg1_business_day_conv=conv)
        dates[conv] = [r["pay_date"] for r in res["schedules"]["leg1_fixed"]]
    if dates["Following"] == dates["Preceding"]:
        raise AssertionError("Following and Preceding produced identical schedules")


@case("L3-6", "maturity landing on a Seoul holiday rolls to a business day")
def t_l3_6():
    # 2027-10-12 is a Korean substitute holiday carried in the calendar data.
    res = price("/api/krw/price", notional=10_000_000_000.0,
                effective_date="2026-10-12", maturity_date="2027-10-12",
                fixed_coupon_pct=2.6)
    last = res["schedules"]["leg1_fixed"][-1]
    if last["pay_date"] == "2027-10-12":
        raise AssertionError("pay date stayed on a Seoul holiday")


@case("L3-7", "leap-year effective date prices cleanly")
def t_l3_7():
    res = price(USD, effective_date="2028-02-29", tenor="1Y", fixed_coupon_pct=4.0)
    rows = res["schedules"]["leg1_fixed"]
    if not rows or rows[0]["start_date"] != "2028-02-29":
        raise AssertionError(f"leap-year start not honoured: {rows[:1]}")


@case("L3-8", "month-end roll clamps to the shorter month")
def t_l3_8():
    res = price(USD, effective_date="2027-01-31", tenor="1Y",
                fixed_coupon_pct=4.0, leg1_payment_freq="3M")
    ends = [r["end_date"] for r in res["schedules"]["leg1_fixed"]]
    if not any(e.startswith("2027-04-") for e in ends):
        raise AssertionError(f"no April period after a Jan-31 start: {ends}")


@case("L3-9", "KOFR applies a +2 business day payment lag")
def t_l3_9():
    res = price("/api/kofr/price", notional=10_000_000_000.0, tenor="2Y",
                fixed_coupon_pct=2.4)
    rows = res["schedules"]["leg1_fixed"]
    lagged = sum(1 for r in rows if r["pay_date"] > r["end_date"])
    if lagged < len(rows) - 1:
        raise AssertionError(
            f"payment lag missing: only {lagged}/{len(rows)} rows pay after accrual end")


# ---------------------------------------------------------------- L8 contract
@case("L8-1", "invalid tenor is rejected as a client error, not a 500")
def t_l8_1():
    for name, ep, notional in PRODUCTS + [("KRW_CRS", "/api/crs/price", 1e7)]:
        r = client.post(ep, json={"tenor": "XYZ", "notional": notional})
        if r.status_code >= 500:
            raise AssertionError(f"{name}: invalid tenor -> HTTP {r.status_code}")
        if r.status_code == 200:
            raise AssertionError(f"{name}: invalid tenor silently accepted")


@case("L8-2", "maturity before effective date is rejected")
def t_l8_2():
    r = client.post(USD, json={"effective_date": "2030-01-15",
                               "maturity_date": "2027-01-15", "tenor": "5Y"})
    if r.status_code == 200:
        raise AssertionError("inverted date range was accepted")
    if r.status_code >= 500:
        raise AssertionError(f"inverted date range -> HTTP {r.status_code} (want 4xx)")


@case("L8-3", "non-positive notional is rejected consistently across products")
def t_l8_3():
    for name, ep, _ in PRODUCTS:
        for bad in (0.0, -1_000_000.0):
            r = client.post(ep, json={"tenor": "5Y", "notional": bad})
            if r.status_code == 200:
                raise AssertionError(f"{name}: notional {bad} was accepted")
            if r.status_code >= 500:
                raise AssertionError(f"{name}: notional {bad} -> HTTP {r.status_code}")


@case("L8-6", "reload-and-price payload shape is stable across products")
def t_l8_6():
    eps = ["/api/reload-and-price", "/api/krw/reload-and-price",
           "/api/kofr/reload-and-price", "/api/crs/reload-and-price"]
    for ep in eps:
        r = client.post(ep, json={"tenor": "5Y"})
        if r.status_code != 200:
            raise AssertionError(f"{ep} -> HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        for key in ("status", "data", "pricing", "market_snapshot"):
            if key not in body:
                raise AssertionError(f"{ep} missing '{key}'")


if __name__ == "__main__":
    import sys
    print("\n=== L3 schedules / L8 contract ===")
    failed = run_all("L3") + run_all("L8")
    sys.exit(1 if failed else 0)
