# -*- coding: utf-8 -*-
"""
L35 거래조건서 초안이 트레이더가 넣은 값을 덮지 않는다.

휴대폰에서 스프레드를 넣어도 금리에 반영되지 않는다는 보고. 네 상품 모두,
쿠폰이 있든 없든, 요청에는 제대로 실리고 par 도 정확히 그만큼 움직였습니다.
문제는 순서였습니다 - 스프레드를 먼저 넣고 거래조건서를 적용하면 입력칸이
0.0 으로 덮였습니다.

문서에 스프레드가 없을 때 초안이 "0.0" 을 실어 보낸 탓입니다. 화면은 그걸
문서에서 읽은 값으로 알고 입력칸에 써넣었고, 트레이더가 넣은 50bp 는 조용히
사라졌습니다. 아무 경고도 없고 par 만 50bp 낮게 나옵니다.

없는 값은 비워서 보냅니다. 프라이서가 0 으로 계산하는 것은 같지만, 입력칸을
덮지는 않습니다.
"""
import io
import os
import sys

from harness import case, run_all

from server.termsheet import ExtractedTrade, to_ticket_draft

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def draft(**kw):
    base = dict(supported=True, currency="KRW")
    base.update(kw)
    return to_ticket_draft(ExtractedTrade(**base))["draft"]


@case("L35-1", "문서에 없는 스프레드를 0.0 으로 지어내지 않는다")
def t_1():
    got = draft().get("spreadBp")
    if got != "":
        raise AssertionError(f"스프레드가 비어 있지 않음: {got!r}")


@case("L35-2", "문서에 적힌 스프레드는 그대로 싣는다")
def t_2():
    got = draft(spread_bp=25.0).get("spreadBp")
    if got != "25.0":
        raise AssertionError(f"25bp 를 읽었는데 {got!r}")
    got = draft(spread_bp=0.0).get("spreadBp")
    if got != "0.0":
        raise AssertionError(f"문서가 0 이라고 했는데 {got!r} - 0 과 '없음' 은 다릅니다")


@case("L35-3", "화면이 빈 값을 입력칸에 써넣지 않는다")
def t_3():
    """
    초안이 비워 보내도 화면이 그대로 대입하면 입력칸이 지워집니다. 두 화면이
    같은 규칙을 써야 하므로 여기서 묶어 둡니다.
    """
    with io.open(os.path.join(ROOT, "static", "m.js"), encoding="utf-8") as f:
        m = f.read()
    if 't.spreadBp !== ""' not in m:
        raise AssertionError("m.js 가 빈 spreadBp 를 걸러내지 않음")

    with io.open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as f:
        a = f.read()
    # 데스크톱은 초안을 티켓에 옮길 때 빈 값을 건너뜁니다.
    if 'draft[k] !== undefined && draft[k] !== ""' not in a:
        raise AssertionError("app.js 가 빈 초안 값을 건너뛰지 않음")


@case("L35-4", "쿠폰도 같은 규칙이다")
def t_4():
    """고정금리가 안 적힌 거래조건서는 흔합니다. 0 을 지어내면 안 됩니다."""
    if draft().get("coupon") != "":
        raise AssertionError(f"쿠폰이 비어 있지 않음: {draft().get('coupon')!r}")
    if draft(fixed_coupon_pct=3.31).get("coupon") != "3.3100":
        raise AssertionError("문서에 적힌 쿠폰을 싣지 못함")


if __name__ == "__main__":
    print("\n=== L35 초안이 입력을 덮지 않는다 ===")
    sys.exit(1 if run_all("L35") else 0)
