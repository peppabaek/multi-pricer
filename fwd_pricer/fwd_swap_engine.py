"""
Forward Swap Point & FX Forward Pricing Engine
- Based on Reference Excel '삼중' Sheet & Murex CIP Pricing Models
- Workflow:
  1. Trader pastes/inputs Far Leg list: [Maturity, Notional USD, Margin bp]
  2. Pricer sets Near Leg to Spot Date (T+2 using SEB_NYB joint calendar)
  3. Computes Covered Interest Parity (CIP) Theoretical Forward Rate & Swap Point:
       F(T_far) = Spot_FX * (DF_USD(T_far) / DF_KRW(T_far)) * (DF_KRW(T_spot) / DF_USD(T_spot))
       SP_theo  = F(T_far) - Spot_FX  (in KRW / 원)
  4. Applies Margin (bp) from T+2 base:
       Swap_Margin = F(T_far) * ((T_far - T_spot)/365) / 10000 * Margin_bp
       SP_quote    = SP_theo - sign(Notional_USD) * Swap_Margin
       F_quote     = Spot_FX + SP_quote
  5. Computes FX Delta & Spot Hedge:
       FX_Delta_USD    = (Notional_USD * (DF_USD(T_far) / DF_USD(T_spot))) / Spot_FX
       Spot_Hedge_KRW  = -Spot_FX * FX_Delta_USD
  6. Outputs clean tabular summary for Trader to send to Marketer.
"""

import math
import datetime
import re
from typing import List, Dict, Any, Optional, Union

from server.calendar_manager import (
    parse_date,
    add_business_days,
    apply_convention,
    get_calendar_holidays
)
from crs_pricer.crs_curve_engine import KRWFXSOFRCurve
from sofr_pricer.curve_engine import SOFRCurve, bootstrap_sofr_curve

