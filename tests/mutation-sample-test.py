#!/usr/bin/env python3
"""tools/mutation-sample, end to end (ported from cobenian-control-plane tests/mutation-sample-verify.py) against a scripted "test suite".

The test command is a script that reads the source and passes or fails the way a real suite
would: it notices a broken `>=` and does not notice a broken `and`. So the tool's orchestration --
baseline, killed versus survived, untested, invalid, restoring every file, refusing a dirty
repository -- is exercised for real, without an Elixir toolchain.
"""
import json, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "mutation-sample"
results = []


def expect(name, cond, detail=""):
    results.append(cond)
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"   <- {detail}"))


def repo():
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "lib").mkdir(); (d / "test").mkdir()
    (d / "lib" / "billing.ex").write_text(
        'defmodule Billing do\n'
        '  @doc """\n  total == 0 in prose is never mutated\n  """\n'
        '  def billable?(hours), do: hours >= 1 and true\n'
        '  # hours == 2 in a comment is never mutated\n'
        '  def label, do: "a == b"\n'
        'end\n')
    (d / "lib" / "orphan.ex").write_text('defmodule Orphan do\n  def f(x), do: x != 3\nend\n')
    (d / "test" / "billing_test.exs").write_text("# tests Billing\n")
    # Names only a submodule: Billing.Extra is not Billing, and running it would slow every mutant.
    (d / "test" / "extra_test.exs").write_text("# tests Billing.Extra\n")
    # The "suite": fails if the >= guard is broken, compiles-fails on a marker, ignores `and`.
    (d / "suite.sh").write_text(
        '#!/bin/sh\n'
        'grep -q "hours >= 1" lib/billing.ex || { echo "1 failure"; exit 1; }\n'
        'grep -q "COMPILE_ME_NOT" lib/billing.ex && { echo "== Compilation error"; exit 1; }\n'
        'exit 0\n')
    (d / "suite.sh").chmod(0o755)
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=d, check=True)
    return d


def run(d, *extra):
    out = d / "report.json"
    p = subprocess.run([sys.executable, str(TOOL), "--repo", str(d), "--command", "sh suite.sh",
                        "--out", str(out), *extra], capture_output=True, text=True)
    return p.returncode, (json.loads(out.read_text()) if out.exists() else None), p.stdout + p.stderr


d = repo()
original = (d / "lib" / "billing.ex").read_text()
code, report, out = run(d, "--path", "lib/*.ex", "--sample", "50", "--seed", "1")
by = {(m["file"], m["from"]): m["outcome"] for m in report["mutants"]}
expect("only real operators are candidates: prose, comments and strings are not",
       report["candidates"] == 4, json.dumps(report["mutants"], indent=1))
expect("breaking the guard the tests check is killed", by.get(("lib/billing.ex", ">=")) == "killed", str(by))
expect("breaking the `and` they do not check survives", by.get(("lib/billing.ex", "and")) == "survived", str(by))
expect("a test naming only a submodule is not a test of the module",
       all(m["tests"] == ["test/billing_test.exs"] for m in report["mutants"] if m["file"] == "lib/billing.ex"),
       json.dumps(report["mutants"]))
expect("a module no test names is untested, not guessed at", by.get(("lib/orphan.ex", "!=")) == "untested", str(by))
expect("the score counts killed over killed, survived and untested",
       report["score"] == round(1 / 4, 3), str(report["counts"]))
expect("a survivor or untested mutant exits 1", code == 1, out)
expect("every file is restored", (d / "lib" / "billing.ex").read_text() == original)

(d / "lib" / "billing.ex").write_text(original.replace("and true", "and true # changed"))
code, report, out = run(d, "--path", "lib/billing.ex")
expect("a repository with uncommitted changes to those files is refused", code == 2 and "uncommitted" in out, out)
subprocess.run(["git", "checkout", "-q", "--", "lib/billing.ex"], cwd=d)

(d / "suite.sh").write_text('#!/bin/sh\necho "1 failure"; exit 1\n')
subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "y"], cwd=d)
code, report, out = run(d, "--path", "lib/billing.ex")
expect("tests failing before any mutation stop the run: nothing they kill would mean anything",
       code == 2 and "do not pass before mutation" in out, out)

shutil.rmtree(d, ignore_errors=True)


def commit(d):
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=d, check=True)


# ---- Python: the tokenizer decides what an operator is, and standalone test scripts run one by one.
print("\npython")
d = pathlib.Path(tempfile.mkdtemp())
(d / "runner").mkdir(); (d / "tests").mkdir(); (d / "collect").mkdir()
(d / "runner" / "__init__.py").write_text("")
(d / "runner" / "bounds.py").write_text(
    '"""Bounds.\n\n    a == b in a docstring is never mutated\n"""\n'
    'def allowed(depth, limit, *args):\n'
    '    # depth >= limit in a comment is never mutated\n'
    '    label = "depth > limit"\n'
    '    return depth <= limit and depth is not None\n'
    '\n'
    'def offset(n):\n'
    '    return -n\n')
