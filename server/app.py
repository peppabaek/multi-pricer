"""
FastAPI Server for USD SOFR and KRW CD 91D IRS Live Pricer Dashboard
Exposes On-Demand Snapshot, Dual-Leg Pricing, Custom Schedule Customization, and Quote Override REST APIs
"""

import os
import json
import re
import sys
import datetime
import time
import asyncio
import warnings
from typing import Dict, Any, Optional, List, Tuple

# Suppress Eikon library internal pandas FutureWarning
warnings.filterwarnings("ignore", category=FutureWarning)

# Suppress benign Windows asyncio ConnectionResetError (WinError 10054) on abrupt client socket close
if sys.platform == "win32":
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
        _orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost
        def _patched_call_connection_lost(self, exc=None):
            try:
                _orig_call_connection_lost(self, exc)
            except ConnectionResetError:
                pass
            except OSError as e:
                if getattr(e, "winerror", None) == 10054:
                    pass
                else:
                    raise
        _ProactorBasePipeTransport._call_connection_lost = _patched_call_connection_lost
    except Exception:
        pass

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
from server import relay
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser

# Keep uploaded termsheets in memory. Starlette spools multipart bodies to a temp file
# above 1 MB by default, which would leave the document on disk.
MultiPartParser.spool_max_size = 32 * 1024 * 1024

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Common Rollercoaster & Smart Excel Schedule Engine
from common_pricer.rollercoaster_engine import parse_rollercoaster_paste

# USD SOFR Engines
from sofr_pricer import (
    parse_date, apply_convention, add_business_days,
    bootstrap_sofr_curve, bootstrap_advanced_sofr_curve,
    USDSOFRSwapPricer, SOFRCurve, AdvancedSOFRCurve,
    CompositeSOFRCurve, create_hedge_composite_curve
)
from server.tradition_feed import tradition_feed

# KRW CD 91D Engines
from krw_pricer import (
    get_krw_spot_date, apply_krw_convention,
    bootstrap_krw_curve, KRWSwapPricer, KRWCurve
)
from server.krw_feed import krw_feed

# KRW KOFR OIS Engines
from kofr_pricer import (
    get_spot_date as get_kofr_spot_date, apply_kofr_convention,
    bootstrap_kofr_curve, KOFRSwapPricer, KOFRCurve
)
from server.kofr_feed import kofr_feed

# KRW FX SOFR (CRS) Engines
from crs_pricer import (
    get_crs_spot_date, apply_crs_convention,
    bootstrap_crs_curve, KRWFXSOFRSwapPricer, KRWFXSOFRCurve
)
from server.crs_feed import crs_feed

# KMBC FX Forward & Swap Point Feed
from server.kmbc_fwd_feed import kmbc_fwd_feed_instance as kmbc_fwd_feed

# Forward Swap Point Engine
from fwd_pricer.fwd_swap_engine import FwdSwapPricer, parse_trader_paste_text

app = FastAPI(title="Multi-Currency (USD SOFR / KRW CD / KRW KOFR / KRW CRS / FX FWD) Live Pricer Dashboard")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FwdPricingRequest(BaseModel):
    spot_fx: Optional[float] = None
    default_margin_bp: Optional[float] = 1.0
    pricing_date: Optional[str] = None
    calendar: Optional[str] = "SEB_NYB"
    raw_paste_text: Optional[str] = None
    far_legs: Optional[List[Dict[str, Any]]] = None

class PricingRequest(BaseModel):
    currency: Optional[str] = "USD" # "USD", "KRW", "KRW_KOFR", "KRW_CRS"
    notional: float = 100_000_000.0
    usd_notional: Optional[float] = None
    krw_notional: Optional[float] = None
    spot_fx: Optional[float] = None
    position: str = "Pay Fixed" # "Pay Fixed" or "Rec Fixed"
    fixed_coupon_pct: Optional[float] = None
    spread_bp: float = 0.0
    tenor: str = "5Y"
    
    # Curve Model Selection (USD SOFR only & CRS USD OIS)
    curve_type: Optional[str] = "Standard" # "Standard" or "Advanced"
    
    # CRS Specific
    crs_swap_type: Optional[str] = "Vanilla" # "Vanilla" or "Fixed-Fixed"
    usd_fixed_coupon_pct: Optional[float] = None # For Fixed-Fixed CRS USD Leg
    
    # Advanced Parametric Selection Fields (Legacy / Unified Fallback)
    day_count: Optional[str] = None # "Act/365", "Act/360", "30/360", "Act/Act"
    fix_cal: Optional[str] = None   # "SEB", "LNB", "NYB", "TKB", "SEB_NYB", "TGT", etc.
    pay_cal: Optional[str] = None   # "SEB", "LNB", "NYB", "TKB", "SEB_NYB", "TGT", etc.
    payment_freq: Optional[str] = None # "1M", "3M", "6M", "12M"
    frequency_months: Optional[int] = None
    business_day_conv: Optional[str] = None # "Modified Following", "Following", "Preceding"
    stub_rule: Optional[str] = None # "Short in arrears", "Short upfront", "Long in arrears", "Long upfront"
    adjust_rule: Optional[str] = None # "Adjust", "Unadjust"
    fix_day: Optional[int] = None # e.g. -1, -2, 0

    # Independent Leg 1 (Fixed / KRW) Parameters
    leg1_day_count: Optional[str] = None
    leg1_payment_freq: Optional[str] = None
    leg1_frequency_months: Optional[int] = None
    leg1_business_day_conv: Optional[str] = None
    leg1_stub_rule: Optional[str] = None
    leg1_adjust_rule: Optional[str] = None
    leg1_calendar: Optional[str] = None

    # Independent Leg 2 (Floating / USD) Parameters
    leg2_day_count: Optional[str] = None
    leg2_payment_freq: Optional[str] = None
    leg2_frequency_months: Optional[int] = None
    leg2_business_day_conv: Optional[str] = None
    leg2_stub_rule: Optional[str] = None
    leg2_adjust_rule: Optional[str] = None
    leg2_calendar: Optional[str] = None
    leg2_fix_day: Optional[int] = None
    
    payment_lag_bd: Optional[int] = None
    effective_date: Optional[str] = None
    maturity_date: Optional[str] = None
    pricing_date: Optional[str] = None
    settle_date: Optional[str] = None
    custom_schedule: Optional[List[Dict[str, Any]]] = None
    leg1_custom_schedule: Optional[List[Dict[str, Any]]] = None
    leg2_custom_schedule: Optional[List[Dict[str, Any]]] = None
    raw_paste_text: Optional[str] = None
    leg1_raw_paste_text: Optional[str] = None
    leg2_raw_paste_text: Optional[str] = None

class RollercoasterParseRequest(BaseModel):
    raw_paste_text: Optional[str] = None
    leg1_raw_paste_text: Optional[str] = None
    leg2_raw_paste_text: Optional[str] = None
    currency: Optional[str] = "USD"
    effective_date: Optional[str] = None
    notional: Optional[float] = 100_000_000.0
    fixed_coupon_pct: Optional[float] = 0.0
    spread_bp: Optional[float] = 0.0

_TENOR_RE = re.compile(r"^\d+(?:\.\d+)?\s*[MY]$", re.IGNORECASE)


def _parse_date_arg(label: str, value: Optional[str]) -> Optional[datetime.date]:
    if not value:
        return None
    try:
        return parse_date(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{label} '{value}' is not a valid YYYY-MM-DD date")


def _validate_pricing_request(req: PricingRequest) -> None:
    """Reject trades that would otherwise be priced silently against the wrong terms."""
    eff = _parse_date_arg("effective_date", req.effective_date)
    mat = _parse_date_arg("maturity_date", req.maturity_date)
    _parse_date_arg("pricing_date", req.pricing_date)
    _parse_date_arg("settle_date", req.settle_date)

    if mat is not None and eff is not None and mat <= eff:
        raise HTTPException(
            status_code=400,
            detail=f"maturity_date {req.maturity_date} must be after effective_date {req.effective_date}"
        )

    if mat is None:
        tenor = (req.tenor or "").strip()
        if not _TENOR_RE.match(tenor):
            raise HTTPException(
                status_code=400,
                detail=f"Unrecognised tenor '{req.tenor}'. Use a form like 3M, 18M or 5Y, "
                       f"or supply maturity_date instead."
            )

    for label, val in (("notional", req.notional),
                       ("usd_notional", req.usd_notional),
                       ("krw_notional", req.krw_notional)):
        if val is not None and val <= 0:
            raise HTTPException(status_code=400, detail=f"{label} must be greater than zero (got {val})")

    if req.spot_fx is not None and req.spot_fx <= 0:
        raise HTTPException(status_code=400, detail=f"spot_fx must be greater than zero (got {req.spot_fx})")


def _resolve_freq_months(freq_str: Optional[str], freq_months: Optional[int], default_months: int) -> int:
    if freq_months and freq_months > 0:
        return freq_months
    if freq_str:
        s = freq_str.strip().upper()
        if "12" in s or "1Y" in s:
            return 12
        elif "6" in s:
            return 6
        elif "3" in s:
            return 3
        elif "1" in s:
            return 1
    return default_months

def _resolve_custom_schedules(
    req: PricingRequest,
    eff_date: datetime.date,
    default_notional: float,
    default_coupon: float,
    default_spread: float,
    currency: str
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]]]:
    leg1_sched = req.leg1_custom_schedule
    leg2_sched = req.leg2_custom_schedule
    
    # Check Leg 1 paste
    if req.leg1_raw_paste_text and req.leg1_raw_paste_text.strip():
        p1 = parse_rollercoaster_paste(
            raw_text=req.leg1_raw_paste_text,
            effective_date=eff_date,
            default_notional=default_notional,
            default_coupon_pct=default_coupon,
            default_spread_bp=default_spread,
            currency=currency
        )
        if p1:
            leg1_sched = p1
            
    # Check Leg 2 paste
    if req.leg2_raw_paste_text and req.leg2_raw_paste_text.strip():
        p2 = parse_rollercoaster_paste(
            raw_text=req.leg2_raw_paste_text,
            effective_date=eff_date,
            default_notional=default_notional,
            default_coupon_pct=default_coupon,
            default_spread_bp=default_spread,
            currency=currency
        )
        if p2:
            leg2_sched = p2

    # Fallback to legacy single paste or custom_schedule if neither leg1 nor leg2 is set
    if not leg1_sched and not leg2_sched:
        if req.raw_paste_text and req.raw_paste_text.strip():
            p_common = parse_rollercoaster_paste(
                raw_text=req.raw_paste_text,
                effective_date=eff_date,
                default_notional=default_notional,
                default_coupon_pct=default_coupon,
                default_spread_bp=default_spread,
                currency=currency
            )
            if p_common:
                leg1_sched = p_common
                leg2_sched = p_common
        elif req.custom_schedule:
            leg1_sched = req.custom_schedule
            leg2_sched = req.custom_schedule

    return leg1_sched, leg2_sched

