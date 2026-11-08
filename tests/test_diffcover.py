import contextlib
import io

import pytest

from agent_checks import cli, diffcover


def cobertura(files: dict[str, dict[int, int]], source: str | None = None) -> str:
    src = f"<sources><source>{source}</source></sources>" if source else ""
    classes = "".join(
        f'<class name="{n}" filename="{n}"><lines>' + "".join(f'<line number="{ln}" hits="{h}"/>' for ln, h in lines.items()) + "</lines></class>"
        for n, lines in files.items()
    )
    return f'<?xml version="1.0"?><coverage version="7">{src}<packages><package name="p"><classes>{classes}</classes></package></packages></coverage>'


def run(repo, *args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(["diffcover", "-C", str(repo.root), *args])
    return code, buf.getvalue()


@pytest.fixture
def change(repo):
    """A branch that adds src/a.py: lines 1-4 are executable, line 5 is a comment."""
    repo.git("switch", "-q", "-c", "feature")
    repo.write("src/a.py", "def f(x):\n    if x:\n        return 1\n    return 2\n# note\n")
    repo.commit("add a")
    return repo


def test_fails_below_threshold_and_names_the_missed_lines(change):
    change.write("coverage.xml", cobertura({"src/a.py": {1: 1, 2: 1, 3: 0, 4: 0}}))
    code, out = run(change, "--base", "main")
    assert code == 1
    assert "50% of 4 added executable lines" in out
    assert "src/a.py:3-4" in out
    assert "pragma: no cover" in out  # tells the agent not to dodge the check


def test_passes_at_threshold(change):
    change.write("coverage.xml", cobertura({"src/a.py": {1: 1, 2: 1, 3: 1, 4: 0}}))
    code, out = run(change, "--base", "main", "--fail-under", "75")
    assert code == 0
    assert "ok, 75%" in out


def test_report_only_prints_but_exits_zero(change):
    change.write("coverage.xml", cobertura({"src/a.py": {1: 0, 2: 0, 3: 0, 4: 0}}))
    code, out = run(change, "--base", "main", "--report-only")
    assert code == 0
    assert "0% of 4" in out
    assert "report only" in out
    assert "src/a.py:1-4" in out


def test_only_added_lines_count(change):
    change.git("switch", "-q", "main")
    change.git("switch", "-q", "-c", "second")
    change.write("src/a.py", "def f(x):\n    if x:\n        return 1\n    return 2\n")
    change.commit("base file")
    change.write("src/a.py", "def f(x):\n    if x:\n        return 1\n    return 2\n\n\ndef g():\n    return 3\n")
    change.write("coverage.xml", cobertura({"src/a.py": {1: 0, 2: 0, 3: 0, 4: 0, 7: 1, 8: 1}}))
    code, out = run(change, "--base", "HEAD")
    assert code == 0  # lines 1-4 are old and unrun, g() is new and run
    assert "100% of 2" in out


def test_non_executable_lines_do_not_count(change):
    change.write("coverage.xml", cobertura({"src/a.py": {1: 1, 2: 1, 3: 1, 4: 1}}))
    code, out = run(change, "--base", "main")
    assert code == 0
    assert "100% of 4" in out


def test_file_missing_from_report_is_listed_not_counted(change):
    change.write("coverage.xml", cobertura({"src/other.py": {1: 1}}))
    code, out = run(change, "--base", "main")
    assert code == 0
    assert "100% of 0" in out
    assert "1 changed file(s) not in the report" in out


def test_source_root_prefix_is_resolved(change):
    # pytest-cov with `src/` layout names the file `pkg/a.py` and the source `<repo>/src`.
    change.write("src/pkg/a.py", "def f():\n    return 1\n")
    change.commit("pkg")
    change.write("coverage.xml", cobertura({"pkg/a.py": {1: 1, 2: 0}}, source=str(change.root.resolve() / "src")))
    assert run(change, "--base", "main", "--fail-under", "1")[0] == 0
    assert "src/pkg/a.py:2" in run(change, "--base", "main", "--fail-under", "99")[1]


def test_tail_match_when_report_is_made_inside_a_subfolder(change):
    change.write("coverage.xml", cobertura({"a.py": {1: 1, 2: 1, 3: 1, 4: 1}}))
    code, out = run(change, "--base", "main")
    assert code == 0
    assert "100% of 4" in out


def test_a_line_counts_as_run_if_any_class_ran_it(change):
    xml = (
        '<coverage><packages><package><classes>'
        '<class filename="src/a.py"><lines><line number="1" hits="0"/></lines></class>'
        '<class filename="src/a.py"><lines><line number="1" hits="3"/></lines></class>'
        "</classes></package></packages></coverage>"
    )
    change.write("coverage.xml", xml)
    assert "100% of 1" in run(change, "--base", "main")[1]


def test_no_added_code_passes(repo):
    repo.write("coverage.xml", cobertura({}))
    code, out = run(repo, "--base", "HEAD")
    assert code == 0
    assert "100% of 0" in out


def test_github_format_annotates_each_missed_line(change):
    change.write("coverage.xml", cobertura({"src/a.py": {1: 1, 2: 1, 3: 0, 4: 0}}))
    code, out = run(change, "--base", "main", "--format", "github")
    assert code == 1
    assert "::error file=src/a.py,line=3,title=agent-checks diff-coverage::" in out
    assert "::error file=src/a.py,line=4," in out
    _, out = run(change, "--base", "main", "--format", "github", "--report-only")
    assert "::warning file=src/a.py,line=3," in out
    assert "::error" not in out


def test_base_from_env(change, monkeypatch):
    monkeypatch.setenv("AGENT_CHECKS_BASE", "main")
    change.write("coverage.xml", cobertura({"src/a.py": {1: 0, 2: 0, 3: 0, 4: 0}}))
    assert run(change)[0] == 1


@pytest.mark.parametrize("content", ["not xml", "<report/>"])
def test_unreadable_report_is_an_error(change, content, capsys):
    change.write("coverage.xml", content)
    assert run(change, "--base", "main")[0] == 3
    assert "agent-checks:" in capsys.readouterr().err


def test_missing_report_is_an_error(change, capsys):
    assert run(change, "--base", "main")[0] == 3
    assert "cannot read coverage report" in capsys.readouterr().err


def test_ranges():
    assert diffcover.ranges([1, 2, 3, 7, 9, 10]) == "1-3,7,9-10"


def test_failing_percent_never_reads_as_the_threshold():
    res = diffcover.Result(covered=796, missed={"src/a.py": list(range(1, 205))})
    out = diffcover.render(res, 80, report_only=False)
    assert "79.6% of 1000 added executable lines" in out
    assert "(need 80%)" in out


def test_passing_percent_keeps_whole_numbers():
    res = diffcover.Result(covered=799, missed={"src/a.py": [1]})
    assert "ok, 100% of 800" in diffcover.render(res, 80, report_only=False)


@pytest.mark.parametrize(("percent", "fail_under", "expected"), [
    (79.6, 80, "79.6"),
    (79.996, 80, "79.99"),
    (80.0, 80, "80"),
    (50.0, 80, "50"),
    (80.004, 80.005, "80"),
    (80.0049, 80.0045, "80.01"),
])
def test_shown_stays_on_the_side_the_check_decided(percent, fail_under, expected):
    assert diffcover.shown(percent, fail_under) == expected
