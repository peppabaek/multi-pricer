"""
KOFR Swap Pricing Engine
- Implements Murex '\\KRW KOFR Q 3M' Dual-Leg IRS & OIS Pricer
- Supports:
  - Vanilla auto-generated 3M schedule with +2 Business Days payment lag
  - Custom pasted / amortizing schedules
  - Par Swap Rate (Equilibrium)
  - Fixed Leg NPV, Float Leg NPV, Deal NPV (₩)
  - DV01 / BPV (₩/bp) and Key Rate Deltas
"""

import datetime
from typing import List, Dict, Any, Optional
from .kofr_date_engine import (
    generate_kofr_schedule,
    get_seoul_holidays,
    apply_kofr_convention,
    add_months,
    add_business_days,
    day_count_fraction
)
from .kofr_curve_engine import KOFRCurve

def parse_date(d):
    if isinstance(d, str):
        return datetime.datetime.strptime(d, "%Y-%m-%d").date()
    return d


def _apply_payment_lag(pay_dt: datetime.date, lag_bd: int, cal_code: str) -> datetime.date:
    r"""Murex '\KRW KOFR Q 3M' settles lag_bd business days after the accrual end."""
    if not lag_bd:
        return pay_dt
    from server.calendar_manager import add_business_days as add_bd
    return add_bd(pay_dt, lag_bd, cal_code)

