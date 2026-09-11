r"""
KOFR Date and Schedule Engine
- Calendar: Seoul Bank Holidays (KRB)
- Business Day Convention: Modified Following (MODFOL)
- Day Count Convention: Act/365
- Payment Schedule Deduction Formula: +2 BUSINESS DAYS (Murex '\KRW KOFR Q 3M' Generator)
- Spot Lag: T + 1 (or T + 2)
"""

import datetime
from typing import List, Set, Dict, Any, Optional

# Seoul Banking Holidays (2024 ~ 2036)
SEOUL_HOLIDAYS_LIST = [
    # 2024
    "2024-01-01", "2024-02-09", "2024-02-12", "2024-03-01", "2024-04-10",
    "2024-05-06", "2024-05-15", "2024-06-06", "2024-08-15", "2024-09-16",
    "2024-09-17", "2024-09-18", "2024-10-01", "2024-10-03", "2024-10-09",
    "2024-12-25",
    # 2025
    "2025-01-01", "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30",
    "2025-03-03", "2025-05-05", "2025-05-06", "2025-06-06", "2025-08-15",
    "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08", "2025-10-09",
    "2025-12-25",
    # 2026
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02",
    "2026-05-05", "2026-05-25", "2026-06-05", "2026-08-17", "2026-09-24",
    "2026-09-25", "2026-10-05", "2026-10-09", "2026-12-25",
    # 2027
    "2027-01-01", "2027-02-05", "2027-02-08", "2027-03-01", "2027-05-05",
    "2027-05-13", "2027-06-07", "2027-08-16", "2027-09-14", "2027-09-15",
    "2027-09-16", "2027-10-04", "2027-10-11", "2027-12-25",
    # 2028 ~ 2036 standard fixed
    "2028-01-01", "2028-03-01", "2028-05-05", "2028-06-06", "2028-08-15", "2028-10-03", "2028-10-09", "2028-12-25",
    "2029-01-01", "2029-03-01", "2029-05-05", "2029-06-06", "2029-08-15", "2029-10-03", "2029-10-09", "2029-12-25",
    "2030-01-01", "2030-03-01", "2030-05-05", "2030-06-06", "2030-08-15", "2030-10-03", "2030-10-09", "2030-12-25",
    "2031-01-01", "2031-03-01", "2031-05-05", "2031-06-06", "2031-08-15", "2031-10-03", "2031-10-09", "2031-12-25",
    "2032-01-01", "2032-03-01", "2032-05-05", "2032-06-06", "2032-08-15", "2032-10-03", "2032-10-09", "2032-12-25",
    "2033-01-01", "2033-03-01", "2033-05-05", "2033-06-06", "2033-08-15", "2033-10-03", "2033-10-09", "2033-12-25",
    "2034-01-01", "2034-03-01", "2034-05-05", "2034-06-06", "2034-08-15", "2034-10-03", "2034-10-09", "2034-12-25",
    "2035-01-01", "2035-03-01", "2035-05-05", "2035-06-06", "2035-08-15", "2035-10-03", "2035-10-09", "2035-12-25",
    "2036-01-01", "2036-03-01", "2036-05-05", "2036-06-06", "2036-08-15", "2036-10-03", "2036-10-09", "2036-12-25"
]

def get_seoul_holidays() -> Set[datetime.date]:
    holidays = set()
    for s in SEOUL_HOLIDAYS_LIST:
        try:
            holidays.add(datetime.datetime.strptime(s, "%Y-%m-%d").date())
        except Exception:
            pass
    return holidays

def is_seoul_business_day(d: datetime.date, holidays: Optional[Set[datetime.date]] = None) -> bool:
    if holidays is None:
        holidays = get_seoul_holidays()
    if d.weekday() >= 5: # Saturday or Sunday
        return False
    if d in holidays:
        return False
    return True

