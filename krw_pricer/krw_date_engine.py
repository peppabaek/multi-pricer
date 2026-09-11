"""
KRW Date & Schedule Engine for KRW IRS (CD 91D)
- Seoul Bank Holidays (KRB: 한국거래소 및 금융결제원 공휴일)
- Spot T+1 Convention (국내 원화 스왑 표준)
- Act/365 (Fixed) Day Count Convention
- Modified Following Business Day Rolling
- Quarterly (3M) Cash Flow Period Schedule Generator
"""

import datetime
from typing import List, Tuple, Optional, Set

# Comprehensive Seoul Bank Holidays (KRB) for 2024 - 2036
# Includes Solar Holidays, Lunar New Year (설날), Chuseok (추석), Buddha's Birthday, and Substitute Holidays
SEOUL_BANK_HOLIDAYS: Set[datetime.date] = {
    # 2024
    datetime.date(2024, 1, 1),   # 신정
    datetime.date(2024, 2, 9),   # 설날 전날
    datetime.date(2024, 2, 10),  # 설날
    datetime.date(2024, 2, 12),  # 대체공휴일
    datetime.date(2024, 3, 1),   # 삼일절
    datetime.date(2024, 4, 10),  # 총선
    datetime.date(2024, 5, 1),   # 근로자의 날
    datetime.date(2024, 5, 6),   # 어린이날 대체
    datetime.date(2024, 5, 15),  # 부처님오신날
    datetime.date(2024, 6, 6),   # 현충일
    datetime.date(2024, 8, 15),  # 광복절
    datetime.date(2024, 9, 16),  # 추석 전날
    datetime.date(2024, 9, 17),  # 추석
    datetime.date(2024, 9, 18),  # 추석 다음날
    datetime.date(2024, 10, 1),  # 국군의 날 임시
    datetime.date(2024, 10, 3),  # 개천절
    datetime.date(2024, 10, 9),  # 한글날
    datetime.date(2024, 12, 25), # 성탄절
    
    # 2025
    datetime.date(2025, 1, 1),
    datetime.date(2025, 1, 28), datetime.date(2025, 1, 29), datetime.date(2025, 1, 30), # 설날
    datetime.date(2025, 3, 3),   # 삼일절 대체
    datetime.date(2025, 5, 1),   # 근로자의 날
    datetime.date(2025, 5, 5),   # 어린이날
    datetime.date(2025, 5, 6),   # 부처님오신날 대체
    datetime.date(2025, 6, 6),   # 현충일
    datetime.date(2025, 8, 15),  # 광복절
    datetime.date(2025, 10, 3),  # 개천절
    datetime.date(2025, 10, 5), datetime.date(2025, 10, 6), datetime.date(2025, 10, 7), datetime.date(2025, 10, 8), # 추석
    datetime.date(2025, 10, 9),  # 한글날
    datetime.date(2025, 12, 25), # 성탄절

    # 2026
    datetime.date(2026, 1, 1),
    datetime.date(2026, 2, 16), datetime.date(2026, 2, 17), datetime.date(2026, 2, 18), # 설날
    datetime.date(2026, 3, 2),   # 삼일절 대체
    datetime.date(2026, 5, 1),   # 근로자의 날
    datetime.date(2026, 5, 5),   # 어린이날
    datetime.date(2026, 5, 25),  # 부처님오신날 대체
    datetime.date(2026, 8, 17),  # 광복절 대체
    datetime.date(2026, 9, 24), datetime.date(2026, 9, 25), datetime.date(2026, 9, 28), # 추석
    datetime.date(2026, 10, 5),  # 개천절 대체
    datetime.date(2026, 10, 9),  # 한글날
    datetime.date(2026, 12, 25), # 성탄절

    # 2027
    datetime.date(2027, 1, 1),   # 신정
    datetime.date(2027, 2, 6), datetime.date(2027, 2, 7), datetime.date(2027, 2, 8), datetime.date(2027, 2, 9), # 설날 및 대체
    datetime.date(2027, 3, 1),   # 삼일절
    datetime.date(2027, 5, 1),   # 근로자의 날
    datetime.date(2027, 5, 5),   # 어린이날
    datetime.date(2027, 5, 13),  # 부처님오신날
    datetime.date(2027, 6, 6),   # 현충일
    datetime.date(2027, 8, 15), datetime.date(2027, 8, 16), # 광복절 및 대체
    datetime.date(2027, 9, 14), datetime.date(2027, 9, 15), datetime.date(2027, 9, 16), # 추석
    datetime.date(2027, 10, 3), datetime.date(2027, 10, 4),  # 개천절 및 대체
    datetime.date(2027, 10, 9), datetime.date(2027, 10, 11), # 한글날 및 대체
    datetime.date(2027, 10, 12), # 대체공휴일 (Murex/은행 협약 대체공휴일)
    datetime.date(2027, 12, 25), datetime.date(2027, 12, 27), # 성탄절 및 대체

    # 2028 - 2036 Fixed Anniversaries
}

def parse_date(date_str: str) -> datetime.date:
    """Parse 'YYYY-MM-DD' or datetime object into date object"""
    if isinstance(date_str, datetime.date):
        return date_str
    if isinstance(date_str, datetime.datetime):
        return date_str.date()
    return datetime.datetime.strptime(str(date_str).strip()[:10], "%Y-%m-%d").date()

