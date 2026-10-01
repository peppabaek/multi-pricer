"""
KRW CD 91D IRS Curve Bootstrapping & Interpolation Engine (/KRW KRCD Q 3M MODFOL)
Matching Reference Excel ('KRWQ3MIRS' sheet) and Murex KRW Curve exactly:
- Day Count: Act/365 (Fixed)
- Spot Convention: T+1 (Seoul)
- 3M Quarterly Grid (1M to 240M / 20Y, 80 Quarters)
- Closed-Form Sequential Bootstrapping with Par Swap Rate Linear Interpolation for intermediate quarters
- EXP ACT/365 Continuous Zero Rate: r_zero = -ln(DF) * 365 / (t - PricingDate) * 100
- Linear Spline Zero Rate Interpolation for arbitrary Odd Tenors
"""

import math
import datetime
from typing import List, Dict, Tuple, Optional, Set
from .krw_date_engine import (
    parse_date, apply_krw_convention, add_months, day_count_fraction, get_krw_spot_date
)

# Standard KRW IRS Pillars from Market Data (Tradition / KMBC / ICAP)
KRW_STANDARD_PILLARS = [
    ("ON", "O/N", 0),
    ("3M", "3M CD", 3),
    ("6M", "6M IRS", 6),
    ("9M", "9M IRS", 9),
    ("1Y", "1Y IRS", 12),
    ("18M", "18M IRS", 18),
    ("2Y", "2Y IRS", 24),
    ("3Y", "3Y IRS", 36),
    ("4Y", "4Y IRS", 48),
    ("5Y", "5Y IRS", 60),
    ("7Y", "7Y IRS", 84),
    ("10Y", "10Y IRS", 120),
    ("12Y", "12Y IRS", 144),
    ("15Y", "15Y IRS", 180),
    ("20Y", "20Y IRS", 240)
]

class KRWCurve:
    def __init__(self, pricing_date: datetime.date, settle_date: datetime.date):
        self.pricing_date = pricing_date
        self.settle_date = settle_date
        
        self.pillars: List[Dict] = []
        self.mat_dates: List[datetime.date] = []
        self.zero_rates: List[float] = []
        self.dfs: List[float] = []
        self.df_settle: float = 1.0
        
    def get_zero_rate(self, target_date: datetime.date) -> float:
        """
        Step 6-A: 대표 tenor zero rate를 interpolation하여 기타 tenor zero rate 산출
        (Linear interpolation of continuous Zero Rate from Today across curve pillars)
        """
        if not self.mat_dates or not self.zero_rates:
            return 0.0
            
        if target_date <= self.mat_dates[0]:
            return self.zero_rates[0]
        if target_date >= self.mat_dates[-1]:
            return self.zero_rates[-1]
            
        for i in range(1, len(self.mat_dates)):
            if target_date <= self.mat_dates[i]:
                d0 = self.mat_dates[i - 1]
                d1 = self.mat_dates[i]
                z0 = self.zero_rates[i - 1]
                z1 = self.zero_rates[i]
                
                t_total = (d1 - d0).days
                t_curr = (target_date - d0).days
                if t_total == 0:
                    return z0
                return z0 + (z1 - z0) * (t_curr / t_total)
                
        return self.zero_rates[-1]
        
    def get_df(self, target_date: datetime.date) -> float:
        """
        Step 6-B: 산출된 zero rate를 이용하여 기타 tenor의 discount factor 산출
        DF(t) = exp( - r_zero(t)/100 * (t - PricingDate) / 365 )
        """
        if target_date <= self.pricing_date:
            return 1.0
        if target_date == self.settle_date and getattr(self, "df_settle", None) is not None:
            return self.df_settle
            
        zero = self.get_zero_rate(target_date)
        dt_days = (target_date - self.pricing_date).days
        return math.exp(- (zero / 100.0) * (dt_days / 365.0))
        
    def get_forward_rate(self, start_date: datetime.date, end_date: datetime.date, day_count: str = "Act/365") -> float:
        """
        Step 7: 산출된 discount factor를 이용해 implied forward rate 산출
        F(ts, te) = (1 / tau) * (DF(ts) / DF(te) - 1.0)
        """
        if start_date >= end_date:
            return 0.0
        df_start = self.get_df(start_date)
        df_end = self.get_df(end_date)
        
        frac = day_count_fraction(start_date, end_date, day_count)
        if frac == 0 or df_end == 0:
            return 0.0
            
        return (df_start / df_end - 1.0) / frac


