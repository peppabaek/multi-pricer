"""
Unit & Parity Verification Tests
Compare Python SOFR Pricer against Reference Excel ('USDSOFR' sheet benchmark)
"""

import os
import json
import datetime
from sofr_pricer import (
    parse_date, apply_convention, day_count_fraction, generate_schedule,
    bootstrap_sofr_curve, USDSOFRSwapPricer
)

def run_parity_test():
    print("=" * 60)
    print("RUNNING SOFR PRICER PARITY & ACCURACY TESTS")
    print("=" * 60)
    
    # 1. Load Golden Benchmark from JSON
    benchmark_path = r"c:\test1\sofr_benchmark.json"
    with open(benchmark_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    p_date = parse_date(data["pricing_date"])
    s_date = parse_date(data["settle_date"])
    
    print(f"Pricing Date: {p_date}, Settle Date: {s_date}")
    
    # Exact Tenor Labels matching Excel Rows 5 to 42
    excel_tenor_labels = [
        "SW", "2W", "1M", "2M", "3M", "4M", "5M", "6M", "7M", "8M", "9M", "10M", "11M", "12M",
        "18M", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "11Y", "12Y",
        "13Y", "14Y", "15Y", "16Y", "17Y", "18Y", "19Y", "20Y", "21Y", "22Y", "23Y", "24Y"
    ]
    
    quotes = []
    for i, item in enumerate(data["tenors"]):
        t_label = excel_tenor_labels[i] if i < len(excel_tenor_labels) else f"{i}Y"
        quotes.append((t_label, item["rate"]))
        
    # 2. Bootstrap Curve in Python
    curve = bootstrap_sofr_curve(p_date, s_date, quotes)
    
    # 3. Compare Discount Factors and Zero Rates
    max_df_diff = 0.0
    max_zero_diff_bp = 0.0
    
    print("\n--- Pillar Comparison (Python vs Excel Benchmark) ---")
    print(f"{'Tenor':<8} {'Mat Date':<12} {'Rate(%)':<10} {'Py DF':<12} {'Excel DF':<12} {'Diff DF':<12} {'Zero Diff(bp)':<12}")
    print("-" * 80)
    
    for i, item in enumerate(data["tenors"]):
        if i >= len(curve.pillars):
            break
        pillar = curve.pillars[i]
        py_df = pillar["df"]
        ex_df = item["df"]
        py_zero = pillar["zero_rate"]
        ex_zero = item["zero_rate"]
        
        df_diff = abs(py_df - ex_df)
        zero_diff_bp = abs(py_zero - ex_zero) * 100.0 # in bp
        
        max_df_diff = max(max_df_diff, df_diff)
        max_zero_diff_bp = max(max_zero_diff_bp, zero_diff_bp)
        
        t_name = pillar["tenor"]
        mat_str = pillar["mat_date"].strftime("%Y-%m-%d")
        rate_str = f"{pillar['rate']:.4f}"
        
        if i < 15 or i % 3 == 0:
            print(f"{t_name:<8} {mat_str:<12} {rate_str:<10} {py_df:.7f}  {ex_df:.7f}  {df_diff:.2e}     {zero_diff_bp:.4f} bp")
            
    print("-" * 80)
    print(f"Max DF Absolute Difference:   {max_df_diff:.2e}")
    print(f"Max Zero Rate Difference:     {max_zero_diff_bp:.4f} bp")
    
    # 4. Test Swap Pricing Engine
    pricer = USDSOFRSwapPricer(curve)
    print("\n--- Test Swap Pricing: 5Y USD SOFR IRS ---")
    res_5y = pricer.price_swap(
        notional=100_000_000.0,
        position="Pay Fixed",
        fixed_coupon_pct=3.725,
        tenor_str="5Y"
    )
    
    p_res = res_5y["pricing_results"]
    print(f"Notional:            $ {res_5y['trade_info']['notional']:,.2f}")
    print(f"Position:            {res_5y['trade_info']['position']}")
    print(f"Fixed Coupon:        {res_5y['trade_info']['fixed_coupon_pct']:.4f} %")
    print(f"Par Swap Rate:       {p_res['par_swap_rate_pct']:.4f} %")
    print(f"Spread vs Cpn:       {p_res['spread_vs_coupon_bp']:+.2f} bp")
    print(f"Deal NPV:            $ {p_res['deal_npv']:,.2f}")
    print(f"DV01 (PV01):         $ {p_res['dv01']:,.2f}")
    print(f"Annuity:             {p_res['annuity']:.6f}")
    
    print("\n--- Key Rate Delta Bucketing ---")
    for b in res_5y["delta_bucketing"]:
        print(f"  {b['tenor']:<5}: $ {b['delta_dv01']:>10,.2f}")
        
    print("\n--- Cash Flow Waterfall (All 5 Periods) ---")
    for row in res_5y["schedules"]["dual_comparison"]:
        print(f"  P{row['period_no']}: {row['start_date']} ~ {row['end_date']} | Fwd: {row['fwd_sofr_pct']:.4f}% | DF: {row['discount_factor']:.6f} | Net PV: $ {row['net_pv']:>10,.2f}")
        
    # Strict validation: DF within 5e-4 and Zero Rate within 0.5 bp
    assert max_df_diff < 5e-4, f"DF difference too large: {max_df_diff}"
    assert max_zero_diff_bp < 0.5, f"Zero rate difference too large: {max_zero_diff_bp} bp"
    print("\n>>> ALL TESTS PASSED! ACCURACY VERIFIED WITH EXCEL BENCHMARK <<<")
    return True

if __name__ == "__main__":
    run_parity_test()
