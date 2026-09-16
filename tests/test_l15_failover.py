# -*- coding: utf-8 -*-
"""
L15 Provider failover.

A rate limit on one vendor should move the document to another, not stop the upload -
but the trader has to be told, because which vendor read the term sheet is a
data-handling fact, not an implementation detail.
"""
import sys, os
from harness import case, run_all

import server.termsheet as tsmod
from server.termsheet import (
    ExtractedTrade, call_extractor, extraction_chain, process_termsheet,
    _classify_provider_error,
)
from test_l10_termsheet import _MINIMAL_PDF, _fake_trade
import server.providers as provmod


class _Rate(Exception):
    pass


def _trade(note="ok"):
    t = _fake_trade("")
    return t


class _Env:
    """Pretend a particular set of providers is configured and reachable."""

    def __init__(self, primary, available, behaviours, fallbacks=None):
        self.primary, self.available = primary, available
        self.behaviours = behaviours          # name -> callable(text) or Exception
        self.fallbacks = fallbacks
        self.calls = []

    def __enter__(self):
        self._saved_env = {k: os.environ.get(k) for k in
                           ("TERMSHEET_PROVIDER", "TERMSHEET_FALLBACK_PROVIDERS",
                            "TERMSHEET_SECOND_PROVIDER")}
        os.environ["TERMSHEET_PROVIDER"] = self.primary
        os.environ.pop("TERMSHEET_SECOND_PROVIDER", None)
        if self.fallbacks is None:
            os.environ.pop("TERMSHEET_FALLBACK_PROVIDERS", None)
        else:
            os.environ["TERMSHEET_FALLBACK_PROVIDERS"] = self.fallbacks

        self._saved_ladder = {k: os.environ.get(k) for k in
                              ("GEMINI_FALLBACK_MODELS", "ANTHROPIC_FALLBACK_MODELS",
                               "GROQ_FALLBACK_MODELS")}
        for k in self._saved_ladder:
            os.environ[k] = ""          # one model each, unless a test says otherwise
        self._is_av, self._get_ex = provmod.is_available, provmod.get_extractor
        self._load = tsmod.load_env_file
        tsmod.load_env_file = lambda *a, **k: None
        provmod.is_available = lambda n: n in self.available

        def get_extractor(name, *a, model_name=None, **k):
            def run(text):
                # Behaviours are keyed by provider, or by "provider:model" to make one
                # model fail while its siblings still work.
                key = f"{name}:{model_name}" if f"{name}:{model_name}" in self.behaviours \
                      else name
                self.calls.append(key if ":" in key else name)
                b = self.behaviours.get(key)
                if isinstance(b, Exception):
                    raise b
                return b(text) if callable(b) else _trade()
            return run

        provmod.get_extractor = get_extractor
        tsmod._PROVIDER_COOLDOWN.clear()
        return self

    def __exit__(self, *exc):
        for k, v in self._saved_ladder.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        provmod.is_available, provmod.get_extractor = self._is_av, self._get_ex
        tsmod.load_env_file = self._load
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tsmod._PROVIDER_COOLDOWN.clear()


@case("L15-1", "a rate-limited primary hands the document to the next model")
def t_1():
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini": _Rate("429 RESOURCE_EXHAUSTED quota exceeded")}) as env:
        used = {}
        call_extractor("doc", used=used)
        if env.calls != ["gemini", "anthropic"]:
            raise AssertionError(f"wrong order: {env.calls}")
        if used["provider"] != "anthropic" or not used["fell_back"]:
            raise AssertionError(f"failover not recorded: {used}")
        if used["attempts"][0]["reason"] != "호출 한도":
            raise AssertionError(f"reason lost: {used['attempts']}")


@case("L15-2", "a working primary is not replaced, and no fallback is claimed")
def t_2():
    with _Env("gemini", {"gemini", "anthropic"}, {}) as env:
        used = {}
        call_extractor("doc", used=used)
        if env.calls != ["gemini"]:
            raise AssertionError(f"called more than it needed: {env.calls}")
        if used["fell_back"]:
            raise AssertionError("claimed a fallback that did not happen")


@case("L15-3", "an exhausted balance also fails over")
def t_3():
    with _Env("anthropic", {"anthropic", "gemini"},
              {"anthropic": _Rate("Your credit balance is too low")}) as env:
        used = {}
        call_extractor("doc", used=used)
        if used["provider"] != "gemini":
            raise AssertionError(f"did not fail over: {used}")


