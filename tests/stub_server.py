# -*- coding: utf-8 -*-
"""
The real app with the model call stubbed out.

    uvicorn tests.stub_server:app

Browser tests that need to exercise the upload endpoint itself - its status codes, its
headers, its error handling - cannot stub the endpoint from the page, because then the
request never reaches the server and whatever the server does goes untested. This
replaces only the model call, so everything else is the shipped code path.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
for path in (HERE, ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import server.termsheet as tsmod          # noqa: E402
from test_l11_scenarios import _stub      # noqa: E402

# TS-B is the amortising sample the browser tests assert against.
_extract = _stub("TS-B")

# STUB_EXTRACT_DELAY stands in for the 45-60 seconds a real model takes, so a test
# can watch whether the server still answers anything while a read is in flight.
_DELAY = float(os.environ.get("STUB_EXTRACT_DELAY", "0") or 0)


def _stub_call(text, *a, **kw):
    if _DELAY:
        import time
        time.sleep(_DELAY)
    return _extract(text)


def _stub_vision(raw, mime, *a, **kw):
    """
    사진 경로도 같은 답을 돌려준다.

    폰 사진은 call_extractor 가 아니라 call_vision_extractor 로 갑니다. 이쪽을
    대역으로 두지 않으면 사진 업로드 테스트가 실제 모델을 부르게 됩니다 - 그러면
    키가 없는 환경에서 실패하고, 있으면 돈이 나갑니다.

    받은 바이트는 확인용으로 남깁니다: prepare_photo 를 거친 JPEG 이어야지,
    HEIC 원본이나 12MB 원본이 여기 도착하면 안 됩니다.
    """
    if _DELAY:
        import time
        time.sleep(_DELAY)
    _stub_vision.last = {"bytes": len(raw), "mime": mime, "magic": raw[:4]}
    return _extract("")


_stub_vision.last = None

tsmod.call_extractor = _stub_call
tsmod.call_vision_extractor = _stub_vision

from server.app import app                # noqa: E402,F401


def _last_vision(request):
    """테스트가 모델에 무엇이 갔는지 들여다보는 창. 대역 서버에만 있습니다."""
    from starlette.responses import JSONResponse
    d = _stub_vision.last
    return JSONResponse({"data": None if not d else
                         {"bytes": d["bytes"], "mime": d["mime"],
                          "magic": list(d["magic"])}})


# app.py 는 마지막에 StaticFiles 를 "/" 에 mount 합니다. 그 뒤에 더한 경로는
# 라우트 순서상 mount 가 먼저 잡아 404 가 됩니다. 앞에 끼워 넣습니다.
from starlette.routing import Route       # noqa: E402

app.router.routes.insert(0, Route("/__stub/last-vision", _last_vision,
                                  methods=["GET"]))
