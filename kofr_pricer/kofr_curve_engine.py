"""
KOFR OIS Curve Bootstrapping & Zero Rate Interpolation Engine
- Value to calibrate: Zero Coupon (EXP ACT/365)
- Interpolation: Linear on Zero Rate
- Frequency: 3M Quarterly closed-form bootstrapping up to 30Y (120 Quarters)
"""

import math
import datetime
from typing import List, Tuple, Dict, Any, Optional

from .kofr_date_engine import (
    get_seoul_holidays,
    apply_kofr_convention,
    add_months,
    add_business_days,
    day_count_fraction
)

class KOFRCurve:
    def __init__(self, pricing_date: datetime.date, settle_date: datetime.date):
        self.pricing_date = pricing_date
        self.settle_date = settle_date
        self.df_settle: float = 1.0
        
        # Pillars & calibrated grid points
        self.pillars: List[Dict[str, Any]] = []
        self.mat_dates: List[datetime.date] = []
        self.zero_rates: List[float] = [] # Continuously Compounded Zero Rates (EXP ACT/365) in %
        self.dfs: List[float] = []

    def get_zero_rate(self, target_date: datetime.date) -> float:
        """Linear interpolation on Zero Rate (EXP ACT/365) matching Murex"""
        if not self.mat_dates:
            return 0.0
            
        if target_date <= self.mat_dates[0]:
            return self.zero_rates[0]
        if target_date >= self.mat_dates[-1]:
            return self.zero_rates[-1]
            
        # Binary search / Linear interpolation
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
        # DF = exp(-ZeroRate * dt / 365)
        return math.exp(-(zero_rate / 100.0) * (dt / 365.0))

    def get_forward_compounded_rate(self, start_date: datetime.date, end_date: datetime.date) -> float:
        """
        Calculate Forward Compounded KOFR rate (% p.a., Act/365)
        R_KOFR = (DF(start) / DF(end) - 1) * (365 / dt) * 100
        """
        df_start = self.get_df(start_date)
        df_end = self.get_df(end_date)
        dt = (end_date - start_date).days
        if dt <= 0 or df_end <= 0:
            return 0.0
        return ((df_start / df_end) - 1.0) * (365.0 / dt) * 100.0

