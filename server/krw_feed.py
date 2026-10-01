"""
LSEG Workspace Real-Time Market Data Feed for KRW CD 91D IRS
- CD 91D Fixing: KRCD3M=KFIA (KOFIA Official Daily Fixing)
- O/N Call Rate: KRCALL=BOKK (Bank of Korea)
- 1M, 2M, 4M, 5M: 시장에서 받지 않고 O/N·3M·6M 사이를 보간합니다 (_reinterpolate)
- Tradition KRW IRS Broker Quotes: KRWIRSxx=TRDL (6M, 9M, 1Y, 18M, 2Y, 3Y, 4Y, 5Y, 7Y, 10Y, 12Y, 15Y, 20Y)
- Single Dedicated Background Worker Thread for 100% Lock-Free & Crash-Proof Instant Serving (<0.1ms)
"""

import os
import json
import time
import datetime
import threading
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np

CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lseg_config.json"))

# KRW CD 91D IRS 호가. 단기는 한국은행 콜금리와 KOFIA CD 3M 두 개만 시장에서
# 받고, 1M·2M·4M·5M 은 그 사이를 보간합니다(interp 항목이 양쪽 기준점).
# Murex 의 KRWIRS 커브가 6M 미만에서 똑같이 O/N 과 3M 만 물리고 나머지를
# 보간하므로, 그쪽과 맞추는 것이 목적입니다. 프라이싱 커브도 6M 미만은
# O/N 과 3M 만 필러로 쓰므로, 보간된 네 개는 화면과 대사용입니다.
# - O/N to 5M: KRW Deposit
# - 6M to 30Y: KRWQMCD with Broker PREA (KRWQMCD{Tenor}=PREA)
KRW_REAL_RIC_DEFS = [
    {"tenor": "ON",  "ric": "KRCALL=BOKK",      "bid": 2.8042, "ask": 2.8042, "mid": 2.8042, "is_fix": True},
    {"tenor": "1M",  "ric": None,               "bid": 2.8619, "ask": 2.8619, "mid": 2.8619, "is_fix": True, "interp": ("ON", "3M")},
    {"tenor": "2M",  "ric": None,               "bid": 2.9141, "ask": 2.9141, "mid": 2.9141, "is_fix": True, "interp": ("ON", "3M")},
    {"tenor": "3M",  "ric": "KRCD3M=KFIA",      "bid": 2.9700, "ask": 2.9700, "mid": 2.9700, "is_fix": True},
    {"tenor": "4M",  "ric": None,               "bid": 3.0401, "ask": 3.0401, "mid": 3.0401, "is_fix": True, "interp": ("3M", "6M")},
    {"tenor": "5M",  "ric": None,               "bid": 3.1079, "ask": 3.1079, "mid": 3.1079, "is_fix": True, "interp": ("3M", "6M")},
    {"tenor": "6M",  "ric": "KRWQMCD6M=PREA",   "bid": 3.2400, "ask": 3.2750, "mid": 3.2575, "is_fix": False},
    {"tenor": "9M",  "ric": "KRWQMCD9M=PREA",   "bid": 3.3750, "ask": 3.4100, "mid": 3.3925, "is_fix": False},
    {"tenor": "1Y",  "ric": "KRWQMCD1Y=PREA",   "bid": 3.4900, "ask": 3.5250, "mid": 3.5075, "is_fix": False},
    {"tenor": "18M", "ric": "KRWQMCD18M=PREA",  "bid": 3.6550, "ask": 3.6900, "mid": 3.6725, "is_fix": False},
    {"tenor": "2Y",  "ric": "KRWQMCD2Y=PREA",   "bid": 3.7300, "ask": 3.7650, "mid": 3.7475, "is_fix": False},
    {"tenor": "3Y",  "ric": "KRWQMCD3Y=PREA",   "bid": 3.8400, "ask": 3.8700, "mid": 3.8550, "is_fix": False},
    {"tenor": "4Y",  "ric": "KRWQMCD4Y=PREA",   "bid": 3.9100, "ask": 3.9400, "mid": 3.9250, "is_fix": False},
    {"tenor": "5Y",  "ric": "KRWQMCD5Y=PREA",   "bid": 3.9500, "ask": 3.9850, "mid": 3.9675, "is_fix": False},
    {"tenor": "6Y",  "ric": "KRWQMCD6Y=PREA",   "bid": 3.9900, "ask": 4.0250, "mid": 4.0075, "is_fix": False},
    {"tenor": "7Y",  "ric": "KRWQMCD7Y=PREA",   "bid": 4.0250, "ask": 4.0550, "mid": 4.0400, "is_fix": False},
    {"tenor": "8Y",  "ric": "KRWQMCD8Y=PREA",   "bid": 4.0450, "ask": 4.0750, "mid": 4.0600, "is_fix": False},
    {"tenor": "9Y",  "ric": "KRWQMCD9Y=PREA",   "bid": 4.0650, "ask": 4.0950, "mid": 4.0800, "is_fix": False},
    {"tenor": "10Y", "ric": "KRWQMCD10Y=PREA",  "bid": 4.0850, "ask": 4.1150, "mid": 4.1000, "is_fix": False},
    {"tenor": "12Y", "ric": "KRWQMCD12Y=PREA",  "bid": 4.1050, "ask": 4.1400, "mid": 4.1225, "is_fix": False},
    {"tenor": "15Y", "ric": "KRWQMCD15Y=PREA",  "bid": 4.0950, "ask": 4.1300, "mid": 4.1125, "is_fix": False},
    {"tenor": "20Y", "ric": "KRWQMCD20Y=PREA",  "bid": 4.0250, "ask": 4.0550, "mid": 4.0400, "is_fix": False},
    {"tenor": "25Y", "ric": "KRWQMCD25Y=PREA",  "bid": 3.9250, "ask": 3.9600, "mid": 3.9425, "is_fix": False},
    {"tenor": "30Y", "ric": "KRWQMCD30Y=PREA",  "bid": 3.8300, "ask": 3.8600, "mid": 3.8450, "is_fix": False}
]

