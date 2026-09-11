"""
CRS Live Market Data Feed Provider
Connects to LSEG Workspace (Desktop Proxy) to stream Prebon Yamane KRUSQ CRS quotes (KRUSQxx=PREA) and USD/KRW Spot FX (KRW=).
"""

import os
import json
import time
import datetime
import threading
from typing import Dict, Any, List, Optional
import pandas as pd

# Global thread lock for Eikon Desktop Proxy
from server.tradition_feed import EIKON_GLOBAL_LOCK

class CRSFeed:
    """
    Manages live streaming and polling of Prebon Yamane KRUSQ CRS quotes and Spot FX from LSEG Workspace.
    """
    DEFAULT_CRS_QUOTES = [
        {"tenor": "1Y", "ric": "KRUSQBSR1Y=PREA", "bid": 3.1400, "ask": 3.7400, "mid": 3.4400, "prev_close": 3.4400, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "18M", "ric": "KRUSQBSR18M=PREA", "bid": 3.1800, "ask": 3.7800, "mid": 3.4800, "prev_close": 3.4800, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "2Y", "ric": "KRUSQBSR2Y=PREA", "bid": 3.1850, "ask": 3.7850, "mid": 3.4850, "prev_close": 3.4850, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "3Y", "ric": "KRUSQBSR3Y=PREA", "bid": 3.2600, "ask": 3.8600, "mid": 3.5600, "prev_close": 3.5600, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "4Y", "ric": "KRUSQBSR4Y=PREA", "bid": 3.2950, "ask": 3.8950, "mid": 3.5950, "prev_close": 3.5950, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "5Y", "ric": "KRUSQBSR5Y=PREA", "bid": 3.2950, "ask": 3.8950, "mid": 3.5950, "prev_close": 3.5950, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "6Y", "ric": "KRUSQBSR6Y=PREA", "bid": 3.3000, "ask": 3.9000, "mid": 3.6000, "prev_close": 3.6000, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "7Y", "ric": "KRUSQBSR7Y=PREA", "bid": 3.3500, "ask": 3.9500, "mid": 3.6500, "prev_close": 3.6500, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "8Y", "ric": "KRUSQBSR8Y=PREA", "bid": 3.3500, "ask": 3.9500, "mid": 3.6500, "prev_close": 3.6500, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "9Y", "ric": "KRUSQBSR9Y=PREA", "bid": 3.2950, "ask": 3.8950, "mid": 3.5950, "prev_close": 3.5950, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "10Y", "ric": "KRUSQBSR10Y=PREA", "bid": 3.2450, "ask": 3.8450, "mid": 3.5450, "prev_close": 3.5450, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "12Y", "ric": "KRUSQBSR12Y=PREA", "bid": 3.2100, "ask": 3.8100, "mid": 3.5100, "prev_close": 3.5100, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "15Y", "ric": "KRUSQBSR15Y=PREA", "bid": 3.1850, "ask": 3.7850, "mid": 3.4850, "prev_close": 3.4850, "chg_bp": 0.0, "last_tick": "Init (Base)"},
        {"tenor": "20Y", "ric": "KRUSQBSR20Y=PREA", "bid": 3.1350, "ask": 3.7350, "mid": 3.4350, "prev_close": 3.4350, "chg_bp": 0.0, "last_tick": "Init (Base)"},
    ]

    def __init__(self, config_path: str = "lseg_config.json"):
        self.config_path = config_path
        self.quotes: Dict[str, Dict[str, Any]] = {q["tenor"]: dict(q) for q in self.DEFAULT_CRS_QUOTES}
        self.spot_fx: float = 1346.15
        self.spot_fx_tick: str = "Init (Base)"
        self.is_connected = False
        self.status_message = "Initializing Prebon KRUSQ CRS Feed..."
        self.last_update = datetime.datetime.now()
        self.ek_session = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        self._load_config()
        self._init_eikon()
        self._start_worker()

    def _load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                self.config = {"app_key": "YOUR_APP_KEY", "port": 9000}
        except Exception as e:
            self.config = {"app_key": "YOUR_APP_KEY", "port": 9000}

    def _init_eikon(self):
        try:
            import eikon as ek
            self.ek = ek
            app_key = self.config.get("app_key", "")
            port = self.config.get("port", 9000)
            if app_key and app_key != "YOUR_APP_KEY":
                self.ek.set_app_key(app_key)
                self.ek.set_port_number(port)
                self.is_connected = True
                self.status_message = "🟢 LIVE LSEG Workspace (Prebon KRUSQ CRS Feed)"
            else:
                self.is_connected = False
                self.status_message = "🟡 Offline (Using Prebon Baseline Quotes)"
        except Exception as e:
            self.is_connected = False
            self.status_message = f"🔴 Eikon Init Error: {str(e)}"

    def _start_worker(self):
        # Background worker disabled to prevent Eikon rate limit exhaustion
        self._worker_thread = None

    def _poll_loop(self):
        """Relaxed background worker (60s interval)"""
        time.sleep(20.0)
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=60.0)
            if self.is_connected and not self._stop_event.is_set():
                try:
                    self.poll_quotes()
                except Exception:
                    pass

    def trigger_on_demand_refresh(self) -> bool:
        """Triggers an immediate synchronous poll from LSEG Workspace proxy"""
        return self.poll_quotes()

    def get_snapshot(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Instant (<0.1ms) snapshot with on-demand refresh"""
        if force_refresh:
            self.poll_quotes()
            
        with self._lock:
            now_ts = self.last_update.strftime("%Y-%m-%d %H:%M:%S")
            return {
                "source": "LSEG Workspace (Prebon KRUSQ CRS Feed)",
                "status_message": self.status_message,
                "is_connected": self.is_connected,
                "is_live_connected": self.is_connected,
                "timestamp": now_ts,
                "last_update": now_ts,
                "epoch_ms": int(self.last_update.timestamp() * 1000),
                "spot_fx": round(self.spot_fx, 2),
                "spot_fx_tick": self.spot_fx_tick,
                "quotes": list(self.quotes.values())
            }

    def poll_quotes(self) -> bool:
        try:
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            from .eikon_rate_limiter import eikon_manager
            
            spot_rics = ["KRW=", "KRW=TRDS", "KRW=PREA"]
            crs_rics = [q["ric"] for q in self.DEFAULT_CRS_QUOTES]
            all_rics = spot_rics + crs_rics
            fields = ["CF_LAST", "BID", "ASK", "PRIMACT_1", "SEC_ACT_1"]

            df_all, err = eikon_manager.get_data(all_rics, fields)
            if df_all is not None and not df_all.empty:
                # 1. Process Spot FX
                df_spot = df_all[df_all["Instrument"].isin(spot_rics)]
                for _, srow in df_spot.iterrows():
                    bid_s = srow.get("BID") if pd.notna(srow.get("BID")) else srow.get("PRIMACT_1")
                    ask_s = srow.get("ASK") if pd.notna(srow.get("ASK")) else srow.get("SEC_ACT_1")
                    last_s = srow.get("CF_LAST")
                    
                    found_spot = None
                    if pd.notna(bid_s) and pd.notna(ask_s) and float(bid_s) > 500 and float(ask_s) > 500:
                        found_spot = (float(bid_s) + float(ask_s)) / 2.0
                    elif pd.notna(last_s) and float(last_s) > 500:
                        found_spot = float(last_s)

                    if found_spot and found_spot > 500:
                        with self._lock:
                            self.spot_fx = round(found_spot, 2)
                            self.spot_fx_tick = f"{now_str} (Live)"
                        break

                # 2. Process CRS Quotes
                df_crs = df_all[df_all["Instrument"].isin(crs_rics)]
                with self._lock:
                    for _, row in df_crs.iterrows():
                        ric = str(row.get("Instrument", "")).strip()
                        if not ric:
                            continue
                        bid = row.get("BID")
                        ask = row.get("ASK")
                        last = row.get("CF_LAST")
                        prim = row.get("PRIMACT_1")
                        sec = row.get("SEC_ACT_1")

                        # Prebon & KMBC broker convention matching reference Excel FEED2:
                        # - PRIMACT_1 / BID = Broker Bid
                        # - SEC_ACT_1 / ASK = Broker Ask
                        # - Mid = (Bid + Ask) / 2.0 (matching =AVERAGE(PRIMACT_1, SEC_ACT_1))
                        bid_val = None
                        if pd.notna(bid) and float(bid) > 0:
                            bid_val = float(bid)
                        elif pd.notna(prim) and float(prim) > 0:
                            bid_val = float(prim)

                        ask_val = None
                        if pd.notna(ask) and float(ask) > 0:
                            ask_val = float(ask)
                        elif pd.notna(sec) and float(sec) > 0:
                            ask_val = float(sec)

                        if bid_val is not None and ask_val is not None:
                            mid_val = (bid_val + ask_val) / 2.0
                        elif pd.notna(last) and float(last) > 0:
                            mid_val = float(last)
                            bid_val = round(mid_val - 0.025, 4)
                            ask_val = round(mid_val + 0.025, 4)
                        elif bid_val is not None:
                            mid_val = bid_val
                            ask_val = round(mid_val + 0.05, 4)
                        elif ask_val is not None:
                            mid_val = ask_val
                            bid_val = round(mid_val - 0.05, 4)
                        else:
                            continue

                        for tenor, item in self.quotes.items():
                            if item["ric"] == ric:
                                item["bid"] = round(bid_val, 4)
                                item["ask"] = round(ask_val, 4)
                                item["mid"] = round(mid_val, 4)
                                prev = item.get("prev_close", item["mid"])
                                item["chg_bp"] = round((item["mid"] - prev) * 100.0, 2)
                                item["last_tick"] = f"{now_str} (Live)"
                                break

                    self.last_update = datetime.datetime.now()
                    self.is_connected = True
                    self.status_message = "🟢 LIVE LSEG Workspace (Prebon KRUSQ CRS Feed)"
                return True
        except Exception as e:
            self.status_message = f"🟡 Feed Warning: {str(e)[:60]}"
            return False
        return False

    def update_spot_fx_manually(self, spot_fx: float):
        with self._lock:
            self.spot_fx = round(spot_fx, 2)
            self.spot_fx_tick = datetime.datetime.now().strftime("%H:%M:%S") + " (Manual)"
            self.last_update = datetime.datetime.now()

    def update_quote_manually(self, tenor: str, mid: float, bid: Optional[float] = None, ask: Optional[float] = None):
        with self._lock:
            if tenor == "SPOT" or tenor == "FX" or tenor == "SPOT_FX":
                self.update_spot_fx_manually(mid)
                return
            if tenor in self.quotes:
                self.quotes[tenor]["mid"] = round(mid, 4)
                self.quotes[tenor]["bid"] = round(bid if bid is not None else mid - 0.025, 4)
                self.quotes[tenor]["ask"] = round(ask if ask is not None else mid + 0.025, 4)
                self.quotes[tenor]["last_tick"] = datetime.datetime.now().strftime("%H:%M:%S") + " (Manual)"
                self.last_update = datetime.datetime.now()

    def reset_quotes(self):
        with self._lock:
            self.quotes = {q["tenor"]: dict(q) for q in self.DEFAULT_CRS_QUOTES}
            self.spot_fx = 1346.15
            self.spot_fx_tick = "Reset (Base)"
            self.last_update = datetime.datetime.now()

crs_feed = CRSFeed()
