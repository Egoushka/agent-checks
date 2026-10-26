"""The rule pack: every rule id, what it matches and the message the agent reads.

Line rules are regexes run on added lines only. AST rules live in data/rules/*.yml
(ast-grep); their ids must appear in RULES so they get a message. A message is an
instruction to the agent that wrote the line: what is wrong, what to do instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

C_LIKE = ("csharp", "kotlin", "java", "ts", "js", "go", "rust", "swift")
CODE = C_LIKE + ("python", "shell")

ALLOW_HINT = "If this is deliberate, put `agent-checks: allow {id} -- <why>` in a comment on this line or the one above."


@dataclass(frozen=True)
class Rule:
    id: str
    summary: str
    message: str
    # lang -> regexes; "*" applies to every file. Empty for AST and file-level rules.
    patterns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tests_only: bool = False
    # A match is dropped when one of the 3 lines above it matches this.
    unless_above: str | None = None
    # A match is dropped when its own line matches this (a suppression that carries its reason).
    unless_line: str | None = None
    kind: str = "line"  # line | ast | file | lint
    allowable: bool = True
    severity: str = "error"  # error fails the check; warn is printed only


RULES: list[Rule] = [
    # --- tests that stop testing ---
    Rule(
        "skip-test",
        "A test is skipped, ignored or disabled.",
        "You disabled a test. A skipped test hides the bug it was written to catch. "
        "Fix the code or the test so it passes; if the test is obsolete, delete it and say why in the commit.",
        {
            "csharp": (
                r"\[\s*(Fact|Theory|Test|TestMethod|TestCase|SkippableFact)\s*\([^\]]*\bSkip\s*=",
                r"\[\s*(Ignore|Explicit)\b",
                r"\bAssert\.Inconclusive\s*\(",
            ),
            "kotlin": (r"@(Disabled|Ignore)\b", r"\bassumeTrue\s*\(\s*false\s*\)"),
            "java": (r"@(Disabled|Ignore)\b", r"\bassumeTrue\s*\(\s*false\s*\)"),
            "python": (r"@pytest\.mark\.(skip|skipif|xfail)\b", r"\bpytest\.skip\s*\(", r"@unittest\.(skip|expectedFailure)"),
            "ts": (r"\b(it|test|describe|context)\.(skip|todo)\s*\(", r"\bx(it|test|describe)\s*\("),
            "js": (r"\b(it|test|describe|context)\.(skip|todo)\s*\(", r"\bx(it|test|describe)\s*\("),
            "go": (r"\bt\.Skip(f|Now)?\s*\(",),
        },
    ),
    Rule(
        "focused-test",
        "A test is focused with .only, which silently skips every other test.",
        "You focused one test with .only (or fit/fdescribe). Every other test in the run is now skipped. Remove the focus.",
        {
            "ts": (r"\b(it|test|describe|context)\.only\s*\(", r"\bf(it|describe)\s*\("),
            "js": (r"\b(it|test|describe|context)\.only\s*\(", r"\bf(it|describe)\s*\("),
        },
        allowable=False,
    ),
    Rule(
        "tautology",
        "An assertion that can never fail.",
        "This assertion can never fail, so the test checks nothing. "
        "Assert the behaviour the test name promises: call the code under test and compare its result with a concrete expected value.",
        {
            "csharp": (
                r"\bAssert\.(True|IsTrue)\s*\(\s*true\s*\)",
                r"\bAssert\.(False|IsFalse)\s*\(\s*false\s*\)",
                r"\bAssert\.Pass\s*\(",
                r"\btrue\s*\.\s*Should\s*\(\s*\)\s*\.\s*BeTrue\s*\(",
                r"\bAssert\.(Equal|AreEqual|Same)\s*\(\s*([\w.]+)\s*,\s*\2\s*\)",
            ),
            "kotlin": (r"\bassert(True)?\s*\(\s*true\s*\)", r"\bassertFalse\s*\(\s*false\s*\)", r"\bassertEquals\s*\(\s*([\w.]+)\s*,\s*\1\s*\)"),
            "java": (r"\bassert(True)?\s*\(\s*true\s*\)", r"\bassertFalse\s*\(\s*false\s*\)", r"\bassertEquals\s*\(\s*([\w.]+)\s*,\s*\1\s*\)"),
            "python": (
                r"^\s*assert\s+(True|1|not\s+False)\s*(#.*)?$",
                r"\bassertTrue\s*\(\s*True\s*\)",
                r"^\s*assert\s+([\w.]+)\s*==\s*\1\s*(#.*)?$",
            ),
            "ts": (
                r"\bexpect\s*\(\s*(true|1)\s*\)\s*\.\s*(toBe|toEqual|toStrictEqual)\s*\(\s*(true|1)\s*\)",
                r"\bexpect\s*\(\s*true\s*\)\s*\.\s*toBeTruthy\s*\(",
                r"\bassert(\.ok)?\s*\(\s*true\s*\)",
                r"\bexpect\s*\(\s*([\w.]+)\s*\)\s*\.\s*(toBe|toEqual)\s*\(\s*\1\s*\)",
            ),
            "js": (
                r"\bexpect\s*\(\s*(true|1)\s*\)\s*\.\s*(toBe|toEqual|toStrictEqual)\s*\(\s*(true|1)\s*\)",
                r"\bexpect\s*\(\s*true\s*\)\s*\.\s*toBeTruthy\s*\(",
                r"\bassert(\.ok)?\s*\(\s*true\s*\)",
                r"\bexpect\s*\(\s*([\w.]+)\s*\)\s*\.\s*(toBe|toEqual)\s*\(\s*\1\s*\)",
            ),
        },
        allowable=False,
    ),
    Rule(
        "test-without-assert",
        "A new test that never asserts.",
        "This test has no assertion, so it passes whatever the code does. "
        "Add an assertion on the result or the observable side effect the test name describes.",
        kind="ast",
    ),
    Rule(
        "sleep-in-test",
        "A fixed sleep in a test.",
        "A fixed sleep makes the test slow and flaky. Wait on the condition instead: "
        "await the task, poll with a timeout, or inject a fake clock (TimeProvider, TestScope, fake timers).",
        {
            "csharp": (r"\bThread\.Sleep\s*\(", r"\bTask\.Delay\s*\(\s*(\d|TimeSpan\.From)"),
            "kotlin": (r"\bThread\.sleep\s*\(", r"\bSystemClock\.sleep\s*\("),
            "java": (r"\bThread\.sleep\s*\(",),
            "python": (r"\b(time\.)?sleep\s*\(\s*\d",),
            "ts": (r"\bwaitForTimeout\s*\(", r"\bsetTimeout\s*\(\s*\w+\s*,\s*\d{2,}"),
            "js": (r"\bwaitForTimeout\s*\(", r"\bsetTimeout\s*\(\s*\w+\s*,\s*\d{2,}"),
            "go": (r"\btime\.Sleep\s*\(",),
        },
        tests_only=True,
    ),
    Rule(
        "deleted-assertions",
        "The change removes more assertions from a test file than it adds.",
        "You removed assertions from this test file. If the behaviour changed on purpose, change the expected value "
        "instead of deleting the check. If they really are obsolete, rerun with AGENT_CHECKS_ALLOW='deleted-assertions: <why>'.",
        kind="file",
        tests_only=True,
    ),
    Rule(
        "deleted-tests",
        "The change removes test cases.",
        "You deleted tests. Deleting a failing test hides the bug instead of fixing it. Restore them and fix the code; "
        "if they really are obsolete, rerun with AGENT_CHECKS_ALLOW='deleted-tests: <why>'.",
        kind="file",
        tests_only=True,
    ),
    # --- silenced errors and gates ---
    Rule(
        "empty-catch",
        "An exception is caught and dropped.",
        "This catch block swallows the exception, so the failure disappears without a trace. "
        "Handle it, log it with context and rethrow, or narrow the catch to the exception you expect. "
        "If dropping it is right, say why in a comment inside the block.",
        kind="ast",
    ),
    Rule(
        "bare-except",
        "A bare `except:` that also catches KeyboardInterrupt and SystemExit.",
        "A bare `except:` catches everything, including Ctrl-C and sys.exit. Catch the specific exception you expect.",
        {"python": (r"^\s*except\s*:",)},
    ),
    Rule(
        "rethrow-loses-stack",
        "`throw ex;` resets the stack trace.",
        "`throw ex;` throws the exception again from here and loses where it really failed. Use `throw;`.",
        {"csharp": (r"\bthrow\s+(ex|e|exc|exception|err|error)\s*;",)},
    ),
    Rule(
        "async-void",
        "An `async void` method outside an event handler.",
        "An `async void` method cannot be awaited and its exceptions crash the process. Return Task.",
        {"csharp": (r"\basync\s+void\s+\w+\s*\((?![^)]*EventArgs)",)},
    ),
    Rule(
        "suppress-warning",
        "A compiler, analyzer or linter warning is silenced.",
        "You silenced a warning instead of fixing what it reports. Fix the cause.",
        {
            "csharp": (r"#\s*pragma\s+warning\s+disable", r"\[\s*(assembly\s*:\s*)?SuppressMessage\b", r"//\s*ReSharper\s+disable"),
            "kotlin": (r"@(file:)?Suppress\s*\(",),
            "java": (r"@SuppressWarnings\s*\(",),
            "python": (r"#\s*noqa\b", r"#\s*type:\s*ignore", r"#\s*pyright:\s*ignore", r"#\s*pylint:\s*disable"),
            "ts": (r"eslint-disable", r"@ts-(ignore|nocheck)\b", r"biome-ignore"),
            "js": (r"eslint-disable", r"@ts-(ignore|nocheck)\b", r"biome-ignore"),
            "shell": (r"#\s*shellcheck\s+disable",),
            "go": (r"//\s*nolint",),
            "msbuild": (r"<NoWarn>",),
        },
        # A suppression that states its reason passes: biome's `: reason`, ESLint's `-- reason`,
        # SuppressMessage's Justification, or a trailing comment of three or more words.
        unless_line=(
            r"biome-ignore\S*\s+\S+:\s*\S+(\s+\S+){2,}|Justification\s*=\s*\"[^\"]{10,}"
            r"|(Suppress|SuppressWarnings|pragma\s+warning\s+disable|noqa|type:\s*ignore|eslint-disable[-\w]*|ts-ignore|shellcheck\s+disable|nolint)"
            r".*?(//|#|\s--)\s*[A-Za-z]\S*(\s+\S+){2,}"
        ),
    ),
    Rule(
        "weakened-gate",
        "A quality gate is turned down: warnings allowed, strict mode off, failures ignored.",
        "You weakened a quality gate (warnings as errors, nullable, strict mode, a failing CI step or hook). Make the code pass the gate instead.",
        {
            "msbuild": (r"<TreatWarningsAsErrors>\s*false", r"<Nullable>\s*(disable|warnings)", r"<WarningsNotAsErrors>", r"<EnforceCodeStyleInBuild>\s*false"),
            "yaml": (
                r"\bcontinue-on-error:\s*true",
                r"\|\|\s*true\b",
                r"\bgit\b.*--no-verify\b",
                r"\ballow_failure:\s*true",
                r"-warnaserror-",
                r"--passWithNoTests\b",
            ),
            "json": (r"\"strict\"\s*:\s*false", r"--passWithNoTests\b", r"\"noImplicitAny\"\s*:\s*false"),
            "shell": (r"^\s*[^#\"']*\bgit\b[^#\"']*--no-verify\b", r"^\s*(export\s+)?LEFTHOOK=0\b"),
            "toml": (r"^\s*strict\s*=\s*false",),
        },
    ),
    # --- unfinished work ---
    Rule(
        "stub",
        "Unfinished code: a not-implemented stub.",
        "This is a stub that fails at run time. Implement it in this change, or leave the feature out.",
        {
            "csharp": (r"\bthrow\s+new\s+NotImplementedException\b",),
            "kotlin": (r"\bTODO\s*\(",),
            "python": (r"\braise\s+NotImplementedError\b",),
            "rust": (r"\b(todo|unimplemented)!\s*\(",),
            "ts": (r"throw\s+new\s+Error\s*\(\s*['\"`](not implemented|todo)",),
            "js": (r"throw\s+new\s+Error\s*\(\s*['\"`](not implemented|todo)",),
            "go": (r"\bpanic\s*\(\s*\"(not implemented|todo)",),
        },
        unless_above=r"@(abc\.)?abstractmethod|\babstract\b|@overload|Protocol\)",
    ),
    Rule(
        "todo-comment",
        "A TODO/FIXME without an issue reference.",
        "You left a TODO in new code. Finish it in this change, or file an issue and reference it: TODO(#123) or TODO(PROJ-12).",
        {
            lang: (r"(^|\s)(//+|#+|/\*+|\*|<!--|--)\s*(TODO|FIXME|XXX|HACK)\b(?!\s*[(:]?\s*(#\d+|[A-Z][A-Z0-9]+-\d+|https?://))",)
            for lang in CODE + ("yaml", "msbuild")
        },
    ),
    Rule(
        "commented-out-code",
        "Code left in a comment.",
        "Delete commented-out code; git keeps the history. If it documents an example, say so in prose.",
        {
            **{
                lang: (
                    r"^\s*//(?!/)\s*(?!agent-checks)(?!.*\b[a-z]+,? [a-z]+,? [a-z]+ [a-z]+\b)(\S.*[(=.].*[;{}]\s*$|(var|let|const|val|if|for|foreach|while|return|await|using|import|public|private|internal|fun|func)\b.*[;({]\s*$)",
                )
                for lang in C_LIKE
            },
            "python": (
                r"^\s*#(?!!)\s*(?!.*\b[a-z]+,? [a-z]+,? [a-z]+ [a-z]+\b)(import \w+\s*$|from \S+ import \w|def \w+\(.*\):|class \w+[(:]|return\b\s*\S|print\(.*\)\s*$|await \w)",
            ),
        },
    ),
    Rule(
        "debug-leftover",
        "A debugger statement or breakpoint left in.",
        "Remove the debugger/breakpoint call before committing.",
        {
            "ts": (r"^\s*debugger\s*;?\s*$",),
            "js": (r"^\s*debugger\s*;?\s*$",),
            "python": (r"\bbreakpoint\s*\(\s*\)", r"\bpdb\.set_trace\s*\(", r"^\s*import\s+i?pdb\b"),
            "csharp": (r"\bDebugger\.(Break|Launch)\s*\(",),
            "kotlin": (r"\.printStackTrace\s*\(\s*\)",),
            "java": (r"\.printStackTrace\s*\(\s*\)",),
        },
    ),
    # --- hygiene (ports of the pre-commit-hooks basics) ---
    Rule(
        "merge-conflict",
        "A merge conflict marker.",
        "This is a leftover merge conflict marker. Resolve the conflict and remove the marker.",
        {"*": (r"^(<{7}|>{7}|\|{7})( |$)",)},
        allowable=False,
    ),
    Rule(
        "private-key",
        "A private key in the change.",
        "This is a private key. Remove it from the change, rotate it, and load it from the secret store at run time.",
        {"*": (r"-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY( BLOCK)?-----",)},
        allowable=False,
    ),
    Rule(
        "trailing-whitespace",
        "Trailing whitespace.",
        "Remove the trailing whitespace on this line.",
        {"*": (r"[ \t]+$",)},
        severity="warn",
    ),
    Rule("final-newline", "A file without a final newline.", "End the file with a newline.", kind="file", severity="warn"),
    Rule(
        "large-file",
        "A large file is added.",
        "This file is larger than the repo's limit (max_file_kb). Keep generated output, binaries and data out of git.",
        kind="file",
    ),
    Rule(
        "plaintext-env",
        "A plaintext .env file is committed.",
        "Never commit a .env file. Commit the encrypted or example version instead and add the file to .gitignore.",
        kind="file",
        allowable=False,
    ),
    Rule(
        "out-of-scope",
        "A changed file outside the task's declared scope.",
        "You changed a file outside this task's scope. Revert it, or if the task really needs it, "
        "widen the scope (AGENT_CHECKS_SCOPE or .git/agent-checks-scope) and say why.",
        kind="file",
    ),
    Rule("typo", "A misspelled word (comments and docs only).", "Fix the spelling.", kind="lint", severity="warn"),
    Rule(
        "ruff",
        "A ruff finding on an added line (the repo's ruff config, or ruff's defaults).",
        "ruff reports a problem in a line you added. Fix it; `ruff rule <code>` explains each code.",
        kind="lint",
    ),
    Rule(
        "shellcheck",
        "A shellcheck warning or error on an added line.",
        "shellcheck reports a problem in a line you added. Fix it; https://www.shellcheck.net/wiki/SC<code> explains each code.",
        kind="lint",
    ),
    Rule(
        "allow-without-reason",
        "An agent-checks allow marker without a reason.",
        "An allow marker needs a reason: `agent-checks: allow <rule> -- <why this is right>`.",
        kind="file",
        allowable=False,
    ),
]

BY_ID: dict[str, Rule] = {r.id: r for r in RULES}

# Tokens that count as an assertion or a test case, for the deleted-* rules.
ASSERT_TOKEN = re.compile(
    r"\b(Assert\.\w+|Should\(\)|\.Should\w*\(|Verify\(|Received\(|expect\s*\(|assert(?:Equals|True|False|That|NotNull|Null|Throws)\w*\s*\(|assert\s|self\.assert\w+\(|require\.\w+\(|t\.(Error|Fatal)f?\()"
)
TEST_DECL = re.compile(
    r"\[\s*(Fact|Theory|Test|TestMethod|TestCase|SkippableFact)\b|@Test\b|^\s*(async\s+)?def\s+test\w*\s*\(|\b(it|test)\s*\(\s*['\"`]|^func\s+Test\w+\s*\("
)