@case("L15-4", "a document-level failure is not retried elsewhere")
def t_4():
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini": ValueError("schema validation failed: not a swap")}) as env:
        try:
            call_extractor("doc", used={})
        except ValueError:
            pass
        else:
            raise AssertionError("a bad document was allowed to pass")
        if env.calls != ["gemini"]:
            raise AssertionError(f"retried a failure another model shares: {env.calls}")


@case("L15-5", "when every model is out, the error names each one and why")
def t_5():
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini": _Rate("429 quota"),
               "anthropic": _Rate("rate limit exceeded")}):
        try:
            call_extractor("doc", used={})
        except ValueError as e:
            msg = str(e)
            if "Google Gemini" not in msg or "Anthropic" not in msg:
                raise AssertionError(f"error does not say what was tried: {msg}")
            if "호출 한도" not in msg:
                raise AssertionError(f"error does not say why: {msg}")
        else:
            raise AssertionError("no error raised with every provider down")


@case("L15-6", "a provider that just hit its quota is skipped on the next upload")
def t_6():
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini": _Rate("429 quota exceeded")}) as env:
        call_extractor("doc", used={})
        env.calls.clear()
        call_extractor("doc", used={})
        if "gemini" in env.calls:
            raise AssertionError(f"burned a call on a provider known to be out: {env.calls}")
        if env.calls != ["anthropic"]:
            raise AssertionError(f"unexpected order: {env.calls}")


@case("L15-7", "the only provider left is tried even while cooling off")
def t_7():
    with _Env("gemini", {"gemini"}, {}) as env:
        tsmod._PROVIDER_COOLDOWN["gemini"] = 9e18
        call_extractor("doc", used={})
        if env.calls != ["gemini"]:
            raise AssertionError("refused to read the document with a usable provider")


@case("L15-8", "failover can be switched off where only one vendor is cleared")
def t_8():
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini": _Rate("429 quota")}, fallbacks="") as env:
        try:
            call_extractor("doc", used={})
        except ValueError:
            pass
        else:
            raise AssertionError("sent the document elsewhere despite failover being off")
        if "anthropic" in env.calls:
            raise AssertionError(f"leaked to an unlisted vendor: {env.calls}")


@case("L15-9", "the fallback order can be pinned")
def t_9():
    with _Env("gemini", {"gemini", "anthropic", "groq"},
              {"gemini": _Rate("429 quota")}, fallbacks="groq,anthropic") as env:
        used = {}
        call_extractor("doc", used=used)
        if used["provider"] != "groq":
            raise AssertionError(f"ignored the pinned order: {env.calls}")


@case("L15-10", "the pipeline tells the trader another vendor read the document")
def t_10():
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini": _Rate("429 quota exceeded")}):
        res = process_termsheet(_MINIMAL_PDF)
        ex = res.get("extraction") or {}
        if not ex.get("fell_back"):
            raise AssertionError(f"failover not reported: {ex}")
        if not any("대체" in w for w in res["warnings"]):
            raise AssertionError(f"failover left unsaid: {res['warnings']}")
        label = ex.get("label")
        if not label or not any(label in w for w in res["warnings"]):
            raise AssertionError(
                f"the warning does not name the vendor that read it: {res['warnings']}")


@case("L15-11", "a normal read reports the provider without a fallback warning")
def t_11():
    with _Env("gemini", {"gemini", "anthropic"}, {}):
        res = process_termsheet(_MINIMAL_PDF)
        ex = res.get("extraction") or {}
        if ex.get("provider") != "gemini" or ex.get("fell_back"):
            raise AssertionError(f"wrong provenance: {ex}")
        if any("대체" in w for w in res["warnings"]):
            raise AssertionError(f"invented a fallback: {res['warnings']}")


@case("L15-12", "failing over onto the cross-check model skips cross-validation")
def t_12():
    saved = os.environ.get("TERMSHEET_SECOND_PROVIDER")
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini": _Rate("429 quota")}):
        os.environ["TERMSHEET_SECOND_PROVIDER"] = "anthropic"
        try:
            res = process_termsheet(_MINIMAL_PDF)
            if res.get("cross_validation"):
                raise AssertionError("one model cross-checked itself")
            if not any("교차검증" in w for w in res["warnings"]):
                raise AssertionError(f"skipped check left unsaid: {res['warnings']}")
        finally:
            if saved is None:
                os.environ.pop("TERMSHEET_SECOND_PROVIDER", None)
            else:
                os.environ["TERMSHEET_SECOND_PROVIDER"] = saved


