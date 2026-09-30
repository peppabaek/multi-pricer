# -*- coding: utf-8 -*-
"""
L29 검토 창이 문서를 그대로 보여주는가.

트레이더가 사진을 올리고 본 것: 9개월짜리 IRS 인데 검토 창의 테너가 3Y.
가격은 맞게 나왔습니다 - 만기일로 계산하니까요. 화면만 틀렸습니다.

조건을 확인하라고 띄운 창이 잘못된 조건을 보여주면, 그 창은 확인이 아니라
승인 도장입니다. 두 가지가 겹쳐 있었습니다.

  1. 모델이 테너를 따로 적어주지 않으면 - 문서에 날짜만 있고 "9 months" 라는
     말이 없으면 흔합니다 - 서버가 통화별 기본값을 채웠습니다. KRW 는 3Y.
  2. 그 값이 '추정' 으로 표시되지도 않았습니다. inferred_fields 는 추출기
     이름(tenor)을 쓰는데 휴대폰 화면은 티켓 키를 camelCase→snake_case 로
     바꿔서 찾았고, customTenorInput → custom_tenor_input 이라 영영 안 맞았습니다.
     지어낸 값이 문서에서 읽은 사실처럼 보였습니다.
"""
import io
import os
import sys

from harness import case, run_all

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

from server.termsheet import tenor_from_dates, to_ticket_draft


def trade(**kw):
    from test_l11_scenarios import _stub
    t = _stub("TS-B")("")
    for k, v in kw.items():
        setattr(t, k, v)
    return t


@case("L29-1", "날짜에서 테너를 읽는다")
def t_1():
    cases = [("2026-09-15", "2031-09-15", "5Y"),
             ("2026-09-15", "2027-06-15", "9M"),
             ("2026-09-15", "2028-03-15", "18M"),
             ("2026-09-15", "2027-09-15", "1Y"),
             ("2026-09-15", "2026-10-01", "2W")]
    for a, b, want in cases:
        got = tenor_from_dates(a, b)
        if got != want:
            raise AssertionError(f"{a} → {b}: {got!r}, 기대 {want!r}")


@case("L29-2", "날짜가 없거나 거꾸로면 지어내지 않는다")
def t_2():
    for a, b in ((None, "2031-09-15"), ("2026-09-15", None), (None, None),
                 ("2031-09-15", "2026-09-15"), ("아무말", "2031-09-15")):
        if tenor_from_dates(a, b) is not None:
            raise AssertionError(f"{a} → {b} 에서 테너를 만들어냄")


@case("L29-3", "모델이 테너를 안 줘도 통화 기본값으로 때우지 않는다")
def t_3():
    # 이것이 트레이더가 본 증상입니다: 9개월 거래에 3Y.
    t = trade(tenor=None, currency="KRW",
              effective_date="2026-09-15", maturity_date="2027-06-15")
    out = to_ticket_draft(t)
    shown = out["draft"]["customTenorInput"]
    if shown == "3Y":
        raise AssertionError("KRW 통화 기본값 3Y 로 때움 — 문서는 9개월입니다")
    if shown != "9M":
        raise AssertionError(f"날짜에서 읽은 9M 이 아님: {shown!r}")


@case("L29-4", "날짜에서 읽은 테너는 '추정'으로 표시하지 않는다")
def t_4():
    # 날짜는 문서에 적힌 사실입니다. 거기서 나온 테너를 "시장 관행 적용" 이라고
    # 하면, 진짜 추정값과 구분이 사라집니다.
    t = trade(tenor=None, currency="USD",
              effective_date="2026-09-15", maturity_date="2027-06-15")
    out = to_ticket_draft(t)
    if "tenor" in out["inferred_fields"]:
        raise AssertionError("날짜에서 읽었는데 추정으로 표시")


@case("L29-5", "날짜도 없으면 기본값을 쓰되 추정으로 표시한다")
def t_5():
    t = trade(tenor=None, currency="KRW", effective_date=None, maturity_date=None)
    out = to_ticket_draft(t)
    if not out["draft"]["customTenorInput"]:
        raise AssertionError("테너가 비어 있음 — 프라이싱할 수 없습니다")
    if "tenor" not in out["inferred_fields"]:
        raise AssertionError("지어낸 값인데 추정으로 표시하지 않음")


