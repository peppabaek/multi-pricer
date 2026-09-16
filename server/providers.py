"""
Model providers for term sheet extraction.

One registry, used for both the primary reading and the cross-checking second opinion,
so either slot can be filled by any vendor - including the free tiers that make
two-model cross-validation cost nothing to run.

    TERMSHEET_PROVIDER=gemini          # primary
    TERMSHEET_SECOND_PROVIDER=github   # second opinion

A note on the free tiers: most of them reserve the right to train on what you send.
This pipeline strips counterparty identity before anything leaves the process, but the
economic terms still go out. Which vendor is acceptable is a compliance decision, not a
technical one - see PROVIDERS[...]["data_policy"] for what each one claims.
"""

import os
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------- registry
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "anthropic": {
        "label": "Anthropic Claude",
        "key_env": ["ANTHROPIC_API_KEY"],
        "model_env": "ANTHROPIC_MODEL",
        "default_model": "claude-3-5-sonnet-20241022",
        "cost": "paid",
        "data_policy": "학습 미사용 (API 기본), 30일 보존 · ZDR 설정 가능",
        "signup": "https://console.anthropic.com/settings/keys",
    },
    "gemini": {
        "label": "Google Gemini",
        "key_env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "model_env": "GEMINI_MODEL",
        # Pinned rather than a "-latest" alias: the alias moves under you, and the
        # aliased model answered 503 while the pinned one was fine. Override with
        # GEMINI_MODEL when a newer release is worth taking.
        "default_model": "gemini-3.5-flash",
        "tier_env": "GEMINI_TIER",
        "cost": {"free": "free tier", "paid": "paid"},
        "free_limits": "분당 15회 · 일 1,500회 (무료 티어)",
        "data_policy": {
            "free": "무료 티어는 제품 개선에 사용될 수 있음",
            "paid": "유료 티어 — 학습 미사용 (Google 유료 서비스 약관)",
        },
        "signup": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq",
        "key_env": ["GROQ_API_KEY"],
        "model_env": "GROQ_MODEL",
        "default_model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "openai_compatible": True,
        "tier_env": "GROQ_TIER",
        "cost": {"free": "free tier", "paid": "paid"},
        "free_limits": "분당 30회 · 일 14,400회 (무료 티어)",
        "data_policy": {
            "free": "무료 티어 약관 확인 필요",
            "paid": "유료 티어 — 학습 미사용",
        },
        "signup": "https://console.groq.com/keys",
    },
    "openai": {
        "label": "OpenAI",
        "key_env": ["OPENAI_API_KEY"],
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
        "openai_compatible": True,
        "cost": "paid",
        "data_policy": "API 기본 학습 미사용",
        "signup": "https://platform.openai.com/api-keys",
    },
    "ollama": {
        "label": "Ollama (로컬)",
        "key_env": [],
        "model_env": "OLLAMA_MODEL",
        "default_model": "qwen2.5:7b",
        "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "openai_compatible": True,
        "needs_key": False,
        "cost": "free (local)",
        "data_policy": "외부 전송 없음 · 문서가 이 PC를 벗어나지 않음",
        "signup": "https://ollama.com/download",
    },
}


def resolve_tier(name: str) -> str:
    """
    Which billing tier this provider is on here.

    It changes what the vendor may do with the text, so it is declared rather than
    guessed, and defaults to the conservative reading: assume free-tier terms until
    someone says otherwise.
    """
    spec = PROVIDERS.get(name, {})
    env = spec.get("tier_env")
    if env:
        v = (os.environ.get(env) or "").strip().lower()
        if v in ("paid", "pay", "billing", "enterprise"):
            return "paid"
        if v in ("free", "trial"):
            return "free"
    cost = spec.get("cost")
    if isinstance(cost, dict):
        return "free"
    # A provider with a single, free cost - a local model, say - is not paid.
    return "free" if isinstance(cost, str) and "free" in cost.lower() else "paid"


def _pick(value, tier: str):
    """Registry fields may vary by tier."""
    return value.get(tier, next(iter(value.values()))) if isinstance(value, dict) else value


def resolve_key(name: str) -> Optional[str]:
    for env in PROVIDERS.get(name, {}).get("key_env", []):
        v = os.environ.get(env)
        if v:
            return v
    return None


def resolve_model(name: str, override_env: Optional[str] = None) -> str:
    spec = PROVIDERS[name]
    if override_env:
        v = os.environ.get(override_env)
        if v:
            return v
    return os.environ.get(spec["model_env"], spec["default_model"])


def is_available(name: str) -> bool:
    spec = PROVIDERS.get(name)
    if not spec:
        return False
    if spec.get("needs_key") is False:
        # A local server needs no key, but it does need to be running.
        return _local_server_up(spec.get("base_url", ""))
    return bool(resolve_key(name))


def _local_server_up(base_url: str) -> bool:
    if not base_url:
        return False
    try:
        import httpx
        root = base_url.rstrip("/").removesuffix("/v1")
        return httpx.get(root, timeout=1.5).status_code < 500
    except Exception:
        return False


def available_providers() -> List[str]:
    return [n for n in PROVIDERS if is_available(n)]


def describe() -> List[Dict[str, Any]]:
    """What the dashboard shows when asked which models can run."""
    out = []
    for name, spec in PROVIDERS.items():
        tier = resolve_tier(name)
        out.append({
            "name": name,
            "label": spec["label"],
            "tier": tier,
            "cost": _pick(spec["cost"], tier),
            "free_limits": spec.get("free_limits") if tier == "free" else None,
            "data_policy": _pick(spec["data_policy"], tier),
            "model": resolve_model(name),
            "available": is_available(name),
            "signup": spec["signup"],
        })
    return out


