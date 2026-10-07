# -*- coding: utf-8 -*-
"""
L34 KRWCDIRS 단기 RIC 교체와 보간.

데스크 지시로 두 개만 시장에서 받습니다:

    O/N  KRCALL=BOKK      한국은행 콜금리
    3M   KRCD3M=KFIA      KOFIA CD 91D 고시

1M·2M·4M·5M 은 RIC 을 걸지 않고 보간합니다. Murex 의 KRWIRS 커브가 6M 미만에서
O/N 과 3M 만 물리고 나머지를 보간하므로, 화면도 같은 모양이어야 대사가 됩니다.
프라이싱 커브 역시 6M 미만은 O/N 과 3M 만 필러로 쓰므로, 보간된 네 개는 화면과
대사용입니다.

보간은 조정 전 날짜의 일수로 선형입니다. 영업일로 민 날짜를 쓰면 연휴가
끼어드는 테너만 가중치가 튑니다 - 4M 만기가 설 연휴를 지나 나흘 밀리는 날
보간값이 1bp 뛰었습니다.

데스크가 Murex 에 맞춰 손으로 넣었던 값과 대조하면 0.2bp 안에 들어옵니다.
"""
import datetime
import sys

from harness import case, run_all

from server.krw_feed import KRWMarketFeed, KRW_REAL_RIC_DEFS
from server.calendar_manager import add_months, apply_convention

# 데스크가 Murex 에 맞춰 넣었던 기준점과 보간 대상.
ANCHORS = {"ON": (3.1189, 3.1189, 3.1189),
           "3M": (3.2200, 3.2200, 3.2200),
           "6M": (3.4050, 3.3875, 3.4225)}
DESK = {"1M": 3.1522, "2M": 3.1845, "4M": 3.2818, "5M": 3.3414}
INTERPOLATED = ("1M", "2M", "4M", "5M")


def feed_with_anchors():
    f = KRWMarketFeed()
    for t, (m, b, a) in ANCHORS.items():
        f.update_quote(t, m, b, a, source="Live")
    return f


def quotes(f):
    return {q["tenor"]: q for q in f.get_snapshot()["quotes"]}


@case("L34-1", "O/N 과 3M 이 지시받은 RIC 을 쓴다")
def t_1():
    by_tenor = {d["tenor"]: d.get("ric") for d in KRW_REAL_RIC_DEFS}
    for tenor, ric in (("ON", "KRCALL=BOKK"), ("3M", "KRCD3M=KFIA")):
        if by_tenor.get(tenor) != ric:
            raise AssertionError(f"{tenor} RIC 이 {by_tenor.get(tenor)!r}, 기대 {ric!r}")


@case("L34-2", "보간 테너는 RIC 을 걸지 않는다")
def t_2():
    """
    RIC 이 남아 있으면 Workspace 에 쓸데없는 조회가 나가고, 응답이 오면
    보간값을 덮어씁니다.
    """
    by_tenor = {d["tenor"]: d for d in KRW_REAL_RIC_DEFS}
    for t in INTERPOLATED:
        d = by_tenor[t]
        if d.get("ric"):
            raise AssertionError(f"{t} 에 RIC 이 남아 있음: {d['ric']!r}")
        if not d.get("interp"):
            raise AssertionError(f"{t} 에 보간 기준점이 없음")

    asked = [d["ric"] for d in KRW_REAL_RIC_DEFS if d.get("ric")]
    if len(asked) != len(set(asked)):
        raise AssertionError("조회 목록에 중복 RIC")
    if any(r is None for r in asked):
        raise AssertionError("조회 목록에 None 이 섞임")

    # 화면에서는 빈 칸이 아니라 보간이라고 밝혀야 합니다. 비어 있으면 조회가
    # 실패한 것과 구분이 안 됩니다.
    q = quotes(KRWMarketFeed())
    for t in INTERPOLATED:
        shown = q[t].get("ric")
        if not shown or "보간" not in str(shown):
            raise AssertionError(f"{t} RIC 칸이 {shown!r} - 보간이라고 표시되지 않음")
    for t in ("ON", "3M"):
        if "보간" in str(q[t].get("ric")):
            raise AssertionError(f"{t} 가 보간으로 표시됨: {q[t].get('ric')!r}")


