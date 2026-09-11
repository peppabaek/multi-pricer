"""
Centralized Single-Session Rate-Limiter & Safe Proxy Client for LSEG Eikon Desktop API
- Prevents 429 Too Many Requests errors and asyncio session collisions
- Thread-safe singleton Eikon manager with global lock and call throttling
"""

import os
import json
import time
import logging
import threading
from typing import List, Tuple, Any, Optional
import pandas as pd

# Suppress internal eikon logs that spam stderr on transient proxy retries
for log_name in ("eikon", "pyeikon", "httpx", "httpcore"):
    l = logging.getLogger(log_name)
    l.setLevel(logging.CRITICAL)
    l.propagate = False
    for h in list(l.handlers):
        l.removeHandler(h)

CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lseg_config.json"))

class EikonManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._ek = None
        self._initialized = False
        self._last_call = 0.0
        self._app_key = None
        self._port = 9000
        self._rate_limit_until = 0.0

    def _ensure_init(self):
        if not self._initialized:
            try:
                import eikon as ek
                self._ek = ek
                if os.path.exists(CONFIG_FILE):
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        self._app_key = cfg.get("lseg_app_key") or cfg.get("app_key")
                        self._port = cfg.get("port", 9000)
                if self._app_key and self._app_key != "YOUR_APP_KEY":
                    self._ek.set_app_key(self._app_key)
                    self._ek.set_port_number(self._port)
                    try:
                        self._ek.set_log_level(1)
                    except Exception:
                        pass
                    self._initialized = True
            except Exception:
                self._initialized = False

    def get_data(self, instruments: List[str], fields: List[str]) -> Tuple[Optional[pd.DataFrame], Optional[Any]]:
        """Serialized, single-session rate-limited query to Eikon proxy with fast fallback"""
        with self._lock:
            now = time.time()
            if now < self._rate_limit_until:
                return None, "Eikon rate limit cooldown active (429)"

            self._ensure_init()
            if not self._initialized or not self._ek:
                return None, "Eikon not initialized"
            
            # Enforce 0.25s minimum gap to respect 5 req/s proxy limit
            elapsed = now - self._last_call
            if elapsed < 0.25:
                time.sleep(0.25 - elapsed)
                
            try:
                df, err = self._ek.get_data(instruments, fields)
                self._last_call = time.time()
                return df, err
            except Exception as e:
                self._last_call = time.time()
                err_str = str(e)
                if "429" in err_str or "too many requests" in err_str.lower():
                    # Set 10s cooldown to prevent cascade timeouts during daily or burst quota limit
                    self._rate_limit_until = time.time() + 10.0
                return None, err_str

eikon_manager = EikonManager()
EIKON_GLOBAL_LOCK = eikon_manager._lock

def safe_eikon_get_data(ek_ignored, instruments: List[str], fields: List[str]) -> Tuple[Optional[pd.DataFrame], Optional[Any]]:
    return eikon_manager.get_data(instruments, fields)
