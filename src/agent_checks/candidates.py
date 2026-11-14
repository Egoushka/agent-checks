"""Mine rejected PRs into candidate rules, and replay a candidate against real history.

A rejected PR is a labelled example of what an agent got wrong: a reviewer (the owner or a judge)
pointed at one line and said why. `mine()` groups those records by category and language and, where
the same category recurs across several distinct PRs, builds a regex template from the lines they
flagged (the tokens they share become the pattern; the tokens that differ become a wildcard).

A mined pattern is a guess, not a rule: `replay()` runs it over real history the way `cli.cmd_bench`
does (one FileChange list per commit from gitdiff.commit) and reports every added line it would have
flagged. Zero hits across that history is the calibration AGENTS.md asks for before a rule leaves
`warn`; any hit is a false positive, and the candidate stays hand-written.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import engine, gitdiff

REQUIRED = ("pr", "path", "lang", "line", "category", "reason")


@dataclass(frozen=True)
class RejectedCase:
    """One flagged line from a rejected PR. `category` is the short slug a review tool gives a finding
    (e.g. `agent-checks: allow <category>` style ids); cases with the same category and language are what
    `mine()` groups into one candidate."""

    pr: str
    path: str
    lang: str
    line: str
    category: str
    reason: str


def load_cases(path: Path) -> list[RejectedCase]:
    """`path` is a JSON file (a record, or a list of records) or a directory of such files."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        raise ValueError(f"{path}: no .json file found")
    cases: list[RejectedCase] = []
    for f in files:
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"cannot read {f}: {e}") from e
        for i, item in enumerate(data if isinstance(data, list) else [data]):
            try:
                missing = [k for k in REQUIRED if not item.get(k)]
            except AttributeError:
                raise ValueError(f"{f}[{i}]: not an object") from None
            if missing:
                raise ValueError(f"{f}[{i}]: missing {', '.join(missing)}")
            cases.append(RejectedCase(**{k: str(item[k]) for k in REQUIRED}))
    return cases


@dataclass(frozen=True)
class Candidate:
    id: str
    lang: str
    pattern: str
    summary: str
    message: str
    support: tuple[str, ...] = ()  # the distinct PRs this pattern was mined from

    def to_json(self) -> dict:
        return {"id": self.id, "lang": self.lang, "pattern": self.pattern, "summary": self.summary, "message": self.message, "support": list(self.support)}


_TOKEN = re.compile(r"\w+|[^\w\s]")


def _tokenize(line: str) -> list[str]:
    return _TOKEN.findall(line)


def _template(lines: list[str]) -> str | None:
    """A regex built from tokens every line shares, in the order the first line has them; a run of
    tokens that differ becomes `\\S+`. None when the lines share nothing (too broad to be a pattern)."""
    base = _tokenize(lines[0])
    if not base:
        return None
    keep = [True] * len(base)
    for other in lines[1:]:
        sm = difflib.SequenceMatcher(a=base, b=_tokenize(other), autojunk=False)
        matched = [False] * len(base)
        for blk in sm.get_matching_blocks():
            for i in range(blk.a, blk.a + blk.size):
                matched[i] = True
        keep = [k and m for k, m in zip(keep, matched)]
    if not any(keep):
        return None
    parts: list[str] = []
    i = 0
    while i < len(base):
        if keep[i]:
            parts.append(re.escape(base[i]))
            i += 1
        else:
            while i < len(base) and not keep[i]:
                i += 1
            parts.append(r"\S+")
    return r"\s*".join(parts)


def mine(cases: list[RejectedCase], min_support: int = 2) -> list[Candidate]:
    """One candidate per (category, lang) with at least `min_support` distinct rejected PRs behind it.
    A pattern seen on only one PR is an incident, not a pattern; AGENTS.md's calibration step is `replay`,
    not this count, but a single example has nothing to generalise from."""
    groups: dict[tuple[str, str], list[RejectedCase]] = {}
    for c in cases:
        groups.setdefault((c.category, c.lang), []).append(c)
    out = []
    for (category, lang), group in sorted(groups.items()):
        prs = sorted({c.pr for c in group})
        if len(prs) < min_support:
            continue
        pattern = _template([c.line for c in group])
        if not pattern:
            continue
        reason = Counter(c.reason for c in group).most_common(1)[0][0]
        out.append(
            Candidate(
                id=f"{category}.{lang}",
                lang=lang,
                pattern=pattern,
                summary=reason,
                message=f"{reason} (mined from {len(prs)} rejected PRs: {', '.join(prs)}; replay on history before raising this above warn).",
                support=tuple(prs),
            )
        )
    return out