# ---------------------------------------------------------------- extractors
def _openai_style_extractor(name: str, model_override_env: Optional[str] = None):
    """Covers every OpenAI-compatible endpoint: GitHub Models, Groq, Ollama, OpenAI."""
    spec = PROVIDERS[name]

    def extract(redacted_text: str):
        from openai import OpenAI
        from server.termsheet import SYSTEM_PROMPT, ExtractedTrade

        client = OpenAI(api_key=resolve_key(name) or "not-needed",
                        base_url=spec.get("base_url"))
        model = resolve_model(name, model_override_env)
        schema = ExtractedTrade.model_json_schema()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",
                 "content": "Extract the trade terms from this termsheet and return JSON "
                            f"matching this schema:\n{schema}\n\n{redacted_text}"},
            ],
            response_format={"type": "json_object"},
        )
        return ExtractedTrade.model_validate_json(resp.choices[0].message.content)

    return extract


def _anthropic_extractor(model_override_env: Optional[str] = None):
    def extract(redacted_text: str):
        import anthropic
        from server.termsheet import SYSTEM_PROMPT, ExtractedTrade

        client = anthropic.Anthropic(api_key=resolve_key("anthropic"))
        resp = client.messages.parse(
            model=resolve_model("anthropic", model_override_env),
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user",
                       "content": "Extract the trade terms from this termsheet.\n\n"
                                  + redacted_text}],
            output_format=ExtractedTrade,
        )
        return resp.parsed_output

    return extract


def _gemini_extractor(model_override_env: Optional[str] = None):
    def extract(redacted_text: str):
        from google import genai
        from google.genai import types
        from server.termsheet import SYSTEM_PROMPT, ExtractedTrade

        client = genai.Client(api_key=resolve_key("gemini"))
        resp = client.models.generate_content(
            model=resolve_model("gemini", model_override_env),
            contents=f"Extract the trade terms from this termsheet.\n\n{redacted_text}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ExtractedTrade,
            ),
        )
        return ExtractedTrade.model_validate_json(resp.text)

    return extract


def get_extractor(name: str, model_override_env: Optional[str] = None) -> Callable[[str], Any]:
    name = (name or "").strip().lower()
    if name not in PROVIDERS:
        raise ValueError(f"알 수 없는 프로바이더: {name!r} "
                         f"(사용 가능: {', '.join(PROVIDERS)})")
    if not is_available(name):
        envs = " 또는 ".join(PROVIDERS[name]["key_env"]) or "(키 불필요)"
        raise ValueError(f"{PROVIDERS[name]['label']} 키가 없습니다 — {envs} 를 설정하세요")
    if name == "anthropic":
        return _anthropic_extractor(model_override_env)
    if name == "gemini":
        return _gemini_extractor(model_override_env)
    return _openai_style_extractor(name, model_override_env)


# ---------------------------------------------------------------- reviewers
def get_reviewer(name: str, model_override_env: Optional[str] = None):
    """Second-round re-read, restricted to the disputed fields."""
    from server.crossvalidate import REVIEW_PROMPT, ReviewSet

    name = (name or "").strip().lower()
    if name not in PROVIDERS or not is_available(name):
        return None
    spec = PROVIDERS[name]

    if name == "anthropic":
        def review(redacted_text: str, disputes: str):
            import anthropic
            from server.termsheet import SYSTEM_PROMPT
            client = anthropic.Anthropic(api_key=resolve_key("anthropic"))
            resp = client.messages.parse(
                model=resolve_model("anthropic", model_override_env),
                max_tokens=8000,
                system=[{"type": "text", "text": SYSTEM_PROMPT,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user",
                           "content": f"{REVIEW_PROMPT.format(disputes=disputes)}"
                                      f"\n\nDocument:\n\n{redacted_text}"}],
                output_format=ReviewSet)
            return {r.field: r.model_dump() for r in resp.parsed_output.reviews}
        return review

    if name == "gemini":
        def review(redacted_text: str, disputes: str):
            from google import genai
            from google.genai import types
            from server.termsheet import SYSTEM_PROMPT
            client = genai.Client(api_key=resolve_key("gemini"))
            r = client.models.generate_content(
                model=resolve_model("gemini", model_override_env),
                contents=f"{REVIEW_PROMPT.format(disputes=disputes)}"
                         f"\n\nDocument:\n\n{redacted_text}",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=ReviewSet,
                ),
            )
            return {x.field: x.model_dump()
                    for x in ReviewSet.model_validate_json(r.text).reviews}
        return review

    def review(redacted_text: str, disputes: str):
        from openai import OpenAI
        from server.termsheet import SYSTEM_PROMPT
        client = OpenAI(api_key=resolve_key(name) or "not-needed",
                        base_url=spec.get("base_url"))
        schema = ReviewSet.model_json_schema()
        resp = client.chat.completions.create(
            model=resolve_model(name, model_override_env),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",
                 "content": f"{REVIEW_PROMPT.format(disputes=disputes)}\n\n"
                            f"Return JSON matching this schema:\n{schema}\n\n"
                            f"Document:\n\n{redacted_text}"},
            ],
            response_format={"type": "json_object"})
        return {x.field: x.model_dump()
                for x in ReviewSet.model_validate_json(
                    resp.choices[0].message.content).reviews}
    return review