@case("L15-13", "error classification separates provider trouble from document trouble")
def t_13():
    provider_side = ["429 Too Many Requests", "RESOURCE_EXHAUSTED",
                     "credit balance is too low", "503 overloaded",
                     "Connection timed out",
                     # A retired model is the vendor's decision, not a bad document
                     "model `llama-3.1-70b` has been decommissioned",
                     "404 model_not_found"]
    doc_side = ["ValidationError: 3 fields missing", "could not parse the schedule"]
    for m in provider_side:
        if _classify_provider_error(Exception(m)) is None:
            raise AssertionError(f"provider failure read as a document failure: {m!r}")
    for m in doc_side:
        if _classify_provider_error(Exception(m)) is not None:
            raise AssertionError(f"document failure read as a provider failure: {m!r}")


@case("L15-14", "the chain puts the configured provider first")
def t_14():
    with _Env("anthropic", {"anthropic", "gemini", "groq"}, {}):
        chain = extraction_chain()
        if chain[0] != "anthropic":
            raise AssertionError(f"primary is not first: {chain}")
        if len(set(chain)) != len(chain):
            raise AssertionError(f"a provider appears twice: {chain}")


@case("L15-15", "an exhausted model moves to the next model of the same provider")
def t_15():
    # The free tier meters per model: gemini-3.5-flash being out says nothing about
    # its siblings, and switching vendors at that point would be premature.
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini:m1": _Rate("429 RESOURCE_EXHAUSTED")}) as env:
        os.environ["GEMINI_MODEL"] = "m1"
        os.environ["GEMINI_FALLBACK_MODELS"] = "m2,m3"
        try:
            used = {}
            call_extractor("doc", used=used)
        finally:
            os.environ.pop("GEMINI_MODEL", None)
        if used["provider"] != "gemini":
            raise AssertionError(f"left the provider too early: {used}")
        if used["model"] != "m2":
            raise AssertionError(f"wrong model chosen: {used}")
        if "anthropic" in env.calls:
            raise AssertionError(f"went to another vendor unnecessarily: {env.calls}")


@case("L15-16", "only once every model is out does it change provider")
def t_16():
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini:m1": _Rate("429 quota"), "gemini:m2": _Rate("429 quota")}) as env:
        os.environ["GEMINI_MODEL"] = "m1"
        os.environ["GEMINI_FALLBACK_MODELS"] = "m2"
        try:
            used = {}
            call_extractor("doc", used=used)
        finally:
            os.environ.pop("GEMINI_MODEL", None)
        if used["provider"] != "anthropic":
            raise AssertionError(f"did not move on: {used}")
        if [a["model"] for a in used["attempts"]] != ["m1", "m2"]:
            raise AssertionError(f"did not try every model first: {used['attempts']}")


@case("L15-17", "the model ladder can be pinned to a single approved model")
def t_17():
    with _Env("gemini", {"gemini", "anthropic"},
              {"gemini:m1": _Rate("429 quota")}) as env:
        os.environ["GEMINI_MODEL"] = "m1"
        os.environ["GEMINI_FALLBACK_MODELS"] = ""
        try:
            used = {}
            call_extractor("doc", used=used)
        finally:
            os.environ.pop("GEMINI_MODEL", None)
        if used["provider"] != "anthropic":
            raise AssertionError(f"expected a provider switch: {used}")
        if any(a["model"] != "m1" for a in used["attempts"] if a["provider"] == "gemini"):
            raise AssertionError(f"used an unapproved model: {used['attempts']}")


@case("L15-18", "a model switch counts as a fallback and is reported")
def t_18():
    with _Env("gemini", {"gemini"}, {"gemini:m1": _Rate("429 quota")}):
        os.environ["GEMINI_MODEL"] = "m1"
        os.environ["GEMINI_FALLBACK_MODELS"] = "m2"
        try:
            used = {}
            call_extractor("doc", used=used)
        finally:
            os.environ.pop("GEMINI_MODEL", None)
        if not used["fell_back"]:
            raise AssertionError("a different model read the document without saying so")


@case("L15-19", "the cooldown is per model, not per provider")
def t_19():
    with _Env("gemini", {"gemini"}, {"gemini:m1": _Rate("429 quota")}) as env:
        os.environ["GEMINI_MODEL"] = "m1"
        os.environ["GEMINI_FALLBACK_MODELS"] = "m2"
        try:
            call_extractor("doc", used={})
            env.calls.clear()
            used = {}
            call_extractor("doc", used=used)
        finally:
            os.environ.pop("GEMINI_MODEL", None)
        if "gemini:m1" in env.calls:
            raise AssertionError(f"retried the exhausted model: {env.calls}")
        if used["model"] != "m2":
            raise AssertionError(f"the working model was cooled off too: {used}")


if __name__ == "__main__":
    print("\n=== L15 Provider failover ===")
    sys.exit(1 if run_all("L15") else 0)
