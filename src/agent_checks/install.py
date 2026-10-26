"""`agent-checks install`: write lefthook.yml and .agent-checks.toml for a repo, then install the git hooks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import __version__, gitdiff

CONFIG = """\
# agent-checks: rules that fail with a message written to the coding agent.
# Rules, options and the allow marker: https://github.com/Egoushka/agent-checks
# This file also turns on the Claude Code hook for this repo.

# Rule ids to switch off for this repo (agent-checks rules).
disable = []

# Paths never checked, on top of the built-in list (lockfiles, generated code, vendored deps).
exclude = []

# Extra globs for test files (the test-only rules use these).
tests = []

# Linters whose output is filtered to added lines: typos, ruff, shellcheck.
linters = ["typos", "ruff", "shellcheck"]
"""

HEAD = """\
# Git hooks, run by lefthook (https://lefthook.dev). After cloning: `lefthook install`.
# agent-checks messages are written for coding agents: https://github.com/Egoushka/agent-checks
"""

PRE_COMMIT = """\
pre-commit:
  parallel: true
  jobs:
    - name: agent-checks
      run: agent-checks check --staged
    - name: gitleaks
      run: gitleaks git --staged --redact --no-banner
"""

DOTNET_PUSH = """\
pre-push:
  jobs:
    # Whitespace only: `dotnet format style` loads the solution and takes minutes; CI runs the full check.
    - name: dotnet-format
      glob: "*.cs"
      run: dotnet format whitespace --folder --verify-no-changes --include {push_files}
"""


WORKFLOW = """\
# Checks the lines a pull request adds: https://github.com/Egoushka/agent-checks
name: agent-checks
on: pull_request
permissions:
  contents: read
jobs:
  agent-checks:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 2
      - uses: Egoushka/agent-checks@v{version}
"""


def detect(root: Path) -> set[str]:
    files = gitdiff.git(root, "ls-files").decode(errors="replace").splitlines()
    exts = {Path(f).suffix.lower() for f in files}
    stacks = set()
    if exts & {".cs", ".csproj", ".sln", ".slnx"}:
        stacks.add("dotnet")
    if exts & {".kt", ".kts"}:
        stacks.add("kotlin")
    if ".py" in exts:
        stacks.add("python")
    if exts & {".ts", ".tsx", ".js", ".mjs"}:
        stacks.add("node")
    if ".sh" in exts:
        stacks.add("shell")
    return stacks


def legacy_hooks(root: Path) -> tuple[str | None, list[str]]:
    hp = gitdiff.git(root, "config", "--local", "--get", "core.hooksPath", check=False).decode().strip()
    if not hp:
        return None, []
    d = root / hp
    if Path(hp).is_absolute() and Path(hp).resolve().is_relative_to(root.resolve()):
        hp = str(Path(hp).resolve().relative_to(root.resolve()))
    names = [p.name for p in sorted(d.iterdir()) if p.is_file() and p.name in ("pre-commit", "commit-msg", "pre-push")] if d.is_dir() else []
    return hp, names


def render(root: Path) -> str:
    stacks = detect(root)
    hp, legacy = legacy_hooks(root)
    out = [HEAD + "\n" + PRE_COMMIT]
    if "pre-commit" in legacy:
        out[-1] += f"    - name: repo-pre-commit\n      run: {hp}/pre-commit\n"
    if "commit-msg" in legacy:
        out += ["", f"commit-msg:\n  jobs:\n    - name: repo-commit-msg\n      run: {hp}/commit-msg {{1}}\n"]
    if "dotnet" in stacks:
        out += ["", DOTNET_PUSH]
    if "pre-push" in legacy:
        if "dotnet" in stacks:
            out[-1] += f"    - name: repo-pre-push\n      run: {hp}/pre-push {{0}}\n"
        else:
            out += ["", f"pre-push:\n  jobs:\n    - name: repo-pre-push\n      run: {hp}/pre-push {{0}}\n"]
    return "\n".join(out)


def install(target: Path, force: bool = False, dry_run: bool = False, files_only: bool = False) -> int:
    root = gitdiff.toplevel(target)
    if root is None:
        print(f"agent-checks: {target} is not a git repository")
        return 3
    lefthook_yml = root / "lefthook.yml"
    config = root / ".agent-checks.toml"
    text = render(root)
    hp, legacy = legacy_hooks(root)
    remote = gitdiff.git(root, "remote", "get-url", "origin", check=False).decode().strip()
    workflow = root / ".github" / "workflows" / "agent-checks.yml"
    want_workflow = "github.com" in remote and not workflow.exists()
    plan = []
    if not config.exists():
        plan.append(f"write {config.name}")
    if not lefthook_yml.exists() or force:
        plan.append(f"write {lefthook_yml.name} ({', '.join(sorted(detect(root))) or 'no stack'} detected)")
    elif "agent-checks" not in lefthook_yml.read_text():
        print(f"agent-checks: {lefthook_yml} exists without an agent-checks job. Add this job to its pre-commit section, or rerun with --force:\n")
        print("    - name: agent-checks\n      run: agent-checks check --staged\n")
    if want_workflow:
        plan.append(f"write {workflow.relative_to(root)} (Egoushka/agent-checks@v{__version__} on pull requests)")
    if not files_only:
        if hp:
            plan.append(f"unset core.hooksPath={hp} (lefthook now runs {', '.join(legacy) or 'nothing'} from it)")
        plan.append("lefthook install")
    print(f"agent-checks install {root}:")
    for p in plan:
        print(f"  - {p}")
    if dry_run:
        if not lefthook_yml.exists() or force:
            print("\n--- lefthook.yml ---\n" + text)
        return 0
    if not config.exists():
        config.write_text(CONFIG)
    if not lefthook_yml.exists() or force:
        lefthook_yml.write_text(text)
    if want_workflow:
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(WORKFLOW.format(version=__version__))
    if files_only:
        print("files written; run `agent-checks install` again after the PR merges to activate the hooks.")
        return 0
    if hp:
        gitdiff.git(root, "config", "--local", "--unset", "core.hooksPath", check=False)
    lh = shutil.which("lefthook")
    if not lh:
        print("agent-checks: lefthook is not installed (brew install lefthook); hooks are written but not active.")
        return 1
    p = subprocess.run([lh, "install"], check=False, cwd=root, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout + p.stderr)
        return p.returncode
    print("done: commit hooks active. Agents get the same checks via the Claude Code hook and `agent-checks check --base auto` in CI.")
    return 0
