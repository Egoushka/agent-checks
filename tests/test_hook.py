import io
import json
import sys

from agent_checks import cli


def run_hook(monkeypatch, capsys, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = cli.main(["hook", "claude"])
    return code, capsys.readouterr().err


def test_hook_blocks_with_message(repo, monkeypatch, capsys):
    repo.write("src/A.cs", "public async void Run() { await F(); }\n")
    code, err = run_hook(monkeypatch, capsys, {"tool_name": "Write", "tool_input": {"file_path": str(repo.root / "src/A.cs")}})
    assert code == 2
    assert "async-void" in err and "src/A.cs:1" in err and "Return Task" in err


def test_hook_is_quiet_on_clean_file(repo, monkeypatch, capsys):
    repo.write("src/A.cs", "public async Task Run() { await F(); }\n")
    code, err = run_hook(monkeypatch, capsys, {"tool_name": "Edit", "tool_input": {"file_path": str(repo.root / "src/A.cs")}})
    assert (code, err) == (0, "")


def test_hook_needs_opt_in(repo, monkeypatch, capsys):
    (repo.root / ".agent-checks.toml").unlink()
    repo.write("src/A.cs", "public async void Run() { await F(); }\n")
    code, _ = run_hook(monkeypatch, capsys, {"tool_name": "Write", "tool_input": {"file_path": str(repo.root / "src/A.cs")}})
    assert code == 0


def test_hook_ignores_non_repo_and_bad_payload(tmp_path, monkeypatch, capsys):
    (tmp_path / "x.cs").write_text("public async void Run() {}\n")
    assert run_hook(monkeypatch, capsys, {"tool_input": {"file_path": str(tmp_path / "x.cs")}})[0] == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert cli.main(["hook", "claude"]) == 0
