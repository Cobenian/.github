#!/usr/bin/env python3
"""The "Configured?" steps of mutation.yml and test-improvement.yml, run for real.

The scripts are extracted from the workflow YAML and run with the shell GitHub uses, against a
stubbed `gh`, so a test here exercises the shell that ships rather than a copy that can drift.

WHY. Panel's unit test improvement job ran for the first time with no model credential, drafted
nothing, and the only trace was a line in a log. A job that has done nothing must say so and must
not read as a pass, so every not-configured shape is seen FAILING here, and the configured shapes
are seen going ahead: a gate that only ever says no is as useless as one that only says yes.

THE SUBSCRIPTION, NEVER THE API KEY (2026-09-16). The job runs Claude Code on CLAUDE_CODE_OAUTH_TOKEN.
A ~$45/day API bill had just been traced to model calls nobody could see, so a repository that can
see ANTHROPIC_API_KEY but not the token must FAIL rather than quietly fall back to billing the API,
and the API key must never reach the model step at all.
"""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "mutation-sample"
results = []


def expect(name, cond, detail=""):
    results.append(cond)
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"   <- {detail}"))


def step(workflow, name):
    d = yaml.safe_load((ROOT / ".github" / "workflows" / workflow).read_text())
    for job in d["jobs"].values():
        for st in job.get("steps", []):
            if st.get("name") == name:
                return st["run"]
    raise SystemExit(f"no step {name!r} in {workflow} — this test has gone stale")


def run(workflow, env, files=None, open_prs="0"):
    d = pathlib.Path(tempfile.mkdtemp())
    try:
        work, tmp, stub = d / "repo", d / "tmp", d / "stub"
        for p in (work, tmp, stub):
            p.mkdir()
        # A directory the default umbrella glob would match, so a shell that expanded the glob
        # (instead of passing it to the tool) is caught.
        (work / "apps" / "web" / "test").mkdir(parents=True)
        for path, text in (files or {}).items():
            (work / path).parent.mkdir(parents=True, exist_ok=True)
            (work / path).write_text(text)
        (stub / "gh").write_text(f"#!/bin/sh\necho {open_prs}\n")
        (stub / "gh").chmod(0o755)
        (tmp / "summary").write_text(""); (tmp / "env").write_text(""); (tmp / "output").write_text("")
        script = d / "step.sh"
        script.write_text(step(workflow, "Configured?"))
        full = {"PATH": f"{stub}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp),
                "GITHUB_STEP_SUMMARY": str(tmp / "summary"), "GITHUB_ENV": str(tmp / "env"),
                "GITHUB_OUTPUT": str(tmp / "output"), "PATHS_FILE": ".github/mutation/paths.txt",
                "SAMPLE": "25", "UMBRELLA": "false", "TESTS_DIR": "", "TEST_COMMAND": "", "MUTANT_COMMAND": "",
                "FORMAT_COMMAND": "", "SETUP_COMMAND": "", "ANTHROPIC_API_KEY": "", "CLAUDE_CODE_OAUTH_TOKEN": "", **env}
        p = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", str(script)], cwd=work,
                           env=full, capture_output=True, text=True)
        read = lambda n: (tmp / n).read_text() if (tmp / n).exists() else ""
        return {"code": p.returncode, "log": p.stdout + p.stderr, "summary": read("summary"), "env": read("env"),
                "output": read("output"), "sample": read("sample-args").split("\n"), "verify": read("verify-args").split("\n"),
                "sample_args_raw": read("sample-args")}
    finally:
        shutil.rmtree(d)


BASH = shutil.which("bash")
PATHS = {".github/mutation/paths.txt": "# why this file matters\nlib/app/billing.ex\n\n  # indented comment\nlib/app/authz.ex\n"}

