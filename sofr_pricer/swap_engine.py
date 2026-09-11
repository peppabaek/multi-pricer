"""
USD SOFR IRS Pricing Engine with Odd Tenor & Dual-Leg Schedule Support
- Odd Tenor Parser (e.g. 15M, 18M, 21M, 2.5Y, 3Y6M, 42M, 7Y, custom dates)
- Dual-Leg Schedule Generation: Leg 1 (Fixed Leg) & Leg 2 (Floating SOFR Leg)
- Par Swap Rate Calculation (NPV = 0 equilibrium fixed rate)
- Deal NPV, DV01 / PV01 (1bp Sensitivity), Key Rate Delta Bucketing
"""

import re
import datetime
from typing import Dict, List, Any, Optional, Tuple
from .date_engine import (
    parse_date, apply_convention, add_months, day_count_fraction, generate_schedule
)
from .curve_engine import SOFRCurve, bootstrap_sofr_curve

def parse_tenor_string(tenor_str: str, effective_date: datetime.date, business_day_conv: str = "Modified Following", holidays: Optional[set] = None) -> Tuple[datetime.date, str, int]:
    """
    Parse any standard or Odd Tenor string (e.g. '15M', '18M', '2.5Y', '3Y6M', '42M', '7Y')
    Returns: (maturity_date, normalized_tenor_label, total_months)
    """
    s = tenor_str.strip().upper()
    total_months = 0
    
    # Check for compound tenors like '3Y6M', '1Y3M', '2Y9M'
    match_ym = re.match(r"^(\d+)Y(\d+)M$", s)
    if match_ym:
        years = int(match_ym.group(1))
        months = int(match_ym.group(2))
        total_months = years * 12 + months
        label = f"{years}Y{months}M"
    # Check for decimal years like '2.5Y', '1.5Y'
    elif re.match(r"^(\d+\.?\d*)Y$", s):
        y_float = float(s[:-1])
        total_months = int(round(y_float * 12))
        label = f"{y_float:g}Y"
    # Check for pure months like '15M', '18M', '42M'
    elif re.match(r"^(\d+)M$", s):
        total_months = int(s[:-1])
        label = f"{total_months}M"
    # Check for pure weeks like '2W', '3W'
    elif re.match(r"^(\d+)W$", s):
        weeks = int(s[:-1])
        mat = apply_convention(effective_date + datetime.timedelta(days=weeks * 7), business_day_conv, holidays)
        return mat, f"{weeks}W", 0
    else:
        # Default fallback to 5Y
        total_months = 60
        label = "5Y"
        
    maturity_date = apply_convention(add_months(effective_date, total_months), business_day_conv, holidays)
    return maturity_date, label, total_months