@case("L29-6", "문서가 테너를 적어줬으면 그것이 이긴다")
def t_6():
    t = trade(tenor="2Y", currency="USD",
              effective_date="2026-09-15", maturity_date="2031-09-15")
    out = to_ticket_draft(t)
    if out["draft"]["customTenorInput"] != "2Y":
        raise AssertionError(f"문서의 테너를 덮어씀: {out['draft']['customTenorInput']!r}")
    if "tenor" in out["inferred_fields"]:
        raise AssertionError("문서에 있는 값을 추정으로 표시")


@case("L29-7", "휴대폰 화면이 추정 표시를 규칙으로 유추하지 않는다")
def t_7():
    # camelCase → snake_case 변환은 customTenorInput → custom_tenor_input 이 되어
    # tenor 와 맞지 않았습니다. 데스크톱과 같은 표를 씁니다.
    with io.open(os.path.join(ROOT, "static", "m.js"), encoding="utf-8") as f:
        m = f.read()
    if "snake(" in m:
        raise AssertionError("아직 규칙으로 유추함 — 키가 어긋납니다")
    if "TS_FIELD_KEY" not in m:
        raise AssertionError("공유 표를 쓰지 않음")

    with io.open(os.path.join(ROOT, "static", "pricing-core.js"), encoding="utf-8") as f:
        core = f.read()
    for key in ("customTenorInput", "notionalDisplay"):
        if key not in core:
            raise AssertionError(f"공유 표에 {key} 가 없음")

    # 데스크톱 표와 어긋나면 두 화면이 다른 말을 합니다.
    with io.open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8") as f:
        desk = f.read()
    import re
    def pairs(src, name):
        i = src.find(name)
        body = src[i:src.find("};", i)]
        return dict(re.findall(r"(\w+):\s*\"([\w_]+)\"", body))
    a, b = pairs(desk, "const TS_FIELD_KEY"), pairs(core, "const TS_FIELD_KEY")
    diff = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
    if diff:
        raise AssertionError(f"데스크톱과 휴대폰의 표가 다름: {sorted(diff)}")


@case("L29-8", "사다리가 시간 예산을 넘기면 멈추고 이유를 말한다")
def t_8():
    """
    같은 사진을 연속으로 올렸을 때 배포본 실측: 1회차 17.9초, 2회차 122초,
    3회차 91초. 재시도에 sleep 은 없지만, 프리티어가 분당 한도에 걸리면 한
    모델이 답하는 데만 수십 초가 걸립니다.

    브라우저는 그 전에 끊고, 사용자에게는 "fetch error" 만 남습니다 - 무엇이
    잘못됐는지도, 다시 시도하면 되는지도 알 수 없습니다.
    """
    import time as _t
    import server.termsheet as T

    saved_budget = T._LADDER_BUDGET_SECONDS
    saved_chain = T.extraction_chain
    saved_get = None
    T._LADDER_BUDGET_SECONDS = 1.0
    try:
        import server.providers as P
        saved_get = P.get_extractor
        T.extraction_chain = lambda: ["gemini", "anthropic"]

        calls = {"n": 0}

        def slow(name, model_name=None):
            def _fn(text):
                calls["n"] += 1
                _t.sleep(0.7)
                raise RuntimeError("429 quota exceeded")
            return _fn

        P.get_extractor = slow
        T.get_extractor = slow if hasattr(T, "get_extractor") else None

        try:
            T.call_extractor("테스트 문서 본문")
        except ValueError as e:
            msg = str(e)
            if "초" not in msg:
                raise AssertionError(f"얼마나 걸렸는지 말하지 않음: {msg[:120]}")
            if "다시 시도" not in msg and "GROQ" not in msg:
                raise AssertionError(f"무엇을 하라는 안내가 없음: {msg[:120]}")
        except Exception as e:
            raise AssertionError(f"예상 밖 예외: {type(e).__name__}: {e}")
        else:
            raise AssertionError("예산을 넘겼는데 그냥 통과")

        # 예산이 있으면 사다리 전체를 다 돌지는 않아야 합니다.
        if calls["n"] > 4:
            raise AssertionError(f"예산을 무시하고 {calls['n']}번 시도")
    finally:
        T._LADDER_BUDGET_SECONDS = saved_budget
        T.extraction_chain = saved_chain
        if saved_get is not None:
            import server.providers as P
            P.get_extractor = saved_get


