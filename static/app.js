/**
 * MULTI-CURRENCY IRS LIVE TERMINAL FRONTEND LOGIC (v3.0 PRO)
 * - Multi-Currency Switcher: USD SOFR OIS ↔ KRW CD 91D IRS
 * - 1,000s Comma Masking for Notional (USD $ / KRW ₩)
 * - Odd Tenor Custom Input & Direct Date Calculations
 * - Dual-Leg Cash Flow Schedule (Fixed Leg vs Floating Leg)
 * - Default Auto-Generated Schedule & Custom Pasted Schedule (Amortizing, Stepped Coupons)
 * - Excel / Murex Tab-Separated Paste Modal & Direct Ctrl+V Support
 * - Inline Spreadsheet-like Cell Editing & CSV Export
 * - Manual Quote Override Modal & Baseline Reset
 * - Hotkeys: F5 (Reload), Enter (Price), F9 (Reload & Price)
 */

window.fwdMarketSnapshot = null;
var fwdMarketSnapshot = null;

document.addEventListener("DOMContentLoaded", () => {
    window.fwdMarketSnapshot = null;
    var fwdMarketSnapshot = null;

    // Application State
    const state = {
        currency: "USD", // "USD" or "KRW"
        curveType: "Standard", // "Standard" or "Advanced"
        crsSwapType: "Vanilla", // "Vanilla" or "Fixed-Fixed"
        marketSnapshot: null,
        fwdMarketSnapshot: null,
        lastSnapshotTime: null,
        snapshotEpochMs: null, // wall-clock of the last snapshot, drives the staleness badge
        pricingResult: null,
        selectedTenor: "5Y",
        curvePillars: [],
        activeScheduleTab: "dual",
        customSchedule: null // Array of custom period objects when pasted/edited
    };

    // DOM Elements
    const elements = {
        // Currency Toggle
        btnCurrUsd: document.getElementById("btn-curr-usd"),
        btnCurrKrw: document.getElementById("btn-curr-krw"),
        btnCurrKofr: document.getElementById("btn-curr-kofr"),
        btnCurrCrs: document.getElementById("btn-curr-crs"),
        btnCurrFwd: document.getElementById("btn-curr-fwd"),

        // Containers for Swap vs FWD
        swapTradeContainer: document.getElementById("swap-trade-container"),
        fwdTradeContainer: document.getElementById("fwd-trade-container"),
        swapResultsContainer: document.getElementById("swap-results-container"),
        fwdResultsContainer: document.getElementById("fwd-results-container"),
        tabBtnFwd: document.getElementById("tab-btn-fwd"),
        tabPaneFwd: document.getElementById("tab-pane-fwd"),
        rcPasteCard: document.getElementById("rc-paste-card"),

        // Multi-Quote Ticket Workspace Elements
        quoteTicketsWorkspaceBar: document.getElementById("quote-tickets-workspace-bar"),
        ticketsScrollContainer: document.getElementById("tickets-scroll-container"),
        btnNewTicket: document.getElementById("btn-new-ticket"),
        ticketClientInput: document.getElementById("ticket-client-input"),
        ticketAliasInput: document.getElementById("ticket-alias-input"),
        btnDuplicateTicket: document.getElementById("btn-duplicate-ticket"),
        btnCopyQuoteTop: document.getElementById("btn-copy-quote-top"),
        btnSwapCopyMessenger: document.getElementById("btn-swap-copy-messenger"),

        // FWD Mode specific elements
        fwdSpotFx: document.getElementById("fwd-spot-fx"),
        fwdDefaultMargin: document.getElementById("fwd-default-margin"),
        fwdSpotDate: document.getElementById("fwd-spot-date"),
        fwdPasteTextarea: document.getElementById("fwd-paste-textarea"),
        btnFwdApplyPaste: document.getElementById("btn-fwd-apply-paste"),
        btnFwdSample: document.getElementById("btn-fwd-sample"),
        btnFwdClear: document.getElementById("btn-fwd-clear"),
        btnFwdReload: document.getElementById("btn-fwd-reload"),
        btnFwdCalc: document.getElementById("btn-fwd-calc"),
        btnFwdOneshot: document.getElementById("btn-fwd-oneshot"),
        btnFwdCopyMessenger: document.getElementById("btn-fwd-copy-messenger"),
        btnFwdDirBuy: document.getElementById("btn-fwd-dir-buy"),
        btnFwdDirSell: document.getElementById("btn-fwd-dir-sell"),

        fwdResWavgSp: document.getElementById("fwd-res-wavg-sp"),
        fwdResWavgSub: document.getElementById("fwd-res-wavg-sub"),
        fwdResTotalNotional: document.getElementById("fwd-res-total-notional"),
        fwdResDeltaSub: document.getElementById("fwd-res-delta-sub"),
        fwdResTotalMargin: document.getElementById("fwd-res-total-margin"),
        fwdResMarginSub: document.getElementById("fwd-res-margin-sub"),
        fwdDeltaBars: document.getElementById("fwd-delta-bars"),
        fwdScheduleTableBody: document.getElementById("fwd-table-body"),

        // Status Bar
        snapshotTimestamp: document.getElementById("snapshot-timestamp"),
        stalenessBadge: document.getElementById("staleness-badge"),
        feedStatusText: document.getElementById("feed-status-text"),
        liveConnectedBadge: document.getElementById("live-connected-badge"),
        liveIndicator: document.getElementById("live-indicator"),
        systemClock: document.getElementById("system-clock"),

        // Market Panel & Stats
        marketPanelTitle: document.getElementById("market-panel-title"),
        lblFixRate: document.getElementById("lbl-fix-rate"),
        oisFixRate: document.getElementById("ois-fix-rate"),
        lbl1yRate: document.getElementById("lbl-1y-rate"),
        ois1yRate: document.getElementById("ois-1y-rate"),
        lbl3yRate: document.getElementById("lbl-3y-rate"),
        ois3yRate: document.getElementById("ois-3y-rate"),
        lbl5yRate: document.getElementById("lbl-5y-rate"),
        ois5yRate: document.getElementById("ois-5y-rate"),
        quoteTableBody: document.getElementById("quote-table-body"),
        curveCanvas: document.getElementById("curveCanvas"),

        // Trade Builder
        tradePanelTitle: document.getElementById("trade-panel-title"),
        tradeBadgeTag: document.getElementById("trade-badge-tag"),
        lblNotional: document.getElementById("lbl-notional"),
        notionalAffix: document.getElementById("notional-affix"),
        notionalDisplay: document.getElementById("notional-display"),
        positionSelect: document.getElementById("position"),
        couponInput: document.getElementById("fixed-coupon"),
        spreadInput: document.getElementById("spread-bp") || document.getElementById("floating-spread"),
        tenorChipsContainer: document.getElementById("tenor-chips"),
        oddTenorContainer: document.getElementById("odd-tenor-container"),
        customTenorInput: document.getElementById("custom-tenor-input"),
        btnApplyOddTenor: document.getElementById("btn-apply-odd-tenor"),
        lblEffectiveDate: document.getElementById("lbl-effective-date"),
        effectiveDateInput: document.getElementById("effective-date"),
        maturityDateInput: document.getElementById("maturity-date"),

        // Direction Controls & Leg Tags
        btnPhasePay: document.getElementById("btn-phase-pay"),
        btnPhaseRec: document.getElementById("btn-phase-rec"),
        tagFixedLeg: document.getElementById("tag-fixed-leg"),
        tagFloatLeg: document.getElementById("tag-float-leg"),
        tagFixedSub: document.getElementById("tag-fixed-sub"),
        tagFloatSub: document.getElementById("tag-float-sub"),
        phaseTitlePay: document.getElementById("phase-title-pay"),
        phaseDescPay: document.getElementById("phase-desc-pay"),
        phaseTitleRec: document.getElementById("phase-title-rec"),
        phaseDescRec: document.getElementById("phase-desc-rec"),

        // Dual-Leg Structure Control
        btnStructVanilla: document.getElementById("btn-struct-vanilla"),
        btnStructFixedFixed: document.getElementById("btn-struct-fixed-fixed"),
        btnLeg2TypeFloat: document.getElementById("btn-leg2-type-float"),
        btnLeg2TypeFixed: document.getElementById("btn-leg2-type-fixed"),

        // Curve Model Selector (USD SOFR only & CRS USD OIS)
        groupCurveModel: document.getElementById("group-curve-model"),
        lblCurveModel: document.getElementById("lbl-curve-model"),
        btnCurveStandard: document.getElementById("btn-curve-standard"),
        btnCurveAdvanced: document.getElementById("btn-curve-advanced"),

        // CRS Swap Structure (KRW_CRS only)
        groupCrsSwapType: document.getElementById("group-crs-swap-type"),
        btnCrsVanilla: document.getElementById("btn-crs-vanilla"),
        btnCrsFixedFixed: document.getElementById("btn-crs-fixed-fixed"),

        // Leg 2 Inputs (Spread vs USD Fixed Coupon)
        groupFloatSpread: document.getElementById("group-float-spread"),
        groupUsdFixedCoupon: document.getElementById("group-usd-fixed-coupon"),
        usdFixedCouponInput: document.getElementById("usd-fixed-coupon"),
        rowLeg2FixingDetails: document.getElementById("row-leg2-fixing-details"),

        // Symmetric Leg 1 Specifications (Fixed / KRW)
        leg1DayCount: document.getElementById("param-day-count"),
        leg1PaymentFreq: document.getElementById("param-payment-freq"),
        leg1Convention: document.getElementById("param-convention"),
        leg1Stub: document.getElementById("param-stub"),
        leg1Adjust: document.getElementById("param-adjust"),
        leg1PayCal: document.getElementById("param-pay-cal"),

        // Symmetric Leg 2 Specifications (Floating / USD)
        leg2DayCount: document.getElementById("leg2-day-count"),
        leg2PaymentFreq: document.getElementById("leg2-payment-freq"),
        leg2Convention: document.getElementById("leg2-convention"),
        leg2Stub: document.getElementById("leg2-stub"),
        leg2Adjust: document.getElementById("leg2-adjust"),
        leg2Cal: document.getElementById("leg2-cal"),

        // Dual-Leg Rollercoaster / Marketer Paste Elements
        rcPasteInput: document.getElementById("rc-paste-input"),
        rcPasteInputLeg1: document.getElementById("rc-paste-input-leg1"),
        rcPasteInputLeg2: document.getElementById("rc-paste-input-leg2"),
        btnRcSample: document.getElementById("btn-rc-sample"),
        btnRcDownloadTemplate: document.getElementById("btn-rc-download-template"),
        btnRcUploadBtn: document.getElementById("btn-rc-upload-btn"),
        rcExcelFileInput: document.getElementById("rc-excel-file-input"),
        btnSyncHolidaysLseg: document.getElementById("btn-sync-holidays-lseg"),
        btnRcCopyL1ToL2: document.getElementById("btn-rc-copy-l1-to-l2"),
        btnRcClear: document.getElementById("btn-rc-clear"),
        btnRcClearLeg1: document.getElementById("btn-rc-clear-leg1"),
        btnRcClearLeg2: document.getElementById("btn-rc-clear-leg2"),
        rcStatusBadge: document.getElementById("rc-status-badge"),
        rcStatusBadgeLeg1: document.getElementById("rc-status-badge-leg1"),
        rcStatusBadgeLeg2: document.getElementById("rc-status-badge-leg2"),
        rcPeriodCount: document.getElementById("rc-period-count"),
        rcPeriodCountLeg1: document.getElementById("rc-period-count-leg1"),
        rcPeriodCountLeg2: document.getElementById("rc-period-count-leg2"),
        rcActiveSummary: document.getElementById("rc-active-summary"),

        // Parametric Specifications Controls (Legacy Aliases)
        paramDayCount: document.getElementById("param-day-count"),
        paramPaymentFreq: document.getElementById("param-payment-freq"),
        paramFixCal: document.getElementById("param-fix-cal"),
        paramPayCal: document.getElementById("param-pay-cal"),
        paramConvention: document.getElementById("param-convention"),
        paramStub: document.getElementById("param-stub"),
        paramAdjust: document.getElementById("param-adjust"),
        paramFixDay: document.getElementById("param-fix-day"),
        btnResetParams: document.getElementById("btn-reset-params"),

        // Action Buttons
        btnResetQuotes: document.getElementById("btn-reset-quotes"),
        btnReloadFeed: document.getElementById("btn-reload-feed"),
        btnReloadMarket: document.getElementById("btn-reload-market"),
        btnCalcPrice: document.getElementById("btn-calc-price"),
        btnOneShot: document.getElementById("btn-oneshot"),

        // Pricing Results
        calcStatus: document.getElementById("calc-status"),
        lblHeroPar: document.getElementById("lbl-hero-par"),
        resParRate: document.getElementById("res-par-rate"),
        resSpreadVsCpn: document.getElementById("res-spread-vs-cpn"),
        resParSecondary: document.getElementById("res-par-secondary"),
        resDealNpv: document.getElementById("res-deal-npv"),
        resPvBreakdown: document.getElementById("res-pv-breakdown"),
        resDv01: document.getElementById("res-dv01"),
        resAnnuity: document.getElementById("res-annuity"),
        deltaBarsContainer: document.getElementById("delta-bars"),
        lblDeltaSectionTitle: document.getElementById("lbl-delta-section-title"),
        hedgeDeltaSection: document.getElementById("hedge-delta-section"),
        hedgeDeltaBarsContainer: document.getElementById("hedge-delta-bars"),

        // Waterfall & Dual Schedules
        waterfallToggle: document.getElementById("waterfall-toggle"),
        waterfallContent: document.getElementById("waterfall-content"),
        collapseIcon: document.getElementById("collapse-icon"),
        scheduleTitleText: document.getElementById("schedule-title-text"),
        periodCountBadge: document.getElementById("period-count-badge"),
        scheduleModeBadge: document.getElementById("schedule-mode-badge"),
        btnResetSchedule: document.getElementById("btn-reset-schedule"),
        btnExportCsv: document.getElementById("btn-export-csv"),
        dualTableBody: document.getElementById("dual-table-body"),
        leg1TableBody: document.getElementById("leg1-table-body"),
        leg2TableBody: document.getElementById("leg2-table-body"),
        tabButtons: document.querySelectorAll(".tab-btn"),
        tabPanes: document.querySelectorAll(".tab-pane"),

        // Table Column Headers (for Currency dynamic units)
        thFixedCf: document.getElementById("th-fixed-cf"),
        thFixedPv: document.getElementById("th-fixed-pv"),
        thFwdRate: document.getElementById("th-fwd-rate"),
        thFloatCf: document.getElementById("th-float-cf"),
        thFloatPv: document.getElementById("th-float-pv"),
        thNetCf: document.getElementById("th-net-cf"),
        thNetPv: document.getElementById("th-net-pv"),
        thLeg1Notional: document.getElementById("th-leg1-notional"),
        thLeg1Frac: document.getElementById("th-leg1-frac"),
        thLeg1Cf: document.getElementById("th-leg1-cf"),
        thLeg1Pv: document.getElementById("th-leg1-pv"),
        thLeg2Notional: document.getElementById("th-leg2-notional"),
        thLeg2Frac: document.getElementById("th-leg2-frac"),
        thLeg2Fwd: document.getElementById("th-leg2-fwd"),
        thLeg2Cf: document.getElementById("th-leg2-cf"),
        thLeg2Pv: document.getElementById("th-leg2-pv"),

        // CRS Spot FX & Dual Notional Inputs
        capitalFxRate: document.getElementById("capital-fx-rate"),
        groupCapitalFx: document.getElementById("group-capital-fx"),
        krwNotionalDisplay: document.getElementById("krw-notional-display"),
        rowKrwNotional: document.getElementById("row-krw-notional"),

        // Schedule Actions Toolbar & Murex View
        btnCopyExcel: document.getElementById("btn-copy-excel"),
        btnOpenEvalModal: document.getElementById("btn-open-eval-modal"),
        btnOpenEvalModalPane: document.getElementById("btn-open-eval-modal-pane"),
        tabBtnMurex: document.getElementById("tab-btn-murex"),
        murexTableBody: document.getElementById("murex-table-body"),

        // Murex Global Evaluation Modal
        evalModalBackdrop: document.getElementById("eval-modal-backdrop"),
        evalModalWindow: document.getElementById("eval-modal-window"),
        evalModalHeader: document.getElementById("eval-modal-header"),
        evalModalBtnMax: document.getElementById("eval-modal-btn-max"),
        evalModalBtnClose: document.getElementById("eval-modal-btn-close"),
        evalBtnCloseFooter: document.getElementById("eval-btn-close-footer"),
        evalBtnCopy: document.getElementById("eval-btn-copy"),
        evalTabs: document.querySelectorAll(".eval-tab-btn"),
        evalModalSubbar: document.getElementById("eval-modal-subbar"),
        evalTableBody: document.getElementById("eval-table-body"),
        evalTotalFlow: document.getElementById("eval-total-flow"),
        evalTotalDiscFlow: document.getElementById("eval-total-disc-flow"),
        evalInfoTradeTag: document.getElementById("eval-info-trade-tag"),
        evalInfoNpv: document.getElementById("eval-info-npv"),
        evalInfoTenor: document.getElementById("eval-info-tenor"),

        // Paste Schedule Modal

        // Quote Modal
        quoteModalBackdrop: document.getElementById("quote-modal-backdrop"),
        modalTenor: document.getElementById("modal-tenor"),
        modalRic: document.getElementById("modal-ric"),
        modalMid: document.getElementById("modal-mid"),
        modalCloseBtn: document.getElementById("modal-close-btn"),
        modalCancelBtn: document.getElementById("modal-cancel-btn"),
        modalSaveBtn: document.getElementById("modal-save-btn"),

        // App Key Modal
        btnOpenAppkeyModal: document.getElementById("btn-open-appkey-modal"),
        appkeyModalBackdrop: document.getElementById("appkey-modal-backdrop"),
        inputAppKey: document.getElementById("input-app-key"),
        lsegConnStatusMsg: document.getElementById("lseg-conn-status-msg"),
        appkeyModalCloseBtn: document.getElementById("appkey-modal-close-btn"),
        appkeyModalCancelBtn: document.getElementById("appkey-modal-cancel-btn"),
        appkeyModalSaveBtn: document.getElementById("appkey-modal-save-btn"),

        // Toast Container
        toastContainer: document.getElementById("toast-container")
    };

    // --------------------------------------------------------------------------
    // 1. Formatting Helpers
    // --------------------------------------------------------------------------
    function formatNumberWithCommas(val) {
        if (val === null || val === undefined || val === "") return "";
        const clean = val.toString().replace(/[^0-9.-]/g, "");
        const isNeg = clean.startsWith("-");
        const absClean = isNeg ? clean.substring(1) : clean;
        const parts = absClean.split(".");
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        const res = parts.join(".");
        return isNeg ? `-${res}` : res;
    }

    function parseFormattedNumber(val) {
        if (!val) return 0;
        return parseFloat(val.toString().replace(/,/g, "")) || 0;
    }

    function formatCurrency(val, isKrw = false) {
        if (val === null || val === undefined || isNaN(val)) return "-";
        const symbol = isKrw ? "\u20A9 " : "$ ";
        const isNeg = val < 0;
        const absVal = Math.abs(val);
        const decimals = isKrw ? 0 : 2;
        const numStr = formatNumberWithCommas(absVal.toFixed(decimals));
        return isNeg ? `-${symbol}${numStr}` : `${symbol}${numStr}`;
    }

    function formatAccounting(val, isKrw = false) {
        if (val === null || val === undefined || isNaN(val) || Math.abs(val) < 0.001) return "-";
        const isNeg = val < 0;
        const absVal = Math.abs(val);
        const decimals = isKrw ? 0 : 2;
        const formatted = formatNumberWithCommas(absVal.toFixed(decimals));
        if (isNeg) {
            return `<span style="color:#f43f5e; font-weight:600;">(${formatted})</span>`;
        } else {
            return `<span style="color:#10b981; font-weight:600;">${formatted}</span>`;
        }
    }

    function showToast(msg, type = "info") {
        if (!elements.toastContainer) return;
        const toast = document.createElement("div");
        toast.className = `toast ${type}`;
        toast.innerHTML = `<span class="toast-icon">${type === "success" ? "\u2713" : type === "warning" ? "\u26A0" : "\u2139"}</span><span>${msg}</span>`;
        elements.toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateX(50px)";
            setTimeout(() => toast.remove(), 300);
        }, 3500);
    }

    // Two-Way Interactive Notional & Capital FX Calculation
    function syncCrsNotionals(source) {
        if (state.currency !== "KRW_CRS") return;
        const fx = parseFormattedNumber(elements.capitalFxRate?.value) || 1373.50;
        if (source === "usd") {
            const usdVal = parseFormattedNumber(elements.notionalDisplay.value);
            const krwVal = Math.round(usdVal * fx);
            if (elements.krwNotionalDisplay) elements.krwNotionalDisplay.value = formatNumberWithCommas(krwVal);
        } else if (source === "krw") {
            const krwVal = parseFormattedNumber(elements.krwNotionalDisplay.value);
            const usdVal = Math.round(krwVal / fx);
            elements.notionalDisplay.value = formatNumberWithCommas(usdVal);
        } else if (source === "fx") {
            const usdVal = parseFormattedNumber(elements.notionalDisplay.value);
            const krwVal = Math.round(usdVal * fx);
            if (elements.krwNotionalDisplay) elements.krwNotionalDisplay.value = formatNumberWithCommas(krwVal);
        }
    }

    function applyCurrencyParamDefaults(curr) {
        const setVal = (elem, val) => { if (elem) elem.value = val; };
        if (curr === "KRW_CRS") {
            // Leg 1 (KRW)
            setVal(elements.leg1DayCount || elements.paramDayCount, "30/360");
            setVal(elements.leg1PaymentFreq || elements.paramPaymentFreq, "6M");
            setVal(elements.leg1Convention || elements.paramConvention, "Modified Following");
            setVal(elements.leg1Stub || elements.paramStub, "Short in arrears");
            setVal(elements.leg1Adjust || elements.paramAdjust, "Adjust");
            setVal(elements.leg1PayCal || elements.paramPayCal, "SEB_NYB");

            // Leg 2 (USD)
            setVal(elements.leg2DayCount, state.crsSwapType === "Fixed-Fixed" ? "30/360" : "Act/360");
            setVal(elements.leg2PaymentFreq, "6M");
            setVal(elements.leg2Convention, "Modified Following");
            setVal(elements.leg2Stub, "Short in arrears");
            setVal(elements.leg2Adjust, "Adjust");
            setVal(elements.leg2Cal, "SEB_NYB");
            setVal(elements.paramFixCal, "SEB_NYB");
            setVal(elements.paramFixDay, "-1");
        } else if (curr === "KRW_KOFR") {
            // Leg 1 (Fixed)
            setVal(elements.leg1DayCount || elements.paramDayCount, "Act/365");
            setVal(elements.leg1PaymentFreq || elements.paramPaymentFreq, "3M");
            setVal(elements.leg1Convention || elements.paramConvention, "Modified Following");
            setVal(elements.leg1Stub || elements.paramStub, "Short in arrears");
            setVal(elements.leg1Adjust || elements.paramAdjust, "Adjust");
            setVal(elements.leg1PayCal || elements.paramPayCal, "SEB");

            // Leg 2 (Float)
            setVal(elements.leg2DayCount, "Act/365");
            setVal(elements.leg2PaymentFreq, "3M");
            setVal(elements.leg2Convention, "Modified Following");
            setVal(elements.leg2Stub, "Short in arrears");
            setVal(elements.leg2Adjust, "Adjust");
            setVal(elements.leg2Cal, "SEB");
            setVal(elements.paramFixCal, "SEB");
            setVal(elements.paramFixDay, "0");
        } else if (curr === "KRW") {
            // Leg 1 (Fixed)
            setVal(elements.leg1DayCount || elements.paramDayCount, "Act/365");
            setVal(elements.leg1PaymentFreq || elements.paramPaymentFreq, "3M");
            setVal(elements.leg1Convention || elements.paramConvention, "Modified Following");
            setVal(elements.leg1Stub || elements.paramStub, "Short in arrears");
            setVal(elements.leg1Adjust || elements.paramAdjust, "Adjust");
            setVal(elements.leg1PayCal || elements.paramPayCal, "SEB");

            // Leg 2 (Float)
            setVal(elements.leg2DayCount, "Act/365");
            setVal(elements.leg2PaymentFreq, "3M");
            setVal(elements.leg2Convention, "Modified Following");
            setVal(elements.leg2Stub, "Short in arrears");
            setVal(elements.leg2Adjust, "Adjust");
            setVal(elements.leg2Cal, "SEB");
            setVal(elements.paramFixCal, "SEB");
            setVal(elements.paramFixDay, "-1");
        } else if (curr === "USD") {
            // Leg 1 (Fixed)
            setVal(elements.leg1DayCount || elements.paramDayCount, "Act/360");
            setVal(elements.leg1PaymentFreq || elements.paramPaymentFreq, "12M");
            setVal(elements.leg1Convention || elements.paramConvention, "Modified Following");
            setVal(elements.leg1Stub || elements.paramStub, "Short in arrears");
            setVal(elements.leg1Adjust || elements.paramAdjust, "Adjust");
            setVal(elements.leg1PayCal || elements.paramPayCal, "NYB");

            // Leg 2 (Float)
            setVal(elements.leg2DayCount, "Act/360");
            setVal(elements.leg2PaymentFreq, "12M");
            setVal(elements.leg2Convention, "Modified Following");
            setVal(elements.leg2Stub, "Short in arrears");
            setVal(elements.leg2Adjust, "Adjust");
            setVal(elements.leg2Cal, "NYB");
            setVal(elements.paramFixCal, "NYB");
            setVal(elements.paramFixDay, "-2");
        }
    }

    function setCurveType(type, triggerPricing = true) {
        if (!type) return;
        state.curveType = type;

        const curveButtons = [
            { el: elements.btnCurveStandard, name: "Standard" },
            { el: elements.btnCurveAdvanced, name: "Advanced" }
        ];

        curveButtons.forEach(({ el, name }) => {
            if (!el) return;
            if (name.toLowerCase() === type.toLowerCase()) {
                el.classList.add("active");
                el.style.background = "#2563eb";
                el.style.color = "#fff";
                el.style.borderColor = "#94a3b8";
            } else {
                el.classList.remove("active");
                el.style.background = "#f1f5f9";
                el.style.color = "#475569";
                el.style.borderColor = "#cbd5e1";
            }
        });

        saveActiveTicketFormData();
        if (triggerPricing) {
            if (state.currency === "USD") {
                loadMarketSnapshot().then(() => calculatePricing());
            } else {
                calculatePricing();
            }
        }
    }

    function setCrsSwapType(type, triggerPricing = true) {
        if (!type) return;
        state.crsSwapType = type;
        const isFixedFixed = (type === "Fixed-Fixed");

        // 1. Update Dual-Leg Header Structure Toggle buttons
        if (elements.btnStructVanilla && elements.btnStructFixedFixed) {
            if (isFixedFixed) {
                elements.btnStructFixedFixed.classList.add("active");
                elements.btnStructFixedFixed.style.background = "#2563eb";
                elements.btnStructFixedFixed.style.color = "#fff";
                elements.btnStructFixedFixed.style.borderColor = "#2563eb";

                elements.btnStructVanilla.classList.remove("active");
                elements.btnStructVanilla.style.background = "#ffffff";
                elements.btnStructVanilla.style.color = "#475569";
                elements.btnStructVanilla.style.borderColor = "#cbd5e1";
            } else {
                elements.btnStructVanilla.classList.add("active");
                elements.btnStructVanilla.style.background = "#2563eb";
                elements.btnStructVanilla.style.color = "#fff";
                elements.btnStructVanilla.style.borderColor = "#2563eb";

                elements.btnStructFixedFixed.classList.remove("active");
                elements.btnStructFixedFixed.style.background = "#ffffff";
                elements.btnStructFixedFixed.style.color = "#475569";
                elements.btnStructFixedFixed.style.borderColor = "#cbd5e1";
            }
        }

        // 2. Update Leg 2 mini-type toggle buttons
        if (elements.btnLeg2TypeFloat && elements.btnLeg2TypeFixed) {
            if (isFixedFixed) {
                elements.btnLeg2TypeFixed.classList.add("active");
                elements.btnLeg2TypeFixed.style.background = "#2563eb";
                elements.btnLeg2TypeFixed.style.color = "#fff";
                elements.btnLeg2TypeFloat.classList.remove("active");
                elements.btnLeg2TypeFloat.style.background = "#f1f5f9";
                elements.btnLeg2TypeFloat.style.color = "#64748b";
            } else {
                elements.btnLeg2TypeFloat.classList.add("active");
                elements.btnLeg2TypeFloat.style.background = "#2563eb";
                elements.btnLeg2TypeFloat.style.color = "#fff";
                elements.btnLeg2TypeFixed.classList.remove("active");
                elements.btnLeg2TypeFixed.style.background = "#f1f5f9";
                elements.btnLeg2TypeFixed.style.color = "#64748b";
            }
        }

        // 3. Synchronize CRS Swap Structure row (KRW_CRS only)
        if (elements.btnCrsVanilla && elements.btnCrsFixedFixed) {
            if (isFixedFixed) {
                elements.btnCrsFixedFixed.classList.add("active");
                elements.btnCrsFixedFixed.style.background = "#2563eb";
                elements.btnCrsFixedFixed.style.color = "#fff";
                elements.btnCrsFixedFixed.style.borderColor = "#3b82f6";

                elements.btnCrsVanilla.classList.remove("active");
                elements.btnCrsVanilla.style.background = "#dbeafe";
                elements.btnCrsVanilla.style.color = "#1e40af";
                elements.btnCrsVanilla.style.borderColor = "#bfdbfe";
            } else {
                elements.btnCrsVanilla.classList.add("active");
                elements.btnCrsVanilla.style.background = "#2563eb";
                elements.btnCrsVanilla.style.color = "#fff";
                elements.btnCrsVanilla.style.borderColor = "#3b82f6";

                elements.btnCrsFixedFixed.classList.remove("active");
                elements.btnCrsFixedFixed.style.background = "#dbeafe";
                elements.btnCrsFixedFixed.style.color = "#1e40af";
                elements.btnCrsFixedFixed.style.borderColor = "#bfdbfe";
            }
        }

        // 4. Update Leg 2 Card fields, subtags, and conventions
        const l2Curr = (state.currency === "KRW_CRS") ? "USD" : (state.currency.startsWith("KRW") ? "KRW" : "USD");
        if (isFixedFixed) {
            if (elements.groupFloatSpread) elements.groupFloatSpread.style.display = "none";
            if (elements.groupUsdFixedCoupon) elements.groupUsdFixedCoupon.style.display = "block";
            if (elements.rowLeg2FixingDetails) elements.rowLeg2FixingDetails.style.display = "none";
            if (elements.tagFloatLeg) elements.tagFloatLeg.textContent = `\u25B8 Leg 2 (Fixed / ${l2Curr})`;
            if (elements.tagFloatSub) elements.tagFloatSub.textContent = "Coupon & Schedule";
            if (elements.leg2DayCount && elements.leg2DayCount.value === "Act/360") {
                elements.leg2DayCount.value = "30/360";
            }

            // Update Direction Bar Texts
            if (elements.phaseTitlePay) elements.phaseTitlePay.textContent = "Pay Leg 1 Fixed (Rec Leg 2 Fixed)";
            if (elements.phaseDescPay) elements.phaseDescPay.textContent = "Pay Leg 1 Fixed Coupon ↔ Receive Leg 2 Fixed Coupon";
            if (elements.phaseTitleRec) elements.phaseTitleRec.textContent = "Receive Leg 1 Fixed (Pay Leg 2 Fixed)";
            if (elements.phaseDescRec) elements.phaseDescRec.textContent = "Receive Leg 1 Fixed Coupon ↔ Pay Leg 2 Fixed Coupon";
        } else {
            if (elements.groupFloatSpread) elements.groupFloatSpread.style.display = "block";
            if (elements.groupUsdFixedCoupon) elements.groupUsdFixedCoupon.style.display = "none";
            if (elements.rowLeg2FixingDetails) elements.rowLeg2FixingDetails.style.display = "flex";
            if (elements.tagFloatLeg) elements.tagFloatLeg.textContent = `\u25B8 Leg 2 (Floating / ${l2Curr})`;
            if (elements.tagFloatSub) elements.tagFloatSub.textContent = "Index & Fixing";
            if (elements.leg2DayCount && elements.leg2DayCount.value === "30/360") {
                elements.leg2DayCount.value = "Act/360";
            }

            // Update Direction Bar Texts
            if (elements.phaseTitlePay) elements.phaseTitlePay.textContent = "Pay Fixed (Rec Float)";
            if (elements.phaseDescPay) elements.phaseDescPay.textContent = "Pay Fixed Coupon ↔ Receive Floating Index";
            if (elements.phaseTitleRec) elements.phaseTitleRec.textContent = "Receive Fixed (Pay Float)";
            if (elements.phaseDescRec) elements.phaseDescRec.textContent = "Receive Fixed Coupon ↔ Pay Floating Index";
        }

        renderScheduleHeaders();
        saveActiveTicketFormData();
        if (triggerPricing) {
            calculatePricing();
        }
    }

    function updateCurveAndStructureVisibility() {
        if (state.currency === "USD") {
            if (elements.groupCurveModel) {
                elements.groupCurveModel.style.display = "flex";
                if (elements.lblCurveModel) elements.lblCurveModel.textContent = "USD SOFR Curve Model:";
            }
            if (elements.groupCrsSwapType) elements.groupCrsSwapType.style.display = "none";
            setCrsSwapType(state.crsSwapType || "Vanilla", false);
            setCurveType(state.curveType || "Standard", false);
        } else if (state.currency === "KRW_CRS") {
            if (elements.groupCurveModel) {
                elements.groupCurveModel.style.display = "flex";
                if (elements.lblCurveModel) elements.lblCurveModel.textContent = "USD SOFR OIS Curve Model:";
            }
            if (elements.groupCrsSwapType) elements.groupCrsSwapType.style.display = "flex";
            setCrsSwapType(state.crsSwapType || "Vanilla", false);
            setCurveType(state.curveType || "Standard", false);
        } else {
            if (elements.groupCurveModel) elements.groupCurveModel.style.display = "none";
            if (elements.groupCrsSwapType) elements.groupCrsSwapType.style.display = "none";
            setCrsSwapType(state.crsSwapType || "Vanilla", false);
        }
    }

    // --------------------------------------------------------------------------
    // 2. Currency Switcher Handler
    // --------------------------------------------------------------------------
    function setCurrency(newCurrency) {
        if (state.currency !== newCurrency && typeof saveActiveTicketFormData === "function") {
            saveActiveTicketFormData();
        }
        if (state.currency === newCurrency) return;
        state.currency = newCurrency;
        state.customSchedule = null; // Reset custom schedule on currency switch
        if (newCurrency !== "USD_FWD") {
            applyCurrencyParamDefaults(newCurrency);
        }

        elements.btnCurrUsd.classList.remove("active");
        elements.btnCurrKrw.classList.remove("active");
        if (elements.btnCurrKofr) elements.btnCurrKofr.classList.remove("active");
        if (elements.btnCurrCrs) elements.btnCurrCrs.classList.remove("active");
        if (elements.btnCurrFwd) elements.btnCurrFwd.classList.remove("active");

        if (newCurrency === "USD_FWD") {
            if (elements.btnCurrFwd) elements.btnCurrFwd.classList.add("active");
            if (elements.swapTradeContainer) elements.swapTradeContainer.style.display = "none";
            if (elements.fwdTradeContainer) elements.fwdTradeContainer.style.display = "block";
            if (elements.swapResultsContainer) elements.swapResultsContainer.style.display = "none";
            if (elements.fwdResultsContainer) elements.fwdResultsContainer.style.display = "block";
            if (elements.rcPasteCard) elements.rcPasteCard.style.display = "none";
            if (elements.tabBtnFwd) elements.tabBtnFwd.style.display = "inline-flex";
            if (elements.tabBtnMurex) elements.tabBtnMurex.style.display = "none";

            elements.marketPanelTitle.textContent = "KMBC USD/KRW Forward Swap Points (KMBC)";
            elements.feedStatusText.innerHTML = "LSEG Workspace";
            elements.tradePanelTitle.textContent = "USD/KRW Forward Swap Point Pricer";
            elements.tradeBadgeTag.textContent = "Far Leg Maturity + Notional + Margin bp → Quoted SP & FX Delta";

            // Update Quote Table Header for KMBC Swap Points
            const thead = document.querySelector("#quote-table thead");
            if (thead) {
                thead.innerHTML = `
                    <tr>
                        <th>Tenor</th>
                        <th>RIC</th>
                    <th class="num">Bid (₩)</th>
                    <th class="num">Ask (₩)</th>
                    <th class="num">Mid (₩)</th>
                    </tr>
                `;
            }

            switchScheduleTab("fwd");
            if (typeof getActiveTicket === "function") {
                loadTicketToUI(getActiveTicket("USD_FWD"));
                renderTicketBar();
            }
            showToast("Switched to USD/KRW Forward Swap Point Pricer", "info");
            fetchFwdMarketSnapshot();
            calculateFwdPricing();
            return;
        } else {
            if (elements.swapTradeContainer) elements.swapTradeContainer.style.display = "block";
            if (elements.fwdTradeContainer) elements.fwdTradeContainer.style.display = "none";
            if (elements.swapResultsContainer) elements.swapResultsContainer.style.display = "block";
            if (elements.fwdResultsContainer) elements.fwdResultsContainer.style.display = "none";
            if (elements.rcPasteCard) elements.rcPasteCard.style.display = "block";
            if (elements.tabBtnFwd) elements.tabBtnFwd.style.display = "none";
            if (state.activeScheduleTab === "fwd") {
                switchScheduleTab("dual");
            }

            // Restore Quote Table Header for Swaps
            const thead = document.querySelector("#quote-table thead");
            if (thead) {
                thead.innerHTML = `
                    <tr>
                        <th>Tenor</th>
                        <th>RIC</th>
                        <th class="num">Bid</th>
                        <th class="num">Ask</th>
                        <th class="num">Mid (%)</th>
                        <th class="num">Chg(bp)</th>
                    </tr>
                `;
            }
        }

        if (newCurrency === "KRW_CRS") {
            if (elements.btnCurrCrs) elements.btnCurrCrs.classList.add("active");
            if (elements.groupCapitalFx) elements.groupCapitalFx.style.display = "block";
            if (elements.rowKrwNotional) elements.rowKrwNotional.style.display = "flex";
            if (elements.tabBtnMurex) elements.tabBtnMurex.style.display = "inline-flex";

            // Update Labels for KRWFXSOFR (CRS)
            elements.marketPanelTitle.textContent = "Prebon KRUSQ CRS Quotes";
            elements.feedStatusText.innerHTML = "LSEG Workspace";
            elements.tradePanelTitle.textContent = "USD/KRW Cross Currency Swap (CRS) Specifications";
            elements.tradeBadgeTag.textContent = "USD SOFR vs KRW Fixed CRS (Murex Global Parity)";
            elements.lblNotional.textContent = "USD Notional ($)";
            elements.notionalAffix.textContent = "$";
            elements.notionalDisplay.value = "100,000,000"; // $ 100M default for CRS
            
            const liveFx = (state.marketSnapshot && state.marketSnapshot.spot_fx) ? state.marketSnapshot.spot_fx : 1373.50;
            if (elements.capitalFxRate) elements.capitalFxRate.value = formatNumberWithCommas(liveFx.toFixed(2));
            if (elements.krwNotionalDisplay) elements.krwNotionalDisplay.value = formatNumberWithCommas(Math.round(100_000_000 * liveFx));
            elements.lblEffectiveDate.textContent = "Effective Date (Spot T+2)";



            // Stats Labels
            elements.lblFixRate.textContent = "Spot FX";
            elements.lbl1yRate.textContent = "1Y CRS";
            elements.lbl3yRate.textContent = "3Y CRS";
            elements.lbl5yRate.textContent = "5Y CRS";

            // Headers
            elements.thFixedCf.textContent = "KRW Leg CF (\u20A9)";
            elements.thFixedPv.textContent = "KRW Leg PV (\u20A9)";
            elements.thFwdRate.textContent = "Fwd SOFR";
            elements.thFloatCf.textContent = "USD Leg CF ($)";
            elements.thFloatPv.textContent = "USD Leg PV ($)";
            elements.thNetCf.textContent = "Net CF (\u20A9)";
            elements.thNetPv.textContent = "Net PV (\u20A9)";
            elements.thLeg1Notional.textContent = "KRW Notional (\u20A9)";
            elements.thLeg1Frac.textContent = "Fraction (30/360)";
            elements.thLeg1Cf.textContent = "KRW Flow (\u20A9)";
            elements.thLeg1Pv.textContent = "Present Value (\u20A9)";
            elements.thLeg2Notional.textContent = "USD Notional ($)";
            elements.thLeg2Frac.textContent = "Fraction (30/360)";
            elements.thLeg2Fwd.textContent = "Fwd SOFR (%)";
            elements.thLeg2Cf.textContent = "USD Flow ($)";
            elements.thLeg2Pv.textContent = "Present Value ($)";

            // Default Tenor for CRS: 5Y
            state.selectedTenor = "5Y";
            updateTenorChipsUI("5Y");
            elements.couponInput.value = "3.5500";

        } else if (newCurrency === "KRW_KOFR") {
            if (elements.btnCurrKofr) elements.btnCurrKofr.classList.add("active");
            if (elements.groupCapitalFx) elements.groupCapitalFx.style.display = "none";
            if (elements.rowKrwNotional) elements.rowKrwNotional.style.display = "none";
            if (elements.tabBtnMurex) elements.tabBtnMurex.style.display = "inline-flex";

            // Update Labels for KRW KOFR OIS
            elements.marketPanelTitle.textContent = "KMBC KRW KOFR OIS Quotes";
            elements.feedStatusText.innerHTML = "LSEG Workspace";
            elements.tradePanelTitle.textContent = "KRW KOFR OIS Trade Specifications";
            elements.tradeBadgeTag.textContent = "KRW / \\KRW KOFR Q 3M (+2BD Lag)";
            elements.lblNotional.textContent = "Notional (KRW)";
            elements.notionalAffix.textContent = "\u20A9";
            elements.notionalDisplay.value = "10,000,000,000"; // 100억 원
            elements.lblEffectiveDate.textContent = "Effective Date (Spot T+1)";



            // Stats Labels
            elements.lblFixRate.textContent = "KOFR Fix (ON)";
            elements.lbl1yRate.textContent = "1Y KOFR";
            elements.lbl3yRate.textContent = "2Y KOFR";
            elements.lbl5yRate.textContent = "3Y KOFR";

            // Headers
            elements.thFixedCf.textContent = "Fixed CF (\u20A9)";
            elements.thFixedPv.textContent = "Fixed PV (\u20A9)";
            elements.thFwdRate.textContent = "Fwd KOFR";
            elements.thFloatCf.textContent = "Float CF (\u20A9)";
            elements.thFloatPv.textContent = "Float PV (\u20A9)";
            elements.thNetCf.textContent = "Net CF (\u20A9)";
            elements.thNetPv.textContent = "Net PV (\u20A9)";
            elements.thLeg1Notional.textContent = "Notional (\u20A9)";
            elements.thLeg1Frac.textContent = "Fraction (Act/365)";
            elements.thLeg1Cf.textContent = "Fixed CF (\u20A9)";
            elements.thLeg1Pv.textContent = "Present Value (\u20A9)";
            elements.thLeg2Notional.textContent = "Notional (\u20A9)";
            elements.thLeg2Frac.textContent = "Fraction (Act/365)";
            elements.thLeg2Fwd.textContent = "Fwd KOFR (%)";
            elements.thLeg2Cf.textContent = "Float CF (\u20A9)";
            elements.thLeg2Pv.textContent = "Present Value (\u20A9)";

            // Default Tenor for KOFR: 1Y
            state.selectedTenor = "1Y";
            updateTenorChipsUI("1Y");
            elements.couponInput.value = "3.3775";

        } else if (newCurrency === "KRW") {
            elements.btnCurrKrw.classList.add("active");
            if (elements.groupCapitalFx) elements.groupCapitalFx.style.display = "none";
            if (elements.rowKrwNotional) elements.rowKrwNotional.style.display = "none";
            if (elements.tabBtnMurex) elements.tabBtnMurex.style.display = "inline-flex";

            // Update Labels for KRW CD IRS
            elements.marketPanelTitle.textContent = "Prebon KRW CD 91D IRS Quotes";
            elements.feedStatusText.innerHTML = "LSEG Workspace";
            elements.tradePanelTitle.textContent = "KRW CD IRS Trade Specifications";
            elements.tradeBadgeTag.textContent = "KRW / CD 91D Quarterly";
            elements.lblNotional.textContent = "Notional (KRW)";
            elements.notionalAffix.textContent = "\u20A9";
            elements.notionalDisplay.value = "10,000,000,000"; // 100억 원
            elements.lblEffectiveDate.textContent = "Effective Date (Spot T+1)";



            // Stats Labels
            elements.lblFixRate.textContent = "CD 91D Fix";
            elements.lbl1yRate.textContent = "1Y IRS";
            elements.lbl3yRate.textContent = "2Y IRS";
            elements.lbl5yRate.textContent = "3Y IRS";

            // Headers
            elements.thFixedCf.textContent = "Fixed CF (\u20A9)";
            elements.thFixedPv.textContent = "Fixed PV (\u20A9)";
            elements.thFwdRate.textContent = "Fwd CD 91D";
            elements.thFloatCf.textContent = "Float CF (\u20A9)";
            elements.thFloatPv.textContent = "Float PV (\u20A9)";
            elements.thNetCf.textContent = "Net CF (\u20A9)";
            elements.thNetPv.textContent = "Net PV (\u20A9)";
            elements.thLeg1Notional.textContent = "Notional (\u20A9)";
            elements.thLeg1Frac.textContent = "Fraction (Act/365)";
            elements.thLeg1Cf.textContent = "Fixed CF (\u20A9)";
            elements.thLeg1Pv.textContent = "Present Value (\u20A9)";
            elements.thLeg2Notional.textContent = "Notional (\u20A9)";
            elements.thLeg2Frac.textContent = "Fraction (Act/365)";
            elements.thLeg2Fwd.textContent = "Fwd CD 91D (%)";
            elements.thLeg2Cf.textContent = "Float CF (\u20A9)";
            elements.thLeg2Pv.textContent = "Present Value (\u20A9)";

            // Default Tenor for KRW: 3Y
            state.selectedTenor = "3Y";
            updateTenorChipsUI("3Y");
            elements.couponInput.value = "3.8475";

        } else {
            elements.btnCurrUsd.classList.add("active");
            if (elements.groupCapitalFx) elements.groupCapitalFx.style.display = "none";
            if (elements.rowKrwNotional) elements.rowKrwNotional.style.display = "none";
            if (elements.tabBtnMurex) elements.tabBtnMurex.style.display = "inline-flex";

            // Update Labels for USD SOFR
            elements.marketPanelTitle.textContent = "Tradeweb USD SOFR OIS Quotes";
            elements.feedStatusText.innerHTML = "LSEG Workspace";
            elements.tradePanelTitle.textContent = "USD IRS Trade Specifications";
            elements.tradeBadgeTag.textContent = "USD / SOFR Compound";
            elements.lblNotional.textContent = "Notional (USD)";
            elements.notionalAffix.textContent = "$";
            elements.notionalDisplay.value = "100,000,000"; // $ 100M
            elements.lblEffectiveDate.textContent = "Effective Date (Spot T+2)";



            // Stats Labels
            elements.lblFixRate.textContent = "SOFR Fix (ON)";
            elements.lbl1yRate.textContent = "1Y Swap";
            elements.lbl3yRate.textContent = "3Y Swap";
            elements.lbl5yRate.textContent = "5Y Swap";

            // Headers
            elements.thFixedCf.textContent = "Fixed CF ($)";
            elements.thFixedPv.textContent = "Fixed PV ($)";
            elements.thFwdRate.textContent = "Fwd SOFR";
            elements.thFloatCf.textContent = "Float CF ($)";
            elements.thFloatPv.textContent = "Float PV ($)";
            elements.thNetCf.textContent = "Net CF ($)";
            elements.thNetPv.textContent = "Net PV ($)";
            elements.thLeg1Notional.textContent = "Notional ($)";
            elements.thLeg1Frac.textContent = "Fraction (Act/360)";
            elements.thLeg1Cf.textContent = "Fixed CF ($)";
            elements.thLeg1Pv.textContent = "Present Value ($)";
            elements.thLeg2Notional.textContent = "Notional ($)";
            elements.thLeg2Frac.textContent = "Fraction (Act/360)";
            elements.thLeg2Fwd.textContent = "Fwd SOFR (%)";
            elements.thLeg2Cf.textContent = "Float CF ($)";
            elements.thLeg2Pv.textContent = "Present Value ($)";

            // Default Tenor for USD: 5Y
            state.selectedTenor = "5Y";
            updateTenorChipsUI("5Y");
        }

        if (elements.couponInput) elements.couponInput.dataset.userEdited = "";
        updateCurveAndStructureVisibility();
        renderScheduleHeaders();
        updateScheduleModeUI();
        setTradePosition(elements.positionSelect?.value || "Pay Fixed");
        if (typeof getActiveTicket === "function") {
            loadTicketToUI(getActiveTicket(newCurrency));
            renderTicketBar();
        }
        showToast(`Switched currency to ${newCurrency} mode`, "info");
        reloadAndPrice();
    }

    elements.btnCurrUsd.addEventListener("click", () => setCurrency("USD"));
    elements.btnCurrKrw.addEventListener("click", () => setCurrency("KRW"));
    if (elements.btnCurrKofr) elements.btnCurrKofr.addEventListener("click", () => setCurrency("KRW_KOFR"));
    if (elements.btnCurrCrs) elements.btnCurrCrs.addEventListener("click", () => setCurrency("KRW_CRS"));
    if (elements.btnCurrFwd) elements.btnCurrFwd.addEventListener("click", () => setCurrency("USD_FWD"));

    // Curve Model Selection Listeners
    if (elements.btnCurveStandard) elements.btnCurveStandard.addEventListener("click", () => setCurveType("Standard", true));
    if (elements.btnCurveAdvanced) elements.btnCurveAdvanced.addEventListener("click", () => setCurveType("Advanced", true));

    // CRS & Dual-Leg Swap Structure Listeners
    if (elements.btnCrsVanilla) elements.btnCrsVanilla.addEventListener("click", () => setCrsSwapType("Vanilla", true));
    if (elements.btnCrsFixedFixed) elements.btnCrsFixedFixed.addEventListener("click", () => setCrsSwapType("Fixed-Fixed", true));
    if (elements.btnStructVanilla) elements.btnStructVanilla.addEventListener("click", () => setCrsSwapType("Vanilla", true));
    if (elements.btnStructFixedFixed) elements.btnStructFixedFixed.addEventListener("click", () => setCrsSwapType("Fixed-Fixed", true));
    if (elements.btnLeg2TypeFloat) elements.btnLeg2TypeFloat.addEventListener("click", () => setCrsSwapType("Vanilla", true));
    if (elements.btnLeg2TypeFixed) elements.btnLeg2TypeFixed.addEventListener("click", () => setCrsSwapType("Fixed-Fixed", true));

    // --------------------------------------------------------------------------
    // 3. Tenor Management & Sync
    // --------------------------------------------------------------------------
    function updateTenorChipsUI(activeTenor) {
        const chips = elements.tenorChipsContainer.querySelectorAll(".chip");
        let matched = false;
        chips.forEach(chip => {
            const t = chip.dataset.tenor;
            if (t.toUpperCase() === activeTenor.toUpperCase()) {
                chip.classList.add("active");
                matched = true;
            } else {
                chip.classList.remove("active");
            }
        });

        const chipOdd = document.getElementById("chip-odd");
        if (!matched && chipOdd) {
            chipOdd.classList.add("active");
            chipOdd.textContent = `Odd (${activeTenor})`;
            elements.oddTenorContainer.classList.add("show");
            elements.customTenorInput.value = activeTenor;
        } else if (chipOdd) {
            chipOdd.textContent = "Odd Tenor";
        }
    }

    elements.tenorChipsContainer.addEventListener("click", (e) => {
        const chip = e.target.closest(".chip");
        if (!chip) return;
        const tenor = chip.dataset.tenor;

        if (tenor === "custom") {
            elements.oddTenorContainer.classList.toggle("show");
            if (elements.oddTenorContainer.classList.contains("show")) {
                elements.customTenorInput.focus();
            }
            return;
        }

        state.selectedTenor = tenor;
        elements.customTenorInput.value = tenor;
        updateTenorChipsUI(tenor);
        updateDatesFromTenor();
        if (elements.couponInput) elements.couponInput.dataset.userEdited = "";

        // Auto update Fixed Coupon input to matching tenor quote mid rate
        if (state.marketSnapshot && state.marketSnapshot.quotes) {
            const matchQ = state.marketSnapshot.quotes.find(q => q.tenor === tenor);
            if (matchQ && matchQ.mid) {
                elements.couponInput.value = matchQ.mid.toFixed(6);
            }
        }

        calculatePricing();
    });

    elements.customTenorInput.addEventListener("input", () => {
        const val = elements.customTenorInput.value.trim().toUpperCase();
        if (val) {
            state.selectedTenor = val;
            updateTenorChipsUI(val);
            updateDatesFromTenor();
        }
    });

    elements.btnApplyOddTenor.addEventListener("click", () => {
        const val = elements.customTenorInput.value.trim().toUpperCase();
        if (val) {
            state.selectedTenor = val;
            updateTenorChipsUI(val);
            updateDatesFromTenor();
            if (elements.couponInput) elements.couponInput.dataset.userEdited = "";
            if (state.marketSnapshot && state.marketSnapshot.quotes) {
                const matchQ = state.marketSnapshot.quotes.find(q => q.tenor === val);
                if (matchQ && matchQ.mid) {
                    elements.couponInput.value = matchQ.mid.toFixed(6);
                }
            }
            calculatePricing();
        }
    });

    // --------------------------------------------------------------------------
    // 4. Date Calculation Helpers
    // --------------------------------------------------------------------------
    function addMonthsToDate(date, months) {
        const d = new Date(date);
        const day = d.getDate();
        d.setMonth(d.getMonth() + months);
        if (d.getDate() !== day) {
            d.setDate(0);
        }
        return d;
    }

    function parseTenorMonths(tenorStr) {
        const s = (tenorStr || "5Y").trim().toUpperCase();
        const mYm = s.match(/^(\d+)Y(\d+)M$/);
        if (mYm) return parseInt(mYm[1]) * 12 + parseInt(mYm[2]);
        const mY = s.match(/^(\d+\.?\d*)Y$/);
        if (mY) return Math.round(parseFloat(mY[1]) * 12);
        const mM = s.match(/^(\d+)M$/);
        if (mM) return parseInt(mM[1]);
        const mW = s.match(/^(\d+)W$/);
        if (mW) return Math.max(1, Math.round(parseInt(mW[1]) / 4.33));
        return 60;
    }

    function updateDatesFromTenor() {
        if (!elements.effectiveDateInput.value) {
            const today = new Date();
            const spotDays = state.currency === "KRW" ? 1 : 2;
            const spot = new Date(today);
            spot.setDate(spot.getDate() + spotDays);
            elements.effectiveDateInput.value = spot.toISOString().split("T")[0];
        }

        const eff = new Date(elements.effectiveDateInput.value);
        if (isNaN(eff.getTime())) return;

        const months = parseTenorMonths(state.selectedTenor);
        const mat = addMonthsToDate(eff, months);
        elements.maturityDateInput.value = mat.toISOString().split("T")[0];
    }

    elements.effectiveDateInput.addEventListener("change", () => {
        updateDatesFromTenor();
        calculatePricing();
    });

    // --------------------------------------------------------------------------
    // 5. Market Snapshot & Data Loading
    // --------------------------------------------------------------------------
    function getSnapshotEndpoint(forceReload = false) {
        const reloadParam = forceReload ? `&reload=true&_t=${Date.now()}` : "";
        if (state.currency === "KRW_CRS") return `/api/crs/market-snapshot?reload=${forceReload}&_t=${Date.now()}`;
        if (state.currency === "KRW_KOFR") return `/api/kofr/market-snapshot?reload=${forceReload}&_t=${Date.now()}`;
        if (state.currency === "KRW") return `/api/krw/market-snapshot?reload=${forceReload}&_t=${Date.now()}`;
        return `/api/market-snapshot?curve_type=${state.curveType || "Standard"}${reloadParam}`;
    }
    function getPriceEndpoint() {
        if (state.currency === "KRW_CRS") return "/api/crs/price";
        if (state.currency === "KRW_KOFR") return "/api/kofr/price";
        if (state.currency === "KRW") return "/api/krw/price";
        return "/api/price";
    }
    function getReloadAndPriceEndpoint() {
        if (state.currency === "KRW_CRS") return "/api/crs/reload-and-price";
        if (state.currency === "KRW_KOFR") return "/api/kofr/reload-and-price";
        if (state.currency === "KRW") return "/api/krw/reload-and-price";
        return "/api/reload-and-price";
    }
    function getQuoteUpdateEndpoint() {
        if (state.currency === "KRW_CRS") return "/api/crs/quotes/update";
        if (state.currency === "KRW_KOFR") return "/api/kofr/quotes/update";
        if (state.currency === "KRW") return "/api/krw/quotes/update";
        return "/api/quotes/update";
    }
    function getQuoteResetEndpoint() {
        if (state.currency === "KRW_CRS") return "/api/crs/quotes/reset";
        if (state.currency === "KRW_KOFR") return "/api/kofr/quotes/reset";
        if (state.currency === "KRW") return "/api/krw/quotes/reset";
        return "/api/quotes/reset";
    }

    async function loadMarketSnapshot(forceReload = false) {
        if (state.currency === "USD_FWD") {
            return fetchFwdMarketSnapshot(forceReload);
        }
        try {
            elements.calcStatus.textContent = forceReload ? "Reloading..." : "Loading...";
            elements.calcStatus.className = "calc-status-badge calc-loading";

            const endpoint = getSnapshotEndpoint(forceReload);
            const resp = await fetch(endpoint);
            const data = await resp.json();

            if (data.status === "success") {
                const payloadData = data.data || data;
                state.marketSnapshot = payloadData;
                state.curvePillars = payloadData.curve_pillars || [];
                state.lastSnapshotTime = new Date();

                // Live Spot FX Sync for CRS
                if (state.currency === "KRW_CRS" && payloadData.spot_fx) {
                    elements.oisFixRate.textContent = `${payloadData.spot_fx.toFixed(2)}`;
                    if (elements.capitalFxRate) {
                        elements.capitalFxRate.value = formatNumberWithCommas(payloadData.spot_fx.toFixed(2));
                    }
                    syncCrsNotionals("usd");
                }

                renderMarketQuotes(payloadData.quotes);
                renderCurveChart(payloadData.curve_pillars);

                // Update Effective Date from Settle Date
                if (payloadData.settle_date) {
                    elements.effectiveDateInput.value = payloadData.settle_date;
                    updateDatesFromTenor();
                }

                // Update Header Time
                if (payloadData.timestamp) {
                    elements.snapshotTimestamp.textContent = payloadData.timestamp.split(" ")[1] || "--:--:--";
                    markSnapshotTaken();
                    if (payloadData.is_live_connected) {
                        elements.liveConnectedBadge.style.display = "inline-flex";
                    }
                }

                // Automatically re-calculate pricing with freshly reloaded market rates
                await calculatePricing();

                elements.calcStatus.textContent = "Market Live";
                elements.calcStatus.className = "calc-status-badge calc-ready";
                showToast(`Market reloaded & pricing refreshed for ${state.currency}`, "success");
            }
        } catch (err) {
            console.error("Market fetch error:", err);
            elements.calcStatus.textContent = "Offline Base";
            elements.calcStatus.className = "calc-status-badge calc-offline";
            showToast(`Market reload failed: ${err.message}`, "warning");
        }
    }

    // ---- Market data freshness -------------------------------------------------
    // A live pricer must never let a trader mistake an old snapshot for a live one,
    // so the badge ages on a timer and the results panel is flagged once data is stale.
    const STALE_AGING_SEC = 30;
    const STALE_OLD_SEC = 120;

    function markSnapshotTaken() {
        state.snapshotEpochMs = Date.now();
        refreshStaleness();
    }

    function formatAge(sec) {
        if (sec < 60) return `${sec}s`;
        const m = Math.floor(sec / 60);
        if (m < 60) return `${m}m ${sec % 60}s`;
        return `${Math.floor(m / 60)}h ${m % 60}m`;
    }

    function refreshStaleness() {
        if (!elements.stalenessBadge) return;
        if (!state.snapshotEpochMs) {
            elements.stalenessBadge.textContent = "\u25CF NO DATA";
            elements.stalenessBadge.className = "staleness-badge stale";
            setResultsStale(false);
            return;
        }
        const sec = Math.max(0, Math.round((Date.now() - state.snapshotEpochMs) / 1000));
        const age = formatAge(sec);
        if (sec < STALE_AGING_SEC) {
            elements.stalenessBadge.textContent = `\u25CF LIVE (${age} ago)`;
            elements.stalenessBadge.className = "staleness-badge fresh";
            setResultsStale(false);
        } else if (sec < STALE_OLD_SEC) {
            elements.stalenessBadge.textContent = `\u25CF AGING (${age} ago)`;
            elements.stalenessBadge.className = "staleness-badge aging";
            setResultsStale(false);
        } else {
            elements.stalenessBadge.textContent = `\u25CF STALE (${age} ago)`;
            elements.stalenessBadge.className = "staleness-badge stale";
            setResultsStale(true, age);
        }
    }

    function setResultsStale(isStale, age) {
        const banner = document.getElementById("results-stale-banner");
        if (!banner) return;
        banner.style.display = isStale ? "flex" : "none";
        if (isStale) {
            const label = document.getElementById("results-stale-text");
            if (label) label.textContent = `Priced on market data ${age} old — press F9 to reload and re-price.`;
        }
    }

    function renderMarketQuotes(quotes) {
        if (!elements.quoteTableBody || !quotes) return;
        elements.quoteTableBody.innerHTML = "";

        // Update Quick Stat Pill Rates
        if (state.currency === "KRW_CRS") {
            const spotVal = state.marketSnapshot && state.marketSnapshot.spot_fx ? state.marketSnapshot.spot_fx : 1373.50;
            elements.oisFixRate.textContent = `${spotVal.toFixed(2)}`;
            const q1y = quotes.find(q => q.tenor === "1Y");
            if (q1y) elements.ois1yRate.textContent = `${q1y.mid.toFixed(4)}%`;
            const q3y = quotes.find(q => q.tenor === "3Y");
            if (q3y) elements.ois3yRate.textContent = `${q3y.mid.toFixed(4)}%`;
            const q5y = quotes.find(q => q.tenor === "5Y");
            if (q5y) elements.ois5yRate.textContent = `${q5y.mid.toFixed(4)}%`;

            // Spot FX Top Row for CRS Market Table
            const trSpot = document.createElement("tr");
            trSpot.dataset.tenor = "SPOT_FX";
            trSpot.dataset.ric = "KRW=";
            trSpot.dataset.mid = spotVal;
            trSpot.style.backgroundColor = "#f0fdf4";
            trSpot.innerHTML = `
                <td><strong style="color:var(--accent-blue);">Spot FX</strong></td>
                <td style="font-size:10px; color:var(--accent-blue); font-weight:700;">KRW=</td>
                <td class="num">${(spotVal - 0.20).toFixed(2)}</td>
                <td class="num">${(spotVal + 0.20).toFixed(2)}</td>
                <td class="num"><strong class="editable-rate" style="color:var(--accent-blue);">${spotVal.toFixed(2)}</strong></td>
                <td class="num" style="color:var(--text-muted); font-size:10px;">KRW</td>
            `;
            trSpot.addEventListener("click", () => openQuoteModal("SPOT_FX", "KRW=", spotVal));
            elements.quoteTableBody.appendChild(trSpot);

        } else {
            if (quotes.length > 0) {
                elements.oisFixRate.textContent = `${quotes[0].mid.toFixed(4)}%`;
            }
            const q1y = quotes.find(q => q.tenor === "1Y");
            if (q1y) elements.ois1yRate.textContent = `${q1y.mid.toFixed(4)}%`;
            const q3y = quotes.find(q => q.tenor === "3Y" || q.tenor === "2Y");
            if (q3y) elements.ois3yRate.textContent = `${q3y.mid.toFixed(4)}%`;
            const q5y = quotes.find(q => q.tenor === "5Y" || q.tenor === "3Y");
            if (q5y) elements.ois5yRate.textContent = `${q5y.mid.toFixed(4)}%`;
        }

        quotes.forEach(q => {
            const tr = document.createElement("tr");
            tr.dataset.tenor = q.tenor;
            tr.dataset.ric = q.ric;
            tr.dataset.mid = q.mid;

            const chgColor = q.chg_bp > 0 ? "color:#15803d; font-weight:700;" : q.chg_bp < 0 ? "color:#be123c; font-weight:700;" : "color:var(--text-muted);";
            const chgSign = q.chg_bp > 0 ? "+" : "";

            tr.innerHTML = `
                <td><strong>${q.tenor}</strong></td>
                <td style="font-size:10px; color:var(--text-secondary); font-weight:600;">${q.ric}</td>
                <td class="num">${q.bid ? q.bid.toFixed(4) : "-"}</td>
                <td class="num">${q.ask ? q.ask.toFixed(4) : "-"}</td>
                <td class="num"><strong class="editable-rate">${q.mid.toFixed(4)}</strong></td>
                <td class="num" style="${chgColor}">${chgSign}${q.chg_bp ? q.chg_bp.toFixed(2) : "0.00"}</td>
            `;

            tr.addEventListener("click", () => openQuoteModal(q.tenor, q.ric, q.mid));
            elements.quoteTableBody.appendChild(tr);
        });
    }

    function setTradePosition(pos) {
        if (elements.positionSelect) elements.positionSelect.value = pos;
        const isPay = (pos === "Pay Fixed");
        const isFixedFixed = (state.crsSwapType === "Fixed-Fixed");
        const l1Curr = (state.currency === "KRW_CRS") ? "KRW" : (state.currency.startsWith("KRW") ? "KRW" : "USD");
        const l2Curr = (state.currency === "KRW_CRS") ? "USD" : (state.currency.startsWith("KRW") ? "KRW" : "USD");

        if (isPay) {
            if (elements.btnPhasePay) elements.btnPhasePay.classList.add("active");
            if (elements.btnPhaseRec) elements.btnPhaseRec.classList.remove("active");
            if (elements.tagFixedLeg) elements.tagFixedLeg.textContent = `\u25B8 Leg 1 (Fixed / ${l1Curr}) [PAY]`;
            if (elements.tagFloatLeg) elements.tagFloatLeg.textContent = isFixedFixed ? `\u25B8 Leg 2 (Fixed / ${l2Curr}) [REC]` : `\u25B8 Leg 2 (Floating / ${l2Curr}) [REC]`;
        } else {
            if (elements.btnPhaseRec) elements.btnPhaseRec.classList.add("active");
            if (elements.btnPhasePay) elements.btnPhasePay.classList.remove("active");
            if (elements.tagFixedLeg) elements.tagFixedLeg.textContent = `\u25B8 Leg 1 (Fixed / ${l1Curr}) [REC]`;
            if (elements.tagFloatLeg) elements.tagFloatLeg.textContent = isFixedFixed ? `\u25B8 Leg 2 (Fixed / ${l2Curr}) [PAY]` : `\u25B8 Leg 2 (Floating / ${l2Curr}) [PAY]`;
        }

        const chkL1Pay = document.getElementById("chk-hdr-leg1-pay");
        const chkL1Rec = document.getElementById("chk-hdr-leg1-rec");
        const chkL2Pay = document.getElementById("chk-hdr-leg2-pay");
        const chkL2Rec = document.getElementById("chk-hdr-leg2-rec");
        if (chkL1Pay) chkL1Pay.checked = isPay;
        if (chkL1Rec) chkL1Rec.checked = !isPay;
        if (chkL2Pay) chkL2Pay.checked = !isPay;
        if (chkL2Rec) chkL2Rec.checked = isPay;
    }

    function renderCurveChart(pillars) {
        const canvas = elements.curveCanvas;
        if (!canvas || !pillars || pillars.length === 0) return;
        const ctx = canvas.getContext("2d");
        const w = canvas.width;
        const h = canvas.height;

        ctx.clearRect(0, 0, w, h);

        // Find min and max rates
        let minR = 999, maxR = -999;
        pillars.forEach(p => {
            const par = p.par_rate !== undefined ? p.par_rate : (p.rate !== undefined ? p.rate : 3.5);
            const zero = p.zero_rate !== undefined ? p.zero_rate : par;
            if (par < minR) minR = par;
            if (par > maxR) maxR = par;
            if (zero < minR) minR = zero;
            if (zero > maxR) maxR = zero;
        });

        const padTop = 8, padBottom = 8, padLeft = 32, padRight = 8;
        const plotW = w - padLeft - padRight;
        const plotH = h - padTop - padBottom;
        const rangeR = Math.max(0.4, (maxR - minR) * 1.15);
        const baseR = minR - (maxR - minR) * 0.08;

        // Draw Grid Lines (Crisp soft light borders)
        ctx.strokeStyle = "#e2e8f0";
        ctx.lineWidth = 1;
        for (let i = 0; i <= 2; i++) {
            const y = padTop + (plotH / 2) * i;
            ctx.beginPath();
            ctx.moveTo(padLeft, y);
            ctx.lineTo(w - padRight, y);
            ctx.stroke();

            const rVal = baseR + rangeR * (1 - i / 2);
            ctx.fillStyle = "#64748b";
            ctx.font = "bold 8px JetBrains Mono";
            ctx.fillText(`${rVal.toFixed(2)}%`, 2, y + 3);
        }

        // Draw Par Curve (Solid Ocean Blue)
        ctx.strokeStyle = "#0284c7";
        ctx.lineWidth = 2;
        ctx.beginPath();
        pillars.forEach((p, idx) => {
            const par = p.par_rate !== undefined ? p.par_rate : (p.rate !== undefined ? p.rate : 3.5);
            const x = padLeft + (plotW / (pillars.length - 1)) * idx;
            const y = padTop + plotH * (1 - (par - baseR) / rangeR);
            if (idx === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Draw Zero Curve (Dashed Warm Amber Orange)
        ctx.strokeStyle = "#d97706";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([3, 2]);
        ctx.beginPath();
        pillars.forEach((p, idx) => {
            const zero = p.zero_rate !== undefined ? p.zero_rate : (p.par_rate !== undefined ? p.par_rate : p.rate);
            const x = padLeft + (plotW / (pillars.length - 1)) * idx;
            const y = padTop + plotH * (1 - (zero - baseR) / rangeR);
            if (idx === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.setLineDash([]); // Reset dash
    }

    // --------------------------------------------------------------------------
    // 6. Pricing Calculation Engine
    // --------------------------------------------------------------------------
    async function calculatePricing() {
        if (state.currency === "USD_FWD") {
            return calculateFwdPricing();
        }
        try {
            elements.calcStatus.textContent = "Calculating...";
            elements.calcStatus.className = "calc-status-badge calc-loading";

            const notional = parseFormattedNumber(elements.notionalDisplay?.value || "100,000,000");
            const position = elements.positionSelect?.value || "Pay Fixed";
            const isCustomCoupon = elements.couponInput && elements.couponInput.dataset.userEdited === "true";
            const fixedCoupon = isCustomCoupon ? (parseFloat(elements.couponInput?.value) || 0.0) : null;
            const spreadBp = parseFloat(elements.spreadInput?.value) || 0.0;
            const tenor = (elements.customTenorInput?.value || state.selectedTenor || "1Y").trim();
            const effDate = elements.effectiveDateInput?.value || "";
            const matDate = elements.maturityDateInput?.value || "";

            const isCrs = state.currency === "KRW_CRS";
            const spotFx = isCrs ? (parseFormattedNumber(elements.capitalFxRate?.value) || 1375.75) : null;
            const usdNotional = isCrs ? notional : null;
            const krwNotional = isCrs ? parseFormattedNumber(elements.krwNotionalDisplay?.value) : null;

            // Independent Leg 1 (Fixed / KRW)
            const leg1DayCount = (elements.leg1DayCount || elements.paramDayCount)?.value || (state.currency === "USD" ? "Act/360" : (state.currency === "KRW_CRS" ? "30/360" : "Act/365"));
            const leg1Freq = (elements.leg1PaymentFreq || elements.paramPaymentFreq)?.value || (state.currency === "USD" ? "12M" : (state.currency === "KRW_CRS" ? "6M" : "3M"));
            const leg1FreqMonths = leg1Freq === "12M" ? 12 : leg1Freq === "6M" ? 6 : leg1Freq === "3M" ? 3 : 1;
            const leg1Conv = (elements.leg1Convention || elements.paramConvention)?.value || "Modified Following";
            const leg1Stub = (elements.leg1Stub || elements.paramStub)?.value || "Short in arrears";
            const leg1Adj = (elements.leg1Adjust || elements.paramAdjust)?.value || "Adjust";
            const leg1Cal = (elements.leg1PayCal || elements.paramPayCal)?.value || (state.currency === "USD" ? "NYB" : (state.currency === "KRW_CRS" ? "SEB_NYB" : "SEB"));

            // Independent Leg 2 (Floating / USD)
            const leg2DayCount = elements.leg2DayCount?.value || (state.currency === "USD" ? "Act/360" : (state.currency === "KRW_CRS" ? (state.crsSwapType === "Fixed-Fixed" ? "30/360" : "Act/360") : "Act/365"));
            const leg2Freq = elements.leg2PaymentFreq?.value || (state.currency === "USD" ? "12M" : (state.currency === "KRW_CRS" ? "6M" : "3M"));
            const leg2FreqMonths = leg2Freq === "12M" ? 12 : leg2Freq === "6M" ? 6 : leg2Freq === "3M" ? 3 : 1;
            const leg2Conv = elements.leg2Convention?.value || "Modified Following";
            const leg2Stub = elements.leg2Stub?.value || "Short in arrears";
            const leg2Adj = elements.leg2Adjust?.value || "Adjust";
            const leg2Cal = elements.leg2Cal?.value || (state.currency === "USD" ? "NYB" : (state.currency === "KRW_CRS" ? "SEB_NYB" : "SEB"));
            const fixDay = elements.paramFixDay?.value !== undefined ? (parseInt(elements.paramFixDay.value, 10) || 0) : -1;
            const fixCal = elements.paramFixCal?.value || (state.currency === "USD" ? "NYB" : (state.currency === "KRW_CRS" ? "SEB_NYB" : "SEB"));

            const usdFixedCoupon = parseFloat(elements.usdFixedCouponInput?.value) || 3.50;

            const payload = {
                currency: state.currency,
                notional: notional,
                usd_notional: usdNotional,
                krw_notional: krwNotional,
                spot_fx: spotFx,
                position: position,
                fixed_coupon_pct: fixedCoupon,
                spread_bp: spreadBp,
                tenor: tenor,
                effective_date: effDate || null,
                maturity_date: matDate || null,

                // Curve Model Selection & CRS Structure
                curve_type: state.curveType || "Standard",
                crs_swap_type: state.crsSwapType || "Vanilla",
                usd_fixed_coupon_pct: usdFixedCoupon,

                // Independent Leg 1
                leg1_day_count: leg1DayCount,
                leg1_payment_freq: leg1Freq,
                leg1_frequency_months: leg1FreqMonths,
                leg1_business_day_conv: leg1Conv,
                leg1_stub_rule: leg1Stub,
                leg1_adjust_rule: leg1Adj,
                leg1_calendar: leg1Cal,

                // Independent Leg 2
                leg2_day_count: leg2DayCount,
                leg2_payment_freq: leg2Freq,
                leg2_frequency_months: leg2FreqMonths,
                leg2_business_day_conv: leg2Conv,
                leg2_stub_rule: leg2Stub,
                leg2_adjust_rule: leg2Adj,
                leg2_calendar: leg2Cal,
                leg2_fix_day: fixDay,

                // Legacy Fallback fields
                day_count: leg1DayCount,
                fix_cal: fixCal,
                pay_cal: leg1Cal,
                payment_freq: leg1Freq,
                frequency_months: leg1FreqMonths,
                business_day_conv: leg1Conv,
                stub_rule: leg1Stub,
                adjust_rule: leg1Adj,
                fix_day: fixDay,
                payment_lag_bd: state.currency === "KRW_CRS" ? 2 : (state.currency === "KRW_KOFR" ? 2 : 0),
                custom_schedule: state.customSchedule,
                raw_paste_text: (elements.rcPasteInputLeg1 ? elements.rcPasteInputLeg1.value.trim() : "") || (elements.rcPasteInput ? elements.rcPasteInput.value.trim() : null),
                leg1_raw_paste_text: elements.rcPasteInputLeg1 ? elements.rcPasteInputLeg1.value.trim() : null,
                leg2_raw_paste_text: elements.rcPasteInputLeg2 ? elements.rcPasteInputLeg2.value.trim() : null
            };

            const endpoint = getPriceEndpoint();
            const resp = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            const json = await resp.json();
            if (json.status === "success") {
                state.pricingResult = json.data;
                // Auto populate Leg 1 Fixed Coupon with equilibrium Par swap rate (Deal NPV = 0)
                if (json.data && json.data.pricing_results) {
                    const pRate = (json.data.pricing_results.par_crs_rate_pct !== undefined)
                        ? json.data.pricing_results.par_crs_rate_pct
                        : json.data.pricing_results.par_swap_rate_pct;
                    if (pRate !== undefined && elements.couponInput && elements.couponInput.dataset.userEdited !== "true") {
                        elements.couponInput.value = Number(pRate).toFixed(6);
                    }
                }
                renderPricingResults(json.data);
                renderSchedules(json.data.schedules, json.data.principal_flows);
                if (typeof updateActiveTicketPricingResult === "function") {
                    updateActiveTicketPricingResult(json.data, state.marketSnapshot?.timestamp);
                }
                elements.calcStatus.textContent = "Pricing Ready";
                elements.calcStatus.className = "calc-status-badge calc-ready";

                const rcL1 = elements.rcPasteInputLeg1 ? elements.rcPasteInputLeg1.value.trim() : (elements.rcPasteInput ? elements.rcPasteInput.value.trim() : "");
                const rcL2 = elements.rcPasteInputLeg2 ? elements.rcPasteInputLeg2.value.trim() : "";
                if (json.data && json.data.schedules) {
                    const countL1 = (json.data.schedules.leg1_fixed || json.data.schedules.leg1_schedule || []).length;
                    const countL2 = (json.data.schedules.leg2_floating || json.data.schedules.leg2_schedule || []).length;
                    
                    if (rcL1 && elements.rcStatusBadgeLeg1) {
                        elements.rcStatusBadgeLeg1.style.display = "inline-block";
                        if (elements.rcPeriodCountLeg1) elements.rcPeriodCountLeg1.textContent = `${countL1} Periods`;
                    } else if (elements.rcStatusBadgeLeg1) {
                        elements.rcStatusBadgeLeg1.style.display = "none";
                    }

                    if (rcL2 && elements.rcStatusBadgeLeg2) {
                        elements.rcStatusBadgeLeg2.style.display = "inline-block";
                        if (elements.rcPeriodCountLeg2) elements.rcPeriodCountLeg2.textContent = `${countL2} Periods`;
                    } else if (elements.rcStatusBadgeLeg2) {
                        elements.rcStatusBadgeLeg2.style.display = "none";
                    }

                    if ((rcL1 || rcL2) && elements.rcActiveSummary) {
                        elements.rcActiveSummary.style.display = "inline-block";
                        elements.rcActiveSummary.textContent = `\u2713 Marketer Schedule Active (${Math.max(countL1, countL2)} Periods)`;
                        if (elements.periodCountBadge) elements.periodCountBadge.textContent = `${Math.max(countL1, countL2)} Periods (Custom)`;
                    } else if (elements.rcActiveSummary) {
                        elements.rcActiveSummary.style.display = "none";
                    }
                }
            } else {
                throw new Error(json.detail || "Pricing calculation failed");
            }
        } catch (err) {
            console.error("Pricing error:", err);
            elements.calcStatus.textContent = "Error";
            elements.calcStatus.className = "calc-status-badge calc-offline";
            showToast(`Pricing error: ${err.message}`, "warning");
        }
    }

    async function reloadAndPrice() {
        if (state.currency === "USD_FWD") {
            return reloadAndPriceFwd();
        }
        try {
            elements.calcStatus.textContent = "Reload & Price...";
            elements.calcStatus.className = "calc-status-badge calc-loading";

            const notional = parseFormattedNumber(elements.notionalDisplay?.value || "100,000,000");
            const position = elements.positionSelect?.value || "Pay Fixed";
            const isCustomCoupon = elements.couponInput && elements.couponInput.dataset.userEdited === "true";
            const fixedCoupon = isCustomCoupon ? (parseFloat(elements.couponInput?.value) || 0.0) : null;
            const spreadBp = parseFloat(elements.spreadInput?.value) || 0.0;
            const tenor = (elements.customTenorInput?.value || state.selectedTenor || "1Y").trim();
            const effDate = elements.effectiveDateInput?.value || null;
            const matDate = elements.maturityDateInput?.value || null;

            const isCrs = state.currency === "KRW_CRS";
            const spotFx = isCrs ? (parseFormattedNumber(elements.capitalFxRate?.value) || 1375.75) : null;
            const usdNotional = isCrs ? notional : null;
            const krwNotional = isCrs ? parseFormattedNumber(elements.krwNotionalDisplay?.value) : null;

            // Independent Leg 1 (Fixed / KRW)
            const leg1DayCount = (elements.leg1DayCount || elements.paramDayCount)?.value || (state.currency === "USD" ? "Act/360" : (state.currency === "KRW_CRS" ? "30/360" : "Act/365"));
            const leg1Freq = (elements.leg1PaymentFreq || elements.paramPaymentFreq)?.value || (state.currency === "USD" ? "12M" : (state.currency === "KRW_CRS" ? "6M" : "3M"));
            const leg1FreqMonths = leg1Freq === "12M" ? 12 : leg1Freq === "6M" ? 6 : leg1Freq === "3M" ? 3 : 1;
            const leg1Conv = (elements.leg1Convention || elements.paramConvention)?.value || "Modified Following";
            const leg1Stub = (elements.leg1Stub || elements.paramStub)?.value || "Short in arrears";
            const leg1Adj = (elements.leg1Adjust || elements.paramAdjust)?.value || "Adjust";
            const leg1Cal = (elements.leg1PayCal || elements.paramPayCal)?.value || (state.currency === "USD" ? "NYB" : (state.currency === "KRW_CRS" ? "SEB_NYB" : "SEB"));

            // Independent Leg 2 (Floating / USD)
            const leg2DayCount = elements.leg2DayCount?.value || (state.currency === "USD" ? "Act/360" : (state.currency === "KRW_CRS" ? (state.crsSwapType === "Fixed-Fixed" ? "30/360" : "Act/360") : "Act/365"));
            const leg2Freq = elements.leg2PaymentFreq?.value || (state.currency === "USD" ? "12M" : (state.currency === "KRW_CRS" ? "6M" : "3M"));
            const leg2FreqMonths = leg2Freq === "12M" ? 12 : leg2Freq === "6M" ? 6 : leg2Freq === "3M" ? 3 : 1;
            const leg2Conv = elements.leg2Convention?.value || "Modified Following";
            const leg2Stub = elements.leg2Stub?.value || "Short in arrears";
            const leg2Adj = elements.leg2Adjust?.value || "Adjust";
            const leg2Cal = elements.leg2Cal?.value || (state.currency === "USD" ? "NYB" : (state.currency === "KRW_CRS" ? "SEB_NYB" : "SEB"));
            const fixDay = elements.paramFixDay?.value !== undefined ? (parseInt(elements.paramFixDay.value, 10) || 0) : -1;
            const fixCal = elements.paramFixCal?.value || (state.currency === "USD" ? "NYB" : (state.currency === "KRW_CRS" ? "SEB_NYB" : "SEB"));

            const usdFixedCoupon = parseFloat(elements.usdFixedCouponInput?.value) || 3.50;

            const payload = {
                currency: state.currency,
                notional: notional,
                usd_notional: usdNotional,
                krw_notional: krwNotional,
                spot_fx: spotFx,
                position: position,
                fixed_coupon_pct: null, // Initial reload pricing auto-calculates at Par swap rate (Deal NPV = 0)
                spread_bp: spreadBp,
                tenor: tenor,
                effective_date: effDate || null,
                maturity_date: matDate || null,

                // Curve Model Selection & CRS Structure
                curve_type: state.curveType || "Standard",
                crs_swap_type: state.crsSwapType || "Vanilla",
                usd_fixed_coupon_pct: usdFixedCoupon,

                // Independent Leg 1
                leg1_day_count: leg1DayCount,
                leg1_payment_freq: leg1Freq,
                leg1_frequency_months: leg1FreqMonths,
                leg1_business_day_conv: leg1Conv,
                leg1_stub_rule: leg1Stub,
                leg1_adjust_rule: leg1Adj,
                leg1_calendar: leg1Cal,

                // Independent Leg 2
                leg2_day_count: leg2DayCount,
                leg2_payment_freq: leg2Freq,
                leg2_frequency_months: leg2FreqMonths,
                leg2_business_day_conv: leg2Conv,
                leg2_stub_rule: leg2Stub,
                leg2_adjust_rule: leg2Adj,
                leg2_calendar: leg2Cal,
                leg2_fix_day: fixDay,

                // Legacy Fallback fields
                day_count: leg1DayCount,
                fix_cal: fixCal,
                pay_cal: leg1Cal,
                payment_freq: leg1Freq,
                frequency_months: leg1FreqMonths,
                business_day_conv: leg1Conv,
                stub_rule: leg1Stub,
                adjust_rule: leg1Adj,
                fix_day: fixDay,
                payment_lag_bd: state.currency === "KRW_CRS" ? 2 : (state.currency === "KRW_KOFR" ? 2 : 0),
                custom_schedule: state.customSchedule,
                raw_paste_text: (elements.rcPasteInputLeg1 ? elements.rcPasteInputLeg1.value.trim() : "") || (elements.rcPasteInput ? elements.rcPasteInput.value.trim() : null),
                leg1_raw_paste_text: elements.rcPasteInputLeg1 ? elements.rcPasteInputLeg1.value.trim() : null,
                leg2_raw_paste_text: elements.rcPasteInputLeg2 ? elements.rcPasteInputLeg2.value.trim() : null
            };

            const endpoint = getReloadAndPriceEndpoint();
            const resp = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            const json = await resp.json();
            if (json.status === "success") {
                // Update Market Snapshot & Curve
                const snap = json.market_snapshot || json;
                state.marketSnapshot = snap;
                state.curvePillars = snap.curve_pillars || [];
                renderMarketQuotes(snap.quotes);
                renderCurveChart(snap.curve_pillars);

                // F9 just pulled fresh quotes, so restart the staleness clock - otherwise
                // the header keeps ageing from the last plain snapshot load and the
                // "priced on stale data" banner never clears.
                if (snap.timestamp && elements.snapshotTimestamp) {
                    elements.snapshotTimestamp.textContent = snap.timestamp.split(" ")[1] || "--:--:--";
                }
                markSnapshotTaken();

                // Update Settle Date if provided
                if (snap.settle_date) {
                    elements.lblEffectiveDate.textContent = `Effective Date (Settle: ${snap.settle_date})`;
                }

                // Update Pricing Results & Schedules
                const pricing = json.data || json.pricing;
                if (pricing) {
                    state.pricingResult = pricing;
                    // Auto populate Leg 1 Fixed Coupon with equilibrium Par swap rate (Deal NPV = 0)
                    if (pricing.pricing_results) {
                        const pRate = (pricing.pricing_results.par_crs_rate_pct !== undefined)
                            ? pricing.pricing_results.par_crs_rate_pct
                            : pricing.pricing_results.par_swap_rate_pct;
                        if (pRate !== undefined && elements.couponInput) {
                            elements.couponInput.value = Number(pRate).toFixed(6);
                            elements.couponInput.dataset.userEdited = "";
                        }
                    }
                    renderPricingResults(pricing);
                    renderSchedules(pricing.schedules, pricing.principal_flows);
                    if (typeof updateActiveTicketPricingResult === "function") {
                        updateActiveTicketPricingResult(pricing, snap.timestamp);
                    }
                }

                elements.calcStatus.textContent = "Pricing Ready";
                elements.calcStatus.className = "calc-status-badge calc-ready";
                showToast(`[F9] Reloaded latest market data and calculated pricing`, "success");

                const rcL1 = elements.rcPasteInputLeg1 ? elements.rcPasteInputLeg1.value.trim() : (elements.rcPasteInput ? elements.rcPasteInput.value.trim() : "");
                const rcL2 = elements.rcPasteInputLeg2 ? elements.rcPasteInputLeg2.value.trim() : "";
                if (pricing && pricing.schedules) {
                    const countL1 = (pricing.schedules.leg1_fixed || pricing.schedules.leg1_schedule || []).length;
                    const countL2 = (pricing.schedules.leg2_floating || pricing.schedules.leg2_schedule || []).length;
                    
                    if (rcL1 && elements.rcStatusBadgeLeg1) {
                        elements.rcStatusBadgeLeg1.style.display = "inline-block";
                        if (elements.rcPeriodCountLeg1) elements.rcPeriodCountLeg1.textContent = `${countL1} Periods`;
                    } else if (elements.rcStatusBadgeLeg1) {
                        elements.rcStatusBadgeLeg1.style.display = "none";
                    }

                    if (rcL2 && elements.rcStatusBadgeLeg2) {
                        elements.rcStatusBadgeLeg2.style.display = "inline-block";
                        if (elements.rcPeriodCountLeg2) elements.rcPeriodCountLeg2.textContent = `${countL2} Periods`;
                    } else if (elements.rcStatusBadgeLeg2) {
                        elements.rcStatusBadgeLeg2.style.display = "none";
                    }

                    if ((rcL1 || rcL2) && elements.rcActiveSummary) {
                        elements.rcActiveSummary.style.display = "inline-block";
                        elements.rcActiveSummary.textContent = `\u2713 Marketer Schedule Active (${Math.max(countL1, countL2)} Periods)`;
                        if (elements.periodCountBadge) elements.periodCountBadge.textContent = `${Math.max(countL1, countL2)} Periods (Custom)`;
                    } else if (elements.rcActiveSummary) {
                        elements.rcActiveSummary.style.display = "none";
                    }
                }
            } else {
                elements.calcStatus.textContent = "Error";
                elements.calcStatus.className = "calc-status-badge calc-offline";
                showToast(`[F9] Reload & Pricing failed`, "warning");
            }
        } catch (err) {
            console.error("One-shot error:", err);
            elements.calcStatus.textContent = "Error";
            elements.calcStatus.className = "calc-status-badge calc-offline";
            showToast(`One-shot error: ${err.message}`, "warning");
        }
    }

    function renderPricingResults(data) {
        if (!data || !data.pricing_results) return;
        const res = data.pricing_results;
        const isKrw = state.currency.startsWith("KRW");
        const isCrs = state.currency === "KRW_CRS";

        // Par Rate
        const isFixedFixed = isCrs && state.crsSwapType === "Fixed-Fixed";
        if (isFixedFixed) {
            if (elements.lblHeroPar) elements.lblHeroPar.textContent = "Par KRW Rate (given USD Cpn)";
            const parKrw = res.par_krw_rate_pct !== undefined ? res.par_krw_rate_pct : (res.par_crs_rate_pct || 0.0);
            elements.resParRate.innerHTML = `${parKrw.toFixed(6)} <span class="unit">%</span>`;

            if (elements.resParSecondary) {
                const parUsd = res.par_usd_rate_pct !== undefined ? res.par_usd_rate_pct : 0.0;
                elements.resParSecondary.style.display = "block";
                elements.resParSecondary.innerHTML = `Par USD Rate: <strong>${parUsd.toFixed(6)}%</strong> (given KRW Cpn)`;
            }
        } else {
            if (elements.lblHeroPar) elements.lblHeroPar.textContent = isCrs ? "Par CRS Rate (Equilibrium)" : "Par Swap Rate (Equilibrium)";
            if (elements.resParSecondary) elements.resParSecondary.style.display = "none";
            const parVal = res.par_crs_rate_pct !== undefined ? res.par_crs_rate_pct : (res.par_swap_rate_pct !== undefined ? res.par_swap_rate_pct : 0.0);
            elements.resParRate.innerHTML = `${parVal.toFixed(6)} <span class="unit">%</span>`;
        }

        // Spread vs Coupon
        const sprdVal = res.spread_vs_coupon_bp !== undefined ? res.spread_vs_coupon_bp : 0.0;
        const sprdSign = sprdVal >= 0 ? "+" : "";
        elements.resSpreadVsCpn.textContent = `Spread vs Cpn: ${sprdSign}${sprdVal.toFixed(2)} bp`;
        elements.resSpreadVsCpn.style.color = sprdVal > 0 ? "#15803d" : sprdVal < 0 ? "#be123c" : "#475569";
        elements.resSpreadVsCpn.style.fontWeight = "700";

        // Deal NPV
        const dealNpvVal = res.deal_npv_krw !== undefined ? res.deal_npv_krw : (res.deal_npv !== undefined ? res.deal_npv : 0.0);
        elements.resDealNpv.textContent = formatCurrency(dealNpvVal, isKrw);
        elements.resDealNpv.style.color = dealNpvVal > 0 ? "#15803d" : dealNpvVal < 0 ? "#be123c" : "#0f172a";
        elements.resDealNpv.style.fontWeight = "800";
        
        if (isCrs) {
            const leg1Npv = res.leg1_npv_krw !== undefined ? res.leg1_npv_krw : (res.krw_leg_pv || 0);
            const leg2Npv = res.leg2_npv_usd !== undefined ? res.leg2_npv_usd : (res.usd_leg_pv || 0);
            elements.resPvBreakdown.textContent = `Leg 1 (KRW): ${formatCurrency(leg1Npv, true)} | Leg 2 (USD): ${formatCurrency(leg2Npv, false)}`;
        } else {
            elements.resPvBreakdown.textContent = `Fixed PV: ${formatCurrency(res.fixed_leg_pv, isKrw)} | Float PV: ${formatCurrency(res.float_leg_pv, isKrw)}`;
        }

        // DV01 / PV01 & Annuity
        const dv01Val = res.deal_pv01_krw !== undefined ? res.deal_pv01_krw : (res.krw_dv01 !== undefined ? res.krw_dv01 : (res.dv01 !== undefined ? res.dv01 : 0.0));
        const annuityVal = res.annuity_krw !== undefined ? res.annuity_krw : (res.annuity !== undefined ? res.annuity : 0.0);
        elements.resDv01.innerHTML = `${formatCurrency(dv01Val, isKrw)} <span class="unit">/ bp</span>`;
        elements.resAnnuity.textContent = isCrs ? `KRW BPV: ${formatCurrency(res.leg1_bpv_krw || 0, true)} | USD BPV: ${formatCurrency(res.leg2_bpv_usd || 0, false)}` : `Annuity: ${annuityVal.toFixed(6)}`;

        updateCurveModelBadge();

        // Key Rate Deltas.
        // For a CRS the dominant rate risk sits on the KRW CRS curve - the USD SOFR leg is
        // a par floater and barely moves - so lead with KRW and show USD underneath.
        const usdDeltas = data.delta_bucketing || data.key_rate_deltas;
        const krwDeltas = data.krw_key_rate_deltas;
        const hedgeDeltas = data.hedge_delta_bucketing || data.hedge_key_rate_deltas;
        const isAdvanced = (state.curveType || "").toLowerCase() === "advanced";

        let primary = usdDeltas;
        let primaryTitle = "Key Rate Delta Bucketing (1bp Shift Sensitivity)";
        let secondary = null;
        let secondaryTitle = "";
        let secondaryIsHedge = false;

        if (isCrs && krwDeltas && krwDeltas.length > 0) {
            primary = krwDeltas;
            primaryTitle = `Key Rate Delta &mdash; KRW CRS Curve ${chip("Primary Risk", "#0f766e", "#f0fdfa", "#99f6e4")}`;
            if (usdDeltas && usdDeltas.some(d => Math.abs(d.dv01 || 0) > 1)) {
                secondary = usdDeltas;
                secondaryTitle = "Key Rate Delta &mdash; USD SOFR Curve";
            } else if (isAdvanced && hedgeDeltas && hedgeDeltas.length > 0) {
                secondary = hedgeDeltas;
                secondaryTitle = "Hedge Curve Delta &mdash; USD SOFR";
                secondaryIsHedge = true;
            }
        } else if (isAdvanced && hedgeDeltas && hedgeDeltas.length > 0) {
            primaryTitle = `Key Rate Delta Bucketing ${chip("Advanced Spline (Global Ripple)", "#2563eb", "#eff6ff", "#bfdbfe")}`;
            secondary = hedgeDeltas;
            secondaryTitle = "Hedge Curve Delta Bucketing";
            secondaryIsHedge = true;
        }

        renderDeltaBars(primary, elements.deltaBarsContainer, false);
        if (elements.lblDeltaSectionTitle) {
            elements.lblDeltaSectionTitle.innerHTML = primaryTitle;
        }

        if (elements.hedgeDeltaSection) {
            if (secondary && secondary.length > 0) {
                elements.hedgeDeltaSection.style.display = "block";
                const lbl = document.getElementById("lbl-hedge-delta-title");
                if (lbl) lbl.innerHTML = secondaryTitle;
                renderDeltaBars(secondary, elements.hedgeDeltaBarsContainer, secondaryIsHedge);
            } else {
                elements.hedgeDeltaSection.style.display = "none";
            }
        }
    }

    // ---- Termsheet upload -------------------------------------------------
    // The document is parsed and redacted server-side and never stored. A ticket built
    // from it stays reviewState "pending" until the trader confirms, which gates F9.
    const ts = {
        zone: document.getElementById("termsheet-zone"),
        idle: document.getElementById("ts-idle"),
        input: document.getElementById("ts-file-input"),
        busy: document.getElementById("ts-busy"),
        busyText: document.getElementById("ts-busy-text"),
        cancel: document.getElementById("ts-cancel"),
        // Review popup
        backdrop: document.getElementById("ts-modal-backdrop"),
        file: document.getElementById("ts-modal-file"),
        close: document.getElementById("ts-modal-close"),
        model: document.getElementById("ts-modal-model"),
        redaction: document.getElementById("ts-redaction"),
        warnings: document.getElementById("ts-warnings"),
        groups: document.getElementById("ts-groups"),
        schedWrap: document.getElementById("ts-sched-wrap"),
        schedSummary: document.getElementById("ts-sched-summary"),
        questions: document.getElementById("ts-questions"),
        footNote: document.getElementById("ts-foot-note"),
        confirm: document.getElementById("ts-confirm"),
        discard: document.getElementById("ts-discard"),
    };
    let tsAbort = null;

    const TS_LABELS = {
        product: "상품", position: "포지션", notionalDisplay: "원금",
        customTenorInput: "만기(테너)", effectiveDate: "개시일", maturityDate: "만기일",
        coupon: "고정금리", spreadBp: "스프레드(bp)", crsSwapType: "CRS 유형",
        capitalFxRate: "환율", krwNotionalDisplay: "KRW 원금",
        leg1DayCount: "Leg1 이자계산", leg1PaymentFreq: "Leg1 지급주기",
        leg1Convention: "Leg1 영업일규칙", leg1Stub: "Leg1 스텁", leg1Adjust: "Leg1 조정",
        leg1PayCal: "Leg1 캘린더",
        leg2DayCount: "Leg2 이자계산", leg2PaymentFreq: "Leg2 지급주기",
        leg2Convention: "Leg2 영업일규칙", leg2Stub: "Leg2 스텁", leg2Adjust: "Leg2 조정",
        leg2Cal: "Leg2 캘린더", fixDay: "픽싱 오프셋", rawPasteText: "커스텀 스케줄",
    };
    // draft key -> the extractor's field name, so inferred/unverified flags line up
    const TS_FIELD_KEY = {
        notionalDisplay: "notional", customTenorInput: "tenor",
        effectiveDate: "effective_date", maturityDate: "maturity_date",
        coupon: "fixed_coupon_pct", spreadBp: "spread_bp", position: "position",
        leg1DayCount: "leg1_day_count", leg1PaymentFreq: "leg1_payment_freq",
        leg1Convention: "leg1_business_day_conv", leg1Stub: "leg1_stub_rule",
        leg1Adjust: "leg1_adjust_rule", leg1PayCal: "leg1_calendar",
        leg2DayCount: "leg2_day_count", leg2PaymentFreq: "leg2_payment_freq",
        leg2Convention: "leg2_business_day_conv", leg2Stub: "leg2_stub_rule",
        leg2Adjust: "leg2_adjust_rule", leg2Cal: "leg2_calendar",
    };

    function tsShow(which) {
        if (!ts.zone) return;
        if (ts.idle) ts.idle.hidden = which !== "idle";
        if (ts.busy) ts.busy.hidden = which !== "busy";
    }

    async function uploadTermsheet(file) {
        if (!file) return;
        if (!/\.pdf$/i.test(file.name)) {
            showToast("PDF 파일만 지원합니다", "warning");
            return;
        }
        tsShow("busy");
        if (ts.busyText) ts.busyText.textContent = `${file.name} 분석 중…`;

        const body = new FormData();
        body.append("file", file, file.name);
        tsAbort = new AbortController();

        try {
            const resp = await fetch("/api/termsheet/extract", {
                method: "POST", body, signal: tsAbort.signal,
            });
            const json = await resp.json();
            if (!resp.ok) {
                throw new Error(json.detail || `HTTP ${resp.status}`);
            }
            const data = json.data;
            if (!data.supported) {
                tsShow("idle");
                showToast(`평가 불가 상품: ${data.unsupported_reason}`, "warning");
                return;
            }
            renderTermsheetReview(data, file.name);
        } catch (err) {
            tsShow("idle");
            if (err.name !== "AbortError") {
                showToast(`Term Sheet 분석 실패: ${err.message}`, "warning");
            }
        } finally {
            tsAbort = null;
            if (ts.input) ts.input.value = "";
        }
    }

    // Review happens in a popup, and nothing reaches the dashboard until the trader
    // presses confirm. Holding the draft here rather than building a ticket up front
    // means a discarded term sheet leaves no trace in the workspace.
    let tsPending = null;

    const TS_GROUPS = [
        { title: "기본 조건", keys: [
            "product", "position", "notionalDisplay", "customTenorInput",
            "effectiveDate", "maturityDate", "coupon", "spreadBp",
            "crsSwapType", "capitalFxRate", "krwNotionalDisplay"] },
        { title: "Leg 1", keys: [
            "leg1DayCount", "leg1PaymentFreq", "leg1Convention",
            "leg1Stub", "leg1Adjust", "leg1PayCal"] },
        { title: "Leg 2", keys: [
            "leg2DayCount", "leg2PaymentFreq", "leg2Convention",
            "leg2Stub", "leg2Adjust", "leg2Cal", "fixDay"] },
    ];

    function renderTermsheetReview(data, fileName) {
        const draft = data.ticket_draft || {};
        const inferred = new Set(data.inferred_fields || []);
        const blocked = new Set(data.unverified_fields || []);
        const quotes = {};
        (data.provenance || []).forEach(p => { quotes[p.field] = p; });

        tsPending = { data: data, draft: draft, fileName: fileName, blocked: blocked };

        if (ts.file) ts.file.textContent = fileName;

        const counts = (data.redaction && data.redaction.counts) || {};
        const removed = Object.values(counts).reduce((a, b) => a + b, 0);
        if (ts.redaction) {
            ts.redaction.textContent = removed
                ? `민감정보 ${removed}건 제거 후 분석 · 원본 미저장`
                : "원본 미저장";
        }

        // Which vendor read the document. Different providers have different data
        // policies, so when failover sends it somewhere other than the configured
        // model, that is the trader's business, not a detail to bury in a log.
        const ex = data.extraction;
        if (ts.model) {
            ts.model.textContent = ex && ex.label ? ex.label : "";
            ts.model.className = "ts-model" + (ex && ex.fell_back ? " fell-back" : "");
            ts.model.title = ex && ex.fell_back
                ? `설정된 1차 프로바이더 대체 실행: ${(ex.attempts || [])
                    .map(a => `${a.label} ${a.reason}`).join(", ")}`
                : "";
        }

        // Cross-validation summary: what the two models disagreed on, how it was settled,
        // and which one was wrong - the provenance of a contested value, shown before it.
        const adj = data.adjudication;
        if (ts.redaction && adj) {
            const errs = Object.entries(adj.error_counts || {})
                .filter(([, n]) => n > 0)
                .map(([m, n]) => `${m} ${n}건`).join(", ");
            const settled = (adj.trail || []).filter(t => t.resolution !== "unresolved").length;
            ts.redaction.textContent +=
                ` · 교차검증 ${settled}/${(adj.trail || []).length}건 해결`
                + (errs ? ` (오류: ${errs})` : "");
        }

        renderTermsheetFieldGroups(draft, inferred, blocked, quotes);
        renderTermsheetSchedule(draft);

        const warns = (data.warnings || []).slice();
        if (ts.warnings) {
            ts.warnings.hidden = warns.length === 0;
            ts.warnings.innerHTML = "";
            warns.forEach(w => {
                const d = document.createElement("div");
                const settled = w.startsWith("재검토 합의") || w.startsWith("근거 판정");
                d.textContent = `${settled ? "\u2713" : "\u26A0"} ${w}`;
                if (settled) d.style.color = "#047857";
                ts.warnings.appendChild(d);
            });
        }

        const qs = data.open_questions || [];
        if (ts.questions) {
            ts.questions.hidden = qs.length === 0;
            ts.questions.innerHTML = "";
            if (qs.length) {
                const h = document.createElement("div");
                h.innerHTML = "<strong>카운터파티에 확인할 사항</strong>";
                ts.questions.appendChild(h);
                qs.forEach(q => {
                    const d = document.createElement("div");
                    d.textContent = `· ${q}`;
                    ts.questions.appendChild(d);
                });
            }
        }

        // A field whose quote could not be verified in the document is the one thing
        // that stops the draft going through unread.
        if (ts.confirm) {
            const hardBlocked = blocked.size > 0;
            ts.confirm.disabled = hardBlocked;
            ts.confirm.textContent = hardBlocked
                ? `근거 미확인 ${blocked.size}건 — 적용 불가`
                : "확인 · 대시보드에 적용";
        }
        if (ts.footNote) {
            ts.footNote.textContent = blocked.size
                ? "근거를 확인할 수 없는 항목이 있어 적용할 수 없습니다"
                : "확인하면 거래조건과 스케줄이 대시보드에 적용되고 바로 프라이싱됩니다";
        }

        openTermsheetModal();
    }

    function renderTermsheetFieldGroups(draft, inferred, blocked, quotes) {
        if (!ts.groups) return;
        ts.groups.innerHTML = "";
        TS_GROUPS.forEach(group => {
            const rows = group.keys.filter(k => draft[k] !== undefined && draft[k] !== "");
            if (!rows.length) return;

            const box = document.createElement("div");
            box.className = "ts-group";
            const head = document.createElement("div");
            head.className = "ts-group-title";
            head.textContent = group.title;
            box.appendChild(head);

            rows.forEach(key => {
                const srcKey = TS_FIELD_KEY[key] || key;
                let cls = "ok", note = "";
                if (blocked.has(srcKey)) {
                    cls = "blocked"; note = "근거 확인 실패 — 직접 확인 필요";
                } else if (inferred.has(srcKey)) {
                    cls = "inferred"; note = "문서에 없음 — 시장 관행 적용";
                } else if (quotes[srcKey] && quotes[srcKey].quote) {
                    note = quotes[srcKey].quote;
                }
                const row = document.createElement("div");
                row.className = `ts-row ${cls}`;
                row.innerHTML = '<span class="k"></span><span class="v"></span><span class="q"></span>';
                row.querySelector(".k").textContent = TS_LABELS[key] || key;
                row.querySelector(".v").textContent = draft[key];
                row.querySelector(".q").textContent = note;
                if (note) row.title = note;
                box.appendChild(row);
            });
            ts.groups.appendChild(box);
        });
    }

    function renderTermsheetSchedule(draft) {
        if (!ts.schedWrap) return;
        ts.schedWrap.innerHTML = "";
        const text = (draft.rawPasteText || "").trim();

        if (!text) {
            ts.schedWrap.innerHTML =
                '<div class="ts-sched-none">문서에 개별 스케줄이 없습니다 — '
                + '개시일·만기일과 지급주기로 표준 스케줄을 생성합니다</div>';
            if (ts.schedSummary) ts.schedSummary.textContent = "표준 스케줄";
            return;
        }

        const periods = parseClipboardScheduleText(text);
        const table = document.createElement("table");
        table.className = "ts-sched-table";
        table.innerHTML =
            "<thead><tr><th>#</th><th>시작일</th><th>종료일</th>"
            + '<th class="num">원금</th><th class="num">금리(%)</th></tr></thead>';
        const tb = document.createElement("tbody");
        let prevNotional = null;
        periods.forEach((p, i) => {
            const tr = document.createElement("tr");
            // Mark the steps, so an amortising or accreting profile is visible at a glance
            // rather than something the trader has to read down the column for.
            let step = "";
            if (prevNotional !== null && p.notional !== prevNotional) {
                step = p.notional < prevNotional ? " step-down" : " step-up";
            }
            prevNotional = p.notional;
            tr.innerHTML =
                `<td>${i + 1}</td><td>${p.start_date}</td><td>${p.end_date}</td>`
                + `<td class="num${step}">${formatNumberWithCommas(p.notional.toFixed(0))}</td>`
                + `<td class="num">${Number(p.fixed_rate_pct).toFixed(4)}</td>`;
            tb.appendChild(tr);
        });
        table.appendChild(tb);
        ts.schedWrap.appendChild(table);

        if (ts.schedSummary) {
            const first = periods.length ? periods[0].notional : 0;
            const last = periods.length ? periods[periods.length - 1].notional : 0;
            const shape = !periods.length ? ""
                : last < first ? "상각(Amortising)"
                : last > first ? "증가(Accreting)"
                : "원금 고정";
            const span = first === last
                ? formatNumberWithCommas(first.toFixed(0))
                : `${formatNumberWithCommas(first.toFixed(0))} → ${formatNumberWithCommas(last.toFixed(0))}`;
            ts.schedSummary.textContent = `${periods.length}개 기간 · ${shape} · ${span}`;
        }
    }

    function openTermsheetModal() {
        if (!ts.backdrop) return;
        ts.backdrop.style.display = "flex";
        tsShow("idle");
        if (ts.confirm && !ts.confirm.disabled) ts.confirm.focus();
    }

    function closeTermsheetModal() {
        if (ts.backdrop) ts.backdrop.style.display = "none";
        tsPending = null;
        tsShow("idle");
    }

    // The trader has read the popup: build the ticket, paint the dashboard, and price it
    // so the schedule they just approved is the one in the table at the bottom.
    function confirmTermsheetTicket() {
        if (!tsPending) return closeTermsheetModal();
        const data = tsPending.data, draft = tsPending.draft, fileName = tsPending.fileName;

        const targetCurrency = draft.product || "USD";
        if (state.currency !== targetCurrency) setCurrency(targetCurrency);

        const ticket = getDefaultTicketData(targetCurrency);
        Object.keys(draft).forEach(k => {
            if (draft[k] !== undefined && draft[k] !== "") ticket[k] = draft[k];
        });
        ticket.alias = `TS · ${draft.customTenorInput || ""} ${draft.position || ""}`.trim();
        ticket.reviewState = "confirmed";
        ticket.termsheetName = fileName;
        ticket.docSha256 = data.doc_sha256;
        ticket.termsheetEdits = [];
        ticket.termsheetDraft = JSON.parse(JSON.stringify(draft));

        if (!ticketsStore[targetCurrency]) ticketsStore[targetCurrency] = [];
        ticketsStore[targetCurrency].push(ticket);
        activeTicketIdByProduct[targetCurrency] = ticket.id;

        loadTicketToUI(ticket);
        if (draft.coupon !== undefined && draft.coupon !== "" && elements.couponInput) {
            elements.couponInput.dataset.userEdited = "true";
        }
        renderTicketBar();
        closeTermsheetModal();

        const n = (draft.rawPasteText || "").trim()
            ? parseClipboardScheduleText(draft.rawPasteText).length : 0;
        showToast(n
            ? `거래조건과 ${n}개 기간 스케줄 적용 — 프라이싱 중`
            : "거래조건 적용 — 프라이싱 중", "success");

        // Fills the schedule tables at the foot of the dashboard.
        calculatePricing();
    }

    function discardTermsheetTicket() {
        closeTermsheetModal();
        showToast("분석 결과를 폐기했습니다", "info");
    }

    function isAwaitingTermsheetReview() {
        return Boolean(tsPending);
    }

    if (ts.idle) {
        ts.idle.addEventListener("click", () => ts.input && ts.input.click());
        ["dragenter", "dragover"].forEach(ev =>
            ts.idle.addEventListener(ev, e => {
                e.preventDefault(); ts.idle.classList.add("dragover");
            }));
        ["dragleave", "drop"].forEach(ev =>
            ts.idle.addEventListener(ev, e => {
                e.preventDefault(); ts.idle.classList.remove("dragover");
            }));
        ts.idle.addEventListener("drop", e => {
            const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
            if (f) uploadTermsheet(f);
        });
    }
    if (ts.input) {
        ts.input.addEventListener("change", e => uploadTermsheet(e.target.files[0]));
    }
    if (ts.cancel) {
        ts.cancel.addEventListener("click", () => { if (tsAbort) tsAbort.abort(); tsShow("idle"); });
    }
    if (ts.confirm) ts.confirm.addEventListener("click", confirmTermsheetTicket);
    if (ts.discard) ts.discard.addEventListener("click", discardTermsheetTicket);
    if (ts.close) ts.close.addEventListener("click", discardTermsheetTicket);
    if (ts.backdrop) {
        ts.backdrop.addEventListener("click", e => {
            if (e.target === ts.backdrop) discardTermsheetTicket();
        });
    }
    document.addEventListener("keydown", e => {
        if (e.key === "Escape" && tsPending) discardTermsheetTicket();
    });

    // Say up front whether extraction can actually run, rather than failing on upload.
    (async function checkTermsheetReady() {
        if (!ts.idle) return;
        try {
            const r = await fetch("/api/termsheet/status");
            const d = (await r.json()).data || {};
            const note = ts.idle.querySelector(".ts-copy span");
            if (!d.ready) {
                ts.idle.classList.add("ts-unavailable");
                if (note) note.textContent = `분석 비활성 — ${d.reason || "API 키 미설정"}`;
            } else if (note) {
                note.textContent =
                    "PDF를 끌어다 놓거나 클릭해 선택 · 거래상대 정보는 제거 후 분석하며 원본은 저장하지 않습니다";
            }
        } catch (e) { /* status is advisory; upload still reports its own errors */ }
    })();

    function revealPasteCard() {
        const content = document.getElementById("paste-schedule-content");
        if (content) {
            content.classList.remove("collapsed");
            content.style.display = "block";
        }
        const icon = document.getElementById("paste-collapse-icon");
        if (icon) icon.textContent = "▾";
        // Expand only - scrolling here would pull the trader away from the review
        // panel they are meant to read first.
    }

    function chip(text, color, bg, border) {
        return `<span style="font-size:10px;font-weight:700;color:${color};background:${bg};` +
               `padding:2px 6px;border-radius:4px;border:1px solid ${border};margin-left:6px;">${text}</span>`;
    }

    function updateCurveModelBadge() {
        const el = document.getElementById("curve-model-badge");
        if (!el) return;
        const ct = (state.curveType || "Standard").toLowerCase();
        if (ct === "advanced") {
            el.textContent = "Advanced Hybrid";
            el.className = "curve-model-badge advanced";
            el.title = "Flat-forward below 2Y, log-cubic spline above, C1-blended at the 2Y junction";
        } else if (ct.indexOf("hedge") === 0) {
            el.textContent = "Hedge Curve";
            el.className = "curve-model-badge hedge";
            el.title = "Advanced pricing curve plus a localised zero-coupon hedge layer (Z^C = Z^P + Z^H)";
        } else {
            el.textContent = "Standard";
            el.className = "curve-model-badge";
            el.title = "Linear-on-zero-rate bootstrapped curve";
        }
    }

    function renderDeltaBars(bucketing, containerEl = elements.deltaBarsContainer, isHedgeCurve = false) {
        if (!containerEl || !bucketing) return;
        containerEl.innerHTML = "";
        const isKrw = state.currency.startsWith("KRW");

        // Calculate maximum absolute delta to scale the bars nicely
        let maxAbs = 1.0;
        bucketing.forEach(b => {
            const val = b.delta_dv01 !== undefined ? b.delta_dv01 : (b.dv01 !== undefined ? b.dv01 : (b.usd_delta_krw !== undefined ? b.usd_delta_krw : 0.0));
            if (Math.abs(val) > maxAbs) maxAbs = Math.abs(val);
        });

        bucketing.forEach(b => {
            const item = document.createElement("div");
            item.className = "delta-item";
            const val = b.delta_dv01 !== undefined ? b.delta_dv01 : (b.dv01 !== undefined ? b.dv01 : (b.usd_delta_krw !== undefined ? b.usd_delta_krw : 0.0));
            const tLabel = b.tenor || b.pillar;
            const isZero = Math.abs(val) < 0.001;
            const pct = Math.min(100, Math.max(isZero ? 0 : 1, (Math.abs(val) / maxAbs) * 100));
            const isNeg = val < 0;

            let fillClass = isNeg ? 'negative' : '';
            let customFillStyle = "";
            if (isHedgeCurve) {
                if (isNeg) {
                    customFillStyle = "background: linear-gradient(90deg, #f43f5e, #be123c);";
                } else if (isZero) {
                    customFillStyle = "background: transparent;";
                } else {
                    customFillStyle = "background: linear-gradient(90deg, #34d399, #059669);";
                }
            }

            let valStyle = "";
            if (isZero) {
                valStyle = "color: #94a3b8; font-weight: normal;";
            } else if (isNeg) {
                valStyle = "color: #be123c;";
            } else if (isHedgeCurve) {
                valStyle = "color: #047857;";
            }

            item.innerHTML = `
                <span class="delta-tenor">${tLabel}</span>
                <div class="delta-bar-track">
                    <div class="delta-bar-fill ${fillClass}" style="width:${pct.toFixed(1)}%; ${customFillStyle}"></div>
                </div>
                <span class="delta-val" style="${valStyle}">${formatCurrency(val, isKrw)}</span>
            `;
            containerEl.appendChild(item);
        });
    }

    // --------------------------------------------------------------------------
    // 7. Schedule Tables & Custom Paste Management
    // --------------------------------------------------------------------------
    // A schedule that arrives with a ticket - extracted from a term sheet, or a saved
    // ticket reopened - has to look as loaded as one the trader pasted by hand. These
    // badges are how they confirm the custom schedule is live before pressing F9;
    // until now they only appeared after a price, so a freshly extracted schedule sat
    // in the box looking inert.
    function reflectLoadedSchedule() {
        const l1 = elements.rcPasteInputLeg1 ? elements.rcPasteInputLeg1.value.trim() : "";
        const l2 = elements.rcPasteInputLeg2 ? elements.rcPasteInputLeg2.value.trim() : "";
        const p1 = l1 ? parseClipboardScheduleText(l1) : [];
        const p2 = l2 ? parseClipboardScheduleText(l2) : [];
        const n = Math.max(p1.length, p2.length);

        const setBadge = (badge, count, label) => {
            if (badge) badge.style.display = count ? "inline-block" : "none";
            if (label && count) label.textContent = `${count} Periods`;
        };
        setBadge(elements.rcStatusBadgeLeg1, p1.length, elements.rcPeriodCountLeg1);
        setBadge(elements.rcStatusBadgeLeg2, p2.length, elements.rcPeriodCountLeg2);

        if (elements.rcStatusBadge) elements.rcStatusBadge.style.display = n ? "inline-block" : "none";
        const pill = document.getElementById("rc-period-count-pill");
        if (pill) pill.style.display = n ? "inline-block" : "none";
        if (elements.rcPeriodCount && n) elements.rcPeriodCount.textContent = String(n);
        if (elements.rcActiveSummary) {
            elements.rcActiveSummary.style.display = n ? "inline-block" : "none";
            if (n) elements.rcActiveSummary.textContent = `✓ Custom Schedule Loaded (${n} Periods)`;
        }
        if (elements.periodCountBadge && n) {
            elements.periodCountBadge.textContent = `${n} Periods (Custom)`;
        }

        // Pricing sends the raw text and the server re-parses it, so this copy only
        // drives the schedule-mode indicator. Leave a schedule that came in by another
        // route alone when the boxes are empty.
        if (n) state.customSchedule = p1.length ? p1 : p2;
        updateScheduleModeUI();
    }

    function updateScheduleModeUI() {
        const isCustom = state.customSchedule !== null && state.customSchedule.length > 0;
        if (isCustom) {
            elements.scheduleModeBadge.textContent = `⚠ Custom (${state.customSchedule.length} Periods)`;
            elements.scheduleModeBadge.className = "schedule-mode-badge custom";
            elements.btnResetSchedule.style.display = "inline-flex";
        } else {
            elements.scheduleModeBadge.textContent = "\u2713 Auto Generated";
            elements.scheduleModeBadge.className = "schedule-mode-badge auto";
            elements.btnResetSchedule.style.display = "none";
        }
    }

    function formatMurexCellNpv(val, decimals = 6) {
        if (val === undefined || val === null || isNaN(val)) return "-";
        const num = Number(val);
        const formatted = formatNumberWithCommas(Math.abs(num).toFixed(decimals));
        if (num < -1e-9) {
            return `<span style="color:#dc2626; font-weight:700;">-${formatted}</span>`;
        } else if (num > 1e-9) {
            return `<span style="color:#0284c7; font-weight:700;">${formatted}</span>`;
        } else {
            return "-0." + "0".repeat(decimals);
        }
    }

    function bindHeaderCheckboxEvents() {
        const chkL1Pay = document.getElementById("chk-hdr-leg1-pay");
        const chkL1Rec = document.getElementById("chk-hdr-leg1-rec");
        const chkL2Pay = document.getElementById("chk-hdr-leg2-pay");
        const chkL2Rec = document.getElementById("chk-hdr-leg2-rec");

        if (chkL1Pay) {
            chkL1Pay.onchange = () => {
                setTradePosition(chkL1Pay.checked ? "Pay Fixed" : "Rec Fixed");
                saveActiveTicketFormData();
                calculatePricing();
            };
        }
        if (chkL1Rec) {
            chkL1Rec.onchange = () => {
                setTradePosition(chkL1Rec.checked ? "Rec Fixed" : "Pay Fixed");
                saveActiveTicketFormData();
                calculatePricing();
            };
        }
        if (chkL2Pay) {
            chkL2Pay.onchange = () => {
                setTradePosition(chkL2Pay.checked ? "Rec Fixed" : "Pay Fixed");
                saveActiveTicketFormData();
                calculatePricing();
            };
        }
        if (chkL2Rec) {
            chkL2Rec.onchange = () => {
                setTradePosition(chkL2Rec.checked ? "Pay Fixed" : "Rec Fixed");
                saveActiveTicketFormData();
                calculatePricing();
            };
        }
    }

    function renderScheduleHeaders() {
        const thead = document.getElementById("dual-schedule-thead");
        if (!thead) return;

        const isPayFixed = (elements.positionSelect?.value || "Pay Fixed") === "Pay Fixed";

        thead.innerHTML = `
            <tr class="murex-dual-header-top">
                <th colspan="8" class="murex-th-leg1-top">
                    <div class="murex-header-leg-box">
                        <div class="murex-pos-radios">
                            <label class="murex-chk-label">
                                <input type="checkbox" id="chk-hdr-leg1-pay" ${isPayFixed ? "checked" : ""}>
                                <span>Pay</span>
                            </label>
                            <label class="murex-chk-label">
                                <input type="checkbox" id="chk-hdr-leg1-rec" ${!isPayFixed ? "checked" : ""}>
                                <span>Receive</span>
                            </label>
                        </div>
                        <div class="murex-leg-title murex-title-leg1">Leg 1</div>
                    </div>
                </th>
                <th colspan="8" class="murex-th-leg2-top">
                    <div class="murex-header-leg-box">
                        <div class="murex-pos-radios">
                            <label class="murex-chk-label">
                                <input type="checkbox" id="chk-hdr-leg2-pay" ${!isPayFixed ? "checked" : ""}>
                                <span>Pay</span>
                            </label>
                            <label class="murex-chk-label">
                                <input type="checkbox" id="chk-hdr-leg2-rec" ${isPayFixed ? "checked" : ""}>
                                <span>Receive</span>
                            </label>
                        </div>
                        <div class="murex-leg-title murex-title-leg2">Leg 2</div>
                    </div>
                </th>
            </tr>
            <tr class="murex-dual-header-cols">
                <th class="col-center">Start date</th>
                <th class="col-center">End date</th>
                <th class="col-center">Pay date</th>
                <th class="num">Nominal</th>
                <th class="col-center">Fixing date</th>
                <th class="num">DF</th>
                <th class="num">Rate</th>
                <th class="num th-leg-divider">NPV</th>
                <th class="col-center">Start date</th>
                <th class="col-center">End date</th>
                <th class="col-center">Pay date</th>
                <th class="num">Nominal</th>
                <th class="col-center">Fixing date</th>
                <th class="num">DF</th>
                <th class="num">Rate</th>
                <th class="num">NPV</th>
            </tr>
        `;

        bindHeaderCheckboxEvents();
    }

    function renderSchedules(schedules, principalFlows) {
        if (!schedules) return;
        const isKrw = state.currency.startsWith("KRW");
        const isCrs = state.currency === "KRW_CRS";

        // Update Period Count Badge & Headers
        const count = schedules.dual_comparison ? schedules.dual_comparison.length : 0;
        elements.periodCountBadge.textContent = `${count} Periods`;
        updateScheduleModeUI();
        renderScheduleHeaders();

        // 1. Dual Comparison Table (Side-by-Side Dual Leg matching Murex capture)
        if (elements.dualTableBody) {
            elements.dualTableBody.innerHTML = "";
            const isPayFixed = (elements.positionSelect?.value || "Pay Fixed") === "Pay Fixed";
            const isMod = state.customSchedule !== null ? "cell-modified" : "";

            let periods = [];
            if (schedules.dual_comparison && schedules.dual_comparison.length > 0) {
                periods = schedules.dual_comparison;
            } else {
                // Fallback from leg1 and leg2
                const l1List = schedules.leg1_schedule || schedules.leg1_fixed || [];
                const l2List = schedules.leg2_schedule || schedules.leg2_floating || [];
                const maxL = Math.max(l1List.length, l2List.length);
                for (let i = 0; i < maxL; i++) {
                    const l1 = l1List[i] || {};
                    const l2 = l2List[i] || {};
                    periods.push({
                        start_date: l1.start_date || l2.start_date,
                        end_date: l1.end_date || l2.end_date,
                        pay_date: l1.pay_date || l2.pay_date,
                        fixing_date: l2.fixing_date,
                        notional: l1.notional || l2.notional,
                        nominal_krw: l1.nominal_krw,
                        nominal_usd: l2.nominal_usd,
                        df_krw: l1.discount_factor || l1.df,
                        df_usd: l2.discount_factor || l2.df,
                        discount_factor: l1.discount_factor || l2.discount_factor || l1.df || l2.df,
                        rate_krw_pct: l1.fixed_rate_pct || l1.rate,
                        rate_usd_pct: l2.fwd_sofr_pct || l2.fwd_cd_pct || l2.fwd_rate_pct || l2.rate,
                        fixed_rate_pct: l1.fixed_rate_pct || l1.rate,
                        fwd_sofr_pct: l2.fwd_sofr_pct || l2.fwd_cd_pct || l2.all_in_rate_pct || l2.rate,
                        fixed_pv: l1.present_value || l1.fixed_pv || 0,
                        float_pv: l2.present_value || l2.float_pv || 0,
                        npv_krw: l1.npv_krw || l1.present_value,
                        npv_usd: l2.npv_usd || l2.present_value
                    });
                }
            }

            let sumLeg1Npv = 0;
            let sumLeg2Npv = 0;

            periods.forEach(p => {
                const tr = document.createElement("tr");

                // Leg 1 Data
                const l1Start = p.start_date || "-";
                const l1End = p.end_date || "-";
                const l1Pay = p.pay_date || "-";
                const l1Nom = p.nominal_krw !== undefined ? p.nominal_krw : (p.nominal !== undefined ? p.nominal : (p.notional !== undefined ? p.notional : state.notional || 0));
                const l1NomStr = formatNumberWithCommas(Math.abs(l1Nom).toFixed(2));
                const l1Fixing = p.fixing_date_krw && p.fixing_date_krw !== "N/A" ? p.fixing_date_krw : "-";
                const l1DfVal = p.df_krw !== undefined ? p.df_krw : (p.df !== undefined ? p.df : (p.discount_factor !== undefined ? p.discount_factor : 1.0));
                const l1DfStr = Number(l1DfVal).toFixed(6);
                const l1RateVal = p.rate_krw_pct !== undefined ? p.rate_krw_pct : (p.fixed_rate_pct !== undefined ? p.fixed_rate_pct : (p.rate || 0.0));
                const l1RateStr = Number(l1RateVal).toFixed(6) + "%";
                
                // Leg 1 NPV (Negative if Pay, Positive if Receive)
                let l1NpvVal = 0;
                if (isCrs && p.npv_krw !== undefined) {
                    l1NpvVal = p.npv_krw;
                } else {
                    const basePv = p.fixed_pv !== undefined ? Math.abs(p.fixed_pv) : (p.present_value !== undefined ? Math.abs(p.present_value) : 0);
                    l1NpvVal = isPayFixed ? -basePv : basePv;
                }
                sumLeg1Npv += l1NpvVal;
                const l1NpvHtml = formatMurexCellNpv(l1NpvVal, 6);

                // Leg 2 Data
                const l2Start = p.start_date || "-";
                const l2End = p.end_date || "-";
                const l2Pay = p.pay_date || "-";
                const l2Nom = p.nominal_usd !== undefined ? p.nominal_usd : (p.nominal !== undefined ? p.nominal : (p.notional !== undefined ? p.notional : state.notional || 0));
                const l2NomStr = formatNumberWithCommas(Math.abs(l2Nom).toFixed(2));
                const l2Fixing = (p.fixing_date_usd || p.fixing_date) && (p.fixing_date_usd !== "N/A" && p.fixing_date !== "N/A") ? (p.fixing_date_usd || p.fixing_date) : "-";
                const l2DfVal = p.df_usd !== undefined ? p.df_usd : (p.df !== undefined ? p.df : (p.discount_factor !== undefined ? p.discount_factor : 1.0));
                const l2DfStr = Number(l2DfVal).toFixed(6);
                const l2RateVal = p.rate_usd_pct !== undefined ? p.rate_usd_pct : (p.fwd_cd_pct !== undefined ? p.fwd_cd_pct : (p.fwd_sofr_pct !== undefined ? p.fwd_sofr_pct : (p.fwd_kofr_pct !== undefined ? p.fwd_kofr_pct : (p.all_in_rate_pct !== undefined ? p.all_in_rate_pct : (p.fwd_rate_pct || 0.0)))));
                const l2RateStr = Number(l2RateVal).toFixed(6) + "%";

                // Leg 2 NPV (Positive if Receive, Negative if Pay)
                let l2NpvVal = 0;
                if (isCrs && p.npv_usd !== undefined) {
                    l2NpvVal = p.npv_usd;
                } else {
                    const basePv = p.float_pv !== undefined ? Math.abs(p.float_pv) : (p.present_value !== undefined ? Math.abs(p.present_value) : 0);
                    l2NpvVal = isPayFixed ? basePv : -basePv;
                }
                sumLeg2Npv += l2NpvVal;
                const l2NpvHtml = formatMurexCellNpv(l2NpvVal, 6);

                tr.innerHTML = `
                    <td class="col-center">${l1Start}</td>
                    <td class="col-center">${l1End}</td>
                    <td class="col-center"><strong>${l1Pay}</strong></td>
                    <td class="num ${isMod}">${l1NomStr}</td>
                    <td class="col-center">${l1Fixing}</td>
                    <td class="num">${l1DfStr}</td>
                    <td class="num ${isMod}"><strong>${l1RateStr}</strong></td>
                    <td class="num td-leg-divider"><strong>${l1NpvHtml}</strong></td>
                    <td class="col-center">${l2Start}</td>
                    <td class="col-center">${l2End}</td>
                    <td class="col-center"><strong>${l2Pay}</strong></td>
                    <td class="num ${isMod}">${l2NomStr}</td>
                    <td class="col-center">${l2Fixing}</td>
                    <td class="num">${l2DfStr}</td>
                    <td class="num ${isMod}"><strong>${l2RateStr}</strong></td>
                    <td class="num"><strong>${l2NpvHtml}</strong></td>
                `;
                elements.dualTableBody.appendChild(tr);
            });

            // If CRS Principal Flows exist, render Initial and Final principal exchanges
            if (isCrs && (principalFlows || schedules.principal_rows)) {
                const pRows = schedules.principal_rows || principalFlows;
                if (pRows && pRows.ini) {
                    const trIni = document.createElement("tr");
                    trIni.className = "row-principal row-principal-ini";
                    trIni.style.backgroundColor = "#f0fdf4";
                    trIni.style.borderTop = "1px dashed #059669";
                    
                    const iniNomKrw = formatNumberWithCommas(Math.abs(pRows.ini.nominal_krw || 0).toFixed(2));
                    const iniNomUsd = formatNumberWithCommas(Math.abs(pRows.ini.nominal_usd || 0).toFixed(2));
                    const iniNpvKrw = pRows.ini.npv_krw || 0;
                    const iniNpvUsd = pRows.ini.npv_usd || 0;
                    sumLeg1Npv += iniNpvKrw;
                    sumLeg2Npv += iniNpvUsd;

                    trIni.innerHTML = `
                        <td class="col-center">${pRows.ini.pay_date || "-"}</td>
                        <td class="col-center">${pRows.ini.pay_date || "-"}</td>
                        <td class="col-center"><strong>${pRows.ini.pay_date || "-"}</strong></td>
                        <td class="num">${iniNomKrw}</td>
                        <td class="col-center">-</td>
                        <td class="num">${Number(pRows.ini.df_krw || 1.0).toFixed(6)}</td>
                        <td class="num">-</td>
                        <td class="num td-leg-divider"><strong>${formatMurexCellNpv(iniNpvKrw, 6)}</strong></td>
                        <td class="col-center">${pRows.ini.pay_date || "-"}</td>
                        <td class="col-center">${pRows.ini.pay_date || "-"}</td>
                        <td class="col-center"><strong>${pRows.ini.pay_date || "-"}</strong></td>
                        <td class="num">${iniNomUsd}</td>
                        <td class="col-center">-</td>
                        <td class="num">${Number(pRows.ini.df_usd || 1.0).toFixed(6)}</td>
                        <td class="num">-</td>
                        <td class="num"><strong>${formatMurexCellNpv(iniNpvUsd, 6)}</strong></td>
                    `;
                    elements.dualTableBody.appendChild(trIni);
                }
                if (pRows && pRows.fin) {
                    const trFin = document.createElement("tr");
                    trFin.className = "row-principal row-principal-fin";
                    trFin.style.backgroundColor = "#fff1f2";
                    trFin.style.borderBottom = "1px dashed #e11d48";

                    const finNomKrw = formatNumberWithCommas(Math.abs(pRows.fin.nominal_krw || 0).toFixed(2));
                    const finNomUsd = formatNumberWithCommas(Math.abs(pRows.fin.nominal_usd || 0).toFixed(2));
                    const finNpvKrw = pRows.fin.npv_krw || 0;
                    const finNpvUsd = pRows.fin.npv_usd || 0;
                    sumLeg1Npv += finNpvKrw;
                    sumLeg2Npv += finNpvUsd;

                    trFin.innerHTML = `
                        <td class="col-center">${pRows.fin.pay_date || "-"}</td>
                        <td class="col-center">${pRows.fin.pay_date || "-"}</td>
                        <td class="col-center"><strong>${pRows.fin.pay_date || "-"}</strong></td>
                        <td class="num">${finNomKrw}</td>
                        <td class="col-center">-</td>
                        <td class="num">${Number(pRows.fin.df_krw || 1.0).toFixed(6)}</td>
                        <td class="num">-</td>
                        <td class="num td-leg-divider"><strong>${formatMurexCellNpv(finNpvKrw, 6)}</strong></td>
                        <td class="col-center">${pRows.fin.pay_date || "-"}</td>
                        <td class="col-center">${pRows.fin.pay_date || "-"}</td>
                        <td class="col-center"><strong>${pRows.fin.pay_date || "-"}</strong></td>
                        <td class="num">${finNomUsd}</td>
                        <td class="col-center">-</td>
                        <td class="num">${Number(pRows.fin.df_usd || 1.0).toFixed(6)}</td>
                        <td class="num">-</td>
                        <td class="num"><strong>${formatMurexCellNpv(finNpvUsd, 6)}</strong></td>
                    `;
                    elements.dualTableBody.appendChild(trFin);
                }
            }

            // Bottom Total Row
            const trTotal = document.createElement("tr");
            trTotal.className = "total-row";
            trTotal.innerHTML = `
                <td colspan="7" style="text-align:right; font-weight:700; color:#475569;">Total Leg 1:</td>
                <td class="num td-leg-divider"><strong style="font-size:12px;">${formatMurexCellNpv(sumLeg1Npv, 6)}</strong></td>
                <td colspan="7" style="text-align:right; font-weight:700; color:#475569;">Total Leg 2:</td>
                <td class="num"><strong style="font-size:12px;">${formatMurexCellNpv(sumLeg2Npv, 6)}</strong></td>
            `;
            elements.dualTableBody.appendChild(trTotal);
        }

        // 2. Leg 1 Fixed Table
        const leg1Data = schedules.leg1_schedule || schedules.leg1_fixed;
        if (elements.leg1TableBody && leg1Data) {
            elements.leg1TableBody.innerHTML = "";
            leg1Data.forEach(p => {
                const tr = document.createElement("tr");
                const isMod = state.customSchedule !== null ? "cell-modified" : "";
                const df = p.discount_factor !== undefined ? p.discount_factor : (p.df !== undefined ? p.df : 1.0);
                const pv = p.present_value !== undefined ? p.present_value : (p.npv !== undefined ? p.npv : 0.0);
                const cf = p.cash_flow !== undefined ? p.cash_flow : (p.flow !== undefined ? p.flow : 0.0);
                const notional = p.notional !== undefined ? p.notional : (p.nominal !== undefined ? p.nominal : 0.0);
                const frac = p.day_count_fraction !== undefined ? p.day_count_fraction : (p.fraction !== undefined ? p.fraction : 0.5);
                const rawRate = p.fixed_rate_pct !== undefined ? p.fixed_rate_pct : (p.rate_pct !== undefined ? p.rate_pct : (p.rate !== undefined ? p.rate : 0.0));
                const rate = parseFloat(rawRate) || 0.0;

                tr.innerHTML = `
                    <td class="col-center"><strong>P${p.period_no}</strong></td>
                    <td class="col-center">${p.start_date}</td>
                    <td class="col-center">${p.end_date}</td>
                    <td class="col-center"><strong>${p.pay_date}</strong></td>
                    <td class="num ${isMod}">${formatCurrency(notional, isKrw)}</td>
                    <td class="num">${frac.toFixed(6)}</td>
                    <td class="num ${isMod}"><strong>${rate.toFixed(6)}%</strong></td>
                    <td class="num">${formatCurrency(cf, isKrw)}</td>
                    <td class="num">${df.toFixed(6)}</td>
                    <td class="num"><strong>${formatCurrency(pv, isKrw)}</strong></td>
                `;
                elements.leg1TableBody.appendChild(tr);
            });
        }

        // 3. Leg 2 Floating Table
        const leg2Data = schedules.leg2_schedule || schedules.leg2_floating;
        if (elements.leg2TableBody && leg2Data) {
            elements.leg2TableBody.innerHTML = "";
            leg2Data.forEach(p => {
                const tr = document.createElement("tr");
                const rawFwd = p.fwd_sofr_pct !== undefined ? p.fwd_sofr_pct : (p.fwd_kofr_pct !== undefined ? p.fwd_kofr_pct : (p.fwd_cd_pct !== undefined ? p.fwd_cd_pct : (p.fwd_rate_pct !== undefined ? p.fwd_rate_pct : (p.rate !== undefined ? p.rate : 0.0))));
                const fwdVal = parseFloat(rawFwd) || 0.0;
                const df = p.discount_factor !== undefined ? p.discount_factor : (p.df !== undefined ? p.df : 1.0);
                const pv = p.present_value !== undefined ? p.present_value : (p.npv !== undefined ? p.npv : 0.0);
                const cf = p.cash_flow !== undefined ? p.cash_flow : (p.flow !== undefined ? p.flow : 0.0);
                const notional = p.notional !== undefined ? p.notional : (p.nominal !== undefined ? p.nominal : 0.0);
                const frac = p.day_count_fraction !== undefined ? p.day_count_fraction : (p.fraction !== undefined ? p.fraction : 0.5);
                const spread = p.spread_bp ? parseFloat(p.spread_bp) : 0.0;
                const allInRate = fwdVal + (spread / 100.0);

                tr.innerHTML = `
                    <td class="col-center"><strong>P${p.period_no}</strong></td>
                    <td class="col-center">${p.start_date}</td>
                    <td class="col-center">${p.end_date}</td>
                    <td class="col-center"><strong>${p.pay_date}</strong></td>
                    <td class="num">${formatCurrency(notional, isCrs ? false : isKrw)}</td>
                    <td class="num">${frac.toFixed(6)}</td>
                    <td class="num"><strong>${fwdVal.toFixed(6)}%</strong></td>
                    <td class="num">${spread.toFixed(2)}</td>
                    <td class="num"><strong>${allInRate.toFixed(6)}%</strong></td>
                    <td class="num">${formatCurrency(cf, isCrs ? false : isKrw)}</td>
                    <td class="num">${df.toFixed(6)}</td>
                    <td class="num"><strong>${formatCurrency(pv, isCrs ? false : isKrw)}</strong></td>
                `;
                elements.leg2TableBody.appendChild(tr);
            });
        }

        // 4. Murex Global View Table
        if (elements.murexTableBody && schedules.all_legs_murex) {
            elements.murexTableBody.innerHTML = "";
            schedules.all_legs_murex.forEach(p => {
                const tr = document.createElement("tr");
                const isKrwFlow = p.currency === "KRW";
                const remCapStr = formatNumberWithCommas(p.remaining_capital ? p.remaining_capital.toFixed(0) : "0");
                const rateStr = p.rate !== null && p.rate !== undefined ? `${p.rate.toFixed(6)}%` : "-";
                const marginStr = p.margin !== null && p.margin !== undefined ? p.margin.toFixed(6) : "-";
                const flowStr = formatAccounting(p.flow, isKrwFlow);

                tr.innerHTML = `
                    <td>${p.lg}</td>
                    <td><span class="badge-tag">${p.flow_tp}</span></td>
                    <td>${p.sub_tp || "-"}</td>
                    <td>${p.start_date}</td>
                    <td>${p.end_date}</td>
                    <td class="num">${remCapStr}</td>
                    <td>${p.first_fixing || "-"}</td>
                    <td>${p.last_fixing || "-"}</td>
                    <td class="num">${rateStr}</td>
                    <td class="num">${marginStr}</td>
                    <td><strong>${p.pay_date}</strong></td>
                    <td class="num">${flowStr}</td>
                    <td><strong>${p.currency}</strong></td>
                    <td>${p.index}</td>
                    <td class="num">${p.num_days || "-"}</td>
                `;
                elements.murexTableBody.appendChild(tr);
            });
        }

        // Auto-refresh Murex Global Evaluation Modal if open
        if (elements.evalModalBackdrop && elements.evalModalBackdrop.style.display !== "none") {
            renderEvaluationModal(activeEvalTab);
        }
    }

    // Schedule Tab Switching
    function switchScheduleTab(tabName) {
        if (!elements.tabButtons) return;
        elements.tabButtons.forEach(b => {
            if (b.dataset.tab === tabName) b.classList.add("active");
            else b.classList.remove("active");
        });
        if (elements.tabPanes) {
            elements.tabPanes.forEach(p => {
                if (p.id === `tab-pane-${tabName}`) p.classList.add("active");
                else p.classList.remove("active");
            });
        }
        state.activeScheduleTab = tabName;
        if (elements.waterfallContent && elements.waterfallContent.classList.contains("collapsed")) {
            elements.waterfallContent.classList.remove("collapsed");
            if (elements.collapseIcon) elements.collapseIcon.textContent = "\u25BE";
        }
        if (tabName === "fwd" && fwdPricingResult && fwdPricingResult.legs) {
            if (elements.periodCountBadge) elements.periodCountBadge.textContent = `${fwdPricingResult.legs.length} Far Legs`;
            if (elements.scheduleTitleText) elements.scheduleTitleText.textContent = "USD/KRW Forward Far Leg Schedule ('일중' 시트 매핑)";
        }
    }

    elements.tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            switchScheduleTab(btn.dataset.tab);
            if (btn.dataset.tab === "murex") {
                openEvaluationModal("all");
            }
        });
    });

    // --------------------------------------------------------------------------
    // Murex Global Evaluation Schedule Popup Modal System
    // Exact Replica of Desktop Murex Global Evaluation Schedule
    // --------------------------------------------------------------------------
    let activeEvalTab = "all";

    function formatMurexEvalDate(dateStr) {
        if (!dateStr || dateStr === "N/A") return "-";
        const parts = String(dateStr).trim().split("-");
        if (parts.length === 3) {
            const y = parts[0];
            const mIdx = parseInt(parts[1], 10) - 1;
            const d = parts[2];
            const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
            const m = monthNames[mIdx] || parts[1];
            return `${y} ${m} ${d}`;
        }
        return dateStr;
    }

    function formatMurexNumber(val, decimals = 6) {
        if (val === null || val === undefined || isNaN(val)) return "-";
        if (Math.abs(val) < 1e-9) {
            return "-0." + "0".repeat(decimals);
        }
        return Number(val).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    }

    function renderEvaluationModal(activeTab = "all") {
        activeEvalTab = activeTab;
        if (!elements.evalTableBody) return;
        elements.evalTableBody.innerHTML = "";

        // Update tab buttons
        if (elements.evalTabs) {
            elements.evalTabs.forEach(b => {
                if (b.dataset.evalTab === activeTab) b.classList.add("active");
                else b.classList.remove("active");
            });
        }

        // Subbar text
        if (elements.evalModalSubbar) {
            if (activeTab === "leg1") elements.evalModalSubbar.textContent = "Leg 1 view";
            else if (activeTab === "leg2") elements.evalModalSubbar.textContent = "Leg 2 view";
            else elements.evalModalSubbar.textContent = "Aggregated view";
        }

        if (!state.pricingResult || !state.pricingResult.schedules) {
            elements.evalTableBody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align:center;padding:36px 16px;color:#64748b;font-weight:600;">
                        No pricing evaluation schedule available.<br>
                        <span style="font-size:11px;font-weight:400;color:#94a3b8;">Please perform a pricing calculation (press F9 or click Calculate Pricing) first.</span>
                    </td>
                </tr>
            `;
            if (elements.evalTotalFlow) elements.evalTotalFlow.textContent = "-";
            if (elements.evalTotalDiscFlow) elements.evalTotalDiscFlow.textContent = "-";
            return;
        }

        const res = state.pricingResult;
        const sched = res.schedules || {};
        const dual = sched.dual_comparison || [];
        const leg1 = sched.leg1_fixed || sched.leg1_schedule || [];
        const leg2 = sched.leg2_floating || sched.leg2_schedule || [];
        const tradeInfo = res.trade_info || {};
        const pricingRes = res.pricing_results || {};

        // Accurate position sign inspection: "Pay Fixed" / "Pay" vs "Rec Fixed" / "Receive"
        const posStr = String(tradeInfo.position || elements.positionSelect?.value || "Pay Fixed").toLowerCase();
        const isPayFixed = posStr.includes("pay") || tradeInfo.is_pay_fixed === true;
        const curr = tradeInfo.currency || state.currency || "KRW";

        if (elements.evalInfoTradeTag) {
            let tag = curr;
            if (curr === "KRW") tag = "KRW CD IRS";
            else if (curr === "USD") tag = "USD SOFR OIS";
            else if (curr === "KRW_KOFR") tag = "KRW KOFR OIS";
            else if (curr === "KRW_CRS") tag = "USD/KRW CRS";
            elements.evalInfoTradeTag.textContent = tag;
        }
        if (elements.evalInfoNpv) {
            const npvVal = pricingRes.deal_npv !== undefined ? pricingRes.deal_npv : (pricingRes.deal_npv_krw !== undefined ? pricingRes.deal_npv_krw : 0);
            elements.evalInfoNpv.textContent = formatMurexNumber(npvVal, 6);
        }
        if (elements.evalInfoTenor) {
            elements.evalInfoTenor.textContent = tradeInfo.tenor || state.selectedTenor || "-";
        }

        const isCrs = curr === "KRW_CRS";
        const rowsLeg1 = [];
        const rowsLeg2 = [];

        if (dual.length > 0) {
            dual.forEach(p => {
                const dateStr = p.pay_date || p.end_date;
                const evalDate = formatMurexEvalDate(dateStr);
                const df = p.discount_factor !== undefined ? p.discount_factor : 1.0;

                // Leg 1 (Fixed)
                const cf1 = (p.fixed_cf !== undefined) ? p.fixed_cf : (p.cash_flow || 0);
                const pv1 = (p.fixed_pv !== undefined) ? p.fixed_pv : (p.present_value || 0);
                const sign1 = isPayFixed ? -1 : 1;
                const flow1 = sign1 * Math.abs(cf1);
                const discFlow1 = sign1 * Math.abs(pv1);
                const cur1 = isCrs ? "KRW" : curr;

                rowsLeg1.push({
                    lg: 1,
                    evalDate: evalDate,
                    rawDate: dateStr,
                    flow: flow1,
                    df: df,
                    discFlow: discFlow1,
                    cur: cur1
                });

                // Leg 2 (Floating)
                const cf2 = (p.float_cf !== undefined) ? p.float_cf : (p.cash_flow || 0);
                const pv2 = (p.float_pv !== undefined) ? p.float_pv : (p.present_value || 0);
                const sign2 = isPayFixed ? 1 : -1;
                const flow2 = sign2 * Math.abs(cf2);
                const discFlow2 = sign2 * Math.abs(pv2);
                const cur2 = isCrs ? "USD" : curr;

                rowsLeg2.push({
                    lg: 2,
                    evalDate: evalDate,
                    rawDate: dateStr,
                    flow: flow2,
                    df: df,
                    discFlow: discFlow2,
                    cur: cur2
                });
            });
        } else if (leg1.length > 0 || leg2.length > 0) {
            leg1.forEach(p => {
                const dateStr = p.pay_date || p.end_date;
                const evalDate = formatMurexEvalDate(dateStr);
                const df = p.discount_factor !== undefined ? p.discount_factor : 1.0;
                const cf = p.cash_flow || 0;
                const pv = p.present_value || 0;
                const sign = isPayFixed ? -1 : 1;
                rowsLeg1.push({
                    lg: 1,
                    evalDate: evalDate,
                    rawDate: dateStr,
                    flow: sign * Math.abs(cf),
                    df: df,
                    discFlow: sign * Math.abs(pv),
                    cur: isCrs ? "KRW" : curr
                });
            });

            leg2.forEach(p => {
                const dateStr = p.pay_date || p.end_date;
                const evalDate = formatMurexEvalDate(dateStr);
                const df = p.discount_factor !== undefined ? p.discount_factor : 1.0;
                const cf = p.cash_flow || 0;
                const pv = p.present_value || 0;
                const sign = isPayFixed ? 1 : -1;
                rowsLeg2.push({
                    lg: 2,
                    evalDate: evalDate,
                    rawDate: dateStr,
                    flow: sign * Math.abs(cf),
                    df: df,
                    discFlow: sign * Math.abs(pv),
                    cur: isCrs ? "USD" : curr
                });
            });
        }

        let rowsToDisplay = [];
        if (activeTab === "leg1") {
            rowsToDisplay = rowsLeg1;
        } else if (activeTab === "leg2") {
            rowsToDisplay = rowsLeg2;
        } else {
            // "all" tab: All Leg 1 rows followed by All Leg 2 rows (exact Murex capture structure)
            rowsToDisplay = [...rowsLeg1, ...rowsLeg2];
        }

        let totalFlow = 0;
        let totalDiscFlow = 0;

        rowsToDisplay.forEach(item => {
            totalFlow += item.flow;
            totalDiscFlow += item.discFlow;

            const tr = document.createElement("tr");
            tr.addEventListener("click", () => {
                document.querySelectorAll("#eval-table-body tr").forEach(r => r.classList.remove("selected"));
                tr.classList.add("selected");
            });

            const flowStr = formatMurexNumber(item.flow, 6);
            const dfStr = Number(item.df).toFixed(6);
            const discFlowStr = formatMurexNumber(item.discFlow, 6);

            tr.innerHTML = `
                <td class="col-lg">${item.lg}</td>
                <td class="col-date">${item.evalDate}</td>
                <td class="col-num">${flowStr}</td>
                <td class="col-num">${dfStr}</td>
                <td class="col-num">${discFlowStr}</td>
                <td class="col-cur">${item.cur}</td>
            `;
            elements.evalTableBody.appendChild(tr);
        });

        // Recessed Total Boxes (Displayed to 6 decimals)
        if (elements.evalTotalFlow) {
            elements.evalTotalFlow.textContent = formatMurexNumber(totalFlow, 6);
        }
        if (elements.evalTotalDiscFlow) {
            elements.evalTotalDiscFlow.textContent = formatMurexNumber(totalDiscFlow, 6);
        }
    }

    function openEvaluationModal(tab = "all") {
        activeEvalTab = tab;
        renderEvaluationModal(activeEvalTab);
        if (elements.evalModalBackdrop) {
            elements.evalModalBackdrop.style.display = "flex";
            if (elements.evalModalWindow && !elements.evalModalWindow.classList.contains("maximized")) {
                elements.evalModalWindow.style.position = "";
                elements.evalModalWindow.style.left = "";
                elements.evalModalWindow.style.top = "";
                elements.evalModalWindow.style.margin = "";
            }
        }
    }

    function closeEvaluationModal() {
        if (elements.evalModalBackdrop) {
            elements.evalModalBackdrop.style.display = "none";
        }
    }

    function copyEvaluationScheduleToClipboard() {
        const table = document.getElementById("eval-schedule-table");
        if (!table) return;
        let tsv = "Lg\tEval Date\tFlow\tDisc Factor\tDiscounted Flow\tCur\n";
        const rows = table.querySelectorAll("#eval-table-body tr");
        rows.forEach(tr => {
            const cells = Array.from(tr.querySelectorAll("td")).map(td => td.textContent.trim());
            if (cells.length === 6) {
                tsv += cells.join("\t") + "\n";
            }
        });
        const totalFlow = elements.evalTotalFlow ? elements.evalTotalFlow.textContent.trim() : "";
        const totalDiscFlow = elements.evalTotalDiscFlow ? elements.evalTotalDiscFlow.textContent.trim() : "";
        tsv += `Total\t\t${totalFlow}\t\t${totalDiscFlow}\t\n`;
        navigator.clipboard.writeText(tsv).then(() => {
            showToast("Evaluation schedule copied to clipboard (Excel Ctrl+V)", "success");
        }).catch(() => {
            showToast("Failed to copy schedule", "warning");
        });
    }

    function makeModalDraggable(headerEl, modalEl) {
        if (!headerEl || !modalEl) return;
        let isDragging = false;
        let startX, startY, initialLeft, initialTop;

        headerEl.addEventListener("mousedown", (e) => {
            if (e.target.closest(".eval-win-btn")) return;
            if (modalEl.classList.contains("maximized")) return;
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            const rect = modalEl.getBoundingClientRect();
            initialLeft = rect.left;
            initialTop = rect.top;
            modalEl.style.position = "fixed";
            modalEl.style.margin = "0";
            modalEl.style.left = `${initialLeft}px`;
            modalEl.style.top = `${initialTop}px`;
            document.body.style.userSelect = "none";
        });

        document.addEventListener("mousemove", (e) => {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            modalEl.style.left = `${Math.max(10, initialLeft + dx)}px`;
            modalEl.style.top = `${Math.max(10, initialTop + dy)}px`;
        });

        document.addEventListener("mouseup", () => {
            isDragging = false;
            document.body.style.userSelect = "";
        });
    }

    // Bind Eval Modal Event Listeners
    if (elements.btnOpenEvalModal) {
        elements.btnOpenEvalModal.addEventListener("click", () => openEvaluationModal("all"));
    }
    if (elements.btnOpenEvalModalPane) {
        elements.btnOpenEvalModalPane.addEventListener("click", () => openEvaluationModal("all"));
    }
    if (elements.evalModalBtnClose) {
        elements.evalModalBtnClose.addEventListener("click", closeEvaluationModal);
    }
    if (elements.evalBtnCloseFooter) {
        elements.evalBtnCloseFooter.addEventListener("click", closeEvaluationModal);
    }
    if (elements.evalBtnCopy) {
        elements.evalBtnCopy.addEventListener("click", copyEvaluationScheduleToClipboard);
    }
    if (elements.evalModalBtnMax && elements.evalModalWindow) {
        elements.evalModalBtnMax.addEventListener("click", () => {
            elements.evalModalWindow.classList.toggle("maximized");
        });
    }
    if (elements.evalTabs) {
        elements.evalTabs.forEach(tabBtn => {
            tabBtn.addEventListener("click", () => {
                renderEvaluationModal(tabBtn.dataset.evalTab);
            });
        });
    }
    if (elements.evalModalBackdrop) {
        elements.evalModalBackdrop.addEventListener("click", (e) => {
            if (e.target === elements.evalModalBackdrop) {
                closeEvaluationModal();
            }
        });
    }
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && elements.evalModalBackdrop && elements.evalModalBackdrop.style.display !== "none") {
            closeEvaluationModal();
        }
    });

    makeModalDraggable(elements.evalModalHeader, elements.evalModalWindow);


    // --------------------------------------------------------------------------
    // 8. Excel Copy & Paste System
    // --------------------------------------------------------------------------
    function copyScheduleToClipboard() {
        const activeTab = state.activeScheduleTab || "dual";
        let activeTable = document.querySelector(`#tab-pane-${activeTab} table`);
        if (!activeTable) {
            showToast("No active table to copy", "warning");
            return;
        }

        const rows = activeTable.querySelectorAll("tr");
        let tsvText = "";

        rows.forEach(tr => {
            const cells = tr.querySelectorAll("th, td");
            const rowData = [];
            cells.forEach(c => {
                let cellText = c.innerText.trim().replace(/\r?\n/g, " ");
                rowData.push(cellText);
            });
            if (rowData.length > 0) {
                tsvText += rowData.join("\t") + "\n";
            }
        });

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(tsvText).then(() => {
                showToast("Schedule copied to clipboard! Paste directly into Excel (Ctrl + V)", "success");
            }).catch(err => {
                console.error("Clipboard error:", err);
                showToast("Clipboard copy failed, please check permissions", "warning");
            });
        } else {
            showToast("Clipboard API not supported in browser", "warning");
        }
    }

    if (elements.btnCopyExcel) {
        elements.btnCopyExcel.addEventListener("click", copyScheduleToClipboard);
    }

    function looksLikeScheduleDate(cell) {
        if (!cell) return false;
        const s = String(cell).trim();
        if (/^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$/.test(s)) return true;
        // A bare 8-digit run is only a date if it reads as one: 20000000 is a
        // notional, not the zeroth day of the zeroth month of the year 2000.
        return /^(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$/.test(s);
    }

    function parseClipboardScheduleText(text) {
        if (!text || !text.trim()) return [];
        const lines = text.trim().split(/\r?\n/);
        const parsedPeriods = [];
        const baseNotional = parseFormattedNumber(elements.notionalDisplay.value);
        const baseCoupon = parseFloat(elements.couponInput.value) || 3.5;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            if (!line) continue;

            // Split by Tab or Comma
            const cols = line.includes("\t") ? line.split("\t") : line.split(/[,;]/);
            const cleanCols = cols.map(c => c.trim().replace(/[$₩()]/g, ""));

            // Check if header row
            if (isNaN(parseInt(cleanCols[0].charAt(0))) && isNaN(Date.parse(cleanCols[0]))) {
                continue; // Skip header row
            }

            // Two shapes reach this box. The marketer's Excel carries a pay date,
            // [Start, End, Pay, Notional, Fixing]; a term sheet has none to carry,
            // [Start, End, Notional, Rate]. Tell them apart by whether the third
            // column is a date - counting columns gets it wrong either way.
            const hasPayCol = looksLikeScheduleDate(cleanCols[2]);
            const nomIdx = hasPayCol ? 3 : 2;

            let st = cleanCols[0];
            let ed = cleanCols[1] || st;
            let pay = hasPayCol ? cleanCols[2] : ed;
            let notional = cleanCols[nomIdx] ? parseFormattedNumber(cleanCols[nomIdx]) : baseNotional;
            let rate = baseCoupon;
            let spread = 0.0;
            // Whatever follows the notional may be a fixing date, a rate or a spread,
            // in any order. Classify by what it is, the way the pricing engine does.
            for (let c = nomIdx + 1; c < cleanCols.length; c++) {
                const cell = cleanCols[c];
                if (!cell || looksLikeScheduleDate(cell)) continue;
                const val = parseFloat(cell.replace(/,/g, "").replace("%", "").replace(/bp/i, ""));
                if (isNaN(val)) continue;
                if (/bp/i.test(cell) || Math.abs(val) > 25.0) spread = val;
                else rate = val;
            }

            // Normalize Date formats (YYYY-MM-DD)
            try {
                if (st.length === 8 && !st.includes("-")) {
                    st = `${st.substring(0,4)}-${st.substring(4,6)}-${st.substring(6,8)}`;
                }
                if (ed.length === 8 && !ed.includes("-")) {
                    ed = `${ed.substring(0,4)}-${ed.substring(4,6)}-${ed.substring(6,8)}`;
                }
                if (pay.length === 8 && !pay.includes("-")) {
                    pay = `${pay.substring(0,4)}-${pay.substring(4,6)}-${pay.substring(6,8)}`;
                }
            } catch (e) {}

            parsedPeriods.push({
                period_no: parsedPeriods.length + 1,
                start_date: st,
                end_date: ed,
                pay_date: pay,
                notional: notional > 0 ? notional : baseNotional,
                fixed_rate_pct: !isNaN(rate) ? rate : baseCoupon,
                spread_bp: !isNaN(spread) ? spread : 0.0
            });
        }
        return parsedPeriods;
    }

    // The schedule-paste modal was a second way to do what the always-visible
    // "Paste Excel Schedule" card already does; it has been removed.

    // Reset Custom Schedule back to Default Auto
    elements.btnResetSchedule.addEventListener("click", () => {
        state.customSchedule = null;
        updateScheduleModeUI();
        calculatePricing();
        showToast("Reset to auto-generated default schedule", "info");
    });

    // Marketer & Rollercoaster Quick Paste Controls
    const MARKETER_SAMPLE_SCHEDULE = `Start date\tEnd date\tPay date\tNominal\tFixing date
2025-08-06\t2025-09-06\t2025-09-08\t2,200,000,000\t2025-08-05
2025-09-06\t2025-10-06\t2025-10-10\t2,200,000,000\t2025-08-05
2025-10-06\t2025-11-06\t2025-11-06\t2,200,000,000\t2025-08-05
2025-11-06\t2025-12-06\t2025-12-08\t2,200,000,000\t2025-11-05
2025-12-06\t2026-01-06\t2026-01-06\t2,200,000,000\t2025-11-05
2026-01-06\t2026-02-06\t2026-02-06\t2,200,000,000\t2025-11-05
2026-02-06\t2026-03-06\t2026-03-06\t2,200,000,000\t2026-02-05
2026-03-06\t2026-04-06\t2026-04-06\t2,200,000,000\t2026-02-05
2026-04-06\t2026-05-06\t2026-05-06\t2,200,000,000\t2026-02-05
2026-05-06\t2026-06-06\t2026-06-08\t2,200,000,000\t2026-05-04
2026-06-06\t2026-07-06\t2026-07-06\t2,200,000,000\t2026-05-04
2026-07-06\t2026-08-03\t2026-08-03\t2,200,000,000\t2026-05-04`;

    if (elements.btnRcSample) {
        elements.btnRcSample.addEventListener("click", () => {
            if (elements.rcPasteInputLeg1) elements.rcPasteInputLeg1.value = MARKETER_SAMPLE_SCHEDULE;
            if (elements.rcPasteInputLeg2) elements.rcPasteInputLeg2.value = MARKETER_SAMPLE_SCHEDULE;
            if (elements.rcPasteInput) elements.rcPasteInput.value = MARKETER_SAMPLE_SCHEDULE;
            const pasteContent = document.getElementById("paste-schedule-content");
            if (pasteContent && pasteContent.classList.contains("collapsed")) {
                pasteContent.classList.remove("collapsed");
                pasteContent.style.display = "block";
                const icon = document.getElementById("paste-collapse-icon");
                if (icon) icon.textContent = "\u25BE";
            }
            if (elements.rcStatusBadge) elements.rcStatusBadge.style.display = "inline-block";
            const pill = document.getElementById("rc-period-count-pill");
            if (pill) pill.style.display = "inline-block";
            if (elements.rcPeriodCount) elements.rcPeriodCount.textContent = "12";
            showToast("Marketer 12-Period schedule (22억) loaded for Leg 1 & Leg 2. Pricing calculated.", "info");
            calculatePricing();
        });
    }

    // 1. Download Standard Excel Schedule Template
    if (elements.btnRcDownloadTemplate) {
        elements.btnRcDownloadTemplate.addEventListener("click", () => {
            downloadScheduleExcelTemplate();
        });
    }

    // 2. Upload Excel File to Populate Schedule
    if (elements.btnRcUploadBtn && elements.rcExcelFileInput) {
        elements.btnRcUploadBtn.addEventListener("click", () => {
            elements.rcExcelFileInput.value = "";
            elements.rcExcelFileInput.click();
        });

        elements.rcExcelFileInput.addEventListener("change", (e) => {
            const file = e.target.files && e.target.files[0];
            if (!file) return;
            handleScheduleExcelUpload(file);
        });
    }

    // 3. Holiday Sync via LSEG Workspace
    if (elements.btnSyncHolidaysLseg) {
        elements.btnSyncHolidaysLseg.addEventListener("click", async () => {
            const origText = elements.btnSyncHolidaysLseg.innerHTML;
            elements.btnSyncHolidaysLseg.innerHTML = "<span>⟳</span> 동기화 중...";
            elements.btnSyncHolidaysLseg.disabled = true;
            try {
                const resp = await fetch("/api/calendar/sync?source=lseg", { method: "POST" });
                const json = await resp.json();
                if (json.status === "success" && json.data && json.data.success) {
                    const d = json.data;
                    const seb = d.sync_details?.SEB?.total || "-";
                    const nyb = d.sync_details?.NYB?.total || "-";
                    const lnb = d.sync_details?.LNB?.total || "-";
                    const tkb = d.sync_details?.TKB?.total || "-";
                    const tgt = d.sync_details?.TGT?.total || "-";
                    showToast(`[LSEG 공휴일 동기화 완료]\n총 ${d.new_dates_added}개 신규 등록.\nSEB(KRW): ${seb}일 (대체공휴일 2027-10-12 정상 반영)\nNYB: ${nyb}일, LNB: ${lnb}일, TKB: ${tkb}일, TGT: ${tgt}일`, "success");
                } else {
                    showToast(`동기화 경고: ${json.data?.error || "응답 실패"}`, "warning");
                }
            } catch (err) {
                showToast(`동기화 오류: ${err.message}`, "error");
            } finally {
                elements.btnSyncHolidaysLseg.innerHTML = origText;
                elements.btnSyncHolidaysLseg.disabled = false;
            }
        });
    }

    // 4. Full-Width Paste Excel Schedule Collapse & Action Handlers
    const pasteScheduleToggle = document.getElementById("paste-schedule-toggle");
    const pasteScheduleContent = document.getElementById("paste-schedule-content");
    const pasteCollapseIcon = document.getElementById("paste-collapse-icon");

    if (pasteScheduleToggle && pasteScheduleContent) {
        pasteScheduleToggle.addEventListener("click", () => {
            const isCollapsed = pasteScheduleContent.classList.toggle("collapsed");
            if (isCollapsed) {
                pasteScheduleContent.style.display = "none";
                if (pasteCollapseIcon) pasteCollapseIcon.textContent = "\u25B8";
            } else {
                pasteScheduleContent.style.display = "block";
                if (pasteCollapseIcon) pasteCollapseIcon.textContent = "\u25BE";
            }
        });
    }

    const btnRcCalcNow = document.getElementById("btn-rc-calc-now");
    if (btnRcCalcNow) {
        btnRcCalcNow.addEventListener("click", () => {
            calculatePricing();
        });
    }

    function downloadScheduleExcelTemplate() {
        const headers = ["Start date", "End date", "Pay date", "Nominal", "Fixing date"];
        const rows = [
            ["2025-08-06", "2025-09-06", "2025-09-08", 2200000000, "2025-08-05"],
            ["2025-09-06", "2025-10-06", "2025-10-08", 2200000000, "2025-08-05"],
            ["2025-10-06", "2025-11-06", "2025-11-10", 2200000000, "2025-08-05"],
            ["2025-11-06", "2025-12-06", "2025-12-08", 2200000000, "2025-11-05"],
            ["2025-12-06", "2026-01-06", "2026-01-06", 2200000000, "2025-11-05"],
            ["2026-01-06", "2026-02-06", "2026-02-06", 2200000000, "2025-11-05"],
            ["2026-02-06", "2026-03-06", "2026-03-06", 2200000000, "2026-02-05"],
            ["2026-03-06", "2026-04-06", "2026-04-06", 2200000000, "2026-02-05"],
            ["2026-04-06", "2026-05-06", "2026-05-06", 2200000000, "2026-02-05"],
            ["2026-05-06", "2026-06-06", "2026-06-08", 2200000000, "2026-05-04"],
            ["2026-06-06", "2026-07-06", "2026-07-06", 2200000000, "2026-05-04"],
            ["2026-07-06", "2026-08-03", "2026-08-03", 2200000000, "2026-05-04"]
        ];

        if (typeof XLSX !== "undefined") {
            const aoa = [headers, ...rows];
            const ws = XLSX.utils.aoa_to_sheet(aoa);
            ws['!cols'] = [
                { wch: 14 },
                { wch: 14 },
                { wch: 14 },
                { wch: 18 },
                { wch: 14 }
            ];
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "Schedule_Template");
            XLSX.writeFile(wb, "KRW_IRS_Schedule_Template.xlsx");
            showToast("표준 엑셀 양식(KRW_IRS_Schedule_Template.xlsx) 다운로드 완료!", "success");
        } else {
            let csvContent = headers.join("\t") + "\n";
            rows.forEach(r => { csvContent += r.join("\t") + "\n"; });
            const blob = new Blob([csvContent], { type: "text/tab-separated-values;charset=utf-8;" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "KRW_IRS_Schedule_Template.txt";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            showToast("스케줄 양식 파일 다운로드 완료!", "success");
        }
    }

    function handleScheduleExcelUpload(file) {
        showToast(`엑셀 파일(${file.name}) 분석 중...`, "info");
        const reader = new FileReader();

        reader.onload = function(e) {
            try {
                const data = new Uint8Array(e.target.result);
                if (typeof XLSX === "undefined") {
                    showToast("XLSX 라이브러리가 로드되지 않았습니다", "error");
                    return;
                }

                const workbook = XLSX.read(data, { type: "array", cellDates: true });
                const firstSheetName = workbook.SheetNames[0];
                const worksheet = workbook.Sheets[firstSheetName];
                
                const rawRows = XLSX.utils.sheet_to_json(worksheet, { header: 1, raw: false, dateNF: 'yyyy-mm-dd' });
                if (!rawRows || rawRows.length < 2) {
                    showToast("엑셀 파일에 유효한 데이터 행이 없습니다.", "warning");
                    return;
                }

                let startIdx = -1, endIdx = -1, payIdx = -1, nomIdx = -1, fixIdx = -1;
                let headerRowIndex = 0;

                for (let r = 0; r < Math.min(rawRows.length, 5); r++) {
                    const row = rawRows[r];
                    if (!Array.isArray(row)) continue;
                    for (let c = 0; c < row.length; c++) {
                        const colStr = String(row[c] || "").trim().toLowerCase().replace(/[^a-z0-9]/g, "");
                        if (colStr.includes("start")) startIdx = c;
                        else if (colStr.includes("end") || colStr.includes("maturity")) endIdx = c;
                        else if (colStr.includes("pay") || colStr.includes("settle")) payIdx = c;
                        else if (colStr.includes("nom") || colStr.includes("notional") || colStr.includes("amount") || colStr.includes("bal")) nomIdx = c;
                        else if (colStr.includes("fix") || colStr.includes("reset")) fixIdx = c;
                    }
                    if (startIdx !== -1 && endIdx !== -1) {
                        headerRowIndex = r;
                        break;
                    }
                }

                if (startIdx === -1) startIdx = 0;
                if (endIdx === -1) endIdx = 1;
                if (payIdx === -1) payIdx = 2;
                if (nomIdx === -1) nomIdx = 3;
                if (fixIdx === -1) fixIdx = 4;

                const parsedLines = [];
                for (let r = headerRowIndex + 1; r < rawRows.length; r++) {
                    const row = rawRows[r];
                    if (!Array.isArray(row) || row.length === 0) continue;

                    const startVal = cleanDateStr(row[startIdx]);
                    const endVal = cleanDateStr(row[endIdx]);
                    const payVal = cleanDateStr(row[payIdx]) || endVal;
                    let nomVal = row[nomIdx] != null ? String(row[nomIdx]).trim() : "0";
                    const fixVal = cleanDateStr(row[fixIdx]) || startVal;

                    if (!startVal || !endVal) continue;

                    nomVal = nomVal.replace(/,/g, "");
                    const numNom = parseFloat(nomVal);
                    if (!isNaN(numNom)) {
                        nomVal = numNom.toLocaleString("en-US");
                    }

                    parsedLines.push(`${startVal}\t${endVal}\t${payVal}\t${nomVal}\t${fixVal}`);
                }

                if (parsedLines.length === 0) {
                    showToast("스케줄 데이터 행을 찾을 수 없습니다. 양식을 확인해주세요.", "warning");
                    return;
                }

                const formattedText = parsedLines.join("\n");
                
                if (elements.rcPasteInputLeg1) elements.rcPasteInputLeg1.value = formattedText;
                if (elements.rcPasteInputLeg2) elements.rcPasteInputLeg2.value = formattedText;
                if (elements.rcPasteInput) elements.rcPasteInput.value = formattedText;

                const pasteContent = document.getElementById("paste-schedule-content");
                if (pasteContent && pasteContent.classList.contains("collapsed")) {
                    pasteContent.classList.remove("collapsed");
                    pasteContent.style.display = "block";
                    const icon = document.getElementById("paste-collapse-icon");
                    if (icon) icon.textContent = "\u25BE";
                }
                if (elements.rcStatusBadge) elements.rcStatusBadge.style.display = "inline-block";
                const pill = document.getElementById("rc-period-count-pill");
                if (pill) pill.style.display = "inline-block";
                if (elements.rcPeriodCount) elements.rcPeriodCount.textContent = String(parsedLines.length);

                showToast(`엑셀 파일(${file.name})에서 ${parsedLines.length}개 기간 스케줄 로드 완료!`, "success");
                calculatePricing();
            } catch (err) {
                console.error("Excel upload error:", err);
                showToast(`엑셀 파일 파싱 오류: ${err.message}`, "error");
            }
        };

        reader.readAsArrayBuffer(file);
    }

    function cleanDateStr(val) {
        if (!val) return "";
        if (val instanceof Date) {
            return val.toISOString().slice(0, 10);
        }
        const s = String(val).trim();
        const matched = s.match(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
        if (matched) {
            const y = matched[1];
            const m = matched[2].padStart(2, "0");
            const d = matched[3].padStart(2, "0");
            return `${y}-${m}-${d}`;
        }
        return s;
    }

    if (elements.btnRcCopyL1ToL2) {
        elements.btnRcCopyL1ToL2.addEventListener("click", () => {
            const l1Val = elements.rcPasteInputLeg1 ? elements.rcPasteInputLeg1.value.trim() : "";
            if (l1Val && elements.rcPasteInputLeg2) {
                elements.rcPasteInputLeg2.value = l1Val;
                showToast("Copied Leg 1 schedule to Leg 2. Pricing recalculated.", "success");
                calculatePricing();
            } else {
                showToast("Leg 1에 붙여넣을 스케줄이 없습니다.", "warning");
            }
        });
    }

    if (elements.btnRcClear) {
        elements.btnRcClear.addEventListener("click", () => {
            if (elements.rcPasteInputLeg1) elements.rcPasteInputLeg1.value = "";
            if (elements.rcPasteInputLeg2) elements.rcPasteInputLeg2.value = "";
            if (elements.rcPasteInput) elements.rcPasteInput.value = "";
            if (elements.rcStatusBadge) elements.rcStatusBadge.style.display = "none";
            if (elements.rcStatusBadgeLeg1) elements.rcStatusBadgeLeg1.style.display = "none";
            if (elements.rcStatusBadgeLeg2) elements.rcStatusBadgeLeg2.style.display = "none";
            if (elements.rcActiveSummary) elements.rcActiveSummary.style.display = "none";
            const pill = document.getElementById("rc-period-count-pill");
            if (pill) pill.style.display = "none";
            state.customSchedule = null;
            showToast("All custom schedules cleared. Reverted to standard vanilla swap.", "info");
            calculatePricing();
        });
    }

    if (elements.btnRcClearLeg1) {
        elements.btnRcClearLeg1.addEventListener("click", () => {
            if (elements.rcPasteInputLeg1) elements.rcPasteInputLeg1.value = "";
            if (elements.rcStatusBadgeLeg1) elements.rcStatusBadgeLeg1.style.display = "none";
            calculatePricing();
            showToast("Leg 1 schedule cleared.", "info");
        });
    }

    if (elements.btnRcClearLeg2) {
        elements.btnRcClearLeg2.addEventListener("click", () => {
            if (elements.rcPasteInputLeg2) elements.rcPasteInputLeg2.value = "";
            if (elements.rcStatusBadgeLeg2) elements.rcStatusBadgeLeg2.style.display = "none";
            calculatePricing();
            showToast("Leg 2 schedule cleared.", "info");
        });
    }

    // Direct Table Paste Event Listener (Ctrl + V)
    document.addEventListener("paste", (e) => {
        const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
        if (activeTag === "input" || activeTag === "textarea") return;

        const clipboardData = e.clipboardData || window.clipboardData;
        const pastedData = clipboardData.getData("Text");
        if (pastedData && (pastedData.includes("\t") || pastedData.includes("\n"))) {
            const periods = parseClipboardScheduleText(pastedData);
            if (periods.length > 0) {
                e.preventDefault();
                state.customSchedule = periods;
                updateScheduleModeUI();
                calculatePricing();
                showToast(`[Ctrl+V] Pasted ${periods.length} periods from clipboard`, "success");
            }
        }
    });

    // --------------------------------------------------------------------------
    // 9. Export Schedule to CSV
    // --------------------------------------------------------------------------
    elements.btnExportCsv.addEventListener("click", () => {
        if (!state.pricingResult || !state.pricingResult.schedules) {
            showToast("No active schedule to export", "warning");
            return;
        }

        const list = state.pricingResult.schedules.dual_comparison || [];
        let csvContent = "data:text/csv;charset=utf-8,";
        csvContent += "Period,Start Date,End Date,Pay Date,Fixed Rate (%),Fixed CF,Fixed PV,Fwd Rate (%),Float CF,Float PV,Net CF,Net PV\n";

        list.forEach(p => {
            const row = [
                p.period_no,
                p.start_date,
                p.end_date,
                p.pay_date,
                p.fixed_rate_pct,
                p.fixed_cf,
                p.fixed_pv,
                p.fwd_sofr_pct,
                p.float_cf,
                p.float_pv,
                p.net_cf,
                p.net_pv
            ].join(",");
            csvContent += row + "\n";
        });

        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `${state.currency}_IRS_Schedule_${state.selectedTenor}.csv`);
        document.body.appendChild(link);
        link.click();
        link.remove();
        showToast("Exported schedule to CSV", "success");
    });

    // --------------------------------------------------------------------------
    // 10. Quote Override Modal & App Key Handlers
    // --------------------------------------------------------------------------
    function openQuoteModal(tenor, ric, mid) {
        elements.modalTenor.value = tenor;
        elements.modalRic.value = ric;
        elements.modalMid.value = mid.toFixed(4);
        elements.quoteModalBackdrop.style.display = "flex";
        elements.modalMid.focus();
    }

    function closeQuoteModal() {
        elements.quoteModalBackdrop.style.display = "none";
    }

    elements.modalCloseBtn.addEventListener("click", closeQuoteModal);
    elements.modalCancelBtn.addEventListener("click", closeQuoteModal);

    elements.modalSaveBtn.addEventListener("click", async () => {
        const tenor = elements.modalTenor.value;
        const newMid = parseFloat(elements.modalMid.value);
        if (isNaN(newMid)) return;

        const endpoint = getQuoteUpdateEndpoint();
        await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenor: tenor, mid: newMid })
        });

        if (tenor === "SPOT_FX" || tenor === "SPOT") {
            if (elements.capitalFxRate) elements.capitalFxRate.value = formatNumberWithCommas(newMid.toFixed(2));
            syncCrsNotionals("fx");
        }

        closeQuoteModal();
        showToast(`Updated quote for ${tenor} to ${newMid.toFixed(4)}`, "success");
        reloadAndPrice();
    });

    elements.btnResetQuotes.addEventListener("click", async () => {
        const endpoint = getQuoteResetEndpoint();
        await fetch(endpoint, { method: "POST" });
        showToast(`Reset ${state.currency} quotes to baseline`, "info");
        reloadAndPrice();
    });

    // App Key Modal
    elements.btnOpenAppkeyModal.addEventListener("click", () => {
        elements.appkeyModalBackdrop.style.display = "flex";
    });

    elements.appkeyModalCloseBtn.addEventListener("click", () => elements.appkeyModalBackdrop.style.display = "none");
    elements.appkeyModalCancelBtn.addEventListener("click", () => elements.appkeyModalBackdrop.style.display = "none");

    elements.appkeyModalSaveBtn.addEventListener("click", async () => {
        const key = elements.inputAppKey.value.trim();
        if (!key) return;

        elements.lsegConnStatusMsg.textContent = "Connecting to LSEG Desktop Proxy...";
        const resp = await fetch("/api/lseg/set-app-key", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ app_key: key })
        });
        const res = await resp.json();
        if (res.status === "success") {
            elements.appkeyModalBackdrop.style.display = "none";
            showToast("LSEG Workspace Connected!", "success");
            reloadAndPrice();
        } else {
            elements.lsegConnStatusMsg.textContent = `Error: ${res.message}`;
        }
    });

    // --------------------------------------------------------------------------
    // 11. Event Listeners & Keyboard Shortcuts
    // --------------------------------------------------------------------------
    elements.notionalDisplay.addEventListener("input", (e) => {
        e.target.value = formatNumberWithCommas(e.target.value);
        syncCrsNotionals("usd");
    });

    if (elements.capitalFxRate) {
        elements.capitalFxRate.addEventListener("input", () => {
            syncCrsNotionals("fx");
        });
        elements.capitalFxRate.addEventListener("change", () => {
            calculatePricing();
        });
    }

    if (elements.krwNotionalDisplay) {
        elements.krwNotionalDisplay.addEventListener("input", (e) => {
            e.target.value = formatNumberWithCommas(e.target.value);
            syncCrsNotionals("krw");
        });
        elements.krwNotionalDisplay.addEventListener("change", () => {
            calculatePricing();
        });
    }

    // 2-Phase Direction & Position Controls
    if (elements.btnPhasePay) {
        elements.btnPhasePay.addEventListener("click", () => {
            setTradePosition("Pay Fixed");
            calculatePricing();
        });
    }
    if (elements.btnPhaseRec) {
        elements.btnPhaseRec.addEventListener("click", () => {
            setTradePosition("Rec Fixed");
            calculatePricing();
        });
    }
    if (elements.positionSelect) {
        elements.positionSelect.addEventListener("change", (e) => {
            setTradePosition(e.target.value);
            calculatePricing();
        });
    }

    elements.btnReloadMarket.addEventListener("click", () => {
        if (state.currency === "USD_FWD") {
            fetchFwdMarketSnapshot(true);
        } else {
            loadMarketSnapshot(true);
        }
    });
    elements.btnReloadFeed.addEventListener("click", () => {
        if (state.currency === "USD_FWD") {
            fetchFwdMarketSnapshot(true);
        } else {
            loadMarketSnapshot(true);
        }
    });
    elements.btnCalcPrice.addEventListener("click", calculatePricing);
    elements.btnOneShot.addEventListener("click", () => {
        if (state.currency === "USD_FWD") {
            reloadAndPriceFwd();
        } else {
            reloadAndPrice();
        }
    });

    // Parametric Selection Changes (Auto Recalculate & Schedule Refresh)
    [
        elements.leg1DayCount,
        elements.leg1PaymentFreq,
        elements.leg1Convention,
        elements.leg1Stub,
        elements.leg1Adjust,
        elements.leg1PayCal,
        elements.leg2DayCount,
        elements.leg2PaymentFreq,
        elements.leg2Convention,
        elements.leg2Stub,
        elements.leg2Adjust,
        elements.leg2Cal,
        elements.paramDayCount,
        elements.paramPaymentFreq,
        elements.paramFixCal,
        elements.paramPayCal,
        elements.paramConvention,
        elements.paramStub,
        elements.paramAdjust
    ].forEach(sel => {
        if (sel) {
            sel.addEventListener("change", () => {
                updateDatesFromTenor();
                saveActiveTicketFormData();
                calculatePricing();
            });
        }
    });

    if (elements.paramFixDay) {
        elements.paramFixDay.addEventListener("change", () => {
            saveActiveTicketFormData();
            calculatePricing();
        });
    }

    if (elements.usdFixedCouponInput) {
        elements.usdFixedCouponInput.addEventListener("change", () => {
            saveActiveTicketFormData();
            calculatePricing();
        });
    }

    if (elements.couponInput) {
        elements.couponInput.addEventListener("input", () => {
            elements.couponInput.dataset.userEdited = "true";
        });
    }

    if (elements.btnResetParams) {
        elements.btnResetParams.addEventListener("click", () => {
            applyCurrencyParamDefaults(state.currency);
            updateDatesFromTenor();
            saveActiveTicketFormData();
            calculatePricing();
            showToast(`Reset parameters to default for ${state.currency}`, "info");
        });
    }

    // --------------------------------------------------------------------------
    // 12. Forward Swap Point & FX Forward Engine Functions (Trader Workflow)
    // --------------------------------------------------------------------------
    // --------------------------------------------------------------------------
    // 12. KMBC Forward Swap Point & FX Forward Engine Functions (Reference '일중' 매핑)
    // --------------------------------------------------------------------------
    let fwdPricingResult = null;
    var fwdMarketSnapshot = null;
    window.fwdMarketSnapshot = null;

    async function fetchFwdMarketSnapshot(forceReload = false) {
        try {
            const url = forceReload ? `/api/fwd/market-snapshot?reload=true&_t=${Date.now()}` : "/api/fwd/market-snapshot";
            const resp = await fetch(url);
            const json = await resp.json();
            if (json.status === "success") {
                const data = json.data;
                fwdMarketSnapshot = data;
                window.fwdMarketSnapshot = data;
                state.fwdMarketSnapshot = data;
                state.marketSnapshot = data;
                if (data.timestamp && elements.snapshotTimestamp) {
                    elements.snapshotTimestamp.textContent = data.timestamp.split(" ")[1] || "--:--:--";
                }
                markSnapshotTaken();
                if (elements.fwdSpotFx && !elements.fwdSpotFx.dataset.manual) {
                    elements.fwdSpotFx.value = formatNumberWithCommas(data.spot_fx.toFixed(2));
                }
                if (elements.fwdSpotDate) {
                    elements.fwdSpotDate.value = data.spot_date;
                }

                // Update Mini Stat Labels for KMBC Swap Points
                if (elements.lblFixRate) elements.lblFixRate.textContent = "Spot FX (KRW=)";
                if (elements.oisFixRate) elements.oisFixRate.textContent = data.spot_fx.toFixed(2);
                if (elements.lbl1yRate) elements.lbl1yRate.textContent = "1M SP (원 / 전)";
                if (elements.lbl3yRate) elements.lbl3yRate.textContent = "3M SP (원 / 전)";
                if (elements.lbl5yRate) elements.lbl5yRate.textContent = "6M SP (원 / 전)";

                const quotes = data.kmbc_quotes || data.quotes || [];
                const q1m = quotes.find(q => q.tenor === "1M");
                const q3m = quotes.find(q => q.tenor === "3M");
                const q6m = quotes.find(q => q.tenor === "6M");
                if (elements.ois1yRate && q1m) {
                    const mWon = q1m.mid_krw !== undefined ? q1m.mid_krw : q1m.mid / 100.0;
                    elements.ois1yRate.textContent = `${mWon >= 0 ? "+" : ""}${mWon.toFixed(2)} 원 (${q1m.mid.toFixed(1)}전)`;
                }
                if (elements.ois3yRate && q3m) {
                    const mWon = q3m.mid_krw !== undefined ? q3m.mid_krw : q3m.mid / 100.0;
                    elements.ois3yRate.textContent = `${mWon >= 0 ? "+" : ""}${mWon.toFixed(2)} 원 (${q3m.mid.toFixed(1)}전)`;
                }
                if (elements.ois5yRate && q6m) {
                    const mWon = q6m.mid_krw !== undefined ? q6m.mid_krw : q6m.mid / 100.0;
                    elements.ois5yRate.textContent = `${mWon >= 0 ? "+" : ""}${mWon.toFixed(2)} 원 (${q6m.mid.toFixed(1)}전)`;
                }

                renderFwdKmbcQuoteTable(quotes, data.spot_fx, data.spot_fx_bid, data.spot_fx_ask);
                renderFwdCurveChart(quotes);

                // Immediately recalculate forward pricing with freshly loaded market rates
                calculateFwdPricing();
            }
        } catch (err) {
            console.error("Error fetching KMBC FWD market snapshot:", err);
        }
    }

    function renderFwdKmbcQuoteTable(quotes, spotFx, spotBid, spotAsk) {
        if (!elements.quoteTableBody || !quotes) return;
        elements.quoteTableBody.innerHTML = "";

        // Spot FX Top Row
        const trSpot = document.createElement("tr");
        trSpot.style.backgroundColor = "#f0fdf4";
        trSpot.style.borderBottom = "1.5px solid #86efac";
        const bVal = spotBid ? spotBid.toFixed(2) : (spotFx - 0.20).toFixed(2);
        const aVal = spotAsk ? spotAsk.toFixed(2) : (spotFx + 0.20).toFixed(2);
        trSpot.innerHTML = `
            <td><strong style="color:#0284c7;">USD/KRW Spot</strong></td>
            <td style="font-size:10px; color:#0284c7; font-weight:700;">KRW=</td>
            <td class="num">${bVal}</td>
            <td class="num">${aVal}</td>
            <td class="num"><strong style="color:#0284c7;">${spotFx.toFixed(2)}</strong></td>
        `;
        elements.quoteTableBody.appendChild(trSpot);

        quotes.forEach(q => {
            const tr = document.createElement("tr");
            const isCip = q.source === "CIP_Inverse" || q.type === "CIP (DF 역산)" || q.ric === "CIP (DF 역산)";
            if (isCip) {
                tr.style.backgroundColor = "#f8fafc";
            }
            const midVal = typeof q.mid === "number" ? q.mid : parseFloat(q.mid) || 0;
            const bidStr = (q.bid !== null && q.bid !== undefined) ? (typeof q.bid === "number" ? q.bid.toFixed(2) : q.bid) : "-";
            const askStr = (q.ask !== null && q.ask !== undefined) ? (typeof q.ask === "number" ? q.ask.toFixed(2) : q.ask) : "-";
            const spColor = midVal >= 0 ? "color:#15803d; font-weight:700;" : "color:#be123c; font-weight:700;";
            
            const ricDisplay = isCip
                ? `<span style="color:#94a3b8; font-weight:600; text-align:center; display:block;">-</span>`
                : `<span style="font-size:10px; color:var(--text-secondary); font-weight:600;">${q.ric}</span>`;

            tr.innerHTML = `
                <td><strong>${q.tenor}</strong></td>
                <td>${ricDisplay}</td>
                <td class="num">${bidStr}</td>
                <td class="num">${askStr}</td>
                <td class="num" style="${spColor}"><strong>${midVal.toFixed(2)}</strong></td>
            `;
            elements.quoteTableBody.appendChild(tr);
        });
    }

    function renderFwdCurveChart(quotes) {
        const canvas = elements.curveCanvas;
        if (!canvas || !quotes || quotes.length === 0) return;
        const ctx = canvas.getContext("2d");
        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        const validPoints = quotes.filter(q => typeof q.mid_krw === "number" || typeof q.mid === "number");
        if (validPoints.length === 0) return;

        let minSP = 999, maxSP = -999;
        validPoints.forEach(p => {
            const val = p.mid_krw !== undefined ? p.mid_krw : p.mid / 100.0;
            if (val < minSP) minSP = val;
            if (val > maxSP) maxSP = val;
        });
        const padTop = 10, padBottom = 14, padLeft = 42, padRight = 12;
        const plotW = w - padLeft - padRight;
        const plotH = h - padTop - padBottom;
        const rangeSP = Math.max(2.0, (maxSP - minSP) * 1.15);
        const baseSP = minSP - (maxSP - minSP) * 0.08;

        // Grid lines
        ctx.strokeStyle = "#e2e8f0";
        ctx.lineWidth = 1;
        for (let i = 0; i <= 2; i++) {
            const y = padTop + (plotH / 2) * i;
            ctx.beginPath();
            ctx.moveTo(padLeft, y);
            ctx.lineTo(w - padRight, y);
            ctx.stroke();

            const spVal = baseSP + rangeSP * (1 - i / 2);
            ctx.fillStyle = "#64748b";
            ctx.font = "bold 8px JetBrains Mono";
            ctx.fillText(`${spVal.toFixed(1)}전`, 2, y + 3);
        }

        // KMBC + CIP Forward Swap Point Curve
        ctx.strokeStyle = "#0284c7";
        ctx.lineWidth = 2;
        ctx.beginPath();
        validPoints.forEach((p, idx) => {
            const val = p.mid_krw !== undefined ? p.mid_krw : p.mid / 100.0;
            const x = padLeft + (plotW / (validPoints.length - 1)) * idx;
            const y = padTop + plotH * (1 - (val - baseSP) / rangeSP);
            if (idx === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Points with Source Color Coding (Green for KMBC Live, Amber for CIP DF Inverse)
        validPoints.forEach((p, idx) => {
            const val = p.mid_krw !== undefined ? p.mid_krw : p.mid / 100.0;
            const x = padLeft + (plotW / (validPoints.length - 1)) * idx;
            const y = padTop + plotH * (1 - (val - baseSP) / rangeSP);
            const isCip = p.source === "CIP_Inverse" || p.type === "CIP (DF 역산)" || p.ric === "CIP (DF 역산)";
            ctx.fillStyle = isCip ? "#d97706" : "#0284c7";
            ctx.beginPath();
            ctx.arc(x, y, 3, 0, Math.PI * 2);
            ctx.fill();
        });
    }

    async function calculateFwdPricing() {
        try {
            elements.calcStatus.textContent = "Pricing FWD...";
            elements.calcStatus.className = "calc-status-badge calc-loading";

            const rawSpot = elements.fwdSpotFx ? elements.fwdSpotFx.value.replace(/,/g, "") : "1357.85";
            const spotFx = parseFloat(rawSpot) || 1357.85;
            const defaultMarginBp = (elements.fwdDefaultMargin && elements.fwdDefaultMargin.value !== "" && !isNaN(parseFloat(elements.fwdDefaultMargin.value))) ? parseFloat(elements.fwdDefaultMargin.value) : 0.0;
            const rawPaste = elements.fwdPasteTextarea?.value || "";

            const payload = {
                spot_fx: spotFx,
                default_margin_bp: defaultMarginBp,
                raw_paste_text: rawPaste
            };

            const resp = await fetch("/api/fwd/price", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            const json = await resp.json();
            if (json.status === "success") {
                fwdPricingResult = json.data;
                renderFwdPricingResults(json.data);
                renderFwdScheduleTable(json.data.legs, spotFx);
                if (typeof updateActiveTicketPricingResult === "function") {
                    const snapTime = state.fwdMarketSnapshot ? state.fwdMarketSnapshot.timestamp : (state.marketSnapshot ? state.marketSnapshot.timestamp : null);
                    updateActiveTicketPricingResult(json.data, snapTime);
                }
                if (elements.periodCountBadge) elements.periodCountBadge.textContent = `${json.data.legs.length} Far Legs`;
                if (elements.scheduleTitleText) elements.scheduleTitleText.textContent = "USD/KRW Forward Far Leg Schedule";

                elements.calcStatus.textContent = "FWD Ready";
                elements.calcStatus.className = "calc-status-badge calc-ready";
            } else {
                throw new Error(json.detail || "FWD calculation failed");
            }
        } catch (err) {
            console.error("FWD pricing error:", err);
            elements.calcStatus.textContent = "Error";
            elements.calcStatus.className = "calc-status-badge calc-offline";
            showToast(`FWD Pricing error: ${err.message}`, "warning");
        }
    }

    async function reloadAndPriceFwd() {
        try {
            elements.calcStatus.textContent = "Reload & Price FWD...";
            elements.calcStatus.className = "calc-status-badge calc-loading";

            const rawSpot = elements.fwdSpotFx ? elements.fwdSpotFx.value.replace(/,/g, "") : "1357.85";
            const spotFx = parseFloat(rawSpot) || 1357.85;
            const defaultMarginBp = (elements.fwdDefaultMargin && elements.fwdDefaultMargin.value !== "" && !isNaN(parseFloat(elements.fwdDefaultMargin.value))) ? parseFloat(elements.fwdDefaultMargin.value) : 0.0;
            const rawPaste = elements.fwdPasteTextarea?.value || "";

            const payload = {
                spot_fx: spotFx,
                default_margin_bp: defaultMarginBp,
                raw_paste_text: rawPaste
            };

            const resp = await fetch("/api/fwd/reload-and-price", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            const json = await resp.json();
            if (json.status === "success") {
                fwdPricingResult = json.data;
                if (json.market_snapshot) {
                    fwdMarketSnapshot = json.market_snapshot;
                    window.fwdMarketSnapshot = json.market_snapshot;
                    state.fwdMarketSnapshot = json.market_snapshot;
                    state.marketSnapshot = json.market_snapshot;
                    if (json.market_snapshot.timestamp && elements.snapshotTimestamp) {
                        elements.snapshotTimestamp.textContent =
                            json.market_snapshot.timestamp.split(" ")[1] || "--:--:--";
                    }
                }
                markSnapshotTaken();
                renderFwdPricingResults(json.data);
                renderFwdScheduleTable(json.data.legs, spotFx);
                if (typeof updateActiveTicketPricingResult === "function") {
                    const snapTime = state.fwdMarketSnapshot ? state.fwdMarketSnapshot.timestamp : (state.marketSnapshot ? state.marketSnapshot.timestamp : null);
                    updateActiveTicketPricingResult(json.data, snapTime);
                }
                if (elements.periodCountBadge) elements.periodCountBadge.textContent = `${json.data.legs.length} Far Legs`;
                if (elements.scheduleTitleText) elements.scheduleTitleText.textContent = "USD/KRW Forward Far Leg Schedule";

                // Refresh Left Market table
                fetchFwdMarketSnapshot();

                elements.calcStatus.textContent = "FWD Ready";
                elements.calcStatus.className = "calc-status-badge calc-ready";
                showToast(`[F9] Forward Curves & Far Leg Pricing refreshed`, "success");
            } else {
                throw new Error(json.detail || "FWD calculation failed");
            }
        } catch (err) {
            console.error("FWD reload & price error:", err);
            elements.calcStatus.textContent = "Error";
            elements.calcStatus.className = "calc-status-badge calc-offline";
            showToast(`FWD Reload & Price error: ${err.message}`, "warning");
        }
    }

    function renderFwdPricingResults(data) {
        if (!data) return;
        // Hero Card 1: Weighted Avg Swap Point (P2 in Reference 일중 sheet)
        const wavgSp = data.weighted_avg_sp;
        const wavgSpColor = wavgSp >= 0 ? "#15803d" : "#be123c";
        if (elements.fwdResWavgSp) {
            elements.fwdResWavgSp.innerHTML = `<span style="color:${wavgSpColor};">${wavgSp.toFixed(2)}</span> <span class="unit">원</span>`;
        }
        if (elements.fwdResWavgSub) {
            elements.fwdResWavgSub.textContent = `Theo SP: ${data.weighted_avg_theo_sp.toFixed(2)} | Margin: ${data.weighted_avg_margin_sp.toFixed(2)} 원`;
        }

        // Hero Card 2: Total USD Notional & FX Delta (S2 / AN2 in Reference 일중 sheet)
        if (elements.fwdResTotalNotional) {
            elements.fwdResTotalNotional.textContent = `$ ${formatNumberWithCommas(Math.round(data.total_notional_usd))}`;
        }
        if (elements.fwdResDeltaSub) {
            elements.fwdResDeltaSub.textContent = `FX Delta: $ ${formatNumberWithCommas(data.total_fx_delta_usd.toFixed(2))} | Spot Hedge: ₩${formatNumberWithCommas(Math.round(data.total_spot_hedge_krw))}`;
        }

        // Hero Card 3: Total Sales Margin (AJ3 in Reference 일중 sheet)
        if (elements.fwdResTotalMargin) {
            elements.fwdResTotalMargin.textContent = `\u20A9 ${formatNumberWithCommas(Math.round(data.total_sales_margin_krw))}`;
        }
        if (elements.fwdResMarginSub) {
            elements.fwdResMarginSub.textContent = `Tranches: ${data.total_count} | Default Margin: ${data.default_margin_bp} bp`;
        }

        // Spot Date Discount Factors
        const elDfUsdSpot = document.getElementById("fwd-spec-df-usd");
        const elDfKrwSpot = document.getElementById("fwd-spec-df-krw");
        if (elDfUsdSpot && typeof data.df_usd_spot === "number") {
            elDfUsdSpot.textContent = data.df_usd_spot.toFixed(6);
        }
        if (elDfKrwSpot && typeof data.df_krw_spot === "number") {
            elDfKrwSpot.textContent = data.df_krw_spot.toFixed(6);
        }
    }

    function renderFwdScheduleTable(legs, spotFx) {
        if (!elements.fwdScheduleTableBody || !legs) return;
        elements.fwdScheduleTableBody.innerHTML = "";

        legs.forEach(leg => {
            const tr = document.createElement("tr");
            const spQuoteColor = leg.sp_quote >= 0 ? "color:#15803d; font-weight:700;" : "color:#be123c; font-weight:700;";
            const rawMat = leg.raw_maturity || leg.maturity;
            const dfUsdStr = typeof leg.df_usd === "number" ? leg.df_usd.toFixed(6) : "-";
            const dfKrwStr = typeof leg.df_krw === "number" ? leg.df_krw.toFixed(6) : "-";

            tr.innerHTML = `
                <td><strong>#${leg.leg_id}</strong></td>
                <td><strong>${rawMat}</strong></td>
                <td style="color:#64748b; font-size:11px;">${leg.maturity}</td>
                <td>${leg.days_from_spot}d</td>
                <td class="num">$ ${formatNumberWithCommas(Math.round(leg.notional_usd))}</td>
                    <td class="num">₩${formatNumberWithCommas(Math.round(Math.abs(leg.notional_krw)))}</td>
                <td class="num" style="color:#0369a1; font-family:'Roboto Mono',monospace; font-size:11px;">${dfUsdStr}</td>
                <td class="num" style="color:#d97706; font-family:'Roboto Mono',monospace; font-size:11px;">${dfKrwStr}</td>
                <td class="num">${leg.fwd_theo.toFixed(2)}</td>
                <td class="num">${leg.sp_theo.toFixed(2)}</td>
                <td class="num">${leg.margin_bp} bp</td>
                <td class="num" style="color:#0369a1;">${leg.swap_margin.toFixed(2)}</td>
                <td class="num" style="${spQuoteColor}"><strong>${leg.sp_quote.toFixed(2)}</strong></td>
                <td class="num"><strong>${leg.fwd_quote.toFixed(2)}</strong></td>
                <td class="num">$ ${formatNumberWithCommas(leg.fx_delta_usd.toFixed(2))}</td>
                    <td class="num">₩${formatNumberWithCommas(Math.round(leg.spot_hedge_krw))}</td>
                    <td class="num" style="color:#15803d; font-weight:600;">₩${formatNumberWithCommas(Math.round(leg.sales_margin_krw))}</td>
            `;
            elements.fwdScheduleTableBody.appendChild(tr);
        });
    }

    function copyFwdQuotesForMessenger() {
        if (!fwdPricingResult || !fwdPricingResult.legs || fwdPricingResult.legs.length === 0) {
            showToast("No forward quotes to copy. Please calculate first.", "warning");
            return;
        }

        const data = fwdPricingResult;
        let text = `[USD/KRW FX Forward & Swap Point Quote (KMBC)]\n`;
        text += `Spot FX: ${formatNumberWithCommas(data.spot_fx.toFixed(2))} (Spot Date: ${data.spot_date})\n`;
        text += `-----------------------------------------------------------------------------------------\n`;
            text += `No   Maturity        Notional (USD)    Quoted SP (원)       Quoted Fwd      FX Delta (USD)\n`;
        text += `-----------------------------------------------------------------------------------------\n`;

        data.legs.forEach(leg => {
            const noStr = String(leg.leg_id).padEnd(4, " ");
            const matStr = (leg.raw_maturity || leg.maturity).padEnd(15, " ");
            const notionalStr = ("$ " + formatNumberWithCommas(Math.round(leg.notional_usd))).padEnd(18, " ");
            const spStr = (leg.sp_quote.toFixed(2) + " 원").padEnd(20, " ");
            const fwdStr = formatNumberWithCommas(leg.fwd_quote.toFixed(2)).padEnd(15, " ");
            const deltaStr = "$ " + formatNumberWithCommas(leg.fx_delta_usd.toFixed(2));
            text += `${noStr} ${matStr} ${notionalStr} ${spStr} ${fwdStr} ${deltaStr}\n`;
        });

        text += `-----------------------------------------------------------------------------------------\n`;
        text += `Total USD Notional:  $ ${formatNumberWithCommas(Math.round(data.total_notional_usd))}\n`;
        text += `Total FX Delta:      $ ${formatNumberWithCommas(data.total_fx_delta_usd.toFixed(2))}\n`;
            text += `Total Spot Hedge:    ₩${formatNumberWithCommas(Math.round(data.total_spot_hedge_krw))}\n`;
            text += `Total Sales Margin:  ₩${formatNumberWithCommas(Math.round(data.total_sales_margin_krw))}\n`;
            text += `Weighted Avg SP:     ${data.weighted_avg_sp.toFixed(2)} 원 (Margin: ${data.default_margin_bp} bp)\n`;
        text += `-----------------------------------------------------------------------------------------\n`;

        navigator.clipboard.writeText(text).then(() => {
            showToast("\u2713 Copied Quote table to Clipboard for Messenger!", "success");
        }).catch(err => {
            console.error("Clipboard copy failed:", err);
            showToast("Clipboard copy failed. Please copy manually.", "warning");
        });
    }

    // FWD Event Listeners
    if (elements.fwdDefaultMargin) {
        elements.fwdDefaultMargin.addEventListener("input", () => calculateFwdPricing());
        elements.fwdDefaultMargin.addEventListener("change", () => calculateFwdPricing());
    }
    if (elements.fwdSpotFx) {
        elements.fwdSpotFx.addEventListener("input", () => calculateFwdPricing());
        elements.fwdSpotFx.addEventListener("change", () => calculateFwdPricing());
    }
    if (elements.btnFwdApplyPaste) elements.btnFwdApplyPaste.addEventListener("click", calculateFwdPricing);
    if (elements.btnFwdCalc) elements.btnFwdCalc.addEventListener("click", calculateFwdPricing);
    if (elements.btnFwdReload) elements.btnFwdReload.addEventListener("click", () => fetchFwdMarketSnapshot(true));
    if (elements.btnFwdOneshot) elements.btnFwdOneshot.addEventListener("click", reloadAndPriceFwd);
    if (elements.btnFwdCopyMessenger) elements.btnFwdCopyMessenger.addEventListener("click", copyFwdQuotesForMessenger);

    if (elements.btnFwdSample) {
        elements.btnFwdSample.addEventListener("click", () => {
            if (elements.fwdPasteTextarea) {
                elements.fwdPasteTextarea.value = "2026-11-30\t1,648,000\n2027-02-26\t1,676,000\n2027-05-28\t3,353,000\n2027-07-28\t1,649,000\n2027-11-30\t1,677,000\n2028-01-31\t1,676,000";
            }
            calculateFwdPricing();
        });
    }

    if (elements.btnFwdClear) {
        elements.btnFwdClear.addEventListener("click", () => {
            if (elements.fwdPasteTextarea) elements.fwdPasteTextarea.value = "";
            if (elements.fwdScheduleTableBody) elements.fwdScheduleTableBody.innerHTML = "";
            showToast("Cleared Far Leg paste inputs", "info");
        });
    }

    if (elements.tabBtnFwd) {
        elements.tabBtnFwd.addEventListener("click", () => {
            switchScheduleTab("fwd");
        });
    }

    // ==========================================================================
    // MULTI-QUOTE TICKET WORKSPACE & LAZY EVALUATION MANAGER
    // ==========================================================================
    const TICKETS_STORAGE_KEY = "MULTIPRICER_QUOTE_TICKETS_v4";

    let ticketsStore = {
        "USD": [],
        "KRW": [],
        "KRW_KOFR": [],
        "KRW_CRS": [],
        "USD_FWD": []
    };

    let activeTicketIdByProduct = {
        "USD": null,
        "KRW": null,
        "KRW_KOFR": null,
        "KRW_CRS": null,
        "USD_FWD": null
    };

    function getDefaultTicketData(curr) {
        if (curr === "USD_FWD") {
            return {
                id: `ticket_${curr}_${Date.now()}_${Math.floor(Math.random()*1000)}`,
                product: curr,
                clientName: "General",
                alias: "USD/KRW Far Legs",
                memo: "",
                fwdSpotFx: "1357.85",
                fwdDefaultMargin: "1.0",
                fwdPasteText: "2026-11-30\t1,648,000\n2027-02-26\t1,676,000\n2027-05-28\t3,353,000",
                fwdDir: "buy",
                lastPricingResult: null,
                pricedCurveTimestamp: null,
                lastCalculatedAt: null
            };
        }
        
        const defaultNotional = curr === "USD" ? "100,000,000" : (curr === "KRW_KOFR" ? "10,000,000,000" : (curr === "KRW" ? "100,000,000,000" : "100,000,000"));
        const defaultTenor = curr === "KRW_KOFR" ? "1Y" : (curr === "KRW" ? "3Y" : "5Y");
        const defaultCoupon = curr === "USD" ? "4.0610" : (curr === "KRW_KOFR" ? "3.3775" : (curr === "KRW" ? "3.8475" : "3.5500"));

        return {
            id: `ticket_${curr}_${Date.now()}_${Math.floor(Math.random()*1000)}`,
            product: curr,
            clientName: "General",
            alias: `${defaultTenor} Pay Fixed`,
            memo: "",
            notionalDisplay: defaultNotional,
            capitalFxRate: "1,375.75",
            krwNotionalDisplay: "137,575,000,000",
            position: "Pay Fixed",
            selectedTenor: defaultTenor,
            customTenorInput: defaultTenor,
            effectiveDate: "",
            maturityDate: "",
            coupon: defaultCoupon,
            spreadBp: "0.0",
            curveType: "Standard",
            crsSwapType: "Vanilla",
            usdFixedCoupon: "3.5000",

            // Independent Leg 1
            leg1DayCount: curr === "USD" ? "Act/360" : (curr === "KRW_CRS" ? "30/360" : "Act/365"),
            leg1PaymentFreq: curr === "USD" ? "12M" : (curr === "KRW_CRS" ? "6M" : "3M"),
            leg1Convention: "Modified Following",
            leg1Stub: "Short in arrears",
            leg1Adjust: "Adjust",
            leg1PayCal: curr === "USD" ? "NYB" : (curr === "KRW_CRS" ? "SEB_NYB" : "SEB"),

            // Independent Leg 2
            leg2DayCount: curr === "USD" ? "Act/360" : (curr === "KRW_CRS" ? "Act/360" : "Act/365"),
            leg2PaymentFreq: curr === "USD" ? "12M" : (curr === "KRW_CRS" ? "6M" : "3M"),
            leg2Convention: "Modified Following",
            leg2Stub: "Short in arrears",
            leg2Adjust: "Adjust",
            leg2Cal: curr === "USD" ? "NYB" : (curr === "KRW_CRS" ? "SEB_NYB" : "SEB"),
            fixCal: curr === "USD" ? "NYB" : (curr === "KRW_CRS" ? "SEB_NYB" : "SEB"),
            fixDay: curr === "USD" ? -2 : (curr === "KRW_KOFR" ? 0 : -1),

            // Legacy fallbacks
            dayCount: curr === "USD" ? "Act/360" : (curr === "KRW_CRS" ? "30/360" : "Act/365"),
            payCal: curr === "USD" ? "NYB" : (curr === "KRW_CRS" ? "SEB_NYB" : "SEB"),
            paymentFreq: curr === "USD" ? "12M" : (curr === "KRW_CRS" ? "6M" : "3M"),
            convention: "Modified Following",
            stubRule: "Short in arrears",
            adjustRule: "Adjust",
            rawPasteText: "",
            customSchedule: null,
            lastPricingResult: null,
            pricedCurveTimestamp: null,
            lastCalculatedAt: null
        };
    }

    function initTicketWorkspace() {
        try {
            const raw = localStorage.getItem(TICKETS_STORAGE_KEY);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (parsed.ticketsStore) ticketsStore = parsed.ticketsStore;
                if (parsed.activeTicketIdByProduct) activeTicketIdByProduct = parsed.activeTicketIdByProduct;
            }
        } catch (e) {
            console.warn("Failed to load tickets from localStorage:", e);
        }

        const products = ["USD", "KRW", "KRW_KOFR", "KRW_CRS", "USD_FWD"];
        products.forEach(p => {
            if (!ticketsStore[p] || ticketsStore[p].length === 0) {
                const initialTicket = getDefaultTicketData(p);
                ticketsStore[p] = [initialTicket];
                activeTicketIdByProduct[p] = initialTicket.id;
            } else if (!activeTicketIdByProduct[p] || !ticketsStore[p].some(t => t.id === activeTicketIdByProduct[p])) {
                activeTicketIdByProduct[p] = ticketsStore[p][0].id;
            }
        });

        saveTicketsToStorage();
    }

    function saveTicketsToStorage() {
        try {
            localStorage.setItem(TICKETS_STORAGE_KEY, JSON.stringify({
                ticketsStore,
                activeTicketIdByProduct
            }));
        } catch (e) {
            console.warn("Failed to save tickets to localStorage:", e);
        }
    }

    function getActiveTicket(curr = state.currency) {
        if (!ticketsStore[curr]) return null;
        const activeId = activeTicketIdByProduct[curr];
        return ticketsStore[curr].find(t => t.id === activeId) || ticketsStore[curr][0] || null;
    }

    // loadTicketToUI writes the form, and some of the setters it calls save the form
    // back to the ticket. Mid-load the form is only half written, so that round trip
    // wipes whatever has not been painted yet - the pasted schedule, in particular.
    let suppressTicketSave = false;

    function saveActiveTicketFormData() {
        if (suppressTicketSave) return;
        const ticket = getActiveTicket();
        if (!ticket) return;

        if (state.currency === "USD_FWD") {
            if (elements.ticketClientInput) ticket.clientName = elements.ticketClientInput.value.trim();
            if (elements.ticketAliasInput) ticket.alias = elements.ticketAliasInput.value.trim();
            if (elements.fwdSpotFx) ticket.fwdSpotFx = elements.fwdSpotFx.value;
            if (elements.fwdDefaultMargin) ticket.fwdDefaultMargin = elements.fwdDefaultMargin.value;
            if (elements.fwdPasteTextarea) ticket.fwdPasteText = elements.fwdPasteTextarea.value;
            ticket.fwdDir = (typeof fwdTradeDirection !== "undefined") ? fwdTradeDirection : "buy";
        } else {
            if (elements.ticketClientInput) ticket.clientName = elements.ticketClientInput.value.trim();
            if (elements.ticketAliasInput) ticket.alias = elements.ticketAliasInput.value.trim();
            if (elements.notionalDisplay) ticket.notionalDisplay = elements.notionalDisplay.value;
            if (elements.capitalFxRate) ticket.capitalFxRate = elements.capitalFxRate.value;
            if (elements.krwNotionalDisplay) ticket.krwNotionalDisplay = elements.krwNotionalDisplay.value;
            if (elements.positionSelect) ticket.position = elements.positionSelect.value;
            ticket.selectedTenor = state.selectedTenor || "5Y";
            if (elements.customTenorInput) ticket.customTenorInput = elements.customTenorInput.value;
            if (elements.effectiveDateInput) ticket.effectiveDate = elements.effectiveDateInput.value;
            if (elements.maturityDateInput) ticket.maturityDate = elements.maturityDateInput.value;
            if (elements.couponInput) ticket.coupon = elements.couponInput.value;
            if (elements.spreadInput) ticket.spreadBp = elements.spreadInput.value;

            ticket.curveType = state.curveType || "Standard";
            ticket.crsSwapType = state.crsSwapType || "Vanilla";
            if (elements.usdFixedCouponInput) ticket.usdFixedCoupon = elements.usdFixedCouponInput.value;

            // Leg 1
            if (elements.leg1DayCount) ticket.leg1DayCount = elements.leg1DayCount.value;
            if (elements.leg1PaymentFreq) ticket.leg1PaymentFreq = elements.leg1PaymentFreq.value;
            if (elements.leg1Convention) ticket.leg1Convention = elements.leg1Convention.value;
            if (elements.leg1Stub) ticket.leg1Stub = elements.leg1Stub.value;
            if (elements.leg1Adjust) ticket.leg1Adjust = elements.leg1Adjust.value;
            if (elements.leg1PayCal) ticket.leg1PayCal = elements.leg1PayCal.value;

            // Leg 2
            if (elements.leg2DayCount) ticket.leg2DayCount = elements.leg2DayCount.value;
            if (elements.leg2PaymentFreq) ticket.leg2PaymentFreq = elements.leg2PaymentFreq.value;
            if (elements.leg2Convention) ticket.leg2Convention = elements.leg2Convention.value;
            if (elements.leg2Stub) ticket.leg2Stub = elements.leg2Stub.value;
            if (elements.leg2Adjust) ticket.leg2Adjust = elements.leg2Adjust.value;
            if (elements.leg2Cal) ticket.leg2Cal = elements.leg2Cal.value;
            if (elements.paramFixCal) ticket.fixCal = elements.paramFixCal.value;
            if (elements.paramFixDay) ticket.fixDay = elements.paramFixDay.value;

            // Legacy mirrors
            if (elements.leg1DayCount || elements.paramDayCount) ticket.dayCount = (elements.leg1DayCount || elements.paramDayCount).value;
            if (elements.leg1PaymentFreq || elements.paramPaymentFreq) ticket.paymentFreq = (elements.leg1PaymentFreq || elements.paramPaymentFreq).value;
            if (elements.leg1Convention || elements.paramConvention) ticket.convention = (elements.leg1Convention || elements.paramConvention).value;
            if (elements.leg1Stub || elements.paramStub) ticket.stubRule = (elements.leg1Stub || elements.paramStub).value;
            if (elements.leg1Adjust || elements.paramAdjust) ticket.adjustRule = (elements.leg1Adjust || elements.paramAdjust).value;
            if (elements.leg1PayCal || elements.paramPayCal) ticket.payCal = (elements.leg1PayCal || elements.paramPayCal).value;

            // Pricing reads the per-leg boxes, so those are the source of truth.
            // rc-paste-input is a hidden legacy field kept only for older saved tickets.
            if (elements.rcPasteInputLeg1) ticket.rawPasteText = elements.rcPasteInputLeg1.value;
            else if (elements.rcPasteInput) ticket.rawPasteText = elements.rcPasteInput.value;
            if (elements.rcPasteInputLeg2) ticket.rawPasteTextLeg2 = elements.rcPasteInputLeg2.value;
            ticket.customSchedule = state.customSchedule;
        }

        saveTicketsToStorage();
    }

    function loadTicketToUI(ticket) {
        if (!ticket) return;
        suppressTicketSave = true;
        try {
            loadTicketToUIInner(ticket);
        } finally {
            suppressTicketSave = false;
        }
    }

    function loadTicketToUIInner(ticket) {

        if (elements.ticketClientInput) elements.ticketClientInput.value = ticket.clientName || "";
        if (elements.ticketAliasInput) elements.ticketAliasInput.value = ticket.alias || "";

        if (state.currency === "USD_FWD") {
            if (elements.fwdSpotFx && ticket.fwdSpotFx !== undefined) elements.fwdSpotFx.value = ticket.fwdSpotFx;
            if (elements.fwdDefaultMargin && ticket.fwdDefaultMargin !== undefined) elements.fwdDefaultMargin.value = ticket.fwdDefaultMargin;
            if (elements.fwdPasteTextarea && ticket.fwdPasteText !== undefined) elements.fwdPasteTextarea.value = ticket.fwdPasteText;
            if (ticket.fwdDir && typeof setFwdDirection === "function") setFwdDirection(ticket.fwdDir);
            
            if (ticket.lastPricingResult) {
                fwdPricingResult = ticket.lastPricingResult;
                renderFwdPricingResults(ticket.lastPricingResult);
                if (ticket.lastPricingResult.legs) {
                    renderFwdScheduleTable(ticket.lastPricingResult.legs);
                }
            }
        } else {
            if (elements.notionalDisplay && ticket.notionalDisplay) elements.notionalDisplay.value = ticket.notionalDisplay;
            if (elements.capitalFxRate && ticket.capitalFxRate) elements.capitalFxRate.value = ticket.capitalFxRate;
            if (elements.krwNotionalDisplay && ticket.krwNotionalDisplay) elements.krwNotionalDisplay.value = ticket.krwNotionalDisplay;
            if (ticket.position) setTradePosition(ticket.position);
            
            state.selectedTenor = ticket.selectedTenor || "5Y";
            updateTenorChipsUI(state.selectedTenor);
            if (elements.customTenorInput && ticket.customTenorInput) elements.customTenorInput.value = ticket.customTenorInput;
            
            if (elements.effectiveDateInput && ticket.effectiveDate) elements.effectiveDateInput.value = ticket.effectiveDate;
            if (elements.maturityDateInput && ticket.maturityDate) elements.maturityDateInput.value = ticket.maturityDate;
            if (elements.couponInput && ticket.coupon !== undefined) elements.couponInput.value = ticket.coupon;
            if (elements.spreadInput && ticket.spreadBp !== undefined) elements.spreadInput.value = ticket.spreadBp;

            if (ticket.curveType) setCurveType(ticket.curveType, false);
            if (ticket.crsSwapType) setCrsSwapType(ticket.crsSwapType, false);
            if (elements.usdFixedCouponInput && ticket.usdFixedCoupon !== undefined) {
                elements.usdFixedCouponInput.value = ticket.usdFixedCoupon;
            }

            // Leg 1
            const l1Dc = ticket.leg1DayCount || ticket.dayCount;
            if (elements.leg1DayCount && l1Dc) elements.leg1DayCount.value = l1Dc;
            else if (elements.paramDayCount && l1Dc) elements.paramDayCount.value = l1Dc;

            const l1Freq = ticket.leg1PaymentFreq || ticket.paymentFreq;
            if (elements.leg1PaymentFreq && l1Freq) elements.leg1PaymentFreq.value = l1Freq;
            else if (elements.paramPaymentFreq && l1Freq) elements.paramPaymentFreq.value = l1Freq;

            const l1Conv = ticket.leg1Convention || ticket.convention;
            if (elements.leg1Convention && l1Conv) elements.leg1Convention.value = l1Conv;
            else if (elements.paramConvention && l1Conv) elements.paramConvention.value = l1Conv;

            const l1Stub = ticket.leg1Stub || ticket.stubRule;
            if (elements.leg1Stub && l1Stub) elements.leg1Stub.value = l1Stub;
            else if (elements.paramStub && l1Stub) elements.paramStub.value = l1Stub;

            const l1Adj = ticket.leg1Adjust || ticket.adjustRule;
            if (elements.leg1Adjust && l1Adj) elements.leg1Adjust.value = l1Adj;
            else if (elements.paramAdjust && l1Adj) elements.paramAdjust.value = l1Adj;

            const l1Cal = ticket.leg1PayCal || ticket.payCal;
            if (elements.leg1PayCal && l1Cal) elements.leg1PayCal.value = l1Cal;
            else if (elements.paramPayCal && l1Cal) elements.paramPayCal.value = l1Cal;

            // Leg 2
            if (elements.leg2DayCount && ticket.leg2DayCount) elements.leg2DayCount.value = ticket.leg2DayCount;
            if (elements.leg2PaymentFreq && ticket.leg2PaymentFreq) elements.leg2PaymentFreq.value = ticket.leg2PaymentFreq;
            if (elements.leg2Convention && ticket.leg2Convention) elements.leg2Convention.value = ticket.leg2Convention;
            if (elements.leg2Stub && ticket.leg2Stub) elements.leg2Stub.value = ticket.leg2Stub;
            if (elements.leg2Adjust && ticket.leg2Adjust) elements.leg2Adjust.value = ticket.leg2Adjust;
            if (elements.leg2Cal && ticket.leg2Cal) elements.leg2Cal.value = ticket.leg2Cal;

            if (elements.paramFixCal && ticket.fixCal) elements.paramFixCal.value = ticket.fixCal;
            if (elements.paramFixDay && ticket.fixDay !== undefined) elements.paramFixDay.value = ticket.fixDay;
            
            const paste = ticket.rawPasteText || "";
            if (elements.rcPasteInputLeg1) elements.rcPasteInputLeg1.value = paste;
            if (elements.rcPasteInputLeg2) {
                elements.rcPasteInputLeg2.value = ticket.rawPasteTextLeg2 || paste;
            }
            if (elements.rcPasteInput) elements.rcPasteInput.value = paste;
            // A schedule arriving from a term sheet is easy to miss inside a collapsed
            // card, so open it when there is one to look at.
            if (paste.trim()) revealPasteCard();
            state.customSchedule = ticket.customSchedule || null;
            reflectLoadedSchedule();

            if (ticket.lastPricingResult) {
                state.pricingResult = ticket.lastPricingResult;
                renderPricingResults(ticket.lastPricingResult);
                renderSchedules(ticket.lastPricingResult.schedules, ticket.lastPricingResult.principal_flows);
                elements.calcStatus.textContent = "Pricing Ready";
                elements.calcStatus.className = "calc-status-badge calc-ready";
            }
        }
    }

    function renderTicketBar() {
        if (!elements.ticketsScrollContainer) return;
        elements.ticketsScrollContainer.innerHTML = "";

        const currentList = ticketsStore[state.currency] || [];
        const activeId = activeTicketIdByProduct[state.currency];
        const currentSnapTime = state.currency === "USD_FWD" ? (state.fwdMarketSnapshot ? state.fwdMarketSnapshot.timestamp : null) : (state.marketSnapshot ? state.marketSnapshot.timestamp : null);

        currentList.forEach((ticket, idx) => {
            const isActive = ticket.id === activeId;
            const isLive = Boolean(currentSnapTime && ticket.pricedCurveTimestamp && ticket.pricedCurveTimestamp === currentSnapTime);
            
            // Extract Par Rate or FWD SP label
            let rateStr = "--";
            if (ticket.lastPricingResult) {
                if (state.currency === "USD_FWD") {
                    const sp = ticket.lastPricingResult.weighted_avg_sp;
                    if (sp !== undefined && sp !== null) rateStr = `${sp.toFixed(2)}원`;
                } else {
                    const res = ticket.lastPricingResult.pricing_results || ticket.lastPricingResult;
                    const pRate = res.par_crs_rate_pct !== undefined ? res.par_crs_rate_pct : (res.par_swap_rate_pct !== undefined ? res.par_swap_rate_pct : null);
                    if (pRate !== null && pRate !== undefined) rateStr = `${pRate.toFixed(4)}%`;
                }
            }

            if (ticket.reviewState === "pending") rateStr = "검토 대기";

            const pill = document.createElement("div");
            pill.className = `quote-ticket-pill ${isActive ? "active" : ""}`
                + (ticket.reviewState === "pending" ? " needs-review" : "");
            pill.dataset.ticketId = ticket.id;

            const clientLabel = ticket.clientName && ticket.clientName !== "General" ? ticket.clientName : (ticket.alias || `Ticket ${idx + 1}`);
            const tenorLabel = ticket.selectedTenor || (state.currency === "USD_FWD" ? "FWD" : "5Y");

            pill.innerHTML = `
                <span class="ticket-status-dot ${isLive ? 'live' : 'stale'}" title="${isLive ? 'Live: Evaluated on Current Market Curve' : 'Stale: Market Curve updated'}">●</span>
                <span class="ticket-client-tag" title="${ticket.clientName || ''} - ${ticket.alias || ''}">${clientLabel}</span>
                <span class="ticket-tenor-badge">${tenorLabel}</span>
                <span class="ticket-rate-tag">${rateStr}</span>
                <button type="button" class="btn-ticket-dup" title="Duplicate ticket (동일 조건 복제)">⧉</button>
                ${currentList.length > 1 ? `<button type="button" class="btn-ticket-close" title="Close ticket (삭제)">×</button>` : ''}
            `;

            // Click on pill to switch
            pill.addEventListener("click", (e) => {
                if (e.target.closest(".btn-ticket-dup") || e.target.closest(".btn-ticket-close")) return;
                switchTicket(ticket.id);
            });

            // Duplicate button
            const btnDup = pill.querySelector(".btn-ticket-dup");
            if (btnDup) {
                btnDup.addEventListener("click", (e) => {
                    e.stopPropagation();
                    duplicateTicket(ticket.id);
                });
            }

            // Close button
            const btnClose = pill.querySelector(".btn-ticket-close");
            if (btnClose) {
                btnClose.addEventListener("click", (e) => {
                    e.stopPropagation();
                    deleteTicket(ticket.id);
                });
            }

            elements.ticketsScrollContainer.appendChild(pill);
        });
    }

    function createTicket(curr = state.currency) {
        saveActiveTicketFormData();
        const newTicket = getDefaultTicketData(curr);
        const count = (ticketsStore[curr] || []).length + 1;
        newTicket.alias = `Quote #${count}`;
        
        if (!ticketsStore[curr]) ticketsStore[curr] = [];
        ticketsStore[curr].push(newTicket);
        activeTicketIdByProduct[curr] = newTicket.id;
        
        saveTicketsToStorage();
        renderTicketBar();
        loadTicketToUI(newTicket);
        
        showToast(`새 호가 티켓이 생성되었습니다. (#${count})`, "info");
        if (state.currency === "USD_FWD") {
            calculateFwdPricing();
        } else {
            calculatePricing();
        }
    }

    function duplicateTicket(sourceTicketId) {
        saveActiveTicketFormData();
        const list = ticketsStore[state.currency] || [];
        const source = list.find(t => t.id === sourceTicketId) || getActiveTicket();
        if (!source) return;

        const cloned = JSON.parse(JSON.stringify(source));
        cloned.id = `ticket_${state.currency}_${Date.now()}_${Math.floor(Math.random()*1000)}`;
        cloned.alias = `${source.alias || source.clientName || 'Quote'} (Copy)`;
        
        const srcIndex = list.findIndex(t => t.id === source.id);
        if (srcIndex >= 0) {
            list.splice(srcIndex + 1, 0, cloned);
        } else {
            list.push(cloned);
        }

        activeTicketIdByProduct[state.currency] = cloned.id;
        saveTicketsToStorage();
        renderTicketBar();
        loadTicketToUI(cloned);
        showToast(`[${cloned.alias}] 티켓이 복제되었습니다`, "success");
    }

    function deleteTicket(ticketId) {
        const list = ticketsStore[state.currency] || [];
        if (list.length <= 1) {
            showToast("최소 1개의 호가 탭이 유지되어야 합니다", "warning");
            return;
        }

        const index = list.findIndex(t => t.id === ticketId);
        if (index < 0) return;

        const isDeletingActive = activeTicketIdByProduct[state.currency] === ticketId;
        list.splice(index, 1);

        if (isDeletingActive) {
            const newActiveIndex = Math.max(0, index - 1);
            activeTicketIdByProduct[state.currency] = list[newActiveIndex].id;
        }

        saveTicketsToStorage();
        renderTicketBar();
        const activeT = getActiveTicket();
        loadTicketToUI(activeT);
        showToast("호가 티켓이 삭제되었습니다", "info");
    }

    function switchTicket(targetId) {
        if (activeTicketIdByProduct[state.currency] === targetId) return;

        saveActiveTicketFormData();
        activeTicketIdByProduct[state.currency] = targetId;
        const targetTicket = getActiveTicket();
        if (!targetTicket) return;

        loadTicketToUI(targetTicket);
        renderTicketBar();

        // Lazy Evaluation: a termsheet ticket must not price before the trader signs off.
        if (targetTicket.reviewState === "pending") return;

        const currentSnapTime = state.currency === "USD_FWD" ? (state.fwdMarketSnapshot ? state.fwdMarketSnapshot.timestamp : null) : (state.marketSnapshot ? state.marketSnapshot.timestamp : null);
        if (!targetTicket.lastPricingResult || targetTicket.pricedCurveTimestamp !== currentSnapTime) {
            if (state.currency === "USD_FWD") {
                calculateFwdPricing();
            } else {
                calculatePricing();
            }
        }
    }

    function updateActiveTicketPricingResult(pricingData, snapshotTime) {
        const ticket = getActiveTicket();
        if (!ticket) return;
        ticket.lastPricingResult = pricingData;
        ticket.pricedCurveTimestamp = snapshotTime || (state.currency === "USD_FWD" ? (state.fwdMarketSnapshot ? state.fwdMarketSnapshot.timestamp : null) : (state.marketSnapshot ? state.marketSnapshot.timestamp : null));
        ticket.lastCalculatedAt = new Date().toLocaleTimeString('ko-KR', { hour12: false });
        saveTicketsToStorage();
        renderTicketBar();
    }

    function copySwapQuoteToClipboard() {
        const activeTicket = getActiveTicket();
        if (!activeTicket || !activeTicket.lastPricingResult) {
            showToast("먼저 프라이싱을 실행해주세요 (F9 / Enter).", "warning");
            return;
        }
        const res = activeTicket.lastPricingResult.pricing_results || activeTicket.lastPricingResult;
        const isKrw = state.currency.startsWith("KRW");
        const isCrs = state.currency === "KRW_CRS";
        const isFixedFixed = isCrs && activeTicket.crsSwapType === "Fixed-Fixed";
        const parRate = isFixedFixed ? (res.par_krw_rate_pct !== undefined ? res.par_krw_rate_pct : res.par_crs_rate_pct) : (res.par_crs_rate_pct !== undefined ? res.par_crs_rate_pct : (res.par_swap_rate_pct !== undefined ? res.par_swap_rate_pct : 0.0));
        const dealNpv = res.deal_npv_krw !== undefined ? res.deal_npv_krw : (res.deal_npv !== undefined ? res.deal_npv : 0.0);
        const dv01 = res.deal_pv01_krw !== undefined ? res.deal_pv01_krw : (res.krw_dv01 !== undefined ? res.krw_dv01 : (res.dv01 !== undefined ? res.dv01 : 0.0));
        
        const clientStr = activeTicket.clientName && activeTicket.clientName !== "General" ? `[${activeTicket.clientName}] ` : "";
        const aliasStr = activeTicket.alias || `${activeTicket.selectedTenor || '5Y'} ${activeTicket.position || 'Pay Fixed'}`;
        let prodName = state.currency === "USD" ? `USD SOFR OIS (${activeTicket.curveType || 'Standard'})` : (state.currency === "KRW" ? "KRW CD 91d IRS" : (state.currency === "KRW_KOFR" ? "KRW KOFR OIS" : "KRW FX SOFR CRS"));
        if (isFixedFixed) prodName += " [Fixed-to-Fixed]";

        let text = `[RFQ 호가 회신] ${clientStr}${aliasStr}\n`;
        text += `━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`;
        text += `▸ 상품명: ${prodName}\n`;
        text += `\u25B8 포지션: ${activeTicket.position || 'Pay Fixed'}\n`;
        text += `▸ 명목원금: ${isKrw ? '₩ ' : '$ '}${activeTicket.notionalDisplay || '100,000,000'}\n`;
        if (activeTicket.effectiveDate && activeTicket.maturityDate) {
            text += `\u25B8 거래기간: ${activeTicket.effectiveDate} ~ ${activeTicket.maturityDate} (${activeTicket.selectedTenor || ''})\n`;
        }
        if (isFixedFixed) {
            text += `\u25B8 KRW 고정금리: ${parseFloat(activeTicket.coupon || 0).toFixed(4)} %\n`;
            text += `\u25B8 USD 고정금리: ${parseFloat(activeTicket.usdFixedCoupon || 3.5).toFixed(4)} %\n`;
            text += `▸ Par KRW Rate: ${parRate.toFixed(4)} % (USD Cpn 기준)\n`;
            if (res.par_usd_rate_pct !== undefined) {
                text += `▸ Par USD Rate: ${res.par_usd_rate_pct.toFixed(4)} % (KRW Cpn 기준)\n`;
            }
        } else {
            text += `\u25B8 고정금리: ${parseFloat(activeTicket.coupon || 0).toFixed(4)} %\n`;
            text += `\u25B8 Par Swap Rate: ${parRate.toFixed(4)} %\n`;
        }
        text += `\u25B8 Deal NPV: ${formatCurrency(dealNpv, isKrw)}\n`;
        text += `\u25B8 DV01 / PV01: ${formatCurrency(dv01, isKrw)} / bp\n`;
        text += `▸ 산출시각: ${activeTicket.lastCalculatedAt || new Date().toLocaleTimeString()} (${state.marketSnapshot?.source || 'LSEG Live'})\n`;
        text += `━━━━━━━━━━━━━━━━━━━━━━━━━━━`;

        navigator.clipboard.writeText(text).then(() => {
            showToast("메신저용 호가 정보가 클립보드에 복사되었습니다", "success");
        }).catch(err => {
            console.error("Clipboard copy error:", err);
            showToast("클립보드 복사 실패", "warning");
        });
    }

    // Auto-save form inputs to active ticket on input/change
    const inputsToSync = [
        elements.notionalDisplay,
        elements.capitalFxRate,
        elements.krwNotionalDisplay,
        elements.couponInput,
        elements.spreadInput,
        elements.usdFixedCouponInput,
        elements.customTenorInput,
        elements.effectiveDateInput,
        elements.maturityDateInput,
        elements.leg1DayCount,
        elements.leg1PaymentFreq,
        elements.leg1Convention,
        elements.leg1Stub,
        elements.leg1Adjust,
        elements.leg1PayCal,
        elements.leg2DayCount,
        elements.leg2PaymentFreq,
        elements.leg2Convention,
        elements.leg2Stub,
        elements.leg2Adjust,
        elements.leg2Cal,
        elements.paramDayCount,
        elements.paramPaymentFreq,
        elements.paramFixCal,
        elements.paramPayCal,
        elements.paramConvention,
        elements.paramStub,
        elements.paramAdjust,
        elements.paramFixDay,
        elements.rcPasteInput,
        elements.fwdSpotFx,
        elements.fwdDefaultMargin,
        elements.fwdPasteTextarea
    ];

    inputsToSync.forEach(inputEl => {
        if (inputEl) {
            inputEl.addEventListener("input", () => saveActiveTicketFormData());
            inputEl.addEventListener("change", () => saveActiveTicketFormData());
        }
    });


    // Metadata & Quick Action Toolbar Listeners
    if (elements.ticketClientInput) {
        elements.ticketClientInput.addEventListener("input", (e) => {
            const ticket = getActiveTicket();
            if (ticket) {
                ticket.clientName = e.target.value.trim();
                saveTicketsToStorage();
                renderTicketBar();
            }
        });
    }
    if (elements.ticketAliasInput) {
        elements.ticketAliasInput.addEventListener("input", (e) => {
            const ticket = getActiveTicket();
            if (ticket) {
                ticket.alias = e.target.value.trim();
                saveTicketsToStorage();
                renderTicketBar();
            }
        });
    }
    if (elements.btnNewTicket) {
        elements.btnNewTicket.addEventListener("click", () => createTicket(state.currency));
    }
    if (elements.btnDuplicateTicket) {
        elements.btnDuplicateTicket.addEventListener("click", () => duplicateTicket(activeTicketIdByProduct[state.currency]));
    }
    if (elements.btnCopyQuoteTop) {
        elements.btnCopyQuoteTop.addEventListener("click", copySwapQuoteToClipboard);
    }
    if (elements.btnSwapCopyMessenger) {
        elements.btnSwapCopyMessenger.addEventListener("click", copySwapQuoteToClipboard);
    }

    // Live Clock
    setInterval(() => {
        if (elements.systemClock) {
            elements.systemClock.textContent = new Date().toLocaleTimeString();
        }
        refreshStaleness();
    }, 1000);

    // Hotkeys: F5 (Reload), Enter (Price), F9 (Reload & Price)
    document.addEventListener("keydown", (e) => {
        if (e.key === "F9") {
            e.preventDefault();
            if (isAwaitingTermsheetReview()) {
                showToast("Term Sheet 조건을 검토하고 확인을 누르세요", "warning");
                if (ts.confirm && !ts.confirm.disabled) ts.confirm.focus();
                return;
            }
            if (state.currency === "USD_FWD") {
                reloadAndPriceFwd();
            } else {
                reloadAndPrice();
            }
        } else if (e.key === "F5") {
            e.preventDefault();
            if (state.currency === "USD_FWD") {
                fetchFwdMarketSnapshot(true);
            } else {
                loadMarketSnapshot(true);
            }
        } else if (e.key === "Enter") {
            const tag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
            if (tag !== "textarea") {
                e.preventDefault();
                if (state.currency === "USD_FWD") {
                    calculateFwdPricing();
                } else {
                    calculatePricing();
                }
            }
        }
    });

    // Initial Startup Load.
    // setCurrency returns early when the target matches the current state, which it
    // always does on boot ("USD"), so the first market pull has to be explicit -
    // otherwise the dashboard paints with placeholder numbers and an empty quote table
    // until someone presses F5/F9.
    initTicketWorkspace();
    setCurrency("USD");
    loadMarketSnapshot();
});