for wf in ("test-improvement.yml", "mutation.yml"):
    print(wf)
    key = {"CLAUDE_CODE_OAUTH_TOKEN": "present"}
    r = run(wf, {"LANGUAGE": "elixir", **key})
    expect("no paths file FAILS, and the summary says not configured",
           r["code"] == 1 and "not configured" in r["summary"] and "does not exist" in r["summary"], r)
    r = run(wf, {"LANGUAGE": "elixir", **key}, files={".github/mutation/paths.txt": "# only a comment\n\n"})
    expect("a paths file that lists nothing FAILS", r["code"] == 1 and "lists no files" in r["summary"], r)
    r = run(wf, {"LANGUAGE": "ruby", **key}, files=PATHS)
    expect("an unknown language FAILS", r["code"] == 1 and "elixir or python" in r["summary"], r)
    r = run(wf, {"LANGUAGE": "elixir", "UMBRELLA": "true", **key}, files=PATHS)
    expect("a configured umbrella goes ahead", r["code"] == 0, r)
    expect("every listed path, and only those, reaches the tool; comments and blanks do not",
           [r["sample"][i + 1] for i, a in enumerate(r["sample"]) if a == "--path"] == ["lib/app/billing.ex", "lib/app/authz.ex"],
           r["sample"])
    expect("the tests glob reaches the tool unexpanded",
           [r["sample"][i + 1] for i, a in enumerate(r["sample"]) if a == "--tests-dir"] == ["apps/*/test"], r["sample"])
    expect("the seed is the ISO year and week", re.search(r"^SEED=\d{6}$", r["env"], re.M) is not None, r["env"])
    r = run(wf, {"LANGUAGE": "python", **key}, files=PATHS)
    expect("python defaults run each standalone test script once",
           r["code"] == 0 and "python3 {test}" in r["sample"] and "tests" in r["sample"], r["sample"])
    both = r["sample_args_raw"]
    if wf == "test-improvement.yml":
        ti_python_args = both

print("test-improvement.yml only")
r = run("test-improvement.yml", {"LANGUAGE": "elixir"}, files=PATHS)
expect("no CLAUDE_CODE_OAUTH_TOKEN FAILS, and says which secret",
       r["code"] == 1 and "CLAUDE_CODE_OAUTH_TOKEN" in r["summary"] and "not configured" in r["summary"], r)
r = run("test-improvement.yml", {"LANGUAGE": "elixir", "ANTHROPIC_API_KEY": "present"}, files=PATHS)
expect("an API key is NOT a fallback: with only ANTHROPIC_API_KEY it still fails as not configured",
       r["code"] == 1 and "CLAUDE_CODE_OAUTH_TOKEN" in r["summary"] and "go=true" not in r["output"], r)
wf_text = (ROOT / ".github" / "workflows" / "test-improvement.yml").read_text()
expect("no step is handed secrets.ANTHROPIC_API_KEY", "secrets.ANTHROPIC_API_KEY" not in wf_text)
draft = step("test-improvement.yml", "Draft stronger tests")
expect("the drafting step removes any inherited API key before Claude Code starts",
       "unset ANTHROPIC_API_KEY" in draft and draft.index("unset ANTHROPIC_API_KEY") < draft.index("claude -p"))
r = run("test-improvement.yml", {"LANGUAGE": "elixir", "CLAUDE_CODE_OAUTH_TOKEN": "present"}, files=PATHS, open_prs="1")
expect("an open improvement pull request waits, succeeds, and says so",
       r["code"] == 0 and "go=false" in r["output"] and "waiting" in r["summary"], r)
r = run("test-improvement.yml", {"LANGUAGE": "elixir", "CLAUDE_CODE_OAUTH_TOKEN": "present"}, files=PATHS)
expect("configured with no open pull request goes ahead", r["code"] == 0 and "go=true" in r["output"], r)
expect("the verifier is told the same tests directories", r["verify"][:2] == ["--tests-dir", "test"], r["verify"])
expect("elixir checks formatting", "RUN_FORMAT=mix format --check-formatted" in r["env"], r["env"])
r = run("test-improvement.yml", {"LANGUAGE": "python", "CLAUDE_CODE_OAUTH_TOKEN": "present"}, files=PATHS)
expect("python has no formatter to check, and says the full suite is every script",
       re.search(r"^RUN_FORMAT=$", r["env"], re.M) is not None and "tests/*.py" in r["env"], r["env"])
