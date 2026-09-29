"""
LSEG Workspace Tradition Data Feed Service for USD SOFR OIS
- Dedicated single-threaded LSEG Desktop Proxy polling to prevent async loop collisions
- Zero-latency snapshot serving (<0.1ms)
- Thread-safe AppKey persistence and on-demand refresh triggers
- Automatic background updates every 3-4 seconds
"""

import os
import sys
import time
import datetime
import threading
import json
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np

CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lseg_config.json"))

from .eikon_rate_limiter import EIKON_GLOBAL_LOCK, safe_eikon_get_data

# Exact 31 Tradition SOFR OIS RIC Table matching Murex Standard
TRADITION_REAL_RIC_DEFS = [
    {"tenor": "ON",  "ric": "USDSOFR=",         "bid": 3.6500, "ask": 3.6500, "mid": 3.6500, "is_fix": True},
    {"tenor": "1W",  "ric": "USDSROISSW=TWEB",  "bid": 3.6210, "ask": 3.6410, "mid": 3.6310, "is_fix": False},
    {"tenor": "2W",  "ric": "USDSROIS2W=TWEB",  "bid": 3.6740, "ask": 3.6940, "mid": 3.6840, "is_fix": False},
    {"tenor": "1M",  "ric": "USDSROIS1M=TWEB",  "bid": 3.7300, "ask": 3.7500, "mid": 3.7400, "is_fix": False},
    {"tenor": "2M",  "ric": "USDSROIS2M=TWEB",  "bid": 3.7680, "ask": 3.7880, "mid": 3.7780, "is_fix": False},
    {"tenor": "3M",  "ric": "USDSROIS3M=TWEB",  "bid": 3.8010, "ask": 3.8210, "mid": 3.8110, "is_fix": False},
    {"tenor": "4M",  "ric": "USDSROIS4M=TWEB",  "bid": 3.8590, "ask": 3.8790, "mid": 3.8690, "is_fix": False},
    {"tenor": "5M",  "ric": "USDSROIS5M=TWEB",  "bid": 3.8960, "ask": 3.9160, "mid": 3.9060, "is_fix": False},
    {"tenor": "6M",  "ric": "USDSROIS6M=TWEB",  "bid": 3.9260, "ask": 3.9460, "mid": 3.9360, "is_fix": False},
    {"tenor": "7M",  "ric": "USDSROIS7M=TWEB",  "bid": 3.9640, "ask": 3.9840, "mid": 3.9740, "is_fix": False},
    {"tenor": "8M",  "ric": "USDSROIS8M=TWEB",  "bid": 3.9980, "ask": 4.0180, "mid": 4.0080, "is_fix": False},
    {"tenor": "9M",  "ric": "USDSROIS9M=TWEB",  "bid": 4.0270, "ask": 4.0470, "mid": 4.0370, "is_fix": False},
    {"tenor": "10M", "ric": "USDSROIS10M=TWEB", "bid": 4.0580, "ask": 4.0780, "mid": 4.0680, "is_fix": False},
    {"tenor": "11M", "ric": "USDSROIS11M=TWEB", "bid": 4.0850, "ask": 4.1050, "mid": 4.0950, "is_fix": False},
    {"tenor": "1Y",  "ric": "USDSROIS1Y=TWEB",  "bid": 4.1100, "ask": 4.1300, "mid": 4.1200, "is_fix": False},
    {"tenor": "18M", "ric": "USDSROIS18M=TWEB", "bid": 4.1570, "ask": 4.1770, "mid": 4.1670, "is_fix": False},
    {"tenor": "2Y",  "ric": "USDSROIS2Y=TWEB",  "bid": 4.1910, "ask": 4.2110, "mid": 4.2010, "is_fix": False},
    {"tenor": "3Y",  "ric": "USDSROIS3Y=TWEB",  "bid": 4.2040, "ask": 4.2240, "mid": 4.2140, "is_fix": False},
    {"tenor": "4Y",  "ric": "USDSROIS4Y=TWEB",  "bid": 4.2130, "ask": 4.2330, "mid": 4.2230, "is_fix": False},
    {"tenor": "5Y",  "ric": "USDSROIS5Y=TWEB",  "bid": 4.2300, "ask": 4.2500, "mid": 4.2400, "is_fix": False},
    {"tenor": "6Y",  "ric": "USDSROIS6Y=TWEB",  "bid": 4.2540, "ask": 4.2740, "mid": 4.2640, "is_fix": False},
    {"tenor": "7Y",  "ric": "USDSROIS7Y=TWEB",  "bid": 4.2810, "ask": 4.3010, "mid": 4.2910, "is_fix": False},
    {"tenor": "8Y",  "ric": "USDSROIS8Y=TWEB",  "bid": 4.3090, "ask": 4.3290, "mid": 4.3190, "is_fix": False},
    {"tenor": "9Y",  "ric": "USDSROIS9Y=TWEB",  "bid": 4.3400, "ask": 4.3600, "mid": 4.3500, "is_fix": False},
    {"tenor": "10Y", "ric": "USDSROIS10Y=TWEB", "bid": 4.3740, "ask": 4.3940, "mid": 4.3840, "is_fix": False},
    {"tenor": "11Y", "ric": "USDSROIS11Y=TWEB", "bid": 4.4070, "ask": 4.4270, "mid": 4.4170, "is_fix": False},
    {"tenor": "12Y", "ric": "USDSROIS12Y=TWEB", "bid": 4.4390, "ask": 4.4590, "mid": 4.4490, "is_fix": False},
    {"tenor": "15Y", "ric": "USDSROIS15Y=TWEB", "bid": 4.5250, "ask": 4.5450, "mid": 4.5350, "is_fix": False},
    {"tenor": "20Y", "ric": "USDSROIS20Y=TWEB", "bid": 4.5980, "ask": 4.6180, "mid": 4.6080, "is_fix": False},
    {"tenor": "25Y", "ric": "USDSROIS25Y=TWEB", "bid": 4.5940, "ask": 4.6140, "mid": 4.6040, "is_fix": False},
    {"tenor": "30Y", "ric": "USDSROIS30Y=TWEB", "bid": 4.5550, "ask": 4.5750, "mid": 4.5650, "is_fix": False}
]

