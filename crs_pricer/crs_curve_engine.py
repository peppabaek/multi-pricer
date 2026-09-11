"""
KRWFXSOFR (CRS) Curve Bootstrapping Engine
- Calibrates KRW FX SOFR Discount Curve from Prebon Yamane CRS Quotes (KRUSQxx=PREA) and USD/KRW Spot FX
- Discounting: EXP ACT/365 Zero Coupon Linear Interpolation matching Reference SwapPricer
"""

import math
import datetime
from typing import List, Tuple, Dict, Any, Optional

from .crs_date_engine import (
    get_joint_holidays,
    apply_crs_convention,
    add_months,
    add_joint_business_days,
    day_count_fraction
)

class KRWFXSOFRCurve:
    def __init__(self, pricing_date: datetime.date, settle_date: datetime.date, spot_fx: float = 1335.50):
        self.pricing_date = pricing_date
        self.settle_date = settle_date
        self.spot_fx = spot_fx
        self.df_settle: float = 1.0
        
        # Pillars & calibrated grid points
        self.pillars: List[Dict[str, Any]] = []
        self.mat_dates: List[datetime.date] = []
        self.zero_rates: List[float] = [] # Continuously Compounded Zero Rates (EXP ACT/365) in %
        self.dfs: List[float] = []

    def get_zero_rate(self, target_date: datetime.date) -> float:
        """Linear interpolation on Zero Rate (EXP ACT/365) matching Murex / Excel"""
        if not self.mat_dates:
            return 0.0
            
        if target_date <= self.mat_dates[0]:
            return self.zero_rates[0]
        if target_date >= self.mat_dates[-1]:
            return self.zero_rates[-1]
            
        for i in range(len(self.mat_dates) - 1):
            d0, d1 = self.mat_dates[i], self.mat_dates[i + 1]
            if d0 <= target_date <= d1:
                z0, z1 = self.zero_rates[i], self.zero_rates[i + 1]
                t_total = (d1 - d0).days
                if t_total == 0:
                    return z0
                t_target = (target_date - d0).days
                weight = t_target / float(t_total)
                return z0 + weight * (z1 - z0)
                
        return self.zero_rates[-1]

    def get_df(self, target_date: datetime.date) -> float:
        """Calculate Discount Factor using EXP ACT/365 Zero Rate"""
        if target_date <= self.pricing_date:
            return 1.0
        if target_date == self.settle_date:
            return self.df_settle
            
        zero_rate = self.get_zero_rate(target_date) # in %
        dt = (target_date - self.pricing_date).days
        return math.exp(-(zero_rate / 100.0) * (dt / 365.0))

