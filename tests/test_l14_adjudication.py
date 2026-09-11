"""
L14 - the disagreement round: two models re-read, the document decides, the loser is named.
"""
import sys
from harness import case, run_all

from server.crossvalidate import compare_extractions, adjudicate, format_disputes
from server.termsheet import process_termsheet, ExtractedTrade, Provenance
from test_l10_termsheet import _MINIMAL_PDF, SAMPLE

DOC = SAMPLE  # the fixture document the quotes must be found in


def base(**over):
    d = dict(supported=True, currency="KRW", position="Pay Fixed", notional=5e10,
             effective_date="2026-09-15", maturity_date="2031-09-15",
             fixed_coupon_pct=2.72, tenor="5Y", leg1_day_count="Act/365",
             leg1_payment_freq="3M", leg1_calendar="SEB")
    d.update(over)
    return ExtractedTrade(**d)


def cmp2(a, b):
    return compare_extractions(a, b, "claude", "gemini")


# ---------------------------------------------------------------- convergence
@case("L14-1", "when both models change to the same answer, the movers are recorded")
def t_1():
    c = cmp2(base(fixed_coupon_pct=2.72), base(fixed_coupon_pct=2.27))
    adj = adjudicate(
        c,
        {"fixed_coupon_pct": {"value": 2.72, "quote": None, "changed": False}},
        {"fixed_coupon_pct": {"value": 2.72, "quote": None, "changed": True}},
        DOC)
    if adj["resolved"].get("fixed_coupon_pct") != 2.72:
        raise AssertionError(f"not resolved to 2.72: {adj['resolved']}")
    rec = adj["trail"][0]
    if rec["resolution"] != "converged":
        raise AssertionError(rec["resolution"])
    if rec["wrong"] != ["gemini"]:
        raise AssertionError(f"wrong model not identified: {rec['wrong']}")
    if adj["error_counts"].get("gemini") != 1:
        raise AssertionError(f"error not counted: {adj['error_counts']}")


@case("L14-2", "the primary model can be the one that was wrong")
def t_2():
    c = cmp2(base(leg1_day_count="Act/360"), base(leg1_day_count="Act/365"))
    adj = adjudicate(
        c,
        {"leg1_day_count": {"value": "Act/365", "changed": True}},
        {"leg1_day_count": {"value": "Act/365", "changed": False}},
        DOC)
    rec = adj["trail"][0]
    if rec["wrong"] != ["claude"]:
        raise AssertionError(f"expected claude wrong, got {rec['wrong']}")
    if adj["resolved"]["leg1_day_count"] != "Act/365":
        raise AssertionError(adj["resolved"])


# ---------------------------------------------------------------- evidence
@case("L14-3", "a verifiable quote beats an unsupported answer")
def t_3():
    c = cmp2(base(fixed_coupon_pct=2.72), base(fixed_coupon_pct=2.27))
    adj = adjudicate(
        c,
        {"fixed_coupon_pct": {"value": 2.72,
                              "quote": "Fixed Rate: 2.7200 per cent per annum"}},
        {"fixed_coupon_pct": {"value": 2.27, "quote": "Fixed Rate: 2.2700 per annum"}},
        DOC)
    rec = adj["trail"][0]
    if rec["resolution"] != "evidence":
        raise AssertionError(f"expected evidence ruling, got {rec['resolution']}")
    if adj["resolved"]["fixed_coupon_pct"] != 2.72:
        raise AssertionError(adj["resolved"])
    if rec["wrong"] != ["gemini"]:
        raise AssertionError(rec["wrong"])
    if rec["quote_verified"] != {"claude": True, "gemini": False}:
        raise AssertionError(rec["quote_verified"])


@case("L14-4", "a fabricated quote does not win")
def t_4():
    c = cmp2(base(notional=5e10), base(notional=9.9e10))
    adj = adjudicate(
        c,
        {"notional": {"value": 5e10,
                      "quote": "Notional Amount: KRW 50,000,000,000"}},
        {"notional": {"value": 9.9e10,
                      "quote": "Notional Amount: KRW 99,000,000,000"}},
        DOC)
    if adj["resolved"].get("notional") != 5e10:
        raise AssertionError(f"fabricated quote won: {adj['resolved']}")
    if adj["trail"][0]["wrong"] != ["gemini"]:
        raise AssertionError(adj["trail"][0]["wrong"])


