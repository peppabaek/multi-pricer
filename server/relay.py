# -*- coding: utf-8 -*-
"""
데스크 PC 가 받은 LSEG 호가를 클라우드 인스턴스로 중계하는 경로.

Workspace 데스크톱 API 는 같은 PC 에서만 동작하므로, 클라우드에 올린 프라이서는
LSEG 에 직접 붙을 수 없습니다. 대신 Workspace 가 떠 있는 데스크 PC 가 자기가 받은
호가를 밀어 넣으면, 클라우드는 그 호가로 프라이싱합니다.

여기서 반드시 지켜야 할 것은 **나이**입니다. 원래 스냅샷의 timestamp 는 데이터를
받은 시각이 아니라 읽는 시각이라, 중계에 그대로 쓰면 데스크 PC 가 꺼져도 호가가
계속 '방금 것'으로 보입니다. 트레이더가 어제 호가로 오늘 가격을 내게 됩니다.
그래서 중계본은 **원본 시각**을 함께 받아 보관하고, 그 나이를 화면에 그대로
내보냅니다.
"""

import datetime
import threading
from typing import Any, Dict, List, Optional

# 이 나이를 넘기면 화면에서 '오래됨'으로 표시한다. 스왑 호가가 분 단위로 움직이는
# 것을 감안한 값이고, RELAY_STALE_SECONDS 로 조정할 수 있다.
DEFAULT_STALE_SECONDS = 90

_lock = threading.Lock()
_state: Dict[str, Dict[str, Any]] = {}


def stale_after() -> int:
    import os
    try:
        return max(10, int(os.environ.get("RELAY_STALE_SECONDS", DEFAULT_STALE_SECONDS)))
    except (TypeError, ValueError):
        return DEFAULT_STALE_SECONDS


def record(currency: str, origin: str, source_timestamp: Optional[str],
           quote_count: int, source_epoch_ms: Optional[float] = None) -> Dict[str, Any]:
    """
    중계가 들어왔음을 기록한다. 호가 자체는 기존 피드에 그대로 반영된다.

    나이는 **절대 시각**으로 센다. 데스크는 서울, 서버는 UTC 에서 도는 것이
    보통이라, 벽시계 문자열을 그대로 빼면 9시간이 어긋난다. 실제 배포에서
    원본 시각이 9시간 미래로 계산되어 나이가 영원히 0 이 되었고, 끊긴 호가가
    계속 최신으로 보였다.
    """
    now = datetime.datetime.now()
    now_epoch = now.timestamp()

    epoch = None
    if source_epoch_ms:
        try:
            epoch = float(source_epoch_ms) / 1000.0
        except (TypeError, ValueError):
            epoch = None

    # epoch 이 없을 때만 문자열을 쓴다. 오프셋이 붙어 있으면 그대로 신뢰하고,
    # 없으면 서버 시간대로 읽을 수밖에 없다 - 그 사실을 감추지 않는다.
    naive_string = False
    if epoch is None and source_timestamp:
        text = source_timestamp.strip()
        try:
            dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                naive_string = True
            epoch = dt.timestamp()
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    epoch = datetime.datetime.strptime(text[:19], fmt).timestamp()
                    naive_string = True
                    break
                except ValueError:
                    continue

    supplied = epoch is not None
    if epoch is None:
        epoch = now_epoch

    with _lock:
        _state[currency.upper()] = {
            "origin": origin or "desk",
            "source_time": datetime.datetime.fromtimestamp(epoch).strftime(
                "%Y-%m-%d %H:%M:%S"),
            "source_time_supplied": supplied,
            # 벽시계 문자열만 받은 경우, 데스크와 서버의 시간대가 다르면 나이가
            # 어긋난다. 화면에서 이를 구분할 수 있어야 한다.
            "source_time_naive": naive_string,
            "received_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "_source_epoch": epoch,
            "quote_count": quote_count,
        }
    return status(currency)


def status(currency: str) -> Dict[str, Any]:
    """현재 중계 상태. 중계가 없으면 active=False."""
    with _lock:
        row = _state.get(currency.upper())
        if not row:
            return {"active": False}
        raw_age = datetime.datetime.now().timestamp() - row["_source_epoch"]
        limit = stale_after()
        # 미래 시각은 시계가 어긋났다는 뜻이다. 0 으로 깎아 '방금'으로 보이게 하면
        # 끊긴 중계가 영원히 최신이 된다 - 실제 배포에서 그렇게 됐다. 모를 때는
        # 신선하다고 하지 않는다.
        skewed = raw_age < -5
        age = max(0.0, raw_age)
        return {
            "active": True,
            "origin": row["origin"],
            "source_time": row["source_time"],
            "source_time_supplied": row["source_time_supplied"],
            "source_time_naive": row.get("source_time_naive", False),
            "received_at": row["received_at"],
            "quote_count": row["quote_count"],
            "age_seconds": round(age, 1),
            "clock_skewed": skewed,
            "stale": skewed or age > limit,
            "stale_after_seconds": limit,
        }


def clear(currency: str) -> None:
    with _lock:
        _state.pop(currency.upper(), None)


def all_status() -> Dict[str, Dict[str, Any]]:
    with _lock:
        currencies = list(_state)
    return {c: status(c) for c in currencies}


def describe(currency: str) -> str:
    """화면에 그대로 쓸 한 줄. 나이를 숨기지 않는다."""
    st = status(currency)
    if not st.get("active"):
        return ""
    age = st["age_seconds"]
    when = f"{int(age)}초 전" if age < 120 else f"{int(age // 60)}분 전"
    head = f"데스크 중계 ({st['origin']}) · {when}"
    if st.get("clock_skewed"):
        return (f"{head} — 원본 시각이 서버보다 미래입니다. 시계·시간대를 확인하세요 "
                f"(나이를 신뢰할 수 없어 오래된 것으로 취급)")
    if st["stale"]:
        return f"{head} — 오래된 호가입니다. 데스크 PC 연결을 확인하세요"
    if not st["source_time_supplied"]:
        return f"{head} — 원본 시각 미제공, 도착 시각 기준"
    return head