class KRWMarketFeed:
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
        self._worker_thread = None

    def _load_app_key(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self._app_key = cfg.get("lseg_app_key") or cfg.get("app_key")
            except Exception:
                pass

    def _init_baseline(self):
        with self._lock:
            for item in KRW_REAL_RIC_DEFS:
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
            self._reinterpolate()

    def _reinterpolate(self):
        """
        시장에서 받지 않는 단기 호가를 양쪽 기준점 사이에 놓는다.

        1M·2M 은 O/N 과 3M 사이, 4M·5M 은 3M 과 6M 사이를 spot 에서 쟴
        일수로 선형 보간합니다. 개월 수로 나누지 않는 것은 달마다 길이가
        다르고 만기가 휴일로 밀리기 때문입니다.

        데스크가 Murex 에 맞추어 손으로 넣었던 값과 대조해 보면 0.2bp 안에
        들어옵니다(1M 3.1515 / 3.1522, 4M 3.2810 / 3.2818).

        수기로 눌러 둔 호가는 건드리지 않습니다 - 보간값이 덮어버리면
        손으로 넣는 의미가 없습니다.
        """
        from .calendar_manager import add_months, apply_convention

        today = datetime.date.today()
        # KRW 현물은 T+1 입니다. 그냥 하루를 더하면 금요일에 토요일이 나옵니다.
        spot = apply_convention(today + datetime.timedelta(days=1), "Following", "SEB")

        def horizon(tenor):
            """
            spot 에서 그 테너까지의 일수. 영업일로 밀기 전 날짜를 씁니다.

            밀린 날짜를 쓰면 연휴가 끼어드는 테너만 가중치가 튀어오릅니다. 4M
            만기가 설 연휴를 지나 나흘 밀리는 날에 보간값이 1bp 뛰었고,
            데스크가 Murex 에 맞추어 넣었던 값과 떨어졌습니다.
            """
            if tenor == "ON":
                return 1
            months = int(tenor[:-1]) * (12 if tenor.endswith("Y") else 1)
            return max(1, (add_months(spot, months) - spot).days)

        for item in KRW_REAL_RIC_DEFS:
            pair = item.get("interp")
            if not pair:
                continue
            t = item["tenor"]
            q = self._quotes.get(t)
            if q is None or q.get("is_overridden"):
                continue
            lo, hi = (self._quotes.get(pair[0]), self._quotes.get(pair[1]))
            if not lo or not hi or lo.get("mid") is None or hi.get("mid") is None:
                continue
            d_lo, d_hi, d_t = horizon(pair[0]), horizon(pair[1]), horizon(t)
            if d_hi <= d_lo:
                continue
            w = (d_t - d_lo) / float(d_hi - d_lo)
            def blend(key):
                a, b = lo.get(key), hi.get(key)
                if a is None or b is None:
                    return None
                return round(a + (b - a) * w, 4)
            mid = blend("mid")
            if mid is None:
                continue
            q["mid"] = mid
            q["bid"] = blend("bid") if blend("bid") is not None else mid
            q["ask"] = blend("ask") if blend("ask") is not None else mid
            q["chg_bp"] = round((mid - q["prev_close"]) * 100.0, 2)
            q["last_tick"] = (lo.get("last_tick") or "").split(" ")[0] + " (Interp)"

    def _dedicated_fetch_loop(self):
        """Relaxed background worker (60s interval)"""
        time.sleep(12.0)
        while self._running:
            self._refresh_event.wait(timeout=60.0)
            self._refresh_event.clear()
            if self._running:
                try:
                    self._do_eikon_fetch()
                except Exception:
                    pass

    def _do_eikon_fetch(self):
        try:
            from .eikon_rate_limiter import eikon_manager
            rics = [item["ric"] for item in KRW_REAL_RIC_DEFS if item.get("ric")]
            fields = ["PRIMACT_1", "SEC_ACT_1", "CF_LAST", "CF_CLOSE"]
            df, err = eikon_manager.get_data(rics, fields)
            if df is not None and not df.empty:
                ric_to_row = {}
                for idx, row in df.iterrows():
                    inst = str(row.get("Instrument", "")).strip().upper()
                    ric_to_row[inst] = row

                now_str = datetime.datetime.now().strftime("%H:%M:%S") + " (Live)"
                with self._lock:
                    for item in KRW_REAL_RIC_DEFS:
                        t = item["tenor"]
                        if not item.get("ric"):
                            continue
                        r_code = item["ric"].strip().upper()
                        
                        if t in self._quotes and self._quotes[t]["is_overridden"]:
                            continue
                                
                        if r_code in ric_to_row:
                            r_data = ric_to_row[r_code]
                            prim = r_data.get("PRIMACT_1")
                            sec = r_data.get("SEC_ACT_1")
                            last = r_data.get("CF_LAST")
                            prev_c = r_data.get("CF_CLOSE")

                            bid_val = prim if pd.notnull(prim) and isinstance(prim, (int, float)) and prim > 0 else None
                            ask_val = sec if pd.notnull(sec) and isinstance(sec, (int, float)) and sec > 0 else None
                            last_val = last if pd.notnull(last) and isinstance(last, (int, float)) and last > 0 else None

                            if bid_val is not None and ask_val is not None:
                                bid = float(bid_val)
                                ask = float(ask_val)
                                mid = round((bid + ask) / 2.0, 4)
                            elif last_val is not None:
                                mid = float(last_val)
                                # 고시치는 한 개의 숫자입니다. 콜금리도 CD 91D 도
                                # 양방으로 불리지 않으므로 ±1bp 를 지어내면 화면에
                                # 없는 호가가 생깁니다 - 이제 단기에서 시장을 타는
                                # 것이 이 둘뿐이라 더 그렇습니다.
                                if item.get("is_fix"):
                                    bid = ask = round(mid, 4)
                                else:
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
                    self._reinterpolate()
                    self._is_live_connected = True
                    self._last_update_ts = datetime.datetime.now()
        except Exception:
            with self._lock:
                self._is_live_connected = False

    def trigger_on_demand_refresh(self):
        self._do_eikon_fetch()

    def get_snapshot(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Instant (<0.1ms) thread-safe snapshot with on-demand refresh"""
        if force_refresh:
            self._do_eikon_fetch()
            
        with self._lock:
            ordered_quotes = []
            for item in KRW_REAL_RIC_DEFS:
                t = item["tenor"]
                if t in self._quotes:
                    ordered_quotes.append(dict(self._quotes[t]))
                    
            status_msg = "● LIVE LSEG Workspace (Prebon PREA)" if self._is_live_connected else "Offline Prebon Baseline"
            source_lbl = "LSEG Workspace (Prebon Yamane PREA & KRW Deposit)" if self._is_live_connected else "Prebon Yamane PREA & KRW Deposit Baseline"
            
            return {
                "source": source_lbl,
                "status_message": status_msg,
                "is_live_connected": self._is_live_connected,
                "has_app_key": bool(self._app_key),
                "timestamp": self._last_update_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "epoch_ms": int(self._last_update_ts.timestamp() * 1000),
                "quotes": ordered_quotes
            }

    def update_quote(self, tenor: str, new_mid: float,
                     new_bid=None, new_ask=None, source: str = "Manual") -> bool:
        """
        호가 하나를 갈아끼운다.

        bid/ask 를 주면 그대로 씁니다. 중계는 LSEG 에서 받은 실제 양방 호가를
        보내는데, 이 함수가 mid 만 받던 탓에 인자가 맞지 않아 버려지고 ±1bp 를
        지어냈습니다. 배포본의 1Y 가 3.7125/3.7325 로 보인 이유입니다 - LSEG 와
        Murex 는 3.7050/3.7400 이었고, mid 만 우연히 같았습니다.

        source 는 마지막 틱에 찍힙니다. 중계로 들어온 값을 "Manual" 이라고 하면
        사람이 손으로 넣은 것처럼 읽힙니다.
        """
        with self._lock:
            t = tenor.strip().upper()
            if t in self._quotes:
                prev = self._quotes[t]["prev_close"]
                # 준 값이 있으면 그것이 진실입니다. 없을 때만 벌립니다.
                spread_half = 0.0100
                bid = float(new_bid) if new_bid is not None else new_mid - spread_half
                ask = float(new_ask) if new_ask is not None else new_mid + spread_half
                self._quotes[t].update({
                    "bid": round(bid, 4),
                    "ask": round(ask, 4),
                    "mid": round(new_mid, 4),
                    "chg_bp": round((new_mid - prev) * 100.0, 2),
                    "is_overridden": source == "Manual",
                    "last_tick": datetime.datetime.now().strftime("%H:%M:%S") + f" ({source})"
                })
                # O/N 이나 3M 을 고쳤으면 그 사이에 걸린 호가도 같이 움직여야
                # 합니다. 안 그러면 화면에 서로 맞지 않는 단기 커브가 남습니다.
                self._reinterpolate()
                self._last_update_ts = datetime.datetime.now()
                return True
        return False

    def reset_to_base(self):
        self._init_baseline()
        self.trigger_on_demand_refresh()

krw_feed = KRWMarketFeed()
