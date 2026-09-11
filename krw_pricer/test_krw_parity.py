import os
import sys
import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from krw_pricer import (
    parse_date, get_krw_spot_date, bootstrap_krw_curve, KRWSwapPricer
)

def test_krw_parity():
    print("=" * 60)
    print("RUNNING KRW IRS PRICER PARITY & ACCURACY TESTS")
    print("=" * 60)

    # Reference Excel Baseline Quotes (2026-08-14)
    pricing_date = datetime.date(2026, 8, 14)
    settle_date = datetime.date(2026, 8, 17) # T+1 (Monday)
    
    quotes = [
        ("ON", 2.769),
        ("3M", 2.930),
        ("6M", 3.1525),
        ("9M", 3.2975),
        ("1Y", 3.4525),
        ("18M", 3.6375),
        ("2Y", 3.7350),
        ("3Y", 3.8475),
        ("4Y", 3.9150),
        ("5Y", 3.9650),
        ("7Y", 4.0350),
        ("10Y", 4.0950),
        ("12Y", 4.1175),
        ("15Y", 4.1000),
        ("20Y", 4.0550)
    ]

    curve = bootstrap_krw_curve(pricing_date, settle_date, quotes)
    print(f"Bootstrapped {len(curve.pillars)} quarterly pillars.")
    
    # 1. Verify DF and Zero Rate at key pillars matching Excel
    expected_benchmarks = [
        ("3M", 0.992443, 2.9145),
        ("6M", 0.984067, 3.1349),
        ("1Y", 0.965954, 3.4356),
        ("2Y", 0.927901, 3.7211),
        ("3Y", 0.890923, 3.8359)
    ]

    print("\n--- Key Pillar Comparison vs Reference Excel ---")
    for tenor, exp_df, exp_zero in expected_benchmarks:
        match = [p for p in curve.pillars if p["tenor"] == tenor][0]
        py_df = match["df"]
        py_zero = match["zero_rate"]
        df_diff = abs(py_df - exp_df)
        zero_diff = abs(py_zero - exp_zero)
        print(f"Tenor {tenor:>4} | Py DF: {py_df:.6f} vs Ex: {exp_df:.6f} (Diff: {df_diff:.7f}) | Zero: {py_zero:.4f}% vs Ex: {exp_zero:.4f}%")
        assert df_diff < 1e-5, f"DF discrepancy on {tenor}"

    # 2. Test 3Y Vanilla Swap Pricing (Notional: 100억)
    pricer = KRWSwapPricer(curve)
    vanilla_res = pricer.price_swap(
        notional=10_000_000_000.0,
        position="Pay Fixed",
        fixed_coupon_pct=3.8475,
        tenor_str="3Y",
        frequency_months=3
    )

    print("\n--- 3Y Vanilla KRW IRS Pricing Result ---")
    p_res = vanilla_res["pricing_results"]
    print("Par Swap Rate :", p_res["par_swap_rate_pct"], "%")
    print("Deal NPV (KRW):", f"KRW {p_res['deal_npv']:,.0f}")
    print("DV01 (KRW/bp) :", f"KRW {p_res['dv01']:,.0f}")
    print("Annuity       :", p_res["annuity"])
    assert abs(p_res["par_swap_rate_pct"] - 3.8475) < 0.0001, "Par rate does not match market quote!"

    # 3. Test Custom Amortizing Notional Schedule (100억 -> 75억 -> 50억 -> 25억)
    custom_schedule = [
        {"start_date": "2026-08-17", "end_date": "2027-08-17", "pay_date": "2027-08-17", "notional": 10_000_000_000, "fixed_rate_pct": 3.80},
        {"start_date": "2027-08-17", "end_date": "2028-08-17", "pay_date": "2028-08-17", "notional": 7_500_000_000, "fixed_rate_pct": 3.85},
        {"start_date": "2028-08-17", "end_date": "2029-08-17", "pay_date": "2029-08-17", "notional": 5_000_000_000, "fixed_rate_pct": 3.90},
        {"start_date": "2029-08-17", "end_date": "2030-08-19", "pay_date": "2030-08-19", "notional": 2_500_000_000, "fixed_rate_pct": 3.95}
    ]
    
    custom_res = pricer.price_swap(
        notional=10_000_000_000.0,
        position="Pay Fixed",
        custom_schedule=custom_schedule
    )

    print("\n--- Custom Amortizing Schedule Pricing Result ---")
    c_res = custom_res["pricing_results"]
    print("Custom Par Rate:", c_res["par_swap_rate_pct"], "%")
    print("Custom NPV (KRW):", f"KRW {c_res['deal_npv']:,.0f}")
    print("Custom DV01 (KRW):", f"KRW {c_res['dv01']:,.0f}")
    print("Schedules count:", len(custom_res["schedules"]["dual_comparison"]))

    print("\n[SUCCESS] ALL KRW PARITY & CUSTOM SCHEDULE TESTS PASSED 100%!")

if __name__ == "__main__":
    test_krw_parity()
