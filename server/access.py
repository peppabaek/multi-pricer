# -*- coding: utf-8 -*-
"""
Who may reach the dashboard when it is not on the desk's own machine.

Run locally this is a tool on localhost and needs no gate. Published to a host it is a
URL anyone can find, with an upload box that sends documents to a model on the desk's
own API key - so on a host it is closed unless credentials are configured, rather than
open unless someone remembers to close it.
"""

import base64
import hmac
import os
from typing import Optional, Tuple

from fastapi import Response

# Render, Railway, Fly and Heroku all announce themselves. Any of them means this is
# not localhost any more.
_HOSTED_ENV_VARS = ("RENDER", "RAILWAY_ENVIRONMENT", "FLY_APP_NAME", "DYNO",
                    "KOYEB_APP_NAME", "WEBSITE_INSTANCE_ID")

# Reachable without credentials: the health check a host polls, and nothing else.
PUBLIC_PATHS = frozenset({"/healthz"})


def is_hosted() -> bool:
    if os.environ.get("PRICER_HOSTED", "").strip().lower() in ("1", "true", "yes"):
        return True
    return any(os.environ.get(v) for v in _HOSTED_ENV_VARS)


def credentials() -> Tuple[Optional[str], Optional[str]]:
    return (os.environ.get("PRICER_AUTH_USER") or None,
            os.environ.get("PRICER_AUTH_PASS") or None)


def auth_required() -> bool:
    """Locally, only if asked for. On a host, always."""
    if os.environ.get("PRICER_AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return False
    return bool(is_hosted() or any(credentials()))


def _check(header: Optional[str]) -> bool:
    user, password = credentials()
    if not (user and password):
        return False
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(header.split(None, 1)[1]).decode("utf-8")
        got_user, _, got_pass = raw.partition(":")
    except Exception:
        return False
    # compare_digest on both halves: a wrong username must cost the same as a wrong
    # password, or the difference tells an attacker which half to keep guessing.
    return (hmac.compare_digest(got_user, user)
            and hmac.compare_digest(got_pass, password))


def gate(path: str, authorization: Optional[str]) -> Optional[Response]:
    """The response to send instead of serving `path`, or None to let it through."""
    if not auth_required() or path in PUBLIC_PATHS:
        return None

    user, password = credentials()
    if not (user and password):
        # Hosted with nothing configured. Closed, and saying which two variables open
        # it - a dashboard that quietly served a term sheet uploader to the internet
        # would be a worse outcome than one that will not start.
        return Response(
            content=("접근이 설정되지 않았습니다.\\n"
                     "호스팅 환경에서는 PRICER_AUTH_USER 와 PRICER_AUTH_PASS 를 "
                     "설정해야 대시보드가 열립니다.\\n"
                     "(로컬에서만 쓰신다면 PRICER_AUTH_DISABLED=1)\\n"),
            status_code=503, media_type="text/plain; charset=utf-8")

    if _check(authorization):
        return None
    return Response(
        content="인증이 필요합니다\\n", status_code=401,
        media_type="text/plain; charset=utf-8",
        headers={"WWW-Authenticate": 'Basic realm="Multipricer", charset="UTF-8"'})
