"""
Cross-validation of term sheet extraction by two independent models.

Why only extraction: reading a document is a judgement call, and two models that fail
differently are a real check on each other. Pricing is not - it is deterministic
arithmetic over a calibrated curve, already pinned by the invariant suite (par -> NPV 0,
analytic DV01 vs finite difference, sum of key-rate deltas vs DV01, Murex parity). Asking
a language model to "check" a DV01 would return a less reliable number wearing the same
confidence, so this module deliberately does not do that. The pricing-side check that does
earn its place is the market cross-check already in the pipeline: a coupon far from the
curve's par rate is flagged for the trader.
"""

import os
from typing import Any, Dict, List, Optional, Tuple, Callable

from pydantic import BaseModel

# Fields where the two extractions must agree before a trade can be confirmed.
# These are the terms that move the price.
MATERIAL_FIELDS = [
    "currency", "position", "notional", "usd_notional", "krw_notional",
    "effective_date", "maturity_date", "tenor", "fixed_coupon_pct", "spread_bp",
    "crs_swap_type", "usd_fixed_coupon_pct", "payment_lag_bd",
    "leg1_day_count", "leg1_payment_freq", "leg1_business_day_conv",
    "leg1_stub_rule", "leg1_adjust_rule", "leg1_calendar",
    "leg2_day_count", "leg2_payment_freq", "leg2_business_day_conv",
    "leg2_stub_rule", "leg2_adjust_rule", "leg2_calendar", "leg2_fix_day",
]

# Money and rates rarely match to the last bit across models; these are the widths
# inside which two readings mean the same thing.
_NUMERIC_TOL = {
    "notional": 1.0,
    "usd_notional": 1.0,
    "krw_notional": 1.0,
    "fixed_coupon_pct": 1e-6,
    "usd_fixed_coupon_pct": 1e-6,
    "spread_bp": 1e-6,
    "payment_lag_bd": 0,
    "leg2_fix_day": 0,
}


