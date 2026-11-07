import contextlib
import copy
import io
import json
from pathlib import Path

import pytest

from agent_checks import cli, record

FIXTURES = Path(__file__).parent / "fixtures" / "change-records"
VALID = sorted((FIXTURES / "valid").glob("*.json"))
BROKEN = sorted((FIXTURES / "broken").glob("*.json"))
FAILING = sorted((FIXTURES / "failing").glob("*.json"))


def load(p: Path) -> dict:
    return json.loads(p.read_text())


def run(*args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(["verify-record", *args])
    return code, buf.getvalue()


def test_there_are_three_good_and_three_broken_fixtures():
    assert len(VALID) == 3
    assert len(BROKEN) == 3


# The schema file is the contract other tools will use, so a real JSON Schema library must agree with the verifier.
@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_schema_accepts_good_records(path):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(load(path)["predicate"], record.load_schema())


@pytest.mark.parametrize("path", BROKEN, ids=lambda p: p.name)
def test_schema_rejects_broken_records(path):
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(load(path)["predicate"], record.load_schema())


def test_schema_is_itself_a_valid_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(record.load_schema())


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_verify_accepts_good_records(path):
    code, out = run(str(path))
    assert code == 0
    assert "ok" in out


@pytest.mark.parametrize("path", BROKEN, ids=lambda p: p.name)
def test_verify_rejects_broken_records_and_says_where(path):
    code, out = run(str(path))
    assert code == 1
    assert "not a valid change record" in out
    assert "$.predicate" in out


def test_verify_names_each_problem_in_a_broken_record():
    _, out = run(str(FIXTURES / "broken" / "empty-checks-bad-risk.json"))
    assert "$.predicate.checks: needs at least 1 item" in out
    assert '$.predicate.risk.level: must be one of "low", "medium", "high"' in out
    assert "$.predicate.agent: missing required field name" in out


def test_a_check_that_did_not_pass_fails_a_well_formed_record():
    path = FAILING[0]
    assert record.validate(load(path)["predicate"], record.load_schema()) == []
    code, out = run(str(path))
    assert code == 1
    assert "diff coverage: result is fail" in out
    assert "agent smells: result is skipped" in out


def test_missing_file_exits_non_zero():
    assert cli.main(["verify-record", str(FIXTURES / "nope.json")]) == 3


def test_not_json_exits_non_zero(tmp_path):
    f = tmp_path / "r.json"
    f.write_text("{not json")
    code, out = run(str(f))
    assert code == 1
    assert "not JSON" in out


def test_empty_file_exits_non_zero(tmp_path):
    f = tmp_path / "r.json"
    f.write_text("")
    assert run(str(f))[0] == 1


@pytest.mark.parametrize(
    "mutate, expect",
    [
        (lambda d: d.update(_type="https://in-toto.io/Statement/v0.1"), "$._type"),
        (lambda d: d.update(subject=[]), "$.subject"),
        (lambda d: d.update(subject=[{"name": "x"}]), "$.subject[0].digest"),
        (lambda d: d.update(subject=[{"digest": {"gitCommit": "NOT-HEX"}}]), "$.subject[0].digest"),
        (lambda d: d.update(predicateType="https://slsa.dev/provenance/v1"), "$.predicateType"),
        (lambda d: d.pop("predicate"), "$.predicate"),
    ],
    ids=["type", "no-subject", "no-digest", "bad-digest", "other-predicate", "no-predicate"],
)
def test_statement_layer_problems_fail(tmp_path, mutate, expect):
    doc = copy.deepcopy(load(VALID[0]))
    mutate(doc)
    f = tmp_path / "r.json"
    f.write_text(json.dumps(doc))
    code, out = run(str(f))
    assert code == 1
    assert expect in out


def test_a_json_array_is_not_a_statement(tmp_path):
    f = tmp_path / "r.json"
    f.write_text("[]")
    code, out = run(str(f))
    assert code == 1
    assert "must be a JSON object" in out


def test_unknown_fields_are_ignored():
    doc = load(FIXTURES / "valid" / "full.json")
    assert "futureField" in doc["predicate"]
    assert record.verify(doc).ok


def test_github_format_writes_annotations():
    code, out = run("--format", "github", str(FIXTURES / "broken" / "missing-claim.json"))
    assert code == 1
    assert out.startswith("::error file=")
    assert "missing required field claim" in out
    code, out = run("--format", "github", str(VALID[0]))
    assert code == 0
    assert "::error" not in out


def test_the_example_in_the_format_doc_is_valid():
    doc = (Path(__file__).parent.parent / "docs" / "change-record-v0.1.md").read_text()
    example = json.loads(doc.split("```json\n", 1)[1].split("```", 1)[0])
    v = record.verify(example)
    assert v.ok, [str(p) for p in v.problems + v.not_passed]
