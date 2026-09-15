# -*- coding: utf-8 -*-
"""
Which models can actually run right now, and what each would cost.

    python tests/check_providers.py          # status only
    python tests/check_providers.py --probe  # also make one tiny live call each
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from server.termsheet import load_env_file, extraction_status
from server.providers import PROVIDERS, describe, is_available, resolve_model, resolve_key

load_env_file()

FREE_PAIR_HINT = """
무료로 두 모델 교차검증을 돌리려면 .env 에 아래를 넣으세요:

    TERMSHEET_PROVIDER=gemini
    GEMINI_API_KEY=...            https://aistudio.google.com/apikey  (카드 불필요)

    TERMSHEET_SECOND_PROVIDER=groq
    GROQ_API_KEY=...              https://console.groq.com/keys       (카드 불필요)
"""


def probe(name: str) -> str:
    """One minimal call, just to see whether the key and network actually work."""
    try:
        if name == "anthropic":
            import anthropic
            c = anthropic.Anthropic(api_key=resolve_key(name))
            c.messages.create(model=resolve_model(name), max_tokens=8,
                              messages=[{"role": "user", "content": "ok"}])
        elif name == "gemini":
            from google import genai
            # Keep a reference: an inline client is collected mid-request and the
            # call fails with "client has been closed".
            client = genai.Client(api_key=resolve_key(name))
            client.models.generate_content(model=resolve_model(name), contents="ok")
        else:
            from openai import OpenAI
            c = OpenAI(api_key=resolve_key(name) or "not-needed",
                       base_url=PROVIDERS[name].get("base_url"))
            c.chat.completions.create(model=resolve_model(name), max_tokens=8,
                                      messages=[{"role": "user", "content": "ok"}])
        return "OK"
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "credit balance" in low or "insufficient_quota" in low:
            return "잔액 부족"
        if "rate limit" in low or "429" in low:
            return "호출 한도"
        if "api key" in low or "401" in low or "unauthorized" in low or "invalid" in low:
            return "키 오류"
        if "connect" in low or "getaddrinfo" in low or "timeout" in low:
            return "연결 불가"
        return f"{type(e).__name__}: {msg[:50]}"


def main():
    do_probe = "--probe" in sys.argv
    st = extraction_status()

    print("=" * 78)
    print(f"  1차 프로바이더 : {st['provider_label']}  ({st.get('model')})")
    print(f"  실행 가능      : {'예' if st['ready'] else '아니오 — ' + st.get('reason', '')}")
    print(f"  교차검증       : {'켜짐 — ' + str(st['second_provider']) if st['cross_check'] else '꺼짐'}")
    print("=" * 78)

    rows = describe()
    w = max(len(r["label"]) for r in rows)
    print(f"\n  {'프로바이더':<{w}}  {'티어':<6} {'키':<6} {'한도':<26} {'점검'}")
    print(f"  {'-'*w}  {'-'*6} {'-'*6} {'-'*26} {'-'*12}")
    for r in rows:
        key = "있음" if r["available"] else "없음"
        chk = probe(r["name"]) if (do_probe and r["available"]) else ("-" if r["available"] else "")
        tier = "유료" if r["tier"] == "paid" else "무료"
        print(f"  {r['label']:<{w}}  {tier:<6} {key:<6} "
              f"{(r['free_limits'] or '-'):<26} {chk}")

    print("\n  데이터 취급")
    for r in rows:
        print(f"    {r['label']:<{w}}  {r['data_policy']}")

    ready = [r for r in rows if r["available"]]
    if len(ready) >= 2:
        print(f"\n  준비된 프로바이더 {len(ready)}개 — 교차검증 가능: "
              + ", ".join(r["label"] for r in ready))
    elif not any(r["available"] and r["tier"] == "free" for r in rows):
        print(FREE_PAIR_HINT)

    print("\n  키 발급")
    for r in rows:
        if not r["available"]:
            print(f"    {r['label']:<{w}}  {r['signup']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
