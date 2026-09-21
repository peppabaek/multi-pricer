# -*- coding: utf-8 -*-
"""
L20 거절 판정.

`supported=false`는 이 프라이서가 **평가할 수 없는 상품**을 위한 것입니다 —
callable, CMS, range accrual, 옵션성. 금리가 안 적힌 스케줄이나 시트가 여러 개인
엑셀은 마케터가 흔히 보내는 형태이고, 트레이더가 팝업에서 채우면 되는 것입니다.
그런 문서를 문 앞에서 버리면 업로드 기능 자체가 쓸모없어집니다.
"""
import sys

from harness import case, run_all

import server.termsheet as tsmod
from server.termsheet import (
    ExtractedTrade, process_termsheet, refusal_is_about_product, INSIST_NOTE,
)
from test_l10_termsheet import _MINIMAL_PDF, _fake_trade

# 사용자가 실제로 받은 거절 사유.
REAL_REFUSAL = ("The termsheet contains two conflicting amortizing schedules "
                "('스케쥴' starting 2026-09-22 and 'Sheet1' starting 2026-09-18) and "
                "lacks key pricing parameters such as the fixed rate, floating index, "
                "and spread.")


def _refusing(reason):
    """첫 호출은 거절하고, INSIST_NOTE 가 붙어 오면 제대로 추출하는 모델."""
    state = {"calls": 0, "insisted": False}

    def extract(text, **_kw):
        state["calls"] += 1
        if INSIST_NOTE.strip().splitlines()[1] in text:
            state["insisted"] = True
            return _fake_trade("")
        return ExtractedTrade(supported=False, unsupported_reason=reason,
                              provenance=[], open_questions=[])

    return extract, state


def _always_refusing(reason):
    def extract(text, **_kw):
        return ExtractedTrade(supported=False, unsupported_reason=reason,
                              provenance=[], open_questions=[])
    return extract


@case("L20-1", "상품 문제와 데이터 문제를 구분한다")
def t_1():
    data_side = [
        REAL_REFUSAL,
        "Missing fixed rate and floating index",
        "Multiple sheets contain different schedules",
        "The document is ambiguous about the payment frequency",
        "금리와 스프레드가 문서에 없습니다",
    ]
    product_side = [
        "The swap is Bermudan callable from year 3",
        "CMS-linked coupon on the floating leg",
        "Range accrual on 3M SOFR",
        "조기상환 옵션이 포함되어 있습니다",
        "Cancellable at the counterparty's discretion",
    ]
    for reason in data_side:
        if refusal_is_about_product(reason):
            raise AssertionError(f"데이터 문제를 상품 문제로 분류: {reason[:60]}")
    for reason in product_side:
        if not refusal_is_about_product(reason):
            raise AssertionError(f"상품 문제를 놓침: {reason[:60]}")


@case("L20-2", "상품 문제가 아닌 거절은 한 번 더 읽어본다")
def t_2():
    extract, state = _refusing(REAL_REFUSAL)
    saved = tsmod.call_extractor
    tsmod.call_extractor = extract
    try:
        res = process_termsheet(_MINIMAL_PDF)
    finally:
        tsmod.call_extractor = saved

    if not res.get("supported"):
        raise AssertionError(f"재시도 후에도 버려짐: {res.get('unsupported_reason')}")
    if not state["insisted"]:
        raise AssertionError("재시도했지만 이유를 알려주지 않음")
    if state["calls"] != 2:
        raise AssertionError(f"모델 호출 {state['calls']}회 (2회여야 함)")


@case("L20-3", "재시도로 살린 건은 트레이더에게 알린다")
def t_3():
    extract, _ = _refusing(REAL_REFUSAL)
    saved = tsmod.call_extractor
    tsmod.call_extractor = extract
    try:
        res = process_termsheet(_MINIMAL_PDF)
    finally:
        tsmod.call_extractor = saved
    said = " ".join(res.get("open_questions") or []) + " ".join(res.get("warnings") or [])
    if "평가 불가" not in said:
        raise AssertionError(f"1차 거절 사실이 묻힘: {res.get('open_questions')}")


@case("L20-4", "진짜 평가 불가 상품은 재시도 없이 거절된다")
def t_4():
    calls = {"n": 0}

    def extract(text, **_kw):
        calls["n"] += 1
        return ExtractedTrade(supported=False, provenance=[], open_questions=[],
                              unsupported_reason="Bermudan callable swap, "
                                                 "exercisable annually from year 3")

    saved = tsmod.call_extractor
    tsmod.call_extractor = extract
    try:
        res = process_termsheet(_MINIMAL_PDF)
    finally:
        tsmod.call_extractor = saved

    if res.get("supported"):
        raise AssertionError("평가할 수 없는 상품을 통과시킴")
    if calls["n"] != 1:
        raise AssertionError(f"불필요한 재시도로 호출 {calls['n']}회")


@case("L20-5", "두 번 다 거절하면 사유를 그대로 전달한다")
def t_5():
    saved = tsmod.call_extractor
    tsmod.call_extractor = _always_refusing(REAL_REFUSAL)
    try:
        res = process_termsheet(_MINIMAL_PDF)
    finally:
        tsmod.call_extractor = saved
    if res.get("supported"):
        raise AssertionError("거절이 유지되지 않음")
    if "conflicting" not in (res.get("unsupported_reason") or ""):
        raise AssertionError(f"사유가 바뀜: {res.get('unsupported_reason')}")


@case("L20-6", "프롬프트가 거절 조건을 좁게 규정한다")
def t_6():
    prompt = tsmod.SYSTEM_PROMPT
    for phrase in ("supported=false is ONLY", "NEVER set supported=false"):
        if phrase not in prompt:
            raise AssertionError(f"프롬프트에 {phrase!r} 없음")
    for topic in ("missing", "ambiguous", "sheet"):
        if topic not in prompt.lower():
            raise AssertionError(f"프롬프트가 {topic!r} 경우를 다루지 않음")


@case("L20-7", "재시도가 실패해도 원래 사유를 잃지 않는다")
def t_7():
    def extract(text, **_kw):
        if INSIST_NOTE.strip().splitlines()[1] in text:
            raise RuntimeError("모델 장애")
        return ExtractedTrade(supported=False, unsupported_reason=REAL_REFUSAL,
                              provenance=[], open_questions=[])

    saved = tsmod.call_extractor
    tsmod.call_extractor = extract
    try:
        res = process_termsheet(_MINIMAL_PDF)
    finally:
        tsmod.call_extractor = saved
    if res.get("supported"):
        raise AssertionError("재시도 실패인데 통과됨")
    if "conflicting" not in (res.get("unsupported_reason") or ""):
        raise AssertionError("재시도 실패로 원래 사유가 사라짐")


if __name__ == "__main__":
    print("\n=== L20 거절 판정 ===")
    sys.exit(1 if run_all("L20") else 0)
