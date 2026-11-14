import json

from conftest import Repo

from agent_checks import cli

BAD = "public async void Run() { await F(); }\n"


def run_count(capsys, *args):
    code = cli.main(["count", *args])
    return code, capsys.readouterr().out


def test_count_sums_open_findings_across_repos_without_names(repo, tmp_path_factory, capsys):
    other = Repo(tmp_path_factory.mktemp("other"))
    repo.write("src/A.cs", BAD)
    repo.commit()
    other.write("src/B.cs", BAD)
    other.write("src/C.cs", BAD)
    other.commit()
    code, out = run_count(capsys, str(repo.root), str(other.root))
    data = json.loads(out)
    assert code == 0
    assert data["findings"] == 3
    assert set(data) == {"findings", "asOf"}
    assert data["asOf"].endswith("Z") and "T" in data["asOf"]
    assert "A.cs" not in out and repo.root.name not in out


def test_count_is_zero_for_a_clean_repo(repo, capsys):
    assert json.loads(run_count(capsys, str(repo.root))[1])["findings"] == 0


def test_count_writes_the_file_and_fails_on_a_non_repo(repo, tmp_path, capsys):
    out = tmp_path / "findings.json"
    assert run_count(capsys, str(repo.root), "--out", str(out))[0] == 0
    assert json.loads(out.read_text())["findings"] == 0
    out.unlink()
    code, _ = run_count(capsys, str(tmp_path / "missing"), "--out", str(out))
    assert code == 3 and not out.exists()