def add_business_days(d: datetime.date, n: int, holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    """Add N business days (Seoul calendar)"""
    if holidays is None:
        holidays = get_seoul_holidays()
    cur = d
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    while remaining > 0:
        cur += datetime.timedelta(days=step)
        if is_seoul_business_day(cur, holidays):
            remaining -= 1
    return cur

def apply_kofr_convention(d: datetime.date, conv: str = "Modified Following", holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    """Adjust date using business day convention (Modified Following / Following / Preceding)"""
    if holidays is None:
        holidays = get_seoul_holidays()
        
    c = conv.strip().lower()
    if is_seoul_business_day(d, holidays):
        return d
        
    if "mod" in c:
        # Modified Following: roll forward, if month changes roll backward
        orig_month = d.month
        cur = d
        while not is_seoul_business_day(cur, holidays):
            cur += datetime.timedelta(days=1)
        if cur.month != orig_month:
            cur = d
            while not is_seoul_business_day(cur, holidays):
                cur -= datetime.timedelta(days=1)
        return cur
    elif "prec" in c:
        cur = d
        while not is_seoul_business_day(cur, holidays):
            cur -= datetime.timedelta(days=1)
        return cur
    else: # Following
        cur = d
        while not is_seoul_business_day(cur, holidays):
            cur += datetime.timedelta(days=1)
        return cur

def get_spot_date(pricing_date: datetime.date, lag: int = 1, holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    """Calculate Spot Settlement Date (Seoul Spot = T + 1)"""
    return add_business_days(pricing_date, lag, holidays)

def add_months(d: datetime.date, months: int) -> datetime.date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31,
                      29 if year % 4 == 0 and not year % 100 == 0 or year % 400 == 0 else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return datetime.date(year, month, day)

def day_count_fraction(start_d: datetime.date, end_d: datetime.date, day_count: str = "Act/365") -> float:
    """Calculate day count fraction. KRW KOFR IRS standard is LIN ACT/365."""
    dc = day_count.strip().lower()
    days = (end_d - start_d).days
    if "360" in dc:
        return days / 360.0
    elif "30" in dc:
        d1 = min(start_d.day, 30)
        d2 = min(end_d.day, 30) if d1 == 30 else end_d.day
        days_30 = 360 * (end_d.year - start_d.year) + 30 * (end_d.month - start_d.month) + (d2 - d1)
        return days_30 / 360.0
    else: # Act/365 (Default for KRW)
        return days / 365.0

def generate_kofr_schedule(
    effective_date: datetime.date,
    maturity_date: datetime.date,
    frequency_months: int = 3, # Murex 3M MODFOL
    payment_lag_bd: int = 2,   # Murex Deduction formula: +2 BUSINESS DAY
    day_count: str = "Act/365",
    business_day_conv: str = "Modified Following",
    stub_rule: str = "Short Back",
    holidays: Optional[Set[datetime.date]] = None
) -> List[Dict[str, Any]]:
    """
    Generate Cashflow Schedule matching Murex '\\KRW KOFR Q 3M' Generator:
    - Calculation Schedule: 3M MODFOL
    - Payment Schedule: +2 Business Days after accrual end date (Deduced from Calculation start/end schedule)
    """
    if holidays is None:
        holidays = get_seoul_holidays()

    # Total approximate months
    total_months = (maturity_date.year - effective_date.year) * 12 + (maturity_date.month - effective_date.month)
    if total_months <= 0:
        total_months = max(1, round((maturity_date - effective_date).days / 30.4375))
        
    num_periods = max(1, total_months // frequency_months)
    
    # Generate unadjusted grid dates
    unadjusted_dates = []
    for i in range(num_periods + 1):
        if i == num_periods:
            unadjusted_dates.append(maturity_date)
        else:
            unadjusted_dates.append(add_months(effective_date, i * frequency_months))
            
    # Adjust accrual dates using business day convention (MODFOL)
    adjusted_dates = [apply_kofr_convention(d, business_day_conv, holidays) for d in unadjusted_dates]
    
    # Ensure strict monotonicity
    for i in range(1, len(adjusted_dates)):
        if adjusted_dates[i] <= adjusted_dates[i - 1]:
            adjusted_dates[i] = add_business_days(adjusted_dates[i - 1], 1, holidays)

    schedule = []
    for i in range(len(adjusted_dates) - 1):
        start_d = adjusted_dates[i]
        end_d = adjusted_dates[i + 1]
        
        # Payment Date: +2 Business Days (Seoul calendar) after calculation end date
        pay_d = add_business_days(end_d, payment_lag_bd, holidays) if payment_lag_bd > 0 else end_d
        
        frac = day_count_fraction(start_d, end_d, day_count)
        
        schedule.append({
            "period_no": i + 1,
            "start_date": start_d,
            "end_date": end_d,
            "pay_date": pay_d,
            "payment_lag_bd": payment_lag_bd,
            "day_count_fraction": round(frac, 6),
            "days": (end_d - start_d).days
        })
        
    return schedule
