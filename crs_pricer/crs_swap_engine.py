"""
KRWFXSOFR (CRS) Swap Pricing Engine - Murex & Reference Excel Parity
- Implements Dual-Currency Dual-Leg Cross Currency Swap (CRS) Pricer
- Supports:
  - Initial & Final Principal Exchange (Start/End Principal Flow at Spot FX)
  - Leg 1 (KRW Leg): Fixed Rate (30/360 or Act/365) discounted by KRWFXSOFR curve
  - Leg 2 (USD Leg): Floating SOFR Compounded (Act/360 or 30/360) discounted by USDSOFR curve
  - +2 Business Day Payment Lag on Coupon Interest (ISDA / Murex Standard)
  - Par CRS Rate (%), Par CRS Spread (bp)
  - Leg 1 NPV (KRW) & Leg 1 BPV (KRW/bp)
  - Leg 2 NPV (USD & KRW converted) & Leg 2 BPV (USD/bp)
  - Deal Net Present Value (NPV) in KRW (₩) and USD ($)
  - FX Delta (Sensitivity to 1 KRW change in USD/KRW Spot)
  - Full Side-by-Side Dual-Leg Cash Flow Schedule & Custom Schedule Paste Support
"""

import datetime
from typing import List, Dict, Any, Optional
from .crs_date_engine import (
    generate_crs_schedule,
    get_joint_holidays,
    apply_crs_convention,
    add_months,
    add_joint_business_days,
    day_count_fraction
)
from .crs_curve_engine import KRWFXSOFRCurve
from sofr_pricer.curve_engine import SOFRCurve

