import json

import pytest
from conftest import Repo

from agent_checks import candidates, cli


def case(pr, line, category="swallowed-retry", lang="python", reason="a retry swallows the exception it was retrying on"):
    return candidates.RejectedCase(pr=pr, path="src/a.py", lang=lang, line=line, category=category, reason=reason)


def test_mine_needs_at_least_min_support_distinct_prs():
    cases = [case("o/r#1", "except Exception:\n"), case("o/r#1", "except ValueError:\n")]  # same PR twice
    assert candidates.mine(cases) == []
    assert candidates.mine(cases, min_support=1) != []


def test_mine_groups_by_category_and_language_and_builds_a_shared_pattern():
    cases = [
        case("o/r#1", "    except Exception:\n"),
        case("o/r#2", "    except OSError:\n"),
        case("o/r#2", "    except RuntimeError:\n"),  # same PR as #2; does not add support
    ]
    mined = candidates.mine(cases)
    assert [c.id for c in mined] == ["swallowed-retry.python"]
    c = mined[0]
    assert c.support == ("o/r#1", "o/r#2")
    assert "rejected PRs" in c.message
    import re

    pat = re.compile(c.pattern)
    assert pat.search("    except Exception:\n")
    assert pat.search("    except KeyError:\n")  # the shape generalises past the exact exception type
    assert not pat.search("    return 1\n")  # an unrelated line is not a false hit


def test_mine_skips_a_category_with_nothing_in_common():
    cases = [case("o/r#1", "x = 1\n"), case("o/r#2", "print('hi')\n")]
    assert candidates.mine(cases) == []


def test_load_cases_from_a_single_file(tmp_path):
    f = tmp_path / "rejections.json"
    f.write_text(json.dumps([{"pr": "o/r#1", "path": "a.py", "lang": "python", "line": "x = 1\n", "category": "c", "reason": "r"}]))
    loaded = candidates.load_cases(f)
    assert loaded == [candidates.RejectedCase(pr="o/r#1", path="a.py", lang="python", line="x = 1\n", category="c", reason="r")]


def test_load_cases_from_a_directory_of_files(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"pr": "o/r#1", "path": "a.py", "lang": "python", "line": "x\n", "category": "c", "reason": "r"}))
    (tmp_path / "b.json").write_text(json.dumps({"pr": "o/r#2", "path": "b.py", "lang": "python", "line": "y\n", "category": "c", "reason": "r"}))
    assert len(candidates.load_cases(tmp_path)) == 2


def test_load_cases_rejects_a_record_missing_a_field(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps([{"pr": "o/r#1", "path": "a.py", "lang": "python", "line": "x\n", "category": "c"}]))
    with pytest.raises(ValueError, match="reason"):
        candidates.load_cases(f)


def test_write_and_load_candidate_round_trip(tmp_path):
    c = candidates.Candidate(id="x.python", lang="python", pattern=r"x", summary="s", message="m", support=("o/r#1", "o/r#2"))
    p = candidates.write_candidate(c, tmp_path / "out")
    assert candidates.load_candidate(p) == c


def test_replay_reports_zero_false_positives_on_clean_history(tmp_path):
    repo = Repo(tmp_path)
    repo.write("src/a.py", "def f():\n    return 1\n")
    repo.commit()
    c = candidates.Candidate(id="x.python", lang="python", pattern=r"except\s*\S+", summary="", message="")
    res = candidates.replay(c, repo.root, n=10)
    assert res.ok and res.commits >= 1 and res.hits == []


def test_replay_finds_the_pattern_in_history(tmp_path):
    repo = Repo(tmp_path)
    repo.write("src/a.py", "try:\n    f()\nexcept Exception:\n    pass\n")
    repo.commit()
    c = candidates.Candidate(id="x.python", lang="python", pattern=r"except\s*\S+", summary="", message="")
    res = candidates.replay(c, repo.root, n=10)
    assert not res.ok
    assert any(h.path == "src/a.py" and "except" in h.text for h in res.hits)


def test_replay_ignores_a_match_in_a_different_language(tmp_path):
    repo = Repo(tmp_path)
    repo.write("src/a.cs", "catch (Exception) { }\n")
    repo.commit()
    c = candidates.Candidate(id="x.python", lang="python", pattern=r"catch", summary="", message="")
    res = candidates.replay(c, repo.root, n=10)
    assert res.ok


def test_render_mine_and_replay_text():
    c = candidates.Candidate(id="x.python", lang="python", pattern="x", summary="s", message="m", support=("o/r#1", "o/r#2"))
    assert "x.python" in candidates.render_mine([c], "candidates")
    assert "nothing mined" in candidates.render_mine([], "candidates")
    ok = candidates.ReplayResult(repo="r", commits=10, hits=[])
    assert "0 false positives" in candidates.render_replay(ok)
    bad = candidates.ReplayResult(repo="r", commits=10, hits=[candidates.Hit("abc123", "a.py", 1, "x\n")])
    assert "1 false positive" in candidates.render_replay(bad) and "a.py:1" in candidates.render_replay(bad)


def test_cli_mine_then_replay(tmp_path, capsys):
    cases = tmp_path / "rejections.json"
    cases.write_text(
        json.dumps(
            [
                {"pr": "o/r#1", "path": "a.py", "lang": "python", "line": "except Exception:\n", "category": "swallowed-retry", "reason": "swallows the exception"},
                {"pr": "o/r#2", "path": "b.py", "lang": "python", "line": "except OSError:\n", "category": "swallowed-retry", "reason": "swallows the exception"},
            ]
        )
    )
    out_dir = tmp_path / "candidates"
    assert cli.main(["mine", str(cases), "--out", str(out_dir)]) == 0
    assert "swallowed-retry.python" in capsys.readouterr().out
    candidate_file = out_dir / "swallowed-retry.python.json"
    assert candidate_file.is_file()

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = Repo(repo_dir)
    repo.write("src/a.py", "try:\n    f()\nexcept Exception:\n    pass\n")
    repo.commit()
    assert cli.main(["replay", str(candidate_file), "-C", str(repo.root)]) == 1
    assert "false positive" in capsys.readouterr().out

    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    clean = Repo(clean_dir)
    clean.write("src/b.py", "def f():\n    return 1\n")
    clean.commit()
    assert cli.main(["replay", str(candidate_file), "-C", str(clean.root)]) == 0
    assert "0 false positives" in capsys.readouterr().out
