"""
KOFR OIS Live Market Feed Handler
- Connects to LSEG Workspace (Refinitiv Eikon Desktop API)
- Primary RIC source: Tradition Seoul ('TRDS') and KMBC KOFR OIS ('KRWKFxxOIS=TRDS' / 'KMBC')
- Manages real-time caching, thread-safe access, and manual overrides
"""

import os
import time
import json
import threading
import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lseg_config.json"))

# Standard Tradition Seoul (TRDS) & KMBC KOFR OIS RIC Table
KOFR_REAL_RIC_DEFS = [
    {"tenor": "ON",  "ric": "KRWKOFR=",        "bid": 2.8042, "ask": 2.8042, "mid": 2.8042, "is_fix": True},
    {"tenor": "3M",  "ric": "KRWKF3MOIS=KMBC", "bid": 2.9750, "ask": 3.0250, "mid": 3.0000, "is_fix": True},
    {"tenor": "6M",  "ric": "KRWKF6MOIS=KMBC", "bid": 3.1400, "ask": 3.1900, "mid": 3.1650, "is_fix": False},
    {"tenor": "9M",  "ric": "KRWKF9MOIS=KMBC", "bid": 3.2775, "ask": 3.3275, "mid": 3.3025, "is_fix": False},
    {"tenor": "1Y",  "ric": "KRWKF1YOIS=KMBC", "bid": 3.3475, "ask": 3.4075, "mid": 3.3775, "is_fix": False},
    {"tenor": "18M", "ric": "KRWKF18MOIS=KMBC","bid": 3.5200, "ask": 3.5800, "mid": 3.5500, "is_fix": False},
    {"tenor": "2Y",  "ric": "KRWKF2YOIS=KMBC", "bid": 3.5275, "ask": 3.5875, "mid": 3.5575, "is_fix": False},
    {"tenor": "3Y",  "ric": "KRWKF3YOIS=KMBC", "bid": 3.6225, "ask": 3.6825, "mid": 3.6525, "is_fix": False},
    {"tenor": "4Y",  "ric": "KRWKF4YOIS=KMBC", "bid": 3.6875, "ask": 3.7475, "mid": 3.7175, "is_fix": False},
    {"tenor": "5Y",  "ric": "KRWKF5YOIS=KMBC", "bid": 3.7350, "ask": 3.7950, "mid": 3.7650, "is_fix": False},
    {"tenor": "7Y",  "ric": "KRWKF7YOIS=KMBC", "bid": 3.7925, "ask": 3.8525, "mid": 3.8225, "is_fix": False},
    {"tenor": "8Y",  "ric": "KRWKF8YOIS=KMBC", "bid": 3.8000, "ask": 3.8600, "mid": 3.8300, "is_fix": False},
    {"tenor": "9Y",  "ric": "KRWKF9YOIS=KMBC", "bid": 3.8025, "ask": 3.8625, "mid": 3.8325, "is_fix": False},
    {"tenor": "10Y", "ric": "KRWKF10YOIS=KMBC","bid": 3.8050, "ask": 3.8650, "mid": 3.8350, "is_fix": False},
    {"tenor": "12Y", "ric": "KRWKF12YOIS=KMBC","bid": 3.8050, "ask": 3.8650, "mid": 3.8350, "is_fix": False},
    {"tenor": "15Y", "ric": "KRWKF15YOIS=KMBC","bid": 3.8000, "ask": 3.8600, "mid": 3.8300, "is_fix": False},
    {"tenor": "20Y", "ric": "KRWKF20YOIS=KMBC","bid": 3.6875, "ask": 3.7475, "mid": 3.7175, "is_fix": False},
    {"tenor": "25Y", "ric": "KRWKF25YOIS=KMBC","bid": 3.6000, "ask": 3.6600, "mid": 3.6300, "is_fix": False},
    {"tenor": "30Y", "ric": "KRWKF30YOIS=KMBC","bid": 3.5000, "ask": 3.5600, "mid": 3.5300, "is_fix": False}
]

