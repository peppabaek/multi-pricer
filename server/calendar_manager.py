"""
Universal Calendar, Holiday, and Schedule Engine for Swap Pricers
- Loaded from Reference Excel 'Holidays' Sheet
- Supports all 18 Calendar Codes: SEB, LNB, NYB, TKB, SEB_NYB, TGT, LNB_TGT, NYB_TGT, NYB_TKB, LNB_NYB, LNB_NYB_TGT, LNB_TKB, SEB_TGT, SEB_TKB, SEB_LNB, LNB_SEB_TKB, TGT_TKB, BMA, NONE
- Day Count Conventions: Act/365, Act/360, 30/360, Act/Act
- Business Day Rolling: Modified Following, Following, Preceding
- Stub Rules: Short in arrears (Short back), Short upfront (Short front), Long in arrears (Long back), Long upfront (Long front)
- Adjust / Unadjust handling
- FixDay offset computation
"""

import os
import json
import datetime
from typing import List, Tuple, Set, Dict, Any, Optional

# Load holidays_data.json from workspace
_HOLIDAYS_MAP: Dict[str, Set[str]] = {}
_LAST_LOADED_TIME: Optional[str] = None

def _get_holidays_json_path() -> str:
    """
    Where the holiday calendars live.

    PRICER_DATA_DIR points this at writable storage - a mounted disk on a host, whose
    filesystem is otherwise rebuilt on every deploy, taking any holiday the desk added
    with it. The repo copy seeds it the first time so a fresh deployment starts with
    the calendars rather than with nothing.
    """
    repo_copy = os.path.join(os.path.dirname(__file__), "..", "holidays_data.json")

    data_dir = os.environ.get("PRICER_DATA_DIR")
    if data_dir:
        target = os.path.join(data_dir, "holidays_data.json")
        if not os.path.exists(target):
            try:
                os.makedirs(data_dir, exist_ok=True)
                if os.path.exists(repo_copy):
                    import shutil
                    shutil.copyfile(repo_copy, target)
            except OSError as e:
                print(f"[CalendarManager] PRICER_DATA_DIR unusable ({e}); "
                      f"falling back to the bundled calendars")
                return repo_copy
        return target

    for candidate in (repo_copy, os.path.abspath("holidays_data.json")):
        if os.path.exists(candidate):
            return candidate
    return repo_copy

def _init_holidays(force: bool = False):
    global _HOLIDAYS_MAP, _LAST_LOADED_TIME
    if _HOLIDAYS_MAP and not force:
        return
    json_path = _get_holidays_json_path()
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                new_map: Dict[str, Set[str]] = {}
                for cal_name, dates in raw_data.items():
                    new_map[cal_name.strip().upper()] = set(dates)
                _HOLIDAYS_MAP = new_map
                _LAST_LOADED_TIME = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[CalendarManager] Successfully loaded {len(_HOLIDAYS_MAP)} calendars from {json_path}")
        except Exception as e:
            print(f"[CalendarManager] Error loading holidays_data.json: {e}")

_init_holidays()

def reload_holidays() -> Dict[str, Any]:
    """Force reload holiday sets from holidays_data.json into memory"""
    _init_holidays(force=True)
    return get_calendar_status()

def add_holiday(cal_code: str, date_str: str, persist: bool = True) -> bool:
    """Add a holiday date to in-memory map and optionally persist to holidays_data.json"""
    _init_holidays()
    code = cal_code.strip().upper()
    code = CALENDAR_ALIASES.get(code, code)
    if code not in _HOLIDAYS_MAP:
        _HOLIDAYS_MAP[code] = set()
    _HOLIDAYS_MAP[code].add(date_str)
    
    if persist:
        json_path = _get_holidays_json_path()
        try:
            raw_data = {}
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
            raw_data[code] = sorted(list(_HOLIDAYS_MAP[code]))
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CalendarManager] Error persisting holiday: {e}")
            return False
    return True

def get_calendar_status() -> Dict[str, Any]:
    """Return summary statistics of currently loaded holiday calendars"""
    _init_holidays()
    cal_counts = {k: len(v) for k, v in _HOLIDAYS_MAP.items()}
    total_dates = sum(cal_counts.values())
    seb_dates = _HOLIDAYS_MAP.get("SEB", set())
    return {
        "status": "active",
        "last_loaded": _LAST_LOADED_TIME,
        "total_calendars": len(_HOLIDAYS_MAP),
        "calendar_counts": cal_counts,
        "seb_holiday_count": len(seb_dates),
        "seb_has_2027_10_12": "2027-10-12" in seb_dates,
        "total_holiday_entries": total_dates
    }

# Calendar Aliases
CALENDAR_ALIASES = {
    "SEOUL": "SEB",
    "KRW": "SEB",
    "NEW YORK": "NYB",
    "NYD": "NYB",
    "USD": "NYB",
    "LONDON": "LNB",
    "GBP": "LNB",
    "TOKYO": "TKB",
    "JPY": "TKB",
    "TARGET": "TGT",
    "EUR": "TGT",
    "SEB+NYB": "SEB_NYB",
    "JOINT": "SEB_NYB"
}

