# Multi-Currency Swap Pricer

Live pricing desk for USD SOFR OIS, KRW CD 91D IRS, KRW KOFR OIS, KRW FX SOFR (CRS) and
FX forwards, fed from LSEG Workspace and served as a single-page dashboard.

## What it does

- Bootstraps a discount curve per product from live quotes, then prices dual-leg swaps —
  par rate, NPV, DV01 and key-rate deltas across nine buckets.
- Handles trades whose terms move over their life: amortising or accreting notionals,
  step-up coupons, irregular period boundaries, or all three at once.
- USD SOFR and the CRS USD leg also support an **Advanced** hybrid curve — flat-forward
  below 2Y, log-cubic spline above, blended C¹ across a 120-day window at the junction —
  and a **Hedge** curve that layers a localised zero-coupon deformation for bucketed risk.
- Reads a counterparty term sheet (PDF), extracts the trade terms, and hands the trader a
  draft ticket to review before pricing.

## Running it

```bash
pip install -r requirements.txt
python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/>.

Keyboard: `F5` reload market · `Enter` price · `F9` reload and price.

## Configuration

Two credentials, both kept out of version control.

| File | Purpose | Template |
|---|---|---|
| `.env` | `ANTHROPIC_API_KEY` for term sheet extraction | `.env.example` |
| `lseg_config.json` | LSEG Workspace app key for the market feed | `lseg_config.example.json` |

Optional, for two-model cross-validation of term sheet extraction:

```
TERMSHEET_SECOND_PROVIDER=anthropic     # or gemini / openai
TERMSHEET_SECOND_MODEL=claude-opus-5
```

## Term sheet extraction

Upload a PDF from the trade panel. The document is parsed in memory, counterparty
identity is stripped before anything leaves the process, and the file is never written to
disk or retained.

Every extracted field arrives with a verbatim quote from the document, and the server
checks that quote is really there — a citation it cannot find is rejected rather than
trusted. Fields the document does not state are filled from product defaults and marked
as such, so a trader can see what was read and what was assumed. Nothing prices until
the trader confirms.

With a second model configured, both read the document independently. Where they agree
the value stands; where they differ, both re-read those fields and must cite the text
that settles it. The document decides, not the louder model — and if neither can cite
anything, the field goes to the trader rather than being guessed. Which model was wrong
is recorded.

## Layout

```
server/          FastAPI app, market feeds, calendars, term sheet pipeline
sofr_pricer/     USD SOFR OIS  — curve, dates, swap engine
krw_pricer/      KRW CD 91D IRS
kofr_pricer/     KRW KOFR OIS
crs_pricer/      KRW FX SOFR cross-currency
fwd_pricer/      FX forwards / swap points
common_pricer/   Shared schedule paste parser
AdvancedCurve/   Curve research scripts (not imported by the server)
static/          Dashboard
tests/           Test suites, L1–L14
```

## Tests

```bash
cd tests
python run_all.py
```

No pytest, no live server, no market data connection required — the feeds expose
`update_quote()` so the suites pin a deterministic market, and the API is driven through
FastAPI's `TestClient` in-process.

| Layer | Covers |
|---|---|
| L1 | Curve bootstrap invariants — monotone discount factors, pillar repricing, sparse-feed tolerance |
| L2 | Pricing invariants — par → NPV 0, antisymmetry, linearity, DV01 against finite difference, Σ key-rate deltas vs DV01 |
| L3 | Schedule generation — stub rules, frequencies, day counts, conventions, holiday rolls, leap years |
| L4 | CRS — vanilla and fixed-fixed, principal exchange, FX sensitivity |
| L5 | Varying-term schedules through the paste parser |
| L6 | Live data reaching pricing immediately |
| L8 | API contract and error handling |
| L9 | Advanced hybrid curve and hedge-curve Greeks |
| L10 | Term sheet ingestion — redaction, citation verification, ticket mapping |
| L11 | End-to-end scenarios on synthetic sample documents |
| L12 | Notional / date / rate variation plus holiday handling |
| L13 | Two-model cross-validation |
| L14 | Disagreement adjudication and error attribution |

A browser test (`tests/test_ui_staleness.py`) checks that the stale-market banner clears
when `F9` reloads; it needs Playwright with Chromium.
