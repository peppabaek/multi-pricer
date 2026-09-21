# -*- coding: utf-8 -*-
"""
L18 Hosted deployment.

On the desk this is a tool on localhost. Published to a host it is a URL anyone can
find, carrying an upload box that sends documents to a model on the desk's own key -
so the things that matter are that it closes by default, that it can still start, and
that nothing about it quietly claims to be live market data when it is not.
"""
import os
import sys

from harness import case, run_all

from fastapi.testclient import TestClient
from server.app import app
import server.access as access

client = TestClient(app)


class _Hosted:
    """Pretend this process is running on a host, optionally with credentials."""

    KEYS = ("RENDER", "PRICER_AUTH_USER", "PRICER_AUTH_PASS",
            "PRICER_AUTH_DISABLED", "PRICER_HOSTED")

    def __init__(self, user=None, password=None, hosted=True):
        self.set = {}
        if hosted:
            self.set["RENDER"] = "true"
        if user:
            self.set["PRICER_AUTH_USER"] = user
        if password:
            self.set["PRICER_AUTH_PASS"] = password

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)
        os.environ.update(self.set)
        return self

    def __exit__(self, *exc):
        for k in self.KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v


@case("L18-1", "on the desk it stays open, the way it is used today")
def t_1():
    if access.auth_required():
        raise AssertionError("localhost started asking for a password")
    if client.get("/api/termsheet/status").status_code != 200:
        raise AssertionError("local use was blocked")


@case("L18-2", "hosted with nothing configured, it closes rather than serving")
def t_2():
    with _Hosted():
        r = client.get("/")
        if r.status_code != 503:
            raise AssertionError(
                f"a term sheet uploader was served unauthenticated: {r.status_code}")
        if "PRICER_AUTH_USER" not in r.text:
            raise AssertionError("closed without saying how to open it")
        up = client.post("/api/termsheet/extract",
                         files={"file": ("t.pdf", b"%PDF-1.4 x", "application/pdf")})
        if up.status_code != 503:
            raise AssertionError(f"upload reachable while closed: {up.status_code}")


@case("L18-3", "the health check answers without credentials")
def t_3():
    with _Hosted():
        # A host that cannot poll health marks the service unhealthy and never
        # routes traffic to it, so this one path has to stay open.
        r = client.get("/healthz")
        if r.status_code != 200:
            raise AssertionError(f"health check blocked: {r.status_code}")


@case("L18-4", "credentials open it, and only the right ones")
def t_4():
    with _Hosted("desk", "correct-horse"):
        if client.get("/").status_code != 401:
            raise AssertionError("served without credentials")
        if client.get("/", auth=("desk", "correct-horse")).status_code != 200:
            raise AssertionError("refused the right credentials")
        for bad in (("desk", "wrong"), ("other", "correct-horse"), ("", "")):
            if client.get("/", auth=bad).status_code != 401:
                raise AssertionError(f"accepted {bad}")


@case("L18-5", "the 401 asks the browser for a password")
def t_5():
    with _Hosted("desk", "pw"):
        r = client.get("/")
        if "basic" not in (r.headers.get("www-authenticate") or "").lower():
            raise AssertionError(
                f"no auth challenge, so the browser shows an error instead of a prompt: "
                f"{r.headers.get('www-authenticate')!r}")


@case("L18-6", "a hosted deployment does not claim to be live market data")
def t_6():
    with _Hosted("desk", "pw"):
        r = client.get("/api/market-snapshot", auth=("desk", "pw"))
        if r.status_code != 200:
            raise AssertionError(f"no snapshot at all: {r.status_code}")
        d = r.json()["data"]
        if "is_live_connected" not in d:
            raise AssertionError("nothing says whether the feed is live")
        if d["is_live_connected"]:
            raise AssertionError(
                "reported a live LSEG feed with no Workspace desktop to reach")


@case("L18-7", "every deployed dependency imports without the desktop feed")
def t_7():
    # requirements-deploy.txt leaves out eikon, so nothing may import it at module
    # level - an ImportError at startup would take the whole service down.
    import importlib
    for mod in ("server.app", "server.termsheet", "server.providers",
                "server.calendar_manager", "common_pricer.rollercoaster_engine"):
        importlib.import_module(mod)

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    deploy = os.path.join(root, "requirements-deploy.txt")
    with open(deploy, encoding="utf-8") as f:
        body = "\n".join(l for l in f if not l.strip().startswith("#"))
    if "eikon" in body:
        raise AssertionError("eikon is in the deploy requirements but cannot connect there")