@case("L29-9", "휴대폰 업로드가 무한정 기다리지 않는다")
def t_9():
    with io.open(os.path.join(ROOT, "static", "m.js"), encoding="utf-8") as f:
        m = f.read()
    if "AbortController" not in m or "UPLOAD_TIMEOUT_MS" not in m:
        raise AssertionError("업로드에 시한이 없음 — 브라우저가 알아서 끊고 "
                             "'fetch error' 만 남습니다")
    if "AbortError" not in m:
        raise AssertionError("시한 초과를 다른 실패와 구분하지 않음")
    # 2분 넘게 걸리는 것이 실측됐으므로, 너무 짧으면 멀쩡한 분석을 끊습니다.
    import re
    mm = re.search(r"UPLOAD_TIMEOUT_MS\s*=\s*(\d+)", m)
    if not mm or int(mm.group(1)) < 90000:
        raise AssertionError(f"시한이 너무 짧음: {mm and mm.group(1)}ms")
    if "초" not in m.split("AbortError")[1][:400]:
        raise AssertionError("시한 초과 안내에 경과 시간이 없음")


@case("L29-10", "모델 사다리가 측정된 순서대로 서 있다")
def t_10():
    """
    같은 사진, 한 번씩 호출한 실측:

        gemini-3.6-flash        14.8s  정확
        gemini-3.5-flash-lite    5.2s  정확
        gemini-3.5-flash        58.1s  503 UNAVAILABLE

    3.5-flash 가 맨 앞에 있어서, 추출할 때마다 58초를 먼저 태우고 사다리를
    시작했습니다. 연속 업로드 실측이 17.9s / 122.0s / 91.1s 였던 이유입니다.
    재정렬 뒤 15.2s / 21.6s / 17.7s / 31.9s.

    다시 바꾸려면 다시 재보고 바꾸라는 뜻으로 고정합니다.
    """
    saved = os.environ.pop("GEMINI_FALLBACK_MODELS", None)
    saved_model = os.environ.pop("GEMINI_MODEL", None)
    try:
        from server.providers import model_candidates
        order = model_candidates("gemini")
        if not order:
            raise AssertionError("gemini 후보가 비어 있음")
        if order[0] == "gemini-3.5-flash":
            raise AssertionError(
                "503 로 58초를 태우는 모델이 맨 앞 — 매 추출마다 그 값을 냅니다")
        slow = order.index("gemini-3.5-flash") if "gemini-3.5-flash" in order else 99
        fast = order.index("gemini-3.6-flash") if "gemini-3.6-flash" in order else 99
        if fast > slow:
            raise AssertionError(f"느린 모델이 빠른 모델보다 앞: {order}")
    finally:
        if saved is not None:
            os.environ["GEMINI_FALLBACK_MODELS"] = saved
        if saved_model is not None:
            os.environ["GEMINI_MODEL"] = saved_model


@case("L29-11", "과부하 모델을 잠깐 쉬게 한다")
def t_11():
    # 503 은 쿨다운 대상이 아니었습니다. 그래서 58초짜리 모델을 매 추출마다
    # 다시 시도했습니다. 한도 소진과 달리 금방 풀리므로 짧게 쉽니다.
    import server.termsheet as T
    if not hasattr(T, "_BUSY_COOLDOWN_SECONDS"):
        raise AssertionError("과부하 쿨다운이 없음")
    if not (30 <= T._BUSY_COOLDOWN_SECONDS <= 600):
        raise AssertionError(f"쿨다운이 비현실적: {T._BUSY_COOLDOWN_SECONDS}s")
    if T._BUSY_COOLDOWN_SECONDS >= T._COOLDOWN_SECONDS:
        raise AssertionError("과부하를 한도 소진만큼 길게 쉬게 함 — 멀쩡한 모델을 버립니다")

    with io.open(os.path.join(ROOT, "server", "termsheet.py"), encoding="utf-8") as f:
        src = f.read()
    if src.count("_BUSY_COOLDOWN_SECONDS") < 3:
        raise AssertionError("텍스트/이미지 사다리 양쪽에 적용되지 않음")


