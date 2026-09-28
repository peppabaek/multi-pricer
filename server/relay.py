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
           quote_count: int) -> Dict[str, Any]:
    """중계가 들어왔음을 기록한다. 호가 자체는 기존 피드에 그대로 반영된다."""
    now = datetime.datetime.now()
    parsed = None
    if source_timestamp:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.datetime.strptime(source_timestamp[:19], fmt)
                break
            except ValueError:
                continue
    with _lock:
        _state[currency.upper()] = {
            "origin": origin or "desk",
            # 데스크 PC 가 LSEG 에서 실제로 받은 시각. 없으면 도착 시각으로 대신하되
            # 그 사실을 감추지 않는다.
            "source_time": (parsed or now).strftime("%Y-%m-%d %H:%M:%S"),
            "source_time_supplied": parsed is not None,
            "received_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "_source_epoch": (parsed or now).timestamp(),
            "quote_count": quote_count,
        }
    return status(currency)


def status(currency: str) -> Dict[str, Any]:
    """현재 중계 상태. 중계가 없으면 active=False."""
    with _lock:
        row = _state.get(currency.upper())
        if not row:
            return {"active": False}
        age = max(0.0, datetime.datetime.now().timestamp() - row["_source_epoch"])
        limit = stale_after()
        return {
            "active": True,
            "origin": row["origin"],
            "source_time": row["source_time"],
            "source_time_supplied": row["source_time_supplied"],
            "received_at": row["received_at"],
            "quote_count": row["quote_count"],
            "age_seconds": round(age, 1),
            "stale": age > limit,
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
    if st["stale"]:
        return f"{head} — 오래된 호가입니다. 데스크 PC 연결을 확인하세요"
    if not st["source_time_supplied"]:
        return f"{head} — 원본 시각 미제공, 도착 시각 기준"
    return head
