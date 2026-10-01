/* ==========================================================================
   무엇이 어느 엔드포인트로 가고, 응답에서 무엇을 읽는가.

   통화마다 응답 모양이 같지 않습니다. USD·KRW·KOFR 는 pricing_results 아래
   par_swap_rate_pct / deal_npv / dv01 로 똑같지만, CRS 는 par_crs_rate_pct 에
   원화·달러 NPV 와 DV01 을 따로 내놓습니다. 그 차이를 화면 코드에 흩어놓으면
   한 통화만 조용히 틀린 숫자를 보여주게 됩니다 — 화면은 멀쩡해 보이고요.

   그래서 차이는 전부 이 파일 안에만 둡니다. 테스트가 네 통화 모두를 여기와
   API 직접 호출로 대조합니다.
   ========================================================================== */
(function (root) {
    "use strict";

    // FX FWD 는 없습니다. far leg 를 탭 구분으로 붙여넣는 방식이라 휴대폰에서
    // 입력할 수가 없고, 요청 모델부터 다릅니다(FwdPricingRequest). PC 전용입니다.
    const PRODUCTS = {
        USD: {
            label: "USD SOFR", short: "USD",
            price: "/api/price", reload: "/api/reload-and-price",
            relayKey: "USD", ccy: "USD",
        },
        KRW: {
            label: "KRW CD IRS", short: "KRW CD",
            price: "/api/krw/price", reload: "/api/krw/reload-and-price",
            relayKey: "KRW", ccy: "KRW",
        },
        KRW_KOFR: {
            label: "KRW KOFR OIS", short: "KOFR",
            price: "/api/kofr/price", reload: "/api/kofr/reload-and-price",
            relayKey: "KOFR", ccy: "KRW",
        },
        KRW_CRS: {
            label: "KRW FX SOFR (CRS)", short: "CRS",
            price: "/api/crs/price", reload: "/api/crs/reload-and-price",
            relayKey: "CRS", ccy: "KRW",
        },
    };

    /**
     * 티켓 키 → 추출기 필드명.
     *
     * 서버의 inferred_fields / unverified_fields / provenance 는 추출기 쪽
     * 이름(tenor, notional)을 쓰고, 검토 창의 행은 티켓 키(customTenorInput,
     * notionalDisplay)로 되어 있습니다. 휴대폰 화면에서 이 변환을 camelCase →
     * snake_case 규칙으로 때웠는데, customTenorInput → custom_tenor_input 이
     * 되어 tenor 와 맞지 않았습니다. 그래서 서버가 채운 기본값이 문서에서 읽은
     * 사실처럼 보였습니다 - 9개월짜리 거래에 3Y 이 아무 표시 없이 떴습니다.
     *
     * 규칙으로 유추하지 않고 적어 둡니다. 데스크톱의 TS_FIELD_KEY 와 같은 표입니다.
     */
    const TS_FIELD_KEY = {
        notionalDisplay: "notional", customTenorInput: "tenor",
        effectiveDate: "effective_date", maturityDate: "maturity_date",
        coupon: "fixed_coupon_pct", spreadBp: "spread_bp", position: "position",
        firstFixing: "first_fixing_pct",
        leg1DayCount: "leg1_day_count", leg1PaymentFreq: "leg1_payment_freq",
        leg1Convention: "leg1_business_day_conv", leg1Stub: "leg1_stub_rule",
        leg1Adjust: "leg1_adjust_rule", leg1PayCal: "leg1_calendar",
        leg2DayCount: "leg2_day_count", leg2PaymentFreq: "leg2_payment_freq",
        leg2Convention: "leg2_business_day_conv", leg2Stub: "leg2_stub_rule",
        leg2Adjust: "leg2_adjust_rule", leg2Cal: "leg2_calendar",
    };

    const ORDER = ["USD", "KRW", "KRW_KOFR", "KRW_CRS"];

    /**
     * 응답에서 머리 숫자 세 개를 꺼낸다.
     *
     * CRS 는 다리마다 통화가 달라 DV01 이 둘입니다. 하나로 뭉뚱그리면 어느 쪽
     * 민감도인지 알 수 없으므로, 원화를 주 지표로 놓고 달러는 따로 보여줍니다.
     */
    function readResults(currency, data) {
        const pr = (data && data.pricing_results) || {};
        if (currency === "KRW_CRS") {
            // Fixed-Fixed 에서는 par 가 "USD 쿠폰을 주었을 때의 KRW 고정금리"
            // 입니다. PC 화면의 복사문과 같은 필드를 씁니다.
            const fixedFixed = pr.par_usd_rate_pct !== null
                            && pr.par_usd_rate_pct !== undefined;
            const extra = [
                { label: "USD DV01", value: pr.usd_dv01, ccy: "USD" },
                { label: "USD NPV", value: pr.deal_npv_usd, ccy: "USD" },
            ];
            if (fixedFixed) {
                extra.unshift({ label: "USD 고정금리", value: pr.par_usd_rate_pct,
                                pct: true });
            }
            return {
                par: fixedFixed ? pr.par_krw_rate_pct : pr.par_crs_rate_pct,
                parNote: fixedFixed ? "USD 쿠폰 기준 KRW 고정금리" : "",
                _unused: pr.par_crs_rate_pct,
                spreadBp: pr.spread_vs_coupon_bp,
                npv: pr.deal_npv_krw, npvCcy: "KRW",
                dv01: pr.krw_dv01, dv01Ccy: "KRW",
                extra: extra,
            };
        }
        const ccy = PRODUCTS[currency] ? PRODUCTS[currency].ccy : "USD";
        return {
            par: pr.par_swap_rate_pct,
            spreadBp: pr.spread_vs_coupon_bp,
            npv: pr.deal_npv, npvCcy: ccy,
            dv01: pr.dv01, dv01Ccy: ccy,
            extra: [],
        };
    }

    /**
     * 화면에 보이는 입력 몇 개로 요청을 만든다.
     *
     * 나머지 컨벤션 12개는 서버가 시장 관행으로 채웁니다 — 그래서 휴대폰 화면이
     * 작아도 됩니다. 다만 Term Sheet 을 읽어들였다면 그 값들이 overrides 로
     * 들어와 여기에 얹힙니다. 화면만 간단한 것이지, 요청까지 간단해지면 문서에
     * 적힌 Act/365 나 상각 스케줄이 조용히 버려집니다.
     */
    function buildRequest(state) {
        const req = {
            currency: state.currency,
            notional: Number(state.notional) || 0,
            position: state.position,
            tenor: state.tenor,
            spread_bp: numOrDefault(state.spreadBp, 0),
        };
        const coupon = numOrNull(state.coupon);
        if (coupon !== null) req.fixed_coupon_pct = coupon;
        if (state.effectiveDate) req.effective_date = state.effectiveDate;
        if (state.maturityDate) req.maturity_date = state.maturityDate;
        if (state.curveType) req.curve_type = state.curveType;
        if (state.currency === "KRW_CRS") {
            req.crs_swap_type = state.crsSwapType || "Vanilla";
            // Fixed-Fixed 는 USD 다리도 고정이라, 그 쿠폰이 없으면 서버가 기본값
            // 3.50 으로 계산하고 화면은 아무 말도 하지 않습니다.
            if (req.crs_swap_type === "Fixed-Fixed") {
                const u = numOrNull(state.usdFixedCoupon);
                if (u !== null) req.usd_fixed_coupon_pct = u;
            }
        }
        return Object.assign(req, state.overrides || {});
    }

    /**
     * Term Sheet 초안을 요청에 얹을 형태로 바꾼다.
     *
     * 스케줄은 파싱하지 않고 원문 그대로 넘깁니다 — 서버가 leg1_raw_paste_text 를
     * 받아 직접 해석하므로, 휴대폰이 탭 구분 표를 다룰 이유가 없습니다.
     */
    function overridesFromTicket(t) {
        if (!t) return {};
        const o = {};
        const map = {
            leg1DayCount: "leg1_day_count", leg1PaymentFreq: "leg1_payment_freq",
            leg1Convention: "leg1_business_day_conv", leg1Stub: "leg1_stub_rule",
            leg1Adjust: "leg1_adjust_rule", leg1PayCal: "leg1_calendar",
            leg2DayCount: "leg2_day_count", leg2PaymentFreq: "leg2_payment_freq",
            leg2Convention: "leg2_business_day_conv", leg2Stub: "leg2_stub_rule",
            leg2Adjust: "leg2_adjust_rule", leg2Cal: "leg2_calendar",
        };
        Object.keys(map).forEach((k) => {
            if (t[k] !== undefined && t[k] !== null && t[k] !== "") o[map[k]] = t[k];
        });
        if (t.fixDay !== undefined && t.fixDay !== null && t.fixDay !== "") {
            o.leg2_fix_day = Number(t.fixDay);
        }
        if (t.rawPasteText) {
            o.raw_paste_text = t.rawPasteText;
            o.leg1_raw_paste_text = t.rawPasteText;
        }
        // 이미 시작된 첫 변동기간의 고시금리. 없으면 서버가 커브에서
        // 추정하고 그렇다고 표시합니다.
        if (t.firstFixing) o.first_fixing_pct = numOrNull(t.firstFixing);
        if (t.usdFixedCoupon) o.usd_fixed_coupon_pct = numOrNull(t.usdFixedCoupon);
        if (t.crsSwapType) o.crs_swap_type = t.crsSwapType;
        return o;
    }

    /**
     * LIVE · RELAY · BASE 는 서로 다른 것이다.
     *
     * LIVE 는 이 서버가 LSEG 에 직접 붙은 것, RELAY 는 데스크 PC 가 보내준 호가,
     * BASE 는 아무 피드도 없는 기준호가. RELAY 를 LIVE 로 보이게 하면 데스크가
     * 꺼진 뒤에도 실시간처럼 읽힙니다. PC 화면과 같은 우선순위를 씁니다.
     */
    function feedState(isLive, relay) {
        if (isLive) {
            return { kind: "live", label: "● LIVE", stale: false,
                     title: "LSEG Workspace 직접 연결" };
        }
        if (relay && relay.active) {
            const age = Math.round(relay.age_seconds || 0);
            const when = age < 120 ? age + "s" : Math.round(age / 60) + "m";
            return {
                kind: "relay", label: "● RELAY (" + when + ")",
                stale: Boolean(relay.stale),
                title: relay.stale
                    ? "데스크 중계 호가가 " + when + " 지났습니다 — 데스크 PC 연결을 확인하세요"
                    : "데스크 PC(" + (relay.origin || "-") + ") 중계",
            };
        }
        return { kind: "base", label: "● BASE", stale: true,
                 title: "실시간 피드 없음 — 기준호가로 계산 중입니다" };
    }

    /** 중계 상태는 통화가 아니라 피드 단위로 기록된다. */
    function relayFor(allStatus, currency) {
        const p = PRODUCTS[currency];
        return (allStatus && p) ? allStatus[p.relayKey] : null;
    }

    // ---- 숫자 ----------------------------------------------------------------

    function numOrNull(v) {
        if (v === null || v === undefined) return null;
        const s = String(v).replace(/,/g, "").trim();
        if (s === "") return null;
        const n = Number(s);
        return Number.isFinite(n) ? n : null;
    }

    function numOrDefault(v, d) {
        const n = numOrNull(v);
        return n === null ? d : n;
    }

    /** 금액. 화면이 좁으므로 소수점은 버리고 천단위만 끊는다. */
    function money(v, ccy) {
        if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
        const sign = Number(v) < 0 ? "-" : "";
        const body = Math.abs(Number(v)).toLocaleString("en-US", { maximumFractionDigits: 0 });
        return sign + (ccy === "USD" ? "$ " : "₩ ") + body;
    }

    /** 금리. 4자리는 데스크가 호가를 부르는 자리수입니다. */
    function pct(v) {
        if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
        return Number(v).toFixed(4);
    }

    function commas(v) {
        const n = numOrNull(v);
        return n === null ? "" : n.toLocaleString("en-US", { maximumFractionDigits: 0 });
    }

    root.PricingCore = {
        PRODUCTS, ORDER, readResults, buildRequest, overridesFromTicket,
        feedState, relayFor, money, pct, commas, numOrNull, numOrDefault,
        TS_FIELD_KEY,
    };
})(window);
