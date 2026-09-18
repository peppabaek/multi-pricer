"""Run every layer in order. No pytest, no live server, no Eikon required."""
import sys, os, subprocess

# Test names carry Korean units; a legacy console code page would otherwise abort the run.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = [
    ("L1  curve bootstrap", "test_l1_curves.py"),
    ("L2  pricing invariants", "test_l2_pricing.py"),
    ("L3/L8  schedules + contract", "test_l38_matrix.py"),
    ("L4/L5/L6  CRS + rollercoaster + live data", "test_l456_priority.py"),
    ("L9  Advanced hybrid + Hedge Greeks", "test_l9_advanced_hedge.py"),
    ("L10 Termsheet ingestion", "test_l10_termsheet.py"),
    ("L10 Termsheet endpoint", "test_l10_endpoint.py"),
    ("L11 Termsheet scenarios (samples)", "test_l11_scenarios.py"),
    ("L12 Varying terms + holidays", "test_l12_rollercoaster_holiday.py"),
    ("L13 Two-model cross-validation", "test_l13_crossvalidate.py"),
    ("L14 Disagreement adjudication", "test_l14_adjudication.py"),
    ("L15 Provider failover", "test_l15_failover.py"),
    ("L16 File formats", "test_l16_formats.py"),
    ("L17 Stub periods (amortising)", "test_l17_stub_periods.py"),
    ("L18 Hosted deployment", "test_l18_deploy.py"),
]

total_fail = 0
for label, script in SUITES:
    print(f"\n{'=' * 62}\n  {label}\n{'=' * 62}")
    p = subprocess.run([sys.executable, script], cwd=HERE, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    for line in p.stdout.splitlines():
        s = line.strip()
        if s.startswith(("PASS", "FAIL")) or "passed," in s:
            print("  " + s)
        elif line.startswith(" " * 10) and s:
            print("      " + s)
    if p.returncode:
        total_fail += 1

print("\n" + "=" * 62)
print("  ALL SUITES PASSED" if not total_fail else f"  {total_fail} SUITE(S) FAILED")
print("=" * 62)
sys.exit(1 if total_fail else 0)