class KOFRMarketFeed:
    def __init__(self):
        self._lock = threading.Lock()
        self._quotes: Dict[str, Dict[str, Any]] = {}
        self._is_live_connected = False
        self._last_update_ts = datetime.datetime.now()
        self._app_key: Optional[str] = None
        self._ek_initialized = False
        self._refresh_event = threading.Event()
        self._running = True
        
        self._load_app_key()
        self._init_baseline()
        
        # Background polling disabled to prevent Eikon rate limit exhaustion
        self._running = False
        self._thread = None

    def _load_app_key(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                    self._app_key = cfg.get("app_key")
            except Exception:
                pass

    def _init_baseline(self):
        with self._lock:
            for item in KOFR_REAL_RIC_DEFS:
                t = item["tenor"]
                self._quotes[t] = {
                    "tenor": t,
                    "ric": item["ric"],
                    "bid": float(item["bid"]),
                    "ask": float(item["ask"]),
                    "mid": float(item["mid"]),
                    "prev_close": float(item["mid"]),
                    "chg_bp": 0.0,
                    "is_overridden": False,
                    "last_tick": datetime.datetime.now().strftime("%H:%M:%S") + " (Base)"
                }

    def _dedicated_fetch_loop(self):
        """Relaxed background worker (60s interval)"""
        time.sleep(15.0)
        while self._running:
            self._refresh_event.wait(timeout=60.0)
            self._refresh_event.clear()
            if self._running:
                try:
                    self._do_eikon_fetch()
                except Exception:
                    pass

    def trigger_on_demand_refresh(self):
        self._do_eikon_fetch()

    def get_snapshot(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Instant (<0.1ms) thread-safe snapshot with on-demand refresh"""
        if force_refresh:
            self._do_eikon_fetch()
            
        with self._lock:
            ordered_quotes = []
            for item in KOFR_REAL_RIC_DEFS:
                t = item["tenor"]
                if t in self._quotes:
                    ordered_quotes.append(dict(self._quotes[t]))
                    
            status_msg = "● LIVE LSEG Workspace (KOFR OIS KMBC)" if self._is_live_connected else "Offline KOFR Baseline"
            source_lbl = "LSEG Workspace (KRW KOFR OIS KMBC Feed)" if self._is_live_connected else "KRW KOFR Market Baseline (KMBC)"
            
            return {
                "source": source_lbl,
                "status_message": status_msg,
                "is_live_connected": self._is_live_connected,
                "has_app_key": bool(self._app_key),
                "timestamp": self._last_update_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "epoch_ms": int(self._last_update_ts.timestamp() * 1000),
                "quotes": ordered_quotes
            }

    def _do_eikon_fetch(self):
        try:
            from .eikon_rate_limiter import eikon_manager
            rics = [item["ric"] for item in KOFR_REAL_RIC_DEFS]
            fields = ["PRIMACT_1", "SEC_ACT_1", "CF_LAST", "CF_CLOSE", "BID", "ASK"]
            df, err = eikon_manager.get_data(rics, fields)
            if df is not None and not df.empty:
                ric_to_row = {}
                for idx, row in df.iterrows():
                    inst = str(row.get("Instrument", "")).strip().upper()
                    ric_to_row[inst] = row

                now_str = datetime.datetime.now().strftime("%H:%M:%S") + " (Live)"
                with self._lock:
                    for item in KOFR_REAL_RIC_DEFS:
                        t = item["tenor"]
                        r_code = item["ric"].strip().upper()
                        
                        if t in self._quotes and self._quotes[t]["is_overridden"]:
                            continue
                            
                        if r_code in ric_to_row:
                            r_data = ric_to_row[r_code]
                            prim = r_data.get("PRIMACT_1")
                            sec = r_data.get("SEC_ACT_1")
                            last = r_data.get("CF_LAST")
                            prev_c = r_data.get("CF_CLOSE")
                            raw_bid = r_data.get("BID")
                            raw_ask = r_data.get("ASK")

                            bid_val = prim if pd.notnull(prim) and isinstance(prim, (int, float)) and prim > 0 else raw_bid
                            ask_val = sec if pd.notnull(sec) and isinstance(sec, (int, float)) and sec > 0 else raw_ask
                            last_val = last if pd.notnull(last) and isinstance(last, (int, float)) and last > 0 else None

                            if bid_val is not None and ask_val is not None and pd.notnull(bid_val) and pd.notnull(ask_val):
                                bid = float(bid_val)
                                ask = float(ask_val)
                                mid = round((bid + ask) / 2.0, 4)
                            elif last_val is not None and pd.notnull(last_val):
                                mid = float(last_val)
                                bid = round(mid - 0.01, 4)
                                ask = round(mid + 0.01, 4)
                            else:
                                continue

                            prev = float(prev_c) if (prev_c is not None and pd.notnull(prev_c) and isinstance(prev_c, (int, float))) else self._quotes[t]["prev_close"]
                            chg_bp = round((mid - prev) * 100.0, 2)

                            self._quotes[t].update({
                                "bid": bid,
                                "ask": ask,
                                "mid": mid,
                                "prev_close": prev,
                                "chg_bp": chg_bp,
                                "last_tick": now_str
                            })
                self._is_live_connected = True
                self._last_update_ts = datetime.datetime.now()
        except Exception:
            with self._lock:
                self._is_live_connected = False



    def update_quote(self, tenor: str, new_mid: float) -> bool:
        with self._lock:
            t = tenor.strip().upper()
            if t in self._quotes:
                prev = self._quotes[t]["prev_close"]
                spread_half = 0.0100
                self._quotes[t].update({
                    "bid": round(new_mid - spread_half, 4),
                    "ask": round(new_mid + spread_half, 4),
                    "mid": round(new_mid, 4),
                    "chg_bp": round((new_mid - prev) * 100.0, 2),
                    "is_overridden": True,
                    "last_tick": datetime.datetime.now().strftime("%H:%M:%S") + " (Manual)"
                })
                self._last_update_ts = datetime.datetime.now()
                return True
        return False

    def reset_to_base(self):
        self._init_baseline()
        self.trigger_on_demand_refresh()

kofr_feed = KOFRMarketFeed()
