"""
Smart Excel Rollercoaster Schedule Parser and Helper Engine
Supports USD SOFR, KRW CD 91D, KRW KOFR OIS, and KRW FX SOFR (CRS)
Handles:
1. 2-Column: [Date (End/Pay), Notional] -> auto builds sequential periods from Effective Date
2. 3-Column: [Date (End/Pay), Notional, Spread/Margin bp or Fixed Rate %]
3. 4-Column: [Start Date, End Date, Pay Date, Notional]
4. 6-Column: [Start, End, Pay, Notional, Rate %, Spread bp]
"""

import re
import datetime
from typing import List, Dict, Any, Optional, Tuple

def parse_date_str(d_str: Any) -> Optional[datetime.date]:
    """Parse various date formats (YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD, MM/DD/YYYY)"""
    if isinstance(d_str, datetime.date):
        return d_str
    if not d_str:
        return None
    s = str(d_str).strip()
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%m/%d/%Y", "%d/%m/%Y"]:
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def parse_notional_str(n_str: Any, default_val: float = 100_000_000.0) -> float:
    """Parse notional string supporting suffixes (M, B, k, 억, etc.), $, ₩, commas"""
    if isinstance(n_str, (int, float)):
        return float(n_str)
    if not n_str:
        return default_val
    s = str(n_str).strip().replace(",", "").replace("$", "").replace("₩", "").replace(" ", "")
    multiplier = 1.0
    if s.endswith("M") or s.endswith("m"):
        multiplier = 1_000_000.0
        s = s[:-1]
    elif s.endswith("B") or s.endswith("b") or s.endswith("bn"):
        multiplier = 1_000_000_000.0
        s = s.rstrip("bnBN")
    elif s.endswith("K") or s.endswith("k"):
        multiplier = 1_000.0
        s = s[:-1]
    elif s.endswith("억"):
        multiplier = 100_000_000.0
        s = s[:-1]
    elif s.endswith("조"):
        multiplier = 1_000_000_000_000.0
        s = s[:-1]
    elif s.endswith("천만"):
        multiplier = 10_000_000.0
        s = s[:-2]
    elif s.endswith("백만"):
        multiplier = 1_000_000.0
        s = s[:-2]
        
    try:
        return float(s) * multiplier
    except ValueError:
        return default_val

# Column names seen on desks, in both languages. Matched against a header row so a
# sheet can carry whatever extra columns it likes, in whatever order, without the
# positional reading silently sliding one column to the left.
_COL_PATTERNS = [
    # (field, patterns) - order matters: the first field a header matches wins, and
    # "원금 상환액" must be recognised as a repayment before "원금" claims it as notional.
    ("skip_repay", ("상환", "repay", "amortis", "amortiz", "redemption")),
    ("skip_days", ("일수", "days", "day count", "acc days")),
    ("skip_no", ("회차", "period no", "no.", "seq", "index", "번호")),
    ("fixing", ("변동금리결정", "금리결정", "픽싱", "fixing", "reset", "결정일")),
    ("start", ("시작일", "개시일", "start", "from", "accrual start", "기산일")),
    ("end", ("만기일", "종료일", "end", "to", "accrual end", "maturity")),
    ("pay", ("이자교환일", "지급일", "결제일", "pay", "payment", "settle")),
    ("notional", ("명목", "notional", "nominal", "잔액", "outstanding", "원금", "principal")),
    ("rate", ("금리", "rate", "coupon", "fixed rate")),
    ("spread", ("스프레드", "spread", "margin", "가산")),
]


def _classify_header(cell: str) -> Optional[str]:
    c = str(cell or "").strip().lower()
    if not c:
        return None
    for field, pats in _COL_PATTERNS:
        if any(pat in c for pat in pats):
            return None if field.startswith("skip_") else field
    return None


def _header_map(cells: List[str]) -> Dict[str, int]:
    """Column index per field, from a header row. Empty if this is not a header."""
    out: Dict[str, int] = {}
    for i, cell in enumerate(cells):
        field = _classify_header(cell)
        if field and field not in out:
            out[field] = i
    # Dates alone are not enough to trust it: a data row can look like anything, but a
    # header names at least a start and an end.
    return out if {"start", "end"} <= set(out) else {}