(d / "runner" / "orphan.py").write_text("def f(x):\n    return x != 3\n")
# An extensionless script, and a test that only has a dict key with its bare name: not a reference.
(d / "collect" / "assay").write_text("#!/usr/bin/env python3\nprint(1 + 2)\n")
(d / "tests" / "test_bounds.py").write_text(
    "import pathlib, sys\n"
    "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
    "from runner import bounds  # noqa: E402\n"
    "def check(name, ok):\n    print(name, ok)\n    return ok\n"
    "ok = check('the limit itself is allowed', bounds.allowed(3, 3))\n"
    "ok = check('one past is not', not bounds.allowed(4, 3)) and ok\n"
    "sys.exit(0 if ok else 1)\n")
(d / "tests" / "test_names.py").write_text("KINDS = {'assay': 1}\nprint(KINDS)\n")
commit(d)
original = (d / "runner" / "bounds.py").read_text()
out = d / "report.json"
p = subprocess.run([sys.executable, str(TOOL), "--repo", str(d), "--path", "runner/*.py", "--path", "collect/assay",
                    "--sample", "50", "--seed", "3", "--command", f"{sys.executable} {{test}}", "--out", str(out)],
                   capture_output=True, text=True)
report = json.loads(out.read_text()) if out.exists() else {"mutants": [], "candidates": None}
sites = sorted((m["file"], m["from"], m["to"]) for m in report["mutants"])
expect("a python shebang makes an extensionless file python", report.get("language") == "python", p.stderr[-400:])
expect("python operators are found by token, never in docstrings, comments or strings, and unary minus and *args are not arithmetic",
       sites == sorted([("collect/assay", "+", "-"), ("runner/bounds.py", "<=", "<"), ("runner/bounds.py", "and", "or"),
                        ("runner/bounds.py", "is not", "is"), ("runner/orphan.py", "!=", "==")]), str(sites))
by = {(m["file"], m["from"]): m for m in report["mutants"]}
expect("a module imported by a standalone test script is tested by it, run once per file",
       by.get(("runner/bounds.py", "<="), {}).get("tests") == ["tests/test_bounds.py"]
       and by[("runner/bounds.py", "<=")]["outcome"] == "killed", str(by.get(("runner/bounds.py", "<="))))
expect("`is not` is one mutant, swapped for `is`, and the script notices it",
       by.get(("runner/bounds.py", "is not"), {}).get("outcome") == "killed", str(by.get(("runner/bounds.py", "is not"))))
expect("a bare quoted name is not a reference to an extensionless script",
       by.get(("collect/assay", "+"), {}).get("outcome") == "untested", str(by.get(("collect/assay", "+"))))
expect("every python file is restored", (d / "runner" / "bounds.py").read_text() == original)

(d / "lib").mkdir()
(d / "lib" / "x.ex").write_text("defmodule X do\n  def f(a), do: a == 1\nend\n")
commit(d)
p = subprocess.run([sys.executable, str(TOOL), "--repo", str(d), "--path", "runner/bounds.py", "--path", "lib/x.ex"],
                   capture_output=True, text=True)
expect("a sample mixing Elixir and Python is refused rather than run with one language's command",
       p.returncode == 2 and "both Elixir and Python" in p.stderr, p.stderr)
shutil.rmtree(d, ignore_errors=True)

# ---- Umbrella: each test runs from its own Mix project, and tests in a sibling app count.
print("\numbrella")
d = pathlib.Path(tempfile.mkdtemp())
for app in ("core", "web"):
    (d / "apps" / app / "lib").mkdir(parents=True); (d / "apps" / app / "test").mkdir()
    (d / "apps" / app / "mix.exs").write_text(f"defmodule {app.title()}.MixProject do\nend\n")
(d / "mix.exs").write_text("defmodule Umbrella.MixProject do\nend\n")
(d / "apps" / "core" / "lib" / "gate.ex").write_text("defmodule Core.Gate do\n  def open?(n), do: n >= 1\nend\n")
(d / "apps" / "web" / "test" / "gate_test.exs").write_text("# exercises Core.Gate through the web layer\n")
# The "suite" only works from an app directory: run from the umbrella root it fails the baseline.
(d / "suite.py").write_text(
    "import pathlib, sys\n"
    "here = pathlib.Path.cwd()\n"
    "assert (here / 'mix.exs').exists() and here.parent.name == 'apps', f'ran from {here}'\n"
    "gate = (here.parent / 'core' / 'lib' / 'gate.ex').read_text()\n"
    "assert all(pathlib.Path(t).exists() for t in sys.argv[1:]), sys.argv\n"
    "sys.exit(0 if 'n >= 1' in gate else 1)\n")
commit(d)
out = d / "report.json"
p = subprocess.run([sys.executable, str(TOOL), "--repo", str(d), "--path", "apps/*/lib/**/*.ex",
                    "--command", f"{sys.executable} {d / 'suite.py'}", "--out", str(out)], capture_output=True, text=True)
report = json.loads(out.read_text()) if out.exists() else {"mutants": []}
m = report["mutants"][0] if report["mutants"] else {}
expect("an umbrella test in a sibling app names the module and runs from that app, with an app-relative path",
       m.get("tests") == ["apps/web/test/gate_test.exs"] and m.get("outcome") == "killed", p.stderr[-400:] + str(m))
shutil.rmtree(d, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
