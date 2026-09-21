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


tsmod.call_extractor = _stub_call

from server.app import app                # noqa: E402,F401