@case("L29-12", "폴백 차선이 빠른 모델로 서 있다")
def t_12():
    """
    폴백의 존재 이유는 Gemini 가 503 을 낼 때 빨리 답하는 것입니다. 거기에
    2024년 Sonnet 3.5 를 두고 있었습니다 - 느린 차선은 차선이 아닙니다.

    이 계정에서 쓸 수 있는 모델 목록에 claude-haiku-4-5 와 claude-sonnet-5 가
    있는 것을 확인하고 골랐습니다.
    """
    saved = os.environ.pop("ANTHROPIC_MODEL", None)
    try:
        from server.providers import model_candidates
        first = model_candidates("anthropic")[0]
        if "3-5-sonnet" in first or "3-opus" in first or "3-haiku" in first:
            raise AssertionError(f"폴백 1순위가 구형 모델: {first}")
        if "haiku" not in first:
            raise AssertionError(
                f"폴백 1순위가 빠른 모델이 아님: {first} — 차선은 속도가 값어치입니다")
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_MODEL"] = saved


@case("L29-13", "사진은 교차검증하지 않는다")
def t_13():
    """
    교차검증은 second_extractor(redacted_text) 를 부르는데, 사진 경로에서
    redacted_text 는 빈 문자열입니다. 2차 모델은 이미지를 보지 못합니다.

    그대로 두면 빈 문서로 추출을 돌리고, 그 결과와의 '불일치' 를 판정해서
    실제 거래조건에 덮어씁니다 - 사진에서 읽은 만기일이 아무것도 못 본 모델의
    답으로 바뀔 수 있습니다. 2차 프로바이더 키가 없어 여태 실행된 적이 없었을
    뿐, 키를 넣는 순간 켜지는 경로였습니다.
    """
    import sample_formats as SF
    import server.termsheet as T

    called = {"n": 0}

    def spy(text):
        called["n"] += 1
        raise AssertionError("사진인데 2차 추출기가 호출됨")

    out = T.process_termsheet(
        SF.phone_jpeg_bytes(1400, 1050),
        extractor=lambda payload: __import__("test_l11_scenarios").
            _stub("TS-B")(""),
        second_extractor=spy,
        filename="IMG.JPG")
    if called["n"]:
        raise AssertionError("2차 추출기가 빈 문서로 호출됨")
    cv = out.get("cross_validation") or {}
    if cv.get("compared"):
        raise AssertionError("사진인데 교차검증했다고 보고")


@case("L29-14", "판정이 실패해도 비교 결과를 버리지 않는다")
def t_14():
    # 무료 등급에서는 재검토 프롬프트가 토큰 한도를 넘어 429 가 납니다. 그때
    # 두 모델이 어느 필드에서 갈렸는지까지 잃으면, 확인할 거리가 사라집니다.
    with io.open(os.path.join(ROOT, "server", "termsheet.py"), encoding="utf-8") as f:
        src = f.read()
    i = src.find("Round two:")
    if i < 0:
        raise AssertionError("판정 단계를 찾지 못함")
    body = src[i:i + 2200]
    if "adjudication_error" not in body:
        raise AssertionError("판정 실패를 따로 기록하지 않음")
    if body.count("try:") < 1:
        raise AssertionError("판정이 별도 try 로 감싸여 있지 않음 — 비교까지 함께 날아갑니다")


