# -*- coding: utf-8 -*-
"""
L31 짜투리가 있는 원화 상각 스왑.

실제 거래조건서(IRS-Pay-CD-260918) 사진을 올렸을 때 프라이싱이 실패했습니다.
원인이 네 개 겹쳐 있었습니다.

이 일정표의 모양부터. 지급일이 휴일 때문에 밀리면, 상환되는 원금만 그 며칠을
더 받는 행이 따로 섭니다:

    2026-09-18 → 2026-10-18   명목 2,500,000,000
    2026-10-18 → 2026-10-19   명목   138,904,000   (상환분, 1일)
    2026-10-18 → 2026-11-18   명목 2,361,096,000   (잔액)

두 행은 시간이 아니라 명목을 쪼갭니다 - 합이 직전 기간과 같고, 상환금이 실제로
결제되는 10-19 까지는 전액이 이자를 받습니다. 기간이 시간축을 차례로 덮는다고
가정한 검사는 이것을 "이어지지 않는다" 고 잘못 경고했습니다.
"""
import io
import os
import re
import sys

from harness import case, run_all

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

from server.termsheet import (check_schedule, freq_from_schedule,
                              notional_from_schedule, to_ticket_draft,
                              ExtractedTrade, SchedulePeriod)

# 거래조건서 앞부분을 그대로 옮긴 것.
ROWS = [
    ("2026-09-18", "2026-10-18", 2_500_000_000),
    ("2026-10-18", "2026-10-19", 138_904_000),      # 짜투리 1일
    ("2026-10-18", "2026-11-18", 2_361_096_000),
    ("2026-11-18", "2026-12-18", 2_222_208_000),
    ("2026-12-18", "2027-01-18", 2_083_320_000),
    ("2027-01-18", "2027-02-18", 1_944_432_000),
    ("2027-02-18", "2027-03-18", 1_805_544_000),
]


def sched(rows=None):
    return [SchedulePeriod(start_date=a, end_date=b, notional=float(n))
            for a, b, n in (rows or ROWS)]


def trade(**kw):
    base = dict(supported=True, currency="KRW", leg1_custom_schedule=sched())
    base.update(kw)
    return ExtractedTrade(**base)


@case("L31-1", "명목을 쪼갠 행을 '이어지지 않는다'고 하지 않는다")
def t_1():
    w = check_schedule(trade(notional=2_500_000_000.0))
    bad = [x for x in w if "이어지지" in x]
    if bad:
        raise AssertionError(f"짜투리 구조를 오탐: {bad}")


@case("L31-2", "진짜 끊긴 스케줄은 여전히 잡는다")
def t_2():
    holed = [("2026-09-18", "2026-10-18", 2_500_000_000),
             ("2026-11-01", "2026-12-01", 2_000_000_000)]
    w = check_schedule(trade(notional=2_500_000_000.0,
                             leg1_custom_schedule=sched(holed)))
    if not any("이어지지" in x for x in w):
        raise AssertionError("한 달이 통째로 빠졌는데 넘어감")


@case("L31-3", "쪼갠 행의 명목 합이 안 맞으면 잡는다")
def t_3():
    # 합이 직전 기간과 같아야 쪼갠 것입니다. 아니면 읽다가 하나를 놓친 겁니다.
    wrong = [("2026-09-18", "2026-10-18", 2_500_000_000),
             ("2026-10-18", "2026-10-19", 138_904_000),
             ("2026-10-18", "2026-11-18", 1_000_000_000)]   # 잔액이 틀림
    w = check_schedule(trade(notional=2_500_000_000.0,
                             leg1_custom_schedule=sched(wrong)))
    if not any("이어지지" in x for x in w):
        raise AssertionError("명목 합이 어긋나는데 쪼갠 것으로 인정")


@case("L31-4", "헤드라인 원금을 못 읽으면 스케줄에서 가져온다")
def t_4():
    """
    모델이 표에서 '2,500,000,000' 을 못 집으면 통화 기본값으로 떨어졌습니다.
    원화 기본값은 1,000억 - 25억짜리 거래가 40배로 계산됩니다. 스케줄은 같은
    문서에서 읽은 값이라 지어낸 기본값보다 낫습니다.
    """
    if notional_from_schedule(sched()) != 2_500_000_000.0:
        raise AssertionError("스케줄에서 명목을 읽지 못함")
    d = to_ticket_draft(trade(notional=None))
    shown = d["draft"]["notionalDisplay"].replace(",", "")
    if shown != "2500000000":
        raise AssertionError(f"기본값으로 떨어짐: {d['draft']['notionalDisplay']}")
    if "notional" in d["inferred_fields"]:
        raise AssertionError("문서에서 읽었는데 '시장 관행 적용'으로 표시")