def _split_row(line: str) -> List[str]:
    """
    Split one pasted row, keeping empty cells where they are.

    Excel gives an empty cell for a blank 회차, and dropping it shifts every column
    after it - which is how a notional ends up being read as a date.
    """
    for sep in ("\t", "|", ";"):
        if sep in line:
            cells = [c.strip() for c in line.split(sep)]
            while cells and not cells[-1]:
                cells.pop()
            return cells
    return [c.strip() for c in re.split(r"\s{2,}|\s+", line) if c.strip()]


def _rows_by_header(lines: List[str], default_notional: float,
                    default_coupon_pct: float, default_spread_bp: float
                    ) -> Optional[List[Dict[str, Any]]]:
    """Read the block through its own header row, or return None if it has none."""
    cmap: Dict[str, int] = {}
    periods: List[Dict[str, Any]] = []

    for line in lines:
        cells = _split_row(line)
        if not cells:
            continue
        if not cmap:
            cmap = _header_map(cells)
            continue                       # the header itself is never a period

        def cell(field):
            i = cmap.get(field)
            return cells[i] if i is not None and i < len(cells) else ""

        st = parse_date_str(cell("start"))
        ed = parse_date_str(cell("end"))
        if not st or not ed:
            continue                       # spacer, subtotal, or a stray note

        pay = parse_date_str(cell("pay")) or ed
        notional = parse_notional_str(cell("notional"), default_notional)
        rate = default_coupon_pct
        spread = default_spread_bp
        if cell("rate"):
            try:
                rate = float(str(cell("rate")).replace("%", "").replace(",", ""))
            except ValueError:
                pass
        if cell("spread"):
            try:
                spread = float(str(cell("spread")).replace("bp", "").replace(",", ""))
            except ValueError:
                pass

        per = {
            "period_no": len(periods) + 1,
            "start_date": st.strftime("%Y-%m-%d"),
            "end_date": ed.strftime("%Y-%m-%d"),
            "pay_date": pay.strftime("%Y-%m-%d"),
            # The sheet named a pay date column, so what is in it is what the desk
            # agreed - it is not re-rolled.
            "pay_date_explicit": "pay" in cmap,
            "notional": notional,
            "fixed_rate_pct": rate,
            "spread_bp": spread,
        }
        fx = parse_date_str(cell("fixing"))
        if fx:
            per["fixing_date"] = fx.strftime("%Y-%m-%d")
        periods.append(per)

    return periods if (cmap and periods) else None