m = run("mutation.yml", {"LANGUAGE": "python"}, files=PATHS)
expect("both jobs hand the tool the same arguments, so Tuesday's sample is Monday's",
       bool(ti_python_args) and m["sample_args_raw"] == ti_python_args, (m["sample_args_raw"], ti_python_args))

# WRITES STAY IN THE TESTS (2026-09-16). A run on cobenian-logs left production code modified and the
# week measured nothing. A step after drafting discards anything outside the test directories; path-scoped
# Edit rules were tried and refused every edit, so the step is the boundary, exercised with the shell that ships.
print("keeping to the tests")
def tools(r):
    m = re.search(r"^ALLOWED_TOOLS=(.*)$", r["env"], re.M)
    return m.group(1).split(",") if m else []
key = {"CLAUDE_CODE_OAUTH_TOKEN": "present"}
for lang, extra, dirs in (("elixir", {}, ["test"]), ("elixir", {"UMBRELLA": "true"}, ["apps/*/test"]), ("python", {}, ["tests"])):
    r = run("test-improvement.yml", {"LANGUAGE": lang, **extra, **key, "GITHUB_WORKSPACE": "/work"}, files=PATHS)
    t = tools(r)
    expect(f"{lang}{' umbrella' if extra else ''}: file tools are not path-scoped (the keep step is the boundary)",
           "Write" in t and "Edit" in t and not any(x.startswith(("Edit(", "Write(")) for x in t), t)

keep = step("test-improvement.yml", "Keep only test changes")
def keep_run(tests_dirs, base, change):
    d = pathlib.Path(tempfile.mkdtemp())
    try:
        repo = d / "repo"; repo.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q")
        for path, text in base.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True); (repo / path).write_text(text)
        git("add", "-A"); git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        for path, text in change.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True); (repo / path).write_text(text)
        (d / "summary").write_text("")
        p = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c", keep], cwd=repo,
                           env={"PATH": os.environ["PATH"], "TESTS_DIRS": tests_dirs, "GITHUB_STEP_SUMMARY": str(d / "summary")},
                           capture_output=True, text=True)
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo, capture_output=True, text=True).stdout
        return p.returncode, status, (d / "summary").read_text()
    finally:
        shutil.rmtree(d)
base = {"lib/app.ex": "prod\n", "test/app_test.exs": "test\n"}
code, status, summary = keep_run("test", base, {"test/app_test.exs": "test\nmore\n", "test/new_test.exs": "new\n"})
expect("a draft that changed only tests keeps every change", code == 0 and "test/app_test.exs" in status and "test/new_test.exs" in status and summary == "", (code, status, summary))
code, status, summary = keep_run("test", base, {"lib/app.ex": "prod\nedited\n", "lib/stray.ex": "x\n", "test/app_test.exs": "test\nmore\n"})
expect("a production edit and a stray file are discarded, the test change kept, and both named",
       code == 0 and "lib/" not in status and "test/app_test.exs" in status and "lib/app.ex" in summary and "lib/stray.ex" in summary, (code, status, summary))
ubase = {"apps/core/lib/core.ex": "prod\n", "apps/core/test/core_test.exs": "test\n"}
code, status, summary = keep_run("apps/*/test", ubase, {"apps/core/lib/core.ex": "edited\n", "apps/core/test/core_test.exs": "more\n"})
expect("an umbrella keeps its app's test change and discards the app's production edit",
       code == 0 and "apps/core/lib" not in status and "apps/core/test/core_test.exs" in status, (code, status, summary))

