"""The change-record rule: a pull request body carries Spec, Claim, Checks, Scope, Risk and Agent.

This is the plain-text form a person or an agent writes in the PR description; the JSON in-toto form is record.py.
The rule fails when a field is missing or malformed, when a check did not pass, and when a changed file falls
outside the globs in Scope. The spec is docs/specs/change-record-rule.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .engine import glob

FIELDS = ("Spec", "Claim", "Checks", "Scope", "Risk", "Agent")
RISKS = ("none", "migration", "secrets", "deploy", "public-api")

# `Spec: x`, `- Spec: x`, `**Spec:** x`, `**Spec**: x`, any case.
_LABEL = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*)?(" + "|".join(FIELDS) + r")(?:\*\*)?\s*:(?:\*\*)?\s*(.*)$", re.IGNORECASE)
_SPEC = re.compile(r"(?:\./)?docs/specs/[\w./-]+\.md|https?://\S+")
_CLAIM = re.compile(r"[\w.-]+/[\w.-]+#\d+")
_CHECK = re.compile(r"(\S+)\s+(pass|fail|error|skipped)\s+run\s+(\S+)", re.IGNORECASE)

FIX = {
    "Spec": "Add `Spec: docs/specs/<file>.md` (or the issue URL) to the PR body: the document the change implements.",
    "Claim": "Add `Claim: owner/repo#n` to the PR body: the issue this change claims to resolve.",
    "Checks": "Add `Checks: <test id>  pass  run <id>` to the PR body, one line per check that proves the claim.",
    "Scope": "Add `Scope: <glob>, <glob>` to the PR body: the files this change may touch.",
    "Risk": "Add `Risk: " + " | ".join(RISKS) + "` to the PR body (one or more, comma separated).",
    "Agent": "Add `Agent: <run id>, <model>, <cost>` to the PR body; a change written by hand says `Agent: none`.",
}


@dataclass
class Problem:
    field: str
    message: str
    path: str = ""

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else f"{self.field}: {self.message}"


@dataclass
class Report:
    fields: dict[str, list[str]] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def parse(body: str) -> dict[str, list[str]]:
    """Field name -> its entries. Indented lines and list items under a field continue it, up to a blank line or the next field."""
    out: dict[str, list[str]] = {}
    cur: str | None = None
    for raw in body.splitlines():
        line = raw.strip().strip("`").strip()
        m = _LABEL.match(line)
        if m:
            cur = next(f for f in FIELDS if f.lower() == m.group(1).lower())
            value = m.group(2).strip().strip("`").strip()
            out.setdefault(cur, []).extend([value] if value else [])
        elif cur and line and (raw[:1].isspace() or raw.lstrip().startswith(("- ", "* "))):
            out[cur].append(line.removeprefix("- ").removeprefix("* ").strip("`").strip())
        else:
            cur = None
    return out


def scope_globs(entries: list[str]) -> list[str]:
    return [g.strip("`") for e in entries for g in re.split(r"[,\s]+", e) if g.strip("`")]


def check(body: str, changed: list[str] | None = None) -> Report:
    """Check a PR body; with `changed` (repo-relative paths), also flag each one outside Scope."""
    fields = parse(body)
    rep = Report(fields=fields)
    for name in FIELDS:
        if not fields.get(name):
            rep.problems.append(Problem(name, f"missing. {FIX[name]}"))
    for v in fields.get("Spec", []):
        if not _SPEC.fullmatch(v):
            rep.problems.append(Problem("Spec", f"`{v}` is neither a docs/specs/*.md path nor a URL. {FIX['Spec']}"))
    for v in fields.get("Claim", []):
        if not _CLAIM.fullmatch(v):
            rep.problems.append(Problem("Claim", f"`{v}` is not owner/repo#n. {FIX['Claim']}"))
    for v in fields.get("Checks", []):
        m = _CHECK.fullmatch(v)
        if not m:
            rep.problems.append(Problem("Checks", f"`{v}` is not `<test id>  pass  run <id>`. {FIX['Checks']}"))
        elif m.group(2).lower() != "pass":
            rep.problems.append(Problem("Checks", f"{m.group(1)} is {m.group(2).lower()}, not pass. Fix the code until it passes, then record the passing run."))
    risks = [r.strip().lower() for v in fields.get("Risk", []) for r in re.split(r"[,|]", v) if r.strip()]
    for r in risks:
        if r not in RISKS:
            rep.problems.append(Problem("Risk", f"`{r}` is not one of {', '.join(RISKS)}."))
    if "none" in risks and len(set(risks)) > 1:
        rep.problems.append(Problem("Risk", "`none` cannot be combined with another risk. Keep the risks this change carries and drop `none`."))
    for v in fields.get("Agent", []):
        if v.lower() != "none" and len([p for p in v.split(",") if p.strip()]) != 3:
            rep.problems.append(Problem("Agent", f"`{v}` is not `<run id>, <model>, <cost>`. {FIX['Agent']}"))
    globs = scope_globs(fields.get("Scope", []))
    if globs and changed is not None:
        pats = [glob(g) for g in globs]
        for path in changed:
            if not any(p.match(path) for p in pats):
                rep.problems.append(
                    Problem(
                        "Scope",
                        "changed, but outside Scope. Revert the change to this file, or if the task needs it, add it to Scope and say why.",
                        path,
                    )
                )
    return rep


def render(rep: Report, fmt: str) -> str:
    if fmt == "github":
        lines = []
        for p in rep.problems:
            where = f"file={p.path}," if p.path else ""
            lines.append(f"::error {where}title=change-record {p.field}::{p}")
        if rep.ok:
            lines.append("agent-checks change-record: ok")
        return "\n".join(lines) + "\n"
    if rep.ok:
        return "agent-checks change-record: ok\n"
    n = len(rep.problems)
    lines = [f"agent-checks change-record: {n} problem{'s' if n != 1 else ''} in the PR body:"]
    lines += [f"  {p}" for p in rep.problems]
    lines.append("Edit the PR description to fix each one; do not drop a field to get past the rule.")
    return "\n".join(lines) + "\n"
