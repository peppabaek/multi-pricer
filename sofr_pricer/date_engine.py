"""
Date & Calendar Engine for USD SOFR IRS
- NYB (New York Banking) Holidays
- Business Day Rolling: Modified Following, Following, Preceding
- Day Count Conventions: Act/360, Act/365, 30/360, Act/Act
- Schedule Generation: Effective Date -> Maturity Date with Frequency and Stubs
"""

import datetime
from typing import List, Tuple, Optional

# Default New York Banking Holidays (derived from standard US SIFMA/Federal Reserve & Reference Excel)
DEFAULT_NYB_HOLIDAYS = {
    # 2019 ~ 2035 Standard US Federal Holidays
    "2019-01-01", "2019-01-21", "2019-02-18", "2019-05-27", "2019-07-04", "2019-09-02", "2019-10-14", "2019-11-11", "2019-11-28", "2019-12-25",
    "2020-01-01", "2020-01-20", "2020-02-17", "2020-05-25", "2020-07-03", "2020-07-04", "2020-09-07", "2020-10-12", "2020-11-11", "2020-11-26", "2020-12-25",
    "2021-01-01", "2021-01-18", "2021-02-15", "2021-05-31", "2021-07-05", "2021-09-06", "2021-10-11", "2021-11-11", "2021-11-25", "2021-12-24", "2021-12-25",
    "2022-01-01", "2022-01-17", "2022-02-21", "2022-05-30", "2022-06-20", "2022-07-04", "2022-09-05", "2022-10-10", "2022-11-11", "2022-11-24", "2022-12-26",
    "2023-01-02", "2023-01-16", "2023-02-20", "2023-05-29", "2023-06-19", "2023-07-04", "2023-09-04", "2023-10-09", "2023-11-10", "2023-11-23", "2023-12-25",
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-05-27", "2024-06-19", "2024-07-04", "2024-09-02", "2024-10-14", "2024-11-11", "2024-11-28", "2024-12-25",
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-10-11", "2027-11-11", "2027-11-25", "2027-12-24",
    "2028-01-01", "2028-01-17", "2028-02-21", "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04", "2028-10-09", "2028-11-10", "2028-11-23", "2028-12-25",
    "2029-01-01", "2029-01-15", "2029-02-19", "2029-05-28", "2029-06-19", "2029-07-04", "2029-09-03", "2029-10-08", "2029-11-12", "2029-11-22", "2029-12-25",
    "2030-01-01", "2030-01-21", "2030-02-18", "2030-05-27", "2030-06-19", "2030-07-04", "2030-09-02", "2030-10-14", "2030-11-11", "2030-11-28", "2030-12-25",
    "2031-01-01", "2031-01-20", "2031-02-17", "2031-05-26", "2031-06-19", "2031-07-04", "2031-09-01", "2031-10-13", "2031-11-11", "2031-11-27", "2031-12-25",
    "2032-01-01", "2032-01-19", "2032-02-16", "2032-05-31", "2032-06-18", "2032-07-05", "2032-09-06", "2032-10-11", "2032-11-11", "2032-11-25", "2032-12-24",
    "2033-01-01", "2033-01-17", "2033-02-21", "2033-05-30", "2033-06-20", "2033-07-04", "2033-09-05", "2033-10-10", "2033-11-11", "2033-11-24", "2033-12-26",
    "2034-01-02", "2034-01-16", "2034-02-20", "2034-05-29", "2034-06-19", "2034-07-04", "2034-09-04", "2034-10-09", "2034-11-10", "2034-11-23", "2034-12-25",
    "2035-01-01", "2035-01-15", "2035-02-19", "2035-05-28", "2035-06-19", "2035-07-04", "2035-09-03", "2035-10-08", "2035-11-12", "2035-11-22", "2035-12-25"
}

def parse_date(d) -> datetime.date:
    if isinstance(d, datetime.datetime):
        return d.date()
    elif isinstance(d, datetime.date):
        return d
    elif isinstance(d, str):
        return datetime.datetime.strptime(d[:10], "%Y-%m-%d").date()
    raise ValueError(f"Cannot parse date: {d}")

def is_business_day(dt: datetime.date, holidays: Optional[set] = None) -> bool:
    if holidays is None:
        holidays = DEFAULT_NYB_HOLIDAYS
    if dt.weekday() in (5, 6): # Saturday, Sunday
        return False
    dt_str = dt.strftime("%Y-%m-%d")
    return dt_str not in holidays