@case("L34-3", "보간값이 데스크 수기입력과 0.5bp 안에 든다")
def t_3():
    q = quotes(feed_with_anchors())
    for t, want in DESK.items():
        got = q[t]["mid"]
        if abs(got - want) > 0.005:
            raise AssertionError(f"{t} 보간 {got:.4f} vs 데스크 {want:.4f} "
                                 f"({(got - want) * 100:+.2f}bp)")


@case("L34-4", "보간은 조정 전 날짜의 일수로 선형이다")
def t_4():
    """
    방식을 숫자로 못박습니다. 영업일 조정을 끼우면 연휴가 걸리는 테너만
    가중치가 튑니다.
    """
    f = feed_with_anchors()
    q = quotes(f)
    today = datetime.date.today()
    spot = apply_convention(today + datetime.timedelta(days=1), "Following", "SEB")

    def horizon(t):
        if t == "ON":
            return 1
        n = int(t[:-1]) * (12 if t.endswith("Y") else 1)
        return max(1, (add_months(spot, n) - spot).days)

    for d in KRW_REAL_RIC_DEFS:
        pair = d.get("interp")
        if not pair:
            continue
        t = d["tenor"]
        lo, hi = ANCHORS[pair[0]][0], ANCHORS[pair[1]][0]
        w = (horizon(t) - horizon(pair[0])) / float(horizon(pair[1]) - horizon(pair[0]))
        want = round(lo + (hi - lo) * w, 4)
        if abs(q[t]["mid"] - want) > 1e-9:
            raise AssertionError(f"{t} {q[t]['mid']} vs 선형 기대값 {want}")


@case("L34-5", "기준점이 움직이면 보간값도 따라간다")
def t_5():
    f = feed_with_anchors()
    before = {t: quotes(f)[t]["mid"] for t in INTERPOLATED}
    f.update_quote("3M", 3.7200, 3.7200, 3.7200, source="Live")   # +50bp
    after = quotes(f)
    for t in INTERPOLATED:
        if abs(after[t]["mid"] - before[t]) < 1e-6:
            raise AssertionError(f"3M 을 50bp 올렸는데 {t} 가 {before[t]} 그대로")
    if not (after["1M"]["mid"] < after["2M"]["mid"] < after["3M"]["mid"]):
        raise AssertionError(
            f"단기 커브가 뒤집힘: {[round(after[t]['mid'], 4) for t in ('1M','2M','3M')]}")


@case("L34-6", "수기로 넣은 호가는 보간이 덮지 않는다")
def t_6():
    """덮어쓰면 손으로 넣는 의미가 없습니다."""
    f = feed_with_anchors()
    f.update_quote("2M", 9.9999, source="Manual")
    f.update_quote("3M", 3.7200, 3.7200, 3.7200, source="Live")   # 보간을 다시 돌림
    got = quotes(f)["2M"]
    if abs(got["mid"] - 9.9999) > 1e-6:
        raise AssertionError(f"수기 2M 9.9999 가 {got['mid']} 로 덮임")
    if not got["is_overridden"]:
        raise AssertionError("수기 표시가 꺼짐")


@case("L34-7", "보간값에도 양방 호가가 선다")
def t_7():
    q = quotes(feed_with_anchors())
    for t in ("4M", "5M"):          # 6M 쪽 기준점이 양방이라 벌어져야 합니다
        b, m, a = q[t]["bid"], q[t]["mid"], q[t]["ask"]
        if not (b <= m <= a):
            raise AssertionError(f"{t} bid/mid/ask 가 {b}/{m}/{a}")
        if a - b <= 0:
            raise AssertionError(f"{t} 스프레드가 0 - 양방이 전달되지 않음")


@case("L34-8", "프라이싱 커브는 여전히 O/N 과 3M 만 필러로 쓴다")
def t_8():
    """
    보간된 네 개가 필러로 들어가면 Murex 커브와 모양이 달라집니다.
    화면에는 보이되 커브에는 안 들어가는 것이 맞습니다.
    """
    from krw_pricer.krw_curve_engine import bootstrap_krw_curve
    from krw_pricer.krw_date_engine import get_krw_spot_date

    f = feed_with_anchors()
    qs = [(q["tenor"], float(q["mid"])) for q in f.get_snapshot()["quotes"]]
    today = datetime.date.today()
    c = bootstrap_krw_curve(today, get_krw_spot_date(today), qs)
    short = [p["tenor"] for p in c.pillars if p["months"] <= 5]
    if short != ["ON", "3M"]:
        raise AssertionError(f"6M 미만 필러가 O/N·3M 이 아님: {short}")