class USDSOFRSwapPricer:
    def __init__(self, curve: SOFRCurve):
        self.curve = curve

    def price_swap(
        self,
        notional: float = 100_000_000.0,
        position: str = "Pay Fixed", # "Pay Fixed" or "Rec Fixed"
        fixed_coupon_pct: float = 3.725, # e.g. 3.725 %
        spread_bp: float = 0.0, # e.g. 0.0 bp
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        tenor_str: str = "5Y",
        frequency_months: int = 12, # Annual payment (standard for USD SOFR IRS)
        day_count: str = "Act/360",
        business_day_conv: str = "Modified Following",
        stub_rule: str = "Short in arrears",
        adjust_rule: str = "Adjust",
        fix_cal: str = "NYB",
        pay_cal: str = "NYB",
        fix_day: int = -2,
        holidays: Optional[set] = None,
        custom_schedule: Optional[List[Dict[str, Any]]] = None,
        leg1_custom_schedule: Optional[List[Dict[str, Any]]] = None,
        leg2_custom_schedule: Optional[List[Dict[str, Any]]] = None,
        calculate_greeks: bool = True,
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
        leg2_fix_day: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Full USD SOFR IRS Pricing with Dual-Leg (Fixed vs Float) Schedule
        Supports Independent Leg 1 vs Leg 2 Parameters, All 4 Stub Rules, and Custom Schedule
        """
        from server.calendar_manager import (
            generate_schedule as gen_sched,
            compute_fixing_date,
            day_count_fraction as calc_dc_fraction,
            apply_convention as apply_conv,
            add_months as add_m,
            resolve_custom_pay_date
        )
        
        # Resolve Leg 1 and Leg 2 parameters
        l1_freq = leg1_frequency_months or frequency_months or 12
        l1_dc = leg1_day_count or day_count or "Act/360"
        l1_stub = leg1_stub_rule or stub_rule or "Short in arrears"
        l1_conv = leg1_business_day_conv or business_day_conv or "Modified Following"
        l1_adj = leg1_adjust_rule or adjust_rule or "Adjust"
        l1_cal = leg1_pay_cal or pay_cal or "NYB"

        l2_freq = leg2_frequency_months or frequency_months or 12
        l2_dc = leg2_day_count or day_count or "Act/360"
        l2_stub = leg2_stub_rule or stub_rule or "Short in arrears"
        l2_conv = leg2_business_day_conv or business_day_conv or "Modified Following"
        l2_adj = leg2_adjust_rule or adjust_rule or "Adjust"
        l2_cal = leg2_pay_cal or pay_cal or "NYB"
        l2_fcal = leg2_fix_cal or fix_cal or "NYB"
        l2_fday = leg2_fix_day if leg2_fix_day is not None else fix_day

        if effective_date is None:
            effective_date = self.curve.settle_date
            
        if maturity_date is None and custom_schedule is None:
            maturity_date, tenor_label, total_months = parse_tenor_string(
                tenor_str, effective_date, l1_conv, holidays
            )
        else:
            tenor_label = tenor_str

        base_notional = notional if notional > 0 else 100_000_000.0
        is_pay_fixed = "pay" in position.lower()
        df_settle = getattr(self.curve, "df_settle", 1.0)
        if df_settle <= 0:
            df_settle = 1.0

        leg1_fixed_schedule = []
        leg2_float_schedule = []
        dual_waterfall = []
        sum_fixed_pv = 0.0
        sum_float_pv = 0.0
        sum_weighted_annuity = 0.0

        # 1. Build Periods Schedule (Custom or Auto for Leg 1 and Leg 2)
        l1_custom = leg1_custom_schedule if (leg1_custom_schedule and len(leg1_custom_schedule) > 0) else (custom_schedule if (custom_schedule and len(custom_schedule) > 0) else None)
        l2_custom = leg2_custom_schedule if (leg2_custom_schedule and len(leg2_custom_schedule) > 0) else (custom_schedule if (custom_schedule and len(custom_schedule) > 0) else None)

        if l1_custom:
            for idx, p in enumerate(l1_custom):
                st = parse_date(p.get("start_date", effective_date))
                ed = parse_date(p.get("end_date", add_m(st, l1_freq)))
                pay_dt = resolve_custom_pay_date(p, ed, l1_conv, l1_cal)
                p_notional = float(p.get("notional", notional))
                p_rate_val = p.get("fixed_rate_pct")
                p_rate = float(p_rate_val) if (p_rate_val is not None and float(p_rate_val) > 0.0) else fixed_coupon_pct
                frac = calc_dc_fraction(st, ed, l1_dc)
                df = self.curve.get_df(pay_dt) / df_settle
                fixed_cf = p_notional * (p_rate / 100.0) * frac
                fixed_pv = fixed_cf * df
                sum_fixed_pv += fixed_pv
                annuity_contrib = (p_notional / base_notional) * frac * df
                sum_weighted_annuity += annuity_contrib
                leg1_fixed_schedule.append({
                    "period_no": idx + 1,
                    "start_date": st.strftime("%Y-%m-%d"),
                    "end_date": ed.strftime("%Y-%m-%d"),
                    "pay_date": pay_dt.strftime("%Y-%m-%d"),
                    "fixing_date": p.get("fixing_date", "N/A"),
                    "notional": p_notional,
                    "day_count_fraction": round(frac, 6),
                    "fixed_rate_pct": round(p_rate, 4),
                    "cash_flow": round(fixed_cf, 2),
                    "discount_factor": round(df, 6),
                    "present_value": round(fixed_pv, 2)
                })
            maturity_date = parse_date(l1_custom[-1].get("end_date", maturity_date))
        else:
            raw_periods_l1 = gen_sched(
                effective_date=effective_date,
                maturity_date=maturity_date,
                frequency_months=l1_freq,
                business_day_conv=l1_conv,
                pay_cal=l1_cal,
                stub_rule=l1_stub,
                adjust_rule=l1_adj
            )
            for idx, (a_st, a_ed, pay_dt, calc_st, calc_ed, u_st, u_ed) in enumerate(raw_periods_l1):
                frac = calc_dc_fraction(calc_st, calc_ed, l1_dc)
                df = self.curve.get_df(pay_dt) / df_settle
                if fixed_coupon_pct is not None:
                    fixed_cf = notional * (fixed_coupon_pct / 100.0) * frac
                    fixed_pv = fixed_cf * df
                    sum_fixed_pv += fixed_pv
                else:
                    fixed_cf = 0.0
                    fixed_pv = 0.0
                annuity_contrib = frac * df
                sum_weighted_annuity += annuity_contrib
                leg1_fixed_schedule.append({
                    "period_no": idx + 1,
                    "start_date": a_st.strftime("%Y-%m-%d"),
                    "end_date": a_ed.strftime("%Y-%m-%d"),
                    "pay_date": pay_dt.strftime("%Y-%m-%d"),
                    "fixing_date": "N/A",
                    "notional": notional,
                    "day_count_fraction": round(frac, 6),
                    "fixed_rate_pct": round(fixed_coupon_pct, 6) if fixed_coupon_pct is not None else 0.0,
                    "cash_flow": round(fixed_cf, 6),
                    "discount_factor": round(df, 6),
                    "present_value": round(fixed_pv, 6)
                })

        if l2_custom:
            for idx, p in enumerate(l2_custom):
                st = parse_date(p.get("start_date", effective_date))
                ed = parse_date(p.get("end_date", add_m(st, l2_freq)))
                pay_dt = resolve_custom_pay_date(p, ed, l2_conv, l2_cal)
                p_notional = float(p.get("notional", notional))
                p_spread = float(p.get("spread_bp", spread_bp))
                frac = calc_dc_fraction(st, ed, l2_dc)
                f_date_str = p.get("fixing_date")
                if f_date_str:
                    f_date = parse_date(f_date_str)
                else:
                    f_date = compute_fixing_date(st, l2_fday, l2_fcal)
                fwd_sofr = self.curve.get_forward_rate(st, ed, l2_dc)
                df = self.curve.get_df(pay_dt) / df_settle
                all_in_rate = fwd_sofr + (p_spread / 10000.0)
                float_cf = p_notional * all_in_rate * frac
                float_pv = float_cf * df
                sum_float_pv += float_pv
                leg2_float_schedule.append({
                    "period_no": idx + 1,
                    "start_date": st.strftime("%Y-%m-%d"),
                    "end_date": ed.strftime("%Y-%m-%d"),
                    "pay_date": pay_dt.strftime("%Y-%m-%d"),
                    "fixing_date": f_date.strftime("%Y-%m-%d") if f_date else "N/A",
                    "notional": p_notional,
                    "day_count_fraction": round(frac, 6),
                    "fwd_sofr_pct": round(fwd_sofr * 100.0, 6),
                    "spread_bp": round(p_spread, 4),
                    "all_in_rate_pct": round(all_in_rate * 100.0, 6),
                    "cash_flow": round(float_cf, 6),
                    "discount_factor": round(df, 6),
                    "present_value": round(float_pv, 6)
                })
            if not l1_custom:
                maturity_date = parse_date(l2_custom[-1].get("end_date", maturity_date))
        else:
            raw_periods_l2 = gen_sched(
                effective_date=effective_date,
                maturity_date=maturity_date,
                frequency_months=l2_freq,
                business_day_conv=l2_conv,
                pay_cal=l2_cal,
                stub_rule=l2_stub,
                adjust_rule=l2_adj
            )
            for idx, (a_st, a_ed, pay_dt, calc_st, calc_ed, u_st, u_ed) in enumerate(raw_periods_l2):
                frac = calc_dc_fraction(calc_st, calc_ed, l2_dc)
                f_date = compute_fixing_date(a_st, l2_fday, l2_fcal)
                fwd_sofr = self.curve.get_forward_rate(calc_st, calc_ed, l2_dc)
                df = self.curve.get_df(pay_dt) / df_settle
                all_in_rate = fwd_sofr + (spread_bp / 10000.0)
                float_cf = notional * all_in_rate * frac
                float_pv = float_cf * df
                sum_float_pv += float_pv
                leg2_float_schedule.append({
                    "period_no": idx + 1,
                    "start_date": a_st.strftime("%Y-%m-%d"),
                    "end_date": a_ed.strftime("%Y-%m-%d"),
                    "pay_date": pay_dt.strftime("%Y-%m-%d"),
                    "fixing_date": f_date.strftime("%Y-%m-%d") if f_date else "N/A",
                    "notional": notional,
                    "day_count_fraction": round(frac, 6),
                    "fwd_sofr_pct": round(fwd_sofr * 100.0, 6),
                    "spread_bp": round(spread_bp, 4),
                    "all_in_rate_pct": round(all_in_rate * 100.0, 6),
                    "cash_flow": round(float_cf, 6),
                    "discount_factor": round(df, 6),
                    "present_value": round(float_pv, 6)
                })

        # 2. Par Swap Rate (Equilibrium Fixed Rate)
        if sum_weighted_annuity > 0:
            par_swap_rate = (sum_float_pv / (base_notional * sum_weighted_annuity)) * 100.0
        else:
            par_swap_rate = 0.0

        # If fixed_coupon_pct is None, auto-set to par swap rate so Leg1 & Leg2 NPV sum to 0
        is_par_calc = (fixed_coupon_pct is None)
        if fixed_coupon_pct is None:
            fixed_coupon_pct = par_swap_rate
            sum_fixed_pv = sum_float_pv
            for p in leg1_fixed_schedule:
                frac = p["day_count_fraction"]
                df = p["discount_factor"]
                cf = p["notional"] * (fixed_coupon_pct / 100.0) * frac
                pv = cf * df
                p["fixed_rate_pct"] = round(fixed_coupon_pct, 6)
                p["cash_flow"] = round(cf, 6)
                p["present_value"] = round(pv, 6)

        # Combined Dual Waterfall
        max_p = max(len(leg1_fixed_schedule), len(leg2_float_schedule))
        for i in range(max_p):
            l1 = leg1_fixed_schedule[i] if i < len(leg1_fixed_schedule) else {}
            l2 = leg2_float_schedule[i] if i < len(leg2_float_schedule) else {}
            p_no = i + 1
            st_d = l1.get("start_date") or l2.get("start_date")
            ed_d = l1.get("end_date") or l2.get("end_date")
            pay_d = l1.get("pay_date") or l2.get("pay_date")
            f_d = l2.get("fixing_date") or "N/A"
            frac_val = l1.get("day_count_fraction") or l2.get("day_count_fraction") or 0.0
            p_notion = l1.get("notional") or l2.get("notional") or notional
            r1 = l1.get("fixed_rate_pct", 0.0)
            r2 = l2.get("fwd_sofr_pct", 0.0)
            cf1 = l1.get("cash_flow", 0.0)
            cf2 = l2.get("cash_flow", 0.0)
            df_val = l1.get("discount_factor") or l2.get("discount_factor") or 1.0
            pv1 = l1.get("present_value", 0.0)
            pv2 = l2.get("present_value", 0.0)
            net_cf = (cf2 - cf1) if is_pay_fixed else (cf1 - cf2)
            net_pv = (pv2 - pv1) if is_pay_fixed else (pv1 - pv2)
            dual_waterfall.append({
                "period_no": p_no,
                "start_date": st_d,
                "end_date": ed_d,
                "pay_date": pay_d,
                "fixing_date": f_d,
                "notional": p_notion,
                "day_count_fraction": frac_val,
                "fixed_rate_pct": r1,
                "fwd_sofr_pct": r2,
                "fixed_cf": round(cf1, 6),
                "float_cf": round(cf2, 6),
                "net_cf": round(net_cf, 6),
                "discount_factor": round(df_val, 6),
                "fixed_pv": round(pv1, 6),
                "float_pv": round(pv2, 6),
                "net_pv": round(net_pv, 6)
            })

        # 3. Deal NPV
        if is_par_calc or abs(par_swap_rate - fixed_coupon_pct) < 1e-7:
            net_npv = 0.0
        else:
            net_npv = (sum_float_pv - sum_fixed_pv) if is_pay_fixed else (sum_fixed_pv - sum_float_pv)
            
        # 4. DV01
        dv01 = base_notional * 0.0001 * sum_weighted_annuity
        dv01_signed = dv01 if is_pay_fixed else -dv01

        # 5. Key Rate Delta Bucketing
        delta_bucketing = []
        hedge_delta_bucketing = []
        if calculate_greeks:
            bucket_tenors = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y"]
            delta_bucketing = self._calculate_delta_bucketing(
                notional=notional,
                position=position,
                fixed_coupon_pct=fixed_coupon_pct,
                spread_bp=spread_bp,
                effective_date=effective_date,
                maturity_date=maturity_date,
                tenor_str=tenor_str,
                frequency_months=frequency_months,
                day_count=day_count,
                business_day_conv=business_day_conv,
                stub_rule=stub_rule,
                adjust_rule=adjust_rule,
                fix_cal=fix_cal,
                pay_cal=pay_cal,
                fix_day=fix_day,
                holidays=holidays,
                custom_schedule=custom_schedule,
                leg1_custom_schedule=l1_custom,
                leg2_custom_schedule=l2_custom,
                bucket_tenors=bucket_tenors,
                base_npv=net_npv,
                force_hedge_mode=False
            )
            is_advanced = hasattr(self.curve, "ql_curve") or getattr(self.curve, "curve_type", "") == "Advanced"
            if is_advanced:
                hedge_delta_bucketing = self._calculate_delta_bucketing(
                    notional=notional,
                    position=position,
                    fixed_coupon_pct=fixed_coupon_pct,
                    spread_bp=spread_bp,
                    effective_date=effective_date,
                    maturity_date=maturity_date,
                    tenor_str=tenor_str,
                    frequency_months=frequency_months,
                    day_count=day_count,
                    business_day_conv=business_day_conv,
                    stub_rule=stub_rule,
                    adjust_rule=adjust_rule,
                    fix_cal=fix_cal,
                    pay_cal=pay_cal,
                    fix_day=fix_day,
                    holidays=holidays,
                    custom_schedule=custom_schedule,
                    leg1_custom_schedule=l1_custom,
                    leg2_custom_schedule=l2_custom,
                    bucket_tenors=bucket_tenors,
                    base_npv=net_npv,
                    force_hedge_mode=True
                )

        return {
            "trade_info": {
                "notional": notional,
                "position": position,
                "fixed_coupon_pct": fixed_coupon_pct,
                "spread_bp": spread_bp,
                "effective_date": effective_date.strftime("%Y-%m-%d"),
                "maturity_date": maturity_date.strftime("%Y-%m-%d"),
                "tenor": tenor_label,
                "frequency_months": frequency_months,
                "day_count": day_count,
                "calendar": "NYB (New York)",
                "business_day_conv": business_day_conv
            },
            "pricing_results": {
                "par_swap_rate_pct": round(par_swap_rate, 6),
                "spread_vs_coupon_bp": round((par_swap_rate - fixed_coupon_pct) * 100.0, 4),
                "deal_npv": round(net_npv, 6),
                "fixed_leg_pv": round(sum_fixed_pv, 6),
                "float_leg_pv": round(sum_float_pv, 6),
                "dv01": round(dv01, 2),
                "dv01_signed": round(dv01_signed, 2),
                "annuity": round(sum_weighted_annuity, 6)
            },
            "delta_bucketing": delta_bucketing,
            "hedge_delta_bucketing": hedge_delta_bucketing,
            "schedules": {
                "leg1_fixed": leg1_fixed_schedule,
                "leg2_floating": leg2_float_schedule,
                "dual_comparison": dual_waterfall
            }
        }

    def _calculate_delta_bucketing(
        self,
        notional: float,
        position: str,
        fixed_coupon_pct: Optional[float],
        spread_bp: float,
        effective_date: datetime.date,
        maturity_date: datetime.date,
        tenor_str: str,
        frequency_months: int,
        day_count: str,
        business_day_conv: str,
        stub_rule: str,
        adjust_rule: str,
        fix_cal: str,
        pay_cal: str,
        fix_day: int,
        holidays: Optional[set],
        custom_schedule: Optional[List[Dict[str, Any]]],
        leg1_custom_schedule: Optional[List[Dict[str, Any]]] = None,
        leg2_custom_schedule: Optional[List[Dict[str, Any]]] = None,
        bucket_tenors: List[str] = None,
        base_npv: float = 0.0,
        force_hedge_mode: bool = False
    ) -> List[Dict[str, Any]]:
        """Calculate Key Rate Delta by bumping each pillar by +1bp and re-pricing"""
        bucketing = []
        is_hedge_curve = force_hedge_mode or getattr(self.curve, "curve_type", "") in ("HedgeCurve", "Hedge", "Composite") or hasattr(self.curve, "delta_zh_func")
        is_advanced = hasattr(self.curve, "ql_curve") or getattr(self.curve, "curve_type", "") == "Advanced"
        base_quotes = [("ON" if p["tenor"] in ("O/N", "ON") else p["tenor"], p["rate"]) for p in getattr(self.curve, "pillars", [])]
        
        for b_tenor in (bucket_tenors or []):
            if is_hedge_curve:
                from .curve_engine import CompositeSOFRCurve, create_hedge_composite_curve
                base_c = self.curve.base_curve if isinstance(self.curve, CompositeSOFRCurve) else self.curve
                bumped_curve = create_hedge_composite_curve(
                    base_pricing_curve=base_c,
                    bumped_tenor=b_tenor,
                    bump_bp=0.0001
                )
            else:
                bumped_quotes = []
                bump_applied = False
                for t, r in base_quotes:
                    if t == b_tenor:
                        bumped_quotes.append((t, r + 0.01))
                        bump_applied = True
                    else:
                        bumped_quotes.append((t, r))
                        
                if not bump_applied:
                    continue

                if is_advanced:
                    from .curve_engine import bootstrap_advanced_sofr_curve
                    bumped_curve = bootstrap_advanced_sofr_curve(
                        pricing_date=self.curve.pricing_date,
                        settle_date=self.curve.settle_date,
                        quotes=bumped_quotes,
                        holidays=holidays
                    )
                else:
                    bumped_curve = bootstrap_sofr_curve(
                        pricing_date=self.curve.pricing_date,
                        settle_date=self.curve.settle_date,
                        quotes=bumped_quotes,
                        holidays=holidays
                    )
            
            bumped_pricer = USDSOFRSwapPricer(bumped_curve)
            res = bumped_pricer.price_swap(
                notional=notional,
                position=position,
                fixed_coupon_pct=fixed_coupon_pct,
                spread_bp=spread_bp,
                effective_date=effective_date,
                maturity_date=maturity_date,
                tenor_str=tenor_str,
                frequency_months=frequency_months,
                day_count=day_count,
                business_day_conv=business_day_conv,
                stub_rule=stub_rule,
                adjust_rule=adjust_rule,
                fix_cal=fix_cal,
                pay_cal=pay_cal,
                fix_day=fix_day,
                holidays=holidays,
                custom_schedule=custom_schedule,
                leg1_custom_schedule=leg1_custom_schedule,
                leg2_custom_schedule=leg2_custom_schedule,
                calculate_greeks=False
            )
            
            delta_npv = res["pricing_results"]["deal_npv"] - base_npv
            bucketing.append({
                "tenor": b_tenor,
                "pillar": b_tenor,
                "delta_dv01": round(delta_npv, 2),
                "dv01": round(delta_npv, 2)
            })
            
        return bucketing