@case("L29-15", "Groq 는 비전 제공자로 등록되지 않는다")
def t_15():
    """
    이 계정의 Groq 모델 목록에 이미지 모델이 없습니다:
      allam-2-7b · orpheus(TTS) · llama-prompt-guard · gpt-oss-120b/20b ·
      qwen3.8-27b · whisper ×2
    비전 목록에 넣으면 사진마다 없는 모델을 부르고 실패합니다.
    """
    from server.providers import supports_vision, VISION_CAPABLE
    if supports_vision("groq"):
        raise AssertionError("Groq 에는 쓸 수 있는 비전 모델이 없습니다")
    for name in ("gemini", "anthropic"):
        if name not in VISION_CAPABLE:
            raise AssertionError(f"{name} 이 비전 목록에서 빠짐")


@case("L29-16", "Groq 기본 모델이 실재하는 모델이다")
def t_16():
    # llama-3.3-70b-versatile 은 이 계정에 없어 "does not exist" 로 죽었습니다.
    # 키가 없어 아무도 몰랐을 뿐, 텍스트 경로도 깨져 있었습니다.
    saved = os.environ.pop("GROQ_MODEL", None)
    try:
        from server.providers import model_candidates
        first = model_candidates("groq")[0]
        if "llama-3.3" in first:
            raise AssertionError(f"존재하지 않는 모델이 기본값: {first}")
    finally:
        if saved is not None:
            os.environ["GROQ_MODEL"] = saved


@case("L29-17", "사진에는 인용문 검증을 돌리지 않는다")
def t_17():
    """
    verify_quotes 는 각 필드의 근거 인용문을 문서 텍스트에서 찾습니다. 사진
    경로에는 그 텍스트가 없어(redacted_text = ""), 모든 필드가 "근거를 찾지
    못했다" 로 떨어졌습니다 - 검토 창 11개 항목이 전부 빨간색이 됐습니다.

    전부 경고면 아무것도 경고가 아닙니다. 진짜 의심스러운 필드가 묻힙니다.
    """
    import sample_formats as SF
    import server.termsheet as T
    from test_l11_scenarios import _stub

    out = T.process_termsheet(
        SF.phone_jpeg_bytes(1400, 1050),
        extractor=lambda payload: _stub("TS-B")(""),
        filename="IMG.JPG")

    if out.get("unverified_fields"):
        raise AssertionError(
            f"사진인데 {len(out['unverified_fields'])}개 필드를 '근거 확인 실패' 로 "
            f"표시 — 대조할 텍스트가 없습니다")
    noisy = [w for w in (out.get("warnings") or []) if "근거 인용문" in w]
    if noisy:
        raise AssertionError(f"근거 관련 경고가 {len(noisy)}건 남음")

    # 대신 사진이라는 사실은 한 번 말해야 합니다.
    if not any("이미지" in w or "스캔" in w for w in (out.get("warnings") or [])):
        raise AssertionError("사진으로 읽었다는 사실을 알리지 않음")


@case("L29-18", "텍스트에서는 인용문 검증이 계속 돈다")
def t_18():
    # 사진을 건너뛰느라 텍스트까지 끄면, 근거 없는 값을 걸러낼 장치가 사라집니다.
    with io.open(os.path.join(ROOT, "server", "termsheet.py"), encoding="utf-8") as f:
        src = f.read()
    if "verify_quotes(trade, redacted_text)" not in src:
        raise AssertionError("인용문 검증이 통째로 사라짐")
    # verify_quotes 를 부르는 그 줄을 봅니다 - 같은 이름의 다른 대입이 앞에 있어
    # 첫 번째만 보면 엉뚱한 줄을 검사하게 됩니다.
    line = next((ln for ln in src.splitlines()
                 if "unverified = " in ln and "verify_quotes" in ln), None)
    if line is None:
        raise AssertionError("verify_quotes 를 쓰는 대입을 찾지 못함")
    if "by_vision" not in line:
        raise AssertionError(f"사진 여부로 가르지 않음: {line.strip()[:80]}")


if __name__ == "__main__":
    print("\n=== L29 검토 창 정확도 ===")
    sys.exit(1 if run_all("L29") else 0)
