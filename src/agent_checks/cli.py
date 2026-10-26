"""agent-checks: fast diff checks whose failure messages tell a coding agent what to fix."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, gitdiff, install
from . import rules as R
from .engine import Checker, Config, Finding, Result

MAX_PER_RULE = 20
FOOTER = "Fix each one at its cause, then run the same command again. Do not bypass the check (--no-verify, LEFTHOOK=0) or weaken the rule to get past it."
HOOK_FOOTER = "Fix each one at its cause in your next edit. Do not weaken the rule or move the code elsewhere to get past it."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent-checks", description=__doc__)
    ap.add_argument("--version", action="version", version=f"agent-checks {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="check the lines a change adds")
    c.add_argument("-C", dest="dir", default=".", help="run in this directory")
    mode = c.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="the index (pre-commit)")
    mode.add_argument("--base", metavar="REF", help="working tree against merge-base(REF, HEAD); 'auto' picks the PR base in CI")
    mode.add_argument("--commit", metavar="SHA", help="what one commit adds")
    mode.add_argument("--all", action="store_true", help="every line of every tracked file (audit, not a gate)")
    c.add_argument("--format", choices=["text", "json", "github"], default="text")
    c.add_argument("--timing", action="store_true", help="print timings to stderr")
    c.add_argument("paths", nargs="*", help="limit to these paths")

    h = sub.add_parser("hook", help="run as an agent hook (reads the hook payload on stdin)")
    h.add_argument("agent", choices=["claude"])

    i = sub.add_parser("install", help="set up lefthook and agent-checks in a repo")
    i.add_argument("dir", nargs="?", default=".")
    i.add_argument("--force", action="store_true", help="overwrite an existing lefthook.yml")
    i.add_argument("--dry-run", action="store_true")
    i.add_argument("--files-only", action="store_true", help="write the files but leave git hooks and core.hooksPath alone (activate after the PR merges)")

    r = sub.add_parser("rules", help="list the rules")
    r.add_argument("--markdown", action="store_true")

    b = sub.add_parser("bench", help="time the check over the last N commits of a repo")
    b.add_argument("-C", dest="dir", default=".")
    b.add_argument("-n", type=int, default=20)

    sub.add_parser("doctor", help="show which tools are installed")

    a = ap.parse_args(argv)
    try:
        return {
            "check": cmd_check,
            "hook": cmd_hook,
            "install": cmd_install,
            "rules": cmd_rules,
            "bench": cmd_bench,
            "doctor": cmd_doctor,
        }[a.cmd](a)
    except (gitdiff.GitError, ValueError) as e:
        print(f"agent-checks: {e}", file=sys.stderr)
        return 3


# --- check ---


def collect(root: Path, a) -> tuple[list[gitdiff.FileChange], Path | None]:
    paths = a.paths or None
    if a.staged:
        return gitdiff.staged(root)
    if a.commit:
        return gitdiff.commit(root, a.commit)
    if a.all:
        return gitdiff.all_files(root, paths), None
    if a.base:
        ref = resolve_base(root, a.base)
        return gitdiff.worktree(root, gitdiff.merge_base(root, ref), paths), None
    if gitdiff.git(root, "diff", "--cached", "--name-only", check=False).strip():
        return gitdiff.staged(root)
    return gitdiff.worktree(root, None, paths), None


def resolve_base(root: Path, base: str) -> str:
    if base != "auto":
        return base
    # On a GitHub pull_request checkout HEAD is the merge commit; its first parent is the base.
    parents = gitdiff.git(root, "rev-list", "--parents", "-n", "1", "HEAD", check=False).decode().split()
    if os.environ.get("GITHUB_EVENT_NAME", "").startswith("pull_request") and len(parents) == 3:
        return "HEAD^1"
    if os.environ.get("GITHUB_BASE_REF"):
        return f"origin/{os.environ['GITHUB_BASE_REF']}"
    head = gitdiff.git(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD", check=False).decode().strip()
    return head or "HEAD~1"


def run_check(root: Path, changes: list[gitdiff.FileChange]) -> Result:
    cfg = Config.load(root)
    return Checker(root, cfg, scope=gitdiff.scope_globs(root)).run(changes)


def cmd_check(a) -> int:
    t0 = time.perf_counter()
    root = gitdiff.toplevel(Path(a.dir))
    if root is None:
        print("agent-checks: not inside a git repository", file=sys.stderr)
        return 3
    changes, tmp = collect(root, a)
    t1 = time.perf_counter()
    try:
        res = run_check(root, changes)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    t2 = time.perf_counter()
    emit(res, a.format, sys.stdout)
    if a.timing:
        print(f"agent-checks: {res.files} files, {res.lines} added lines; diff {1000 * (t1 - t0):.0f} ms, rules {1000 * (t2 - t1):.0f} ms", file=sys.stderr)
    return 1 if res.findings else 0


def emit(res: Result, fmt: str, out) -> None:
    if fmt == "json":
        json.dump(
            {
                "version": __version__,
                "ok": not res.findings,
                "files": res.files,
                "lines": res.lines,
                "findings": [f.to_json() for f in res.findings],
                "warnings": [f.to_json() for f in res.warnings],
                "allowed": [f.to_json() for f in res.allowed],
            },
            out,
            indent=2,
        )
        out.write("\n")
        return
    if fmt == "github":
        for f in res.findings:
            r = R.BY_ID[f.rule.split(":")[0]]
            msg = (f"{f.detail}. " if f.detail else "") + r.message
            out.write(f"::error file={f.path},line={max(f.line, 1)},title=agent-checks {f.rule}::{msg}\n")
        for f in res.warnings:
            out.write(f"::warning file={f.path},line={max(f.line, 1)},title=agent-checks {f.rule}::{f.detail or R.BY_ID[f.rule.split(':')[0]].message}\n")
        if not res.findings:
            out.write(f"agent-checks: ok ({res.files} files, {res.lines} added lines)\n")
        return
    out.write(render_text(res))


def render_warnings(res: Result) -> str:
    if not res.warnings:
        return ""
    out = [f"agent-checks: {len(res.warnings)} warning{'s' if len(res.warnings) != 1 else ''} (not blocking):"]
    for f in res.warnings[:MAX_PER_RULE]:
        loc = f"{f.path}:{f.line}" if f.line else f.path
        out.append(f"  {loc}  {f.rule}" + (f"  {f.detail}" if f.detail else ""))
    if len(res.warnings) > MAX_PER_RULE:
        out.append(f"  ... and {len(res.warnings) - MAX_PER_RULE} more")
    return "\n".join(out) + "\n"


def render_text(res: Result, header: str | None = None, footer: str = FOOTER) -> str:
    if not res.findings:
        extra = f", {len(res.allowed)} allowed by marker" if res.allowed else ""
        return render_warnings(res) + f"agent-checks: ok ({res.files} files, {res.lines} added lines{extra})\n"
    groups: dict[str, list[Finding]] = {}
    for f in res.findings:
        groups.setdefault(f.rule.split(":")[0], []).append(f)
    lines = [header or f"agent-checks: {len(res.findings)} problem{'s' if len(res.findings) != 1 else ''} in the lines this change adds.", ""]
    for rid, fs in groups.items():
        rule = R.BY_ID[rid]
        lines.append(f"{rid}: {rule.message}")
        for f in fs[:MAX_PER_RULE]:
            loc = f"{f.path}:{f.line}" if f.line else f.path
            sub = f.rule.split(":", 1)[1] + " " if ":" in f.rule else ""
            detail = f"  {sub}{f.detail}" if (f.detail or sub) else ""
            text = f"  | {f.text.strip()[:140]}" if f.text.strip() else ""
            lines.append(f"  {loc}{detail}{text}")
        if len(fs) > MAX_PER_RULE:
            lines.append(f"  ... and {len(fs) - MAX_PER_RULE} more")
        if rule.allowable and rule.kind in ("line", "ast", "lint"):
            lines.append("  " + R.ALLOW_HINT.format(id=rid))
        lines.append("")
    lines.append(footer)
    return render_warnings(res) + "\n".join(lines) + "\n"


# --- agent hooks ---


def cmd_hook(a) -> int:
    """Claude Code PostToolUse: check the file the tool just wrote. Exit 2 puts stderr in front of the agent."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    ti = payload.get("tool_input") or {}
    target = ti.get("file_path") or ti.get("notebook_path")
    if not target:
        return 0
    path = Path(target)
    if not path.is_absolute():
        path = Path(payload.get("cwd") or ".") / path
    if not path.exists():
        return 0
    root = gitdiff.toplevel(path.parent)
    if root is None or not (root / ".agent-checks.toml").is_file():
        return 0  # opt-in per repo
    try:
        rel = str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return 0
    if _ignored(root, rel):
        return 0
    res = run_check(root, gitdiff.worktree(root, None, [rel]))
    if not res.findings:
        return 0
    sys.stderr.write(
        render_text(res, header=f"agent-checks found problems in lines you just wrote in {rel}. Fix them now, before moving on.", footer=HOOK_FOOTER)
    )
    return 2


