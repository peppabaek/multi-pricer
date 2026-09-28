/* ==========================================================================
   MULTIPRICER — 휴대폰 화면.

   PC 화면(app.js, 5,300줄)의 축소판이 아니라 별개의 작은 화면입니다. 같은 JSON
   API 를 부르고, 통화별 응답 차이는 pricing-core.js 한 곳에만 있습니다.

   화면에 보이는 입력은 여섯 개뿐이지만 요청까지 여섯 개인 것은 아닙니다 —
   Term Sheet 을 읽어들이면 문서에 적힌 컨벤션과 상각 스케줄이 overrides 로
   요청에 함께 실립니다. 안 그러면 Act/365 짜리 거래를 Act/360 으로 계산해놓고
   화면은 멀쩡해 보입니다.
   ========================================================================== */
(function () {
    "use strict";

    const C = window.PricingCore;
    const $ = (id) => document.getElementById(id);

    const TENORS = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"];
    const RELAY_POLL_MS = 20000;

    const state = {
        currency: "USD",
        notional: 100000000,
        position: "Pay Fixed",
        tenor: "5Y",
        coupon: "",
        spreadBp: "0.0",
        effectiveDate: "",
        maturityDate: "",
        crsSwapType: "Vanilla",
        overrides: null,      // Term Sheet 에서 온 컨벤션 + 스케줄
        tsSummary: "",        // 무엇이 적용됐는지 사람이 읽을 한 줄
        priced: null,         // 마지막 결과
        pricedAt: 0,
    };

    let lastRelay = null;     // 절대 시각을 들고 있어야 배지가 스스로 흘러갑니다
    let lastLive = false;
    let busyDepth = 0;

    // ---- 화면 만들기 -------------------------------------------------------

    function buildTabs() {
        const wrap = $("product-tabs");
        wrap.innerHTML = "";
        C.ORDER.forEach((cur) => {
            const b = document.createElement("button");
            b.type = "button";
            b.id = "tab-" + cur.toLowerCase().replace(/_/g, "-");
            b.dataset.currency = cur;
            b.textContent = C.PRODUCTS[cur].short;
            b.title = C.PRODUCTS[cur].label;
            b.addEventListener("click", () => setCurrency(cur));
            wrap.appendChild(b);
        });
    }

    function buildTenors() {
        const wrap = $("tenor-chips");
        wrap.innerHTML = "";
        TENORS.forEach((t) => {
            const b = document.createElement("button");
            b.type = "button";
            b.dataset.tenor = t;
            b.textContent = t;
            b.addEventListener("click", () => {
                state.tenor = t;
                // 만기일을 직접 넣어둔 채 테너를 누르면 서버는 만기일을 씁니다.
                // 눌러도 아무 일이 없는 것처럼 보이므로, 테너를 고르면 비웁니다.
                if (state.maturityDate) {
                    state.maturityDate = "";
                    $("in-mat").value = "";
                    toast("만기일 지정을 해제하고 " + t + " 로 계산합니다");
                }
                paintInputs();
                price(false);
            });
            wrap.appendChild(b);
        });
    }

    function paintInputs() {
        C.ORDER.forEach((cur) => {
            const el = document.querySelector('[data-currency="' + cur + '"]');
            if (el) el.classList.toggle("on", cur === state.currency);
        });
        TENORS.forEach((t) => {
            const el = document.querySelector('[data-tenor="' + t + '"]');
            if (el) el.classList.toggle("on", t === state.tenor && !state.maturityDate);
        });
        const applied = Boolean(state.overrides);
        $("ts-applied").hidden = !applied;
        if (applied) $("ts-applied-text").textContent = state.tsSummary;
    }

    // ---- 결과 --------------------------------------------------------------

    function paintResults() {
        const out = $("results");
        if (!state.priced) {
            $("out-par").textContent = "—";
            $("out-par").classList.add("empty");
            $("out-spread").textContent = "";
            $("out-npv").textContent = "—";
            $("out-dv01").textContent = "—";
            $("out-extra").hidden = true;
            $("out-stamp").textContent = "";
            out.classList.remove("stale");
            return;
        }
        const r = C.readResults(state.currency, state.priced);
        $("out-par").textContent = C.pct(r.par);
        $("out-par").classList.toggle("empty", r.par === null || r.par === undefined);

        const sp = r.spreadBp;
        $("out-spread").textContent =
            (sp === null || sp === undefined) ? ""
            : "Spread vs Cpn: " + (sp >= 0 ? "+" : "") + Number(sp).toFixed(2) + " bp";

        $("out-npv").textContent = C.money(r.npv, r.npvCcy);
        $("out-dv01").textContent = C.money(r.dv01, r.dv01Ccy);

        const extra = $("out-extra");
        if (r.extra && r.extra.length) {
            extra.innerHTML = "";
            r.extra.forEach((e) => {
                const s = document.createElement("span");
                s.textContent = e.label + "  " + C.money(e.value, e.ccy);
                extra.appendChild(s);
            });
            extra.hidden = false;
        } else {
            extra.hidden = true;
        }

        const snap = (state.priced.snapshot_info || {});
        const bits = [];
        if (snap.timestamp) bits.push("호가 " + snap.timestamp);
        if (snap.settle_date) bits.push("settle " + snap.settle_date);
        $("out-stamp").textContent = bits.join(" · ");
    }

    /**
     * 값이 늙었음을 화면에 남긴다.
     *
     * 프라이싱한 뒤 시세가 오래되면 숫자는 그대로인데 근거가 사라집니다.
     * 지우지는 않고 - 방금 본 값을 잃는 것도 곤란하므로 - 흐리게 만듭니다.
     */
    function markStaleness() {
        const out = $("results");
        if (!state.priced) return;
        const feedStale = lastRelay ? Boolean(lastRelay._stale) : !lastLive;
        const old = (Date.now() - state.pricedAt) > 180000;   // 3분
        out.classList.toggle("stale", feedStale || old);
    }

    // ---- 시세 배지 ---------------------------------------------------------

    function paintFeed() {
        const st = C.feedState(lastLive, lastRelay);
        const b = $("feed-badge");
        b.textContent = st.label;
        b.title = st.title;
        b.className = "m-feed " + st.kind + (st.stale ? " stale" : "");
        markStaleness();
    }

    /** 배지가 매초 스스로 나이를 센다. 한 번 그리고 말면 데스크가 멈춰도 얼어붙습니다. */
    function tickFeed() {
        if (!lastRelay || !lastRelay.active || !lastRelay.source_epoch_ms) return;
        const age = Math.max(0, (Date.now() - lastRelay.source_epoch_ms) / 1000);
        const limit = lastRelay.stale_after_seconds || 90;
        lastRelay.age_seconds = age;
        lastRelay.stale = lastRelay.clock_skewed || age > limit;
        lastRelay._stale = lastRelay.stale;
        paintFeed();
    }

    async function pollFeed() {
        try {
            const [lsegR, relayR] = await Promise.all([
                fetch("/api/lseg/status"), fetch("/api/quotes/relay-status"),
            ]);
            if (lsegR.ok) {
                const d = (await lsegR.json()).data || {};
                lastLive = Boolean(d.is_live_connected);
            }
            if (relayR.ok) {
                const all = (await relayR.json()).data || {};
                const st = C.relayFor(all, state.currency);
                lastRelay = st ? Object.assign({}, st, { _stale: st.stale }) : null;
            }
            paintFeed();
        } catch (e) {
            /* 폴링 실패가 화면을 망가뜨리지는 않습니다 */
        }
    }

    // ---- 프라이싱 ----------------------------------------------------------

    function readForm() {
        state.notional = C.numOrDefault($("in-notional").value, 0);
        state.position = $("in-position").value;
        state.coupon = $("in-coupon").value;
        state.spreadBp = $("in-spread").value;
        state.effectiveDate = $("in-eff").value || "";
        state.maturityDate = $("in-mat").value || "";
    }

    async function price(reload) {
        readForm();
        if (!(state.notional > 0)) {
            notice("명목금액을 입력하세요", true);
            return;
        }
        const p = C.PRODUCTS[state.currency];
        const url = reload ? p.reload : p.price;
        busy(true, reload ? "시세 갱신 후 계산 중…" : "계산 중…");
        try {
            const resp = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(C.buildRequest(state)),
            });
            const json = await resp.json();
            if (!resp.ok) throw new Error(json.detail || ("HTTP " + resp.status));
            state.priced = json.data;
            state.pricedAt = Date.now();
            notice("");
            paintResults();
            await pollFeed();
            if (reload) toast("시세를 갱신하고 계산했습니다");
        } catch (err) {
            // 실패했는데 옛 숫자가 그대로 남아 있으면 성공한 것처럼 읽힙니다.
            state.priced = null;
            paintResults();
            notice("계산 실패: " + err.message, true);
        } finally {
            busy(false);
        }
    }

    // ---- Term Sheet --------------------------------------------------------

    let tsPending = null;

    async function uploadTermsheet(file) {
        if (!file) return;
        busy(true, (file.name || "문서") + " 분석 중…");
        try {
            const body = new FormData();
            body.append("file", file, file.name || "upload");
            const resp = await fetch("/api/termsheet/extract", { method: "POST", body });
            const json = await resp.json();
            if (!resp.ok) throw new Error(json.detail || ("HTTP " + resp.status));
            const data = json.data;
            if (!data.supported) {
                notice("평가 불가: " + (data.unsupported_reason || "알 수 없음"), true);
                return;
            }
            tsPending = data;
            renderReview(data, file.name);
            $("ts-modal").hidden = false;
        } catch (err) {
            notice("Term Sheet 분석 실패: " + err.message, true);
        } finally {
            busy(false);
            $("ts-file").value = "";
        }
    }

    // 휴대폰 화면이 실제로 쓰는 값들. PC 팝업은 20개가 넘지만, 여기서는 확인할
    // 수 있는 것만 보여주고 나머지 컨벤션은 그대로 요청에 실어 보냅니다.
    const REVIEW_ROWS = [
        ["product", "상품"], ["position", "포지션"], ["notionalDisplay", "명목"],
        ["customTenorInput", "테너"], ["effectiveDate", "개시일"],
        ["maturityDate", "만기일"], ["coupon", "쿠폰(%)"], ["spreadBp", "스프레드(bp)"],
        ["crsSwapType", "CRS 유형"],
    ];
    const CONV_ROWS = [
        ["leg1DayCount", "Leg1 이자계산"], ["leg1PaymentFreq", "Leg1 지급주기"],
        ["leg1Convention", "Leg1 영업일"], ["leg1Stub", "Leg1 스텁"],
        ["leg2DayCount", "Leg2 이자계산"], ["leg2PaymentFreq", "Leg2 지급주기"],
        ["leg2Convention", "Leg2 영업일"], ["leg2Stub", "Leg2 스텁"],
    ];

    function renderReview(data, filename) {
        const t = data.ticket_draft || {};
        const inferred = new Set(data.inferred_fields || []);
        const body = $("ts-modal-body");
        body.innerHTML = "";
        $("ts-modal-title").textContent = filename || "Term Sheet 분석 결과";

        const red = data.redaction && data.redaction.counts;
        if (red) {
            const n = Object.keys(red).reduce((a, k) => a + red[k], 0);
            if (n > 0) add(body, "div", "ts-warn",
                "민감정보 " + n + "건을 제거한 뒤 분석했습니다 · 원본은 저장하지 않습니다");
        }

        rows(body, "거래조건", REVIEW_ROWS, t, inferred);
        rows(body, "컨벤션 (그대로 계산에 반영됩니다)", CONV_ROWS, t, inferred);

        const sched = data.schedule_preview || [];
        if (sched.length) {
            add(body, "div", "ts-sec", "스케줄 " + sched.length + "개 기간");
            const first = sched[0].notional, last = sched[sched.length - 1].notional;
            if (first !== last) {
                add(body, "div", "ts-warn",
                    "상각(Amortising) — " + C.commas(first) + " → " + C.commas(last)
                    + ". 이 스케줄 그대로 계산합니다.");
            }
            const wrap = add(body, "div", "ts-sched", "");
            const tb = document.createElement("table");
            tb.innerHTML = "<thead><tr><th>#</th><th>Start</th><th>End</th>"
                + "<th>Pay</th><th>Nominal</th></tr></thead>";
            const tbody = document.createElement("tbody");
            sched.forEach((p, i) => {
                const tr = document.createElement("tr");
                tr.innerHTML = "<td>" + (p.no || i + 1) + "</td>"
                    + "<td>" + (p.start_date || "") + "</td>"
                    + "<td>" + (p.end_date || "") + "</td>"
                    + "<td>" + (p.pay_date || "") + "</td>"
                    + '<td class="amt' + (i > 0 && sched[i - 1].notional !== p.notional ? " cut" : "")
                    + '">' + C.commas(p.notional) + "</td>";
                tbody.appendChild(tr);
            });
            tb.appendChild(tbody);
            wrap.appendChild(tb);
        }

        const q = data.open_questions || [];
        if (q.length) {
            add(body, "div", "ts-sec", "카운터파티에 확인할 사항");
            q.forEach((x) => add(body, "div", "ts-warn", "· " + x));
        }
    }

    function rows(parent, title, defs, t, inferred) {
        const present = defs.filter(([k]) => t[k] !== undefined && t[k] !== null && t[k] !== "");
        if (!present.length) return;
        add(parent, "div", "ts-sec", title);
        present.forEach(([k, label]) => {
            const guessed = inferred.has(snake(k));
            const row = add(parent, "div", "ts-row" + (guessed ? " guess" : ""), "");
            add(row, "span", "k", label);
            const v = add(row, "span", "v", String(t[k]));
            if (guessed) add(v, "span", "why", "문서에 없음 — 시장 관행 적용");
        });
    }

    function snake(s) { return s.replace(/([A-Z0-9])/g, "_$1").toLowerCase(); }

    function add(parent, tag, cls, text) {
        const el = document.createElement(tag);
        if (cls) el.className = cls;
        if (text) el.textContent = text;
        parent.appendChild(el);
        return el;
    }

    function applyTermsheet() {
        if (!tsPending) return;
        const t = tsPending.ticket_draft || {};

        if (t.product && C.PRODUCTS[t.product]) state.currency = t.product;
        if (t.position) state.position = t.position;
        if (t.notionalDisplay) $("in-notional").value = C.commas(t.notionalDisplay);
        if (t.customTenorInput) state.tenor = t.customTenorInput;
        if (t.effectiveDate) $("in-eff").value = t.effectiveDate;
        if (t.maturityDate) $("in-mat").value = t.maturityDate;
        if (t.coupon) $("in-coupon").value = t.coupon;
        if (t.spreadBp !== undefined && t.spreadBp !== null) $("in-spread").value = t.spreadBp;
        if (t.crsSwapType) state.crsSwapType = t.crsSwapType;
        $("in-position").value = state.position;
        if (t.effectiveDate || t.maturityDate) $("date-block").open = true;

        state.overrides = C.overridesFromTicket(t);
        const n = (tsPending.schedule_preview || []).length;
        state.tsSummary = "Term Sheet 조건 적용중"
            + (n ? " · 스케줄 " + n + "개 기간" : " · 컨벤션");

        tsPending = null;
        $("ts-modal").hidden = true;
        paintInputs();
        price(false);
    }

    function clearTermsheet() {
        state.overrides = null;
        state.tsSummary = "";
        paintInputs();
        toast("Term Sheet 조건을 해제했습니다 — 시장 관행으로 계산합니다");
        price(false);
    }

    // ---- 잡다 --------------------------------------------------------------

    function setCurrency(cur) {
        if (cur === state.currency) return;
        state.currency = cur;
        // 통화가 바뀌면 이전 통화로 계산한 숫자는 틀린 값입니다. 지웁니다.
        state.priced = null;
        paintInputs();
        paintResults();
        pollFeed();
        price(false);
    }

    function busy(on, text) {
        busyDepth = Math.max(0, busyDepth + (on ? 1 : -1));
        $("busy").hidden = busyDepth === 0;
        if (on && text) $("busy-text").textContent = text;
        const off = busyDepth > 0;
        $("btn-price").disabled = off;
        $("btn-reload").disabled = off;
        $("ts-btn").disabled = off;
    }

    function notice(msg, bad) {
        const el = $("notice");
        el.hidden = !msg;
        el.textContent = msg || "";
        el.className = "m-note" + (bad ? " bad" : "");
    }

    let toastTimer = null;
    function toast(msg, kind) {
        const el = $("toast");
        el.textContent = msg;
        el.className = "m-toast" + (kind ? " " + kind : "");
        el.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
    }

    // ---- 시작 --------------------------------------------------------------

    function init() {
        buildTabs();
        buildTenors();
        paintInputs();
        paintResults();

        $("btn-price").addEventListener("click", () => price(false));
        $("btn-reload").addEventListener("click", () => price(true));
        $("feed-badge").addEventListener("click", () => { toast("시세 상태 확인 중…"); pollFeed(); });

        $("ts-btn").addEventListener("click", () => $("ts-file").click());
        $("ts-file").addEventListener("change", (e) => uploadTermsheet(e.target.files[0]));
        $("ts-confirm").addEventListener("click", applyTermsheet);
        $("ts-cancel").addEventListener("click", () => { tsPending = null; $("ts-modal").hidden = true; });
        $("ts-close").addEventListener("click", () => { tsPending = null; $("ts-modal").hidden = true; });
        $("ts-clear").addEventListener("click", clearTermsheet);

        // 명목금액은 치는 동안 천단위를 넣어줍니다. 0 이 몇 개인지 세는 건
        // 휴대폰에서 특히 틀리기 쉽습니다.
        $("in-notional").addEventListener("blur", (e) => {
            const n = C.numOrNull(e.target.value);
            if (n !== null) e.target.value = C.commas(n);
        });

        setInterval(tickFeed, 1000);
        setInterval(pollFeed, RELAY_POLL_MS);
        setInterval(markStaleness, 5000);

        pollFeed();
        price(false);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
