"""Replay candidate ast-grep rules on real history: a rule that fires on an already-accepted commit
is a false positive on that rule, so it stays hand-written. A rule with zero fires over the history is
a candidate for promotion into the rule pack (the calibration step AGENTS.md describes doing by hand,
over `agent-checks check --commit` and a few repos).

Mining rejected PRs into candidate rule files is a separate job: it needs a feed of rejected PRs (an
issue tracker or forge API) this module does not read. This module answers the half of the plan that
is deterministic and local: given a directory of candidate rules, written by that job or by hand, does
the rule fire on history that was already accepted?
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import gitdiff
from .engine import tool

MAX_EXAMPLES = 10
_ID = re.compile(r"^id:\s*(\S+)", re.MULTILINE)


@dataclass
class RuleReplay:
    id: str
    count: int = 0  # every fire on an added line of an already-accepted commit
    hits: list[str] = field(default_factory=list)  # capped at MAX_EXAMPLES, "repo@sha path:line"


def candidate_ids(rule_dir: Path) -> list[str]:
    """The `id:` of every YAML document under rule_dir, in file then document order."""
    ids: list[str] = []
    for f in sorted(rule_dir.glob("*.yml")) + sorted(rule_dir.glob("*.yaml")):
        for doc in re.split(r"^---\s*$", f.read_text(encoding="utf-8"), flags=re.MULTILINE):
            m = _ID.search(doc)
            if m:
                ids.append(m.group(1))
    return ids


def _sgconfig(rule_dir: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="agent-checks-candidates-"))
    (tmp / "sgconfig.yml").write_text(f"ruleDirs: [{json.dumps(str(rule_dir.resolve()))}]\n", encoding="utf-8")
    return tmp / "sgconfig.yml"


def replay(root: Path, rule_dir: Path, n: int) -> tuple[dict[str, RuleReplay], int]:
    """Run every candidate rule in rule_dir over root's last n non-merge commits.

    Returns the fires per rule id (only ids present in rule_dir) and the number of commits scanned.
    """
    exe = tool("ast-grep") or tool("sg")
    if not exe:
        raise RuntimeError("ast-grep is not installed")
    ids = candidate_ids(rule_dir)
    results = {rid: RuleReplay(rid) for rid in ids}
    config = _sgconfig(rule_dir)
    shas = gitdiff.git(root, "rev-list", "--no-merges", f"-{n}", "HEAD").decode().split()
    try:
        for sha in shas:
            changes, tmp = gitdiff.commit(root, sha)
            try:
                _scan_commit(exe, config, sha, changes, results)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    finally:
        shutil.rmtree(config.parent, ignore_errors=True)
    return results, len(shas)


def _scan_commit(exe: str, config: Path, sha: str, changes: list[gitdiff.FileChange], results: dict[str, RuleReplay]) -> None:
    files = [c for c in changes if c.added and not c.deleted and not c.binary and c.disk and c.disk.is_file()]
    if not files:
        return
    disk_to_change = {str(c.disk): c for c in files}
    p = subprocess.run([exe, "scan", "--config", str(config), "--json=stream", *disk_to_change], capture_output=True, text=True, check=False)
    for line in p.stdout.splitlines():
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = m.get("ruleId")
        rr = results.get(rid)
        c = disk_to_change.get(m.get("file")) or disk_to_change.get(str(Path(m.get("file", "")).resolve()))
        if not rr or not c:
            continue
        start, end = m["range"]["start"]["line"] + 1, m["range"]["end"]["line"] + 1
        if not any(ln in c.added for ln in range(start, end + 1)):
            continue
        rr.count += 1
        if len(rr.hits) < MAX_EXAMPLES:
            rr.hits.append(f"{sha[:8]} {c.path}:{start}")