class QuoteUpdateRequest(BaseModel):
    tenor: str
    mid: float
    bid: Optional[float] = None
    ask: Optional[float] = None

class AppKeyRequest(BaseModel):
    app_key: str

@app.get("/api/lseg/status")
def lseg_status():
    """
    What the Key dialog shows: whether a key is configured, whether the Workspace
    proxy is actually listening, and whether quotes are arriving.

    The dialog used to print a fixed line saying the proxy was running, which was
    true only by coincidence - the same way the LIVE badge was. Never returns the
    key itself, only enough of it to recognise which one is loaded.
    """
    from server.eikon_rate_limiter import workspace_listening

    cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                            "lseg_config.json"))
    key, port, source = "", 9000, None
    if os.path.exists(cfg_path):
        source = "lseg_config.json"
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            key = cfg.get("lseg_app_key") or cfg.get("app_key") or ""
            port = int(cfg.get("port", 9000) or 9000)
        except Exception as e:
            source = f"lseg_config.json (읽기 실패: {e})"

    configured = bool(key) and key != "YOUR_APP_KEY" and key != "YOUR_LSEG_WORKSPACE_APP_KEY"
    snap = tradition_feed.get_snapshot()
    quotes = snap.get("quotes") or []
    live = bool(snap.get("is_live_connected"))

    # 호스팅 인스턴스에는 Workspace 가 있을 수 없다. 거기서 "Workspace 미실행" 은
    # 고칠 수 없는 것을 고치라는 말이라, 실제로 해야 할 일을 가린다 - 데스크
    # 중계를 띄우는 것이다.
    from server import relay as _relay
    from server.access import is_hosted
    rly = _relay.status("USD")
    if rly.get("active"):
        verdict = _relay.describe("USD")
    elif is_hosted() or os.environ.get("PRICER_NO_LOCAL_FEED"):
        verdict = ("이 서버에는 Workspace 가 없습니다 — 데스크 PC 에서 "
                   "tools/desk_relay.py 를 실행하면 호가가 들어옵니다")
    elif not configured:
        verdict = "App Key 미설정 — Workspace 에서 APPKEY 로 발급해 입력하세요"
    elif not workspace_listening(port):
        verdict = f"App Key 있음 · Workspace 미실행 (127.0.0.1:{port} 응답 없음)"
    elif live:
        verdict = f"연동됨 — 실시간 호가 {len(quotes)}건 수신 중"
    else:
        verdict = "App Key 있음 · Workspace 실행 중 · 아직 호가를 받지 못함 (F5 로 조회)"

    return {"status": "success", "data": {
        "configured": configured,
        # Enough to tell which key is loaded, never enough to use it.
        "key_hint": (key[:4] + "…" + key[-4:]) if configured and len(key) > 10 else "",
        "key_source": source,
        "port": port,
        "port_open": workspace_listening(port),
        "is_live_connected": live,
        "quote_count": len(quotes),
        "last_update": snap.get("timestamp"),
        "feed_source": snap.get("source"),
        "verdict": verdict,
        "relay": rly,
        "hosted": bool(is_hosted() or os.environ.get("PRICER_NO_LOCAL_FEED")),
    }}


@app.post("/api/lseg/set-app-key")
def set_lseg_app_key(req: AppKeyRequest):
    """Register LSEG Workspace App Key and connect to Desktop proxy"""
    success, msg = tradition_feed.set_app_key(req.app_key)
    krw_feed._app_key = req.app_key
    krw_feed._ek_initialized = False
    krw_feed.trigger_on_demand_refresh()
    return {
        "status": "success" if success else "failed",
        "is_connected": tradition_feed.is_lseg_live_connected,
        "message": msg
    }

# ==============================================================================
# USD SOFR ENDPOINTS
# ==============================================================================

def _build_usd_curve(snapshot: Dict[str, Any], p_date_str: Optional[str] = None, s_date_str: Optional[str] = None, curve_type: Optional[str] = "Standard"):
    today = datetime.date.today()
    pricing_date = parse_date(p_date_str) if p_date_str else today
    settle_date = parse_date(s_date_str) if s_date_str else add_business_days(pricing_date, 2)
    
    quote_tuples = []
    for q in snapshot["quotes"]:
        quote_tuples.append((q["tenor"], float(q["mid"])))
        
    c_type = (curve_type or "").strip().lower()
    if c_type in ("hedgecurve", "hedge_curve", "hedge"):
        adv = bootstrap_advanced_sofr_curve(pricing_date, settle_date, quote_tuples)
        curve = CompositeSOFRCurve(adv)
    elif c_type == "advanced":
        curve = bootstrap_advanced_sofr_curve(pricing_date, settle_date, quote_tuples)
    else:
        curve = bootstrap_sofr_curve(pricing_date, settle_date, quote_tuples)
    return curve

# Which feeds have pulled live quotes at least once in this process.
_WARMED: set = set()


def _warm_once(name: str, feed) -> None:
    """
    Pull live quotes the first time a currency is asked for.

    Each feed starts on its baseline quotes and only goes live on an explicit reload,
    so opening the dashboard showed BASE with yesterday's numbers until someone
    pressed F5 - which reads as "not connected" even with Workspace running right
    there. One fetch per currency per process, and only when Workspace is actually
    listening, so a desk without it pays nothing and a host never tries.
    """
    if name in _WARMED:
        return
    _WARMED.add(name)          # 실패해도 매 요청마다 재시도하지 않는다
    try:
        from server.eikon_rate_limiter import workspace_listening
        if workspace_listening():
            feed.trigger_on_demand_refresh()
    except Exception as e:
        print(f"[Market] {name} first fetch failed: {e}")


@app.get("/api/market-snapshot")
def get_market_snapshot(pricing_date: Optional[str] = None, settle_date: Optional[str] = None, curve_type: Optional[str] = "Standard", reload: Optional[bool] = False):
    """[USD] Get immutable market data snapshot and bootstrapped curve (<0.1ms)"""
    if reload:
        tradition_feed.trigger_on_demand_refresh()
    else:
        _warm_once("usd", tradition_feed)
    snapshot = tradition_feed.get_snapshot()
    curve = _build_usd_curve(snapshot, pricing_date, settle_date, curve_type)
    
    bootstrapped_curve = []
    for p in curve.pillars:
        bootstrapped_curve.append({
            "tenor": p["tenor"],
            "mat_date": p["mat_date"].strftime("%Y-%m-%d"),
            "par_rate": round(p["rate"], 4),
            "df": round(p["df"], 6),
            "zero_rate": round(p["zero_rate"], 4)
        })

    return {
        "status": "success",
        "data": {
            "currency": "USD",
            "relay": relay.status("USD"),
            "source": snapshot["source"],
            "status_message": snapshot.get("status_message", "Live"),
            "is_live_connected": snapshot.get("is_live_connected", False),
            "has_app_key": snapshot.get("has_app_key", False),
            "timestamp": snapshot["timestamp"],
            "epoch_ms": snapshot["epoch_ms"],
            "pricing_date": curve.pricing_date.strftime("%Y-%m-%d"),
            "settle_date": curve.settle_date.strftime("%Y-%m-%d"),
            "quotes": snapshot["quotes"],
            "curve_pillars": bootstrapped_curve,
            "curve_type": curve_type or "Standard"
        }
    }