def parse_rollercoaster_paste(
    raw_text: str,
    effective_date: datetime.date,
    default_notional: float = 100_000_000.0,
    default_coupon_pct: float = 0.0,
    default_spread_bp: float = 0.0,
    currency: str = "USD"
) -> List[Dict[str, Any]]:
    """
    Parses pasted text from Excel into normalized custom schedule periods.
    """
    if not raw_text or not raw_text.strip():
        return []
        
    lines = raw_text.strip().splitlines()

    # A block with a header row is read by name. That covers any column order, extra
    # columns, and the blank cells that come with sub-rows - none of which the
    # positional reading below can survive.
    by_header = _rows_by_header(lines, default_notional, default_coupon_pct,
                                default_spread_bp)
    if by_header:
        return by_header

    rows = []
    
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
            
        # Split by tab, pipe, semicolon, or multi-space
        if "\t" in cleaned:
            parts = [p.strip() for p in cleaned.split("\t") if p.strip()]
        elif "|" in cleaned:
            parts = [p.strip() for p in cleaned.split("|") if p.strip()]
        elif ";" in cleaned:
            parts = [p.strip() for p in cleaned.split(";") if p.strip()]
        else:
            parts = [p.strip() for p in re.split(r"\s{2,}|\s+", cleaned) if p.strip()]
            
        if not parts:
            continue
            
        # Skip header rows
        first_token = parts[0].lower()
        if any(h in first_token for h in ["start", "end", "date", "pay", "mat", "날짜", "만기", "no", "period", "회차", "leg"]):
            continue
            
        rows.append(parts)
        
    if not rows:
        return []
        
    periods: List[Dict[str, Any]] = []
    curr_start = effective_date
    
    for idx, parts in enumerate(rows):
        # Case A: 1-Column only date (uses default notional)
        if len(parts) == 1:
            ed = parse_date_str(parts[0])
            if not ed:
                continue
            st = curr_start
            periods.append({
                "period_no": idx + 1,
                "start_date": st.strftime("%Y-%m-%d"),
                "end_date": ed.strftime("%Y-%m-%d"),
                "pay_date": ed.strftime("%Y-%m-%d"),
                "notional": default_notional,
                "fixed_rate_pct": default_coupon_pct,
                "spread_bp": default_spread_bp
            })
            curr_start = ed
            
        # Case B: 2-Column [Date, Notional]
        elif len(parts) == 2:
            # Check if token 0 is date and token 1 is notional
            d1 = parse_date_str(parts[0])
            d2 = parse_date_str(parts[1])
            
            if d1 and not d2:
                # [End Date, Notional]
                ed = d1
                notional = parse_notional_str(parts[1], default_notional)
                st = curr_start
                periods.append({
                    "period_no": idx + 1,
                    "start_date": st.strftime("%Y-%m-%d"),
                    "end_date": ed.strftime("%Y-%m-%d"),
                    "pay_date": ed.strftime("%Y-%m-%d"),
                    "notional": notional,
                    "fixed_rate_pct": default_coupon_pct,
                    "spread_bp": default_spread_bp
                })
                curr_start = ed
            elif d1 and d2:
                # [Start Date, End Date] (uses default notional)
                st, ed = d1, d2
                periods.append({
                    "period_no": idx + 1,
                    "start_date": st.strftime("%Y-%m-%d"),
                    "end_date": ed.strftime("%Y-%m-%d"),
                    "pay_date": ed.strftime("%Y-%m-%d"),
                    "notional": default_notional,
                    "fixed_rate_pct": default_coupon_pct,
                    "spread_bp": default_spread_bp
                })
                curr_start = ed
            else:
                continue

        # Case C: 3-Column [Date, Notional, Margin/Rate] OR [Start, End, Notional]
        elif len(parts) == 3:
            d1 = parse_date_str(parts[0])
            d2 = parse_date_str(parts[1])
            
            if d1 and d2:
                # [Start Date, End Date, Notional]
                st, ed = d1, d2
                notional = parse_notional_str(parts[2], default_notional)
                periods.append({
                    "period_no": idx + 1,
                    "start_date": st.strftime("%Y-%m-%d"),
                    "end_date": ed.strftime("%Y-%m-%d"),
                    "pay_date": ed.strftime("%Y-%m-%d"),
                    "notional": notional,
                    "fixed_rate_pct": default_coupon_pct,
                    "spread_bp": default_spread_bp
                })
                curr_start = ed
            elif d1 and not d2:
                # [End Date, Notional, Spread bp or Rate %]
                ed = d1
                notional = parse_notional_str(parts[1], default_notional)
                val3_str = parts[2].strip().replace("bp", "").replace("%", "")
                try:
                    val3 = float(val3_str)
                except ValueError:
                    val3 = default_spread_bp
                
                spread = val3 if "bp" in parts[2].lower() or abs(val3) > 15.0 else default_spread_bp
                rate = val3 if "%" in parts[2] or (0.0 <= val3 <= 15.0 and "bp" not in parts[2].lower()) else default_coupon_pct
                
                st = curr_start
                periods.append({
                    "period_no": idx + 1,
                    "start_date": st.strftime("%Y-%m-%d"),
                    "end_date": ed.strftime("%Y-%m-%d"),
                    "pay_date": ed.strftime("%Y-%m-%d"),
                    "notional": notional,
                    "fixed_rate_pct": rate,
                    "spread_bp": spread
                })
                curr_start = ed

        # Case D: 4 or more columns: [Start Date, End Date, Pay Date, Notional/Nominal, Fixing Date / Rate, ...]
        elif len(parts) >= 4:
            d1 = parse_date_str(parts[0])
            d2 = parse_date_str(parts[1])
            d3 = parse_date_str(parts[2])
            
            rate = default_coupon_pct
            spread = default_spread_bp
            fixing_date_str = None
            
            pay_date_explicit = False
            if d1 and d2 and d3:
                # [Start, End, Pay Date, Notional/Nominal, ...]
                st, ed, pay_dt = d1, d2, d3
                pay_date_explicit = True
                notional = parse_notional_str(parts[3], default_notional)
                
                # Check 5th column: Marketer standard is [Fixing Date]
                if len(parts) >= 5 and parts[4]:
                    d5 = parse_date_str(parts[4])
                    if d5:
                        fixing_date_str = d5.strftime("%Y-%m-%d")
                    else:
                        val_str = parts[4].replace("%", "").replace("bp", "").strip()
                        try:
                            val = float(val_str)
                            if "%" in parts[4] or abs(val) <= 25.0:
                                rate = val
                            else:
                                spread = val
                        except ValueError:
                            pass
                            
                # Check 6th column: Rate % or Spread bp
                if len(parts) >= 6 and parts[5]:
                    d6 = parse_date_str(parts[5])
                    if d6 and not fixing_date_str:
                        fixing_date_str = d6.strftime("%Y-%m-%d")
                    else:
                        val_str = parts[5].replace("%", "").replace("bp", "").strip()
                        try:
                            val = float(val_str)
                            if "bp" in parts[5].lower() or abs(val) > 25.0:
                                spread = val
                            else:
                                rate = val
                        except ValueError:
                            pass
            elif d1 and d2 and not d3:
                # [Start, End, Notional, Rate/Spread]
                st, ed, pay_dt = d1, d2, d2
                notional = parse_notional_str(parts[2], default_notional)
                val_str = parts[3].replace("%", "").replace("bp", "").strip() if len(parts) >= 4 and parts[3] else ""
                try:
                    val = float(val_str) if val_str else 0.0
                    rate = val if "%" in parts[3] or abs(val) <= 25.0 else default_coupon_pct
                    spread = val if "bp" in parts[3].lower() or abs(val) > 25.0 else default_spread_bp
                except ValueError:
                    rate = default_coupon_pct
            elif d1 and not d2:
                # [End, Notional, Rate, Spread]
                st = curr_start
                ed, pay_dt = d1, d1
                notional = parse_notional_str(parts[1], default_notional)
                rate = float(parts[2].replace("%", "")) if len(parts) >= 3 and parts[2] else default_coupon_pct
                spread = float(parts[3].replace("bp", "")) if len(parts) >= 4 and parts[3] else default_spread_bp
            else:
                continue
                
            p_dict = {
                "period_no": idx + 1,
                "start_date": st.strftime("%Y-%m-%d"),
                "end_date": ed.strftime("%Y-%m-%d"),
                "pay_date": pay_dt.strftime("%Y-%m-%d"),
                # Only a pay date the document actually stated is left untouched; a
                # defaulted one is rolled to a business day by the pricing engine.
                "pay_date_explicit": pay_date_explicit,
                "notional": notional,
                "fixed_rate_pct": rate,
                "spread_bp": spread
            }
            if fixing_date_str:
                p_dict["fixing_date"] = fixing_date_str
            periods.append(p_dict)
            curr_start = ed
            
    return periods


