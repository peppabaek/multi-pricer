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

def workspace_listening(port: int = 9000, timeout: float = 0.35) -> bool:
    """
    Whether anything is accepting connections on the Workspace API port.

    eikon's set_app_key performs a handshake as a side effect, and when the desktop
    is not running that prints several lines of its own errors before failing. A
    35ms check first keeps startup quiet and quick, and - on a host, where there is
    no desktop at all - avoids the attempt entirely.
    """
    import socket
    try:
        with socket.socket() as sk:
            sk.settimeout(timeout)
            return sk.connect_ex(("127.0.0.1", int(port or 0))) == 0
    except Exception:
        return False


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
                    if not workspace_listening(self._port):
                        # Nothing to hand shake with. set_app_key would try anyway and
                        # print its own failures, which is the noise at startup.
                        self._ek = None
                        return
                    # Port first: set_app_key hands shakes immediately, and with no
                    # port set yet it builds http://127.0.0.1:None/api/handshake and
                    # fails on "Invalid port: 'None'".
                    self._ek.set_port_number(self._port)
                    self._ek.set_app_key(self._app_key)
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