@app.post("/api/price")
def calculate_pricing(req: PricingRequest):
    """[USD] Calculate Par Swap Rate, NPV, DV01, and Dual-Leg Schedule (Auto or Custom Pasted)"""
    _validate_pricing_request(req)
    try:
        snapshot = tradition_feed.get_snapshot()
        curve = _build_usd_curve(snapshot, req.pricing_date, req.settle_date, req.curve_type)
        pricer = USDSOFRSwapPricer(curve)
        
        eff_date = parse_date(req.effective_date) if req.effective_date else None
        mat_date = parse_date(req.maturity_date) if req.maturity_date else None
        l1_freq = _resolve_freq_months(req.leg1_payment_freq or req.payment_freq, req.leg1_frequency_months or req.frequency_months, 12)
        l2_freq = _resolve_freq_months(req.leg2_payment_freq or req.payment_freq, req.leg2_frequency_months or req.frequency_months, 12)
        
        eff_for_rc = eff_date or (curve.settle_date if hasattr(curve, "settle_date") else datetime.date.today())
        leg1_sched, leg2_sched = _resolve_custom_schedules(
            req=req,
            eff_date=eff_for_rc,
            default_notional=req.notional if req.notional > 0 else 100_000_000.0,
            default_coupon=req.fixed_coupon_pct or 0.0,
            default_spread=req.spread_bp or 0.0,
            currency="USD"
        )

        result = pricer.price_swap(
            notional=req.notional,
            position=req.position,
            fixed_coupon_pct=req.fixed_coupon_pct,
            spread_bp=req.spread_bp,
            effective_date=eff_date,
            maturity_date=mat_date,
            tenor_str=req.tenor,
            frequency_months=l1_freq,
            day_count=req.leg1_day_count or req.day_count or "Act/360",
            business_day_conv=req.leg1_business_day_conv or req.business_day_conv or "Modified Following",
            stub_rule=req.leg1_stub_rule or req.stub_rule or "Short in arrears",
            adjust_rule=req.leg1_adjust_rule or req.adjust_rule or "Adjust",
            fix_cal=req.leg2_calendar or req.fix_cal or "NYB",
            pay_cal=req.leg1_calendar or req.pay_cal or "NYB",
            fix_day=req.leg2_fix_day if req.leg2_fix_day is not None else (req.fix_day if req.fix_day is not None else -2),
            custom_schedule=leg1_sched,
            leg1_custom_schedule=leg1_sched,
            leg2_custom_schedule=leg2_sched,
            leg1_frequency_months=l1_freq,
            leg1_day_count=req.leg1_day_count or req.day_count or "Act/360",
            leg1_stub_rule=req.leg1_stub_rule or req.stub_rule or "Short in arrears",
            leg1_business_day_conv=req.leg1_business_day_conv or req.business_day_conv or "Modified Following",
            leg1_adjust_rule=req.leg1_adjust_rule or req.adjust_rule or "Adjust",
            leg1_pay_cal=req.leg1_calendar or req.pay_cal or "NYB",
            leg2_frequency_months=l2_freq,
            leg2_day_count=req.leg2_day_count or req.day_count or "Act/360",
            leg2_stub_rule=req.leg2_stub_rule or req.stub_rule or "Short in arrears",
            leg2_business_day_conv=req.leg2_business_day_conv or req.business_day_conv or "Modified Following",
            leg2_adjust_rule=req.leg2_adjust_rule or req.adjust_rule or "Adjust",
            leg2_pay_cal=req.leg2_calendar or req.pay_cal or "NYB",
            leg2_fix_cal=req.leg2_calendar or req.fix_cal or "NYB",
            leg2_fix_day=req.leg2_fix_day if req.leg2_fix_day is not None else (req.fix_day if req.fix_day is not None else -2)
        )
        
        result["snapshot_info"] = {
            "currency": "USD",
            "curve_type": req.curve_type or "Standard",
            "source": snapshot.get("source", "LSEG Workspace Tradition Feed"),
            "timestamp": snapshot.get("timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "pricing_date": curve.pricing_date.strftime("%Y-%m-%d"),
            "settle_date": curve.settle_date.strftime("%Y-%m-%d")
        }
        
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/reload-and-price")
def reload_and_price_usd(req: PricingRequest):
    """[USD ONE-SHOT F9] Reload latest market data and calculate pricing in a single step"""
    tradition_feed.trigger_on_demand_refresh()
    snapshot = tradition_feed.get_snapshot()
    curve = _build_usd_curve(snapshot, req.pricing_date, req.settle_date, req.curve_type)
    pricing_res = calculate_pricing(req)
    
    bootstrapped_curve = []
    for p in curve.pillars:
        bootstrapped_curve.append({
            "tenor": p["tenor"],
            "mat_date": p["mat_date"].strftime("%Y-%m-%d"),
            "par_rate": round(p["rate"], 4),
            "df": round(p["df"], 6),
            "zero_rate": round(p["zero_rate"], 4)
        })

    market_snapshot = {
        "currency": "USD",
        "source": snapshot.get("source", "LSEG Workspace Tradition Feed"),
        "status_message": snapshot.get("status_message", "Live"),
        "is_live_connected": snapshot.get("is_live_connected", False),
        "has_app_key": snapshot.get("has_app_key", False),
        "timestamp": snapshot.get("timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "epoch_ms": snapshot.get("epoch_ms", int(time.time() * 1000)),
        "pricing_date": curve.pricing_date.strftime("%Y-%m-%d"),
        "settle_date": curve.settle_date.strftime("%Y-%m-%d"),
        "quotes": snapshot.get("quotes", []),
        "curve_pillars": bootstrapped_curve,
        "curve_type": req.curve_type or "Standard"
    }

    pricing_data = pricing_res.get("data") if isinstance(pricing_res, dict) else pricing_res

    return {
        "status": "success",
        "data": pricing_data,
        "pricing": pricing_data,
        "market_snapshot": market_snapshot
    }

class RelayPushRequest(BaseModel):
    currency: str = "USD"
    quotes: List[Dict[str, Any]]
    # 데스크 PC 가 LSEG 에서 실제로 받은 시각. 없으면 도착 시각으로 대신하지만,
    # 그 사실이 화면에 표시된다.
    source_timestamp: Optional[str] = None
    # 시간대가 섞이지 않는 절대 시각. 데스크와 서버가 다른 표준시에서 도는 것이
    # 보통이므로 이쪽이 우선한다.
    source_epoch_ms: Optional[float] = None
    origin: Optional[str] = None


_RELAY_FEEDS = {}


def _relay_feed(currency: str):
    global _RELAY_FEEDS
    if not _RELAY_FEEDS:
        _RELAY_FEEDS = {
            "USD": tradition_feed, "KRW": krw_feed,
            "KOFR": kofr_feed, "CRS": crs_feed,
            "FWD": kmbc_fwd_feed,
        }
    return _RELAY_FEEDS.get((currency or "USD").upper())


def _apply_quote(feed, tenor: str, mid: float, bid=None, ask=None) -> bool:
    """
    한 건을 피드에 반영하고, 실제로 반영됐는지 돌려준다.

    피드마다 갱신 메서드의 이름과 인자 수가 다르다. tradition_feed 는
    (tenor, mid, bid, ask), KRW/KOFR/FWD 는 (tenor, mid) 뿐이고, CRS 는 이름부터
    update_quote_manually 다. 중계는 이 차이를 알 필요가 없으므로 여기서 흡수한다 -
    맞추지 않았을 때 KOFR 가 매 주기마다 19건씩 실패했다.

    모르는 테너는 대부분의 피드가 조용히 무시하고 아무것도 돌려주지 않는다. 그걸
    성공으로 세면 '31건 반영'이라 보고하면서 실제로는 한 건도 안 바뀔 수 있다.
    """
    fn = getattr(feed, "update_quote", None) or getattr(feed, "update_quote_manually", None)
    if fn is None:
        raise AttributeError(f"{type(feed).__name__} 에 호가 갱신 메서드가 없습니다")

    known = getattr(feed, "quotes", None)
    if isinstance(known, dict) and known:
        if tenor.strip().upper() not in {str(k).strip().upper() for k in known}:
            return False

    try:
        result = fn(tenor, mid, bid, ask)
    except TypeError:
        result = fn(tenor, mid)
    return True if result is None else bool(result)


@app.post("/api/quotes/push")
def push_relayed_quotes(req: RelayPushRequest):
    """
    데스크 PC 가 받은 호가 한 세트를 통째로 받는다.

    /api/quotes/update 는 테너 하나씩이라 31개를 밀려면 31번 왕복해야 한다.
    중계는 주기적으로 도는 일이므로 한 번에 받는다.
    """
    feed = _relay_feed(req.currency)
    if feed is None:
        raise HTTPException(status_code=400,
                            detail=f"알 수 없는 통화: {req.currency!r}")
    if not req.quotes:
        raise HTTPException(status_code=400, detail="호가가 비어 있습니다")

    applied, skipped = 0, []
    for q in req.quotes:
        tenor = str(q.get("tenor") or "").strip()
        mid = q.get("mid")
        if not tenor or mid is None:
            skipped.append(tenor or "?")
            continue
        try:
            if _apply_quote(feed, tenor, float(mid), q.get("bid"), q.get("ask")):
                applied += 1
            else:
                skipped.append(f"{tenor}(피드가 모르는 테너)")
        except Exception as e:
            skipped.append(f"{tenor}({type(e).__name__}: {e})")

    if not applied:
        # 한 건도 반영하지 못했는데 중계를 기록하면, 대시보드가 '데스크 중계 중'
        # 이라고 표시하면서 실제로는 기준호가를 보여준다. 아무것도 안 온 것보다
        # 나쁘다 - 트레이더가 연결됐다고 믿는다.
        raise HTTPException(
            status_code=422,
            detail=f"{req.currency} 호가를 한 건도 반영하지 못했습니다: {skipped[:3]}")

    st = relay.record(req.currency, req.origin or "desk",
                      req.source_timestamp, applied,
                      source_epoch_ms=req.source_epoch_ms)
    return {"status": "success", "data": {
        "applied": applied, "skipped": skipped, "relay": st}}


@app.get("/api/quotes/relay-status")
def relay_status_all():
    """어느 통화가 중계를 받고 있고 그 호가가 얼마나 오래됐는지."""
    return {"status": "success", "data": relay.all_status()}


@app.post("/api/quotes/update")
def update_manual_quote_usd(req: QuoteUpdateRequest):
    tradition_feed.update_quote(req.tenor, req.mid, req.bid, req.ask)
    return {"status": "success", "message": f"USD Quote for {req.tenor} updated to {req.mid}%"}

@app.post("/api/quotes/reset")
def reset_quotes_usd():
    tradition_feed.reset_to_base()
    return {"status": "success", "message": "All USD quotes reset to baseline"}


# ==============================================================================
# KRW CD 91D IRS ENDPOINTS
# ==============================================================================

def _build_krw_curve(snapshot: Dict[str, Any], p_date_str: Optional[str] = None, s_date_str: Optional[str] = None) -> KRWCurve:
    today = datetime.date.today()
    pricing_date = parse_date(p_date_str) if p_date_str else today
    settle_date = parse_date(s_date_str) if s_date_str else get_krw_spot_date(pricing_date)
    
    quote_tuples = []
    for q in snapshot["quotes"]:
        quote_tuples.append((q["tenor"], float(q["mid"])))
        
    curve = bootstrap_krw_curve(pricing_date, settle_date, quote_tuples)
    return curve

@app.get("/api/krw/market-snapshot")
def get_krw_market_snapshot(pricing_date: Optional[str] = None, settle_date: Optional[str] = None, reload: Optional[bool] = False):
    """[KRW] Get immutable market data snapshot and bootstrapped KRW curve (<0.1ms)"""
    if reload:
        krw_feed.trigger_on_demand_refresh()
    else:
        _warm_once("krw", krw_feed)
    snapshot = krw_feed.get_snapshot()
    curve = _build_krw_curve(snapshot, pricing_date, settle_date)
    
    bootstrapped_curve = []
    for p in curve.pillars:
        bootstrapped_curve.append({
            "tenor": p["tenor"],
            "mat_date": p["mat_date"].strftime("%Y-%m-%d"),
            "par_rate": round(p["rate"], 4),
            "df": round(p["df"], 6),
            "zero_rate": round(p["zero_rate"], 4)
        })
        
    return {
        "status": "success",
        "snapshot_info": {
            "currency": "KRW",
            "relay": relay.status("KRW"),
            "source": snapshot["source"],
            "status_message": snapshot.get("status_message", "Live"),
            "is_live_connected": snapshot.get("is_live_connected", False),
            "has_app_key": snapshot.get("has_app_key", False),
            "timestamp": snapshot["timestamp"],
            "epoch_ms": snapshot["epoch_ms"],
            "pricing_date": curve.pricing_date.strftime("%Y-%m-%d"),
            "settle_date": curve.settle_date.strftime("%Y-%m-%d"),
            "df_settle": round(curve.df_settle, 6)
        },
        "quotes": snapshot["quotes"],
        "curve_pillars": bootstrapped_curve
    }

@app.post("/api/krw/price")
def calculate_krw_pricing(req: PricingRequest):
    """[KRW] Calculate Par Swap Rate, NPV (₩), DV01 (₩/bp), and Dual-Leg Schedule (Auto or Custom Pasted)"""
    _validate_pricing_request(req)
    try:
        snapshot = krw_feed.get_snapshot()
        curve = _build_krw_curve(snapshot, req.pricing_date, req.settle_date)
        pricer = KRWSwapPricer(curve)
        
        eff_date = parse_date(req.effective_date) if req.effective_date else None
        mat_date = parse_date(req.maturity_date) if req.maturity_date else None
        l1_freq = _resolve_freq_months(req.leg1_payment_freq or req.payment_freq, req.leg1_frequency_months or req.frequency_months, 3)
        l2_freq = _resolve_freq_months(req.leg2_payment_freq or req.payment_freq, req.leg2_frequency_months or req.frequency_months, 3)
        
        eff_for_rc = eff_date or (curve.settle_date if hasattr(curve, "settle_date") else datetime.date.today())
        leg1_sched, leg2_sched = _resolve_custom_schedules(
            req=req,
            eff_date=eff_for_rc,
            default_notional=req.notional if req.notional > 0 else 10_000_000_000.0,
            default_coupon=req.fixed_coupon_pct or 0.0,
            default_spread=req.spread_bp or 0.0,
            currency="KRW"
        )

        result = pricer.price_swap(
            notional=req.notional if req.notional > 0 else 10_000_000_000.0,
            position=req.position,
            fixed_coupon_pct=req.fixed_coupon_pct,
            spread_bp=req.spread_bp,
            effective_date=eff_date,
            maturity_date=mat_date,
            tenor_str=req.tenor if req.tenor else "3Y",
            frequency_months=l1_freq,
            day_count=req.leg1_day_count or req.day_count or "Act/365",
            business_day_conv=req.leg1_business_day_conv or req.business_day_conv or "Modified Following",
            stub_rule=req.leg1_stub_rule or req.stub_rule or "Short in arrears",
            adjust_rule=req.leg1_adjust_rule or req.adjust_rule or "Adjust",
            fix_cal=req.leg2_calendar or req.fix_cal or "SEB",
            pay_cal=req.leg1_calendar or req.pay_cal or "SEB",
            fix_day=req.leg2_fix_day if req.leg2_fix_day is not None else (req.fix_day if req.fix_day is not None else -1),
            custom_schedule=leg1_sched,
            leg1_custom_schedule=leg1_sched,
            leg2_custom_schedule=leg2_sched,
            leg1_frequency_months=l1_freq,
            leg1_day_count=req.leg1_day_count or req.day_count or "Act/365",
            leg1_stub_rule=req.leg1_stub_rule or req.stub_rule or "Short in arrears",
            leg1_business_day_conv=req.leg1_business_day_conv or req.business_day_conv or "Modified Following",
            leg1_adjust_rule=req.leg1_adjust_rule or req.adjust_rule or "Adjust",
            leg1_pay_cal=req.leg1_calendar or req.pay_cal or "SEB",
            leg2_frequency_months=l2_freq,
            leg2_day_count=req.leg2_day_count or req.day_count or "Act/365",
            leg2_stub_rule=req.leg2_stub_rule or req.stub_rule or "Short in arrears",
            leg2_business_day_conv=req.leg2_business_day_conv or req.business_day_conv or "Modified Following",
            leg2_adjust_rule=req.leg2_adjust_rule or req.adjust_rule or "Adjust",
            leg2_pay_cal=req.leg2_calendar or req.pay_cal or "SEB",
            leg2_fix_cal=req.leg2_calendar or req.fix_cal or "SEB",
            leg2_fix_day=req.leg2_fix_day if req.leg2_fix_day is not None else (req.fix_day if req.fix_day is not None else -1)
        )
        
        result["snapshot_info"] = {
            "currency": "KRW",
            "source": snapshot.get("source", "LSEG Workspace KRW Feed"),
            "timestamp": snapshot.get("timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "pricing_date": curve.pricing_date.strftime("%Y-%m-%d"),
            "settle_date": curve.settle_date.strftime("%Y-%m-%d")
        }
        
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/krw/reload-and-price")
def reload_and_price_krw(req: PricingRequest):
    """[KRW ONE-SHOT F9] Reload latest market data and calculate KRW pricing in a single step"""
    krw_feed.trigger_on_demand_refresh()
    snapshot = krw_feed.get_snapshot()
    curve = _build_krw_curve(snapshot, req.pricing_date, req.settle_date)
    pricing_res = calculate_krw_pricing(req)
    
    bootstrapped_curve = []
    for p in curve.pillars:
        bootstrapped_curve.append({
            "tenor": p["tenor"],
            "mat_date": p["mat_date"].strftime("%Y-%m-%d"),
            "par_rate": round(p["rate"], 4),
            "df": round(p["df"], 6),
            "zero_rate": round(p["zero_rate"], 4)
        })
        
    market_snapshot = {
        "currency": "KRW",
        "source": snapshot["source"],
        "status_message": snapshot.get("status_message", "Live"),
        "is_live_connected": snapshot.get("is_live_connected", False),
        "has_app_key": snapshot.get("has_app_key", False),
        "timestamp": snapshot["timestamp"],
        "epoch_ms": snapshot["epoch_ms"],
        "pricing_date": curve.pricing_date.strftime("%Y-%m-%d"),
        "settle_date": curve.settle_date.strftime("%Y-%m-%d"),
        "df_settle": round(curve.df_settle, 6),
        "quotes": snapshot["quotes"],
        "curve_pillars": bootstrapped_curve
    }
    pricing_data = pricing_res.get("data") if isinstance(pricing_res, dict) else pricing_res
    return {
        "status": "success",
        "data": pricing_data,
        "pricing": pricing_data,
        "market_snapshot": market_snapshot
    }

@app.post("/api/krw/quotes/update")
def update_manual_quote_krw(req: QuoteUpdateRequest):
    krw_feed.update_quote(req.tenor, req.mid)
    return {"status": "success", "message": f"KRW Quote for {req.tenor} updated to {req.mid}%"}

@app.post("/api/krw/quotes/reset")
def reset_quotes_krw():
    krw_feed.reset_to_base()
    return {"status": "success", "message": "All KRW quotes reset to baseline"}


# ==============================================================================
# KRW KOFR OIS API ENDPOINTS ('\KRW KOFR Q 3M')
# ==============================================================================
def _build_kofr_curve(snapshot: Dict[str, Any], pricing_date_str: Optional[str] = None, settle_date_str: Optional[str] = None) -> KOFRCurve:
    p_date = parse_date(pricing_date_str) if pricing_date_str else datetime.date.today()
    s_date = parse_date(settle_date_str) if settle_date_str else get_kofr_spot_date(p_date, 1)
    
    quote_tuples = []
    for q in snapshot.get("quotes", []):
        quote_tuples.append((q["tenor"], float(q["mid"])))
        
    return bootstrap_kofr_curve(p_date, s_date, quote_tuples)

@app.get("/api/kofr/market-snapshot")
def get_kofr_market_snapshot(pricing_date: Optional[str] = None, settle_date: Optional[str] = None, reload: Optional[bool] = False):
    """Fetch instant live KOFR OIS snapshot and calibrated 3M curve"""
    if reload:
        kofr_feed.trigger_on_demand_refresh()
    else:
        _warm_once("kofr", kofr_feed)
    snapshot = kofr_feed.get_snapshot()
    curve = _build_kofr_curve(snapshot, pricing_date, settle_date)
    
    bootstrapped_curve = []
    for p in curve.pillars:
        bootstrapped_curve.append({
            "tenor": p["tenor"],
            "mat_date": p["mat_date"].strftime("%Y-%m-%d"),
            "par_rate": round(p["rate"], 4),
            "df": round(p["df"], 6),
            "zero_rate": round(p["zero_rate"], 4)
        })

    return {
        "status": "success",
        "data": {
            "currency": "KRW_KOFR",
            "relay": relay.status("KOFR"),
            "generator": "\\KRW KOFR Q 3M",
            "source": snapshot["source"],
            "status_message": snapshot.get("status_message", "Live"),
            "is_live_connected": snapshot.get("is_live_connected", False),
            "has_app_key": snapshot.get("has_app_key", False),
            "timestamp": snapshot["timestamp"],
            "epoch_ms": snapshot["epoch_ms"],
            "pricing_date": curve.pricing_date.strftime("%Y-%m-%d"),
            "settle_date": curve.settle_date.strftime("%Y-%m-%d"),
            "quotes": snapshot["quotes"],
            "curve_pillars": bootstrapped_curve
        }
    }

@app.post("/api/kofr/price")
def price_swap_kofr(req: PricingRequest):
    r"""Price KRW KOFR OIS Swap matching Murex '\KRW KOFR Q 3M'"""
    _validate_pricing_request(req)
    try:
        snapshot = kofr_feed.get_snapshot()
        curve = _build_kofr_curve(snapshot, req.pricing_date, req.settle_date)
        pricer = KOFRSwapPricer(curve)
        
        eff_date = parse_date(req.effective_date) if req.effective_date else None
        mat_date = parse_date(req.maturity_date) if req.maturity_date else None
        l1_freq = _resolve_freq_months(req.leg1_payment_freq or req.payment_freq, req.leg1_frequency_months or req.frequency_months, 3)
        l2_freq = _resolve_freq_months(req.leg2_payment_freq or req.payment_freq, req.leg2_frequency_months or req.frequency_months, 3)
        
        eff_for_rc = eff_date or (curve.settle_date if hasattr(curve, "settle_date") else datetime.date.today())
        leg1_sched, leg2_sched = _resolve_custom_schedules(
            req=req,
            eff_date=eff_for_rc,
            default_notional=req.notional if req.notional > 0 else 10_000_000_000.0,
            default_coupon=req.fixed_coupon_pct or 0.0,
            default_spread=req.spread_bp or 0.0,
            currency="KRW_KOFR"
        )

        result = pricer.price_swap(
            notional=req.notional if req.notional > 0 else 10_000_000_000.0,
            position=req.position,
            fixed_coupon_pct=req.fixed_coupon_pct,
            spread_bp=req.spread_bp,
            effective_date=eff_date,
            maturity_date=mat_date,
            tenor_str=req.tenor if req.tenor else "1Y",
            frequency_months=l1_freq,
            payment_lag_bd=2,   # +2 Business Day Payment Lag
            day_count=req.leg1_day_count or req.day_count or "Act/365",
            business_day_conv=req.leg1_business_day_conv or req.business_day_conv or "Modified Following",
            stub_rule=req.leg1_stub_rule or req.stub_rule or "Short in arrears",
            adjust_rule=req.leg1_adjust_rule or req.adjust_rule or "Adjust",
            fix_cal=req.leg2_calendar or req.fix_cal or "SEB",
            pay_cal=req.leg1_calendar or req.pay_cal or "SEB",
            fix_day=req.leg2_fix_day if req.leg2_fix_day is not None else (req.fix_day if req.fix_day is not None else 0),
            custom_schedule=leg1_sched,
            leg1_custom_schedule=leg1_sched,
            leg2_custom_schedule=leg2_sched,
            leg1_frequency_months=l1_freq,
            leg1_day_count=req.leg1_day_count or req.day_count or "Act/365",
            leg1_stub_rule=req.leg1_stub_rule or req.stub_rule or "Short in arrears",
            leg1_business_day_conv=req.leg1_business_day_conv or req.business_day_conv or "Modified Following",
            leg1_adjust_rule=req.leg1_adjust_rule or req.adjust_rule or "Adjust",
            leg1_pay_cal=req.leg1_calendar or req.pay_cal or "SEB",
            leg2_frequency_months=l2_freq,
            leg2_day_count=req.leg2_day_count or req.day_count or "Act/365",
            leg2_stub_rule=req.leg2_stub_rule or req.stub_rule or "Short in arrears",
            leg2_business_day_conv=req.leg2_business_day_conv or req.business_day_conv or "Modified Following",
            leg2_adjust_rule=req.leg2_adjust_rule or req.adjust_rule or "Adjust",
            leg2_pay_cal=req.leg2_calendar or req.pay_cal or "SEB",
            leg2_fix_cal=req.leg2_calendar or req.fix_cal or "SEB",
            leg2_fix_day=req.leg2_fix_day if req.leg2_fix_day is not None else (req.fix_day if req.fix_day is not None else 0),
            swap_type=req.crs_swap_type or "Vanilla",
            usd_fixed_coupon_pct=req.usd_fixed_coupon_pct
        )
        
        result["snapshot_info"] = {
            "currency": "KRW_KOFR",
            "generator": "\\KRW KOFR Q 3M",
            "source": snapshot.get("source", "LSEG Workspace KOFR Feed"),
            "timestamp": snapshot.get("timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "pricing_date": curve.pricing_date.strftime("%Y-%m-%d"),
            "settle_date": curve.settle_date.strftime("%Y-%m-%d")
        }
        
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/kofr/reload-and-price")
def reload_and_price_kofr(req: PricingRequest):
    """[KOFR ONE-SHOT F9] Reload latest market data and calculate KOFR pricing in a single step"""
    kofr_feed.trigger_on_demand_refresh()
    snapshot = kofr_feed.get_snapshot()
    curve = _build_kofr_curve(snapshot, req.pricing_date, req.settle_date)
    pricing_res = price_swap_kofr(req)
    
    bootstrapped_curve = []
    for p in curve.pillars:
        bootstrapped_curve.append({
            "tenor": p["tenor"],
            "mat_date": p["mat_date"].strftime("%Y-%m-%d"),
            "par_rate": round(p["rate"], 4),
            "df": round(p["df"], 6),
            "zero_rate": round(p["zero_rate"], 4)
        })

    market_snapshot = {
        "currency": "KRW_KOFR",
        "generator": "\\KRW KOFR Q 3M",
        "source": snapshot.get("source", "LSEG Workspace KOFR Feed"),
        "status_message": snapshot.get("status_message", "Live"),
        "is_live_connected": snapshot.get("is_live_connected", False),
        "has_app_key": snapshot.get("has_app_key", False),
        "timestamp": snapshot.get("timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "epoch_ms": snapshot.get("epoch_ms", int(time.time() * 1000)),
        "pricing_date": curve.pricing_date.strftime("%Y-%m-%d"),
        "settle_date": curve.settle_date.strftime("%Y-%m-%d"),
        "quotes": snapshot.get("quotes", []),
        "curve_pillars": bootstrapped_curve
    }
    pricing_data = pricing_res.get("data") if isinstance(pricing_res, dict) else pricing_res
    return {
        "status": "success",
        "data": pricing_data,
        "pricing": pricing_data,
        "market_snapshot": market_snapshot
    }

@app.post("/api/kofr/quotes/update")
def update_manual_quote_kofr(req: QuoteUpdateRequest):
    kofr_feed.update_quote(req.tenor, req.mid)
    return {"status": "success", "message": f"KOFR Quote for {req.tenor} updated to {req.mid}%"}

@app.post("/api/kofr/quotes/reset")
def reset_quotes_kofr():
    kofr_feed.reset_to_base()
    return {"status": "success", "message": "All KOFR quotes reset to baseline"}

@app.get("/api/basis/cd-kofr")
def get_cd_kofr_basis():
    """Calculate Real-Time CD IRS vs KOFR OIS Basis Spread (bp)"""
    cd_snap = krw_feed.get_snapshot()
    kofr_snap = kofr_feed.get_snapshot()
    
    cd_map = {q["tenor"]: q["mid"] for q in cd_snap.get("quotes", [])}
    kofr_map = {q["tenor"]: q["mid"] for q in kofr_snap.get("quotes", [])}
    
    basis_table = []
    check_tenors = ["1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y"]
    for t in check_tenors:
        cd_rate = cd_map.get(t)
        kf_rate = kofr_map.get(t)
        if cd_rate is not None and kf_rate is not None:
            basis_bp = round((cd_rate - kf_rate) * 100.0, 2)
            basis_table.append({
                "tenor": t,
                "cd_rate": cd_rate,
                "kofr_rate": kf_rate,
                "basis_bp": basis_bp
            })
            
    return {"status": "success", "data": basis_table}


# ==============================================================================
# KRW FX SOFR (CRS) API ENDPOINTS
# ==============================================================================

@app.get("/api/crs/market-snapshot")
def get_crs_market_snapshot(pricing_date: Optional[str] = None, settle_date: Optional[str] = None, reload: Optional[bool] = False):
    """Returns real-time Prebon Yamane CRS Market Data & Calibrated FX SOFR Curve"""
    if reload:
        crs_feed.trigger_on_demand_refresh()
    else:
        _warm_once("crs", crs_feed)
    snap = crs_feed.get_snapshot()
    p_date = parse_date(pricing_date) if pricing_date else datetime.date.today()
    s_date = parse_date(settle_date) if settle_date else get_crs_spot_date(p_date, 2)
    
    spot_fx = snap.get("spot_fx", 1335.50)
    quotes = [(q["tenor"], float(q["mid"])) for q in snap.get("quotes", [])]
    curve = bootstrap_crs_curve(p_date, s_date, quotes, spot_fx)
    
    bootstrapped_curve = []
    for p in curve.pillars:
        bootstrapped_curve.append({
            "tenor": p["tenor"],
            "mat_date": p["mat_date"].strftime("%Y-%m-%d") if hasattr(p["mat_date"], "strftime") else str(p["mat_date"]),
            "par_rate": round(p["rate"], 4),
            "df": round(p["df"], 6),
            "zero_rate": round(p["zero_rate"], 4)
        })
        
    snap["curve_pillars"] = bootstrapped_curve
    snap["settle_date"] = s_date.strftime("%Y-%m-%d")
    snap["pricing_date"] = p_date.strftime("%Y-%m-%d")
    # 다른 통화 스냅샷과 같은 자리에 중계 상태를 실어 보낸다.
    snap = dict(snap, relay=relay.status("CRS"))
    return {"status": "success", "data": snap}

@app.post("/api/crs/price")
def calculate_price_crs(req: PricingRequest):
    """Price KRW FX SOFR Cross-Currency Swap matching Reference SwapPricer"""
    _validate_pricing_request(req)
    try:
        snap = crs_feed.get_snapshot()
        spot_fx = req.spot_fx if (req.spot_fx and req.spot_fx > 0) else snap.get("spot_fx", 1335.50)
        
        pricing_date = parse_date(req.pricing_date) if req.pricing_date else datetime.date.today()
        settle_date = parse_date(req.settle_date) if req.settle_date else get_crs_spot_date(pricing_date, 2)
        
        crs_quotes = [(q["tenor"], float(q["mid"])) for q in snap.get("quotes", [])]
        krw_fx_curve = bootstrap_crs_curve(pricing_date, settle_date, crs_quotes, spot_fx)
        
        usd_snap = tradition_feed.get_snapshot()
        usd_quotes = [(q["tenor"], float(q["mid"])) for q in usd_snap.get("quotes", [])]
        crs_c_type = (req.curve_type or "").strip().lower()
        if crs_c_type in ("hedgecurve", "hedge_curve", "hedge"):
            adv_usd = bootstrap_advanced_sofr_curve(pricing_date, settle_date, usd_quotes)
            usd_sofr_curve = CompositeSOFRCurve(adv_usd)
        elif crs_c_type == "advanced":
            usd_sofr_curve = bootstrap_advanced_sofr_curve(pricing_date, settle_date, usd_quotes)
        else:
            usd_sofr_curve = bootstrap_sofr_curve(pricing_date, settle_date, usd_quotes)
        
        pricer = KRWFXSOFRSwapPricer(krw_fx_curve, usd_sofr_curve, spot_fx)
        
        usd_notional = req.usd_notional if (req.usd_notional and req.usd_notional > 0) else (req.notional if req.notional > 0 else 10_000_000.0)
        krw_notional = req.krw_notional if (req.krw_notional and req.krw_notional > 0) else usd_notional * spot_fx
        position_str = req.position if req.position else "Pay KRW Fixed"
        tenor_str = req.tenor if req.tenor else "5Y"
        coupon_pct = req.fixed_coupon_pct
        spread_bp = req.spread_bp
        payment_lag_bd = req.payment_lag_bd if req.payment_lag_bd is not None else 2
        
        l1_freq = _resolve_freq_months(req.leg1_payment_freq or req.payment_freq, req.leg1_frequency_months or req.frequency_months, 6)
        l2_freq = _resolve_freq_months(req.leg2_payment_freq or req.payment_freq, req.leg2_frequency_months or req.frequency_months, 6)
        
        is_fixed_fixed = req.crs_swap_type and ("fixed" in req.crs_swap_type.lower())
        default_l2_dc = "30/360" if is_fixed_fixed else "Act/360"

        eff_date = parse_date(req.effective_date) if req.effective_date else settle_date
        mat_date = parse_date(req.maturity_date) if req.maturity_date else None
        
        eff_for_rc = eff_date or settle_date
        leg1_sched, leg2_sched = _resolve_custom_schedules(
            req=req,
            eff_date=eff_for_rc,
            default_notional=req.usd_notional or req.notional or 10_000_000.0,
            default_coupon=coupon_pct or 0.0,
            default_spread=spread_bp or 0.0,
            currency="KRW_CRS"
        )

        res = pricer.price_swap(
            usd_notional=usd_notional,
            krw_notional=krw_notional,
            spot_fx=spot_fx,
            position=position_str,
            fixed_coupon_pct=coupon_pct,
            spread_bp=spread_bp,
            effective_date=eff_date,
            maturity_date=mat_date,
            tenor_str=tenor_str,
            frequency_months=l1_freq,
            payment_lag_bd=payment_lag_bd,
            day_count_krw=req.leg1_day_count or req.day_count or "30/360",
            day_count_usd=req.leg2_day_count or default_l2_dc,
            business_day_conv=req.leg1_business_day_conv or req.business_day_conv or "Modified Following",
            stub_rule=req.leg1_stub_rule or req.stub_rule or "Short in arrears",
            adjust_rule=req.leg1_adjust_rule or req.adjust_rule or "Adjust",
            fix_cal=req.leg2_calendar or req.fix_cal or "SEB_NYB",
            pay_cal=req.leg1_calendar or req.pay_cal or "SEB_NYB",
            fix_day=req.leg2_fix_day if req.leg2_fix_day is not None else (req.fix_day if req.fix_day is not None else -1),
            include_principal_exchange=True,
            custom_schedule=leg1_sched,
            leg1_custom_schedule=leg1_sched,
            leg2_custom_schedule=leg2_sched,
            swap_type=req.crs_swap_type or "Vanilla",
            usd_fixed_coupon_pct=req.usd_fixed_coupon_pct,
            leg1_frequency_months=l1_freq,
            leg1_day_count=req.leg1_day_count or req.day_count or "30/360",
            leg1_stub_rule=req.leg1_stub_rule or req.stub_rule or "Short in arrears",
            leg1_business_day_conv=req.leg1_business_day_conv or req.business_day_conv or "Modified Following",
            leg1_adjust_rule=req.leg1_adjust_rule or req.adjust_rule or "Adjust",
            leg1_pay_cal=req.leg1_calendar or req.pay_cal or "SEB_NYB",
            leg2_frequency_months=l2_freq,
            leg2_day_count=req.leg2_day_count or default_l2_dc,
            leg2_stub_rule=req.leg2_stub_rule or req.stub_rule or "Short in arrears",
            leg2_business_day_conv=req.leg2_business_day_conv or req.business_day_conv or "Modified Following",
            leg2_adjust_rule=req.leg2_adjust_rule or req.adjust_rule or "Adjust",
            leg2_pay_cal=req.leg2_calendar or req.pay_cal or "SEB_NYB",
            leg2_fix_cal=req.leg2_calendar or req.fix_cal or "SEB_NYB",
            leg2_fix_day=req.leg2_fix_day if req.leg2_fix_day is not None else -1
        )
        
        bootstrapped_curve = []
        for p in krw_fx_curve.pillars:
            bootstrapped_curve.append({
                "tenor": p["tenor"],
                "mat_date": p["mat_date"].strftime("%Y-%m-%d") if hasattr(p["mat_date"], "strftime") else str(p["mat_date"]),
                "par_rate": round(p["rate"], 4),
                "df": round(p["df"], 6),
                "zero_rate": round(p["zero_rate"], 4)
            })
            
        snap["curve_pillars"] = bootstrapped_curve
        snap["settle_date"] = settle_date.strftime("%Y-%m-%d")
        snap["pricing_date"] = pricing_date.strftime("%Y-%m-%d")
        snap["curve_type"] = req.curve_type or "Standard"
        snap["swap_type"] = req.crs_swap_type or "Vanilla"
        
        return {
            "status": "success",
            "market_snapshot": snap,
            "data": {
                "market_snapshot": snap,
                "pricing_results": res["pricing_results"],
                "schedules": res["schedules"],
                "principal_flows": res["principal_flows"],
                "key_rate_deltas": res["key_rate_deltas"],
                "hedge_key_rate_deltas": res.get("hedge_key_rate_deltas"),
                "krw_key_rate_deltas": res.get("krw_key_rate_deltas"),
                "curve_pillars": bootstrapped_curve,
                "details": {
                    "effective_date": res["effective_date"],
                    "maturity_date": res["maturity_date"],
                    "tenor": res["tenor"],
                    "spot_fx": res["spot_fx"],
                    "usd_notional": res["usd_notional"],
                    "krw_notional": res["krw_notional"],
                    "position": res["position"],
                    "fixed_coupon_pct": res["fixed_coupon_pct"],
                    "spread_bp": spread_bp,
                    "swap_type": req.crs_swap_type or "Vanilla",
                    "usd_fixed_coupon_pct": req.usd_fixed_coupon_pct,
                    "curve_type": req.curve_type or "Standard"
                }
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/crs/reload-and-price")
def reload_and_price_crs(req: PricingRequest):
    """Refreshes live quotes and recalculates pricing in one atomic shot"""
    crs_feed.trigger_on_demand_refresh()
    snap = crs_feed.get_snapshot()
    pricing_res = calculate_price_crs(req)
    
    p_date = parse_date(req.pricing_date) if req.pricing_date else datetime.date.today()
    s_date = parse_date(req.settle_date) if req.settle_date else get_crs_spot_date(p_date, 2)
    spot_fx = snap.get("spot_fx", 1335.50)
    quotes = [(q["tenor"], float(q["mid"])) for q in snap.get("quotes", [])]
    curve = bootstrap_crs_curve(p_date, s_date, quotes, spot_fx)
    
    bootstrapped_curve = []
    for p in curve.pillars:
        bootstrapped_curve.append({
            "tenor": p["tenor"],
            "mat_date": p["mat_date"].strftime("%Y-%m-%d") if hasattr(p["mat_date"], "strftime") else str(p["mat_date"]),
            "par_rate": round(p["rate"], 4),
            "df": round(p["df"], 6),
            "zero_rate": round(p["zero_rate"], 4)
        })
        
    snap_copy = dict(snap)
    snap_copy["curve_pillars"] = bootstrapped_curve
    snap_copy["settle_date"] = s_date.strftime("%Y-%m-%d")
    snap_copy["pricing_date"] = p_date.strftime("%Y-%m-%d")

    pricing_data = pricing_res.get("data") if isinstance(pricing_res, dict) else pricing_res
    return {
        "status": "success",
        "data": pricing_data,
        "pricing": pricing_data,
        "market_snapshot": snap_copy
    }

@app.post("/api/crs/quotes/update")
def update_quote_crs(req: QuoteUpdateRequest):
    crs_feed.update_quote_manually(req.tenor, req.mid, req.bid, req.ask)
    return {"status": "success", "message": f"Prebon CRS {req.tenor} updated manually"}

@app.post("/api/crs/quotes/reset")
def reset_quotes_crs():
    crs_feed.reset_quotes()
    return {"status": "success", "message": "All Prebon CRS quotes reset to baseline"}

MAX_TERMSHEET_BYTES = 20 * 1024 * 1024


# The build of the dashboard this server ships. app.js sends it on its own requests,
# so a browser running a cached older copy can be recognised from the missing header.
UI_BUILD = "termsheet-popup"


def _stale_ui(request: "Request") -> bool:
    """
    Whether this request came from a dashboard older than the one this server ships.

    Advisory only - nothing is refused on the strength of it. Only a browser can be
    holding a stale page, and a browser identifies itself by sending a Referer or the
    Sec-Fetch headers; curl, the test client and any script send neither.
    """
    from_page = bool(request.headers.get("referer") or request.headers.get("sec-fetch-mode"))
    return from_page and request.headers.get("x-pricer-ui") != UI_BUILD


@app.get("/api/termsheet/status")
def termsheet_status(request: Request):
    """
    Tell the dashboard whether term sheet extraction is available.

    A browser holding a cached pre-popup dashboard reaches this endpoint but cannot
    reach the popup or upload anything but a PDF, and nothing on its screen says why.
    It does render this endpoint's `reason`, so that is where it gets told to reload -
    the one message such a page will actually show.
    """
    from server.termsheet import extraction_status

    data = extraction_status()
    if _stale_ui(request):
        # Advisory only. `ready` still reports whether extraction can run, because a
        # page that is behind can still upload perfectly well - and saying otherwise
        # sends someone hunting for an API problem that is not there.
        data = dict(data, ui_stale=True,
                    ui_message="대시보드가 최신이 아닐 수 있습니다 — Ctrl+F5 로 새로고침하세요")
    return {"status": "success", "data": data}


@app.get("/api/termsheet/diagnostics")
def termsheet_diagnostics():
    """
    What the last few failed uploads were, so a failure can be diagnosed from the
    dashboard rather than from whoever happens to be watching the server console.

    Metadata only - file name, size, detected type, and the error.
    """
    from server.termsheet import recent_failures, extraction_status
    st = extraction_status()
    return {"status": "success", "data": {
        "provider": st.get("provider_label"), "model": st.get("model"),
        "ready": st.get("ready"), "failures": recent_failures(),
    }}


@app.post("/api/termsheet/extract")
async def extract_termsheet(request: Request, file: UploadFile = File(...)):
    """
    Read a termsheet, return a draft ticket for the trader to review.

    The document is held in memory only: identity is stripped before anything is sent
    out, and the bytes are dropped when this call returns. Nothing is written to disk.
    """
    from server.termsheet import process_termsheet, record_failure

    # No extension gate: what the file actually is decides how it is read, and a
    # marketer's attachment is as likely to be an Excel sheet or a phone photo as a PDF.
    raw = await file.read()
    try:
        if not raw:
            raise HTTPException(status_code=400, detail="빈 파일입니다")
        if len(raw) > MAX_TERMSHEET_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"파일이 너무 큽니다 ({len(raw)/1024/1024:.1f}MB). 최대 20MB까지 지원합니다"
            )
        try:
            # In a threadpool, not inline. Reading a term sheet takes 45-60 seconds
            # in the model, and awaiting nothing during it holds the event loop - the
            # server answers nothing at all meanwhile, health checks included, so the
            # host concludes the instance is dead and restarts it. That is the 502.
            result = await run_in_threadpool(
                process_termsheet, raw, filename=file.filename or "")
        except HTTPException:
            raise
        except ValueError as e:
            record_failure(file.filename or "", raw, "read", e)
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            record_failure(file.filename or "", raw, "extract", e)
            # The console is the only place this used to be visible, and nobody is
            # watching it; keep the type so a traceback is not the only clue.
            raise HTTPException(status_code=502,
                                detail=f"터미시트 추출 실패: {type(e).__name__}: {e}")
        return {"status": "success", "data": result}
    finally:
        del raw
        await file.close()


@app.post("/api/rollercoaster/parse-paste")
def parse_rollercoaster_endpoint(req: RollercoasterParseRequest):
    """Parses pasted Excel text into normalized rollercoaster swap periods for preview & pricing (supports Leg 1 and Leg 2)"""
    eff_d = parse_date(req.effective_date) if req.effective_date else datetime.date.today()
    def_notional = req.notional or 100_000_000.0
    def_coupon = req.fixed_coupon_pct or 0.0
    def_spread = req.spread_bp or 0.0
    curr = req.currency or "USD"

    parsed_leg1 = []
    parsed_leg2 = []

    text1 = req.leg1_raw_paste_text or req.raw_paste_text
    if text1 and text1.strip():
        parsed_leg1 = parse_rollercoaster_paste(
            raw_text=text1,
            effective_date=eff_d,
            default_notional=def_notional,
            default_coupon_pct=def_coupon,
            default_spread_bp=def_spread,
            currency=curr
        )

    text2 = req.leg2_raw_paste_text or req.raw_paste_text
    if text2 and text2.strip():
        parsed_leg2 = parse_rollercoaster_paste(
            raw_text=text2,
            effective_date=eff_d,
            default_notional=def_notional,
            default_coupon_pct=def_coupon,
            default_spread_bp=def_spread,
            currency=curr
        )

    return {
        "status": "success",
        "data": parsed_leg1 if parsed_leg1 else parsed_leg2,
        "data_leg1": parsed_leg1,
        "data_leg2": parsed_leg2,
        "count_leg1": len(parsed_leg1),
        "count_leg2": len(parsed_leg2),
        "count": max(len(parsed_leg1), len(parsed_leg2))
    }


# ==============================================================================
# FORWARD SWAP POINT PRICER API ENDPOINTS (KMBC & CIP Hybrid Model)
# ==============================================================================

_CURVE_CACHE: Dict[Any, Any] = {}

def get_cached_sofr_curve(p_date: datetime.date, s_date: datetime.date, usd_quotes: List[Tuple[str, float]]) -> SOFRCurve:
    key = ("USD_SOFR", p_date, s_date, tuple(usd_quotes))
    if key in _CURVE_CACHE:
        return _CURVE_CACHE[key]
    curve = bootstrap_sofr_curve(p_date, s_date, usd_quotes)
    _CURVE_CACHE[key] = curve
    return curve

def get_cached_crs_curve(p_date: datetime.date, s_date: datetime.date, crs_quotes: List[Tuple[str, float]], spot_fx: float) -> KRWFXSOFRCurve:
    key = ("KRW_CRS", p_date, s_date, tuple(crs_quotes), round(spot_fx, 2))
    if key in _CURVE_CACHE:
        return _CURVE_CACHE[key]
    curve = bootstrap_crs_curve(p_date, s_date, crs_quotes, spot_fx)
    _CURVE_CACHE[key] = curve
    return curve

@app.get("/api/fwd/market-snapshot")
def get_fwd_market_snapshot(pricing_date: Optional[str] = None, reload: Optional[bool] = False):
    """Returns KMBC USD/KRW Swap Points, Spot FX (KRW=), and calibrated discount curves for Forward pricing"""
    if reload:
        try:
            kmbc_fwd_feed.trigger_on_demand_refresh()
        except Exception as e:
            print(f"[KMBC SNAPSHOT ERROR] On-demand refresh error: {e}")
    snap_kmbc = kmbc_fwd_feed.get_snapshot()
    snap_crs = crs_feed.get_snapshot()
    snap_usd = tradition_feed.get_snapshot()
    
    p_date = parse_date(pricing_date) if pricing_date else datetime.date.today()
    s_date = add_business_days(p_date, 2, "SEB_NYB")
    
    spot_fx = snap_kmbc.get("spot_fx", 1357.85)
    crs_quotes = [(q["tenor"], float(q["mid"])) for q in snap_crs.get("quotes", [])]
    krw_fx_curve = get_cached_crs_curve(p_date, s_date, crs_quotes, spot_fx)
    
    usd_quotes = [(q["tenor"], float(q["mid"])) for q in snap_usd.get("quotes", [])]
    usd_sofr_curve = get_cached_sofr_curve(p_date, s_date, usd_quotes)
    
    kmbc_q_list = snap_kmbc.get("quotes", [])
    pricer = FwdSwapPricer(krw_fx_curve, usd_sofr_curve, spot_fx, p_date, calendar="SEB_NYB", kmbc_quotes=kmbc_q_list)
    
    # Generate full hybrid USD/KRW forward swap points curve (1W to 20Y)
    kmbc_q_map = {q["tenor"]: q for q in kmbc_q_list}
    std_tenors = ["1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y", "12Y", "15Y", "20Y"]
    hybrid_quotes = []
    
    for t in std_tenors:
        leg = pricer.price_single_leg(maturity=t, notional_usd=10_000_000.0, margin_bp=0.0)
        sp_won = leg["sp_theo"]
        sp_jeon = round(sp_won * 100.0, 2)
        
        if t in kmbc_q_map:
            q_kmbc = kmbc_q_map[t]
            hybrid_quotes.append({
                "tenor": t,
                "ric": q_kmbc.get("ric", f"KRW{t}=KMBC"),
                "type": "KMBC (Live)",
                "bid": q_kmbc.get("bid"),
                "ask": q_kmbc.get("ask"),
                "mid": q_kmbc.get("mid"),
                "bid_krw": q_kmbc.get("bid_krw"),
                "ask_krw": q_kmbc.get("ask_krw"),
                "mid_krw": q_kmbc.get("mid_krw", sp_won),
                "source": "KMBC",
                "maturity": leg["maturity"],
                "days": leg["days_from_spot"],
                "fwd_theo": round(leg["fwd_theo"], 4),
                "df_usd": round(leg["df_usd"], 6),
                "df_krw": round(leg["df_krw"], 6)
            })
        else:
            # CIP DF Inverse for > 1Y (Simplified RIC as '-')
            hybrid_quotes.append({
                "tenor": t,
                "ric": "-",
                "type": "CIP (DF 역산)",
                "bid": None,
                "ask": None,
                "mid": sp_jeon,
                "bid_krw": None,
                "ask_krw": None,
                "mid_krw": round(sp_won, 4),
                "source": "CIP_Inverse",
                "maturity": leg["maturity"],
                "days": leg["days_from_spot"],
                "fwd_theo": round(leg["fwd_theo"], 4),
                "df_usd": round(leg["df_usd"], 6),
                "df_krw": round(leg["df_krw"], 6)
            })
        
    return {
        "status": "success",
        "data": {
            "currency": "USD_FWD",
            "source": "KMBC (<=1Y) + CIP DF Inverse (>1Y) Hybrid Term Structure",
            "pricing_date": p_date.strftime("%Y-%m-%d"),
            "spot_date": s_date.strftime("%Y-%m-%d"),
            "spot_fx": spot_fx,
            "spot_fx_bid": snap_kmbc.get("spot_fx_bid", spot_fx - 0.20),
            "spot_fx_ask": snap_kmbc.get("spot_fx_ask", spot_fx + 0.20),
            "spot_fx_tick": snap_kmbc.get("spot_fx_tick", "Init"),
            "is_connected": snap_kmbc.get("is_connected", False),
            "status_message": snap_kmbc.get("status_message", "Live KMBC & CIP Hybrid Curves"),
            "timestamp": snap_kmbc.get("timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "calendar": "SEB_NYB",
            "kmbc_quotes": hybrid_quotes,
            "quotes": hybrid_quotes,
            "standard_swap_points": hybrid_quotes
        }
    }

@app.post("/api/fwd/price")
def calculate_price_fwd(req: FwdPricingRequest):
    """Price Far Leg schedule pasted by Trader with Margin and CIP calculations"""
    try:
        snap_kmbc = kmbc_fwd_feed.get_snapshot()
        snap_crs = crs_feed.get_snapshot()
        snap_usd = tradition_feed.get_snapshot()
        
        spot_fx = req.spot_fx if (req.spot_fx and req.spot_fx > 0) else snap_kmbc.get("spot_fx", 1357.85)
        p_date = parse_date(req.pricing_date) if req.pricing_date else datetime.date.today()
        cal_code = req.calendar if req.calendar else "SEB_NYB"
        s_date = add_business_days(p_date, 2, cal_code)
        
        crs_quotes = [(q["tenor"], float(q["mid"])) for q in snap_crs.get("quotes", [])]
        krw_fx_curve = get_cached_crs_curve(p_date, s_date, crs_quotes, spot_fx)
        
        usd_quotes = [(q["tenor"], float(q["mid"])) for q in snap_usd.get("quotes", [])]
        usd_sofr_curve = get_cached_sofr_curve(p_date, s_date, usd_quotes)
        
        kmbc_q_list = snap_kmbc.get("quotes", [])
        pricer = FwdSwapPricer(krw_fx_curve, usd_sofr_curve, spot_fx, p_date, cal_code, kmbc_quotes=kmbc_q_list)
        
        # 1. Parse default margin bp allowing 0.0
        def_margin = float(req.default_margin_bp) if req.default_margin_bp is not None else 0.0

        # 2. Parse raw text paste if provided
        far_legs = req.far_legs or []
        if req.raw_paste_text and req.raw_paste_text.strip():
            pasted_legs = parse_trader_paste_text(req.raw_paste_text, def_margin)
            if pasted_legs:
                far_legs = pasted_legs
                
        # If still empty, provide sample default tranches
        if not far_legs:
            far_legs = [
                {"maturity": "2026-11-30", "notional_usd": 1_648_000.0, "margin_bp": def_margin},
                {"maturity": "2027-02-26", "notional_usd": 1_676_000.0, "margin_bp": def_margin},
                {"maturity": "2027-05-28", "notional_usd": 3_353_000.0, "margin_bp": def_margin},
                {"maturity": "2027-07-28", "notional_usd": 1_649_000.0, "margin_bp": def_margin},
                {"maturity": "2027-11-30", "notional_usd": 1_677_000.0, "margin_bp": def_margin},
                {"maturity": "2028-01-31", "notional_usd": 1_676_000.0, "margin_bp": def_margin}
            ]
            
        result = pricer.price_portfolio(far_legs, default_margin_bp=def_margin)
        return {"status": "success", "data": result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fwd/parse-paste")
def parse_paste_endpoint(req: FwdPricingRequest):
    """Parses trader's pasted Excel text [Maturity, Notional USD, Margin bp] into JSON legs"""
    def_margin = float(req.default_margin_bp) if req.default_margin_bp is not None else 0.0
    pasted = parse_trader_paste_text(req.raw_paste_text or "", def_margin)
    return {"status": "success", "data": pasted}

@app.post("/api/fwd/reload-and-price")
def reload_and_price_fwd(req: FwdPricingRequest):
    """[FWD ONE-SHOT F9] Reload latest KMBC market feed and calculate FWD pricing in a single step"""
    try:
        kmbc_fwd_feed.trigger_on_demand_refresh()
    except Exception:
        pass
    pricing_res = calculate_price_fwd(req)
    snap_res = get_fwd_market_snapshot(pricing_date=None, reload=False)
    pricing_data = pricing_res.get("data") if isinstance(pricing_res, dict) else pricing_res
    snap_data = snap_res.get("data") if isinstance(snap_res, dict) else snap_res
    return {
        "status": "success",
        "data": pricing_data,
        "pricing": pricing_data,
        "market_snapshot": snap_data
    }

@app.post("/api/fwd/quotes/update")
def update_quote_fwd(req: QuoteUpdateRequest):
    """Update manual KMBC swap point quote or Spot FX"""
    updated = kmbc_fwd_feed.update_quote(req.tenor, req.mid)
    return {"status": "success", "message": f"KMBC Quote for {req.tenor} updated to {req.mid}"}

@app.post("/api/fwd/quotes/reset")
def reset_quotes_fwd():
    """Reset KMBC swap point quotes to baseline"""
    kmbc_fwd_feed.reset_quotes()
    return {"status": "success", "message": "All KMBC quotes reset to baseline"}


# ==============================================================================
# CALENDAR MANAGEMENT & AUTOMATED DAILY UPDATE APIS
# ==============================================================================
from server.calendar_manager import (
    get_calendar_status, reload_holidays, add_holiday
)
from server.holiday_updater import holiday_updater_service

class HolidayAddRequest(BaseModel):
    cal_code: str = "SEB"
    date_str: str # 'YYYY-MM-DD'

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """
    Startup and shutdown. on_event is deprecated and slated for removal, and a
    DeprecationWarning on every boot is one more line hiding the ones that matter.
    """
    task = asyncio.create_task(
        holiday_updater_service.start_daily_scheduler(run_at_hour=0, run_at_minute=5))
    try:
        yield
    finally:
        task.cancel()


app.router.lifespan_context = _lifespan

@app.get("/api/calendar/status")
def get_calendar_info():
    """Retrieve status of all 18 holiday calendars including holiday counts and last reload time"""
    status = get_calendar_status()
    status["updater_status"] = {
        "last_sync_time": holiday_updater_service.last_sync_time,
        "last_sync_source": holiday_updater_service.last_sync_source,
        "is_scheduler_active": holiday_updater_service.is_running_scheduler
    }
    return {"status": "success", "data": status}

@app.post("/api/calendar/reload")
def trigger_calendar_reload():
    """Force reload holidays_data.json into memory cache with zero downtime"""
    status = reload_holidays()
    return {"status": "success", "message": "Holidays successfully reloaded into memory cache", "data": status}

@app.post("/api/calendar/sync")
def trigger_calendar_sync(source: str = "lseg"):
    """Trigger immediate calendar update from configured daily sync source (lseg, murex, statutory, auto)"""
    src = source.lower()
    if src in ("lseg", "auto"):
        res = holiday_updater_service.sync_from_lseg_api()
        if not res.get("success") and src == "auto":
            if os.path.exists(holiday_updater_service.murex_export_path):
                res = holiday_updater_service.sync_from_murex_export()
            else:
                res = holiday_updater_service.sync_statutory_korean_holidays()
    elif src == "murex":
        res = holiday_updater_service.sync_from_murex_export()
    else:
        res = holiday_updater_service.sync_statutory_korean_holidays()
    return {"status": "success", "data": res}

@app.post("/api/calendar/add-holiday")
def add_custom_holiday(req: HolidayAddRequest):
    """Dynamically register a new holiday for any calendar (persisted to holidays_data.json)"""
    ok = add_holiday(req.cal_code, req.date_str, persist=True)
    if ok:
        return {"status": "success", "message": f"Holiday {req.date_str} added to {req.cal_code.upper()} calendar"}
    raise HTTPException(status_code=500, detail="Failed to persist holiday")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

@app.get("/healthz", include_in_schema=False)
def healthz():
    """What a host polls to decide the service is up. No credentials, no data."""
    return {"status": "ok"}


@app.middleware("http")
async def _access_gate(request: Request, call_next):
    from server.access import gate
    blocked = gate(request.url.path, request.headers.get("authorization"))
    if blocked is not None:
        return blocked
    return await call_next(request)


# ==============================================================================
# STATIC DASHBOARD MOUNT
# ==============================================================================
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
os.makedirs(static_dir, exist_ok=True)

# The dashboard's asset URLs carried a hand-written version query (app.js?v=4.2) that
# nobody remembered to bump. A browser that had cached that URL kept running the old
# script against freshly deployed markup - which does not look like a stale cache, it
# looks like the change was never made. Stamp the URLs from the files on disk instead,
# so the query changes whenever the file does and never when it does not.
_ASSET_REF = re.compile(r'(?P<attr>href|src)="(?P<file>[\w.-]+\.(?:js|css))(?:\?[^"]*)?"')


def _asset_stamp(name: str) -> str:
    try:
        st = os.stat(os.path.join(static_dir, name))
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return "0"


def _stamped_page(name: str) -> str:
    with open(os.path.join(static_dir, name), encoding="utf-8") as fh:
        html = fh.read()
    return _ASSET_REF.sub(
        lambda m: f'{m.group("attr")}="{m.group("file")}?v={_asset_stamp(m.group("file"))}"',
        html)


def _page_response(name: str) -> Response:
    # no-store on the page itself: it is small, and it is what carries the stamps.
    return Response(_stamped_page(name), media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
async def dashboard():
    return _page_response("index.html")


@app.get("/m", include_in_schema=False)
@app.get("/m/", include_in_schema=False)
async def mobile_dashboard():
    """
    The phone build: the same pricing API, a deliberately smaller screen.

    A separate page rather than the desktop one with things hidden. index.html plus
    app.js is 6,500 lines a phone would download and run in full before showing a
    number it mostly cannot fit anyway, and the two would then have to be kept from
    breaking each other on every change.

    It is not exempt from the access gate - the middleware covers every path except
    /healthz, so this is closed on a hosted deployment exactly as / is.
    """
    return _page_response("m.html")


app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # A host supplies PORT and needs every interface; on the desk, stay on localhost.
    port = int(os.environ.get("PORT", "8000"))
    hosted = bool(os.environ.get("PORT"))
    uvicorn.run("server.app:app",
                host="0.0.0.0" if hosted else "127.0.0.1",
                port=port, reload=not hosted)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            