@case("L18-8", "holiday edits go to writable storage when one is configured")
def t_8():
    import tempfile, importlib, json
    import server.calendar_manager as cm

    saved = os.environ.get("PRICER_DATA_DIR")
    data_dir = tempfile.mkdtemp()
    os.environ["PRICER_DATA_DIR"] = data_dir
    try:
        importlib.reload(cm)
        path = cm._get_holidays_json_path()
        if not path.startswith(data_dir):
            raise AssertionError(f"holidays not on the configured storage: {path}")
        if not os.path.exists(path):
            raise AssertionError("storage was not seeded from the bundled calendars")

        cm.add_holiday("SEB", "2031-02-03", persist=True)
        with open(path, encoding="utf-8") as f:
            if "2031-02-03" not in f.read():
                raise AssertionError("a holiday the desk added was not persisted")
    finally:
        if saved is None:
            os.environ.pop("PRICER_DATA_DIR", None)
        else:
            os.environ["PRICER_DATA_DIR"] = saved
        importlib.reload(cm)


@case("L18-9", "unusable storage falls back instead of taking the service down")
def t_9():
    import importlib
    import server.calendar_manager as cm

    saved = os.environ.get("PRICER_DATA_DIR")
    # A path that cannot be created: a directory under a file.
    os.environ["PRICER_DATA_DIR"] = os.path.join(os.path.abspath(__file__), "nope")
    try:
        importlib.reload(cm)
        path = cm._get_holidays_json_path()
        if not os.path.exists(path):
            raise AssertionError("no calendars at all when storage is unusable")
        if not cm.get_calendar_holidays("SEB"):
            raise AssertionError("calendars did not load from the fallback")
    finally:
        if saved is None:
            os.environ.pop("PRICER_DATA_DIR", None)
        else:
            os.environ["PRICER_DATA_DIR"] = saved
        importlib.reload(cm)


@case("L18-10", "the blueprint says what the service needs to run")
def t_10():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, "render.yaml"), encoding="utf-8") as f:
        blueprint = f.read()
    for needed in ("requirements-deploy.txt", "$PORT", "/healthz",
                   "PRICER_AUTH_USER", "PRICER_AUTH_PASS"):
        if needed not in blueprint:
            raise AssertionError(f"blueprint does not mention {needed!r}")

    # A disk and the variable that points at it belong together: a mount nothing uses
    # is wasted, and PRICER_DATA_DIR without a disk writes holiday edits to a
    # filesystem that is rebuilt on deploy, which loses them while looking like it
    # worked.
    live = "\n".join(l for l in blueprint.splitlines()
                      if not l.strip().startswith("#"))
    has_disk = "mountPath:" in live
    uses_dir = "PRICER_DATA_DIR" in live
    if has_disk != uses_dir:
        raise AssertionError(
            f"disk and PRICER_DATA_DIR disagree: disk={has_disk} var={uses_dir}")
    # Secrets are entered in the dashboard, never committed here.
    for line in blueprint.splitlines():
        if "API_KEY" in line and "value:" in line:
            raise AssertionError(f"a key is hard-coded in the blueprint: {line.strip()}")


@case("L18-11", "a console that cannot encode the log does not fail the upload")
def t_11():
    # The diagnostics carry Korean and em-dashes. On a legacy code page print raises
    # UnicodeEncodeError, which is a subclass of ValueError - so a lost log line came
    # back to the browser as a 400 blaming the document.
    import server.termsheet as tsmod

    class _Cp949Console:
        encoding = "cp949"

        def write(self, text):
            text.encode("cp949")      # raises on anything it cannot represent
            return len(text)

        def flush(self):
            pass

    saved = sys.stdout
    sys.stdout = _Cp949Console()
    try:
        tsmod._log("[Termsheet] 교차검증 미실행 \u2014 GROQ_API_KEY 를 설정하세요")
    except Exception as e:
        sys.stdout = saved
        raise AssertionError(f"a log line failed instead of degrading: {type(e).__name__}")
    finally:
        sys.stdout = saved


@case("L18-12", "the upload endpoint's dependencies are declared, not inherited")
def t_12():
    # python-multipart is what FastAPI parses an upload with. It was installed here by
    # accident and in neither requirements file, so a clean install - which is what a
    # host does - could not start the app at all.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    for name in ("requirements.txt", "requirements-deploy.txt"):
        with open(os.path.join(root, name), encoding="utf-8") as f:
            body = "\n".join(l for l in f if not l.strip().startswith("#"))
        if "python-multipart" not in body:
            raise AssertionError(f"{name} does not declare python-multipart")


if __name__ == "__main__":
    print("\n=== L18 Hosted deployment ===")
    sys.exit(1 if run_all("L18") else 0)