class FwdSwapPricer:
    def __init__(
        self,
        krw_fx_curve: KRWFXSOFRCurve,
        usd_sofr_curve: Optional[SOFRCurve] = None,
        spot_fx: float = 1357.85,
        pricing_date: Optional[datetime.date] = None,
        calendar: str = "SEB_NYB",
        kmbc_quotes: Optional[List[Dict[str, Any]]] = None
    ):
        self.pricing_date = pricing_date or krw_fx_curve.pricing_date
        self.spot_fx = spot_fx if spot_fx > 0 else krw_fx_curve.spot_fx
        self.calendar = calendar
        self.krw_fx_curve = krw_fx_curve
        
        # Spot Date: T+2 business days from pricing_date using joint calendar
        self.spot_date = add_business_days(self.pricing_date, 2, self.calendar)
        
        # USD SOFR Discount Curve
        if usd_sofr_curve:
            self.usd_sofr_curve = usd_sofr_curve
        else:
            self.usd_sofr_curve = bootstrap_sofr_curve(self.pricing_date, self.spot_date, quotes=[])
            
        # Discount factors at Spot Date (T+2)
        self.df_usd_spot = self.usd_sofr_curve.get_df(self.spot_date)
        self.df_krw_spot = self.krw_fx_curve.get_df(self.spot_date)
        if self.df_usd_spot <= 0: self.df_usd_spot = 1.0
        if self.df_krw_spot <= 0: self.df_krw_spot = 1.0

        # Build Hybrid Forward Curve (KMBC for <= 1Y, CIP Inverse DF for > 1Y)
        self.curve_nodes: List[Dict[str, Any]] = []
        self._build_hybrid_forward_curve(kmbc_quotes)

    def _build_hybrid_forward_curve(self, kmbc_quotes: Optional[List[Dict[str, Any]]] = None):
        """
        Builds the reference hybrid forward swap point curve matching KRWFXSOFR Sheet:
        1. Tenors <= 1Y: Uses live KMBC market swap points (in 전 -> converted to 원).
        2. Tenors > 1Y: Uses theoretical CIP inverse formula:
           SP(T) = ( (DF_USD(T) / DF_USD(T_spot)) * (DF_CRS(T_spot) / DF_CRS(T)) - 1 ) * Spot_FX
        """
        # 1. Map KMBC market quotes <= 1Y
        kmbc_map: Dict[str, float] = {}
        if kmbc_quotes:
            for q in kmbc_quotes:
                t = q.get("tenor", "").upper()
                if "mid_krw" in q and q["mid_krw"] is not None:
                    kmbc_map[t] = float(q["mid_krw"])
                elif "mid" in q and q["mid"] is not None:
                    # If mid is in 전 (e.g. -50.0), convert to KRW 원 (-0.50)
                    kmbc_map[t] = float(q["mid"]) / 100.0 if q.get("type") == "Outright" else float(q["mid"])

        # Default fallbacks if KMBC quotes missing
        default_kmbc_krw = {
            "1W": -0.14,
            "2W": -0.25,
            "1M": -0.50,
            "2M": -1.20,
            "3M": -2.00,
            "6M": -4.70,
            "9M": -7.00,
            "1Y": -9.20
        }

        short_tenors = ["1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y"]
        for t in short_tenors:
            mat_dt = self.parse_maturity_date(t)
            days = max(1, (mat_dt - self.spot_date).days)
            sp_val = kmbc_map.get(t, default_kmbc_krw.get(t, -0.01 * days))
            self.curve_nodes.append({
                "tenor": t,
                "maturity": mat_dt,
                "days": days,
                "sp_krw": sp_val,
                "sp_jeon": sp_val * 100.0,
                "source": "KMBC_Market"
            })

        # 2. Benchmark Tenors > 1Y (Calculated via USD SOFR DF and KRW CRS DF)
        long_benchmark_tenors = ["18M", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y", "20Y"]
        for t in long_benchmark_tenors:
            mat_dt = self.parse_maturity_date(t)
            days = (mat_dt - self.spot_date).days
            df_u = self.usd_sofr_curve.get_df(mat_dt)
            df_c = self.krw_fx_curve.get_df(mat_dt)
            if df_u <= 0: df_u = 1.0
            if df_c <= 0: df_c = 1.0
            
            # Reference Formula: =(P_row/$L$1*$R$4/R_row - 1)*$M$1*100 (in 전 -> /100 in 원)
            sp_calc_krw = ((df_u / self.df_usd_spot) * (self.df_krw_spot / df_c) - 1.0) * self.spot_fx
            
            self.curve_nodes.append({
                "tenor": t,
                "maturity": mat_dt,
                "days": days,
                "sp_krw": sp_calc_krw,
                "sp_jeon": sp_calc_krw * 100.0,
                "source": "CIP_Inverse_DF"
            })

        # Sort all nodes by days from spot
        self.curve_nodes.sort(key=lambda x: x["days"])

    def get_interpolated_swap_point(self, target_mat: datetime.date) -> float:
        """
        Interpolates Swap Point (in KRW 원) for any Far Leg maturity date:
        - Tenors <= 1Y: linearly interpolated between adjacent KMBC market nodes.
        - Tenors > 1Y: linearly interpolated between adjacent benchmark CIP inverse nodes (=linterp in Excel).
        """
        n_days = (target_mat - self.spot_date).days
        if n_days <= 0:
            return 0.0

        if not self.curve_nodes:
            # Fallback pure CIP
            df_u = self.usd_sofr_curve.get_df(target_mat)
            df_c = self.krw_fx_curve.get_df(target_mat)
            return ((df_u / self.df_usd_spot) * (self.df_krw_spot / df_c) - 1.0) * self.spot_fx

        # If before first node
        if n_days <= self.curve_nodes[0]["days"]:
            first = self.curve_nodes[0]
            return first["sp_krw"] * (n_days / first["days"])

        # If after last node
        if n_days >= self.curve_nodes[-1]["days"]:
            last = self.curve_nodes[-1]
            prev = self.curve_nodes[-2]
            slope = (last["sp_krw"] - prev["sp_krw"]) / (last["days"] - prev["days"])
            return last["sp_krw"] + slope * (n_days - last["days"])

        # Find bracket [node_i, node_{i+1}]
        for i in range(len(self.curve_nodes) - 1):
            n1 = self.curve_nodes[i]
            n2 = self.curve_nodes[i + 1]
            if n1["days"] <= n_days <= n2["days"]:
                denom = (n2["days"] - n1["days"])
                if denom == 0:
                    return n1["sp_krw"]
                alpha = (n_days - n1["days"]) / denom
                return n1["sp_krw"] + alpha * (n2["sp_krw"] - n1["sp_krw"])

        return self.curve_nodes[-1]["sp_krw"]

    def parse_maturity_date(self, mat_val: Union[str, datetime.date, datetime.datetime]) -> datetime.date:
        """Parse date string, excel serial, or tenor string (e.g. '3M', '1Y', '2026-12-15')"""
        if isinstance(mat_val, (datetime.date, datetime.datetime)):
            raw_dt = mat_val if isinstance(mat_val, datetime.date) else mat_val.date()
            return apply_convention(raw_dt, "Modified Following", self.calendar)
            
        s = str(mat_val).strip()
        
        # Check standard date formats YYYY-MM-DD or YYYY/MM/DD or YYYYMMDD
        date_match = re.match(r"^(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})$", s)
        if date_match:
            y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
            raw_dt = datetime.date(y, m, d)
            return apply_convention(raw_dt, "Modified Following", self.calendar)
            
        # Check Tenor string (e.g. '1M', '3M', '6M', '1Y', '2Y', '1W', '2W')
        tenor_match = re.match(r"^(\d+)\s*([DWEMYdwemy])$", s)
        if tenor_match:
            num = int(tenor_match.group(1))
            unit = tenor_match.group(2).upper()
            base_dt = self.spot_date
            if unit == 'D':
                target = base_dt + datetime.timedelta(days=num)
            elif unit == 'W':
                target = base_dt + datetime.timedelta(weeks=num)
            elif unit == 'M':
                # Add num months
                total_months = base_dt.month + num
                new_y = base_dt.year + (total_months - 1) // 12
                new_m = ((total_months - 1) % 12) + 1
                new_d = min(base_dt.day, 28)
                target = datetime.date(new_y, new_m, new_d)
            elif unit == 'Y':
                target = datetime.date(base_dt.year + num, base_dt.month, min(base_dt.day, 28))
            else:
                target = base_dt + datetime.timedelta(days=30 * num)
            return apply_convention(target, "Modified Following", self.calendar)
            
        # Fallback parse
        try:
            return apply_convention(parse_date(s), "Modified Following", self.calendar)
        except Exception:
            # Default to 3M from spot
            return add_business_days(self.spot_date, 60, self.calendar)

    def price_single_leg(
        self,
        maturity: Union[str, datetime.date],
        notional_usd: float,
        margin_bp: float = 0.0,
        leg_id: int = 1
    ) -> Dict[str, Any]:
        """Price a single Far Leg forward contract matching Reference Sheet formulas"""
        adj_mat = self.parse_maturity_date(maturity)
        raw_mat_str = maturity.strftime("%Y-%m-%d") if isinstance(maturity, (datetime.date, datetime.datetime)) else str(maturity).strip()
        
        # 1. Discount Factors
        df_usd = self.usd_sofr_curve.get_df(adj_mat)
        df_krw = self.krw_fx_curve.get_df(adj_mat)
        if df_krw <= 0: df_krw = 1.0
        if df_usd <= 0: df_usd = 1.0
        
        # 2. Theoretical Swap Point from Hybrid Curve (KMBC for <= 1Y, CIP Inverse for > 1Y)
        sp_theo = self.get_interpolated_swap_point(adj_mat) # in KRW / 원
        fwd_theo = self.spot_fx + sp_theo
        
        # 3. Year Fraction from Spot Date (T+2)
        days_from_spot = max(0, (adj_mat - self.spot_date).days)
        tau = days_from_spot / 365.0
        
        # 4. Swap Margin (bp rule: Fwd_theo * (days / 365) / 10000 * margin_bp)
        swap_margin = fwd_theo * tau / 10000.0 * float(margin_bp)
        
        # 5. Quoted Swap Point & Quoted Forward Rate (with Margin applied)
        sign_notional = 1.0 if notional_usd >= 0 else -1.0
        sp_quote = sp_theo - sign_notional * swap_margin
        fwd_quote = self.spot_fx + sp_quote
        
        # 6. Notional in KRW
        notional_krw = -notional_usd * fwd_quote
        
        # 7. FX Delta (USD) & Spot Hedge Amount (KRW)
        # FX Delta = (Notional_USD * (DF_USD(T_far) / DF_USD(T_spot))) / Spot_FX
        fx_delta_usd = (notional_usd * (df_usd / self.df_usd_spot)) / self.spot_fx
        spot_hedge_krw = -self.spot_fx * fx_delta_usd
        
        # 8. Sales Margin Amount (KRW)
        sales_margin_krw = abs(notional_usd) * df_krw * swap_margin
        
        # 9. Key Rate DV01s (1bp curve sensitivity)
        dv01_usd = -tau * df_usd * notional_usd / 10000.0
        dv01_krw = -tau * df_krw * notional_krw / 10000.0
        
        return {
            "leg_id": leg_id,
            "raw_maturity": raw_mat_str,
            "maturity": adj_mat.strftime("%Y-%m-%d"),
            "days_from_spot": days_from_spot,
            "tau": tau,
            "notional_usd": notional_usd,
            "notional_krw": notional_krw,
            "df_usd": df_usd,
            "df_krw": df_krw,
            "fwd_theo": fwd_theo,
            "sp_theo": sp_theo,
            "margin_bp": margin_bp,
            "swap_margin": swap_margin,
            "sp_quote": sp_quote,
            "fwd_quote": fwd_quote,
            "fx_delta_usd": fx_delta_usd,
            "spot_hedge_krw": spot_hedge_krw,
            "sales_margin_krw": sales_margin_krw,
            "dv01_usd": dv01_usd,
            "dv01_krw": dv01_krw
        }

    def price_portfolio(
        self,
        far_legs: List[Dict[str, Any]],
        default_margin_bp: float = 0.0
    ) -> Dict[str, Any]:
        """Price multiple Far Legs pasted from Excel by Trader"""
        priced_legs: List[Dict[str, Any]] = []
        
        tot_notional_usd = 0.0
        tot_notional_krw = 0.0
        tot_fx_delta_usd = 0.0
        tot_spot_hedge_krw = 0.0
        tot_sales_margin_krw = 0.0
        
        weighted_sp_sum = 0.0
        weighted_sp_theo_sum = 0.0
        abs_notional_sum = 0.0
        
        # Pillar bucketing for Zero Delta (0.25Y ~ 10Y)
        pillars = [0.25, 0.5, 0.75, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        pillar_labels = ["3M", "6M", "9M", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y"]
        usd_sofr_deltas = [0.0] * len(pillars)
        krw_fx_deltas = [0.0] * len(pillars)
        
        for idx, item in enumerate(far_legs, start=1):
            mat = item.get("maturity", "")
            if not mat:
                continue
                
            notional = float(item.get("notional_usd", 0.0))
            if notional == 0.0:
                continue
                
            m_bp = float(item["margin_bp"]) if (item.get("margin_bp") is not None and item.get("margin_bp") != "") else float(default_margin_bp)
            
            leg_res = self.price_single_leg(mat, notional, m_bp, leg_id=idx)
            priced_legs.append(leg_res)
            
            # Aggregate totals
            tot_notional_usd += notional
            tot_notional_krw += leg_res["notional_krw"]
            tot_fx_delta_usd += leg_res["fx_delta_usd"]
            tot_spot_hedge_krw += leg_res["spot_hedge_krw"]
            tot_sales_margin_krw += leg_res["sales_margin_krw"]
            
            abs_n = abs(notional)
            abs_notional_sum += abs_n
            weighted_sp_sum += abs_n * leg_res["sp_quote"]
            weighted_sp_theo_sum += abs_n * leg_res["sp_theo"]
            
            # Map DV01 to nearest pillar
            tau = leg_res["tau"]
            best_idx = 0
            best_diff = 999.0
            for p_i, p_val in enumerate(pillars):
                diff = abs(tau - p_val)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = p_i
            usd_sofr_deltas[best_idx] += leg_res["dv01_usd"]
            krw_fx_deltas[best_idx] += leg_res["dv01_krw"]
            
        weighted_avg_sp = (weighted_sp_sum / abs_notional_sum) if abs_notional_sum > 0 else 0.0
        weighted_avg_theo_sp = (weighted_sp_theo_sum / abs_notional_sum) if abs_notional_sum > 0 else 0.0
        weighted_avg_margin_sp = weighted_avg_theo_sp - weighted_avg_sp
        
        # Zero Delta Bucketing List
        zero_delta_bucketing = []
        for p_lbl, p_val, u_d, k_d in zip(pillar_labels, pillars, usd_sofr_deltas, krw_fx_deltas):
            zero_delta_bucketing.append({
                "tenor": p_lbl,
                "pillar_year": p_val,
                "usd_sofr_dv01": round(u_d, 2),
                "krw_fx_dv01": round(k_d, 2),
                "total_dv01": round(u_d + k_d / self.spot_fx, 2)
            })
            
        return {
            "pricing_date": self.pricing_date.strftime("%Y-%m-%d"),
            "spot_date": self.spot_date.strftime("%Y-%m-%d"),
            "spot_fx": self.spot_fx,
            "calendar": self.calendar,
            "default_margin_bp": default_margin_bp,
            "df_usd_spot": self.df_usd_spot,
            "df_krw_spot": self.df_krw_spot,
            "total_count": len(priced_legs),
            "total_notional_usd": tot_notional_usd,
            "total_notional_krw": tot_notional_krw,
            "total_fx_delta_usd": tot_fx_delta_usd,
            "total_spot_hedge_krw": tot_spot_hedge_krw,
            "total_sales_margin_krw": tot_sales_margin_krw,
            "weighted_avg_sp": weighted_avg_sp,
            "weighted_avg_theo_sp": weighted_avg_theo_sp,
            "weighted_avg_margin_sp": weighted_avg_margin_sp,
            "legs": priced_legs,
            "zero_delta_bucketing": zero_delta_bucketing
        }

def parse_trader_paste_text(raw_text: str, default_margin_bp: float = 1.0) -> List[Dict[str, Any]]:
    """
    Parse text copied from Excel containing:
    1. Two columns: [Maturity, Notional USD]
    or
    2. Three columns: [Maturity, Notional USD, Margin bp]
    """
    results: List[Dict[str, Any]] = []
    if not raw_text or not raw_text.strip():
        return results
        
    lines = raw_text.strip().splitlines()
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
            
        # Excel copy is tab-separated (\t). Also support pipe (|), semicolon (;), or multi-spaces
        if "\t" in cleaned:
            parts = [p.strip() for p in cleaned.split("\t") if p.strip()]
        elif "|" in cleaned:
            parts = [p.strip() for p in cleaned.split("|") if p.strip()]
        elif ";" in cleaned:
            parts = [p.strip() for p in cleaned.split(";") if p.strip()]
        else:
            # Split by 2 or more spaces or single space if line has 2 tokens
            parts = [p.strip() for p in re.split(r"\s{2,}|\s+", cleaned) if p.strip()]
            
        if len(parts) < 2:
            continue
                
        # Skip header rows if present
        if any(h in parts[0].lower() for h in ["mat", "date", "만기", "tenor", "no"]):
            continue
            
        mat_str = parts[0].strip()
        
        # Parse notional (remove $, commas, M, k, etc.)
        notional_str = parts[1].strip().replace("$", "").replace(",", "").replace(" ", "")
        multiplier = 1.0
        if notional_str.endswith("M") or notional_str.endswith("m"):
            multiplier = 1_000_000.0
            notional_str = notional_str[:-1]
        elif notional_str.endswith("K") or notional_str.endswith("k"):
            multiplier = 1_000.0
            notional_str = notional_str[:-1]
        elif notional_str.endswith("B") or notional_str.endswith("b"):
            multiplier = 1_000_000_000.0
            notional_str = notional_str[:-1]
            
        try:
            notional_usd = float(notional_str) * multiplier
        except ValueError:
            continue
            
        # Margin bp (optional third column)
        margin_bp = default_margin_bp
        if len(parts) >= 3:
            try:
                m_str = parts[2].strip().replace("bp", "").replace("%", "")
                margin_bp = float(m_str)
            except ValueError:
                margin_bp = default_margin_bp
                
        results.append({
            "maturity": mat_str,
            "notional_usd": notional_usd,
            "margin_bp": margin_bp
        })
        
    return results

def price_forward_portfolio(
    krw_fx_curve: KRWFXSOFRCurve,
    usd_sofr_curve: Optional[SOFRCurve] = None,
    spot_fx: float = 1373.50,
    far_legs: Optional[List[Dict[str, Any]]] = None,
    default_margin_bp: float = 1.0,
    pricing_date: Optional[datetime.date] = None,
    calendar: str = "SEB_NYB"
) -> Dict[str, Any]:
    pricer = FwdSwapPricer(
        krw_fx_curve=krw_fx_curve,
        usd_sofr_curve=usd_sofr_curve,
        spot_fx=spot_fx,
        pricing_date=pricing_date,
        calendar=calendar
    )
    if not far_legs:
        # Provide sample default 3-tranche portfolio if empty
        far_legs = [
            {"maturity": "2026-12-15", "notional_usd": 1_648_000.0, "margin_bp": default_margin_bp},
            {"maturity": "2027-03-15", "notional_usd": 5_000_000.0, "margin_bp": default_margin_bp},
            {"maturity": "2027-06-15", "notional_usd": 3_500_000.0, "margin_bp": default_margin_bp}
        ]
    return pricer.price_portfolio(far_legs, default_margin_bp=default_margin_bp)
