"""
CRS Date and Schedule Engine
- Calendar: Joint Seoul (KRB) & New York (NYB) Bank Holidays
- Spot Date Convention: T + 2 Business Days
- Frequency: 6M Semi-Annual (or 3M Quarterly)
- Day Count Convention: 30/360 (Standard CRS Fixed) / Act/360 (USD SOFR) / Act/365
- Business Day Convention: Modified Following (MODFOL)
"""

import datetime
from typing import List, Set, Dict, Any, Optional

from sofr_pricer.date_engine import DEFAULT_NYB_HOLIDAYS
from kofr_pricer.kofr_date_engine import SEOUL_HOLIDAYS_LIST

def get_joint_holidays() -> Set[datetime.date]:
    """Combine US Fed/SIFMA Holidays & Seoul Bank Holidays"""
    holidays = set()
    for s in DEFAULT_NYB_HOLIDAYS:
        try:
            holidays.add(datetime.datetime.strptime(s, "%Y-%m-%d").date())
        except Exception:
            pass
    for s in SEOUL_HOLIDAYS_LIST:
        try:
            holidays.add(datetime.datetime.strptime(s, "%Y-%m-%d").date())
        except Exception:
            pass
    return holidays

def is_joint_business_day(d: datetime.date, holidays: Optional[Set[datetime.date]] = None) -> bool:
    if holidays is None:
        holidays = get_joint_holidays()
    if d.weekday() >= 5: # Saturday or Sunday
        return False
    if d in holidays:
        return False
    return True

def add_joint_business_days(d: datetime.date, n: int, holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    if holidays is None:
        holidays = get_joint_holidays()
    cur = d
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    while remaining > 0:
        cur += datetime.timedelta(days=step)
        if is_joint_business_day(cur, holidays):
            remaining -= 1
    return cur

def apply_crs_convention(d: datetime.date, conv: str = "Modified Following", holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    if holidays is None:
        holidays = get_joint_holidays()
        
    c = conv.strip().lower()
    if is_joint_business_day(d, holidays):
        return d
        
    if "mod" in c:
        orig_month = d.month
        cur = d
        while not is_joint_business_day(cur, holidays):
            cur += datetime.timedelta(days=1)
        if cur.month != orig_month:
            cur = d
            while not is_joint_business_day(cur, holidays):
                cur -= datetime.timedelta(days=1)
        return cur
    elif "prec" in c:
        cur = d
        while not is_joint_business_day(cur, holidays):
            cur -= datetime.timedelta(days=1)
        return cur
    else: # Following
        cur = d
        while not is_joint_business_day(cur, holidays):
            cur += datetime.timedelta(days=1)
        return cur

def get_crs_spot_date(pricing_date: datetime.date, lag: int = 2, holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    """FX Spot Date Convention (T + 2 Joint Business Days)"""
    return add_joint_business_days(pricing_date, lag, holidays)

def add_months(d: datetime.date, months: int) -> datetime.date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31,
                      29 if year % 4 == 0 and not year % 100 == 0 or year % 400 == 0 else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return datetime.date(year, month, day)

def day_count_fraction(start_d: datetime.date, end_d: datetime.date, day_count: str = "30/360") -> float:
    """Calculate day count fraction for CRS legs"""
    dc = day_count.strip().lower()
    days = (end_d - start_d).days
    if "360" in dc and "30" not in dc: # Act/360
        return days / 360.0
    elif "365" in dc: # Act/365
        return days / 365.0
    else: # 30/360 (ISDA 30/360 Standard for CRS Fixed)
        d1 = min(start_d.day, 30)
        d2 = min(end_d.day, 30) if d1 == 30 else end_d.day
        days_30 = 360 * (end_d.year - start_d.year) + 30 * (end_d.month - start_d.month) + (d2 - d1)
        return days_30 / 360.0

def generate_crs_schedule(
    effective_date: datetime.date,
    maturity_date: datetime.date,
    frequency_months: int = 6, # 6M Semi-Annual Standard for CRS
    day_count: str = "30/360",
    business_day_conv: str = "Modified Following",
    payment_lag_bd: int = 0, # +2 BD Payment Lag for Murex KRW FIXED USD SOFR 3M / 6M
    holidays: Optional[Set[datetime.date]] = None
) -> List[Dict[str, Any]]:
    """Generate periodic payment dates for CRS"""
    if holidays is None:
        holidays = get_joint_holidays()

    total_months = (maturity_date.year - effective_date.year) * 12 + (maturity_date.month - effective_date.month)
    if total_months <= 0:
        total_months = max(1, round((maturity_date - effective_date).days / 30.4375))
        
    num_periods = max(1, total_months // frequency_months)
    
    unadjusted_dates = []
    for i in range(num_periods + 1):
        if i == num_periods:
            unadjusted_dates.append(maturity_date)
        else:
            unadjusted_dates.append(add_months(effective_date, i * frequency_months))
            
    adjusted_dates = [apply_crs_convention(d, business_day_conv, holidays) for d in unadjusted_dates]
    
    for i in range(1, len(adjusted_dates)):
        if adjusted_dates[i] <= adjusted_dates[i - 1]:
            adjusted_dates[i] = add_joint_business_days(adjusted_dates[i - 1], 1, holidays)

    schedule = []
    for i in range(len(adjusted_dates) - 1):
        start_d = adjusted_dates[i]
        end_d = adjusted_dates[i + 1]
        frac = day_count_fraction(start_d, end_d, day_count)
        
        # Payment Date with optional business day lag
        if payment_lag_bd > 0:
            pay_d = add_joint_business_days(end_d, payment_lag_bd, holidays)
        else:
            pay_d = end_d
        
        schedule.append({
            "period_no": i + 1,
            "start_date": start_d,
            "end_date": end_d,
            "pay_date": pay_d,
            "day_count_fraction": round(frac, 6),
            "num_days": (end_d - start_d).days
        })
        
    return schedule
