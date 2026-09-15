"""
Termsheet extraction: PDF in, trade terms out.

Nothing is persisted. The PDF binary never leaves this process - only redacted
text is sent to the model - and every intermediate is dropped when the request ends.
"""

import io
import os
import re
import hashlib
import datetime
from typing import List, Optional, Dict, Any, Tuple, Literal

from pydantic import BaseModel, Field

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ENV_FILE = os.path.join(_PROJECT_ROOT, ".env")


def load_env_file(path: str = _ENV_FILE) -> None:
    """
    Read KEY=VALUE lines from .env into the environment.

    Keeps the API key out of the source tree and off the command line; an already-set
    environment variable always wins so a shell export can override the file.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and val:
                    os.environ[key] = val
    except Exception as e:
        print(f"[Termsheet] .env read failed: {e}")


load_env_file()


def extraction_status() -> Dict[str, Any]:
    """Whether extraction can run, on which provider, and how to enable it if not."""
    load_env_file()
    from server.providers import PROVIDERS, describe, is_available, resolve_model

    primary = os.environ.get("TERMSHEET_PROVIDER", "anthropic").strip().lower()
    second = os.environ.get("TERMSHEET_SECOND_PROVIDER", "").strip().lower()
    known = primary in PROVIDERS
    ready = known and is_available(primary)

    out: Dict[str, Any] = {
        "ready": ready,
        "provider": primary,
        "provider_label": PROVIDERS[primary]["label"] if known else primary,
        "model": resolve_model(primary) if known else None,
        "cross_check": bool(second and second in PROVIDERS and is_available(second)),
        "second_provider": second or None,
        "providers": describe(),
    }
    if not ready:
        if not known:
            out["reason"] = f"TERMSHEET_PROVIDER={primary!r} 는 지원하지 않습니다"
        else:
            envs = " 또는 ".join(PROVIDERS[primary]["key_env"]) or "(키 불필요)"
            out["reason"] = f"{PROVIDERS[primary]['label']} 키가 없습니다 ({envs})"
            out["how_to"] = [
                f"{_ENV_FILE} 에 {envs} 를 추가하고 서버를 재시작하세요",
                f"발급: {PROVIDERS[primary]['signup']}",
            ]
        free = [p["name"] for p in out["providers"]
                if p["cost"].startswith("free") and p["available"]]
        if free:
            out["free_available"] = free
    return out


# Conventions the pricer actually understands (server/calendar_manager.py).
DAY_COUNTS = ["Act/365", "Act/360", "30/360", "Act/Act"]
CALENDARS = ["SEB", "LNB", "NYB", "TKB", "SEB_NYB", "TGT", "LNB_TGT", "NYB_TGT",
             "NYB_TKB", "LNB_NYB", "LNB_NYB_TGT", "LNB_TKB", "SEB_TGT", "SEB_TKB",
             "SEB_LNB", "LNB_SEB_TKB", "TGT_TKB", "BMA", "NONE"]
CONVENTIONS = ["Modified Following", "Following", "Preceding"]
STUB_RULES = ["Short in arrears", "Short upfront", "Long in arrears", "Long upfront"]
FREQUENCIES = ["1M", "3M", "6M", "12M"]


# ---------------------------------------------------------------- 1. text
def extract_text(raw: bytes) -> str:
    """Pull text out of a PDF in memory. Never touches disk."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        try:
            pages.append(f"--- page {i} ---\n{page.extract_text() or ''}")
        except Exception:
            pages.append(f"--- page {i} ---\n")
    return "\n\n".join(pages)


# ---------------------------------------------------------------- 2. redaction
# Only label-anchored values and distinctively shaped identifiers are removed.
# Anything a pricer needs - dates, amounts, rates, tenors, conventions - must survive,
# so this deliberately does not guess at bare names.
_PARTY_LABELS = (
    r"Party\s*A|Party\s*B|Counterparty|Counter\s*Party|Client|Customer|"
    r"Buyer|Seller|Dealer|Borrower|Lender|Beneficiary|Obligor|Issuer|Guarantor|"
    r"Account\s*Name|Legal\s*Name|Company\s*Name|Contact|Attention|Attn|"
    r"To|From|Broker|Agent|Payments?\s*to(?:\s*Party\s*[AB])?|"
    r"거래상대방|거래상대|고객명|상대방|매수인|매도인"
)