def get_calendar_holidays(cal_code: Optional[str]) -> Set[str]:
    """Retrieve holiday set for a given calendar code, dynamically merging composite calendars"""
    _init_holidays()
    if not cal_code:
        return set()
    code = cal_code.strip().upper()
    code = CALENDAR_ALIASES.get(code, code)
    
    # Handle composite codes like SEB_NYB, SEB+LNB, LNB_SEB_TKB dynamically
    if "_" in code or "+" in code:
        parts = code.replace("+", "_").split("_")
        merged = set()
        for p in parts:
            p_code = CALENDAR_ALIASES.get(p.strip(), p.strip())
            if p_code in _HOLIDAYS_MAP:
                merged.update(_HOLIDAYS_MAP[p_code])
        # Also include any dates explicitly registered under the composite key itself
        if code in _HOLIDAYS_MAP:
            merged.update(_HOLIDAYS_MAP[code])
        return merged

    if code in _HOLIDAYS_MAP:
        return _HOLIDAYS_MAP[code]
        
    return set()

def parse_date(d: Any) -> datetime.date:
    if isinstance(d, datetime.datetime):
        return d.date()
    elif isinstance(d, datetime.date):
        return d
    elif isinstance(d, str):
        return datetime.datetime.strptime(d[:10], "%Y-%m-%d").date()
    raise ValueError(f"Cannot parse date: {d}")

def is_business_day(dt: datetime.date, cal_code: Optional[str] = None) -> bool:
    if dt.weekday() in (5, 6): # Saturday, Sunday
        return False
    if not cal_code or cal_code.upper() in ("NONE", "UNADJUSTED"):
        return True
    holidays = get_calendar_holidays(cal_code)
    dt_str = dt.strftime("%Y-%m-%d")
    return dt_str not in holidays

def add_business_days(dt: datetime.date, n: int, cal_code: Optional[str] = None) -> datetime.date:
    """Add or subtract n business days according to the given calendar"""
    curr = dt
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    while remaining > 0:
        curr += datetime.timedelta(days=step)
        if is_business_day(curr, cal_code):
            remaining -= 1
    return curr

def resolve_custom_pay_date(period: dict, end_date: datetime.date,
                            business_day_conv: str, cal_code: Optional[str]) -> datetime.date:
    """
    Pay date for one period of a pasted / extracted schedule.

    A pay date the source document actually stated is honoured as written. One that was
    defaulted to the period end is rolled onto a business day, so a period ending on a
    weekend or holiday does not settle - and discount - on a non-business date.
    """
    raw = period.get("pay_date")
    if isinstance(raw, str):
        try:
            raw = datetime.datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            raw = None
    pay = raw or end_date

    if period.get("pay_date_explicit"):
        return pay
    return apply_convention(pay, business_day_conv or "Modified Following", cal_code)


def roll_following(dt: datetime.date, cal_code: Optional[str] = None) -> datetime.date:
    curr = dt
    while not is_business_day(curr, cal_code):
        curr += datetime.timedelta(days=1)
    return curr

def roll_preceding(dt: datetime.date, cal_code: Optional[str] = None) -> datetime.date:
    curr = dt
    while not is_business_day(curr, cal_code):
        curr -= datetime.timedelta(days=1)
    return curr

def roll_modified_following(dt: datetime.date, cal_code: Optional[str] = None) -> datetime.date:
    """Modified Following: roll following, but if crossing into next month, roll preceding"""
    rolled = roll_following(dt, cal_code)
    if rolled.month != dt.month:
        return roll_preceding(dt, cal_code)
    return rolled

def apply_convention(dt: datetime.date, convention: str = "Modified Following", cal_code: Optional[str] = None) -> datetime.date:
    c = (convention or "").lower()
    if "unadj" in c:
        return dt
    elif "prec" in c:
        return roll_preceding(dt, cal_code)
    elif "mod" in c:
        return roll_modified_following(dt, cal_code)
    elif "foll" in c:
        return roll_following(dt, cal_code)
    return roll_modified_following(dt, cal_code)

def add_months(dt: datetime.date, months: int) -> datetime.date:
    """Add months with month-end day clamping"""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    max_days = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, max_days[month - 1])
    return datetime.date(year, month, day)

def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

