"""Change records: an in-toto Statement whose predicate says what a change claims and which checks prove it.

verify-record reads a Statement and exits non-zero unless it is well formed and every check in it passed.
It does not verify a signature (that is the job of whatever signed the Statement) and it does not fetch evidence.
The schema is the file in data/, read here with a small validator so the run-time stays stdlib only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

PREDICATE_TYPE = "https://github.com/Egoushka/agent-checks/change-record/v0.1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
SCHEMA_FILE = "change-record-v0.1.schema.json"

_HEX = re.compile(r"[0-9a-f]+")


@dataclass
class Problem:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass
class Verdict:
    problems: list[Problem] = field(default_factory=list)  # the record is malformed
    not_passed: list[Problem] = field(default_factory=list)  # well formed, but a check did not pass

    @property
    def ok(self) -> bool:
        return not self.problems and not self.not_passed


def load_schema() -> dict:
    return json.loads((resources.files("agent_checks") / "data" / SCHEMA_FILE).read_text(encoding="utf-8"))


def validate(value: object, schema: dict, root: dict | None = None, at: str = "$") -> list[Problem]:
    """The JSON Schema keywords the change-record schema uses, and no others."""
    root = root or schema
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        return validate(value, node, root, at)
    out: list[Problem] = []
    t = schema.get("type")
    if t and not _is_type(value, t):
        return [Problem(at, f"must be {_article(t)}, got {_kind(value)}")]
    if "enum" in schema and value not in schema["enum"]:
        out.append(Problem(at, "must be one of " + ", ".join(json.dumps(v) for v in schema["enum"])))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            out.append(Problem(at, "must not be empty"))
        if len(value) > schema.get("maxLength", len(value)):
            out.append(Problem(at, f"must be at most {schema['maxLength']} characters"))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(Problem(at, f"does not match {schema['pattern']}"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            out.append(Problem(at, f"needs at least {schema['minItems']} item{'s' if schema['minItems'] != 1 else ''}"))
        if "items" in schema:
            for i, item in enumerate(value):
                out += validate(item, schema["items"], root, f"{at}[{i}]")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                out.append(Problem(at, f"missing required field {name}"))
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties")
        for name, item in value.items():
            if name in props:
                out += validate(item, props[name], root, f"{at}.{name}")
            elif isinstance(extra, dict):
                out += validate(item, extra, root, f"{at}.{name}")
    return out


def _is_type(value: object, t: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
    }[t]


def _article(t: str) -> str:
    return ("an " if t[0] in "aeiou" else "a ") + t


def _kind(value: object) -> str:
    return "null" if value is None else {dict: "an object", list: "an array", str: "a string", bool: "a boolean"}.get(type(value), "a number")


def check_statement(doc: object) -> list[Problem]:
    """The in-toto Statement layer: _type, subject with a digest, predicateType, predicate."""
    if not isinstance(doc, dict):
        return [Problem("$", "a Statement must be a JSON object")]
    out: list[Problem] = []
    if doc.get("_type") != STATEMENT_TYPE:
        out.append(Problem("$._type", f"must be {STATEMENT_TYPE}"))
    subject = doc.get("subject")
    if not isinstance(subject, list) or not subject:
        out.append(Problem("$.subject", "needs at least one subject"))
    else:
        for i, s in enumerate(subject):
            digest = s.get("digest") if isinstance(s, dict) else None
            ok = isinstance(digest, dict) and digest and all(isinstance(v, str) and _HEX.fullmatch(v) for v in digest.values())
            if not ok:
                out.append(Problem(f"$.subject[{i}].digest", "every subject needs a digest of lowercase hex values"))
    if doc.get("predicateType") != PREDICATE_TYPE:
        out.append(Problem("$.predicateType", f"must be {PREDICATE_TYPE}"))
    if not isinstance(doc.get("predicate"), dict):
        out.append(Problem("$.predicate", "the change record is missing"))
    return out


def verify(doc: object) -> Verdict:
    v = Verdict(problems=check_statement(doc))
    predicate = doc.get("predicate") if isinstance(doc, dict) else None
    if isinstance(predicate, dict):
        v.problems += [Problem("$.predicate" + p.path.removeprefix("$"), p.message) for p in validate(predicate, load_schema())]
        for i, check in enumerate(predicate.get("checks") or []):
            if isinstance(check, dict) and check.get("result") in ("fail", "error", "skipped"):
                label = check.get("name") or check.get("command") or f"check {i}"
                v.not_passed.append(Problem(f"$.predicate.checks[{i}]", f"{label}: result is {check['result']}, not pass"))
    return v


def verify_file(path: Path) -> Verdict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"cannot read {path}: {e.strerror or e}") from e
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        return Verdict(problems=[Problem("$", f"not JSON: {e}")])
    return verify(doc)


def render(path: Path, v: Verdict, fmt: str) -> str:
    lines: list[str] = []
    if fmt == "github":
        for p in v.problems:
            lines.append(f"::error file={path},title=change record invalid::{p}")
        for p in v.not_passed:
            lines.append(f"::error file={path},title=change record check did not pass::{p}")
        if v.ok:
            lines.append(f"agent-checks: {path} ok")
        return "\n".join(lines) + "\n"
    if v.ok:
        return f"agent-checks verify-record: {path} ok\n"
    if v.problems:
        lines.append(f"agent-checks verify-record: {path} is not a valid change record ({len(v.problems)} problem{'s' if len(v.problems) != 1 else ''}):")
        lines += [f"  {p}" for p in v.problems]
    if v.not_passed:
        lines.append(f"agent-checks verify-record: {path} records {len(v.not_passed)} check{'s' if len(v.not_passed) != 1 else ''} that did not pass:")
        lines += [f"  {p}" for p in v.not_passed]
    return "\n".join(lines) + "\n"