# Corporate suffixes catch letterheads and signature blocks, where the name carries no
# label at all. No pricing term contains these words, so this cannot eat a rate or a date.
_ENTITY_WORDS = (
    r"Bank|Banking|Securities|Capital|Markets|Investment|Investments|Futures|"
    r"Asset\s+Management|Trust|Holdings|Partners|Financial|Finance|"
    r"Co\.,?\s*Ltd\.?|Company\s+Limited|Ltd\.?|LLC|L\.L\.C\.|Inc\.?|PLC|"
    r"GmbH|S\.A\.|N\.V\.|A\.G\.|Pte\.?\s*Ltd\.?"
)
# Case-insensitive so an all-caps letterhead matches too, but the leading words must
# still be capitalised - (?-i:[A-Z]) keeps that check case-sensitive - and at least one
# is required, so a bare prose word like "trust" is never swallowed.
_ENTITY_RE = re.compile(
    rf"\b(?:(?-i:[A-Z])[\w'&.\-]*\s+){{1,4}}(?:{_ENTITY_WORDS})(?:\s+(?:{_ENTITY_WORDS}))*",
    re.IGNORECASE,
)
_ID_LABELS = (
    r"LEI|BIC|SWIFT|IBAN|Account\s*(?:No|Number|#)|A/C|"
    r"Trade\s*(?:ID|No|Number|Ref)|Deal\s*(?:ID|No|Number|Ref)|"
    r"(?:Our|Your)\s*Ref(?:erence)?|Ref(?:erence)?\s*(?:ID|No|Number)|"
    r"USI|UTI|Address|Tel(?:ephone)?|Fax|Phone"
)