def add_business_days(dt: datetime.date, n: int, holidays: Optional[set] = None) -> datetime.date:
    """Add/subtract n business days"""
    curr = dt
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    while remaining > 0:
        curr += datetime.timedelta(days=step)
        if is_business_day(curr, holidays):
            remaining -= 1
    return curr

def roll_following(dt: datetime.date, holidays: Optional[set] = None) -> datetime.date:
    curr = dt
    while not is_business_day(curr, holidays):
        curr += datetime.timedelta(days=1)
    return curr

def roll_preceding(dt: datetime.date, holidays: Optional[set] = None) -> datetime.date:
    curr = dt
    while not is_business_day(curr, holidays):
        curr -= datetime.timedelta(days=1)
    return curr

def roll_modified_following(dt: datetime.date, holidays: Optional[set] = None) -> datetime.date:
    """Modified Following convention (standard for IRS/OIS)"""
    rolled = roll_following(dt, holidays)
    if rolled.month != dt.month:
        return roll_preceding(dt, holidays)
    return rolled

def apply_convention(dt: datetime.date, convention: str = "Modified Following", holidays: Optional[set] = None) -> datetime.date:
    c = convention.lower()
    if "mod" in c:
        return roll_modified_following(dt, holidays)
    elif "prec" in c:
        return roll_preceding(dt, holidays)
    elif "foll" in c:
        return roll_following(dt, holidays)
    elif "unadj" in c:
        return dt
    return roll_modified_following(dt, holidays)

def add_months(dt: datetime.date, months: int) -> datetime.date:
    """Add months handling end of month clamping"""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    # Day clamping
    max_days = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, max_days[month - 1])
    return datetime.date(year, month, day)

def day_count_fraction(start_date: datetime.date, end_date: datetime.date, convention: str = "Act/360") -> float:
    """Calculate day count fraction"""
    conv = convention.upper().replace(" ", "")
    days = (end_date - start_date).days
    
    if conv in ("ACT/360", "ACTUAL/360", "A/360"):
        return days / 360.0
    elif conv in ("ACT/365", "ACTUAL/365", "A/365", "ACT/365F"):
        return days / 365.0
    elif conv in ("30/360", "30/360BOND", "30E/360"):
        d1 = min(start_date.day, 30)
        d2 = min(end_date.day, 30) if d1 == 30 else end_date.day
        y_diff = end_date.year - start_date.year
        m_diff = end_date.month - start_date.month
        return (360 * y_diff + 30 * m_diff + (d2 - d1)) / 360.0
    elif conv in ("ACT/ACT", "ACTUAL/ACTUAL"):
        # Simple Act/Act approximation
        return days / 365.25
    return days / 360.0

def generate_schedule(
    effective_date: datetime.date,
    maturity_date: datetime.date,
    frequency_months: int = 12, # 12 for Annual, 6 for Semi, 3 for Quarterly
    business_day_conv: str = "Modified Following",
    stub_rule: str = "Short Back",
    holidays: Optional[set] = None
) -> List[Tuple[datetime.date, datetime.date, datetime.date, float]]:
    """
    Generate Cash Flow Period Schedule
    Returns list of (start_date, end_date, pay_date, day_count_fraction)
    """
    periods = []
    
    # Generate unadjusted period bounds
    if "front" in stub_rule.lower(): # Stub at Front (backward from maturity)
        unadj_dates = [maturity_date]
        curr = maturity_date
        while True:
            prev = add_months(curr, -frequency_months)
            if prev <= effective_date:
                unadj_dates.insert(0, effective_date)
                break
            unadj_dates.insert(0, prev)
            curr = prev
    else: # Stub at Back (forward from effective)
        unadj_dates = [effective_date]
        curr = effective_date
        while True:
            nxt = add_months(curr, frequency_months)
            if nxt >= maturity_date:
                unadj_dates.append(maturity_date)
                break
            unadj_dates.append(nxt)
            curr = nxt
            
    # Adjust dates with convention
    adj_dates = [effective_date]
    for d in unadj_dates[1:-1]:
        adj_dates.append(apply_convention(d, business_day_conv, holidays))
    adj_dates.append(apply_convention(maturity_date, business_day_conv, holidays))
    
    # Build periods
    for i in range(len(adj_dates) - 1):
        st = adj_dates[i]
        ed = adj_dates[i + 1]
        # Payment date is usually the period end date rolled with convention
        pay_date = apply_convention(ed, business_day_conv, holidays)
        frac = day_count_fraction(st, ed, "Act/360")
        periods.append((st, ed, pay_date, frac))
        
    return periods