def day_count_fraction(d1: datetime.date, d2: datetime.date, convention: str = "Act/360") -> float:
    """
    Day Count Fraction calculator supporting:
    - Act/365 (or Act/365 Fixed)
    - Act/360
    - 30/360 (Bond Basis / ISDA 30/360)
    - Act/Act (ISDA)
    """
    if d1 >= d2:
        return 0.0
    
    c = (convention or "Act/360").strip().lower()
    
    if "365" in c:
        return (d2 - d1).days / 365.0
        
    elif "360" in c and "30" not in c:
        return (d2 - d1).days / 360.0
        
    elif "30" in c or "360" in c:
        # Standard ISDA 30/360
        y1, m1, day1 = d1.year, d1.month, d1.day
        y2, m2, day2 = d2.year, d2.month, d2.day
        
        if day1 == 31:
            day1 = 30
        if day2 == 31 and day1 >= 30:
            day2 = 30
            
        return (360 * (y2 - y1) + 30 * (m2 - m1) + (day2 - day1)) / 360.0
        
    elif "act/act" in c:
        # ISDA Actual/Actual
        y1, y2 = d1.year, d2.year
        if y1 == y2:
            days_in_year = 366.0 if is_leap_year(y1) else 365.0
            return (d2 - d1).days / days_in_year
        else:
            d1_end = datetime.date(y1, 12, 31)
            days_in_y1 = 366.0 if is_leap_year(y1) else 365.0
            f1 = ((d1_end - d1).days + 1) / days_in_y1
            
            d2_start = datetime.date(y2, 1, 1)
            days_in_y2 = 366.0 if is_leap_year(y2) else 365.0
            f2 = (d2 - d2_start).days / days_in_y2
            
            middle_years = float(max(0, y2 - y1 - 1))
            return f1 + middle_years + f2
            
    return (d2 - d1).days / 360.0

def compute_fixing_date(start_date: datetime.date, fix_day: int = -1, fix_cal: Optional[str] = None) -> datetime.date:
    """Compute fixing date by shifting start_date by fix_day business days on fix_cal"""
    if fix_day == 0:
        return start_date
    return add_business_days(start_date, fix_day, fix_cal)

def generate_schedule(
    effective_date: datetime.date,
    maturity_date: datetime.date,
    frequency_months: int = 12,
    business_day_conv: str = "Modified Following",
    pay_cal: Optional[str] = None,
    stub_rule: str = "Short in arrears",
    adjust_rule: str = "Adjust"
) -> List[Tuple[datetime.date, datetime.date, datetime.date, float, datetime.date, datetime.date]]:
    """
    Generate complete multi-period cashflow schedule supporting all 4 stub rules & adjust modes.
    Returns: List of tuples (adj_start, adj_end, pay_date, frac, unadj_start, unadj_end)
    """
    is_adjusted = "unadj" not in (adjust_rule or "").lower()
    stub_norm = (stub_rule or "").strip().lower()
    
    # 1. Generate unadjusted period boundaries
    unadj_dates = []
    
    if "upfront" in stub_norm or "front" in stub_norm:
        # Backward generation from maturity (stub at front)
        curr = maturity_date
        unadj_dates.append(curr)
        while True:
            prev = add_months(curr, -frequency_months)
            if prev <= effective_date:
                if prev == effective_date:
                    unadj_dates.append(prev)
                else:
                    if "long" in stub_norm and len(unadj_dates) > 1:
                        # Long upfront: merge stub into first regular period
                        pass
                    else:
                        unadj_dates.append(effective_date)
                break
            unadj_dates.append(prev)
            curr = prev
        unadj_dates.reverse()
        if unadj_dates[0] != effective_date:
            unadj_dates[0] = effective_date
            
    else:
        # Forward generation from effective date (stub at back / in arrears)
        curr = effective_date
        unadj_dates.append(curr)
        while True:
            nxt = add_months(curr, frequency_months)
            if nxt >= maturity_date:
                if nxt == maturity_date:
                    unadj_dates.append(nxt)
                else:
                    if "long" in stub_norm and len(unadj_dates) > 1:
                        # Long in arrears: merge stub with preceding period
                        unadj_dates[-1] = maturity_date
                    else:
                        unadj_dates.append(maturity_date)
                break
            unadj_dates.append(nxt)
            curr = nxt
            
    # Clean unique sorted dates
    clean_unadj = []
    for d in unadj_dates:
        if not clean_unadj or d > clean_unadj[-1]:
            clean_unadj.append(d)
            
    if len(clean_unadj) < 2:
        clean_unadj = [effective_date, maturity_date]
        
    # 2. Build adjusted periods and payment dates
    periods = []
    for i in range(len(clean_unadj) - 1):
        u_st = clean_unadj[i]
        u_ed = clean_unadj[i + 1]
        
        a_st = apply_convention(u_st, business_day_conv, pay_cal) if (i > 0 and is_adjusted) else u_st
        a_ed = apply_convention(u_ed, business_day_conv, pay_cal) if is_adjusted else u_ed
        pay_dt = apply_convention(u_ed, business_day_conv, pay_cal)
        
        calc_st = a_st if is_adjusted else u_st
        calc_ed = a_ed if is_adjusted else u_ed
        
        periods.append((a_st, a_ed, pay_dt, calc_st, calc_ed, u_st, u_ed))
        
    return periods