@case("L34-9", "고시치에 없는 양방 호가를 지어내지 않는다")
def t_9():
    """
    콜금리도 CD 91D 도 한 개의 숫자로 고시됩니다. 응답에 양방이 없다고
    ±1bp 를 붙이면 화면에 존재하지 않는 호가가 생깁니다. 이제 단기에서
    시장을 타는 것이 이 둘뿐이라 더 그렇습니다.
    """
    import pandas as pd
    import server.eikon_rate_limiter as erl

    rows = pd.DataFrame([
        {"Instrument": "KRCALL=BOKK", "PRIMACT_1": None, "SEC_ACT_1": None,
         "CF_LAST": 3.1189, "CF_CLOSE": 3.1150},
        {"Instrument": "KRCD3M=KFIA", "PRIMACT_1": None, "SEC_ACT_1": None,
         "CF_LAST": 3.2200, "CF_CLOSE": 3.2150},
        {"Instrument": "KRWQMCD6M=PREA", "PRIMACT_1": 3.3875, "SEC_ACT_1": 3.4225,
         "CF_LAST": None, "CF_CLOSE": 3.4000},
    ])
    real = erl.eikon_manager.get_data
    erl.eikon_manager.get_data = lambda *a, **k: (rows, None)
    try:
        f = KRWMarketFeed()
        f.trigger_on_demand_refresh()
        q = quotes(f)
    finally:
        erl.eikon_manager.get_data = real

    for t, want in (("ON", 3.1189), ("3M", 3.2200)):
        got = q[t]
        if abs(got["mid"] - want) > 1e-9:
            raise AssertionError(f"{t} 고시치 {want} 가 {got['mid']} 로 들어옴")
        if got["bid"] != got["mid"] or got["ask"] != got["mid"]:
            raise AssertionError(
                f"{t} 고시치에 스프레드를 붙임: {got['bid']}/{got['ask']}")
    # 진짜 양방이 오는 쪽은 그대로 벌어져 있어야 합니다.
    if q["6M"]["bid"] >= q["6M"]["ask"]:
        raise AssertionError(f"6M 양방이 사라짐: {q['6M']['bid']}/{q['6M']['ask']}")
    # 그리고 그 사이는 보간돼 있어야 합니다.
    if abs(q["1M"]["mid"] - 3.1522) > 0.005:
        raise AssertionError(f"조회 뒤 보간이 안 돌았음: 1M {q['1M']['mid']}")



# ------------------------------------------------------------------ KOFR OIS

@case("L34-10", "KOFR OIS 의 O/N 은 KOFR=KSDQ 고시를 쓴다")
def t_10():
    """
    KRWKOFR= 는 Workspace 에 없는 레코드이고, 콜금리(KRCALL=BOKK)는 RP 기반인
    KOFR 과 금리 차이가 있으므로 실제 고시 RIC 인 KOFR=KSDQ 를 사용합니다.
    """
    from server.kofr_feed import KOFR_REAL_RIC_DEFS

    by_tenor = {d["tenor"]: d.get("ric") for d in KOFR_REAL_RIC_DEFS}
    if by_tenor.get("ON") != "KOFR=KSDQ":
        raise AssertionError(f"KOFR O/N RIC 이 {by_tenor.get('ON')!r}")
    if any(r == "KRWKOFR=" for r in by_tenor.values()):
        raise AssertionError("없는 레코드 KRWKOFR= 가 아직 남아 있음")


@case("L34-11", "KOFR 쪽도 고시치에 스프레드를 지어내지 않는다")
def t_11():
    import pandas as pd
    import server.eikon_rate_limiter as erl
    from server.kofr_feed import KOFRMarketFeed

    rows = pd.DataFrame([
        {"Instrument": "KOFR=KSDQ", "PRIMACT_1": None, "SEC_ACT_1": None,
         "CF_LAST": 3.05, "CF_CLOSE": 3.048},
        {"Instrument": "KRWKF1YOIS=KMBC", "PRIMACT_1": 3.4775, "SEC_ACT_1": 3.5275,
         "CF_LAST": None, "CF_CLOSE": 3.50},
    ])
    real = erl.eikon_manager.get_data
    erl.eikon_manager.get_data = lambda *a, **k: (rows, None)
    try:
        f = KOFRMarketFeed()
        f.trigger_on_demand_refresh()
        q = {x["tenor"]: x for x in f.get_snapshot()["quotes"]}
    finally:
        erl.eikon_manager.get_data = real

    on = q["ON"]
    if abs(on["mid"] - 3.05) > 1e-9:
        raise AssertionError(f"KOFR 고시치 3.05 가 {on['mid']} 로 들어옴")
    if on["bid"] != on["mid"] or on["ask"] != on["mid"]:
        raise AssertionError(f"고시치에 스프레드를 붙임: {on['bid']}/{on['ask']}")
    if q["1Y"]["bid"] >= q["1Y"]["ask"]:
        raise AssertionError(f"1Y 양방이 사라짐: {q['1Y']['bid']}/{q['1Y']['ask']}")