def bootstrap_kofr_curve(
    pricing_date: datetime.date,
    settle_date: datetime.date,
    quotes: Optional[List[Tuple[str, float]]] = None
) -> KOFRCurve:
    """
    Closed-Form Sequential 3M Grid Bootstrapping for KOFR OIS Curve
    - Standard Quotes: ON KOFR, 3M OIS, 6M, 9M, 1Y, 18M, 2Y, 3Y, 4Y, 5Y, 6Y, 7Y, 8Y, 9Y, 10Y, 12Y, 15Y, 20Y, 25Y, 30Y
    """
    holidays = get_seoul_holidays()
    curve = KOFRCurve(pricing_date, settle_date)
    quote_map: Dict[str, float] = {}
    
    # Default baseline quotes for KOFR OIS (Tradition Seoul / KMBC Market Standard)
    default_quotes = [
        ("ON", 2.8042),
        ("3M", 3.0000),
        ("6M", 3.1650),
        ("9M", 3.3025),
        ("1Y", 3.3775), # Murex Benchmark 1Y KOFR = 3.3775%
        ("18M", 3.5500),
        ("2Y", 3.5275),
        ("3Y", 3.6225),
        ("4Y", 3.6875),
        ("5Y", 3.7350),
        ("6Y", 3.7650),
        ("7Y", 3.7925),
        ("8Y", 3.8000),
        ("9Y", 3.8025),
        ("10Y", 3.8050),
        ("12Y", 3.8050),
        ("15Y", 3.8000),
        ("20Y", 3.6875),
        ("25Y", 3.6000),
        ("30Y", 3.5000)
    ]
    
    input_quotes = quotes if quotes else default_quotes
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
        elif t_clean == "360M": quote_map["30Y"] = float(r)
        elif t_clean == "30Y": quote_map["360M"] = float(r)

    # 1. Settle Date DF & O/N Pillar
    on_rate = quote_map.get("ON", 2.8042)
    dt_settle = (settle_date - pricing_date).days
    df_settle = 1.0 / (1.0 + (on_rate / 100.0) * (dt_settle / 365.0))
    curve.df_settle = df_settle
    
    zero_on = -365.0 / dt_settle * math.log(df_settle) * 100.0 if dt_settle > 0 else on_rate
    item_on = {
        "tenor": "ON",
        "mat_date": settle_date,
        "rate": on_rate,
        "df": df_settle,
        "zero_rate": zero_on,
        "months": 0
    }
    curve.pillars.append(item_on)
    curve.mat_dates.append(settle_date)
    curve.zero_rates.append(zero_on)
    curve.dfs.append(df_settle)

    # 2. 3M KOFR OIS Pillar
    ois_3m_rate = quote_map.get("3M", 3.0000)
    mat_3m = apply_kofr_convention(add_months(settle_date, 3), "Modified Following", holidays)
    dt_3m = (mat_3m - settle_date).days
    days_3m_pricing = (mat_3m - pricing_date).days
    
    df_3m = df_settle / (1.0 + (ois_3m_rate / 100.0) * (dt_3m / 365.0))
    zero_3m = -365.0 / days_3m_pricing * math.log(df_3m) * 100.0 if days_3m_pricing > 0 else ois_3m_rate
    
    item_3m = {
        "tenor": "3M",
        "mat_date": mat_3m,
        "rate": ois_3m_rate,
        "df": df_3m,
        "zero_rate": zero_3m,
        "months": 3
    }
    curve.pillars.append(item_3m)
    curve.mat_dates.append(mat_3m)
    curve.zero_rates.append(zero_3m)
    curve.dfs.append(df_3m)

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
    known_months = [3, 6, 9, 12, 18, 24, 36, 48, 60, 72, 84, 96, 108, 120, 144, 180, 240, 300, 360]
    
    quarterly_history = [(mat_3m, dt_3m, df_3m)]
    prev_mat = mat_3m
    
    for m in range(6, 361, 3):
        mat_m = apply_kofr_convention(add_months(settle_date, m), "Modified Following", holidays)
        dt_m = (mat_m - prev_mat).days
        days_m_pricing = (mat_m - pricing_date).days
        
        t_key_m = f"{m}M"
        t_key_y = f"{m//12}Y" if m % 12 == 0 else ""
        
        # Determine Par Swap Rate for this month m
        if t_key_y and t_key_y in quote_map:
            s_m = quote_map[t_key_y]
        elif t_key_m in quote_map:
            s_m = quote_map[t_key_m]
        else:
            # Interpolate dynamically between nearest available quoted months
            p_prev = max([k for k in available_quoted_months if k < m], default=available_quoted_months[0])
            p_next = min([k for k in available_quoted_months if k > m], default=available_quoted_months[-1])
            
            k_prev = f"{p_prev//12}Y" if p_prev % 12 == 0 and p_prev >= 12 else f"{p_prev}M"
            k_next = f"{p_next//12}Y" if p_next % 12 == 0 and p_next >= 12 else f"{p_next}M"
            
            r_prev = quote_map.get(k_prev, quote_map.get(f"{p_prev}M", 3.5))
            r_next = quote_map.get(k_next, quote_map.get(f"{p_next}M", 3.8))
            
            frac_m = (m - p_prev) / float(p_next - p_prev) if p_next > p_prev else 0.0
            s_m = r_prev + frac_m * (r_next - r_prev)
            
        # Closed-form sequential bootstrapping formula for OIS:
        # Sum of previous discounted annuities
        sum_prev_pv = sum([(dt_j / 365.0) * (df_j / df_settle) for (_, dt_j, df_j) in quarterly_history])
        
        # DF(T_k) = (1 - (S_k / 100) * sum_prev_pv) / (1 + (S_k / 100) * (dt_k / 365)) * df_settle
        numerator = 1.0 - (s_m / 100.0) * sum_prev_pv
        denominator = 1.0 + (s_m / 100.0) * (dt_m / 365.0)
        df_m = (numerator / denominator) * df_settle
        
        # Zero rate: -365 / days * ln(DF) * 100
        zero_m = -365.0 / days_m_pricing * math.log(df_m) * 100.0 if days_m_pricing > 0 and df_m > 0 else s_m
        
        quarterly_history.append((mat_m, dt_m, df_m))
        prev_mat = mat_m
        
        # Record pillar
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