def write_candidate(c: Candidate, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{c.id}.json"
    p.write_text(json.dumps(c.to_json(), indent=2) + "\n")
    return p


def load_candidate(path: Path) -> Candidate:
    data = json.loads(path.read_text())
    missing = [k for k in ("id", "lang", "pattern") if not data.get(k)]
    if missing:
        raise ValueError(f"{path}: missing {', '.join(missing)}")
    return Candidate(
        id=data["id"], lang=data["lang"], pattern=data["pattern"], summary=data.get("summary", ""), message=data.get("message", ""), support=tuple(data.get("support", []))
    )


@dataclass
class Hit:
    sha: str
    path: str
    line: int
    text: str


@dataclass
class ReplayResult:
    repo: str
    commits: int
    hits: list[Hit] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.hits


def replay(candidate: Candidate, root: Path, n: int = 360) -> ReplayResult:
    """Run `candidate.pattern` over the added lines of the last `n` non-merge commits, the way
    cli.cmd_bench walks history for timing. A hit here is a line real history added and a reviewer
    let through, so it is a false positive for the candidate, not evidence for it."""
    shas = gitdiff.git(root, "rev-list", "--no-merges", f"-{n}", "HEAD").decode().split()
    pat = re.compile(candidate.pattern)
    hits: list[Hit] = []
    for sha in shas:
        changes, tmp = gitdiff.commit(root, sha)
        try:
            for c in changes:
                if c.binary or not c.added or engine.lang_of(c) != candidate.lang:
                    continue
                for line_no, text in c.added.items():
                    if pat.search(text):
                        hits.append(Hit(sha, c.path, line_no, text))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return ReplayResult(repo=root.name, commits=len(shas), hits=hits)


def render_mine(mined: list[Candidate], out_dir: Path) -> str:
    if not mined:
        return "agent-checks: no category recurred across enough rejected PRs yet; nothing mined.\n"
    lines = [f"agent-checks: {len(mined)} candidate rule{'s' if len(mined) != 1 else ''} written to {out_dir}:"]
    for c in mined:
        lines.append(f"  {c.id}  ({len(c.support)} PRs: {', '.join(c.support)})")
    lines.append("Replay each one on history before raising it above warn: agent-checks replay <file> -C <repo>.")
    return "\n".join(lines) + "\n"


DEFAULT_STATE = Path(".agent-checks/candidate-state.json")
STOP_AFTER = 3  # the issue's stop condition: this many candidates in a row with false positives means stay hand-written


def load_streak(path: Path) -> int:
    """The number of candidates replayed in a row (most recent first) that came back with false positives."""
    if not path.is_file():
        return 0
    try:
        return int(json.loads(path.read_text()).get("consecutive_false_positives", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return 0


def save_streak(path: Path, streak: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"consecutive_false_positives": streak}) + "\n")


def record_replay(res: ReplayResult, state_path: Path) -> int:
    """Update the on-disk streak of consecutive false-positive replays and return the new value: 0 after
    a clean replay (the streak resets), incremented after one with hits."""
    streak = 0 if res.ok else load_streak(state_path) + 1
    save_streak(state_path, streak)
    return streak


def render_replay(res: ReplayResult, streak: int = 0) -> str:
    if res.ok:
        return f"agent-checks: 0 false positives on {res.commits} commits of {res.repo}. Safe to raise this candidate above warn.\n"
    lines = [f"agent-checks: {len(res.hits)} false positive{'s' if len(res.hits) != 1 else ''} on {res.commits} commits of {res.repo}:"]
    for h in res.hits[:20]:
        lines.append(f"  {h.sha[:12]} {h.path}:{h.line}  | {h.text.strip()[:140]}")
    if len(res.hits) > 20:
        lines.append(f"  ... and {len(res.hits) - 20} more")
    lines.append("This candidate still fires on accepted code. Narrow the pattern and mine again, or stay hand-written.")
    if streak >= STOP_AFTER:
        lines.append(
            f"agent-checks: {streak} candidates in a row have had false positives on replay. Per the stop condition, "
            "stop mining this kind of candidate and write the next rule by hand instead."
        )
    return "\n".join(lines) + "\n"
