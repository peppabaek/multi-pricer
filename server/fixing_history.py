# -*- coding: utf-8 -*-
"""
지나간 변동금리 고시치.

개시일이 오늘보다 앞선 거래조건서를 올리면 첫 몇 기간은 이미 시작돼 있고,
그 금리는 과거 고시일에 정해져 있습니다. 커브에는 없습니다 - 커브는 오늘
이후만 말합니다. 그래서 지금까지는 같은 길이의 구간을 spot 에서 끊어
추정했고(rate_source "Estimated"), Murex 와는 당연히 어긋났습니다.

실제 고시치는 LSEG 시계열에 있습니다. KRW CD 91D 는 KRCD3M=KFIA, KOFR 은 KOFR=KSDQ, 콜금리는
KRCALL=BOKK. 한 번 고시된 값은 바뀌지 않으므로 받아서 영구히 캐시합니다.

호스팅 쪽에는 Workspace 가 없습니다. 호가와 같은 길 - 데스크 PC 가 중계로
올려줍니다(/api/fixings/push). 받은 값은 같은 캐시에 들어가므로 엔진 입장에서
출처는 구분되지 않습니다.
"""
import datetime
import json
import os
import threading
from typing import Dict, Optional, Tuple

# 지수 이름 -> 시계열 RIC. 화면과 거래조건서가 쓰는 이름은 통화 코드이므로
# 그쪽에서 넘어오는 값도 같이 받아 둡니다.
INDEX_RICS = {
    "KRW_CD_91D": "KRCD3M=KFIA",
    "KRW": "KRCD3M=KFIA",
    "KRW_CALL": "KRCALL=BOKK",
    "ON": "KRCALL=BOKK",
    "KOFR": "KOFR=KSDQ",
    "KRW_KOFR": "KOFR=KSDQ",
}

# 고시일이 휴일이거나 그날 값이 비면 직전 영업일 값을 씁니다. 시장 관행이고,
# 며칠씩 거슬러 올라가는 것은 데이터가 없다는 뜻이므로 선을 그어 둡니다.
_LOOKBACK_DAYS = 7


def _data_path() -> str:
    """캐시 파일 위치. 휴일 달력과 같은 규칙을 씁니다."""
    data_dir = os.environ.get("PRICER_DATA_DIR")
    if data_dir:
        try:
            os.makedirs(data_dir, exist_ok=True)
            return os.path.join(data_dir, "fixings.json")
        except OSError:
            pass
    return os.path.join(os.path.dirname(__file__), "..", "fixings_cache.json")


class FixingHistory:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache: Dict[str, Dict[str, float]] = {}
        self._loaded = False

    # ---------------------------------------------------------------- 저장소
    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        path = _data_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for idx, days in raw.items():
                    if isinstance(days, dict):
                        self._cache[idx] = {
                            d: float(v) for d, v in days.items()
                            if isinstance(v, (int, float))
                        }
        except (OSError, ValueError) as e:
            # 캐시가 깨졌다고 프라이싱을 멈출 이유는 없습니다. 비우고 갑니다.
            print(f"[FixingHistory] 캐시를 읽지 못했습니다 ({e}) - 비우고 시작합니다")
            self._cache = {}

    def _save(self):
        path = _data_path()
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, path)
        except OSError as e:
            print(f"[FixingHistory] 캐시를 쓰지 못했습니다 ({e})")

    # ---------------------------------------------------------------- 읽기
    def get(self, index: str, on: datetime.date) -> Tuple[Optional[float], Optional[str]]:
        """
        그 날짜의 고시치와 실제로 쓰인 날짜.

        그날 값이 없으면 직전 영업일로 거슬러 올라갑니다 - 고시일이 휴일로
        잡힌 경우입니다. 일주일을 넘어가면 데이터가 없는 것으로 봅니다.
        """
        with self._lock:
            self._load()
            days = self._cache.get(self._norm(index))
            if not days:
                return None, None
            for back in range(_LOOKBACK_DAYS + 1):
                key = (on - datetime.timedelta(days=back)).isoformat()
                if key in days:
                    return days[key], key
        return None, None

    def has(self, index: str) -> bool:
        with self._lock:
            self._load()
            return bool(self._cache.get(self._norm(index)))

    def coverage(self, index: str) -> Dict[str, Optional[str]]:
        with self._lock:
            self._load()
            days = self._cache.get(self._norm(index)) or {}
            keys = sorted(days)
            return {"count": len(keys),
                    "first": keys[0] if keys else None,
                    "last": keys[-1] if keys else None}

    # ---------------------------------------------------------------- 쓰기
    def put(self, index: str, fixings: Dict[str, float]) -> int:
        """
        받은 고시치를 캐시에 넣는다. 이미 있는 날짜는 덮지 않습니다.

        한 번 고시된 값은 바뀌지 않습니다. 덮어쓰기를 허용하면 중계가 잘못된
        값을 한 번 보냈을 때 그것이 진실이 돼 버립니다.
        """
        idx = self._norm(index)
        added = 0
        with self._lock:
            self._load()
            days = self._cache.setdefault(idx, {})
            for d, v in (fixings or {}).items():
                try:
                    datetime.date.fromisoformat(str(d))
                    rate = float(v)
                except (TypeError, ValueError):
                    continue
                if str(d) not in days:
                    days[str(d)] = rate
                    added += 1
            if added:
                self._save()
        return added

    # ---------------------------------------------------------------- LSEG
    def fetch(self, index: str, start: datetime.date,
              end: Optional[datetime.date] = None) -> int:
        """
        LSEG 시계열에서 받아 캐시에 넣는다. Workspace 가 있는 데스크 PC 전용.

        돌려주는 것은 새로 들어간 날짜 수입니다. Workspace 가 없으면 0 이고,
        그것이 오류는 아닙니다 - 호스팅에서는 중계로 들어옵니다.
        """
        ric = INDEX_RICS.get(self._norm(index))
        if not ric:
            return 0
        end = end or datetime.date.today()
        try:
            from .eikon_rate_limiter import eikon_manager
            eikon_manager._ensure_init()
            import eikon as ek
            df = ek.get_timeseries(ric, start_date=str(start), end_date=str(end),
                                   interval="daily")
        except Exception as e:
            print(f"[FixingHistory] {ric} 시계열 조회 실패: {type(e).__name__} {e}")
            return 0
        if df is None or len(df) == 0:
            return 0

        found = {}
        for ts, row in df.iterrows():
            value = row.get("CLOSE")
            try:
                rate = float(value)
            except (TypeError, ValueError):
                continue
            if rate <= 0:
                continue
            found[ts.date().isoformat()] = rate
        return self.put(index, found)

    @staticmethod
    def _norm(index: str) -> str:
        return (index or "").strip().upper()


fixing_history = FixingHistory()


def lookup(index: str):
    """
    엔진에 넘길 조회 함수. 고시일을 주면 퍼센트 금리를 돌려줍니다.

    엔진은 캐시가 비었는지, LSEG 가 붙었는지 알 필요가 없습니다. 값이 없으면
    None 이고, 그러면 엔진은 지금까지처럼 커브에서 추정합니다.
    """
    def fn(on: datetime.date) -> Optional[float]:
        rate, _ = fixing_history.get(index, on)
        return rate
    return fn