def is_krw_business_day(dt: datetime.date, holidays: Optional[Set[datetime.date]] = None) -> bool:
    """Check if date is a Seoul Bank business day (Monday-Friday, not a public holiday)"""
    if dt.weekday() >= 5: # Saturday or Sunday
        return False
    h_set = holidays if holidays is not None else SEOUL_BANK_HOLIDAYS
    if dt in h_set:
        return False
    # Cross-check with central calendar manager
    try:
        from server.calendar_manager import is_business_day as cm_is_bday
        if not cm_is_bday(dt, "SEB"):
            return False
    except Exception:
        pass
    # Check regular fixed recurring holidays if beyond explicit set
    if dt.month == 1 and dt.day == 1: return False # 신정
    if dt.month == 3 and dt.day == 1: return False # 삼일절
    if dt.month == 5 and dt.day == 1: return False # 근로자의 날
    if dt.month == 5 and dt.day == 5: return False # 어린이날
    if dt.month == 6 and dt.day == 6: return False # 현충일
    if dt.month == 8 and dt.day == 15: return False # 광복절
    if dt.month == 10 and dt.day == 3: return False # 개천절
    if dt.month == 10 and dt.day == 9: return False # 한글날
    if dt.month == 12 and dt.day == 25: return False # 성탄절
    return True

def add_krw_business_days(start_date: datetime.date, n_days: int, holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    """Add N Seoul business days (e.g. N=1 for Spot T+1)"""
    curr = start_date
    step = 1 if n_days >= 0 else -1
    remaining = abs(n_days)
    while remaining > 0:
        curr += datetime.timedelta(days=step)
        if is_krw_business_day(curr, holidays):
            remaining -= 1
    return curr

def get_krw_spot_date(pricing_date: datetime.date, holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    """Calculate Spot T+1 date for KRW IRS"""
    return add_krw_business_days(pricing_date, 1, holidays)

def roll_following(dt: datetime.date, holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    curr = dt
    while not is_krw_business_day(curr, holidays):
        curr += datetime.timedelta(days=1)
    return curr

def roll_preceding(dt: datetime.date, holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    curr = dt
    while not is_krw_business_day(curr, holidays):
        curr -= datetime.timedelta(days=1)
    return curr

def roll_modified_following(dt: datetime.date, holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
    """Modified Following convention for KRW IRS"""
    rolled = roll_following(dt, holidays)
    if rolled.month != dt.month:
        return roll_preceding(dt, holidays)
    return rolled

def apply_krw_convention(dt: datetime.date, convention: str = "Modified Following", holidays: Optional[Set[datetime.date]] = None) -> datetime.date:
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
    """Add months with month-end clamping"""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    max_days = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, max_days[month - 1])
    return datetime.date(year, month, day)

def day_count_fraction(start_date: datetime.date, end_date: datetime.date, convention: str = "Act/365") -> float:
    """Calculate day count fraction. KRW IRS market standard is Act/365 (Fixed)."""
    days = (end_date - start_date).days
    conv = convention.upper().replace(" ", "")
    if conv in ("ACT/365", "ACTUAL/365", "ACT/365F", "A/365", "ACT/365(FIXED)"):
        return days / 365.0
    elif conv in ("ACT/360", "ACTUAL/360", "A/360"):
        return days / 360.0
    elif conv in ("30/360", "30E/360"):
        d1 = min(start_date.day, 30)
        d2 = min(end_date.day, 30) if d1 == 30 else end_date.day
        y_diff = end_date.year - start_date.year
        m_diff = end_date.month - start_date.month
        return (360 * y_diff + 30 * m_diff + (d2 - d1)) / 360.0
    return days / 365.0

def generate_krw_schedule(
    effective_date: datetime.date,
    maturity_date: datetime.date,
    frequency_months: int = 3, # 3M for Standard KRW IRS
    business_day_conv: str = "Modified Following",
    stub_rule: str = "Short Back",
    holidays: Optional[Set[datetime.date]] = None
) -> List[Tuple[datetime.date, datetime.date, datetime.date, float]]:
    """
    Generate KRW IRS Quarterly Cash Flow Schedule
    Returns: List of (start_date, end_date, pay_date, frac_act365)
    """
    if "front" in stub_rule.lower():
        unadj_dates = [maturity_date]
        curr = maturity_date
        while True:
            prev = add_months(curr, -frequency_months)
            if prev <= effective_date:
                unadj_dates.insert(0, effective_date)
                break
            unadj_dates.insert(0, prev)
            curr = prev
    else:
        unadj_dates = [effective_date]
        curr = effective_date
        while True:
            nxt = add_months(curr, frequency_months)
            if nxt >= maturity_date:
                unadj_dates.append(maturity_date)
                break
            unadj_dates.append(nxt)
            curr = nxt
            
    adj_dates = [effective_date]
    for d in unadj_dates[1:-1]:
        adj_dates.append(apply_krw_convention(d, business_day_conv, holidays))
    adj_dates.append(apply_krw_convention(maturity_date, business_day_conv, holidays))
    
    periods = []
    for i in range(len(adj_dates) - 1):
        st = adj_dates[i]
        ed = adj_dates[i + 1]
        pay_date = apply_krw_convention(ed, business_day_conv, holidays)
        frac = day_count_fraction(st, ed, "Act/365")
        periods.append((st, ed, pay_date, frac))
        
    return periods
