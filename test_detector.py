#!/usr/bin/env python3
"""Verification for mcp-benchmark-hygiene core — proves the detector actually
flags a VulcanBench-style pytest-cov workspace and passes a clean one."""
import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp_server as m

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)

results = []
def check(name, got, expect_broken):
    b = got.get("will_corrupt_grading")
    ok = (b == expect_broken)
    results.append((name, ok, b, got.get("verdict")))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: corrupt={b} verdict={got.get('verdict')}")
    if not ok:
        print("      ", json.dumps(got, indent=2)[:800])

# 1) VulcanBench-style: pyproject.toml at workspace ROOT with --cov --cov-fail-under=80
tmp = tempfile.mkdtemp()
write(os.path.join(tmp, "pyproject.toml"),
      '[tool.pytest.ini_options]\naddopts = "--cov=harness --cov-report=term-missing:skip-covered --cov-fail-under=80"\n')
write(os.path.join(tmp, "tests", "test_x.py"), "def test_x():\n    assert True\n")
r = m.inspect_workspace(tmp)
check("vulcanbench-style cov gate at root", r, True)

# 2) sub-workspace nested under the corrupted root: workspace/task-1/src
sub = os.path.join(tmp, "task-1", "src")
write(os.path.join(sub, "test_ok.py"), "def test_ok():\n    assert 1+1==2\n")
r2 = m.inspect_workspace(sub)
check("nested workspace inherits root cov gate (the real bug)", r2, True)

# 3) truly clean workspace (no pytest config anywhere)
tmp2 = tempfile.mkdtemp()
write(os.path.join(tmp2, "test_clean.py"), "def test():\n    assert True\n")
r3 = m.inspect_workspace(tmp2)
check("clean workspace (no ini)", r3, False)

# 4) pytest.ini with --maxfail (abort gate, not coverage)
tmp3 = tempfile.mkdtemp()
write(os.path.join(tmp3, "pytest.ini"), "[pytest]\naddopts = --maxfail=2\n")
r4 = m.inspect_workspace(tmp3)
check("pytest.ini abort gate --maxfail", r4, True)

# 5) pyproject.toml with a harmless addopts (no gate)
tmp4 = tempfile.mkdtemp()
# a pyproject with NO [tool.pytest] section should not corrupt
write(os.path.join(tmp4, "pyproject.toml"), '[project]\nname="x"\n')
write(os.path.join(tmp4, "test_ok.py"), "def test():\n    assert True\n")
r5 = m.inspect_workspace(tmp4)
check("pyproject with no pytest section", r5, False)

print()
passed = sum(1 for _, ok, _, _ in results if ok)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