MARKETER_SAMPLE_LEG1_TEXT = """Start date\tEnd date\tPay date\tNominal\tFixing date
2025-08-06\t2025-09-06\t2025-09-08\t2,200,000,000\t2025-08-05
2025-09-06\t2025-10-06\t2025-10-10\t2,200,000,000\t2025-08-05
2025-10-06\t2025-11-06\t2025-11-06\t2,200,000,000\t2025-08-05
2025-11-06\t2025-12-06\t2025-12-08\t2,200,000,000\t2025-11-05
2025-12-06\t2026-01-06\t2026-01-06\t2,200,000,000\t2025-11-05
2026-01-06\t2026-02-06\t2026-02-06\t2,200,000,000\t2025-11-05
2026-02-06\t2026-03-06\t2026-03-06\t2,200,000,000\t2026-02-05
2026-03-06\t2026-04-06\t2026-04-06\t2,200,000,000\t2026-02-05
2026-04-06\t2026-05-06\t2026-05-06\t2,200,000,000\t2026-02-05
2026-05-06\t2026-06-06\t2026-06-08\t2,200,000,000\t2026-05-04
2026-06-06\t2026-07-06\t2026-07-06\t2,200,000,000\t2026-05-04
2026-07-06\t2026-08-03\t2026-08-03\t2,200,000,000\t2026-05-04"""

MARKETER_SAMPLE_LEG2_TEXT = MARKETER_SAMPLE_LEG1_TEXT