def _agree(field: str, a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= _NUMERIC_TOL.get(field, 1e-9)
    return str(a).strip() == str(b).strip()


def _schedule_rows(trade) -> List[Tuple]:
    sched = getattr(trade, "leg1_custom_schedule", None) or []
    return [(p.start_date, p.end_date, round(float(p.notional), 2),
             None if p.fixed_rate_pct is None else round(float(p.fixed_rate_pct), 6))
            for p in sched]


def compare_extractions(primary, secondary,
                        primary_name: str = "claude",
                        secondary_name: str = "secondary") -> Dict[str, Any]:
    """
    Reconcile two independent readings of the same document.

    Returns the disagreements, not a merged answer: where the models differ the trader
    decides, because silently preferring one model would hide exactly the ambiguity the
    second opinion was bought to expose.
    """
    result: Dict[str, Any] = {
        "compared": True,
        "primary": primary_name,
        "secondary": secondary_name,
        "disagreements": [],
        "agreed_fields": [],
        "schedule_match": None,
        "supported_match": True,
    }

    p_sup = bool(getattr(primary, "supported", False))
    s_sup = bool(getattr(secondary, "supported", False))
    if p_sup != s_sup:
        result["supported_match"] = False
        result["disagreements"].append({
            "field": "supported",
            primary_name: p_sup,
            secondary_name: s_sup,
            "note": "한쪽 모델은 평가 가능, 다른 쪽은 불가로 판단했습니다",
        })
        return result

    if not p_sup:
        return result

    for f in MATERIAL_FIELDS:
        a = getattr(primary, f, None)
        b = getattr(secondary, f, None)
        if a is None and b is None:
            continue
        if _agree(f, a, b):
            result["agreed_fields"].append(f)
        else:
            result["disagreements"].append({"field": f, primary_name: a, secondary_name: b})

    rows_a, rows_b = _schedule_rows(primary), _schedule_rows(secondary)
    if rows_a or rows_b:
        result["schedule_match"] = rows_a == rows_b
        if rows_a != rows_b:
            result["disagreements"].append({
                "field": "leg1_custom_schedule",
                primary_name: f"{len(rows_a)} periods",
                secondary_name: f"{len(rows_b)} periods",
                "note": "스케줄이 일치하지 않습니다 - 기간·원금·금리를 직접 대조하세요",
            })

    return result


def disagreement_fields(comparison: Dict[str, Any]) -> List[str]:
    return [d["field"] for d in comparison.get("disagreements", [])]


# ---------------------------------------------------------------- adjudication
#
# When the two readings differ, each model re-reads the document for those fields only.
# The second round is decided on evidence, not on agreement: a model must quote the text
# that settles the point, and the server checks that quote actually appears in the
# document. That matters because a model shown the other's answer will often simply
# adopt it - consensus reached that way is not a second opinion, it is an echo. Tying
# the outcome to a verifiable quote means the document decides, not the louder model.

REVIEW_PROMPT = """A second reading of this termsheet disagrees with yours on the fields below.

For each field, re-read the document and decide what it actually says. Do not defer to the
other reading because it is there - it may be wrong. It is equally possible that you were wrong.

For each field return:
  - field: the field name
  - value: your final answer after re-reading (null if the document does not state it)
  - quote: the exact text from the document that settles it, copied verbatim, character for
    character. If nothing in the document settles it, leave this null and say so in `note`.
  - changed: true if this differs from your first answer
  - note: one short line on what decided it

Your answer is accepted only if the quote is found in the document, so quote precisely.

Fields in dispute:
{disputes}
"""


def _quote_supports(quote: Optional[str], doc_text: str) -> bool:
    """A quote counts only if it really is in the document."""
    if not quote:
        return False
    import re
    squash = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()
    return squash(quote) in squash(doc_text)


def adjudicate(comparison: Dict[str, Any],
               review_primary: Dict[str, Dict[str, Any]],
               review_secondary: Dict[str, Dict[str, Any]],
               doc_text: str) -> Dict[str, Any]:
    """
    Settle the disputed fields from the second round.

    Returns the resolved values, the fields still unresolved, and a per-field record of
    what each model said in each round and which of them was wrong.
    """
    p = comparison.get("primary", "primary")
    s = comparison.get("secondary", "secondary")

    resolved: Dict[str, Any] = {}
    unresolved: List[str] = []
    trail: List[Dict[str, Any]] = []
    scoreboard: Dict[str, int] = {p: 0, s: 0}

    for d in comparison.get("disagreements", []):
        field = d["field"]
        r1_p, r1_s = d.get(p), d.get(s)
        a = review_primary.get(field) or {}
        b = review_secondary.get(field) or {}
        r2_p, r2_s = a.get("value"), b.get("value")
        q_p, q_s = a.get("quote"), b.get("quote")

        rec: Dict[str, Any] = {
            "field": field,
            "round1": {p: r1_p, s: r1_s},
            "round2": {p: r2_p, s: r2_s},
            "quotes": {p: q_p, s: q_s},
        }

        p_ok = _quote_supports(q_p, doc_text)
        s_ok = _quote_supports(q_s, doc_text)
        rec["quote_verified"] = {p: p_ok, s: s_ok}

        if _agree(field, r2_p, r2_s):
            # They converged. Whoever moved was the one that had it wrong.
            resolved[field] = r2_p
            rec["resolution"] = "converged"
            rec["final"] = r2_p
            moved = []
            if not _agree(field, r1_p, r2_p):
                moved.append(p)
            if not _agree(field, r1_s, r2_s):
                moved.append(s)
            rec["corrected"] = moved
            for m in moved:
                scoreboard[m] = scoreboard.get(m, 0) + 1
            rec["wrong"] = moved or None
        elif p_ok and not s_ok:
            resolved[field] = r2_p
            rec["resolution"] = "evidence"
            rec["final"] = r2_p
            rec["wrong"] = [s]
            scoreboard[s] = scoreboard.get(s, 0) + 1
        elif s_ok and not p_ok:
            resolved[field] = r2_s
            rec["resolution"] = "evidence"
            rec["final"] = r2_s
            rec["wrong"] = [p]
            scoreboard[p] = scoreboard.get(p, 0) + 1
        else:
            # Both quoted verifiable text yet still differ, or neither could quote
            # anything: the document is genuinely ambiguous. Do not invent an answer.
            unresolved.append(field)
            rec["resolution"] = "unresolved"
            rec["final"] = None
            rec["wrong"] = None
            rec["note"] = ("양쪽 모두 근거를 제시했으나 값이 다릅니다"
                           if (p_ok and s_ok) else
                           "양쪽 모두 문서에서 근거를 찾지 못했습니다")
        trail.append(rec)

    return {
        "adjudicated": True,
        "primary": p,
        "secondary": s,
        "resolved": resolved,
        "unresolved": unresolved,
        "trail": trail,
        "error_counts": scoreboard,
    }


def format_disputes(comparison: Dict[str, Any]) -> str:
    p = comparison.get("primary", "primary")
    s = comparison.get("secondary", "secondary")
    lines = []
    for d in comparison.get("disagreements", []):
        lines.append(f"- {d['field']}: your reading = {d.get(p)!r}, "
                     f"other reading = {d.get(s)!r}")
    return "\n".join(lines)


# ---------------------------------------------------------------- reviewers
class FieldReview(BaseModel):
    field: str
    value: Optional[Any] = None
    quote: Optional[str] = None
    changed: bool = False
    note: Optional[str] = None


class ReviewSet(BaseModel):
    reviews: List[FieldReview] = []


def claude_reviewer(redacted_text: str, disputes: str) -> Dict[str, Dict[str, Any]]:
    """Second-round re-read by Claude, restricted to the disputed fields."""
    import anthropic
    from server.termsheet import MODEL, SYSTEM_PROMPT

    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=MODEL,
        max_tokens=8000,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (f"{REVIEW_PROMPT.format(disputes=disputes)}\n\n"
                        f"Document:\n\n{redacted_text}"),
        }],
        output_format=ReviewSet,
    )
    return {r.field: r.model_dump() for r in resp.parsed_output.reviews}


SECOND_MODEL_ENV = "TERMSHEET_SECOND_MODEL"
DEFAULT_SECOND_MODEL = "claude-opus-5"


def secondary_reviewer() -> Optional[Callable[[str, str], Dict[str, Dict[str, Any]]]]:
    """Second-round reviewer for whichever provider is configured as the cross-check."""
    from server.providers import get_reviewer
    name = os.environ.get("TERMSHEET_SECOND_PROVIDER", "").strip().lower()
    if not name:
        return None
    return get_reviewer(name, SECOND_MODEL_ENV)


# ---------------------------------------------------------------- providers
def secondary_extractor() -> Optional[Callable[[str], Any]]:
    """
    The second opinion, if one is configured.

    Any provider in the registry can fill this slot, so a free tier on one vendor can
    cross-check a free tier on another and the pair costs nothing to run.
    """
    from server.providers import get_extractor, PROVIDERS

    name = os.environ.get("TERMSHEET_SECOND_PROVIDER", "").strip().lower()
    if not name:
        return None
    if name not in PROVIDERS:
        raise ValueError(f"알 수 없는 TERMSHEET_SECOND_PROVIDER: {name!r} "
                         f"(사용 가능: {', '.join(PROVIDERS)})")
    return get_extractor(name, SECOND_MODEL_ENV)