class KOFRSwapPricer:
    def __init__(self, curve: KOFRCurve):
        self.curve = curve
        self.holidays = get_seoul_holidays()

    def price_swap(
        self,
        notional: float = 10_000_000_000.0, # Default 100억 원 (or any custom notional)
        position: str = "Pay Fixed",        # "Pay Fixed" or "Receive Fixed"
        fixed_coupon_pct: Optional[float] = None, # in % p.a.
        spread_bp: float = 0.0,             # Float spread in bp
        first_fixing_pct: Optional[float] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        tenor_str: str = "1Y",
        frequency_months: int = 3,          # 3M Quarterly (Murex '\KRW KOFR Q 3M')
        payment_lag_bd: int = 2,            # +2 Business Day Payment Lag
        day_count: str = "Act/365",
        business_day_conv: str = "Modified Following",
        stub_rule: str = "Short in arrears",
        adjust_rule: str = "Adjust",
        fix_cal: str = "SEB",
        pay_cal: str = "SEB",
        fix_day: int = 0,
        custom_schedule: Optional[List[Dict[str, Any]]] = None,
        leg1_custom_schedule: Optional[List[Dict[str, Any]]] = None,
        leg2_custom_schedule: Optional[List[Dict[str, Any]]] = None,
        # Independent Leg 1 (Fixed Leg)
        leg1_frequency_months: Optional[int] = None,
        leg1_day_count: Optional[str] = None,
        leg1_stub_rule: Optional[str] = None,
        leg1_business_day_conv: Optional[str] = None,
        leg1_adjust_rule: Optional[str] = None,
        leg1_pay_cal: Optional[str] = None,
        # Independent Leg 2 (Floating Leg)
        leg2_frequency_months: Optional[int] = None,
        leg2_day_count: Optional[str] = None,
        leg2_stub_rule: Optional[str] = None,
        leg2_business_day_conv: Optional[str] = None,
        leg2_adjust_rule: Optional[str] = None,
        leg2_pay_cal: Optional[str] = None,
        leg2_fix_cal: Optional[str] = None,
        leg2_fix_day: Optional[int] = None,
        swap_type: str = "Vanilla",
        usd_fixed_coupon_pct: Optional[float] = None,
        calculate_greeks: bool = True
    ) -> Dict[str, Any]:
        r"""
        Price KOFR OIS Swap matching Murex '\KRW KOFR Q 3M' Generator
        Supports Independent Leg 1 vs Leg 2 Parameters and All 4 Stub Rules
        """
        from server.calendar_manager import (
            generate_schedule as gen_sched,
            compute_fixing_date,
            day_count_fraction as calc_dc_fraction,
            apply_convention as apply_conv,
            add_months as add_m,
            resolve_custom_pay_date,
            floating_rate_for_period
        )
        
        # Resolve Leg 1 and Leg 2 parameters
        l1_freq = leg1_frequency_months or frequency_months or 3
        l1_dc = leg1_day_count or day_count or "Act/365"
        l1_stub = leg1_stub_rule or stub_rule or "Short in arrears"
        l1_conv = leg1_business_day_conv or business_day_conv or "Modified Following"
        l1_adj = leg1_adjust_rule or adjust_rule or "Adjust"
        l1_cal = leg1_pay_cal or pay_cal or "SEB"

        l2_freq = leg2_frequency_months or frequency_months or 3
        l2_dc = leg2_day_count or day_count or "Act/365"
        l2_stub = leg2_stub_rule or stub_rule or "Short in arrears"
        l2_conv = leg2_business_day_conv or business_day_conv or "Modified Following"
        l2_adj = leg2_adjust_rule or adjust_rule or "Adjust"
        l2_cal = leg2_pay_cal or pay_cal or "SEB"
        l2_fcal = leg2_fix_cal or fix_cal or "SEB"
        l2_fday = leg2_fix_day if leg2_fix_day is not None else fix_day

        eff_d = effective_date if effective_date else self.curve.settle_date
        
        df_settle = getattr(self.curve, "df_settle", 1.0)
        if df_settle <= 0:
            df_settle = 1.0

        leg1_fixed = []
        leg2_floating = []
        comparison_table = []
        sum_float_pv = 0.0
        sum_fixed_pv = 0.0
        sum_weighted_annuity = 0.0

        l1_custom = leg1_custom_schedule if (leg1_custom_schedule and len(leg1_custom_schedule) > 0) else (custom_schedule if (custom_schedule and len(custom_schedule) > 0) else None)
        l2_custom = leg2_custom_schedule if (leg2_custom_schedule and len(leg2_custom_schedule) > 0) else (custom_schedule if (custom_schedule and len(custom_schedule) > 0) else None)

        c_pct_val = fixed_coupon_pct if fixed_coupon_pct is not None else 3.50
        is_fixed_fixed = bool(swap_type and ("fixed" in swap_type.lower() and "vanilla" not in swap_type.lower()))
        c2_val = usd_fixed_coupon_pct if usd_fixed_coupon_pct is not None else 3.50

        # Leg 1 (Fixed)
        if l1_custom:
            for idx, p in enumerate(l1_custom):
                s_d = parse_date(p.get("start_date", eff_d))
                e_d = parse_date(p.get("end_date", add_m(s_d, l1_freq)))
                pay_d = resolve_custom_pay_date(p, e_d, l1_conv, l1_cal)
                p_notional = float(p.get("notional", notional))
                frac = float(p.get("day_count_fraction", calc_dc_fraction(s_d, e_d, l1_dc)))
                c_pct_in = p.get("fixed_rate_pct")
                c_pct = float(c_pct_in) if (c_pct_in is not None and float(c_pct_in) > 0.0) else c_pct_val
                df_pay = self.curve.get_df(pay_d) / df_settle
                fixed_cf = p_notional * (c_pct / 100.0) * frac
                fixed_pv = fixed_cf * df_pay
                sum_fixed_pv += fixed_pv
                sum_weighted_annuity += (p_notional / notional) * frac * df_pay
                leg1_fixed.append({
                    "period_no": idx + 1,
                    "start_date": s_d.strftime("%Y-%m-%d"),
                    "end_date": e_d.strftime("%Y-%m-%d"),
                    "pay_date": pay_d.strftime("%Y-%m-%d"),
                    "fixing_date": p.get("fixing_date", "N/A"),
                    "notional": p_notional,
                    "day_count_fraction": round(frac, 6),
                    "fixed_rate_pct": round(c_pct, 4),
                    "cash_flow": round(fixed_cf, 2),
                    "discount_factor": round(df_pay, 6),
                    "present_value": round(fixed_pv, 2)
                })
            mat_d = parse_date(l1_custom[-1].get("end_date", eff_d))
        else:
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
                    mat_d = apply_conv(add_m(eff_d, 12), l1_conv, l1_cal)

            raw_sched_l1 = gen_sched(
                effective_date=eff_d,
                maturity_date=mat_d,
                frequency_months=l1_freq,
                business_day_conv=l1_conv,
                pay_cal=l1_cal,
                stub_rule=l1_stub,
                adjust_rule=l1_adj
            )
            for idx, (a_st, a_ed, pay_dt, calc_st, calc_ed, u_st, u_ed) in enumerate(raw_sched_l1):
                pay_dt = _apply_payment_lag(pay_dt, payment_lag_bd, l1_cal)
                frac = calc_dc_fraction(calc_st, calc_ed, l1_dc)
                df_pay = self.curve.get_df(pay_dt) / df_settle
                fixed_cf = notional * (c_pct_val / 100.0) * frac
                fixed_pv = fixed_cf * df_pay
                sum_fixed_pv += fixed_pv
                sum_weighted_annuity += frac * df_pay
                leg1_fixed.append({
                    "period_no": idx + 1,
                    "start_date": a_st.strftime("%Y-%m-%d"),
                    "end_date": a_ed.strftime("%Y-%m-%d"),
                    "pay_date": pay_dt.strftime("%Y-%m-%d"),
                    "fixing_date": "N/A",
                    "notional": notional,
                    "day_count_fraction": round(frac, 6),
                    "fixed_rate_pct": round(c_pct_val, 4),
                    "cash_flow": round(fixed_cf, 2),
                    "discount_factor": round(df_pay, 6),
                    "present_value": round(fixed_pv, 2)
                })

        # Leg 2 (Floating KOFR)
        if l2_custom:
            for idx, p in enumerate(l2_custom):
                s_d = parse_date(p.get("start_date", eff_d))
                e_d = parse_date(p.get("end_date", add_m(s_d, l2_freq)))
                pay_d = resolve_custom_pay_date(p, e_d, l2_conv, l2_cal)
                p_notional = float(p.get("notional", notional))
                frac = float(p.get("day_count_fraction", calc_dc_fraction(s_d, e_d, l2_dc)))
                p_spread = float(p.get("spread_bp", spread_bp))
                f_date_str = p.get("fixing_date")
                if f_date_str:
                    f_d = parse_date(f_date_str)
                else:
                    f_d = compute_fixing_date(s_d, l2_fday, l2_fcal)
                df_pay = self.curve.get_df(pay_d) / df_settle
                if is_fixed_fixed:
                    fwd_kofr_rate = c2_val
                    float_rate_total = c2_val
                    rate_src = "Fixed"
                else:
                    fix_pct = p.get("fixing_rate_pct")
                    if fix_pct is None and idx == 0:
                        fix_pct = first_fixing_pct
                    fwd_kofr_rate, rate_src = floating_rate_for_period(
                        self.curve, s_d, e_d,
                        self.curve.get_forward_compounded_rate, fix_pct)
                    float_rate_total = fwd_kofr_rate + (p_spread / 100.0)
                float_cf = p_notional * (float_rate_total / 100.0) * frac
                float_pv = float_cf * df_pay
                sum_float_pv += float_pv
                leg2_floating.append({
                    "period_no": idx + 1,
                    "start_date": s_d.strftime("%Y-%m-%d"),
                    "end_date": e_d.strftime("%Y-%m-%d"),
                    "pay_date": pay_d.strftime("%Y-%m-%d"),
                    "fixing_date": f_d.strftime("%Y-%m-%d") if f_d else "N/A",
                    "notional": p_notional,
                    "day_count_fraction": round(frac, 6),
                    "fwd_sofr_pct": round(fwd_kofr_rate, 4),
                    "fwd_kofr_pct": round(fwd_kofr_rate, 4),
                    "spread_bp": p_spread,
                    "rate_source": rate_src,
                    "all_in_rate_pct": round(float_rate_total, 4),
                    "cash_flow": round(float_cf, 2),
                    "discount_factor": round(df_pay, 6),
                    "present_value": round(float_pv, 2)
                })
            if not l1_custom:
                mat_d = parse_date(l2_custom[-1].get("end_date", eff_d))
        else:
            raw_sched_l2 = gen_sched(
                effective_date=eff_d,
                maturity_date=mat_d,
                frequency_months=l2_freq,
                business_day_conv=l2_conv,
                pay_cal=l2_cal,
                stub_rule=l2_stub,
                adjust_rule=l2_adj
            )
            for idx, (a_st, a_ed, pay_dt, calc_st, calc_ed, u_st, u_ed) in enumerate(raw_sched_l2):
                pay_dt = _apply_payment_lag(pay_dt, payment_lag_bd, l2_cal)
                frac = calc_dc_fraction(calc_st, calc_ed, l2_dc)
                f_d = compute_fixing_date(a_st, l2_fday, l2_fcal)
                df_pay = self.curve.get_df(pay_dt) / df_settle
                if is_fixed_fixed:
                    fwd_kofr_rate = c2_val
                    float_rate_total = c2_val
                    rate_src = "Fixed"
                else:
                    fwd_kofr_rate, rate_src = floating_rate_for_period(
                        self.curve, calc_st, calc_ed,
                        self.curve.get_forward_compounded_rate,
                        first_fixing_pct if idx == 0 else None)
                    float_rate_total = fwd_kofr_rate + (spread_bp / 100.0)
                float_cf = notional * (float_rate_total / 100.0) * frac
                float_pv = float_cf * df_pay
                sum_float_pv += float_pv
                leg2_floating.append({
                    "period_no": idx + 1,
                    "start_date": a_st.strftime("%Y-%m-%d"),
                    "end_date": a_ed.strftime("%Y-%m-%d"),
                    "pay_date": pay_dt.strftime("%Y-%m-%d"),
                    "fixing_date": f_d.strftime("%Y-%m-%d") if f_d else "N/A",
                    "notional": notional,
                    "day_count_fraction": round(frac, 6),
                    "fwd_sofr_pct": round(fwd_kofr_rate, 4),
                    "fwd_kofr_pct": round(fwd_kofr_rate, 4),
                    "spread_bp": spread_bp,
                    "rate_source": rate_src,
                    "all_in_rate_pct": round(float_rate_total, 4),
                    "cash_flow": round(float_cf, 2),
                    "discount_factor": round(df_pay, 6),
                    "present_value": round(float_pv, 2)
                })

        max_p = max(len(leg1_fixed), len(leg2_floating))
        for i in range(max_p):
            l1 = leg1_fixed[i] if i < len(leg1_fixed) else {}
            l2 = leg2_floating[i] if i < len(leg2_floating) else {}
            p_no = i + 1
            st_d = l1.get("start_date") or l2.get("start_date")
            ed_d = l1.get("end_date") or l2.get("end_date")
            pay_d = l1.get("pay_date") or l2.get("pay_date")
            f_d = l2.get("fixing_date") or "N/A"
            frac_val = l1.get("day_count_fraction") or l2.get("day_count_fraction") or 0.0
            p_notion = l1.get("notional") or l2.get("notional") or notional
            r1 = l1.get("fixed_rate_pct", 0.0)
            r2 = l2.get("fwd_kofr_pct", 0.0)
            cf1 = l1.get("cash_flow", 0.0)
            cf2 = l2.get("cash_flow", 0.0)
            df_val = l1.get("discount_factor") or l2.get("discount_factor") or 1.0
            pv1 = l1.get("present_value", 0.0)
            pv2 = l2.get("present_value", 0.0)
            net_cf = (cf2 - cf1) if position == "Pay Fixed" else (cf1 - cf2)
            net_pv = (pv2 - pv1) if position == "Pay Fixed" else (pv1 - pv2)
            comparison_table.append({
                "period_no": p_no,
                "start_date": st_d,
                "end_date": ed_d,
                "pay_date": pay_d,
                "fixing_date": f_d,
                "payment_lag_bd": payment_lag_bd,
                "notional": p_notion,
                "day_count_fraction": frac_val,
                "fixed_rate_pct": r1,
                "fwd_kofr_pct": r2,
                "rate_source": l2.get("rate_source", "Forward"),
                "fixed_cf": round(cf1, 2),
                "float_cf": round(cf2, 2),
                "net_cf": round(net_cf, 2),
                "discount_factor": df_val,
                "fixed_pv": round(pv1, 2),
                "float_pv": round(pv2, 2),
                "net_pv": round(net_pv, 2)
            })

        # Par Swap Rate (% p.a.) = sum(Float PV) / (Notional * Annuity) * 100
        if sum_weighted_annuity > 0:
            par_swap_rate_pct = (sum_float_pv / (notional * sum_weighted_annuity)) * 100.0
        else:
            par_swap_rate_pct = 0.0

        is_par_calc = (fixed_coupon_pct is None)
        if is_par_calc:
            fixed_coupon_pct = par_swap_rate_pct
            c_pct_val = par_swap_rate_pct
            sum_fixed_pv = sum_float_pv
            for p in leg1_fixed:
                frac = p["day_count_fraction"]
                df_pay = p["discount_factor"]
                fixed_cf = p["notional"] * (fixed_coupon_pct / 100.0) * frac
                fixed_pv = fixed_cf * df_pay
                p["fixed_rate_pct"] = round(fixed_coupon_pct, 4)
                p["cash_flow"] = round(fixed_cf, 2)
                p["present_value"] = round(fixed_pv, 2)
            for r in comparison_table:
                r["fixed_rate_pct"] = round(fixed_coupon_pct, 4)
                frac = r["day_count_fraction"]
                df_val = r["discount_factor"]
                cf1 = r["notional"] * (fixed_coupon_pct / 100.0) * frac
                pv1 = cf1 * df_val
                r["fixed_cf"] = round(cf1, 2)
                r["fixed_pv"] = round(pv1, 2)
                r["net_cf"] = round((r["float_cf"] - cf1) if position == "Pay Fixed" else (cf1 - r["float_cf"]), 2)
                r["net_pv"] = round((r["float_pv"] - pv1) if position == "Pay Fixed" else (pv1 - r["float_pv"]), 2)

        # Deal NPV (₩)
        if is_par_calc or abs(par_swap_rate_pct - (fixed_coupon_pct or 0.0)) < 1e-4:
            deal_npv = 0.0
            sum_fixed_pv = sum_float_pv
        else:
            deal_npv = (sum_float_pv - sum_fixed_pv) if position == "Pay Fixed" else (sum_fixed_pv - sum_float_pv)
        
        # DV01 / BPV (₩ per 1bp) = Notional * Annuity * 0.0001
        dv01 = notional * sum_weighted_annuity * 0.0001
        dv01_signed = dv01 if position == "Receive Fixed" else -dv01
        
        coupon_ref = fixed_coupon_pct if fixed_coupon_pct is not None else par_swap_rate_pct
        spread_vs_coupon_bp = (par_swap_rate_pct - coupon_ref) * 100.0

        # Key Rate Deltas (DV01 sensitivities to curve pillars)
        key_rate_deltas = []
        if calculate_greeks:
            key_rate_deltas = self._calculate_key_rate_deltas(
                notional=notional,
                position=position,
                coupon=coupon_ref,
                spread_bp=spread_bp,
                eff_d=eff_d,
                mat_d=mat_d,
                tenor_str=tenor_str,
                freq_m=frequency_months,
                lag_bd=payment_lag_bd,
                dc=day_count,
                bdc=business_day_conv,
                stub_rule=stub_rule,
                adjust_rule=adjust_rule,
                fix_cal=fix_cal,
                pay_cal=pay_cal,
                fix_day=fix_day,
                custom_sched=custom_schedule,
                leg1_custom_schedule=leg1_custom_schedule,
                leg2_custom_schedule=leg2_custom_schedule,
                base_npv=deal_npv
            )

        leg1_fixed = []
        leg2_floating = []
        for r in comparison_table:
            leg1_fixed.append({
                "period_no": r["period_no"],
                "start_date": r["start_date"],
                "end_date": r["end_date"],
                "pay_date": r["pay_date"],
                "fixing_date": r["fixing_date"],
                "notional": r["notional"],
                "day_count_fraction": r["day_count_fraction"],
                "fixed_rate_pct": r["fixed_rate_pct"],
                "cash_flow": r["fixed_cf"],
                "discount_factor": r["discount_factor"],
                "present_value": r["fixed_pv"]
            })
            leg2_floating.append({
                "period_no": r["period_no"],
                "start_date": r["start_date"],
                "end_date": r["end_date"],
                "pay_date": r["pay_date"],
                "fixing_date": r["fixing_date"],
                "notional": r["notional"],
                "day_count_fraction": r["day_count_fraction"],
                "fwd_sofr_pct": r["fwd_kofr_pct"],
                "fwd_kofr_pct": r["fwd_kofr_pct"],
                "rate_source": r.get("rate_source", "Forward"),
                "spread_bp": 0.0,
                "all_in_rate_pct": r["fwd_kofr_pct"],
                "cash_flow": r["float_cf"],
                "discount_factor": r["discount_factor"],
                "present_value": r["float_pv"]
            })

        return {
            "currency": "KRW",
            "generator": "\\KRW KOFR Q 3M",
            "effective_date": eff_d.strftime("%Y-%m-%d"),
            "maturity_date": mat_d.strftime("%Y-%m-%d"),
            "tenor": tenor_str,
            "notional": notional,
            "position": position,
            "fixed_coupon_pct": round(coupon_ref, 6),
            "pricing_results": {
                "par_swap_rate_pct": round(par_swap_rate_pct, 4),
                "spread_vs_coupon_bp": round(spread_vs_coupon_bp, 2),
                "deal_npv": round(deal_npv, 2),
                "fixed_leg_pv": round(sum_fixed_pv, 2),
                "float_leg_pv": round(sum_float_pv, 2),
                "dv01": round(dv01, 2),
                "dv01_signed": round(dv01_signed, 2),
                "annuity": round(sum_weighted_annuity, 6)
            },
            "schedules": {
                "leg1_fixed": leg1_fixed,
                "leg2_floating": leg2_floating,
                "dual_comparison": comparison_table
            },
            "key_rate_deltas": key_rate_deltas
        }

    def _calculate_key_rate_deltas(
        self, notional, position, coupon, spread_bp, eff_d, mat_d, tenor_str,
        freq_m, lag_bd, dc, bdc, stub_rule, adjust_rule, fix_cal, pay_cal, fix_day,
        custom_sched, leg1_custom_schedule=None, leg2_custom_schedule=None, base_npv=0.0
    ) -> List[Dict[str, Any]]:
        """Key Rate DV01 (원/bp): bump each quoted pillar by +1bp and reprice the trade."""
        from .kofr_curve_engine import bootstrap_kofr_curve

        deltas = []
        pillar_labels = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y"]
        base_quotes = [(p["tenor"], p["rate"]) for p in self.curve.pillars
                       if p.get("months", 0) > 0]

        for b_tenor in pillar_labels:
            bumped_quotes = []
            bump_applied = False
            for t_label, r_val in base_quotes:
                if t_label == b_tenor:
                    bumped_quotes.append((t_label, r_val + 0.01))
                    bump_applied = True
                else:
                    bumped_quotes.append((t_label, r_val))

            if not bump_applied:
                continue

            bumped_curve = bootstrap_kofr_curve(
                self.curve.pricing_date, self.curve.settle_date, bumped_quotes
            )
            bumped_res = KOFRSwapPricer(bumped_curve).price_swap(
                notional=notional,
                position=position,
                fixed_coupon_pct=coupon,
                spread_bp=spread_bp,
                effective_date=eff_d,
                maturity_date=mat_d,
                tenor_str=tenor_str,
                frequency_months=freq_m,
                payment_lag_bd=lag_bd,
                day_count=dc,
                business_day_conv=bdc,
                stub_rule=stub_rule,
                adjust_rule=adjust_rule,
                fix_cal=fix_cal,
                pay_cal=pay_cal,
                fix_day=fix_day,
                custom_schedule=custom_sched,
                leg1_custom_schedule=leg1_custom_schedule,
                leg2_custom_schedule=leg2_custom_schedule,
                calculate_greeks=False
            )

            delta_npv = bumped_res["pricing_results"]["deal_npv"] - base_npv
            deltas.append({
                "tenor": b_tenor,
                "pillar": b_tenor,
                "delta_dv01": round(delta_npv, 2),
                "dv01": round(delta_npv, 2),
                "bump_bp": 1.0
            })

        return deltas
