# -*- coding: utf-8 -*-
"""
End-to-end rehearsal of the two-model flow on the real sample PDFs.

Everything runs for real - PDF parsing, redaction, comparison, the disagreement round,
evidence adjudication, ticket mapping, pricing - except the two network calls, which are
played by stand-ins that reproduce the mistakes a model actually makes: a misread decimal,
a convention confused for the other leg's, a hallucinated citation, a genuine ambiguity.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from fastapi.testclient import TestClient
from server.app import app
from server.termsheet import (
    process_termsheet, extract_text, ExtractedTrade, Provenance, SchedulePeriod,
)
from sample_termsheets import pdf, SAMPLES, SECRETS

client = TestClient(app)

TRUTH = dict(
    supported=True, currency="KRW", position="Rec Fixed", notional=5e10,
    effective_date="2026-09-15", maturity_date="2031-09-15",
    fixed_coupon_pct=2.72, tenor="5Y",
    leg1_day_count="Act/365 Fixed", leg1_payment_freq="Quarterly",
    leg1_business_day_conv="Modified Following", leg1_adjust_rule="Adjusted",
    leg1_calendar="SEB", leg2_day_count="Act/365 Fixed",
    leg2_payment_freq="Quarterly", leg2_calendar="SEB",
)

Q_COUPON = "Fixed Rate:                      2.7200 per cent per annum"
Q_NOTIONAL = "Notional Amount:                 KRW 50,000,000,000"
Q_DC = "Fixed Rate Day Count Fraction:   Act/365 Fixed"


def model_a(_text):
    """Reads the document correctly."""
    return ExtractedTrade(**TRUTH, provenance=[
        Provenance(field="fixed_coupon_pct", source="extracted", quote=Q_COUPON),
        Provenance(field="notional", source="extracted", quote=Q_NOTIONAL),
        Provenance(field="leg1_day_count", source="extracted", quote=Q_DC),
    ])


def model_b(_text):
    """Three realistic mistakes: a decimal slip, a wrong day count, a wrong calendar."""
    d = dict(TRUTH)
    d["fixed_coupon_pct"] = 27.2          # decimal misread
    d["leg1_day_count"] = "Act/360"       # convention confused
    d["leg1_calendar"] = "SEB_NYB"        # business centres over-read
    return ExtractedTrade(**d, provenance=[])


def review_a(_text, _disputes):
    return {
        # Holds its ground, and can point at the line that settles it.
        "fixed_coupon_pct": {"value": 2.72, "quote": Q_COUPON, "changed": False},
        "leg1_day_count": {"value": "Act/365 Fixed", "quote": Q_DC, "changed": False},
        # Honest about what the document does not settle.
        "leg1_calendar": {"value": "SEB", "quote": None, "changed": False,
                          "note": "문서에 명시된 business centre는 Seoul 뿐"},
    }


def review_b(_text, _disputes):
    return {
        # Re-reads and concedes the coupon.
        "fixed_coupon_pct": {"value": 2.72, "quote": None, "changed": True,
                             "note": "재확인 결과 2.7200"},
        # Digs in with a citation that is not in the document.
        "leg1_day_count": {"value": "Act/360",
                           "quote": "Day Count Fraction: Act/360", "changed": False},
        # Also cannot cite anything.
        "leg1_calendar": {"value": "SEB_NYB", "quote": None, "changed": False},
    }


def main():
    print("=" * 74)
    print("  두 모델 교차검증 리허설 — TS-A (KRW CD 91D IRS)")
    print("=" * 74)

    raw = pdf("TS-A")
    res = process_termsheet(raw, extractor=model_a, second_extractor=model_b,
                            reviewers=(review_a, review_b))

    cv, adj = res["cross_validation"], res["adjudication"]
    print(f"\n[1] 1차 추출 비교  — 일치 {len(cv['agreed_fields'])}개, "
          f"불일치 {len(cv['disagreements'])}개")
    for d in cv["disagreements"]:
        print(f"    · {d['field']}: A={d['claude']!r}  B={d['secondary']!r}")

    print(f"\n[2] 재검토 및 판정")
    for rec in adj["trail"]:
        v = rec["quote_verified"]
        print(f"    · {rec['field']}")
        print(f"        1라운드  A={rec['round1']['claude']!r}  B={rec['round1']['secondary']!r}")
        print(f"        2라운드  A={rec['round2']['claude']!r}  B={rec['round2']['secondary']!r}")
        print(f"        인용검증 A={'OK' if v['claude'] else '실패/없음'}  "
              f"B={'OK' if v['secondary'] else '실패/없음'}")
        print(f"        판정     {rec['resolution']} → {rec['final']!r}"
              + (f"   오류: {', '.join(rec['wrong'])}" if rec.get("wrong") else ""))
        if rec.get("note"):
            print(f"        비고     {rec['note']}")

    print(f"\n[3] 모델별 오류 집계: {adj['error_counts']}")
    print(f"    해결 {len(adj['resolved'])}건 / 미해결 {len(adj['unresolved'])}건 "
          f"{adj['unresolved']}")

    print(f"\n[4] 확정 차단 필드: {res['unverified_fields']}")
    for w in res["warnings"]:
        print(f"    {w}")

    print(f"\n[5] 마스킹: {res['redaction']['counts']}  누출: {res['redaction']['leaks'] or '없음'}")
    blob = json.dumps(res, ensure_ascii=False).lower()
    leaked = [s for s in SECRETS["TS-A"] if s.lower() in blob]
    print(f"    결과에 남은 거래상대 정보: {leaked or '없음'}")

    d = res["ticket_draft"]
    print(f"\n[6] 최종 티켓 초안")
    for k in ("product", "notionalDisplay", "coupon", "effectiveDate", "maturityDate",
              "leg1DayCount", "leg1PaymentFreq", "leg1PayCal"):
        print(f"    {k:18s} {d.get(k)!r}")

    print(f"\n[7] 프라이싱 (미해결 필드는 트레이더 확정 전제)")
    pr = client.post("/api/krw/price", json={
        "tenor": d["customTenorInput"], "position": d["position"],
        "notional": float(str(d["notionalDisplay"]).replace(",", "")),
        "effective_date": d["effectiveDate"], "maturity_date": d["maturityDate"],
        "fixed_coupon_pct": float(d["coupon"]),
        "leg1_day_count": d["leg1DayCount"], "leg1_payment_freq": d["leg1PaymentFreq"],
        "leg1_business_day_conv": d["leg1Convention"], "leg1_calendar": d["leg1PayCal"],
    })
    if pr.status_code != 200:
        print(f"    FAILED HTTP {pr.status_code}: {pr.text[:200]}")
        return 1
    p = pr.json()["data"]["pricing_results"]
    print(f"    par {p['par_swap_rate_pct']:.4f}%   NPV {p['deal_npv']:>18,.0f}"
          f"   DV01 {p['dv01']:>14,.0f}/bp")
    print(f"    기간 수 {len(pr.json()['data']['schedules']['leg1_fixed'])}")

    ok = (adj["error_counts"].get("secondary") == 2
          and adj["unresolved"] == ["leg1_calendar"]
          and not leaked)
    print("\n" + "=" * 74)
    print("  결과: " + ("예상대로 동작 (B의 오류 2건 적발, 모호한 1건은 트레이더에게)"
                      if ok else "예상과 다름 — 확인 필요"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
