# -*- coding: utf-8 -*-
"""
실제 모델에 실제 사진을 보내 읽게 한다.

나머지 사진 테스트(L25)는 모델을 대역으로 둡니다 - 배관이 맞는지, 즉 무엇이
모델에 전달되는지만 봅니다. 그것만으로는 "AI 가 사진을 읽어 거래조건을 뽑는다"
는 요구가 충족됐다고 말할 수 없습니다.

이 스크립트는 API 키를 쓰고 돈이 듭니다. 그래서 run_all.py 에 넣지 않고 손으로
돌립니다.

    python tests/live_photo_extract.py

주의: 여기 쓰는 사진은 렌더링한 문서를 사진 해상도로 늘린 것입니다. 조명, 그림자,
기울기, 손글씨, 한글 본문이 섞인 진짜 촬영본은 이보다 어렵습니다. 이 스크립트가
통과한다는 것은 경로와 보정이 제 일을 한다는 뜻이지, 어떤 사진이든 읽는다는
뜻은 아닙니다.
"""
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import sample_formats as SF                       # noqa: E402
from server.termsheet import process_termsheet, prepare_photo, load_env_file  # noqa: E402

# sample_formats.TERMS / SCHEDULE 이 정답입니다. 눈으로 맞춰보지 않고 대조합니다.
EXPECT = {
    "product": "USD",
    "position": "Pay Fixed",
    "notionalDisplay": "100,000,000",
    "effectiveDate": "2026-09-15",
    "maturityDate": "2031-09-15",
    "coupon": "3.6500",
    "leg1DayCount": "Act/360",
}
EXPECT_NOTIONALS = [100000000, 80000000, 60000000, 40000000, 20000000]

fails = []


def ok(m):
    print(f"  PASS  {m}")


def bad(m):
    fails.append(m)
    print(f"  FAIL  {m}")


def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def main():
    load_env_file()

    # 세로로 찍은 4032x3024 사진. 폰 갤러리에서 올라오는 그대로의 조건입니다.
    raw = SF.phone_jpeg_bytes(4032, 3024, orientation=6)
    out, mime, notes = prepare_photo(raw, "IMG_4821.JPG")
    print(f"  올림   {len(raw)/1e6:.1f}MB, 4032x3024, EXIF 회전=6")
    print(f"  보정   {mime}, {len(out)/1024:.0f}KB — {', '.join(notes)}")
    print("  모델 호출 중…\n")

    try:
        r = process_termsheet(raw, filename="IMG_4821.JPG")
    except Exception as e:
        bad(f"사진 추출이 실패함: {type(e).__name__}: {e}")
        return 1

    if not r.get("supported"):
        bad(f"평가 불가로 떨어짐: {r.get('unsupported_reason')}")
        return 1
    ok("사진 한 장으로 추출 성공")

    t = r.get("ticket_draft") or {}
    for key, want in EXPECT.items():
        got = t.get(key)
        same = (num(got) == num(want)) if num(want) is not None else (
            str(got or "").strip().lower() == want.lower())
        if same:
            ok(f"{key:<18} {got}")
        else:
            bad(f"{key:<18} 읽음={got!r}  실제={want!r}")

    sched = r.get("schedule_preview") or []
    got_n = [int(p.get("notional") or 0) for p in sched]
    if got_n == EXPECT_NOTIONALS:
        ok(f"상각 스케줄 {len(sched)}개 기간이 정확히 일치")
    else:
        bad(f"스케줄이 다름 — 읽음={got_n} 실제={EXPECT_NOTIONALS}")

    print(f"\n  {len(fails)} failed\n")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    print("\n=== LIVE: 실제 모델이 실제 사진을 읽는가 ===\n")
    sys.exit(main())
