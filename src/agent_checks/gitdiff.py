"""Read a change from git: which lines it adds and removes, per file.

Every mode yields the same FileChange list. Content for the AST and lint passes
comes from where the change lives: the index for --staged, a commit for --commit,
the working tree otherwise. Index and commit content is written to a temp dir by
one `git cat-file --batch` call, so partial staging never shifts line numbers.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BINARY = re.compile(r"^Binary files (?:a/(.*)|/dev/null) and (?:b/(.*)|/dev/null) differ$")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class FileChange:
    path: str  # repo-relative, forward slashes
    added: dict[int, str] = field(default_factory=dict)  # 1-based line number in the new file -> text
    removed: list[str] = field(default_factory=list)
    new_file: bool = False
    deleted: bool = False
    no_final_newline: bool = False
    binary: bool = False
    disk: Path | None = None  # where the new content can be read


class GitError(RuntimeError):
    pass


def git(root: Path, *args: str, input: bytes | None = None, check: bool = True) -> bytes:
    p = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=root, input=input, capture_output=True, check=False)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout


def toplevel(start: Path) -> Path | None:
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, check=False)
    return Path(p.stdout.strip()) if p.returncode == 0 else None


def has_head(root: Path) -> bool:
    return subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=root, capture_output=True, check=False).returncode == 0


def parse_diff(text: str) -> list[FileChange]:
    changes: list[FileChange] = []
    cur: FileChange | None = None
    old = new = ""
    in_header = False
    is_new = False
    line_no = 0
    last_plus = False
    for line in text.splitlines():
        if line.startswith("diff --git "):
            cur, in_header, is_new, old, new = None, True, False, "", ""
            continue
        if in_header:
            if line.startswith("new file mode"):
                is_new = True
            elif line.startswith("--- "):
                old = _unquote(line[4:])
            elif line.startswith("+++ "):
                new = _unquote(line[4:])
                deleted = new == "/dev/null"
                path = (old if deleted else new)[2:]
                cur = FileChange(path=path, new_file=is_new or old == "/dev/null", deleted=deleted)
                changes.append(cur)
            elif line.startswith("Binary files "):
                m = BINARY.match(line)
                if m:
                    cur = FileChange(path=m.group(2) or m.group(1), new_file=m.group(1) is None, deleted=m.group(2) is None, binary=True)
                    changes.append(cur)
                continue
            elif line.startswith("@@"):
                in_header = False
            else:
                continue
            if in_header:
                continue
        if cur is None:
            continue
        if line.startswith("@@"):
            m = HUNK.match(line)
            line_no = int(m.group(1)) if m else 0
            last_plus = False
        elif line.startswith("+"):
            cur.added[line_no] = line[1:]
            line_no += 1
            last_plus = True
        elif line.startswith("-"):
            cur.removed.append(line[1:])
            last_plus = False
        elif line.startswith("\\"):
            if last_plus:
                cur.no_final_newline = True
    return changes


def _unquote(p: str) -> str:
    if len(p) > 1 and p[0] == '"' and p[-1] == '"':
        return p[1:-1].encode().decode("unicode_escape").encode("latin-1").decode()
    return p


DIFF = ["diff", "-U0", "--no-color", "--no-ext-diff", "-M", "--src-prefix=a/", "--dst-prefix=b/", "--diff-filter=ACMRD"]


def staged(root: Path) -> tuple[list[FileChange], Path]:
    changes = parse_diff(git(root, *DIFF, "--cached").decode(errors="replace"))
    tmp = _materialize(root, changes, lambda p: f":{p}")
    return changes, tmp


def commit(root: Path, sha: str) -> tuple[list[FileChange], Path]:
    parent = f"{sha}^" if git(root, "rev-parse", "-q", "--verify", f"{sha}^", check=False).strip() else EMPTY_TREE
    changes = parse_diff(git(root, *DIFF, parent, sha).decode(errors="replace"))
    tmp = _materialize(root, changes, lambda p: f"{sha}:{p}")
    return changes, tmp


def worktree(root: Path, base: str | None = None, paths: list[str] | None = None) -> list[FileChange]:
    """Working tree against `base` (default HEAD), plus untracked files."""
    against = base or ("HEAD" if has_head(root) else EMPTY_TREE)
    spec = ["--", *paths] if paths else []
    changes = parse_diff(git(root, *DIFF, against, *spec).decode(errors="replace"))
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z", *spec).decode(errors="replace")
    for path in filter(None, untracked.split("\0")):
        changes.append(_whole_file(root, path, new_file=True))
    for c in changes:
        c.disk = root / c.path
    return changes


def all_files(root: Path, paths: list[str] | None = None) -> list[FileChange]:
    out = git(root, "ls-files", "-z", *(["--", *paths] if paths else [])).decode(errors="replace")
    changes = []
    for path in filter(None, out.split("\0")):
        if (root / path).is_file():
            c = _whole_file(root, path, new_file=False)
            c.disk = root / path
            changes.append(c)
    return changes


def merge_base(root: Path, ref: str) -> str:
    mb = git(root, "merge-base", ref, "HEAD", check=False).decode().strip()
    return mb or ref


def _whole_file(root: Path, path: str, new_file: bool) -> FileChange:
    c = FileChange(path=path, new_file=new_file)
    try:
        data = (root / path).read_bytes()
    except OSError:
        return c
    if b"\0" in data[:8192]:
        c.binary = True
        return c
    text = data.decode(errors="replace")
    for i, line in enumerate(text.splitlines(), 1):
        c.added[i] = line
    c.no_final_newline = bool(text) and not text.endswith("\n")
    return c


def _materialize(root: Path, changes: list[FileChange], spec) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="agent-checks-")).resolve()
    wanted = [c for c in changes if not c.deleted]
    if not wanted:
        return tmp
    req = "".join(spec(c.path) + "\n" for c in wanted).encode()
    out = git(root, "cat-file", "--batch", input=req)
    pos = 0
    for c in wanted:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].decode(errors="replace").split()
        pos = nl + 1
        if len(header) < 3 or header[1] != "blob":
            continue
        size = int(header[2])
        target = tmp / c.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(out[pos : pos + size])
        pos += size + 1
        c.disk = target
    return tmp


def scope_globs(root: Path) -> list[str]:
    env = os.environ.get("AGENT_CHECKS_SCOPE", "")
    globs = [g.strip() for g in re.split(r"[,\n]", env) if g.strip()]
    if not globs:
        rel = git(root, "rev-parse", "--git-path", "agent-checks-scope", check=False).decode().strip()
        f = root / rel if rel else None
        if f and f.is_file():
            globs = [g.strip() for g in f.read_text().splitlines() if g.strip() and not g.startswith("#")]
    return globs
