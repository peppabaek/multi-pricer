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
    import os
    import socket
    # 호스팅 환경처럼 Workspace 가 있을 수 없는 곳에서는 탐지 자체를 생략한다.
    # 데스크 중계만 받는 인스턴스를 그대로 재현할 때도 쓴다.
    if os.environ.get("PRICER_NO_LOCAL_FEED", "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        with socket.socket() as sk:
            sk.settimeout(timeout)
            return sk.connect_ex(("127.0.0.1", int(port or 0))) == 0
    except Exception:
        return False


_EIKON_LOG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "logs", "eikon"))
# 며칠 지난 것은 지웁니다. 진단에 쓰이는 것은 대개 방금 것입니다.
_EIKON_LOG_KEEP_DAYS = 7
# 나이만으로는 모자랍니다 - 테스트 한 번에 수십 개가 생겨 7일치가 500개를
# 넘었습니다. 개수 상한이 실제로 크기를 정합니다.
_EIKON_LOG_KEEP_MAX = 50


def _configure_eikon_logging(ek) -> None:
    """
    eikon 로깅은 기본으로 끕니다. 켤 때만 logs/eikon/ 에 씁니다.

    루트와 tests/ 에 pyeikon.<날짜>.<시각>.log 가 1,326개, 190MB 쌓여 있었습니다.
    원인은 초기화 때마다 무조건 부르던 set_log_level(1) 이었습니다. eikon 문서는
    "By default, logs are disabled" 이고 인자는 파이썬 로깅 레벨이라, 1 은
    NOTSET 바로 위 - 최소가 아니라 **최대 상세** 입니다. 줄이려던 호출이 켜고
    있었습니다. 실측: 부르지 않으면 파일 0개, 부르면 초기화마다 1개.

    LSEG 연결을 들여다봐야 할 때는 PRICER_EIKON_LOG 에 레벨을 줍니다
    (예: PRICER_EIKON_LOG=20 이면 INFO).

    set_log_path 는 내부에서 desktop 세션을 만들기 때문에 set_app_key 뒤에
    불러야 합니다. 앞에서 부르면 포트가 정해지기 전에 세션이 생깁니다.
    """
    _sweep_eikon_logs()

    level = os.environ.get("PRICER_EIKON_LOG", "").strip()
    if not level:
        return
    try:
        os.makedirs(_EIKON_LOG_DIR, exist_ok=True)
        ek.set_log_path(_EIKON_LOG_DIR)
        ek.set_log_level(int(level))
    except Exception:
        # 로그 설정 때문에 시세가 끊기면 안 됩니다.
        pass


def _sweep_eikon_logs(keep_days: int = _EIKON_LOG_KEEP_DAYS,
                      keep_max: int = _EIKON_LOG_KEEP_MAX) -> int:
    """
    pyeikon 로그를 정리하고 지운 개수를 돌려준다.

    나이만으로는 부족합니다. 테스트를 한 번 돌리면 수십 개가 생겨서, 7일치가
    500개를 넘었습니다. 그래서 개수 상한도 함께 둡니다.

    루트와 tests/ 에 있는 것은 나이와 무관하게 지웁니다. set_log_path 를 건 뒤로
    거기에 새로 생기지 않으므로, 남아 있는 것은 전부 리다이렉트 이전의 잔재이고
    logs/eikon/ 에 현재 로그가 따로 있습니다.
    """
    import glob
    import time as _t

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    removed = 0

    def _rm(path):
        nonlocal removed
        try:
            os.remove(path)
            removed += 1
        except OSError:
            # 지금 열려 있는 파일(Windows). 다음 번에 지워집니다.
            pass

    # 옛 자리: 전부.
    for legacy in (os.path.join(root, "pyeikon.*.log*"),
                   os.path.join(root, "tests", "pyeikon.*.log*")):
        for path in glob.glob(legacy):
            _rm(path)

    # 새 자리: 오래됐거나, 최근 keep_max 개를 넘어선 것.
    current = glob.glob(os.path.join(_EIKON_LOG_DIR, "pyeikon.*.log*"))
    cutoff = _t.time() - keep_days * 86400
    try:
        current.sort(key=os.path.getmtime, reverse=True)
    except OSError:
        return removed
    for i, path in enumerate(current):
        try:
            if i >= keep_max or os.path.getmtime(path) < cutoff:
                _rm(path)
        except OSError:
            pass
    return removed


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
                    _configure_eikon_logging(self._ek)
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
