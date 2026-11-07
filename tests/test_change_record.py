import contextlib
import io
import json

from agent_checks import change_record, cli

FULL = """\
Adds the change-record rule.

**Spec:** docs/specs/change-record-rule.md
**Claim:** Egoushka/agent-checks#14
**Checks:**
- tests/test_change_record.py::test_missing_spec_fails  pass  run 123
- ruff  pass  run 123
**Scope:** src/agent_checks/**, tests/**, docs/**
**Risk:** none
**Agent:** run-20261107-1, claude-opus-5-5, $0.80
"""


def without(field: str) -> str:
    lines = FULL.splitlines()
    i = next(n for n, x in enumerate(lines) if x.startswith(f"**{field}:**"))
    end = i + 1
    while end < len(lines) and lines[end].startswith("- "):
        end += 1
    return "\n".join(lines[:i] + lines[end:]) + "\n"


def run(*args: str, stdin: str = "") -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        import sys

        old, sys.stdin = sys.stdin, io.StringIO(stdin)
        try:
            code = cli.main(["change-record", *args])
        finally:
            sys.stdin = old
    return code, buf.getvalue()


def test_full_body_passes():
    rep = change_record.check(FULL, ["src/agent_checks/change_record.py", "tests/test_change_record.py"])
    assert rep.ok, rep.problems
    assert rep.fields["Checks"][1] == "ruff  pass  run 123"


def test_missing_spec_fails():
    code, out = run("--body", "-", stdin=without("Spec"))
    assert code == 1
    assert "Spec: missing" in out
    assert run("--body", "-", stdin=FULL)[0] == 0


def test_each_missing_field_fails():
    for name in change_record.FIELDS:
        rep = change_record.check(without(name))
        assert [p.field for p in rep.problems] == [name]


def test_scope_violation_flags(repo):
    repo.write("src/a.py", "x = 1\n")
    repo.commit("base")
    repo.write("src/a.py", "x = 2\n")
    repo.write("deploy/prod.yml", "replicas: 3\n")
    body = repo.root / "body.md"
    body.write_text(FULL.replace("src/agent_checks/**, tests/**, docs/**", "src/**, body.md"))
    code, out = run("-C", str(repo.root), "--body", str(body), "--base", "HEAD")
    assert code == 1
    assert "deploy/prod.yml: changed, but outside Scope" in out
    assert "src/a.py" not in out


def test_scope_in_bounds_passes(repo):
    repo.write("src/a.py", "x = 2\n")
    body = repo.root / "body.md"
    body.write_text(FULL.replace("src/agent_checks/**, tests/**, docs/**", "src/**, body.md"))
    assert run("-C", str(repo.root), "--body", str(body), "--base", "HEAD")[0] == 0


def test_malformed_values_fail():
    body = (
        FULL.replace("Egoushka/agent-checks#14", "#14")
        .replace("ruff  pass  run 123", "ruff  fail  run 124")
        .replace("**Risk:** none", "**Risk:** none, deploy")
        .replace("docs/specs/change-record-rule.md", "the spec")
    )
    fields = sorted(p.field for p in change_record.check(body).problems)
    assert fields == ["Checks", "Claim", "Risk", "Spec"]


def test_plain_labels_and_agent_none():
    body = "Spec: https://github.com/o/r/issues/1\nClaim: o/r#1\nChecks: t pass run 1\nScope: src/**\nRisk: public-api, migration\nAgent: none\n"
    assert change_record.check(body).ok


def test_reads_the_pull_request_event(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"body": without("Agent")}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    code, out = run("--format", "github")
    assert code == 1
    assert out.startswith("::error title=change-record Agent::Agent: missing")


def test_no_body_is_a_usage_error(monkeypatch):
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert run()[0] == 3