def _ignored(root: Path, rel: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", rel], cwd=root, check=False).returncode == 0


# --- other commands ---


def cmd_install(a) -> int:
    return install.install(Path(a.dir), force=a.force, dry_run=a.dry_run, files_only=a.files_only)


def cmd_rules(a) -> int:
    if a.markdown:
        print("| Rule | Catches | Scope | Allow marker |\n|---|---|---|---|")
        for r in R.RULES:
            scope = "test files" if r.tests_only else ("whole change" if r.kind == "file" else "added lines")
            print(f"| `{r.id}` | {r.summary} | {scope} | {'yes' if r.allowable else 'no'} |")
        return 0
    for r in R.RULES:
        print(f"{r.id:22} {r.summary}")
    return 0


def cmd_bench(a) -> int:
    root = gitdiff.toplevel(Path(a.dir))
    if root is None:
        return 3
    shas = gitdiff.git(root, "rev-list", "--no-merges", f"-{a.n}", "HEAD").decode().split()
    times, lines = [], []
    for sha in shas:
        t0 = time.perf_counter()
        changes, tmp = gitdiff.commit(root, sha)
        res = run_check(root, changes)
        shutil.rmtree(tmp, ignore_errors=True)
        times.append(1000 * (time.perf_counter() - t0))
        lines.append(res.lines)
    if not times:
        return 0
    s = sorted(times)
    p50, p95 = s[len(s) // 2], s[min(len(s) - 1, int(len(s) * 0.95))]
    print(
        f"{root.name}: {len(s)} commits, median {sorted(lines)[len(lines) // 2]} added lines; check p50 {p50:.0f} ms, p95 {p95:.0f} ms, max {s[-1]:.0f} ms (in-process, excludes interpreter start)"
    )
    return 0


def cmd_doctor(a) -> int:
    from .engine import tool

    ok = True
    for name, need in (("git", True), ("ast-grep", True), ("typos", True), ("ruff", False), ("shellcheck", False), ("gitleaks", False), ("lefthook", False)):
        path = tool(name) or (tool("sg") if name == "ast-grep" else None)
        mark = "ok " if path else ("MISSING" if need else "absent")
        ok &= bool(path) or not need
        print(f"{mark:8} {name:11} {path or ''}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
