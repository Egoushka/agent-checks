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


def test_install_files_only_leaves_hooks_alone(repo):
    repo.git("config", "core.hooksPath", ".githooks")
    (repo.root / ".githooks").mkdir()
    (repo.root / ".githooks" / "pre-commit").write_text("#!/bin/sh\ngitleaks git --staged\n")
    repo.git("remote", "add", "origin", "https://github.com/x/y.git")
    assert cli.main(["install", str(repo.root), "--files-only"]) == 0
    text = (repo.root / "lefthook.yml").read_text()
    assert "agent-checks check --staged" in text and "run: .githooks/pre-commit" in text
    assert "gitleaks" not in text  # the repo's own pre-commit already runs it
    assert "\n\n\n" not in text
    assert "Egoushka/agent-checks@v" in (repo.root / ".github/workflows/agent-checks.yml").read_text()
    assert repo.git("config", "--get", "core.hooksPath").strip() == ".githooks"


def test_install_writes_betterleaks_and_zizmor(repo):
    repo.write(".github/workflows/ci.yml", "name: ci\non: push\njobs: {}\n")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "workflows")
    assert cli.main(["install", str(repo.root), "--files-only"]) == 0
    text = (repo.root / "lefthook.yml").read_text()
    assert "betterleaks git --staged --redact --no-banner --disable-rule generic-password,generic-credential-uri" in text
    assert "gitleaks" not in text
    assert "zizmor --offline --no-progress {staged_files}" in text
    assert "hash-pin" in (repo.root / ".github/zizmor.yml").read_text()


def test_install_skips_zizmor_without_workflows(repo):
    assert cli.main(["install", str(repo.root), "--files-only"]) == 0
    assert "zizmor" not in (repo.root / "lefthook.yml").read_text()
    assert not (repo.root / ".github/zizmor.yml").exists()