# --------------------------------------------- USD SOFR / FX FWD 단기 RIC

@case("L34-12", "USD SOFR 1W 이 살아 있는 RIC 을 쓴다")
def t_12():
    """
    USDSROISSW=TWEB 은 Workspace 에 없는 레코드라("The record could not be
    found") 1W 만 조회해도 값이 안 들어오고 기준호가에 머물러 있었습니다.
    """
    from server.tradition_feed import TRADITION_REAL_RIC_DEFS as DEFS

    by_tenor = {d["tenor"]: d.get("ric") for d in DEFS}
    if by_tenor.get("1W") != "USDSROIS1W=TWEB":
        raise AssertionError(f"1W RIC 이 {by_tenor.get('1W')!r}")
    if any(r == "USDSROISSW=TWEB" for r in by_tenor.values()):
        raise AssertionError("없는 레코드 USDSROISSW=TWEB 가 아직 남아 있음")


@case("L34-13", "호가가 없는 FX FWD 테너는 양옆에서 보간한다")
def t_13():
    """
    KRW2W=KMBC 는 존재하는 레코드인데 값이 비어 옵니다 - 브로커가 그날 그
    구간을 부르지 않은 것이고 흔한 일입니다. 예전에는 기준호가가 그대로 남아
    화면에는 실시간처럼 보였습니다. 몇 달 전 숫자를 오늘 호가로 읽게 됩니다.
    """
    from server.kmbc_fwd_feed import KMBCFwdFeed

    f = KMBCFwdFeed()
    f.quotes["1W"].update({"bid": -53.0, "ask": -3.0, "mid": -28.0})
    f.quotes["1M"].update({"bid": -150.0, "ask": -50.0, "mid": -100.0})
    f._fill_unquoted({"1W", "1M"}, "10:00:00 (Live)")

    q = f.quotes["2W"]
    if q.get("quoted") is not False:
        raise AssertionError("보간한 테너를 호가로 표시")
    if q.get("interp_from") != ["1W", "1M"]:
        raise AssertionError(f"보간 기준점이 {q.get('interp_from')}")
    # 1W(7일) 과 1M(30일) 사이 14일 -> 가중치 7/23
    want = round(-28.0 + (-100.0 - -28.0) * (7 / 23.0), 2)
    if abs(q["mid"] - want) != 0:
        raise AssertionError(f"mid {q['mid']} vs 선형 기대값 {want}")
    if not (q["bid"] < q["mid"] < q["ask"] or q["bid"] > q["mid"] > q["ask"]):
        raise AssertionError(f"보간 후 bid/mid/ask 순서가 깨짐: {q['bid']}/{q['mid']}/{q['ask']}")


@case("L34-14", "양옆도 없으면 호가가 없다고 말한다")
def t_14():
    """지어낼 근거가 없을 때는 지어내지 않고 그렇다고 적습니다."""
    from server.kmbc_fwd_feed import KMBCFwdFeed

    f = KMBCFwdFeed()
    f._fill_unquoted(set(), "10:00:00 (Live)")
    q = f.quotes["2W"]
    if q.get("quoted") is not False:
        raise AssertionError("호가가 없는데 호가로 표시")
    if q.get("interp_from"):
        raise AssertionError("보간할 수 없는데 보간했다고 표시")
    if "호가없음" not in str(q.get("last_tick")):
        raise AssertionError(f"last_tick 이 {q.get('last_tick')!r}")


if __name__ == "__main__":
    print("\n=== L34 KRWCDIRS RIC 교체와 보간 ===")
    sys.exit(1 if run_all("L34") else 0)
