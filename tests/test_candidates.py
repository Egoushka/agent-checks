import json

from agent_checks import cli

HAS_PRINT = """\
id: has-print
language: Python
rule:
  pattern: print($$$ARGS)
"""

NO_MATCH = """\
id: no-match
language: Python
rule:
  pattern: totally_unused_sentinel_call($$$ARGS)
"""


def run_candidates(capsys, rule_dir, *dirs):
    code = cli.main(["candidates", str(rule_dir), *[str(d) for d in dirs], "-n", "50", "--format", "json"])
    return code, capsys.readouterr().out


def test_candidate_with_a_fire_on_history_is_a_false_positive(repo, tmp_path, capsys):
    repo.write("src/a.py", 'print("hi")\n')
    repo.commit("add a print")

    rule_dir = tmp_path / "candidates"
    rule_dir.mkdir()
    (rule_dir / "has-print.yml").write_text(HAS_PRINT)
    (rule_dir / "no-match.yml").write_text(NO_MATCH)

    code, out = run_candidates(capsys, rule_dir, repo.root)
    data = json.loads(out)
    rules = {r["id"]: r for r in data["rules"]}
    assert code == 1
    assert rules["has-print"]["falsePositives"] >= 1
    assert any("src/a.py" in ex for ex in rules["has-print"]["examples"])
    assert rules["no-match"]["falsePositives"] == 0


def test_candidates_pass_when_no_rule_fires_on_history(repo, tmp_path, capsys):
    repo.write("src/a.py", "x = 1\n")
    repo.commit("harmless change")

    rule_dir = tmp_path / "candidates"
    rule_dir.mkdir()
    (rule_dir / "no-match.yml").write_text(NO_MATCH)

    code, out = run_candidates(capsys, rule_dir, repo.root)
    data = json.loads(out)
    assert code == 0
    assert data["rules"] == [{"id": "no-match", "falsePositives": 0, "examples": []}]


def test_candidates_text_format_reports_readiness(repo, tmp_path, capsys):
    repo.write("src/a.py", "x = 1\n")
    repo.commit("harmless change")

    rule_dir = tmp_path / "candidates"
    rule_dir.mkdir()
    (rule_dir / "no-match.yml").write_text(NO_MATCH)

    code = cli.main(["candidates", str(rule_dir), str(repo.root), "-n", "50"])
    out = capsys.readouterr().out
    assert code == 0
    assert "no-match: 0 false positives on history" in out


def test_candidates_rejects_an_empty_rule_dir(tmp_path, repo, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    code = cli.main(["candidates", str(empty), str(repo.root)])
    assert code == 3
