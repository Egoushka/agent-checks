"""Diff coverage: what share of the executable lines a change adds is run by tests.

Reads a Cobertura XML report (the test run already writes one) and the same added-line map the rules use.
A line the report does not list is not executable (blank, comment, signature) and does not count.
"""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .gitdiff import FileChange

DEFAULT_FAIL_UNDER = 80.0


@dataclass
class Report:
    # report-relative file name -> executable line -> hits
    files: dict[str, dict[int, int]] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)


@dataclass
class Result:
    covered: int = 0
    missed: dict[str, list[int]] = field(default_factory=dict)
    unmeasured: list[str] = field(default_factory=list)  # changed files the report does not mention

    @property
    def total(self) -> int:
        return self.covered + sum(len(v) for v in self.missed.values())

    @property
    def percent(self) -> float:
        return 100.0 if self.total == 0 else 100.0 * self.covered / self.total


def parse_report(path: Path) -> Report:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        raise ValueError(f"cannot read coverage report {path}: {e}") from e
    if root.tag != "coverage":
        raise ValueError(f"{path} is not a Cobertura coverage report (root element <{root.tag}>)")
    rep = Report(sources=[(s.text or "").strip() for s in root.iter("source") if (s.text or "").strip()])
    for cls in root.iter("class"):
        name = (cls.get("filename") or "").replace("\\", "/")
        if not name:
            continue
        lines = rep.files.setdefault(name, {})
        for ln in cls.iter("line"):
            n, hits = ln.get("number"), ln.get("hits")
            if n is None or hits is None:
                continue
            # The same file can sit in several classes; a line counts as run if any of them ran it.
            lines[int(n)] = max(lines.get(int(n), 0), int(float(hits)))
    return rep


def _candidates(root: Path, rep: Report) -> dict[str, dict[int, int]]:
    """Map repo-relative paths to their line data, trying each source root the report names."""
    out: dict[str, dict[int, int]] = {}
    base = root.resolve().as_posix()
    for name, lines in rep.files.items():
        out[posixpath.normpath(name)] = lines
        for src in rep.sources:
            full = posixpath.normpath(posixpath.join(src.replace("\\", "/"), name))
            if full.startswith(base + "/"):
                out[full[len(base) + 1 :]] = lines
    return out


def _lookup(path: str, known: dict[str, dict[int, int]]) -> dict[int, int] | None:
    if path in known:
        return known[path]
    # Reports made inside a package folder name files relative to it; match on the path tail.
    tails = [k for k in known if path.endswith("/" + k)]
    return known[max(tails, key=len)] if tails else None


def measure(root: Path, changes: list[FileChange], rep: Report, skip: set[str] = frozenset()) -> Result:
    known = _candidates(root, rep)
    res = Result()
    for c in changes:
        if c.deleted or c.binary or not c.added or c.path in skip:
            continue
        lines = _lookup(c.path, known)
        if lines is None:
            res.unmeasured.append(c.path)
            continue
        for n in sorted(c.added):
            if n not in lines:
                continue
            if lines[n] > 0:
                res.covered += 1
            else:
                res.missed.setdefault(c.path, []).append(n)
    return res


def ranges(nums: list[int]) -> str:
    groups: list[list[int]] = []
    for n in nums:
        if groups and n == groups[-1][-1] + 1:
            groups[-1].append(n)
        else:
            groups.append([n])
    return ",".join(str(g[0]) if len(g) == 1 else f"{g[0]}-{g[-1]}" for g in groups)


def render(res: Result, fail_under: float, report_only: bool, fmt: str = "text") -> str:
    ok = res.percent >= fail_under
    head = f"{res.percent:.0f}% of {res.total} added executable lines are run by tests (need {fail_under:g}%)"
    notes = f"; {len(res.unmeasured)} changed file(s) not in the report" if res.unmeasured else ""
    if fmt == "github":
        out = []
        level = "warning" if report_only else "error"
        for path, nums in res.missed.items():
            for n in nums:
                out.append(f"::{level} file={path},line={n},title=agent-checks diff-coverage::{MESSAGE}")
        out.append(f"agent-checks diff-coverage: {head}{notes}" if ok else f"::{level} title=agent-checks diff-coverage::{head}{notes}")
        return "\n".join(out) + "\n"
    if ok:
        return f"agent-checks diff-coverage: ok, {head}{notes}\n"
    lines = [f"agent-checks diff-coverage: {head}{notes}" + (" (report only, not failing)" if report_only else ""), "", MESSAGE]
    for path, nums in res.missed.items():
        lines.append(f"  {path}:{ranges(nums)}")
    lines += ["", "Write a test that reaches these lines and asserts on their result, then run the same command again."]
    return "\n".join(lines) + "\n"


MESSAGE = (
    "No test runs these added lines. Add a test that executes them and asserts on the outcome; "
    "do not mark them `pragma: no cover` or exclude the file to get past the check."
)