@case("L14-5", "quote matching tolerates whitespace differences")
def t_5():
    c = cmp2(base(leg1_day_count="Act/365"), base(leg1_day_count="Act/360"))
    adj = adjudicate(
        c,
        {"leg1_day_count": {"value": "Act/365",
                            "quote": "Fixed Rate Day Count Fraction: Act/365 Fixed"}},
        {"leg1_day_count": {"value": "Act/360", "quote": None}},
        DOC)
    if adj["trail"][0]["resolution"] != "evidence":
        raise AssertionError("whitespace-normalised quote was not accepted")


# ---------------------------------------------------------------- unresolved
@case("L14-6", "neither able to cite evidence leaves the field for the trader")
def t_6():
    c = cmp2(base(leg1_calendar="SEB"), base(leg1_calendar="SEB_NYB"))
    adj = adjudicate(
        c,
        {"leg1_calendar": {"value": "SEB", "quote": None}},
        {"leg1_calendar": {"value": "SEB_NYB", "quote": None}},
        DOC)
    if "leg1_calendar" in adj["resolved"]:
        raise AssertionError("an answer was invented without evidence")
    if adj["unresolved"] != ["leg1_calendar"]:
        raise AssertionError(adj["unresolved"])
    if adj["trail"][0]["wrong"] is not None:
        raise AssertionError("blamed a model without grounds")


@case("L14-7", "both citing verifiable but different text stays unresolved")
def t_7():
    c = cmp2(base(leg1_payment_freq="3M"), base(leg1_payment_freq="6M"))
    adj = adjudicate(
        c,
        {"leg1_payment_freq": {"value": "3M",
                               "quote": "Fixed Rate Payer Payment Dates: Quarterly"}},
        # Both quotes are really in the document, but they point different ways.
        {"leg1_payment_freq": {"value": "6M",
                               "quote": "Floating Rate Option: KRW-CD-91D"}},
        DOC)
    rec = adj["trail"][0]
    if rec["resolution"] != "unresolved":
        raise AssertionError(f"ambiguity was forced to a decision: {rec}")
    if "양쪽 모두 근거" not in (rec.get("note") or ""):
        raise AssertionError(rec.get("note"))


# ---------------------------------------------------------------- audit trail
@case("L14-8", "the trail records both rounds and both quotes for every dispute")
def t_8():
    c = cmp2(base(fixed_coupon_pct=2.72, notional=5e10),
             base(fixed_coupon_pct=2.27, notional=4e10))
    adj = adjudicate(
        c,
        {"fixed_coupon_pct": {"value": 2.72, "quote": "Fixed Rate: 2.7200 per cent per annum"},
         "notional": {"value": 5e10, "quote": "Notional Amount: KRW 50,000,000,000"}},
        {"fixed_coupon_pct": {"value": 2.72, "changed": True},
         "notional": {"value": 4e10, "quote": None}},
        DOC)
    if len(adj["trail"]) != 2:
        raise AssertionError(f"expected 2 records, got {len(adj['trail'])}")
    for rec in adj["trail"]:
        for key in ("round1", "round2", "quotes", "quote_verified", "resolution", "final"):
            if key not in rec:
                raise AssertionError(f"{rec['field']}: trail missing {key}")
        if set(rec["round1"]) != {"claude", "gemini"}:
            raise AssertionError(rec["round1"])


@case("L14-9", "error counts accumulate across fields")
def t_9():
    c = cmp2(base(fixed_coupon_pct=2.72, notional=5e10),
             base(fixed_coupon_pct=2.27, notional=4e10))
    adj = adjudicate(
        c,
        {"fixed_coupon_pct": {"value": 2.72, "quote": "Fixed Rate: 2.7200 per cent per annum"},
         "notional": {"value": 5e10, "quote": "Notional Amount: KRW 50,000,000,000"}},
        {"fixed_coupon_pct": {"value": 2.27, "quote": None},
         "notional": {"value": 4e10, "quote": None}},
        DOC)
    if adj["error_counts"].get("gemini") != 2:
        raise AssertionError(f"expected 2 gemini errors: {adj['error_counts']}")
    if adj["error_counts"].get("claude"):
        raise AssertionError(f"claude wrongly blamed: {adj['error_counts']}")


