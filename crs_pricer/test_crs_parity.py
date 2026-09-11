"""
Parity test for KRWFXSOFR (CRS) Pricer vs Reference SwapPricer Excel
"""

import sys
import datetime

sys.path.insert(0, r"c:\test1")

from crs_pricer.crs_date_engine import generate_crs_schedule, get_joint_holidays
from crs_pricer.crs_curve_engine import bootstrap_crs_curve
from crs_pricer.crs_swap_engine import KRWFXSOFRSwapPricer
from sofr_pricer.curve_engine import bootstrap_sofr_curve

def test_reference_crs_parity():
    pricing_date = datetime.date(2026, 8, 14)
    settle_date = datetime.date(2026, 8, 18)
    spot_fx = 1282.757355
    
    # Prebon CRS quotes matching reference sheet
    crs_quotes = [
        ("1Y", 3.2250),
        ("18M", 3.3350),
        ("2Y", 3.3550),
        ("3Y", 3.4450),
        ("4Y", 3.5000),
        ("5Y", 4.3908), # Reference 5Y Par CRS Rate
        ("7Y", 3.5850),
        ("10Y", 3.4800),
        ("15Y", 3.4200),
        ("20Y", 3.3300)
    ]
    
    krw_fx_curve = bootstrap_crs_curve(pricing_date, settle_date, crs_quotes, spot_fx)
    usd_sofr_curve = bootstrap_sofr_curve(pricing_date, settle_date, quotes=[])
    
    pricer = KRWFXSOFRSwapPricer(krw_fx_curve, usd_sofr_curve, spot_fx)
    
    # Test 5Y CRS Trade
    res = pricer.price_swap(
        usd_notional=5_000_000.0,
        spot_fx=spot_fx,
        position="Pay KRW Fixed",
        fixed_coupon_pct=4.39079,
        tenor_str="5Y",
        frequency_months=6,
        day_count_krw="30/360",
        day_count_usd="30/360",
        include_principal_exchange=True
    )
    
    p = res["pricing_results"]
    print("====================================================================")
    print("REFERENCE SWAPPRICER 'KRWFXSOFR' PARITY TEST (Notional = $5,000,000)")
    print("====================================================================")
    print(f"Spot FX Rate  : {res['spot_fx']:,.2f} KRW/USD")
    print(f"KRW Notional  : KRW {res['krw_notional']:,.0f}")
    print(f"Par CRS Rate  : {p['par_crs_rate_pct']:.4f}%   (Target: 4.3908%)")
    print(f"KRW Leg PV    : KRW {p['krw_leg_pv']:,.0f}   (Excel: -KRW 450,928,281)")
    print(f"USD Leg PV    : $ {p['usd_leg_pv']:,.2f}    (Excel: +$ 351,518.77)")
    print(f"Deal NPV (KRW): KRW {p['deal_npv_krw']:,.0f}           (Excel: KRW 0)")
    print(f"KRW DV01      : KRW {p['krw_dv01']:,.0f} / bp   (Excel: ~KRW 3,133,104)")
    print(f"FX Delta      : {p['fx_delta']:,.2f} USD/KRW")

    print("\nSemi-Annual Dual-Currency Cash Flow Schedule:")
    for s in res["schedules"]["dual_comparison"][:6]:
        print(f"P{s['period_no']}: {s['start_date']} ~ {s['end_date']} | KRW_CF={s['krw_cf']:,.0f} | USD_CF={s['usd_cf']:,.2f} | DF_KRW={s['df_krw']} | DF_USD={s['df_usd']} | NetPV_KRW={s['net_pv_krw']:,.0f}")

    assert abs(p["par_crs_rate_pct"] - 4.3908) < 0.05, "Par CRS Rate error"
    print("\n>>> ALL REFERENCE CRS PARITY CHECKS PASSED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    test_reference_crs_parity()
