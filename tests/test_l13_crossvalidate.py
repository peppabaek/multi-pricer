"""L13 - two-model cross-validation of extraction (reconciliation logic, no API needed)."""
import sys
from harness import case, run_all

from server.crossvalidate import compare_extractions, disagreement_fields, MATERIAL_FIELDS
from server.termsheet import process_termsheet, ExtractedTrade, SchedulePeriod, Provenance
from test_l10_termsheet import _MINIMAL_PDF, _fake_trade


def base(**over):
    d = dict(
        supported=True, currency="KRW", position="Pay Fixed", notional=5e10,
        effective_date="2026-09-15", maturity_date="2031-09-15",
        fixed_coupon_pct=2.72, tenor="5Y",
        leg1_day_count="Act/365", leg1_payment_freq="3M",
        leg1_business_day_conv="Modified Following", leg1_calendar="SEB",
        leg2_day_count="Act/365", leg2_payment_freq="3M", leg2_calendar="SEB",
    )
    d.update(over)
    return ExtractedTrade(**d)


@case("L13-1", "identical readings produce no disagreements")
def t_1():
    c = compare_extractions(base(), base())
    if c["disagreements"]:
        raise AssertionError(f"identical extractions disagreed: {c['disagreements']}")
    if "fixed_coupon_pct" not in c["agreed_fields"]:
        raise AssertionError("agreement not recorded")


@case("L13-2", "a coupon difference is caught and reported both ways")
def t_2():
    c = compare_extractions(base(), base(fixed_coupon_pct=2.27), "claude", "gemini")
    fields = disagreement_fields(c)
    if fields != ["fixed_coupon_pct"]:
        raise AssertionError(f"expected only the coupon to differ, got {fields}")
    d = c["disagreements"][0]
    if d["claude"] != 2.72 or d["gemini"] != 2.27:
        raise AssertionError(f"both readings not reported: {d}")


@case("L13-3", "a convention difference is caught")
def t_3():
    c = compare_extractions(base(), base(leg1_day_count="Act/360"))
    if "leg1_day_count" not in disagreement_fields(c):
        raise AssertionError("day count difference missed")


@case("L13-4", "one model reading a field the other missed is a disagreement")
def t_4():
    c = compare_extractions(base(spread_bp=25.0), base())
    if "spread_bp" not in disagreement_fields(c):
        raise AssertionError("null vs value not flagged")


@case("L13-5", "rounding noise inside tolerance is not a disagreement")
def t_5():
    c = compare_extractions(base(notional=50_000_000_000.0),
                            base(notional=50_000_000_000.4))
    if "notional" in disagreement_fields(c):
        raise AssertionError("sub-tolerance notional difference wrongly flagged")


@case("L13-6", "disagreement on whether the product is priceable stops everything")
def t_6():
    c = compare_extractions(base(), ExtractedTrade(supported=False,
                                                  unsupported_reason="Callable"))
    if c["supported_match"]:
        raise AssertionError("supported mismatch not detected")
    if disagreement_fields(c) != ["supported"]:
        raise AssertionError(f"expected to stop at 'supported', got {disagreement_fields(c)}")


@case("L13-7", "schedule differences are detected period by period")
def t_7():
    rows_a = [SchedulePeriod(start_date="2026-09-15", end_date="2027-09-15", notional=5e10),
              SchedulePeriod(start_date="2027-09-15", end_date="2028-09-15", notional=4e10)]
    rows_b = [SchedulePeriod(start_date="2026-09-15", end_date="2027-09-15", notional=5e10),
              SchedulePeriod(start_date="2027-09-15", end_date="2028-09-15", notional=3e10)]
    same = compare_extractions(base(leg1_custom_schedule=rows_a),
                               base(leg1_custom_schedule=rows_a))
    if same["schedule_match"] is not True:
        raise AssertionError("identical schedules not recognised")
    diff = compare_extractions(base(leg1_custom_schedule=rows_a),
                               base(leg1_custom_schedule=rows_b))
    if diff["schedule_match"] is not False:
        raise AssertionError("differing schedules not detected")
    if "leg1_custom_schedule" not in disagreement_fields(diff):
        raise AssertionError("schedule difference not reported")


@case("L13-8", "every price-moving field is under comparison")
def t_8():
    for f in ("fixed_coupon_pct", "notional", "effective_date", "maturity_date",
              "leg1_day_count", "leg1_payment_freq", "leg1_calendar",
              "leg2_day_count", "currency", "position"):
        if f not in MATERIAL_FIELDS:
            raise AssertionError(f"{f} is not cross-checked")


@case("L13-9", "a disagreement blocks confirmation in the pipeline")
def t_9():
    def _second(_t):
        tr = _fake_trade(_t)
        tr.fixed_coupon_pct = 2.27      # the other model read a different coupon
        return tr
    res = process_termsheet(_MINIMAL_PDF, extractor=_fake_trade, second_extractor=_second)
    cv = res.get("cross_validation")
    if not cv or not cv.get("compared"):
        raise AssertionError("cross-validation did not run")
    if "fixed_coupon_pct" not in res["unverified_fields"]:
        raise AssertionError(f"disagreement did not block: {res['unverified_fields']}")
    if "coupon" not in res["unverified_fields"]:
        raise AssertionError("ticket field not blocked alongside the extractor field")
    if not any("모델 불일치" in w for w in res["warnings"]):
        raise AssertionError(f"no disagreement warning: {res['warnings']}")


@case("L13-10", "agreement leaves the trade confirmable")
def t_10():
    res = process_termsheet(_MINIMAL_PDF, extractor=_fake_trade, second_extractor=_fake_trade)
    cv = res.get("cross_validation")
    if not cv or cv["disagreements"]:
        raise AssertionError(f"identical models disagreed: {cv}")
    # Only the deliberately fabricated citation in the fixture should remain blocked.
    if set(res["unverified_fields"]) != {"leg2_calendar"}:
        raise AssertionError(f"unexpected blocks: {res['unverified_fields']}")


@case("L13-11", "single-model operation is unaffected when no second provider is set")
def t_11():
    import os
    saved = os.environ.pop("TERMSHEET_SECOND_PROVIDER", None)
    try:
        res = process_termsheet(_MINIMAL_PDF, extractor=_fake_trade)
        if res.get("cross_validation") is not None:
            raise AssertionError("cross-validation ran without a configured provider")
    finally:
        if saved is not None:
            os.environ["TERMSHEET_SECOND_PROVIDER"] = saved


if __name__ == "__main__":
    print("\n=== L13 Two-model cross-validation ===")
    sys.exit(1 if run_all("L13") else 0)