_RULES: List[Tuple[str, "re.Pattern[str]"]] = [
    ("party", re.compile(rf"(?im)^(\s*(?:{_PARTY_LABELS})\s*[:：]\s*)(.+)$")),
    ("identifier", re.compile(rf"(?im)^(\s*(?:{_ID_LABELS})\s*[:：]\s*)(.+)$")),
    ("email", re.compile(r"(?i)\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("lei", re.compile(r"\b[A-Z0-9]{18}\d{2}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s-]\d{3,4}[\s-]\d{4}(?!\d)")),
]

REDACTED = "[REDACTED]"


_GENERIC_VALUES = {
    "applicable", "inapplicable", "n/a", "na", "none", "tbd", "as above",
    "party a", "party b", "seller", "buyer", "the counterparty",
}


_HONORIFIC_RE = re.compile(r"^(?:Mr|Mrs|Ms|Miss|Dr|Prof|Messrs)\.?\s+", re.IGNORECASE)
_SALUTATION_RE = re.compile(
    r"(?im)^\s*Dear\s+(?:Mr|Mrs|Ms|Miss|Dr|Prof|Messrs)?\.?\s*"
    r"([A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+){0,3})")


def _harvest_identity(text: str) -> List[str]:
    """Collect identity strings worth sweeping from the whole document."""
    found: List[str] = []

    def _add(val: str):
        val = val.strip().rstrip(".,;:")
        if len(val) < 4 or val.lower() in _GENERIC_VALUES:
            return
        found.append(val)
        # A name is written several ways across one document: with an honorific on the
        # labelled line, bare in the signature block, with contact details appended.
        bare = _HONORIFIC_RE.sub("", val).strip().rstrip(".,;:")
        if len(bare) >= 4 and bare != val:
            found.append(bare)
        head = re.split(r"\s*[(\[<]", bare)[0].strip().rstrip(".,;:")
        if len(head) >= 4 and head != bare:
            found.append(head)

    label_re = re.compile(rf"(?im)^\s*(?:{_PARTY_LABELS})\s*[:：]\s*(.+)$")
    for m in label_re.finditer(text):
        _add(m.group(1))

    for m in _SALUTATION_RE.finditer(text):
        _add(m.group(1))

    for m in _ENTITY_RE.finditer(text):
        val = m.group(0).strip().rstrip(".,;")
        if len(val) >= 4:
            found.append(val)
            bare = _HONORIFIC_RE.sub("", val).strip()
            if len(bare) >= 4 and bare != val:
                found.append(bare)

    # Longest first so "X Bank Co., Ltd." is removed before the shorter "X Bank".
    return sorted(set(found), key=len, reverse=True)


def redact(text: str) -> Tuple[str, Dict[str, int]]:
    """
    Strip counterparty identity and reference identifiers.

    Three passes, because a termsheet carries identity in three different shapes:
    labelled fields, free-standing entity names (letterheads, signature blocks),
    and structured identifiers. Returns (text, counts).
    """
    counts: Dict[str, int] = {}
    out = text

    # 1. Labelled fields and structured identifiers.
    for name, pattern in _RULES:
        if pattern.groups >= 2:
            def _sub(m, _n=name):
                counts[_n] = counts.get(_n, 0) + 1
                return f"{m.group(1)}{REDACTED}"
            out = pattern.sub(_sub, out)
        else:
            def _sub2(m, _n=name):
                counts[_n] = counts.get(_n, 0) + 1
                return REDACTED
            out = pattern.sub(_sub2, out)

    # 2. Sweep every harvested identity string wherever else it appears - headers,
    #    footers, signature blocks, mid-sentence.
    for ident in _harvest_identity(text):
        if ident == REDACTED or REDACTED in ident:
            continue
        # Case-insensitive: the same name appears title-cased in the body and
        # upper-cased in the letterhead.
        ident_re = re.compile(re.escape(ident), re.IGNORECASE)
        out, hits = ident_re.subn(REDACTED, out)
        if hits:
            counts["name"] = counts.get("name", 0) + hits

    # 3. Entity names introduced only in the redacted text's remaining spans.
    def _sub_entity(m):
        counts["name"] = counts.get("name", 0) + 1
        return REDACTED
    out = _ENTITY_RE.sub(_sub_entity, out)

    return out, counts


def redaction_leaks(redacted_text: str) -> List[str]:
    """Re-scan the redacted text; anything still matching is a leak."""
    leaks = []
    for name, pattern in _RULES:
        for m in pattern.finditer(redacted_text):
            hit = m.group(2) if pattern.groups >= 2 else m.group(0)
            if hit and hit.strip() != REDACTED:
                leaks.append(name)
                break
    return leaks


# ---------------------------------------------------------------- 3. schema
class Provenance(BaseModel):
    field: str
    source: Literal["extracted", "inferred", "missing"]
    quote: Optional[str] = Field(None, description="Verbatim text from the termsheet")
    note: Optional[str] = None


class SchedulePeriod(BaseModel):
    start_date: str
    end_date: str
    pay_date: Optional[str] = None
    notional: float
    fixed_rate_pct: Optional[float] = None
    spread_bp: Optional[float] = None


class ExtractedTrade(BaseModel):
    supported: bool
    unsupported_reason: Optional[str] = None
    # Set by the pipeline, never by the model: marks a canned demo answer.
    demo_fallback: bool = False

    currency: Optional[Literal["USD", "KRW", "KRW_KOFR", "KRW_CRS"]] = None
    position: Optional[Literal["Pay Fixed", "Rec Fixed"]] = None
    notional: Optional[float] = None
    usd_notional: Optional[float] = None
    krw_notional: Optional[float] = None
    spot_fx: Optional[float] = None

    effective_date: Optional[str] = None
    maturity_date: Optional[str] = None
    tenor: Optional[str] = None
    fixed_coupon_pct: Optional[float] = None
    spread_bp: Optional[float] = None

    crs_swap_type: Optional[Literal["Vanilla", "Fixed-Fixed"]] = None
    usd_fixed_coupon_pct: Optional[float] = None
    payment_lag_bd: Optional[int] = None

    leg1_day_count: Optional[str] = None
    leg1_payment_freq: Optional[str] = None
    leg1_business_day_conv: Optional[str] = None
    leg1_stub_rule: Optional[str] = None
    leg1_adjust_rule: Optional[str] = None
    leg1_calendar: Optional[str] = None

    leg2_day_count: Optional[str] = None
    leg2_payment_freq: Optional[str] = None
    leg2_business_day_conv: Optional[str] = None
    leg2_stub_rule: Optional[str] = None
    leg2_adjust_rule: Optional[str] = None
    leg2_calendar: Optional[str] = None
    leg2_fix_day: Optional[int] = None

    leg1_custom_schedule: Optional[List[SchedulePeriod]] = None
    leg2_custom_schedule: Optional[List[SchedulePeriod]] = None

    provenance: List[Provenance] = []
    open_questions: List[str] = []


SYSTEM_PROMPT = f"""You read interest-rate and cross-currency swap termsheets and return the trade terms needed to price them.

The text you receive has already had counterparty identity and reference identifiers removed and replaced with {REDACTED}. That is expected - never report it as missing information, and never try to infer who the parties are.

Rules:

1. Report only what the document states. If a convention is absent, leave the field null and record it as "inferred" or "missing" in provenance - do not silently fill in a market default. The pricer applies its own defaults and shows them to the trader separately.

2. For every field you populate, add a provenance entry with source="extracted" and a quote copied VERBATIM from the document - exact characters, no paraphrase, no normalisation. The server checks each quote against the document text and rejects any it cannot find.

3. Map conventions onto exactly these values:
   - day count: {", ".join(DAY_COUNTS)}
   - payment frequency: {", ".join(FREQUENCIES)}
   - business day convention: {", ".join(CONVENTIONS)}
   - stub rule: {", ".join(STUB_RULES)}
   - adjust rule: Adjust, Unadjust
   - calendar: {", ".join(CALENDARS[:8])} and other combinations from that set
   If the document says something you cannot map confidently (e.g. an unlisted business centre), leave it null and explain in the provenance note.

4. Leg 1 is the fixed / KRW leg. Leg 2 is the floating / USD leg.

5. Product routing:
   - USD SOFR OIS -> currency "USD"
   - KRW CD 91D IRS -> currency "KRW"
   - KRW KOFR OIS -> currency "KRW_KOFR"
   - KRW fixed vs USD SOFR with principal exchange -> currency "KRW_CRS"

6. Amortising, accreting or step-up structures: return every period in leg1_custom_schedule
   (and leg2_custom_schedule if the legs differ). Dates as YYYY-MM-DD.

7. If the trade is something this pricer cannot value - callable, cancellable, CMS-linked,
   range accrual, any optionality - set supported=false with a reason and leave the terms null.
   Do not force it into a vanilla shape.

8. Put anything the trader should confirm with the counterparty into open_questions.

Dates must be YYYY-MM-DD. Rates are percent per annum. Spreads are basis points."""


def demo_mode_enabled() -> bool:
    """Canned sample answers are opt-in and never the default."""
    return os.environ.get("TERMSHEET_DEMO_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def _match_synthetic_sample(text: str) -> Optional[ExtractedTrade]:
    """
    Canned answers for the bundled synthetic samples, for demos without API credit.

    Matching is on values as ordinary as "100,000,000", so a real termsheet can hit these
    patterns by coincidence. Any result from here is therefore marked demo_fallback and
    the pipeline refuses to let it be confirmed or priced.
    """
    if "50,000,000,000" in text and "2.7200" in text:
        return ExtractedTrade(
            supported=True, currency="KRW", position="Rec Fixed", notional=5e10,
            effective_date="2026-09-15", maturity_date="2031-09-15",
            fixed_coupon_pct=2.72, tenor="5Y",
            leg1_day_count="Act/365 Fixed", leg1_payment_freq="Quarterly",
            leg1_business_day_conv="Modified Following", leg1_adjust_rule="Adjusted",
            leg1_calendar="SEB", leg2_day_count="Act/365 Fixed",
            leg2_payment_freq="Quarterly", leg2_calendar="SEB",
            provenance=[
                Provenance(field="notional", source="extracted",
                           quote="Notional Amount:                 KRW 50,000,000,000"),
                Provenance(field="fixed_coupon_pct", source="extracted",
                           quote="Fixed Rate:                      2.7200 per cent per annum"),
                Provenance(field="leg1_day_count", source="extracted",
                           quote="Fixed Rate Day Count Fraction:   Act/365 Fixed"),
                Provenance(field="leg1_business_day_conv", source="extracted",
                           quote="Business Day Convention:         Modified Following"),
            ],
            open_questions=[])
    elif "100,000,000" in text and "3.6500%" in text:
        rows = [("2026-09-15", "2027-09-15", 1e8), ("2027-09-15", "2028-09-15", 8e7),
                ("2028-09-15", "2029-09-15", 6e7), ("2029-09-15", "2030-09-15", 4e7),
                ("2030-09-15", "2031-09-15", 2e7)]
        return ExtractedTrade(
            supported=True, currency="USD", position="Pay Fixed", notional=1e8,
            effective_date="2026-09-15", maturity_date="2031-09-15",
            fixed_coupon_pct=3.65, tenor="5Y",
            leg1_day_count="Act/360", leg1_payment_freq="Annual",
            leg1_business_day_conv="Modified Following", leg1_calendar="NYB",
            leg2_day_count="Act/360", leg2_payment_freq="Annual", leg2_calendar="NYB",
            payment_lag_bd=2,
            leg1_custom_schedule=[SchedulePeriod(start_date=a, end_date=b, notional=n)
                                  for a, b, n in rows],
            provenance=[
                Provenance(field="fixed_coupon_pct", source="extracted",
                           quote="Fixed Rate:                 3.6500%"),
                Provenance(field="leg1_day_count", source="extracted",
                           quote="Day Count:                  Act/360"),
            ],
            open_questions=["Confirm the SOFR observation shift"])
    elif "13,755,000,000" in text and "1,375.50" in text:
        return ExtractedTrade(
            supported=True, currency="KRW_CRS", position="Pay Fixed",
            usd_notional=1e7, krw_notional=1.3755e10, spot_fx=1375.50,
            effective_date="2026-09-15", maturity_date="2031-09-15",
            fixed_coupon_pct=1.08, tenor="5Y", crs_swap_type="Vanilla",
            payment_lag_bd=2,
            leg1_day_count="30/360", leg1_payment_freq="Semi-annual",
            leg1_calendar="SEB_NYB", leg1_business_day_conv="Modified Following",
            leg2_day_count="Act/360", leg2_payment_freq="Semi-annual",
            leg2_calendar="SEB_NYB",
            provenance=[
                Provenance(field="spot_fx", source="extracted",
                           quote="Spot FX Rate (USD/KRW):     1,375.50"),
                Provenance(field="fixed_coupon_pct", source="extracted",
                           quote="Fixed Rate:                 1.0800 per cent per annum"),
            ],
            open_questions=[])
    elif "100,000,000,000" in text and "2.8450%" in text:
        return ExtractedTrade(
            supported=True, currency="KRW_KOFR", position="Rec Fixed", notional=1e11,
            effective_date="2026-09-14", maturity_date="2027-09-14",
            fixed_coupon_pct=2.8450, tenor="1Y",
            leg1_day_count="Act/365 Fixed", leg1_payment_freq="Quarterly",
            leg1_business_day_conv="Modified Following", leg1_calendar="SEB",
            leg2_day_count="Act/365 Fixed", leg2_payment_freq="Quarterly",
            leg2_calendar="SEB", payment_lag_bd=2,
            provenance=[
                Provenance(field="notional", source="extracted",
                           quote="Notional Amount:                 KRW 100,000,000,000"),
                Provenance(field="fixed_coupon_pct", source="extracted",
                           quote="Fixed Rate:                      2.8450% per annum"),
            ],
            open_questions=[])
    return None


# ---------------------------------------------------------------- 4. model call
def primary_provider() -> str:
    """Which model reads the document first. Any provider in the registry will do."""
    return os.environ.get("TERMSHEET_PROVIDER", "anthropic").strip().lower()


def call_extractor(redacted_text: str, model: str = None) -> ExtractedTrade:
    load_env_file()
    from server.providers import get_extractor, PROVIDERS, is_available

    name = primary_provider()
    if name not in PROVIDERS:
        raise ValueError(f"TERMSHEET_PROVIDER={name!r} 는 지원하지 않습니다 "
                         f"(사용 가능: {', '.join(PROVIDERS)})")
    if not is_available(name):
        envs = " 또는 ".join(PROVIDERS[name]["key_env"]) or "(키 불필요)"
        raise ValueError(
            f"{PROVIDERS[name]['label']} 키가 없어 Term Sheet 분석을 실행할 수 없습니다. "
            f"{_ENV_FILE} 에 {envs} 를 추가하세요. "
            f"발급: {PROVIDERS[name]['signup']}")

    try:
        return get_extractor(name)(redacted_text)
    except Exception as e:
        err = str(e).lower()
        if "credit balance is too low" in err or "insufficient_quota" in err:
            if demo_mode_enabled():
                sample = _match_synthetic_sample(redacted_text)
                if sample:
                    sample.demo_fallback = True
                    return sample
            raise ValueError(
                f"{PROVIDERS[name]['label']} 잔액이 부족하여 분석을 완료하지 못했습니다. "
                f"크레딧을 충전하거나, 무료 프로바이더로 전환하세요 "
                f"(.env 에 TERMSHEET_PROVIDER=gemini 등).")
        if "rate limit" in err or "429" in err or "quota" in err:
            raise ValueError(
                f"{PROVIDERS[name]['label']} 호출 한도에 걸렸습니다. "
                f"잠시 후 다시 시도하거나 다른 프로바이더로 전환하세요.")
        raise


# ---------------------------------------------------------------- 5. verification
_ENUM_FIELDS = {
    "leg1_day_count": DAY_COUNTS, "leg2_day_count": DAY_COUNTS,
    "leg1_payment_freq": FREQUENCIES, "leg2_payment_freq": FREQUENCIES,
    "leg1_business_day_conv": CONVENTIONS, "leg2_business_day_conv": CONVENTIONS,
    "leg1_stub_rule": STUB_RULES, "leg2_stub_rule": STUB_RULES,
    "leg1_adjust_rule": ["Adjust", "Unadjust"], "leg2_adjust_rule": ["Adjust", "Unadjust"],
    "leg1_calendar": CALENDARS, "leg2_calendar": CALENDARS,
}

_ALIASES = {
    "ACT/365F": "Act/365", "ACT/365 FIXED": "Act/365", "A/365": "Act/365", "ACT365": "Act/365",
    "ACT/360": "Act/360", "A/360": "Act/360", "ACT360": "Act/360",
    "30/360": "30/360", "30E/360": "30/360", "BOND BASIS": "30/360",
    "ACT/ACT": "Act/Act", "ACTUAL/ACTUAL": "Act/Act",
    "MF": "Modified Following", "MODFOLLOWING": "Modified Following",
    "MODIFIED FOLLOWING": "Modified Following", "FOLLOWING": "Following",
    "PRECEDING": "Preceding", "ADJUSTED": "Adjust", "UNADJUSTED": "Unadjust",
    "QUARTERLY": "3M", "SEMI-ANNUAL": "6M", "SEMIANNUAL": "6M",
    "ANNUAL": "12M", "MONTHLY": "1M", "1Y": "12M",
}


def normalize_enums(trade: ExtractedTrade) -> List[str]:
    """Coerce common spellings onto the pricer's vocabulary. Returns unmappable fields."""
    unmapped = []
    for field, allowed in _ENUM_FIELDS.items():
        val = getattr(trade, field, None)
        if val is None:
            continue
        if val in allowed:
            continue
        canon = _ALIASES.get(str(val).strip().upper())
        if canon and canon in allowed:
            setattr(trade, field, canon)
        else:
            setattr(trade, field, None)
            unmapped.append(field)
    return unmapped


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def verify_quotes(trade: ExtractedTrade, doc_text: str) -> List[str]:
    """Any 'extracted' field whose quote is not in the document is a fabricated citation."""
    haystack = _squash(doc_text)
    unverified = []
    for p in trade.provenance:
        if p.source != "extracted":
            continue
        if not p.quote or _squash(p.quote) not in haystack:
            unverified.append(p.field)
    return unverified


def check_schedule(trade: ExtractedTrade) -> List[str]:
    warnings = []
    sched = trade.leg1_custom_schedule
    if not sched:
        return warnings

    for i in range(1, len(sched)):
        if sched[i].start_date != sched[i - 1].end_date:
            warnings.append(
                f"스케줄 {i}기와 {i+1}기가 이어지지 않습니다 "
                f"({sched[i-1].end_date} → {sched[i].start_date})")
            break

    headline = trade.notional or trade.usd_notional
    if headline and sched and abs(sched[0].notional - headline) > 1.0:
        warnings.append(
            f"첫 기간 원금({sched[0].notional:,.0f})이 "
            f"헤드라인 원금({headline:,.0f})과 다릅니다")

    if trade.maturity_date and sched and sched[-1].end_date != trade.maturity_date:
        warnings.append(
            f"스케줄 종료일({sched[-1].end_date})이 만기일({trade.maturity_date})과 다릅니다")

    return warnings


def check_dates(trade: ExtractedTrade) -> List[str]:
    warnings = []
    for label, val in (("effective_date", trade.effective_date),
                       ("maturity_date", trade.maturity_date)):
        if val:
            try:
                datetime.date.fromisoformat(val)
            except ValueError:
                warnings.append(f"{label} 형식이 올바르지 않습니다: {val}")
    if trade.effective_date and trade.maturity_date:
        try:
            if datetime.date.fromisoformat(trade.maturity_date) <= datetime.date.fromisoformat(trade.effective_date):
                warnings.append("만기일이 개시일보다 앞서거나 같습니다")
        except ValueError:
            pass
    return warnings


# ---------------------------------------------------------------- 6. ticket draft
_TICKET_DEFAULTS = {
    "USD":      dict(dc="Act/360", freq="12M", cal="NYB", fix_day=-2, notional=100_000_000.0, tenor="5Y"),
    "KRW":      dict(dc="Act/365", freq="3M", cal="SEB", fix_day=-1, notional=100_000_000_000.0, tenor="3Y"),
    "KRW_KOFR": dict(dc="Act/365", freq="3M", cal="SEB", fix_day=0, notional=10_000_000_000.0, tenor="1Y"),
    "KRW_CRS":  dict(dc="30/360", freq="6M", cal="SEB_NYB", fix_day=-1, notional=100_000_000.0, tenor="5Y"),
}


def _fmt(n: Optional[float]) -> str:
    return f"{n:,.0f}" if n is not None else ""


def to_ticket_draft(trade: ExtractedTrade) -> Dict[str, Any]:
    """Map extracted terms onto the dashboard's ticket shape, marking which fields are defaults."""
    curr = trade.currency or "USD"
    d = _TICKET_DEFAULTS.get(curr, _TICKET_DEFAULTS["USD"])
    inferred: List[str] = []

    def pick(value, fallback, name):
        if value is None:
            inferred.append(name)
            return fallback
        return value

    notional = trade.usd_notional if curr == "KRW_CRS" and trade.usd_notional else trade.notional
    draft = {
        "product": curr,
        "position": pick(trade.position, "Pay Fixed", "position"),
        "notionalDisplay": _fmt(pick(notional, d["notional"], "notional")),
        "customTenorInput": pick(trade.tenor, d["tenor"], "tenor"),
        "selectedTenor": trade.tenor or d["tenor"],
        "effectiveDate": trade.effective_date or "",
        "maturityDate": trade.maturity_date or "",
        "coupon": f"{trade.fixed_coupon_pct:.4f}" if trade.fixed_coupon_pct is not None else "",
        "spreadBp": f"{trade.spread_bp:.1f}" if trade.spread_bp is not None else "0.0",
        "crsSwapType": trade.crs_swap_type or "Vanilla",
        "usdFixedCoupon": (f"{trade.usd_fixed_coupon_pct:.4f}"
                           if trade.usd_fixed_coupon_pct is not None else "3.5000"),
        "leg1DayCount": pick(trade.leg1_day_count, d["dc"], "leg1_day_count"),
        "leg1PaymentFreq": pick(trade.leg1_payment_freq, d["freq"], "leg1_payment_freq"),
        "leg1Convention": pick(trade.leg1_business_day_conv, "Modified Following", "leg1_business_day_conv"),
        "leg1Stub": pick(trade.leg1_stub_rule, "Short in arrears", "leg1_stub_rule"),
        "leg1Adjust": pick(trade.leg1_adjust_rule, "Adjust", "leg1_adjust_rule"),
        "leg1PayCal": pick(trade.leg1_calendar, d["cal"], "leg1_calendar"),
        "leg2DayCount": pick(trade.leg2_day_count, d["dc"], "leg2_day_count"),
        "leg2PaymentFreq": pick(trade.leg2_payment_freq, d["freq"], "leg2_payment_freq"),
        "leg2Convention": pick(trade.leg2_business_day_conv, "Modified Following", "leg2_business_day_conv"),
        "leg2Stub": pick(trade.leg2_stub_rule, "Short in arrears", "leg2_stub_rule"),
        "leg2Adjust": pick(trade.leg2_adjust_rule, "Adjust", "leg2_adjust_rule"),
        "leg2Cal": pick(trade.leg2_calendar, d["cal"], "leg2_calendar"),
        "fixDay": trade.leg2_fix_day if trade.leg2_fix_day is not None else d["fix_day"],
    }
    if curr == "KRW_CRS":
        if trade.spot_fx:
            draft["capitalFxRate"] = _fmt(trade.spot_fx)
        if trade.krw_notional:
            draft["krwNotionalDisplay"] = _fmt(trade.krw_notional)

    if trade.leg1_custom_schedule:
        draft["rawPasteText"] = "\n".join(
            f"{p.start_date}\t{p.end_date}\t{p.notional:.0f}"
            + (f"\t{p.fixed_rate_pct}" if p.fixed_rate_pct is not None else "")
            for p in trade.leg1_custom_schedule
        )

    return {"draft": draft, "inferred_fields": inferred}


# ---------------------------------------------------------------- 7. orchestration
def process_termsheet(raw: bytes, extractor=None, second_extractor=None,
                      reviewers=None) -> Dict[str, Any]:
    """
    Full pipeline. Extractors and reviewers are injectable so every path - including the
    two-model disagreement round - can be tested without touching an API.
    """
    doc_sha = hashlib.sha256(raw).hexdigest()
    try:
        doc_text = extract_text(raw)
    except Exception as e:
        raise ValueError(f"PDF를 읽을 수 없습니다: {e}")
    # Page markers are always present, so measure the real content behind them - an
    # image-only scan otherwise looks non-empty and would be sent out with nothing in it.
    body = re.sub(r"--- page \d+ ---", "", doc_text).strip()
    if len(body) < 40:
        raise ValueError("PDF에서 텍스트를 추출하지 못했습니다 (스캔 이미지는 아직 지원하지 않습니다)")

    redacted_text, redaction_counts = redact(doc_text)
    leaks = redaction_leaks(redacted_text)

    trade = (extractor or call_extractor)(redacted_text)

    # Optional second opinion. Two models fail differently, so a field they disagree on
    # is a field the document is genuinely ambiguous about - it gets escalated to the
    # trader rather than resolved by preferring one vendor.
    comparison = None
    if second_extractor is None and extractor is None:
        try:
            from server.crossvalidate import secondary_extractor
            second_extractor = secondary_extractor()
        except Exception as e:
            print(f"[Termsheet] second provider unavailable: {e}")
    adjudication = None
    if second_extractor is not None:
        try:
            from server.crossvalidate import (
                compare_extractions, adjudicate, format_disputes,
                claude_reviewer, secondary_reviewer,
            )
            comparison = compare_extractions(trade, second_extractor(redacted_text))

            # Round two: where they differ, both re-read the document for those fields
            # and must cite the text that settles it.
            if comparison.get("compared") and comparison.get("disagreements"):
                rp = reviewers[0] if reviewers else claude_reviewer
                rs = reviewers[1] if reviewers and len(reviewers) > 1 else secondary_reviewer()
                if rs is not None:
                    disputes = format_disputes(comparison)
                    adjudication = adjudicate(
                        comparison,
                        rp(redacted_text, disputes),
                        rs(redacted_text, disputes),
                        redacted_text,
                    )
                    for field, value in adjudication["resolved"].items():
                        if hasattr(trade, field):
                            setattr(trade, field, value)
        except Exception as e:
            print(f"[Termsheet] cross-validation failed: {e}")
            comparison = {"compared": False, "error": str(e)}

    if not trade.supported:
        return {
            "supported": False,
            "unsupported_reason": trade.unsupported_reason or "이 프라이서로 평가할 수 없는 상품입니다",
            "doc_sha256": doc_sha,
            "redaction": {"counts": redaction_counts, "leaks": leaks},
        }

    unmapped = normalize_enums(trade)
    # Quotes are checked against the redacted text - that is what the model actually saw.
    unverified = verify_quotes(trade, redacted_text)

    warnings: List[str] = []
    warnings += check_dates(trade)
    warnings += check_schedule(trade)
    for f in unmapped:
        warnings.append(f"'{f}' 값을 프라이서 컨벤션으로 매핑하지 못해 기본값으로 되돌렸습니다")
    for f in unverified:
        warnings.append(f"'{f}'의 근거 인용문을 문서에서 찾지 못했습니다 - 직접 확인하세요")
    if leaks:
        warnings.append(f"마스킹 후에도 민감정보 패턴이 남아 있습니다: {', '.join(leaks)}")

    mapped = to_ticket_draft(trade)
    blocked = sorted(set(unverified) | set(unmapped))

    if comparison and comparison.get("compared"):
        from server.crossvalidate import disagreement_fields
        diffs = disagreement_fields(comparison)
        if adjudication:
            # Fields the second round settled are no longer in dispute; only what the
            # document could not decide still needs the trader.
            diffs = list(adjudication["unresolved"])
            for rec in adjudication["trail"]:
                if rec["resolution"] == "converged":
                    who = ", ".join(rec["corrected"]) if rec.get("corrected") else "없음"
                    warnings.append(
                        f"재검토 합의 [{rec['field']}] → {rec['final']!r} (정정한 모델: {who})")
                elif rec["resolution"] == "evidence":
                    warnings.append(
                        f"근거 판정 [{rec['field']}] → {rec['final']!r} "
                        f"(오류: {', '.join(rec['wrong'])})")
        if diffs:
            # Map extractor field names onto the ticket keys the review panel blocks on.
            key_by_field = {v: k for k, v in {
                "notionalDisplay": "notional", "customTenorInput": "tenor",
                "effectiveDate": "effective_date", "maturityDate": "maturity_date",
                "coupon": "fixed_coupon_pct", "spreadBp": "spread_bp",
                "position": "position", "leg1DayCount": "leg1_day_count",
                "leg1PaymentFreq": "leg1_payment_freq",
                "leg1Convention": "leg1_business_day_conv",
                "leg1Stub": "leg1_stub_rule", "leg1Adjust": "leg1_adjust_rule",
                "leg1PayCal": "leg1_calendar", "leg2DayCount": "leg2_day_count",
                "leg2PaymentFreq": "leg2_payment_freq",
                "leg2Convention": "leg2_business_day_conv",
                "leg2Stub": "leg2_stub_rule", "leg2Adjust": "leg2_adjust_rule",
                "leg2Cal": "leg2_calendar",
            }.items()}
            blocked = sorted(set(blocked) | set(diffs) |
                             {key_by_field[f] for f in diffs if f in key_by_field})
            p, s = comparison["primary"], comparison["secondary"]
            for d in comparison["disagreements"]:
                if d["field"] not in diffs:
                    continue
                warnings.append(
                    f"모델 불일치 미해결 [{d['field']}]: {p}={d.get(p)!r} vs {s}={d.get(s)!r}"
                    + (f" - {d['note']}" if d.get("note") else ""))

    if getattr(trade, "demo_fallback", False):
        # Canned demo data must never reach a price. Block every field so the review
        # panel cannot be confirmed, and say plainly where the numbers came from.
        blocked = sorted(set(blocked) | set(mapped["draft"].keys()))
        warnings.insert(0, "데모 응답입니다 - API 크레딧이 없어 미리 준비된 샘플 값을 표시했습니다. "
                           "실제 문서에서 추출한 값이 아니므로 프라이싱에 사용할 수 없습니다.")

    return {
        "supported": True,
        "demo_fallback": bool(getattr(trade, "demo_fallback", False)),
        "doc_sha256": doc_sha,
        "ticket_draft": mapped["draft"],
        "inferred_fields": mapped["inferred_fields"],
        "unverified_fields": blocked,
        "provenance": [p.model_dump() for p in trade.provenance],
        "open_questions": trade.open_questions,
        "warnings": warnings,
        "cross_validation": comparison,
        "adjudication": adjudication,
        "redaction": {"counts": redaction_counts, "leaks": leaks},
    }