# The end of the drafting step, run under the shell Actions uses (`bash -e -o pipefail`) with a stub
# `claude`. The exit code must be recorded rather than killing the step, an authentication error must
# fail loudly, and a successful draft that merely mentions a token must not be mistaken for one.
print("drafting step")
tail = draft[draft.index("claude -p"):]
def draft_run(rc, out):
    t = pathlib.Path(tempfile.mkdtemp())
    try:
        stub = t / "stub"; stub.mkdir()
        (stub / "claude").write_text(f"#!/bin/sh\necho '{out}'\nexit {rc}\n"); (stub / "claude").chmod(0o755)
        (t / "prompt.md").write_text("x"); (t / "summary").write_text("")
        env = {"PATH": f"{stub}:{os.environ['PATH']}", "RUNNER_TEMP": str(t), "GITHUB_STEP_SUMMARY": str(t / "summary"),
               "MODEL": "m", "MAX_TURNS": "1", "ALLOWED_TOOLS": "Read"}
        p = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c", tail], env=env, capture_output=True, text=True)
        return p.returncode, (t / "summary").read_text()
    finally:
        shutil.rmtree(t)
def result(text, is_error=False, denials=(), subtype="success"):
    return json.dumps({"type": "result", "subtype": subtype, "is_error": is_error, "result": text, "permission_denials": list(denials)})
code, summary = draft_run(0, result("Added tests for the OAuth token refresh path"))
expect("a successful draft that mentions an OAuth token is not failed", code == 0 and "exited 0" in summary, (code, summary))
code, summary = draft_run(1, result("", is_error=True, subtype="error_max_turns"))
expect("a non-zero exit without an auth error is recorded, and the verifier still decides",
       code == 0 and "exited 1" in summary, (code, summary))
code, summary = draft_run(1, 'API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"Invalid bearer token"}}')
expect("an authentication error fails the step and says which secret to check",
       code == 1 and "could not authenticate" in summary and "CLAUDE_CODE_OAUTH_TOKEN" in summary, (code, summary))
code, summary = draft_run(0, "Not logged in · Please run /login")
expect("output that is not JSON is kept as it came, so a CLI error is still recognised",
       code == 0 and "exited 0" in summary and "could not authenticate" not in summary, (code, summary))
code, summary = draft_run(1, "Not logged in · Please run /login")
expect("plain-text authentication output with a failing exit still fails loudly", code == 1 and "could not authenticate" in summary, (code, summary))
code, summary = draft_run(0, result("Not logged in · Please run /login", is_error=True))
expect("a result marked as an error that says it is not logged in fails even when the exit code is 0",
       code == 1 and "could not authenticate" in summary, (code, summary))
code, summary = draft_run(0, result("The edit needs your approval", denials=[
    {"tool_name": "Edit", "tool_input": {"file_path": "/w/test/a_test.exs"}}]))
expect("a refused edit is named in the summary with its file, and the step still records the exit",
       code == 0 and "refused" in summary and "Edit: `/w/test/a_test.exs`" in summary, (code, summary))
code, summary = draft_run(0, result("Added two tests"))
expect("a draft nobody refused says nothing about refusals", code == 0 and "refused" not in summary, (code, summary))

# The arguments file is read back with `mapfile -t` in the Sample steps; the tool must accept it.
d = pathlib.Path(tempfile.mkdtemp())
subprocess.run(["git", "init", "-q"], cwd=d, check=True)
args = [a for a in ti_python_args.split("\n") if a != ""]
p = subprocess.run([sys.executable, str(TOOL), "--repo", str(d), *args, "--seed", "202638"], capture_output=True, text=True)
expect("the tool parses the arguments file (and, with no such files, refuses to measure)",
       p.returncode == 2 and "no file matched" in p.stderr and "usage:" not in p.stderr, p.stderr)
shutil.rmtree(d)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
