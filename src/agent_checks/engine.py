"""Run the rule pack over a change and return findings on added lines only."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import rules as R
from .gitdiff import FileChange

DATA = Path(__file__).parent / "data"

EXT = {
    ".cs": "csharp",
    ".csx": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".java": "java",
    ".py": "python",
    ".pyi": "python",
    ".ts": "ts",
    ".tsx": "ts",
    ".mts": "ts",
    ".cts": "ts",
    ".js": "js",
    ".jsx": "js",
    ".mjs": "js",
    ".cjs": "js",
    ".go": "go",
    ".rs": "rust",
    ".swift": "swift",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".jsonc": "json",
    ".toml": "toml",
    ".csproj": "msbuild",
    ".fsproj": "msbuild",
    ".props": "msbuild",
    ".targets": "msbuild",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "rst",
}
SHEBANG = re.compile(r"^#!.*\b(?:(python)[\d.]*|(?:ba|z|da)?(sh))\b")
SOURCE_EXT = (".cs", ".kt", ".kts", ".java", ".py", ".ts", ".tsx", ".js", ".mjs", ".go", ".rs", ".swift")
AST_LANGS = {"csharp", "kotlin", "java", "python", "ts", "js"}

DEFAULT_EXCLUDE = [
    "**/node_modules/**",
    "**/obj/**",
    "**/dist/**",
    "**/vendor/**",
    "**/.venv/**",
    "**/generated/**",
    "**/*.g.cs",
    "**/*.Designer.cs",
    "**/Migrations/*.cs",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.map",
    "**/*.lock",
    "**/package-lock.json",
    "**/pnpm-lock.yaml",
    "**/*.snap",
    "**/*.enc",
    "**/*.svg",
    "**/__snapshots__/**",
    "**/*.verified.*",
    "**/*.received.*",
    "**/gradlew",
    "**/gradlew.bat",
    "**/gradle/wrapper/**",
]
# ruff rules used when the repo has no ruff config of its own: bugs, not style.
RUFF_DEFAULT = "E9,F,B006,B008,B012,B015,B017,B018,B023,B904,PLE"
DOC_LANGS = {"markdown", "rst", "other"}
COMMENT = re.compile(r"(^\s*\*|//|#|/\*|<!--|(^|\s)--\s)")
HELPER_NAME = {
    "kotlin": re.compile(r"\bfun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?(`[^`]+`|\w+)"),
    "python": re.compile(r"\bdef\s+(\w+)"),
    "ts": re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function\s*\*?\s*(\w+)|(\w+))"),
    "js": re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function\s*\*?\s*(\w+)|(\w+))"),
    "csharp": re.compile(r"(\w+)\s*(?:<[^>()]*>)?\s*\("),
    "java": re.compile(r"(\w+)\s*\("),
}
DEFAULT_TESTS = [
    "**/test/**",
    "**/tests/**",
    "**/__tests__/**",
    "**/src/test/**",
    "**/src/androidTest/**",
    "**/*Tests/**",
    "**/*.Tests/**",
    "**/*Test.kt",
    "**/*Tests.kt",
    "**/*Test.java",
    "**/*Tests.cs",
    "**/*Test.cs",
    "**/*_test.*",
    "**/test_*.py",
    "**/*.test.*",
    "**/*.spec.*",
    "**/conftest.py",
    "**/e2e/**",
]

ALLOW = re.compile(r"agent-checks:\s*allow\s+([\w,\s-]+?)(?:\s+--\s*(.*?))?\s*(?:\*/|-->)?\s*$")


@dataclass
class Finding:
    rule: str
    path: str
    line: int
    text: str = ""
    detail: str = ""  # linter message or typo correction

    def to_json(self) -> dict:
        r = R.BY_ID.get(self.rule.split(":")[0])
        return {
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "text": self.text.strip(),
            "detail": self.detail,
            "message": r.message if r else "",
        }


@dataclass
class Result:
    findings: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    allowed: list[Finding] = field(default_factory=list)
    files: int = 0
    lines: int = 0
    timings: dict[str, float] = field(default_factory=dict)


@dataclass
class Config:
    disable: set[str] = field(default_factory=set)
    exclude: list[re.Pattern[str]] = field(default_factory=list)
    tests: list[re.Pattern[str]] = field(default_factory=list)
    rule_exclude: dict[str, list[re.Pattern[str]]] = field(default_factory=dict)
    max_file_kb: int = 512
    linters: set[str] = field(default_factory=lambda: {"typos", "ruff", "shellcheck"})
    assert_helpers: list[str] = field(default_factory=list)
    severity: dict[str, str] = field(default_factory=dict)
    present: bool = False

    @classmethod
    def load(cls, root: Path) -> Config:
        f = root / ".agent-checks.toml"
        raw: dict = {}
        if f.is_file():
            raw = tomllib.loads(f.read_text())
        cfg = cls(present=f.is_file())
        cfg.disable = set(raw.get("disable", []))
        cfg.exclude = [glob(g) for g in DEFAULT_EXCLUDE + list(raw.get("exclude", []))]
        cfg.tests = [glob(g) for g in DEFAULT_TESTS + list(raw.get("tests", []))]
        cfg.max_file_kb = int(raw.get("max_file_kb", 512))
        cfg.assert_helpers = list(raw.get("assert_helpers", []))
        for level in ("error", "warn"):
            for rid in raw.get(level, []):
                cfg.severity[rid] = level
        if "linters" in raw:
            cfg.linters = set(raw["linters"])
        for rid, opts in raw.get("rules", {}).items():
            cfg.rule_exclude[rid] = [glob(g) for g in opts.get("exclude", [])]
        unknown = (cfg.disable | set(cfg.rule_exclude) | set(cfg.severity)) - set(R.BY_ID)
        if unknown:
            raise ValueError(f".agent-checks.toml names unknown rules: {', '.join(sorted(unknown))}")
        return cfg

    def level(self, rule: str) -> str:
        return self.severity.get(rule, R.BY_ID[rule].severity)

    def excluded(self, path: str, rule: str | None = None) -> bool:
        pats = self.rule_exclude.get(rule, []) if rule else self.exclude
        return any(p.match(path) for p in pats)

    def is_test(self, path: str) -> bool:
        return any(p.match(path) for p in self.tests)


def glob(g: str) -> re.Pattern[str]:
    """gitignore-flavoured glob: `**` spans directories, a pattern without `/` matches the basename."""
    if "/" not in g:
        g = "**/" + g
    out, i = "", 0
    while i < len(g):
        if g.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif g.startswith("**", i):
            out, i = out + ".*", i + 2
        elif g[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif g[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(g[i]), i + 1
    return re.compile(out + r"\Z")


def lang_of(c: FileChange) -> str:
    p = Path(c.path)
    if p.suffix.lower() in EXT:
        return EXT[p.suffix.lower()]
    if p.name in ("Dockerfile", "Makefile"):
        return p.name.lower()
    first = c.added.get(1)
    if first is None and c.disk and c.disk.is_file():
        try:
            with c.disk.open(errors="replace") as fh:
                first = fh.readline()
        except OSError:
            first = None
    m = SHEBANG.match(first or "")
    if m:
        return "python" if m.group(1) else "shell"
    return "other"


def tool(name: str) -> str | None:
    """Prefer the binary installed next to this interpreter (the uv tool venv), then PATH."""
    local = Path(sys.executable).parent / name
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which(name)


class Checker:
    def __init__(self, root: Path, cfg: Config, scope: list[str] | None = None, allow_env: str | None = None):
        self.root = root
        self.cfg = cfg
        self.scope = [glob(g) for g in scope or []]
        self.allow_env = _parse_allow_env(allow_env if allow_env is not None else os.environ.get("AGENT_CHECKS_ALLOW", ""))
        self.compiled = {
            r.id: {lang: [re.compile(p) for p in ps] for lang, ps in r.patterns.items()} for r in R.RULES if r.kind == "line" and r.id not in cfg.disable
        }
        self._lines: dict[str, list[str]] = {}

    # --- helpers ---
    def file_lines(self, c: FileChange) -> list[str]:
        if c.path not in self._lines:
            try:
                self._lines[c.path] = c.disk.read_text(errors="replace").splitlines() if c.disk else []
            except OSError:
                self._lines[c.path] = []
        return self._lines[c.path]

    def line_text(self, c: FileChange, n: int) -> str:
        if n in c.added:
            return c.added[n]
        lines = self.file_lines(c)
        return lines[n - 1] if 0 < n <= len(lines) else ""

    def allowed(self, c: FileChange, n: int, rule: str) -> bool:
        if not R.BY_ID[rule.split(":")[0]].allowable:
            return False
        for k in (n, n - 1):
            m = ALLOW.search(self.line_text(c, k)) if k > 0 else None
            if m and m.group(2) and len(m.group(2).strip()) >= 5:
                ids = {x.strip() for x in m.group(1).replace(",", " ").split()}
                if rule in ids or rule.split(":")[0] in ids:
                    return True
        return False

    # --- passes ---
    def run(self, changes: list[FileChange]) -> Result:
        res = Result()
        live = [c for c in changes if not self.cfg.excluded(c.path)]
        res.files = len(live)
        res.lines = sum(len(c.added) for c in live)
        langs = {c.path: lang_of(c) for c in live}
        raw: list[Finding] = []

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = []
            ast_files = [c for c in live if langs[c.path] in AST_LANGS and c.added and not c.deleted and c.disk]
            if ast_files and not ({"empty-catch", "test-without-assert"} <= self.cfg.disable):
                futures.append(pool.submit(self._ast, ast_files, langs))
            text_files = [c for c in live if c.added and not c.deleted and not c.binary and c.disk]
            if text_files and "typo" not in self.cfg.disable and "typos" in self.cfg.linters:
                futures.append(pool.submit(self._typos, text_files, langs))
            py = [c for c in text_files if langs[c.path] == "python"]
            if py and "ruff" in self.cfg.linters and "ruff" not in self.cfg.disable:
                futures.append(pool.submit(self._ruff, py))
            sh = [c for c in text_files if langs[c.path] == "shell" and not re.match(r"#!.*\bzsh\b", self.line_text(c, 1))]
            if sh and "shellcheck" in self.cfg.linters and "shellcheck" not in self.cfg.disable:
                futures.append(pool.submit(self._shellcheck, sh))
            for c in live:
                raw.extend(self._line_rules(c, langs[c.path]))
                raw.extend(self._file_rules(c, langs[c.path]))
            raw.extend(self._deletions(live))
            for f in futures:
                raw.extend(f.result())

        by_path = {c.path: c for c in live}
        seen = set()
        for f in sorted(raw, key=lambda f: (f.path, f.line, f.rule)):
            key = (f.rule, f.path, f.line, f.detail)
            if key in seen:
                continue
            seen.add(key)
            base = f.rule.split(":")[0]
            if base in self.cfg.disable or self.cfg.excluded(f.path, base):
                continue
            c = by_path.get(f.path)
            marked = bool(c and f.line and self.allowed(c, f.line, f.rule))
            if marked or (base in self.allow_env and R.BY_ID[base].allowable):
                res.allowed.append(f)
            elif self.cfg.level(base) == "warn":
                res.warnings.append(f)
            else:
                res.findings.append(f)
        return res

    def _line_rules(self, c: FileChange, lang: str) -> list[Finding]:
        out: list[Finding] = []
        if not c.added or c.binary:
            return out
        is_test = self.cfg.is_test(c.path)
        for rid, by_lang in self.compiled.items():
            rule = R.BY_ID[rid]
            if rule.tests_only and not is_test:
                continue
            pats = by_lang.get(lang, []) + by_lang.get("*", [])
            if not pats:
                continue
            if rid == "trailing-whitespace" and lang in DOC_LANGS:
                continue
            unless = re.compile(rule.unless_above) if rule.unless_above else None
            unless_line = re.compile(rule.unless_line) if rule.unless_line else None
            for n, text in c.added.items():
                if any(p.search(text) for p in pats):
                    if unless_line and unless_line.search(text):
                        continue
                    if unless and any(unless.search(self.line_text(c, k)) for k in range(max(1, n - 3), n)):
                        continue
                    out.append(Finding(rid, c.path, n, text))
        for n, text in c.added.items():
            m = ALLOW.search(text)
            if m and not (m.group(2) and len(m.group(2).strip()) >= 5):
                out.append(Finding("allow-without-reason", c.path, n, text))
        return out

    def _file_rules(self, c: FileChange, lang: str) -> list[Finding]:
        out: list[Finding] = []
        first = min(c.added) if c.added else 0
        # JSON is skipped: serializers and tools write it without a final newline.
        if c.no_final_newline and not c.binary and lang not in ("other", "json") and c.added:
            last = max(c.added)
            out.append(Finding("final-newline", c.path, last, c.added[last]))
        if c.new_file and not c.deleted and c.disk and c.disk.is_file():
            kb = c.disk.stat().st_size / 1024
            if kb > self.cfg.max_file_kb:
                out.append(Finding("large-file", c.path, 0, detail=f"{kb:.0f} KB > {self.cfg.max_file_kb} KB"))
        name = Path(c.path).name
        if not c.deleted and re.fullmatch(r"\.env(\.[\w.-]+)?", name) and not re.search(r"\.(example|sample|template|dist|enc|defaults?|schema)$", name):
            out.append(Finding("plaintext-env", c.path, 0))
        if self.scope and not any(p.match(c.path) for p in self.scope):
            out.append(Finding("out-of-scope", c.path, first))
        return out

    def _deletions(self, live: list[FileChange]) -> list[Finding]:
        """Net loss across all test files, so a test moved to another file is not a deletion."""
        out = []
        # Deleting a whole test file together with production code is removing a feature, not a test.
        removes_code = any(c.deleted and not self.cfg.is_test(c.path) and c.path.endswith(SOURCE_EXT) for c in live)
        tests = [c for c in live if self.cfg.is_test(c.path) and not (c.deleted and removes_code)]
        for rid, pat in (("deleted-assertions", R.ASSERT_TOKEN), ("deleted-tests", R.TEST_DECL)):
            per = [(c, sum(len(pat.findall(t)) for t in c.removed), sum(len(pat.findall(t)) for t in c.added.values())) for c in tests]
            gone, new = sum(p[1] for p in per), sum(p[2] for p in per)
            if gone > new:
                for c, g, n in per:
                    if g > n:
                        out.append(Finding(rid, c.path, min(c.added) if c.added else 0, detail=f"{g} removed, {n} added"))
        return out

    def _ast(self, files: list[FileChange], langs: dict[str, str]) -> list[Finding]:
        exe = tool("ast-grep") or tool("sg")
        if not exe:
            return []
        disk_to_change = {str(c.disk): c for c in files}
        p = subprocess.run([exe, "scan", "--config", str(DATA / "sgconfig.yml"), "--json=stream", *disk_to_change], capture_output=True, text=True, check=False)
        out: list[Finding] = []
        helpers: dict[str, set[str]] = {}
        no_assert: list[tuple[FileChange, int, str]] = []
        for line in p.stdout.splitlines():
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            c = disk_to_change.get(m.get("file")) or disk_to_change.get(str(Path(m.get("file", "")).resolve()))
            if not c:
                continue
            rid = m["ruleId"].split(".")[0]
            if rid == "assert-helper":
                rx = HELPER_NAME.get(langs[c.path])
                hm = rx.search(m["text"].lstrip()) if rx else None
                name = next((g for g in hm.groups() if g), None) if hm else None
                if name:
                    helpers.setdefault(c.path, set()).add(name.strip("`"))
                continue
            if rid == "test-without-assert" and not self.cfg.is_test(c.path):
                continue
            start, end = m["range"]["start"]["line"] + 1, m["range"]["end"]["line"] + 1
            if not any(n in c.added for n in range(start, end + 1)):
                continue
            if rid == "test-without-assert":
                no_assert.append((c, start, m["text"]))
                continue
            out.append(Finding(rid, c.path, start, self.line_text(c, start)))
        for c, start, text in no_assert:
            # A call to a helper that asserts counts. The test's own name cannot be in `names`:
            # it would only be a helper if it asserted, and then it would not be here.
            names = helpers.get(c.path, set()) | set(self.cfg.assert_helpers)
            if any(re.search(rf"(?<![\w`]){re.escape(n)}\s*[({{]", text) for n in names):
                continue
            out.append(Finding("test-without-assert", c.path, start, self.line_text(c, start)))
        return out

    def _typos(self, files: list[FileChange], langs: dict[str, str]) -> list[Finding]:
        exe = tool("typos")
        if not exe:
            return []
        disk_to_change = {str(c.disk): c for c in files}
        cfg = []
        for name in ("_typos.toml", "typos.toml", ".typos.toml"):
            if (self.root / name).is_file():
                cfg = ["--config", str(self.root / name)]
                break
        p = subprocess.run([exe, "--format", "json", "--force-exclude", *cfg, *disk_to_change], capture_output=True, text=True, cwd=self.root, check=False)
        out = []
        for line in p.stdout.splitlines():
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("type") != "typo":
                continue
            c = disk_to_change.get(m.get("path")) or disk_to_change.get(str((self.root / m.get("path", "")).resolve()))
            if c and m.get("line_num") in c.added:
                text = c.added[m["line_num"]]
                if langs[c.path] not in DOC_LANGS:
                    # In code, identifiers and string data are full of false hits; check comments only.
                    cm = COMMENT.search(text)
                    if not cm or m.get("byte_offset", 0) < len(text[: cm.start()].encode()):
                        continue
                fix = " or ".join(m.get("corrections") or []) or "?"
                out.append(Finding("typo", c.path, m["line_num"], c.added[m["line_num"]], f"'{m['typo']}' -> '{fix}'"))
        return out

    def _ruff(self, files: list[FileChange]) -> list[Finding]:
        exe = tool("ruff")
        if not exe:
            return []
        own = (
            (self.root / "ruff.toml").is_file()
            or (self.root / ".ruff.toml").is_file()
            or ((self.root / "pyproject.toml").is_file() and "[tool.ruff" in (self.root / "pyproject.toml").read_text(errors="replace"))
        )
        select = [] if own else ["--isolated", "--select", RUFF_DEFAULT]
        out = []
        for c in files:
            # stdin keeps the repo's ruff config (found from --stdin-filename) while linting the right content.
            p = subprocess.run(
                [exe, "check", *select, "--output-format", "json", "--no-cache", "--stdin-filename", str(self.root / c.path), "-"],
                input=c.disk.read_text(errors="replace"),
                capture_output=True,
                text=True,
                cwd=self.root,
                check=False,
            )
            try:
                items = json.loads(p.stdout or "[]")
            except json.JSONDecodeError:
                continue
            for it in items:
                n = it.get("location", {}).get("row")
                if n in c.added:
                    out.append(Finding(f"ruff:{it.get('code')}", c.path, n, c.added[n], it.get("message", "")))
        return out

    def _shellcheck(self, files: list[FileChange]) -> list[Finding]:
        exe = tool("shellcheck")
        if not exe:
            return []
        disk_to_change = {str(c.disk): c for c in files}
        p = subprocess.run([exe, "-f", "json1", "-S", "warning", "-x", *disk_to_change], capture_output=True, text=True, cwd=self.root, check=False)
        try:
            items = json.loads(p.stdout or "{}").get("comments", [])
        except json.JSONDecodeError:
            return []
        out = []
        for it in items:
            c = disk_to_change.get(it.get("file"))
            n = it.get("line")
            if c and n in c.added:
                out.append(Finding(f"shellcheck:SC{it.get('code')}", c.path, n, c.added[n], it.get("message", "")))
        return out


def _parse_allow_env(v: str) -> set[str]:
    """AGENT_CHECKS_ALLOW='deleted-tests: moved to FooTests.cs; deleted-assertions: ...' (each needs a reason)."""
    ids = set()
    for part in re.split(r"[;\n]", v):
        if ":" in part:
            rid, why = part.split(":", 1)
            if len(why.strip()) >= 5:
                ids.add(rid.strip())
    return ids