def bootstrap_krw_curve(
    pricing_date: datetime.date,
    settle_date: Optional[datetime.date] = None,
    quotes: Optional[List[Tuple[str, float]]] = None,
    holidays: Optional[Set[datetime.date]] = None
) -> KRWCurve:
    """
    Bootstrap full KRW CD 91D IRS Curve matching Reference Excel 'KRWQ3MIRS' sheet exactly.
    """
    if settle_date is None:
        settle_date = get_krw_spot_date(pricing_date, holidays)
        
    curve = KRWCurve(pricing_date, settle_date)
    quote_map: Dict[str, float] = {}
    
    # Default baseline quotes from Prebon Yamane (PREA) & KRW Deposit
    default_quotes = [
        ("ON", 2.8042),
        ("1M", 2.8619),
        ("2M", 2.9141),
        ("3M", 2.9700),
        ("4M", 3.0401),
        ("5M", 3.1079),
        ("6M", 3.2575),
        ("9M", 3.3925),
        ("1Y", 3.5075),
        ("18M", 3.6725),
        ("2Y", 3.7475),
        ("3Y", 3.8550),
        ("4Y", 3.9250),
        ("5Y", 3.9675),
        ("6Y", 4.0075),
        ("7Y", 4.0400),
        ("8Y", 4.0600),
        ("9Y", 4.0800),
        ("10Y", 4.1000),
        ("12Y", 4.1225),
        ("15Y", 4.1125),
        ("20Y", 4.0400),
        ("25Y", 3.9425),
        ("30Y", 3.8450)
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
        elif t_clean == "72M": quote_map["6Y"] = float(r)
        elif t_clean == "6Y": quote_map["72M"] = float(r)
        elif t_clean == "84M": quote_map["7Y"] = float(r)
        elif t_clean == "7Y": quote_map["84M"] = float(r)
        elif t_clean == "96M": quote_map["8Y"] = float(r)
        elif t_clean == "8Y": quote_map["96M"] = float(r)
        elif t_clean == "108M": quote_map["9Y"] = float(r)
        elif t_clean == "9Y": quote_map["108M"] = float(r)
        elif t_clean == "120M": quote_map["10Y"] = float(r)
        elif t_clean == "10Y": quote_map["120M"] = float(r)
        elif t_clean == "144M": quote_map["12Y"] = float(r)
        elif t_clean == "12Y": quote_map["144M"] = float(r)
        elif t_clean == "180M": quote_map["15Y"] = float(r)
        elif t_clean == "15Y": quote_map["180M"] = float(r)
        elif t_clean == "240M": quote_map["20Y"] = float(r)
        elif t_clean == "20Y": quote_map["240M"] = float(r)
        elif t_clean == "300M": quote_map["25Y"] = float(r)
        elif t_clean == "25Y": quote_map["300M"] = float(r)
        elif t_clean == "360M": quote_map["30Y"] = float(r)
        elif t_clean == "30Y": quote_map["360M"] = float(r)

    # Step 1: 시장에서 관찰되는 Tenor의 Par rate를 구함
    # quote_map contains market-observed par quotes for ON, 3M CD, 6M, 9M, 1Y, 18M, 2Y, ...

    def tenor_to_months(t: str) -> int:
        t = t.strip().upper()
        if t in ("ON", "TN", "SPOT"):
            return 0
        try:
            if t.endswith("M"):
                return int(t[:-1])
            if t.endswith("Y"):
                return int(t[:-1]) * 12
        except ValueError:
            return 0
        return 0

    # Interpolation anchors must come from what the feed actually delivered, not a fixed
    # tenor list: a live snapshot missing a tenor would otherwise fall back to the 3M CD
    # rate and corrupt every pillar beyond it.
    available_quoted_months = sorted({
        mm for mm in (tenor_to_months(k) for k in quote_map.keys()) if mm > 0
    })

    # Origin knot: Pricing Date (Today, DF=1.0)
    on_rate = quote_map.get("ON", 2.8042)
    dt_settle = (settle_date - pricing_date).days
    # Step 4 (ON factor): ON discount factor from Today to Settle (Spot T+1)
    df_settle = 1.0 / (1.0 + (on_rate / 100.0) * (dt_settle / 365.0))
    curve.df_settle = df_settle
    zero_on = -365.0 / dt_settle * math.log(df_settle) * 100.0 if dt_settle > 0 else on_rate

    # Register Today (Pricing Date) at index 0 for zero interpolation origin
    if dt_settle > 0:
        curve.mat_dates.append(pricing_date)
        curve.zero_rates.append(zero_on)
        curve.dfs.append(1.0)

    # 1. Settle Date DF & O/N Pillar (Spot Date T+1)
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

    # 2. 6M 미만 단기 필러 (1M, 2M, 3M CD, 4M, 5M)
    #
    # 예전에는 ON 과 3M CD 둘만 세우고 그 사이를 직선으로 이었습니다. 데스크가
    # O/N 부터 5M 까지 손으로 넣는 호가는 그래서 어디에도 쓰이지 않았습니다 -
    # 1M 부터 5M 까지 전부에 200bp 를 더해도 가격이 1원도 움직이지 않았습니다.
    # 월별 지급처럼 3개월 안쪽에 기간이 여러 개 들어가는 거래는 전부 그 직선
    # 위에서 계산됐습니다.
    #
    # 6M 부터의 분기 그리드는 여전히 3M 에서 출발합니다. 4M·5M 은 보간 매듭점으로만
    # 들어가고 스왓 부트스트래핑의 쿠폰 누적에는 끼지 않아, 6M 이상 필러는
    # 하나도 바뀜지 않습니다.
    cd_rate = quote_map.get("3M", 2.9700)
    mat_3m = dt_3m = df_3m = None
    for m in (1, 2, 3, 4, 5):
        if m != 3 and f"{m}M" not in quote_map:
            continue
        rate_m = quote_map.get(f"{m}M", cd_rate)
        mat_m = apply_krw_convention(add_months(settle_date, m),
                                     "Modified Following", holidays)
        # 영업일로 밀리다 앞 필러와 같은 날이 되면 둘 중 하나는 버려야
        # 합니다. 같은 날짜가 두 번 들어가면 보간이 0으로 나눔니다.
        if curve.mat_dates and mat_m <= curve.mat_dates[-1]:
            continue
        dt_m = (mat_m - settle_date).days
        days_pricing = (mat_m - pricing_date).days
        df_m = df_settle / (1.0 + (rate_m / 100.0) * (dt_m / 365.0))
        zero_m = (-365.0 / days_pricing * math.log(df_m) * 100.0
                  if days_pricing > 0 and df_m > 0 else rate_m)
        curve.pillars.append({"tenor": f"{m}M", "mat_date": mat_m, "rate": rate_m,
                              "df": df_m, "zero_rate": zero_m, "months": m})
        curve.mat_dates.append(mat_m)
        curve.zero_rates.append(zero_m)
        curve.dfs.append(df_m)
        if m == 3:
            mat_3m, dt_3m, df_3m = mat_m, dt_m, df_m

    # 3. Sequential 3M Quarterly Grid Bootstrapping (6M to 360M / 30Y)

    # Quarterly History: List of (mat_date, dt_quarter, df_quarter)
    quarterly_history = [(mat_3m, dt_3m, df_3m)]
    prev_mat = mat_3m
    
    # Quarter loop: m = 6, 9, 12, 15, 18, 21, ..., 360 (30 Years)
    for m in range(6, 361, 3):
        mat_m = apply_krw_convention(add_months(settle_date, m), "Modified Following", holidays)
        dt_m = (mat_m - prev_mat).days
        days_m_pricing = (mat_m - pricing_date).days
        
        # Step 2: 시장에서 관찰되는 Tenor의 Par rate를 Interpolation하여 coupon 발생 tenor의 Par rate 산출
        tenor_str = f"{m}M" if m < 12 or m % 12 != 0 else f"{m//12}Y"
        if tenor_str in quote_map or f"{m}M" in quote_map:
            rate_m = quote_map.get(tenor_str, quote_map.get(f"{m}M", cd_rate))
        elif not available_quoted_months:
            rate_m = cd_rate
        else:
            # Linear interpolation of Par Swap Rate between nearest *quoted* months.
            # Beyond the last quote both bounds collapse to it, giving flat extrapolation.
            lower_m = max([k for k in available_quoted_months if k < m], default=available_quoted_months[0])
            upper_m = min([k for k in available_quoted_months if k > m], default=available_quoted_months[-1])

            lower_str = f"{lower_m}M" if lower_m < 12 or lower_m % 12 != 0 else f"{lower_m//12}Y"
            upper_str = f"{upper_m}M" if upper_m < 12 or upper_m % 12 != 0 else f"{upper_m//12}Y"

            r_lower = quote_map.get(lower_str, quote_map.get(f"{lower_m}M", cd_rate))
            r_upper = quote_map.get(upper_str, quote_map.get(f"{upper_m}M", r_lower))

            if upper_m <= lower_m:
                rate_m = r_lower
            else:
                d_lower = apply_krw_convention(add_months(settle_date, lower_m), "Modified Following", holidays)
                d_upper = apply_krw_convention(add_months(settle_date, upper_m), "Modified Following", holidays)

                t_tot = (d_upper - d_lower).days
                t_cur = (mat_m - d_lower).days
                rate_m = r_lower + (r_upper - r_lower) * (t_cur / t_tot) if t_tot > 0 else r_lower

        # Step 3: Boot strapping을 통해 discount factor 산출 (Spot 기준)
        # Step 4: ON의 discount factor(df_settle)을 곱하여 Today 기준의 discount factor(df_m) 산출
        # DF_m = [1 - (Rate_m/100 / DF_settle) * SUM(dt_j/365 * DF_j)] / [1 + Rate_m/100 * (dt_m/365)] * DF_settle
        sum_pv_coupons = sum((dt / 365.0) * df for _, dt, df in quarterly_history)
        df_m = (1.0 - (sum_pv_coupons * (rate_m / 100.0) / df_settle)) / (1.0 + (rate_m / 100.0) * (dt_m / 365.0)) * df_settle
        
        # Step 5: 대표 tenor discount factor를 이용해 zero rate 산출 (Continuous Zero Rate from Today)
        zero_m = -365.0 / days_m_pricing * math.log(df_m) * 100.0 if days_m_pricing > 0 and df_m > 0 else rate_m
        
        quarterly_history.append((mat_m, dt_m, df_m))
        prev_mat = mat_m
        
        item_m = {
            "tenor": tenor_str,
            "mat_date": mat_m,
            "rate": rate_m,
            "df": df_m,
            "zero_rate": zero_m,
            "months": m
        }
        curve.pillars.append(item_m)
        curve.mat_dates.append(mat_m)
        curve.zero_rates.append(zero_m)
        curve.dfs.append(df_m)
        
    return curve
