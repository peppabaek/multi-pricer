"""
KMBC FX Forward & Swap Point Live Market Data Feed Provider
- Primary RIC source: KMBC USD/KRW Forward Swap Points ('KRWxx=KMBC' and 'KRWxF=KMBC')
- Streams live Spot FX (KRW=) and KMBC market swap points from LSEG Workspace (Desktop Proxy Port 9000).
- Fallback to reference baseline when offline.
"""

import os
import json
import time
import datetime
import threading
from typing import Dict, Any, List, Optional
import pandas as pd

from .eikon_rate_limiter import eikon_manager, EIKON_GLOBAL_LOCK

class KMBCFwdFeed:
    """
    Manages live streaming and polling of KMBC USD/KRW Forward Swap Points and Spot FX.
    """
    DEFAULT_KMBC_QUOTES = [
        # Outright Swap Points (Tenor, RIC, Bid, Ask, Mid in 전, 100전 = 1원)
        {"tenor": "1W", "ric": "KRW1W=KMBC", "type": "Outright", "bid": -32.0, "ask": 18.0, "mid": -7.0, "bid_krw": -0.32, "ask_krw": 0.18, "mid_krw": -0.07, "last_tick": "Init (Base)"},
        {"tenor": "2W", "ric": "KRW2W=KMBC", "type": "Outright", "bid": -50.0, "ask": 0.0, "mid": -25.0, "bid_krw": -0.50, "ask_krw": 0.00, "mid_krw": -0.25, "last_tick": "Init (Base)"},
        {"tenor": "1M", "ric": "KRW1M=KMBC", "type": "Outright", "bid": -100.0, "ask": 0.0, "mid": -50.0, "bid_krw": -1.00, "ask_krw": 0.00, "mid_krw": -0.50, "last_tick": "Init (Base)"},
        {"tenor": "2M", "ric": "KRW2M=KMBC", "type": "Outright", "bid": -205.0, "ask": -5.0, "mid": -105.0, "bid_krw": -2.05, "ask_krw": -0.05, "mid_krw": -1.05, "last_tick": "Init (Base)"},
        {"tenor": "3M", "ric": "KRW3M=KMBC", "type": "Outright", "bid": -300.0, "ask": -50.0, "mid": -175.0, "bid_krw": -3.00, "ask_krw": -0.50, "mid_krw": -1.75, "last_tick": "Init (Base)"},
        {"tenor": "6M", "ric": "KRW6M=KMBC", "type": "Outright", "bid": -630.0, "ask": -230.0, "mid": -430.0, "bid_krw": -6.30, "ask_krw": -2.30, "mid_krw": -4.30, "last_tick": "Init (Base)"},
        {"tenor": "9M", "ric": "KRW9M=KMBC", "type": "Outright", "bid": -950.0, "ask": -450.0, "mid": -700.0, "bid_krw": -9.50, "ask_krw": -4.50, "mid_krw": -7.00, "last_tick": "Init (Base)"},
        {"tenor": "1Y", "ric": "KRW1Y=KMBC", "type": "Outright", "bid": -1160.0, "ask": -660.0, "mid": -910.0, "bid_krw": -11.60, "ask_krw": -6.60, "mid_krw": -9.10, "last_tick": "Init (Base)"},
    ]

    def __init__(self, config_path: str = "lseg_config.json"):
        self.config_path = config_path
        self.quotes: Dict[str, Dict[str, Any]] = {q["tenor"]: dict(q) for q in self.DEFAULT_KMBC_QUOTES}
        self.spot_fx: float = 1343.50
        self.spot_fx_bid: float = 1343.35
        self.spot_fx_ask: float = 1343.65
        self.spot_fx_tick: str = "Init (Base)"
        self.is_connected = False
        self.status_message = "Initializing KMBC USD/KRW FX Swap Point Feed..."
        self.last_update = datetime.datetime.now()
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
        except Exception:
            self.config = {"app_key": "YOUR_APP_KEY", "port": 9000}

    def _init_eikon(self):
        try:
            eikon_manager._ensure_init()
            if eikon_manager._initialized:
                self.is_connected = True
                self.status_message = "● LIVE LSEG Workspace (KMBC Swap Points)"
            else:
                self.is_connected = False
                self.status_message = "Offline Base (KMBC Baseline Rates)"
        except Exception as e:
            self.is_connected = False
            self.status_message = f"Offline Base (LSEG Proxy unavailable: {e})"

    def _start_worker(self):
        # Background polling disabled to prevent Eikon rate limit exhaustion
        self._worker_thread = None

    def _poll_loop(self):
        """Relaxed background worker (60s interval) to prevent 429 rate limit collisions"""
        time.sleep(25.0)
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=60.0)
            if self.is_connected and not self._stop_event.is_set():
                try:
                    self._fetch_live_quotes()
                except Exception:
                    pass

    def trigger_on_demand_refresh(self) -> bool:
        """Triggers an immediate synchronous poll from LSEG Workspace proxy via eikon_manager"""
        return self._fetch_live_quotes()

    @staticmethod
    def _safe_float(val: Any) -> Optional[float]:
        """Safely convert Eikon/pandas field to float without triggering pd.NA boolean ambiguity"""
        if val is not None and pd.notna(val):
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        return None

    def _fetch_live_quotes(self) -> bool:
        try:
            from .eikon_rate_limiter import eikon_manager
            rics = [q["ric"] for q in self.DEFAULT_KMBC_QUOTES] + ["KRW="]
            fields = ["PRIMACT_1", "SEC_ACT_1", "CF_LAST", "CF_BID", "CF_ASK", "MID_PRICE", "NETCHNG_1"]
            df, err = eikon_manager.get_data(rics, fields)
            if df is not None and not df.empty:
                self.is_connected = True
                self.status_message = "● LIVE LSEG Workspace (KMBC Swap Points)"
                now_str = datetime.datetime.now().strftime("%H:%M:%S (Live)")
                with self._lock:
                    live_tenors = set()
                    for _, row in df.iterrows():
                        ric = str(row.get("Instrument", "")).strip()
                        if ric == "KRW=":
                            bid = self._safe_float(row.get("CF_BID")) or self._safe_float(row.get("PRIMACT_1"))
                            ask = self._safe_float(row.get("CF_ASK")) or self._safe_float(row.get("SEC_ACT_1"))
                            last = self._safe_float(row.get("CF_LAST"))
                            if bid is not None and bid > 0: self.spot_fx_bid = bid
                            if ask is not None and ask > 0: self.spot_fx_ask = ask
                            if last is not None and last > 0:
                                self.spot_fx = last
                            elif self.spot_fx_bid > 0 and self.spot_fx_ask > 0:
                                self.spot_fx = round((self.spot_fx_bid + self.spot_fx_ask) / 2.0, 2)
                            self.spot_fx_tick = now_str
                            continue

                        # Find matching quote
                        for tenor, q in self.quotes.items():
                            if q["ric"] == ric:
                                bid = self._safe_float(row.get("PRIMACT_1")) or self._safe_float(row.get("CF_BID"))
                                ask = self._safe_float(row.get("SEC_ACT_1")) or self._safe_float(row.get("CF_ASK"))
                                mid_p = self._safe_float(row.get("MID_PRICE"))
                                chg = self._safe_float(row.get("NETCHNG_1"))

                                if bid is not None:
                                    q["bid"] = bid
                                if ask is not None:
                                    q["ask"] = ask
                                if bid is not None and ask is not None:
                                    q["mid"] = round((bid + ask) / 2.0, 2)
                                elif mid_p is not None:
                                    q["mid"] = round(mid_p, 2)
                                elif bid is not None:
                                    q["mid"] = bid

                                # If Outright (in 전), also compute KRW 원
                                if q["type"] == "Outright":
                                    q["bid_krw"] = round(q["bid"] / 100.0, 4) if q.get("bid") is not None else 0.0
                                    q["ask_krw"] = round(q["ask"] / 100.0, 4) if q.get("ask") is not None else 0.0
                                    q["mid_krw"] = round(q["mid"] / 100.0, 4)
                                else:
                                    q["bid_krw"] = q["bid"]
                                    q["ask_krw"] = q["ask"]
                                    q["mid_krw"] = q["mid"]

                                if chg is not None:
                                    q["chg"] = round(chg, 2)
                                q["last_tick"] = now_str
                                q["quoted"] = bid is not None or ask is not None
                                if q["quoted"]:
                                    live_tenors.add(tenor)

                    self._fill_unquoted(live_tenors, now_str)
                    self.last_update = datetime.datetime.now()
                print(f"[KMBC FWD FEED] Successfully loaded live quotes. 1Y Mid: {self.quotes['1Y']['mid']}전 ({self.quotes['1Y']['mid_krw']}원), Spot FX: {self.spot_fx}")
                return True
            else:
                return False
        except Exception as ex:
            import traceback
            print(f"[KMBC FWD FEED ERROR] Live quote fetch exception: {ex}")
            traceback.print_exc()
            return False

    # 테너를 날짜로 재는 표. 보간은 개월 수가 아니라 일수로 해야
    # 1W 와 1M 사이가 제대로 나뉩니다.
    _TENOR_DAYS = {"1W": 7, "2W": 14, "1M": 30, "2M": 61, "3M": 91,
                   "6M": 182, "9M": 273, "1Y": 365}

    def _fill_unquoted(self, live_tenors, now_str):
        """
        호가가 안 들어온 테너를 어떻게 할 것인가.

        KRW2W=KMBC 는 존재하는 레코드인데 값이 비어 옵니다 - 브로커가 그날
        그 구간을 부르지 않은 것이고, 흔한 일입니다. 예전에는 기준호가가 그대로
        남아 화면에는 실시간처럼 보였습니다. 그것이 제일 나쁜 답입니다 - 데스크가
        몇 달 전 숫자를 오늘 호가로 읽게 됩니다.

        양쪽에 살아있는 테너가 있으면 그 사이를 일수로 선형보간하고 보간이라고
        밝힙니다. 없으면 값은 그대로 두되 "호가없음" 으로 표시해, 화면이 그걸
        실시간으로 읽지 않게 합니다.
        """
        order = [q["tenor"] for q in self.DEFAULT_KMBC_QUOTES]
        for i, tenor in enumerate(order):
            if tenor in live_tenors:
                continue
            q = self.quotes.get(tenor)
            if q is None:
                continue
            lo = next((t for t in reversed(order[:i]) if t in live_tenors), None)
            hi = next((t for t in order[i + 1:] if t in live_tenors), None)
            if lo and hi:
                d_lo, d_hi = self._TENOR_DAYS.get(lo), self._TENOR_DAYS.get(hi)
                d_t = self._TENOR_DAYS.get(tenor)
                if d_lo and d_hi and d_t and d_hi > d_lo:
                    w = (d_t - d_lo) / float(d_hi - d_lo)
                    a, b = self.quotes[lo], self.quotes[hi]
                    for key in ("bid", "ask", "mid"):
                        va, vb = a.get(key), b.get(key)
                        if va is None or vb is None:
                            continue
                        q[key] = round(va + (vb - va) * w, 2)
                    for key in ("bid", "ask", "mid"):
                        q[key + "_krw"] = (round(q[key] / 100.0, 4)
                                           if q["type"] == "Outright" and q.get(key) is not None
                                           else q.get(key))
                    q["quoted"] = False
                    q["interp_from"] = [lo, hi]
                    q["last_tick"] = now_str.split(" ")[0] + f" (Interp {lo}·{hi})"
                    continue
            q["quoted"] = False
            q.pop("interp_from", None)
            q["last_tick"] = now_str.split(" ")[0] + " (호가없음)"

    def get_snapshot(self, force_refresh: bool = False) -> Dict[str, Any]:
        if force_refresh:
            if self.is_connected:
                try:
                    self._fetch_live_quotes()
                except Exception:
                    pass
        with self._lock:
            q_list = list(self.quotes.values())
            return {
                "quotes": q_list,
                "spot_fx": self.spot_fx,
                "spot_fx_bid": self.spot_fx_bid,
                "spot_fx_ask": self.spot_fx_ask,
                "spot_fx_tick": self.spot_fx_tick,
                "is_connected": self.is_connected,
                "status_message": self.status_message,
                "timestamp": self.last_update.strftime("%Y-%m-%d %H:%M:%S")
            }

    def update_quote(self, tenor: str, new_mid: float,
                     new_bid=None, new_ask=None, source: str = "Manual") -> bool:
        """스왑포인트도 양방이 오면 그대로 받습니다. 인자만 받고 버리지 않도록."""
        with self._lock:
            if tenor == "SPOT_FX" or tenor == "SPOT":
                self.spot_fx = float(new_mid)
                self.spot_fx_tick = (
                    datetime.datetime.now().strftime("%H:%M:%S") + f" ({source})")
                return True
            if tenor in self.quotes:
                self.quotes[tenor]["mid"] = float(new_mid)
                if new_bid is not None:
                    self.quotes[tenor]["bid"] = float(new_bid)
                if new_ask is not None:
                    self.quotes[tenor]["ask"] = float(new_ask)
                self.quotes[tenor]["last_tick"] = (
                    datetime.datetime.now().strftime("%H:%M:%S") + f" ({source})")
                return True
        return False

    def reset_quotes(self):
        with self._lock:
            self.quotes = {q["tenor"]: dict(q) for q in self.DEFAULT_KMBC_QUOTES}
            self.spot_fx = 1366.29
            self.spot_fx_tick = "Reset (Base)"
            self.last_update = datetime.datetime.now()

kmbc_fwd_feed_instance = KMBCFwdFeed()