@case("L31-5", "지급주기를 못 읽으면 날짜 간격에서 센다")
def t_5():
    # 월별 일정표를 원화 기본값 3M 으로 계산하면 변동다리가 어긋납니다.
    if freq_from_schedule(sched()) != "1M":
        raise AssertionError(f"간격에서 1M 을 읽지 못함: {freq_from_schedule(sched())}")
    d = to_ticket_draft(trade(leg1_payment_freq=None))
    if d["draft"]["leg1PaymentFreq"] != "1M":
        raise AssertionError(f"기본값 3M 으로 떨어짐: {d['draft']['leg1PaymentFreq']}")


@case("L31-6", "간격이 들쭉날쭉하면 지어내지 않는다")
def t_6():
    odd = [("2026-01-01", "2026-02-01", 100), ("2026-02-01", "2026-09-01", 100),
           ("2026-09-01", "2026-09-05", 100)]
    if freq_from_schedule(sched(odd)) is not None:
        raise AssertionError("읽을 수 없는 간격에서 주기를 만들어냄")


@case("L31-7", "쿠폰 없이 커스텀 스케줄을 프라이싱해도 죽지 않는다")
def t_7():
    """
    거래조건서에 고정금리가 없으면 par 를 구해야 하는데, 커스텀 스케줄이 걸린
    채로 쿠폰이 None 이면 엔진이
    "unsupported operand type(s) for /: 'NoneType' and 'float'" 로 죽었습니다.
    스케줄이 없는 경로는 None 을 걸러내는데 이쪽만 빠져 있었습니다.
    """
    from fastapi.testclient import TestClient
    from server.app import app
    client = TestClient(app)

    rows = "\n".join(f"{a}\t{b}\t{b}\t{n}" for a, b, n in ROWS)
    text = "Start date\tEnd date\tPay date\tNominal\n" + rows
    for path, ccy in (("/api/krw/price", "KRW"), ("/api/price", "USD")):
        r = client.post(path, json={
            "currency": ccy, "notional": 2_500_000_000.0, "position": "Pay Fixed",
            "tenor": "18M", "raw_paste_text": text, "leg1_raw_paste_text": text})
        if r.status_code != 200:
            raise AssertionError(f"{ccy} HTTP {r.status_code}: {r.text[:160]}")
        pr = r.json()["data"]["pricing_results"]
        if not pr.get("par_swap_rate_pct"):
            raise AssertionError(f"{ccy}: par 가 비어 있음")


@case("L31-8", "짜투리 행이 프라이싱 스케줄에 그대로 실린다")
def t_8():
    from fastapi.testclient import TestClient
    from server.app import app
    rows = "\n".join(f"{a}\t{b}\t{b}\t{n}" for a, b, n in ROWS)
    text = "Start date\tEnd date\tPay date\tNominal\n" + rows
    d = TestClient(app).post("/api/krw/price", json={
        "currency": "KRW", "notional": 2_500_000_000.0, "position": "Pay Fixed",
        "tenor": "18M", "leg1_day_count": "Act/365", "leg1_payment_freq": "1M",
        "fixed_coupon_pct": 3.3,
        "raw_paste_text": text, "leg1_raw_paste_text": text}).json()["data"]
    leg1 = d["schedules"]["leg1_fixed"]
    if len(leg1) != len(ROWS):
        raise AssertionError(f"{len(ROWS)}행을 넣었는데 {len(leg1)}행이 나옴")
    stub = [p for p in leg1 if abs(p["notional"] - 138_904_000) < 1]
    if not stub:
        raise AssertionError("짜투리 행이 사라짐")
    # 1일짜리입니다. Act/365 로 1/365 = 0.00274.
    if abs(stub[0]["day_count_fraction"] - 1 / 365) > 1e-5:
        raise AssertionError(f"짜투리 기간이 1일이 아님: {stub[0]['day_count_fraction']}")


@case("L31-9", "화면이 참조하는 요소가 마크업에 있다")
def t_9():
    """
    setCurrency 가 th-fixed-cf 같은 헤더 일곱 개에 textContent 를 쓰는데 그
    요소들은 마크업에서 사라진 지 오래였습니다. KRW 로 바꿀 때마다 거기서
    TypeError 가 나고 setCurrency 가 중단됐습니다 - 통화는 바뀌지 않은 채로요.
    그래서 원화 거래조건서를 적용하면 달러 커브로 계산됐고, 화면 어디에도 그
    말은 없었습니다.
    """
    with io.open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as f:
        js = f.read()
    with io.open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8") as f:
        ids = set(re.findall(r'id="([^"]+)"', f.read()))

    missing = {name: eid for name, eid
               in re.findall(r'(\w+):\s*document\.getElementById\("([^"]+)"\)', js)
               if eid not in ids}
    # 없는 요소를 가드 없이 만지는 곳이 있으면 그 줄에서 화면이 멈춥니다.
    unguarded = [f"{n} ({e})" for n, e in missing.items()
                 if re.search(r'elements\.%s\.\w' % re.escape(n), js)]
    if unguarded:
        raise AssertionError(
            f"마크업에 없는 요소를 가드 없이 사용: {sorted(unguarded)}")


if __name__ == "__main__":
    print("\n=== L31 짜투리 상각 스왑 ===")
    sys.exit(1 if run_all("L31") else 0)