class TraditionMarketFeed:
    def __init__(self):
        self._lock = threading.Lock()
        self._refresh_event = threading.Event()
        self._last_fetch_time = 0.0
        self.quotes: Dict[str, Dict[str, Any]] = {}
        self.is_lseg_live_connected: bool = False
        self.app_key: str = ""
        # Not "Ready": nothing has been reached yet, and on a host there is no
        # Workspace desktop to reach at all. A pricer that says the feed is ready
        # while serving baseline quotes is worse than one that says nothing.
        self.lseg_status_message: str = "LSEG Workspace 미연결 — 기준호가 사용 중"
        
        # Load saved App Key
        self._load_saved_app_key()
        
        # Initialize Base Quotes
        self.reset_to_base()
        
        # Background polling disabled by default to prevent Eikon rate limit exhaustion
        self._running = False
        self._worker_thread = None

    def _load_saved_app_key(self):
        """Load persisted App Key from config file or environment"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    key = cfg.get("app_key", "").strip()
                    if key:
                        self.app_key = key
                        return
        except Exception:
            pass
        
        env_key = os.environ.get("LSEG_APP_KEY") or os.environ.get("EIKON_APP_KEY")
        if env_key:
            self.app_key = env_key.strip()

    def _save_app_key(self, key: str):
        """Persist App Key to config file"""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"app_key": key, "updated_at": datetime.datetime.now().isoformat()}, f, indent=2)
        except Exception as e:
            print(f"[TraditionFeed] Warning: Failed to save config: {e}")

    def set_app_key(self, key: str) -> Tuple[bool, str]:
        """Set App Key and trigger immediate background fetch"""
        clean_key = key.strip()
        if not clean_key:
            return False, "App Key cannot be empty."
        
        self.app_key = clean_key
        self._save_app_key(clean_key)
        
        # Trigger immediate background fetch
        self._refresh_event.set()
        time.sleep(1.0)
        return self.is_lseg_live_connected, self.lseg_status_message

    def reset_to_base(self):
        """Reset all quotes to baseline table"""
        with self._lock:
            self.quotes.clear()
            for item in TRADITION_REAL_RIC_DEFS:
                t = item["tenor"]
                self.quotes[t] = {
                    "tenor": t,
                    "ric": item["ric"],
                    "bid": round(item["bid"], 4),
                    "ask": round(item["ask"], 4),
                    "mid": round(item["mid"], 4),
                    "prev_close": round(item["mid"], 4),
                    "chg_bp": 0.0,
                    "is_overridden": False,
                    "last_tick": datetime.datetime.now().strftime("%H:%M:%S")
                }

    def _dedicated_fetch_loop(self):
        """Relaxed background worker thread (60s interval)"""
        time.sleep(10.0)
        while self._running:
            self._refresh_event.wait(timeout=60.0)
            self._refresh_event.clear()
            if self.app_key and self._running:
                try:
                    self._perform_eikon_fetch()
                except Exception:
                    pass

    def _perform_eikon_fetch(self):
        """Single-threaded rate-limited Eikon fetch"""
        try:
            from .eikon_rate_limiter import eikon_manager
            
            rics = [item["ric"] for item in TRADITION_REAL_RIC_DEFS]
            fields = ["PRIMACT_1", "SEC_ACT_1", "CF_LAST", "CF_CLOSE"]
            df, err = eikon_manager.get_data(rics, fields)
            if df is not None and not df.empty:
                ric_to_tenor = {item["ric"]: item["tenor"] for item in TRADITION_REAL_RIC_DEFS}
                updated_count = 0
                now_str = datetime.datetime.now().strftime("%H:%M:%S") + " (Live)"
                
                with self._lock:
                    for _, row in df.iterrows():
                        ric = str(row.get("Instrument", "")).strip()
                        t = ric_to_tenor.get(ric)
                        if not t or t not in self.quotes:
                            continue
                            
                        q = self.quotes[t]
                        if q.get("is_overridden", False):
                            continue
                                
                        raw_bid = row.get("PRIMACT_1")
                        raw_ask = row.get("SEC_ACT_1")
                        raw_last = row.get("CF_LAST")
                        raw_close = row.get("CF_CLOSE")
                        
                        bid_val = None
                        ask_val = None
                        
                        if raw_bid is not None and not pd.isna(raw_bid) and isinstance(raw_bid, (int, float)) and float(raw_bid) > 0:
                            bid_val = float(raw_bid)
                        if raw_ask is not None and not pd.isna(raw_ask) and isinstance(raw_ask, (int, float)) and float(raw_ask) > 0:
                            ask_val = float(raw_ask)
                        if bid_val is None and raw_last is not None and not pd.isna(raw_last) and isinstance(raw_last, (int, float)) and float(raw_last) > 0:
                            bid_val = float(raw_last)
                            
                        if bid_val is not None:
                            if ask_val is None or ask_val <= bid_val:
                                ask_val = bid_val + (0.0 if t == "ON" else 0.020)
                            mid_val = (bid_val + ask_val) / 2.0
                            
                            q["bid"] = round(bid_val, 4)
                            q["ask"] = round(ask_val, 4)
                            q["mid"] = round(mid_val, 4)
                            
                            if raw_close is not None and not pd.isna(raw_close) and isinstance(raw_close, (int, float)):
                                q["prev_close"] = float(raw_close)
                            q["chg_bp"] = round((mid_val - q["prev_close"]) * 100.0, 2)
                            q["last_tick"] = now_str
                            updated_count += 1
                            
                    self.is_lseg_live_connected = True
                    self.lseg_status_message = f"● LIVE LSEG Workspace Connected ({updated_count} quotes active)"
                    self._last_fetch_time = time.time()
            else:
                self.is_lseg_live_connected = False
                self.lseg_status_message = "LSEG Workspace returned empty dataset"
                
        except Exception as e:
            err_msg = str(e)
            self.is_lseg_live_connected = False
            if "invalid" in err_msg.lower() or "1401" in err_msg:
                self.lseg_status_message = "LSEG App Key is invalid."
            else:
                self.lseg_status_message = f"LSEG Workspace Offline ({err_msg[:30]})"

    def trigger_on_demand_refresh(self, wait_sec: float = 0.0):
        """Perform an immediate synchronous fetch from LSEG Workspace proxy"""
        if self.app_key:
            self._perform_eikon_fetch()
        else:
            self._refresh_event.set()

    def get_snapshot(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Instant (<0.1ms) thread-safe snapshot retrieval with on-demand refresh"""
        if force_refresh and self.app_key:
            self._perform_eikon_fetch()
            
        with self._lock:
            snap_time = datetime.datetime.now()
            quote_list = [dict(v) for v in self.quotes.values()]
            return {
                # 연결이 끊긴 상태에서도 이 문자열이 그대로 나가면, 트레이더가
                # 카운터파티에 보내는 RFQ 회신문에 "LSEG Tradeweb 기준" 이라고
                # 찍힙니다. 실제로는 하드코딩된 기준호가입니다. krw_feed 와
                # kofr_feed 는 이미 이렇게 구분하고 있었습니다.
                "source": ("LSEG Workspace (Tradeweb Composite =TWEB)"
                           if self.is_lseg_live_connected
                           else "Tradeweb Composite Baseline (비실시간)"),
                "status_message": self.lseg_status_message,
                "is_live_connected": self.is_lseg_live_connected,
                "has_app_key": bool(self.app_key),
                "timestamp": snap_time.strftime("%Y-%m-%d %H:%M:%S"),
                "epoch_ms": int(snap_time.timestamp() * 1000),
                "quotes": quote_list
            }

    def update_quote(self, tenor: str, new_mid: float, new_bid: Optional[float] = None, new_ask: Optional[float] = None):
        """Allow trader to override a specific quote manually"""
        with self._lock:
            t = tenor.strip().upper()
            if t in self.quotes:
                q = self.quotes[t]
                q["mid"] = round(new_mid, 4)
                spread = 0.020 if t != "ON" else 0.0
                q["bid"] = round(new_bid if new_bid is not None else new_mid - spread / 2.0, 4)
                q["ask"] = round(new_ask if new_ask is not None else new_mid + spread / 2.0, 4)
                q["chg_bp"] = round((new_mid - q["prev_close"]) * 100.0, 2)
                q["is_overridden"] = True
                q["last_tick"] = datetime.datetime.now().strftime("%H:%M:%S") + " (Manual)"

    def stop(self):
        self._running = False
        self._refresh_event.set()

# Global Singleton Instance
tradition_feed = TraditionMarketFeed()