def bootstrap_crs_curve(
    pricing_date: datetime.date,
    settle_date: datetime.date,
    crs_quotes: Optional[List[Tuple[str, float]]] = None,
    spot_fx: float = 1335.50
) -> KRWFXSOFRCurve:
    """
    Sequential Semi-Annual (6M) Grid Bootstrapping for KRWFXSOFR Curve
    - Standard Quotes: Prebon Yamane KRUSQxx=PREA (1Y, 18M, 2Y, 3Y, 4Y, 5Y, 6Y, 7Y, 8Y, 9Y, 10Y, 12Y, 15Y, 20Y)
    """
    holidays = get_joint_holidays()
    curve = KRWFXSOFRCurve(pricing_date, settle_date, spot_fx)
    quote_map: Dict[str, float] = {}
    
    # Default baseline Prebon CRS quotes (KRW Fixed Rate against USD SOFR Flat)
    default_crs_quotes = [
        ("1M", 2.8500),
        ("3M", 2.9500),
        ("6M", 3.1200),
        ("9M", 3.2000),
        ("1Y", 3.2550),
        ("18M", 3.3250),
        ("2Y", 3.3750),
        ("3Y", 3.4500),
        ("4Y", 3.5100),
        ("5Y", 3.5500),
        ("6Y", 3.5850),
        ("7Y", 3.6150),
        ("8Y", 3.6350),
        ("9Y", 3.6500),
        ("10Y", 3.6650),
        ("12Y", 3.6800),
        ("15Y", 3.6850),
        ("20Y", 3.6200)
    ]
    
    input_quotes = crs_quotes if crs_quotes else default_crs_quotes
    for t, r in input_quotes:
        t_clean = t.strip().upper()
        quote_map[t_clean] = float(r)
        if t_clean == "12M": quote_map["1Y"] = float(r)
        elif t_clean == "1Y": quote_map["12M"] = float(r)
        elif t_clean == "24M": quote_map["2Y"] = float(r)
        elif t_clean == "2Y": quote_map["24M"] = float(r)
        elif t_clean == "36M": quote_map["3Y"] = float(r)
        elif t_clean == "3Y": quote_map["36M"] = float(r)
        elif t_clean == "48M": quote_map["4Y"] = float(r)
        elif t_clean == "4Y": quote_map["48M"] = float(r)
        elif t_clean == "60M": quote_map["5Y"] = float(r)
        elif t_clean == "5Y": quote_map["60M"] = float(r)
        elif t_clean == "84M": quote_map["7Y"] = float(r)
        elif t_clean == "7Y": quote_map["84M"] = float(r)
        elif t_clean == "120M": quote_map["10Y"] = float(r)
        elif t_clean == "10Y": quote_map["120M"] = float(r)
        elif t_clean == "144M": quote_map["12Y"] = float(r)
        elif t_clean == "12Y": quote_map["144M"] = float(r)
        elif t_clean == "180M": quote_map["15Y"] = float(r)
        elif t_clean == "15Y": quote_map["180M"] = float(r)
        elif t_clean == "240M": quote_map["20Y"] = float(r)
        elif t_clean == "20Y": quote_map["240M"] = float(r)

    # Helper to convert tenor to months
    def tenor_to_months(t_str: str) -> int:
        t = t_str.strip().upper()
        if t == "ON" or t == "SPOT":
            return 0
        if "M" in t:
            return int(t.replace("M", ""))
        if "Y" in t:
            return int(t.replace("Y", "")) * 12
        return 0

    available_quoted_months = sorted(list(set([tenor_to_months(k) for k in quote_map.keys() if tenor_to_months(k) > 0])))
    known_months = [6, 12, 18, 24, 36, 48, 60, 72, 84, 96, 108, 120, 144, 180, 240]
    
    # 1. Settle Date DF & Base Spot Pillar
    short_rate = quote_map.get("1M", quote_map.get("1Y", 3.25) - 0.40)
    dt_settle = (settle_date - pricing_date).days
    df_settle = 1.0 / (1.0 + (short_rate / 100.0) * (dt_settle / 365.0))
    curve.df_settle = df_settle
    
    zero_settle = -365.0 / dt_settle * math.log(df_settle) * 100.0 if dt_settle > 0 else short_rate
    item_settle = {
        "tenor": "Spot",
        "mat_date": settle_date,
        "rate": short_rate,
        "par_rate": short_rate,
        "df": df_settle,
        "zero_rate": zero_settle,
        "months": 0
    }
    curve.pillars.append(item_settle)
    curve.mat_dates.append(settle_date)
    curve.zero_rates.append(zero_settle)
    curve.dfs.append(df_settle)

    # 2. Sequential 6M Semi-Annual Grid Bootstrapping (6M to 240M / 20Y)
    semi_history = []
    prev_mat = settle_date
    
    for m in range(6, 241, 6):
        mat_m = apply_crs_convention(add_months(settle_date, m), "Modified Following", holidays)
        frac_m = day_count_fraction(prev_mat, mat_m, "30/360")
        days_m_pricing = (mat_m - pricing_date).days
        
        t_key_m = f"{m}M"
        t_key_y = f"{m//12}Y" if m % 12 == 0 else ""
        
        # Determine Par CRS Rate for this month m
        if t_key_y and t_key_y in quote_map:
            s_m = quote_map[t_key_y]
        elif t_key_m in quote_map:
            s_m = quote_map[t_key_m]
        elif available_quoted_months and m < available_quoted_months[0]:
            first_m = available_quoted_months[0]
            first_k = f"{first_m//12}Y" if first_m % 12 == 0 and first_m >= 12 else f"{first_m}M"
            r_first = quote_map.get(first_k, 3.25)
            s_m = short_rate + (m / float(first_m)) * (r_first - short_rate)
        else:
            p_prev = max([k for k in available_quoted_months if k < m], default=available_quoted_months[0] if available_quoted_months else 12)
            p_next = min([k for k in available_quoted_months if k > m], default=available_quoted_months[-1] if available_quoted_months else 240)
            k_prev = f"{p_prev//12}Y" if p_prev % 12 == 0 and p_prev >= 12 else f"{p_prev}M"
            k_next = f"{p_next//12}Y" if p_next % 12 == 0 and p_next >= 12 else f"{p_next}M"
            r_prev = quote_map.get(k_prev, 3.3)
            r_next = quote_map.get(k_next, 3.6)
            weight_m = (m - p_prev) / float(p_next - p_prev) if p_next > p_prev else 0.0
            s_m = r_prev + weight_m * (r_next - r_prev)
            
        # Closed-form CRS Bootstrapping:
        # Sum of previous discounted coupons
        sum_prev_c = sum([(c_frac) * (df_j / df_settle) for (_, c_frac, df_j) in semi_history])
        
        # DF(T_k) = (1 - (S_k / 100) * sum_prev_c) / (1 + (S_k / 100) * frac_k) * df_settle
        numerator = 1.0 - (s_m / 100.0) * sum_prev_c
        denominator = 1.0 + (s_m / 100.0) * frac_m
        df_m = (numerator / denominator) * df_settle
        
        zero_m = -365.0 / days_m_pricing * math.log(df_m) * 100.0 if days_m_pricing > 0 and df_m > 0 else s_m
        
        semi_history.append((mat_m, frac_m, df_m))
        prev_mat = mat_m
        
        if m in known_months:
            t_label = f"{m//12}Y" if m % 12 == 0 and m >= 12 else f"{m}M"
            item_m = {
                "tenor": t_label,
                "mat_date": mat_m,
                "rate": s_m,
                "par_rate": s_m,
                "df": df_m,
                "zero_rate": zero_m,
                "months": m
            }
            curve.pillars.append(item_m)
            curve.mat_dates.append(mat_m)
            curve.zero_rates.append(zero_m)
            curve.dfs.append(df_m)

    return curve