class KRWFXSOFRSwapPricer:
    def __init__(self, krw_fx_curve: KRWFXSOFRCurve, usd_sofr_curve: Optional[SOFRCurve] = None, spot_fx: float = 1335.50):
        self.krw_fx_curve = krw_fx_curve
        self.spot_fx = spot_fx if spot_fx > 0 else krw_fx_curve.spot_fx
        self.holidays = get_joint_holidays()
        
        # If USD SOFR curve is not passed, create a default baseline curve
        if usd_sofr_curve:
            self.usd_sofr_curve = usd_sofr_curve
        else:
            from sofr_pricer.curve_engine import bootstrap_sofr_curve
            self.usd_sofr_curve = bootstrap_sofr_curve(krw_fx_curve.pricing_date, krw_fx_curve.settle_date, quotes=[])

    def price_swap(
        self,
        usd_notional: float = 10_000_000.0,       # e.g. $ 10M
        krw_notional: Optional[float] = None,     # If None, usd_notional * spot_fx
        spot_fx: Optional[float] = None,          # e.g. 1,375.75 KRW/USD
        position: str = "Pay KRW Fixed",          # "Pay KRW Fixed" or "Rec KRW Fixed"
        fixed_coupon_pct: Optional[float] = None, # KRW Fixed Coupon in % p.a.
        spread_bp: float = 0.0,                   # USD Float SOFR spread in bp
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        tenor_str: str = "5Y",
        frequency_months: int = 6,                # 6M Semi-Annual (Standard CRS)
        payment_lag_bd: int = 2,                  # +2 BD Payment Lag (Murex Standard)
        day_count_krw: str = "30/360",            # Standard KRW CRS Fixed
        day_count_usd: str = "Act/360",           # USD SOFR Leg Day Count
        business_day_conv: str = "Modified Following",
        stub_rule: str = "Short in arrears",
        adjust_rule: str = "Adjust",
        fix_cal: str = "SEB_NYB",
        pay_cal: str = "SEB_NYB",
        fix_day: int = -1,
        include_principal_exchange: bool = True,  # Start & End Principal Exchange
        custom_schedule: Optional[List[Dict[str, Any]]] = None,
        leg1_custom_schedule: Optional[List[Dict[str, Any]]] = None,
        leg2_custom_schedule: Optional[List[Dict[str, Any]]] = None,
        swap_type: str = "Vanilla",               # "Vanilla" or "Fixed-Fixed"
        usd_fixed_coupon_pct: Optional[float] = None,
        # Independent Leg 1 (KRW) Parameters
        leg1_frequency_months: Optional[int] = None,
        leg1_day_count: Optional[str] = None,
        leg1_stub_rule: Optional[str] = None,
        leg1_business_day_conv: Optional[str] = None,
        leg1_adjust_rule: Optional[str] = None,
        leg1_pay_cal: Optional[str] = None,
        # Independent Leg 2 (USD) Parameters
        leg2_frequency_months: Optional[int] = None,
        leg2_day_count: Optional[str] = None,
        leg2_stub_rule: Optional[str] = None,
        leg2_business_day_conv: Optional[str] = None,
        leg2_adjust_rule: Optional[str] = None,
        leg2_pay_cal: Optional[str] = None,
        leg2_fix_cal: Optional[str] = None,
        leg2_fix_day: Optional[int] = None,
        calculate_greeks: bool = True
    ) -> Dict[str, Any]:
        """Price Cross Currency Swap (KRWFXSOFR) matching Reference SwapPricer & Murex, supporting Vanilla & Fixed-Fixed"""
        from server.calendar_manager import (
            generate_schedule as gen_sched,
            compute_fixing_date,
            day_count_fraction as calc_dc_fraction,
            apply_convention as apply_conv,
            add_months as add_m
        )
        
        fx_rate = spot_fx if (spot_fx and spot_fx > 0) else self.spot_fx
        notional_usd = usd_notional if usd_notional > 0 else 10_000_000.0
        notional_krw = krw_notional if (krw_notional and krw_notional > 0) else notional_usd * fx_rate
        
        eff_d = effective_date if effective_date else self.krw_fx_curve.settle_date

        is_fixed_fixed = "fixed-fixed" in swap_type.lower() or "fixed_fixed" in swap_type.lower() or "fixed to fixed" in swap_type.lower()
        
        # Resolve Leg 1 and Leg 2 independent parameters
        l1_freq = leg1_frequency_months or frequency_months or 6
        l1_dc = leg1_day_count or day_count_krw or "30/360"
        l1_stub = leg1_stub_rule or stub_rule or "Short in arrears"
        l1_conv = leg1_business_day_conv or business_day_conv or "Modified Following"
        l1_adj = leg1_adjust_rule or adjust_rule or "Adjust"
        l1_cal = leg1_pay_cal or pay_cal or "SEB_NYB"

        default_l2_dc = "30/360" if is_fixed_fixed else "Act/360"
        l2_freq = leg2_frequency_months or frequency_months or 6
        l2_dc = leg2_day_count or day_count_usd or default_l2_dc
        l2_stub = leg2_stub_rule or stub_rule or "Short in arrears"
        l2_conv = leg2_business_day_conv or business_day_conv or "Modified Following"
        l2_adj = leg2_adjust_rule or adjust_rule or "Adjust"
        l2_cal = leg2_pay_cal or pay_cal or "SEB_NYB"
        l2_fcal = leg2_fix_cal or fix_cal or "SEB_NYB"
        l2_fday = leg2_fix_day if leg2_fix_day is not None else fix_day

        if maturity_date:
            mat_d = maturity_date
        else:
            t_str = tenor_str.strip().upper()
            if "M" in t_str:
                m_val = int(t_str.replace("M", ""))
                mat_d = apply_conv(add_m(eff_d, m_val), l1_conv, l1_cal)
            elif "Y" in t_str:
                y_val = int(t_str.replace("Y", ""))
                mat_d = apply_conv(add_m(eff_d, y_val * 12), l1_conv, l1_cal)
            else:
                mat_d = apply_conv(add_m(eff_d, 60), l1_conv, l1_cal)

        is_pay_krw_fixed = ("pay" in position.lower() and "krw" in position.lower()) or ("pay fixed" in position.lower())
        sign_krw = -1.0 if is_pay_krw_fixed else 1.0
        sign_usd = 1.0 if is_pay_krw_fixed else -1.0

        # 1. Discount Factors for Principal Exchanges (relative to effective date)
        df_krw_start_raw = self.krw_fx_curve.get_df(eff_d)
        df_krw_mat_raw = self.krw_fx_curve.get_df(mat_d)
        df_usd_start_raw = self.usd_sofr_curve.get_df(eff_d)
        df_usd_mat_raw = self.usd_sofr_curve.get_df(mat_d)

        df_krw_base = df_krw_start_raw if df_krw_start_raw > 0 else 1.0
        df_usd_base = df_usd_start_raw if df_usd_start_raw > 0 else 1.0

        df_krw_start = 1.0
        df_krw_mat = df_krw_mat_raw / df_krw_base
        df_usd_start = 1.0
        df_usd_mat = df_usd_mat_raw / df_usd_base

        # 2. Build Schedules for Leg 1 (KRW) and Leg 2 (USD)
        leg1_sched_items = []
        leg2_sched_items = []

        l1_custom = leg1_custom_schedule if (leg1_custom_schedule and len(leg1_custom_schedule) > 0) else (custom_schedule if (custom_schedule and len(custom_schedule) > 0) else None)
        l2_custom = leg2_custom_schedule if (leg2_custom_schedule and len(leg2_custom_schedule) > 0) else (custom_schedule if (custom_schedule and len(custom_schedule) > 0) else None)

        # Leg 1 (KRW Leg)
        if l1_custom:
            for idx, item in enumerate(l1_custom):
                s_d = datetime.datetime.strptime(item["start_date"], "%Y-%m-%d").date() if isinstance(item["start_date"], str) else item["start_date"]
                e_d = datetime.datetime.strptime(item["end_date"], "%Y-%m-%d").date() if isinstance(item["end_date"], str) else item["end_date"]
                p_d = datetime.datetime.strptime(item["pay_date"], "%Y-%m-%d").date() if isinstance(item.get("pay_date"), str) else item.get("pay_date", e_d)
                f_k = calc_dc_fraction(s_d, e_d, l1_dc)
                n_k = float(item.get("notional") or item.get("notional_krw") or notional_krw)
                leg1_sched_items.append({
                    "period_no": idx + 1,
                    "start_date": s_d,
                    "end_date": e_d,
                    "pay_date": p_d,
                    "fixing_date": item.get("fixing_date", "N/A"),
                    "day_count_fraction": f_k,
                    "num_days": (e_d - s_d).days,
                    "custom_rate_krw": float(item["fixed_rate_pct"]) if (item.get("fixed_rate_pct") is not None and float(item["fixed_rate_pct"]) > 0.0) else (float(item["rate_krw"]) if item.get("rate_krw") else None),
                    "custom_notional_krw": n_k
                })
            mat_d = leg1_sched_items[-1]["end_date"]
        else:
            raw_periods_l1 = gen_sched(
                effective_date=eff_d,
                maturity_date=mat_d,
                frequency_months=l1_freq,
                business_day_conv=l1_conv,
                pay_cal=l1_cal,
                stub_rule=l1_stub,
                adjust_rule=l1_adj
            )
            for idx, (a_st, a_ed, pay_dt, calc_st, calc_ed, u_st, u_ed) in enumerate(raw_periods_l1):
                f_k = calc_dc_fraction(calc_st, calc_ed, l1_dc)
                leg1_sched_items.append({
                    "period_no": idx + 1,
                    "start_date": a_st,
                    "end_date": a_ed,
                    "pay_date": pay_dt,
                    "fixing_date": "N/A",
                    "day_count_fraction": f_k,
                    "num_days": (a_ed - a_st).days,
                    "custom_rate_krw": None,
                    "custom_notional_krw": None
                })

        # Leg 2 (USD Leg)
        if l2_custom:
            for idx, item in enumerate(l2_custom):
                s_d = datetime.datetime.strptime(item["start_date"], "%Y-%m-%d").date() if isinstance(item["start_date"], str) else item["start_date"]
                e_d = datetime.datetime.strptime(item["end_date"], "%Y-%m-%d").date() if isinstance(item["end_date"], str) else item["end_date"]
                p_d = datetime.datetime.strptime(item["pay_date"], "%Y-%m-%d").date() if isinstance(item.get("pay_date"), str) else item.get("pay_date", e_d)
                f_u = calc_dc_fraction(s_d, e_d, l2_dc)
                f_date_str = item.get("fixing_date")
                if f_date_str:
                    f_date = datetime.datetime.strptime(f_date_str, "%Y-%m-%d").date() if isinstance(f_date_str, str) else f_date_str
                else:
                    f_date = compute_fixing_date(s_d, l2_fday, l2_fcal)
                n_u = float(item.get("notional") or item.get("notional_usd") or notional_usd)
                leg2_sched_items.append({
                    "period_no": idx + 1,
                    "start_date": s_d,
                    "end_date": e_d,
                    "pay_date": p_d,
                    "fixing_date": f_date,
                    "day_count_fraction_usd": f_u,
                    "num_days": (e_d - s_d).days,
                    "custom_rate_usd": float(item["fwd_sofr_pct"]) if (item.get("fwd_sofr_pct") is not None and float(item["fwd_sofr_pct"]) > 0.0) else (float(item["rate_usd"]) if (item.get("rate_usd") is not None and float(item["rate_usd"]) > 0.0) else None),
                    "custom_notional_usd": n_u
                })
            if not l1_custom:
                mat_d = leg2_sched_items[-1]["end_date"]
        else:
            raw_periods_l2 = gen_sched(
                effective_date=eff_d,
                maturity_date=mat_d,
                frequency_months=l2_freq,
                business_day_conv=l2_conv,
                pay_cal=l2_cal,
                stub_rule=l2_stub,
                adjust_rule=l2_adj
            )
            for idx, (a_st, a_ed, pay_dt, calc_st, calc_ed, u_st, u_ed) in enumerate(raw_periods_l2):
                f_u = calc_dc_fraction(calc_st, calc_ed, l2_dc)
                f_date = compute_fixing_date(a_st, l2_fday, l2_fcal)
                leg2_sched_items.append({
                    "period_no": idx + 1,
                    "start_date": a_st,
                    "end_date": a_ed,
                    "pay_date": pay_dt,
                    "fixing_date": f_date,
                    "day_count_fraction_usd": f_u,
                    "num_days": (a_ed - a_st).days,
                    "custom_rate_usd": None,
                    "custom_notional_usd": None
                })

        # 3. Calculate Annuities and Par Rates
        sum_krw_annuity = 0.0
        sum_krw_weighted_annuity = 0.0
        for p in leg1_sched_items:
            p_d = p.get("pay_date", p["end_date"])
            df_k = self.krw_fx_curve.get_df(p_d) / df_krw_base
            frac_k = p["day_count_fraction"]
            p_notional_krw = p.get("custom_notional_krw") or notional_krw
            sum_krw_annuity += frac_k * df_k
            sum_krw_weighted_annuity += p_notional_krw * frac_k * df_k

        sum_usd_annuity = 0.0
        sum_usd_weighted_annuity = 0.0
        sum_usd_pv_temp = 0.0
        for p in leg2_sched_items:
            s_d = p["start_date"]
            e_d = p["end_date"]
            p_d = p.get("pay_date", e_d)
            df_u = self.usd_sofr_curve.get_df(p_d) / df_usd_base
            frac_u = p["day_count_fraction_usd"]
            p_notional_usd = p.get("custom_notional_usd") or notional_usd
            sum_usd_annuity += frac_u * df_u
            sum_usd_weighted_annuity += p_notional_usd * frac_u * df_u

            if not is_fixed_fixed:
                # Forward USD SOFR Rate
                df_u_s = self.usd_sofr_curve.get_df(s_d)
                df_u_e = self.usd_sofr_curve.get_df(e_d)
                fwd_sofr = ((df_u_s / df_u_e) - 1.0) / frac_u * 100.0 if (df_u_e > 0 and frac_u > 0) else 3.50
                all_in_sofr = fwd_sofr + (spread_bp / 100.0)
                sum_usd_pv_temp += p_notional_usd * (all_in_sofr / 100.0) * frac_u * df_u

        # Principal Cashflows and PVs
        # Unsigned Principal Cash Flows
        flow_krw_ini = notional_krw if include_principal_exchange else 0.0
        flow_krw_fin = notional_krw if include_principal_exchange else 0.0
        flow_usd_ini = notional_usd if include_principal_exchange else 0.0
        flow_usd_fin = notional_usd if include_principal_exchange else 0.0

        # Position-signed Principal PVs (from trader's perspective)
        # Pay KRW Fixed: T0 receives KRW (+), pays USD (-). TM pays KRW (-), receives USD (+).
        prin_krw_ini_pv = -sign_krw * flow_krw_ini * df_krw_start if include_principal_exchange else 0.0
        prin_krw_fin_pv = sign_krw * flow_krw_fin * df_krw_mat if include_principal_exchange else 0.0
        prin_usd_ini_pv = -sign_usd * flow_usd_ini * df_usd_start if include_principal_exchange else 0.0
        prin_usd_fin_pv = sign_usd * flow_usd_fin * df_usd_mat if include_principal_exchange else 0.0

        # Calculate Equilibrium Par Rates based on swap structure
        par_krw_rate_pct = 0.0
        par_usd_rate_pct = 0.0
        exact_par_rate_pct = 0.0

        if is_fixed_fixed:
            # Fixed-to-Fixed CRS Mode.
            # Deal NPV is exactly linear in each fixed coupon:
            #   NPV = K + c_krw * (sign_krw * A_krw / 100) + c_usd * (sign_usd * fx * A_usd / 100)
            # where K is the principal-exchange-only NPV. Each par rate is therefore the
            # root of that line holding the other coupon fixed. Solving against the same
            # terms the NPV is assembled from keeps par and NPV consistent by construction.
            base_coupon_usd = usd_fixed_coupon_pct if usd_fixed_coupon_pct is not None else 3.50

            principal_npv_krw = (
                (prin_krw_ini_pv + prin_krw_fin_pv)
                + fx_rate * (prin_usd_ini_pv + prin_usd_fin_pv)
            )
            krw_pv_per_pct = sign_krw * sum_krw_weighted_annuity / 100.0
            usd_pv_per_pct = sign_usd * fx_rate * sum_usd_weighted_annuity / 100.0

            if krw_pv_per_pct != 0.0:
                par_krw_rate_pct = -(principal_npv_krw + base_coupon_usd * usd_pv_per_pct) / krw_pv_per_pct
            else:
                par_krw_rate_pct = 3.50

            # Par USD Rate that zeroes Deal NPV given the KRW Fixed Coupon:
            base_coupon_krw = fixed_coupon_pct if fixed_coupon_pct is not None else par_krw_rate_pct
            if usd_pv_per_pct != 0.0:
                par_usd_rate_pct = -(principal_npv_krw + base_coupon_krw * krw_pv_per_pct) / usd_pv_per_pct
            else:
                par_usd_rate_pct = 3.50

            exact_par_rate_pct = par_krw_rate_pct
            base_coupon = fixed_coupon_pct if fixed_coupon_pct is not None else par_krw_rate_pct
            base_coupon_usd_final = usd_fixed_coupon_pct if usd_fixed_coupon_pct is not None else par_usd_rate_pct
        else:
            # Vanilla CRS Mode (KRW Fixed vs USD SOFR Float).
            # Solved the same way as Fixed-Fixed: the KRW coupon that zeroes the NPV the
            # engine actually assembles. Deriving it from the USD leg PV keeps a non-zero
            # basis spread in the par rate instead of silently dropping it.
            principal_npv_krw = (
                (prin_krw_ini_pv + prin_krw_fin_pv)
                + fx_rate * (prin_usd_ini_pv + prin_usd_fin_pv)
            )
            usd_float_npv_krw = sign_usd * sum_usd_pv_temp * fx_rate
            krw_pv_per_pct = sign_krw * sum_krw_weighted_annuity / 100.0

            if krw_pv_per_pct != 0.0:
                exact_par_rate_pct = -(principal_npv_krw + usd_float_npv_krw) / krw_pv_per_pct
            elif sum_krw_annuity > 0:
                exact_par_rate_pct = ((df_krw_start - df_krw_mat) / sum_krw_annuity) * 100.0
            else:
                exact_par_rate_pct = 3.50

            base_coupon = fixed_coupon_pct if fixed_coupon_pct is not None else exact_par_rate_pct
            base_coupon_usd_final = 0.0

        # 4. Calculate Coupon Periodic Flows
        dual_comparison_table = []
        leg1_table = []
        leg2_table = []
        all_legs_table = []

        sum_krw_interest_cf = 0.0
        sum_krw_interest_pv = 0.0
        sum_usd_interest_cf = 0.0
        sum_usd_interest_pv = 0.0

        # Leg 1 (KRW Fixed) Processing
        for p in leg1_sched_items:
            s_d = p["start_date"]
            e_d = p["end_date"]
            p_d = p.get("pay_date", e_d)
            p_notional_krw = p.get("custom_notional_krw") or notional_krw
            frac_krw = p["day_count_fraction"]
            df_krw = self.krw_fx_curve.get_df(p_d) / df_krw_base
            c_rate_krw = float(p["custom_rate_krw"]) if p.get("custom_rate_krw") is not None else base_coupon
            
            krw_flow = p_notional_krw * (c_rate_krw / 100.0) * frac_krw
            krw_pv = sign_krw * krw_flow * df_krw

            sum_krw_interest_cf += krw_flow
            sum_krw_interest_pv += krw_pv

            leg1_table.append({
                "type": "INT",
                "period_no": p["period_no"],
                "start_date": s_d.strftime("%Y-%m-%d"),
                "end_date": e_d.strftime("%Y-%m-%d"),
                "pay_date": p_d.strftime("%Y-%m-%d"),
                "nominal": p_notional_krw,
                "notional": p_notional_krw,
                "currency": "KRW",
                "fixing_date": "N/A",
                "df": round(df_krw, 4),
                "discount_factor": round(df_krw, 4),
                "rate": round(c_rate_krw, 4),
                "fixed_rate_pct": round(c_rate_krw, 4),
                "day_count_fraction": frac_krw,
                "fraction": frac_krw,
                "flow": round(sign_krw * krw_flow, 2),
                "cash_flow": round(sign_krw * krw_flow, 2),
                "npv": round(krw_pv, 0),
                "present_value": round(krw_pv, 0),
                "num_days": (e_d - s_d).days
            })

            all_legs_table.append({
                "lg": 1,
                "flow_tp": "INT",
                "sub_tp": "",
                "start_date": s_d.strftime("%Y-%m-%d"),
                "end_date": e_d.strftime("%Y-%m-%d"),
                "remaining_capital": p_notional_krw,
                "first_fixing": "",
                "last_fixing": "",
                "rate": round(c_rate_krw, 5),
                "margin": 0.0,
                "pay_date": p_d.strftime("%Y-%m-%d"),
                "flow": round(sign_krw * krw_flow, 2),
                "currency": "KRW",
                "index": "",
                "num_days": (e_d - s_d).days
            })

        # Leg 2 (USD Float or USD Fixed) Processing
        for p in leg2_sched_items:
            s_d = p["start_date"]
            e_d = p["end_date"]
            p_d = p.get("pay_date", e_d)
            p_notional_usd = p.get("custom_notional_usd") or notional_usd
            frac_usd = p["day_count_fraction_usd"]
            df_usd = self.usd_sofr_curve.get_df(p_d) / df_usd_base

            if is_fixed_fixed:
                c_rate_usd = float(p["custom_rate_usd"]) if p.get("custom_rate_usd") is not None else base_coupon_usd_final
                usd_rate = c_rate_usd
                fixing_range_str = "N/A"
                index_label = "USD FIXED"
                spread_val = 0.0
            else:
                df_u_s = self.usd_sofr_curve.get_df(s_d)
                df_u_e = self.usd_sofr_curve.get_df(e_d)
                if p.get("custom_rate_usd") is not None:
                    fwd_sofr_rate = float(p["custom_rate_usd"])
                else:
                    fwd_sofr_rate = ((df_u_s / df_u_e) - 1.0) / frac_usd * 100.0 if (df_u_e > 0 and frac_usd > 0) else 3.50
                usd_rate = fwd_sofr_rate + (spread_bp / 100.0)
                fix_last = add_joint_business_days(e_d, -1, self.holidays)
                fixing_range_str = f"{s_d.strftime('%Y-%m-%d')} ~ {fix_last.strftime('%Y-%m-%d')}"
                index_label = "USD SOFR CMP"
                spread_val = spread_bp

            usd_flow = p_notional_usd * (usd_rate / 100.0) * frac_usd
            usd_pv = sign_usd * (usd_flow) * df_usd

            sum_usd_interest_cf += usd_flow
            sum_usd_interest_pv += usd_pv

            leg2_table.append({
                "type": "INT",
                "period_no": p["period_no"],
                "start_date": s_d.strftime("%Y-%m-%d"),
                "end_date": e_d.strftime("%Y-%m-%d"),
                "pay_date": p_d.strftime("%Y-%m-%d"),
                "nominal": p_notional_usd,
                "notional": p_notional_usd,
                "currency": "USD",
                "fixing_date": fixing_range_str,
                "df": round(df_usd, 4),
                "discount_factor": round(df_usd, 4),
                "rate": round(usd_rate, 4),
                "fixed_rate_pct": round(usd_rate, 4) if is_fixed_fixed else 0.0,
                "fwd_rate_pct": round(usd_rate, 4),
                "fwd_sofr_pct": round(usd_rate, 4) if not is_fixed_fixed else 0.0,
                "spread_bp": round(spread_val, 2),
                "day_count_fraction": frac_usd,
                "fraction": frac_usd,
                "flow": round(sign_usd * usd_flow, 2),
                "cash_flow": round(sign_usd * usd_flow, 2),
                "npv": round(usd_pv, 2),
                "present_value": round(usd_pv, 2),
                "num_days": (e_d - s_d).days
            })

            all_legs_table.append({
                "lg": 2,
                "flow_tp": "INT",
                "sub_tp": "",
                "start_date": s_d.strftime("%Y-%m-%d"),
                "end_date": e_d.strftime("%Y-%m-%d"),
                "remaining_capital": p_notional_usd,
                "first_fixing": s_d.strftime("%Y-%m-%d") if not is_fixed_fixed else "",
                "last_fixing": fix_last.strftime("%Y-%m-%d") if not is_fixed_fixed else "",
                "rate": round(usd_rate, 5),
                "margin": round(spread_val, 2),
                "pay_date": p_d.strftime("%Y-%m-%d"),
                "flow": round(sign_usd * usd_flow, 2),
                "currency": "USD",
                "index": index_label,
                "num_days": (e_d - s_d).days
            })

        # Dual Comparison Table (Pair rows up to max length)
        max_periods = max(len(leg1_table), len(leg2_table))
        for i in range(max_periods):
            r1 = leg1_table[i] if i < len(leg1_table) else None
            r2 = leg2_table[i] if i < len(leg2_table) else None

            f_krw = r1["flow"] if r1 else 0.0
            f_usd = r2["flow"] if r2 else 0.0
            pv_krw = r1["npv"] if r1 else 0.0
            pv_usd = r2["npv"] if r2 else 0.0

            net_cf = f_krw + (f_usd * fx_rate)
            net_pv = pv_krw + (pv_usd * fx_rate)

            dual_comparison_table.append({
                "period_no": (i + 1),
                "start_date": r1["start_date"] if r1 else (r2["start_date"] if r2 else ""),
                "end_date": r1["end_date"] if r1 else (r2["end_date"] if r2 else ""),
                "pay_date": r1["pay_date"] if r1 else (r2["pay_date"] if r2 else ""),
                "nominal_krw": r1["notional"] if r1 else 0.0,
                "notional": r1["notional"] if r1 else 0.0,
                "fixing_date_krw": "N/A",
                "df_krw": r1["df"] if r1 else 0.0,
                "discount_factor": r1["df"] if r1 else 0.0,
                "rate_krw_pct": r1["rate"] if r1 else 0.0,
                "fixed_rate_pct": r1["rate"] if r1 else 0.0,
                "rate": r1["rate"] if r1 else 0.0,
                "flow_krw": f_krw,
                "fixed_cf": f_krw,
                "npv_krw": pv_krw,
                "fixed_pv": pv_krw,
                "nominal_usd": r2["notional"] if r2 else 0.0,
                "notional_usd": r2["notional"] if r2 else 0.0,
                "fixing_date_usd": r2["fixing_date"] if r2 else "N/A",
                "df_usd": r2["df"] if r2 else 0.0,
                "discount_factor_usd": r2["df"] if r2 else 0.0,
                "rate_usd_pct": r2["rate"] if r2 else 0.0,
                "fwd_rate_pct": r2["rate"] if r2 else 0.0,
                "fwd_sofr_pct": r2.get("fwd_sofr_pct", 0.0) if r2 else 0.0,
                "flow_usd": f_usd,
                "float_cf": f_usd,
                "npv_usd": pv_usd,
                "float_pv": pv_usd,
                "net_cf": round(net_cf, 2),
                "net_pv": round(net_pv, 0),
                "net_npv_krw": round(net_pv, 0),
                "day_count_fraction": r1["day_count_fraction"] if r1 else 0.0,
                "day_count_fraction_usd": r2["day_count_fraction"] if r2 else 0.0,
                "num_days": r1["num_days"] if r1 else (r2["num_days"] if r2 else 0)
            })

        # 5. Principal Exchange Flows (Start & Maturity)
        flow_krw_ini_signed = -sign_krw * flow_krw_ini
        flow_krw_fin_signed = sign_krw * flow_krw_fin
        flow_usd_ini_signed = -sign_usd * flow_usd_ini
        flow_usd_fin_signed = sign_usd * flow_usd_fin

        principal_rows = {
            "ini": {
                "label": "Initial Principal Exchange (T0)",
                "pay_date": eff_d.strftime("%Y-%m-%d"),
                "nominal_krw": flow_krw_ini_signed,
                "df_krw": round(df_krw_start, 4),
                "npv_krw": round(prin_krw_ini_pv, 0),
                "nominal_usd": flow_usd_ini_signed,
                "df_usd": round(df_usd_start, 4),
                "npv_usd": round(prin_usd_ini_pv, 2)
            },
            "fin": {
                "label": "Final Principal Exchange (TM)",
                "pay_date": mat_d.strftime("%Y-%m-%d"),
                "nominal_krw": flow_krw_fin_signed,
                "df_krw": round(df_krw_mat, 4),
                "npv_krw": round(prin_krw_fin_pv, 0),
                "nominal_usd": flow_usd_fin_signed,
                "df_usd": round(df_usd_mat, 4),
                "npv_usd": round(prin_usd_fin_pv, 2)
            }
        }

        if include_principal_exchange:
            leg1_table.append({
                "type": "PRI INI",
                "period_no": "PRI",
                "start_date": eff_d.strftime("%Y-%m-%d"),
                "end_date": eff_d.strftime("%Y-%m-%d"),
                "pay_date": eff_d.strftime("%Y-%m-%d"),
                "nominal": notional_krw,
                "currency": "KRW",
                "fixing_date": "N/A",
                "df": round(df_krw_start, 4),
                "rate": 0.0,
                "flow": round(flow_krw_ini_signed, 2),
                "npv": round(prin_krw_ini_pv, 0),
                "num_days": 0
            })
            leg1_table.append({
                "type": "PRI FIN",
                "period_no": "PRI",
                "start_date": mat_d.strftime("%Y-%m-%d"),
                "end_date": mat_d.strftime("%Y-%m-%d"),
                "pay_date": mat_d.strftime("%Y-%m-%d"),
                "nominal": notional_krw,
                "currency": "KRW",
                "fixing_date": "N/A",
                "df": round(df_krw_mat, 4),
                "rate": 0.0,
                "flow": round(flow_krw_fin_signed, 2),
                "npv": round(prin_krw_fin_pv, 0),
                "num_days": 0
            })

            leg2_table.append({
                "type": "PRI INI",
                "period_no": "PRI",
                "start_date": eff_d.strftime("%Y-%m-%d"),
                "end_date": eff_d.strftime("%Y-%m-%d"),
                "pay_date": eff_d.strftime("%Y-%m-%d"),
                "nominal": notional_usd,
                "currency": "USD",
                "fixing_date": "N/A",
                "df": round(df_usd_start, 4),
                "rate": 0.0,
                "flow": round(flow_usd_ini_signed, 2),
                "npv": round(prin_usd_ini_pv, 2),
                "num_days": 0
            })
            leg2_table.append({
                "type": "PRI FIN",
                "period_no": "PRI",
                "start_date": mat_d.strftime("%Y-%m-%d"),
                "end_date": mat_d.strftime("%Y-%m-%d"),
                "pay_date": mat_d.strftime("%Y-%m-%d"),
                "nominal": notional_usd,
                "currency": "USD",
                "fixing_date": "N/A",
                "df": round(df_usd_mat, 4),
                "rate": 0.0,
                "flow": round(flow_usd_fin_signed, 2),
                "npv": round(prin_usd_fin_pv, 2),
                "num_days": 0
            })

            all_legs_table.append({
                "lg": 1,
                "flow_tp": "PRI",
                "sub_tp": "INI",
                "start_date": "",
                "end_date": "",
                "remaining_capital": notional_krw,
                "first_fixing": "",
                "last_fixing": "",
                "rate": 0.0,
                "margin": 0.0,
                "pay_date": eff_d.strftime("%Y-%m-%d"),
                "flow": round(flow_krw_ini_signed, 2),
                "currency": "KRW",
                "index": "",
                "num_days": 0
            })
            all_legs_table.append({
                "lg": 1,
                "flow_tp": "PRI",
                "sub_tp": "FIN",
                "start_date": "",
                "end_date": "",
                "remaining_capital": notional_krw,
                "first_fixing": "",
                "last_fixing": "",
                "rate": 0.0,
                "margin": 0.0,
                "pay_date": mat_d.strftime("%Y-%m-%d"),
                "flow": round(flow_krw_fin_signed, 2),
                "currency": "KRW",
                "index": "",
                "num_days": 0
            })
            all_legs_table.append({
                "lg": 2,
                "flow_tp": "PRI",
                "sub_tp": "INI",
                "start_date": "",
                "end_date": "",
                "remaining_capital": notional_usd,
                "first_fixing": "",
                "last_fixing": "",
                "rate": 0.0,
                "margin": 0.0,
                "pay_date": eff_d.strftime("%Y-%m-%d"),
                "flow": round(flow_usd_ini_signed, 2),
                "currency": "USD",
                "index": "",
                "num_days": 0
            })
            all_legs_table.append({
                "lg": 2,
                "flow_tp": "PRI",
                "sub_tp": "FIN",
                "start_date": "",
                "end_date": "",
                "remaining_capital": notional_usd,
                "first_fixing": "",
                "last_fixing": "",
                "rate": 0.0,
                "margin": 0.0,
                "pay_date": mat_d.strftime("%Y-%m-%d"),
                "flow": round(flow_usd_fin_signed, 2),
                "currency": "USD",
                "index": "",
                "num_days": 0
            })

        # 6. Total Leg Valuation & Risk Metrics
        total_krw_leg_pv = prin_krw_ini_pv + sum_krw_interest_pv + prin_krw_fin_pv
        total_usd_leg_pv = prin_usd_ini_pv + sum_usd_interest_pv + prin_usd_fin_pv

        deal_npv_krw = total_krw_leg_pv + (total_usd_leg_pv * fx_rate)
        deal_npv_usd = deal_npv_krw / fx_rate

        is_par_calc = (fixed_coupon_pct is None)
        if is_par_calc or abs(exact_par_rate_pct - (fixed_coupon_pct or 0.0)) < 1e-4:
            deal_npv_krw = 0.0
            deal_npv_usd = 0.0
            total_krw_leg_pv = 0.0
            total_usd_leg_pv = 0.0

        spread_vs_coupon_bp = (exact_par_rate_pct - base_coupon) * 100.0

        krw_dv01 = notional_krw * sum_krw_annuity * 0.0001
        usd_dv01 = notional_usd * sum_usd_annuity * 0.0001
        fx_delta = total_usd_leg_pv

        key_rate_deltas = []
        hedge_key_rate_deltas = []
        krw_key_rate_deltas = []
        if calculate_greeks:
            # Pass the resolved coupons, never the raw request values: a None coupon would
            # put every bumped reprice back into par mode, zeroing all deltas.
            key_rate_deltas = self._calc_crs_key_rate_deltas(
                base_deal_npv_krw=deal_npv_krw,
                usd_notional=notional_usd,
                krw_notional=notional_krw,
                spot_fx=fx_rate,
                position=position,
                fixed_coupon_pct=base_coupon,
                spread_bp=spread_bp,
                effective_date=eff_d,
                maturity_date=mat_d,
                tenor_str=tenor_str,
                frequency_months=frequency_months,
                payment_lag_bd=payment_lag_bd,
                day_count_krw=day_count_krw,
                day_count_usd=day_count_usd,
                business_day_conv=business_day_conv,
                stub_rule=stub_rule,
                adjust_rule=adjust_rule,
                fix_cal=fix_cal,
                pay_cal=pay_cal,
                fix_day=fix_day,
                include_principal_exchange=include_principal_exchange,
                custom_schedule=custom_schedule,
                leg1_custom_schedule=leg1_custom_schedule,
                leg2_custom_schedule=leg2_custom_schedule,
                swap_type=swap_type,
                usd_fixed_coupon_pct=(base_coupon_usd_final if is_fixed_fixed else usd_fixed_coupon_pct),
                leg1_frequency_months=leg1_frequency_months,
                leg1_day_count=leg1_day_count,
                leg1_stub_rule=leg1_stub_rule,
                leg1_business_day_conv=leg1_business_day_conv,
                leg1_adjust_rule=leg1_adjust_rule,
                leg1_pay_cal=leg1_pay_cal,
                leg2_frequency_months=leg2_frequency_months,
                leg2_day_count=leg2_day_count,
                leg2_stub_rule=leg2_stub_rule,
                leg2_business_day_conv=leg2_business_day_conv,
                leg2_adjust_rule=leg2_adjust_rule,
                leg2_pay_cal=leg2_pay_cal,
                leg2_fix_cal=leg2_fix_cal,
                leg2_fix_day=leg2_fix_day,
                force_hedge_mode=False
            )
            is_advanced = hasattr(self.usd_sofr_curve, "ql_curve") or getattr(self.usd_sofr_curve, "curve_type", "") == "Advanced"
            if is_advanced:
                hedge_key_rate_deltas = self._calc_crs_key_rate_deltas(
                    base_deal_npv_krw=deal_npv_krw,
                    usd_notional=notional_usd,
                    krw_notional=notional_krw,
                    spot_fx=fx_rate,
                    position=position,
                    fixed_coupon_pct=base_coupon,
                    spread_bp=spread_bp,
                    effective_date=eff_d,
                    maturity_date=mat_d,
                    tenor_str=tenor_str,
                    frequency_months=frequency_months,
                    payment_lag_bd=payment_lag_bd,
                    day_count_krw=day_count_krw,
                    day_count_usd=day_count_usd,
                    business_day_conv=business_day_conv,
                    stub_rule=stub_rule,
                    adjust_rule=adjust_rule,
                    fix_cal=fix_cal,
                    pay_cal=pay_cal,
                    fix_day=fix_day,
                    include_principal_exchange=include_principal_exchange,
                    custom_schedule=custom_schedule,
                    leg1_custom_schedule=leg1_custom_schedule,
                    leg2_custom_schedule=leg2_custom_schedule,
                    swap_type=swap_type,
                    usd_fixed_coupon_pct=(base_coupon_usd_final if is_fixed_fixed else usd_fixed_coupon_pct),
                    leg1_frequency_months=leg1_frequency_months,
                    leg1_day_count=leg1_day_count,
                    leg1_stub_rule=leg1_stub_rule,
                    leg1_business_day_conv=leg1_business_day_conv,
                    leg1_adjust_rule=leg1_adjust_rule,
                    leg1_pay_cal=leg1_pay_cal,
                    leg2_frequency_months=leg2_frequency_months,
                    leg2_day_count=leg2_day_count,
                    leg2_stub_rule=leg2_stub_rule,
                    leg2_business_day_conv=leg2_business_day_conv,
                    leg2_adjust_rule=leg2_adjust_rule,
                    leg2_pay_cal=leg2_pay_cal,
                    leg2_fix_cal=leg2_fix_cal,
                    leg2_fix_day=leg2_fix_day,
                    force_hedge_mode=True
                )

            krw_key_rate_deltas = self._calc_crs_krw_key_rate_deltas(
                base_deal_npv_krw=deal_npv_krw,
                pricer_kwargs=dict(
                    usd_notional=notional_usd,
                    krw_notional=notional_krw,
                    spot_fx=fx_rate,
                    position=position,
                    fixed_coupon_pct=base_coupon,
                    spread_bp=spread_bp,
                    effective_date=eff_d,
                    maturity_date=mat_d,
                    tenor_str=tenor_str,
                    frequency_months=frequency_months,
                    payment_lag_bd=payment_lag_bd,
                    day_count_krw=day_count_krw,
                    day_count_usd=day_count_usd,
                    business_day_conv=business_day_conv,
                    stub_rule=stub_rule,
                    adjust_rule=adjust_rule,
                    fix_cal=fix_cal,
                    pay_cal=pay_cal,
                    fix_day=fix_day,
                    include_principal_exchange=include_principal_exchange,
                    custom_schedule=custom_schedule,
                    leg1_custom_schedule=leg1_custom_schedule,
                    leg2_custom_schedule=leg2_custom_schedule,
                    swap_type=swap_type,
                    usd_fixed_coupon_pct=(base_coupon_usd_final if is_fixed_fixed else usd_fixed_coupon_pct),
                    leg1_frequency_months=leg1_frequency_months,
                    leg1_day_count=leg1_day_count,
                    leg1_stub_rule=leg1_stub_rule,
                    leg1_business_day_conv=leg1_business_day_conv,
                    leg1_adjust_rule=leg1_adjust_rule,
                    leg1_pay_cal=leg1_pay_cal,
                    leg2_frequency_months=leg2_frequency_months,
                    leg2_day_count=leg2_day_count,
                    leg2_stub_rule=leg2_stub_rule,
                    leg2_business_day_conv=leg2_business_day_conv,
                    leg2_adjust_rule=leg2_adjust_rule,
                    leg2_pay_cal=leg2_pay_cal,
                    leg2_fix_cal=leg2_fix_cal,
                    leg2_fix_day=leg2_fix_day,
                )
            )

        return {
            "currency": "USD_KRW_CRS",
            "instrument": "KRWFXSOFR (Cross Currency Swap)",
            "swap_type": "Fixed-Fixed" if is_fixed_fixed else "Vanilla",
            "effective_date": eff_d.strftime("%Y-%m-%d"),
            "maturity_date": mat_d.strftime("%Y-%m-%d"),
            "tenor": tenor_str,
            "spot_fx": fx_rate,
            "usd_notional": notional_usd,
            "krw_notional": notional_krw,
            "position": position,
            "fixed_coupon_pct": round(base_coupon, 6),
            "usd_fixed_coupon_pct": round(base_coupon_usd_final, 6) if is_fixed_fixed else None,
            "pricing_results": {
                "par_crs_rate_pct": round(exact_par_rate_pct, 6),
                "par_krw_rate_pct": round(par_krw_rate_pct if is_fixed_fixed else exact_par_rate_pct, 6),
                "par_usd_rate_pct": round(par_usd_rate_pct, 6) if is_fixed_fixed else None,
                "spread_vs_coupon_bp": round(spread_vs_coupon_bp, 4),
                "deal_npv_krw": round(deal_npv_krw, 6),
                "deal_npv_usd": round(deal_npv_usd, 6),
                "deal_npv": round(deal_npv_krw, 6),
                "leg1_npv_krw": round(total_krw_leg_pv, 6),
                "leg1_int_pv_krw": round(sum_krw_interest_pv, 6),
                "leg1_bpv_krw": round(-sign_krw * krw_dv01, 2),
                "leg2_npv_usd": round(total_usd_leg_pv, 6),
                "leg2_int_pv_usd": round(sum_usd_interest_pv, 6),
                "leg2_npv_krw": round(total_usd_leg_pv * fx_rate, 6),
                "leg2_bpv_usd": round(sign_usd * usd_dv01, 2),
                "krw_dv01": round(krw_dv01, 2),
                "usd_dv01": round(usd_dv01, 2),
                "fx_delta": round(fx_delta, 2),
                "annuity_krw": round(sum_krw_annuity, 6),
                "annuity_usd": round(sum_usd_annuity, 6)
            },
            "principal_flows": {
                "included": include_principal_exchange,
                "start_krw": round(prin_krw_ini_pv, 0),
                "start_usd": round(prin_usd_ini_pv, 2),
                "mat_krw": round(prin_krw_fin_pv, 0),
                "mat_usd": round(prin_usd_fin_pv, 2)
            },
            "principal_rows": principal_rows,
            "schedules": {
                "dual_comparison": dual_comparison_table,
                "leg1_schedule": leg1_table,
                "leg2_schedule": leg2_table,
                "all_legs_murex": all_legs_table,
                "principal_rows": principal_rows
            },
            "key_rate_deltas": key_rate_deltas,
            "hedge_key_rate_deltas": hedge_key_rate_deltas,
            "krw_key_rate_deltas": krw_key_rate_deltas
        }

    def _calc_crs_key_rate_deltas(
        self,
        base_deal_npv_krw: float,
        usd_notional: float,
        krw_notional: float,
        spot_fx: float,
        position: str,
        fixed_coupon_pct: Optional[float],
        spread_bp: float,
        effective_date: Optional[datetime.date],
        maturity_date: Optional[datetime.date],
        tenor_str: str,
        frequency_months: int,
        payment_lag_bd: int,
        day_count_krw: str,
        day_count_usd: str,
        business_day_conv: str,
        stub_rule: str,
        adjust_rule: str,
        fix_cal: str,
        pay_cal: str,
        fix_day: int,
        include_principal_exchange: bool,
        custom_schedule: Optional[List[Dict[str, Any]]],
        leg1_custom_schedule: Optional[List[Dict[str, Any]]],
        leg2_custom_schedule: Optional[List[Dict[str, Any]]],
        swap_type: str,
        usd_fixed_coupon_pct: Optional[float],
        leg1_frequency_months: Optional[int],
        leg1_day_count: Optional[str],
        leg1_stub_rule: Optional[str],
        leg1_business_day_conv: Optional[str],
        leg1_adjust_rule: Optional[str],
        leg1_pay_cal: Optional[str],
        leg2_frequency_months: Optional[int],
        leg2_day_count: Optional[str],
        leg2_stub_rule: Optional[str],
        leg2_business_day_conv: Optional[str],
        leg2_adjust_rule: Optional[str],
        leg2_pay_cal: Optional[str],
        leg2_fix_cal: Optional[str],
        leg2_fix_day: Optional[int],
        force_hedge_mode: bool = False
    ) -> List[Dict[str, Any]]:
        deltas = []
        pillar_labels = ["1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y", "15Y", "20Y"]
        
        base_quotes = [("ON" if p["tenor"] in ("O/N", "ON") else p["tenor"], p["rate"]) for p in getattr(self.usd_sofr_curve, "pillars", [])]
        if not base_quotes:
            return []
            
        is_hedge_curve = force_hedge_mode or getattr(self.usd_sofr_curve, "curve_type", "") in ("HedgeCurve", "Hedge", "Composite") or hasattr(self.usd_sofr_curve, "delta_zh_func")
        is_advanced = hasattr(self.usd_sofr_curve, "ql_curve") or getattr(self.usd_sofr_curve, "curve_type", "") == "Advanced"
        from sofr_pricer.curve_engine import bootstrap_sofr_curve, bootstrap_advanced_sofr_curve, CompositeSOFRCurve, create_hedge_composite_curve
        
        p_date = getattr(self.usd_sofr_curve, "pricing_date", datetime.date.today())
        s_date = getattr(self.usd_sofr_curve, "settle_date", p_date + datetime.timedelta(days=2))
        
        for p in pillar_labels:
            if is_hedge_curve:
                base_c = self.usd_sofr_curve.base_curve if isinstance(self.usd_sofr_curve, CompositeSOFRCurve) else self.usd_sofr_curve
                bumped_usd_curve = create_hedge_composite_curve(
                    base_pricing_curve=base_c,
                    bumped_tenor=p,
                    bump_bp=0.0001
                )
            else:
                bumped_q = []
                bump_applied = False
                for t, r in base_quotes:
                    if t == p:
                        bumped_q.append((t, r + 0.01))
                        bump_applied = True
                    else:
                        bumped_q.append((t, r))
                if not bump_applied:
                    continue
                    
                if is_advanced:
                    bumped_usd_curve = bootstrap_advanced_sofr_curve(p_date, s_date, bumped_q)
                else:
                    bumped_usd_curve = bootstrap_sofr_curve(p_date, s_date, bumped_q)
                
            bumped_pricer = KRWFXSOFRSwapPricer(self.krw_fx_curve, bumped_usd_curve, spot_fx)
            r_bump = bumped_pricer.price_swap(
                usd_notional=usd_notional,
                krw_notional=krw_notional,
                spot_fx=spot_fx,
                position=position,
                fixed_coupon_pct=fixed_coupon_pct,
                spread_bp=spread_bp,
                effective_date=effective_date,
                maturity_date=maturity_date,
                tenor_str=tenor_str,
                frequency_months=frequency_months,
                payment_lag_bd=payment_lag_bd,
                day_count_krw=day_count_krw,
                day_count_usd=day_count_usd,
                business_day_conv=business_day_conv,
                stub_rule=stub_rule,
                adjust_rule=adjust_rule,
                fix_cal=fix_cal,
                pay_cal=pay_cal,
                fix_day=fix_day,
                include_principal_exchange=include_principal_exchange,
                custom_schedule=custom_schedule,
                leg1_custom_schedule=leg1_custom_schedule,
                leg2_custom_schedule=leg2_custom_schedule,
                swap_type=swap_type,
                usd_fixed_coupon_pct=usd_fixed_coupon_pct,
                leg1_frequency_months=leg1_frequency_months,
                leg1_day_count=leg1_day_count,
                leg1_stub_rule=leg1_stub_rule,
                leg1_business_day_conv=leg1_business_day_conv,
                leg1_adjust_rule=leg1_adjust_rule,
                leg1_pay_cal=leg1_pay_cal,
                leg2_frequency_months=leg2_frequency_months,
                leg2_day_count=leg2_day_count,
                leg2_stub_rule=leg2_stub_rule,
                leg2_business_day_conv=leg2_business_day_conv,
                leg2_adjust_rule=leg2_adjust_rule,
                leg2_pay_cal=leg2_pay_cal,
                leg2_fix_cal=leg2_fix_cal,
                leg2_fix_day=leg2_fix_day,
                calculate_greeks=False
            )
            delta_npv_krw = r_bump["pricing_results"]["deal_npv_krw"] - base_deal_npv_krw
            deltas.append({
                "pillar": p,
                "tenor": p,
                "dv01": round(delta_npv_krw, 0),
                "delta_dv01": round(delta_npv_krw, 0)
            })

        return deltas

    def _calc_crs_krw_key_rate_deltas(
        self,
        base_deal_npv_krw: float,
        pricer_kwargs: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Key Rate DV01 against the KRW FX SOFR (CRS) curve - the leg that carries the
        swap's dominant rate risk. Bumps each quoted CRS pillar by +1bp and reprices.
        """
        from .crs_curve_engine import bootstrap_crs_curve

        base_quotes = [(p["tenor"], p["rate"]) for p in getattr(self.krw_fx_curve, "pillars", [])
                       if p.get("months", 0) > 0]
        if not base_quotes:
            return []

        spot = getattr(self.krw_fx_curve, "spot_fx", pricer_kwargs.get("spot_fx", 1335.50))
        p_date = self.krw_fx_curve.pricing_date
        s_date = self.krw_fx_curve.settle_date

        deltas = []
        for b_tenor in ["1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y", "15Y", "20Y"]:
            bumped_q = []
            bump_applied = False
            for t, r in base_quotes:
                if t == b_tenor:
                    bumped_q.append((t, r + 0.01))
                    bump_applied = True
                else:
                    bumped_q.append((t, r))
            if not bump_applied:
                continue

            bumped_krw_curve = bootstrap_crs_curve(p_date, s_date, bumped_q, spot)
            bumped_pricer = KRWFXSOFRSwapPricer(bumped_krw_curve, self.usd_sofr_curve, spot)
            r_bump = bumped_pricer.price_swap(calculate_greeks=False, **pricer_kwargs)

            delta_npv_krw = r_bump["pricing_results"]["deal_npv_krw"] - base_deal_npv_krw
            deltas.append({
                "pillar": b_tenor,
                "tenor": b_tenor,
                "dv01": round(delta_npv_krw, 0),
                "delta_dv01": round(delta_npv_krw, 0)
            })

        return deltas
