"""Minimal test harness - no pytest dependency."""
import sys, os, traceback
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_RESULTS = []
_CASES = []


def case(cid, desc):
    def deco(fn):
        _CASES.append((cid, desc, fn))
        return fn
    return deco


def approx(a, b, tol, label=""):
    if abs(a - b) > tol:
        raise AssertionError(f"{label}: {a!r} != {b!r} (tol={tol}, diff={abs(a-b):.6g})")


def run_all(filter_prefix=None):
    passed = failed = 0
    for cid, desc, fn in _CASES:
        if filter_prefix and not cid.startswith(filter_prefix):
            continue
        try:
            fn()
            print(f"  PASS  {cid}  {desc}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {cid}  {desc}")
            for line in str(e).splitlines()[:6]:
                print(f"          {line}")
            if not isinstance(e, AssertionError):
                print("        " + traceback.format_exc().splitlines()[-3].strip())
            failed += 1
    print(f"\n  {passed} passed, {failed} failed\n")
    return failed
