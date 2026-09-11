r"""
Parity verification test for KRW KOFR IRS vs Murex '\KRW KOFR Q 3M' Deal Capture
"""

import sys
import os
import datetime

sys.path.insert(0, r"c:\test1")

from kofr_pricer.kofr_date_engine import generate_kofr_schedule, get_seoul_holidays, add_business_days
from kofr_pricer.kofr_curve_engine import bootstrap_kofr_curve
from kofr_pricer.kofr_swap_engine import KOFRSwapPricer

def test_murex_kofr_parity():
    pricing_date = datetime.date(2026, 8, 27)
    settle_date = datetime.date(2026, 8, 28)
    
    # Live KOFR Market quotes matching Murex 1Y Par Rate 3.3775%
    quotes = [
        ("ON", 2.8042),
        ("3M", 3.0000),
        ("6M", 3.1650),
        ("9M", 3.3025),
        ("1Y", 3.3775),
        ("18M", 3.5500),
        ("2Y", 3.5275),
        ("3Y", 3.6225),
        ("4Y", 3.6875),
        ("5Y", 3.7350),
        ("7Y", 3.7925),
        ("10Y", 3.8050),
        ("12Y", 3.8050),
        ("15Y", 3.8000),
        ("20Y", 3.6875)
    ]
    
    curve = bootstrap_kofr_curve(pricing_date, settle_date, quotes)
    pricer = KOFRSwapPricer(curve)
    
    # 1. Test with Murex 1,000,000 KRW Deal
    res_murex_deal = pricer.price_swap(
        notional=1_000_000.0,
        position="Pay Fixed",
        fixed_coupon_pct=3.377500,
        effective_date=settle_date,
        maturity_date=datetime.date(2027, 8, 30),
        tenor_str="1Y",
        frequency_months=3,
        payment_lag_bd=2
    )
    
    p = res_murex_deal["pricing_results"]
    
    print("====================================================================")
    print("MUREX '\\KRW KOFR Q 3M' PARITY TEST (Notional = 1,000,000 KRW)")
    print("====================================================================")
    print(f"Par Swap Rate : {p['par_swap_rate_pct']:.4f}%    (Murex: 3.377500%)")
    print(f"Fixed Leg PV  : {p['fixed_leg_pv']:,.0f} KRW       (Murex: 33,263 KRW)")
    print(f"Float Leg PV  : {p['float_leg_pv']:,.0f} KRW       (Murex: 33,263 KRW)")
    print(f"Deal NPV      : {p['deal_npv']:,.0f} KRW          (Murex: 0 KRW)")
    print(f"BPV / DV01    : {p['dv01']:,.0f} KRW          (Murex: 98 KRW)")
    
    print("\nQuarterly Cash Flow Schedule (+2BD Payment Lag):")
    for s in res_murex_deal["schedules"]["dual_comparison"]:
        print(f"P{s['period_no']}: Accrual={s['start_date']} ~ {s['end_date']} | PayDate={s['pay_date']} | Frac={s['day_count_fraction']} | FixedCF={s['fixed_cf']:,.2f} | FloatCF={s['float_cf']:,.2f} | DF={s['discount_factor']}")
        
    assert abs(p["par_swap_rate_pct"] - 3.3775) < 0.005, "Par Swap Rate error"
    assert abs(p["fixed_leg_pv"] - 33263) < 50, "Fixed Leg PV error"
    assert abs(p["float_leg_pv"] - 33263) < 50, "Float Leg PV error"
    assert abs(p["dv01"] - 98) < 2, "BPV error"
    print("\n>>> ALL MUREX PARITY CHECKS PASSED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    test_murex_kofr_parity()
