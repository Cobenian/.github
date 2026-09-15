#!/usr/bin/env python3
"""tools/test-improvement-verify (ported from cobenian-control-plane tests/test-improvement-verify.py), against a scratch repository and hand-written mutation reports.

Every refusal is seen refusing, and the one acceptable change is seen accepted: a gate that only
ever says no is as useless as one that only ever says yes.
"""
import json, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "test-improvement-verify"
results = []

TEST = '''defmodule BillingTest do
  use ExUnit.Case

  # PANEL-TB-010 and §4.1
  test "a billable hour is billed" do
    assert Billing.billable?(1)
  end

  test "zero hours are not" do
    refute Billing.billable?(0)
  end
end
'''


def expect(name, cond, detail=""):
    results.append(cond)
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"   <- {detail}"))


def sh(d, *cmd):
    subprocess.run(cmd, cwd=d, check=True, capture_output=True)


def repo():
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "lib").mkdir(); (d / "test").mkdir()
    (d / "lib" / "billing.ex").write_text("defmodule Billing do\n  def billable?(h), do: h >= 1\nend\n")
    (d / "test" / "billing_test.exs").write_text(TEST)
    sh(d, "git", "init", "-q"); sh(d, "git", "add", "-A")
    sh(d, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
    return d, base


def mutants(killed, survived, seed=202638):
    ms = [{"file": "lib/billing.ex", "line": l, "from": ">=", "to": ">", "outcome": "killed"} for l in killed]
    ms += [{"file": "lib/billing.ex", "line": l, "from": ">=", "to": ">", "outcome": "survived"} for l in survived]
    return {"seed": seed, "paths": ["lib/billing.ex"], "sampled": len(ms), "mutants": ms}


def run(d, base, before, after, *extra):
    (d / "before.json").write_text(json.dumps(before))
    (d / "after.json").write_text(json.dumps(after))
    # The reports are the workflow's, not the change's: keep them out of the diff.
    (d / ".git" / "info" / "exclude").write_text("before.json\nafter.json\nreport.md\n")
    p = subprocess.run([sys.executable, str(TOOL), "--repo", str(d), "--base", base,
                        "--before", str(d / "before.json"), "--after", str(d / "after.json"),
                        "--out", str(d / "report.md"), *extra], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def case(name, change, before=None, after=None, code=1, says=""):
    d, base = repo()
    try:
        change(d)
        rc, out = run(d, base, before or mutants([2], [3]), after or mutants([2, 3], []))
        expect(name, rc == code and says in out, f"exit {rc}, output: {out[-300:]}")
    finally:
        shutil.rmtree(d)


def add_test(d):
    add_test_at(d, "test/billing_test.exs")


def add_test_at(d, path):
    t = d / path
    t.write_text(t.read_text().replace("end\nend\n", 'end\n\n  test "one hour exactly is billed" do\n    assert Billing.billable?(1)\n  end\nend\n'))


print("test-improvement-verify")
case("a new test that catches a missed bug may be proposed", add_test, code=0, says="1 → 2")
case("a change to production code is refused",
     lambda d: (add_test(d), (d / "lib" / "billing.ex").write_text("defmodule Billing do\n  def billable?(h), do: h > 0\nend\n")),
     says="outside test/")
case("a removed test is refused",
     lambda d: (d / "test" / "billing_test.exs").write_text(TEST.replace('  test "zero hours are not" do\n    refute Billing.billable?(0)\n  end\n', "")),
     says='removed or renamed test(s) "zero hours are not"')
case("fewer assertions are refused",
     lambda d: (d / "test" / "billing_test.exs").write_text(TEST.replace("    refute Billing.billable?(0)\n", "    :ok\n")),
     says="1 fewer assertion")
case("a requirement no longer named is refused",
     lambda d: (add_test(d), (d / "test" / "billing_test.exs").write_text((d / "test" / "billing_test.exs").read_text().replace("PANEL-TB-010 and ", ""))),
     says="PANEL-TB-010")
case("a deleted test file is refused",
     lambda d: (d / "test" / "billing_test.exs").unlink(), says="deleted test/billing_test.exs")
case("a bug caught before and not now is refused", add_test,
     before=mutants([2, 4], [3]), after=mutants([2, 3], [4]), says="caught before and not now")
case("no newly caught bug is refused", add_test,
     before=mutants([2], [3]), after=mutants([2], [3]), says="no deliberate bug the tests missed")
case("nothing changed is refused", lambda d: None, says="nothing changed")
case("samples with different seeds cannot be judged", add_test,
     before=mutants([2], [3], seed=1), after=mutants([2, 3], [], seed=2), code=2, says="different seeds")

# ---- Python: standalone test scripts name their tests in check("...") and assert with check/assert.
PY_TEST = """import sys
from runner import bounds

def check(name, ok):
    print(name, ok)
    return ok

# ASSAY-RUN-012
ok = check("the limit itself is allowed", bounds.allowed(3, 3))
ok = check("one past is not", not bounds.allowed(4, 3)) and ok


def test_zero_depth():
    assert bounds.allowed(0, 3)

sys.exit(0 if ok else 1)
"""


def py_case(name, change, code=1, says="", tests_dirs=("tests",), layout=None):
    d = pathlib.Path(tempfile.mkdtemp())
    try:
        for path, text in (layout or {"runner/bounds.py": "def allowed(d, l):\n    return d <= l\n",
                                      "tests/test_bounds.py": PY_TEST}).items():
            (d / path).parent.mkdir(parents=True, exist_ok=True)
            (d / path).write_text(text)
        sh(d, "git", "init", "-q"); sh(d, "git", "add", "-A")
        sh(d, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
        change(d)
        extra = [x for t in tests_dirs for x in ("--tests-dir", t)]
        rc, out = run(d, base, mutants([2], [3]), mutants([2, 3], []), *extra)
        expect(name, rc == code and says in out, f"exit {rc}, output: {out[-300:]}")
    finally:
        shutil.rmtree(d)


def py_edit(old, new, path="tests/test_bounds.py"):
    def f(d):
        t = d / path
        assert old in t.read_text(), old
        t.write_text(t.read_text().replace(old, new))
    return f


print("python")
py_case("a new check in a standalone test script may be proposed",
        py_edit("sys.exit", 'ok = check("depth zero is allowed", bounds.allowed(0, 0)) and ok\nsys.exit'), code=0)
py_case("a removed check(...) is a removed test",
        py_edit('ok = check("one past is not", not bounds.allowed(4, 3)) and ok\n', ""),
        says='removed or renamed test(s) "one past is not"')
py_case("a removed def test_ is a removed test",
        py_edit("def test_zero_depth():", "def zero_depth():"), says='"test_zero_depth"')
py_case("a removed assert is a removed assertion",
        py_edit("    assert bounds.allowed(0, 3)", "    bounds.allowed(0, 3)"), says="1 fewer assertion")
py_case("a requirement no longer named by a python test is refused",
        py_edit("# ASSAY-RUN-012\n", ""), says="ASSAY-RUN-012")
py_case("a change to python production code is refused",
        py_edit("d <= l", "d < l", path="runner/bounds.py"), says="outside tests/")

print("umbrella")
UMBRELLA = {"apps/core/lib/gate.ex": "defmodule Core.Gate do\n  def open?(n), do: n >= 1\nend\n",
            "apps/web/test/gate_test.exs": TEST}
py_case("a new test in any app's test directory may be proposed",
        lambda d: add_test_at(d, "apps/web/test/gate_test.exs"), code=0, tests_dirs=("apps/*/test",), layout=UMBRELLA)
py_case("a change to an app's lib is refused in an umbrella",
        lambda d: (add_test_at(d, "apps/web/test/gate_test.exs"),
                   (d / "apps/core/lib/gate.ex").write_text("defmodule Core.Gate do\n  def open?(n), do: n > 1\nend\n")),
        says="outside apps/*/test/: apps/core/lib/gate.ex", tests_dirs=("apps/*/test",), layout=UMBRELLA)

print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