# ---------------------------------------------------------------- pipeline
def _a(_t):
    return ExtractedTrade(
        supported=True, currency="KRW", position="Pay Fixed", notional=5e10,
        effective_date="2026-09-15", maturity_date="2031-09-15",
        fixed_coupon_pct=2.72, tenor="5Y", leg1_day_count="Act/365",
        leg1_payment_freq="3M", leg1_calendar="SEB",
        provenance=[Provenance(field="fixed_coupon_pct", source="extracted",
                               quote="Fixed Rate: 2.7200 per cent per annum")])


def _b(_t):
    tr = _a(_t)
    tr.fixed_coupon_pct = 2.27      # the second model misreads the coupon
    return tr


@case("L14-10", "pipeline: a settled disagreement releases the field for pricing")
def t_10():
    def rev_a(_text, _disputes):
        return {"fixed_coupon_pct": {"value": 2.72,
                                     "quote": "Fixed Rate: 2.7200 per cent per annum"}}

    def rev_b(_text, _disputes):
        return {"fixed_coupon_pct": {"value": 2.72, "changed": True}}

    res = process_termsheet(_MINIMAL_PDF, extractor=_a, second_extractor=_b,
                            reviewers=(rev_a, rev_b))
    adj = res["adjudication"]
    if not adj or adj["resolved"].get("fixed_coupon_pct") != 2.72:
        raise AssertionError(f"not settled: {adj}")
    if "fixed_coupon_pct" in res["unverified_fields"] or "coupon" in res["unverified_fields"]:
        raise AssertionError(f"settled field still blocked: {res['unverified_fields']}")
    if res["ticket_draft"]["coupon"] != "2.7200":
        raise AssertionError(f"resolved value not applied: {res['ticket_draft']['coupon']}")
    if not any("재검토 합의" in w for w in res["warnings"]):
        raise AssertionError(res["warnings"])


@case("L14-11", "pipeline: an unsettled disagreement still blocks confirmation")
def t_11():
    def rev_a(_text, _disputes):
        return {"fixed_coupon_pct": {"value": 2.72, "quote": None}}

    def rev_b(_text, _disputes):
        return {"fixed_coupon_pct": {"value": 2.27, "quote": None}}

    res = process_termsheet(_MINIMAL_PDF, extractor=_a, second_extractor=_b,
                            reviewers=(rev_a, rev_b))
    if "fixed_coupon_pct" not in res["unverified_fields"]:
        raise AssertionError(f"unsettled dispute not blocked: {res['unverified_fields']}")
    if not any("미해결" in w for w in res["warnings"]):
        raise AssertionError(res["warnings"])


@case("L14-12", "pipeline: the losing model is named in the record")
def t_12():
    def rev_a(_text, _disputes):
        return {"fixed_coupon_pct": {"value": 2.72,
                                     "quote": "Fixed Rate: 2.7200 per cent per annum"}}

    def rev_b(_text, _disputes):
        return {"fixed_coupon_pct": {"value": 2.27, "quote": "Fixed Rate: 2.2700"}}

    res = process_termsheet(_MINIMAL_PDF, extractor=_a, second_extractor=_b,
                            reviewers=(rev_a, rev_b))
    adj = res["adjudication"]
    rec = adj["trail"][0]
    if rec["wrong"] != ["secondary"]:
        raise AssertionError(f"loser not recorded: {rec}")
    if adj["error_counts"].get("secondary") != 1:
        raise AssertionError(adj["error_counts"])
    if not any("근거 판정" in w for w in res["warnings"]):
        raise AssertionError(res["warnings"])


if __name__ == "__main__":
    print("\n=== L14 Disagreement adjudication ===")
    sys.exit(1 if run_all("L14") else 0)
