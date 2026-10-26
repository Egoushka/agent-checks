# Rules and configuration

Generated from `agent-checks rules --markdown`; the messages themselves live in
[`src/agent_checks/rules.py`](../src/agent_checks/rules.py).

Every rule looks only at lines the change adds, except the whole-change rules (deleted tests and
assertions, file size, `.env`, scope), which look at the change as a whole. `error` rules fail the check;
`warn` rules are printed and never fail it.

| Rule | Catches | Scope | Allow marker | Level |
|---|---|---|---|---|
| `skip-test` | A test is skipped, ignored or disabled. | added lines | yes | error |
| `focused-test` | A test is focused with .only, which silently skips every other test. | added lines | no | error |
| `tautology` | An assertion that can never fail. | added lines | no | error |
| `test-without-assert` | A new test that never asserts. | added lines | yes | error |
| `sleep-in-test` | A fixed sleep in a test. | test files | yes | error |
| `deleted-assertions` | The change removes more assertions from a test file than it adds. | test files | yes | error |
| `deleted-tests` | The change removes test cases. | test files | yes | error |
| `empty-catch` | An exception is caught and dropped. | added lines | yes | error |
| `bare-except` | A bare `except:` that also catches KeyboardInterrupt and SystemExit. | added lines | yes | error |
| `rethrow-loses-stack` | `throw ex;` resets the stack trace. | added lines | yes | error |
| `async-void` | An `async void` method outside an event handler. | added lines | yes | error |
| `suppress-warning` | A compiler, analyzer or linter warning is silenced. | added lines | yes | error |
| `weakened-gate` | A quality gate is turned down: warnings allowed, strict mode off, failures ignored. | added lines | yes | error |
| `stub` | Unfinished code: a not-implemented stub. | added lines | yes | error |
| `todo-comment` | A TODO/FIXME without an issue reference. | added lines | yes | error |
| `commented-out-code` | Code left in a comment. | added lines | yes | error |
| `debug-leftover` | A debugger statement or breakpoint left in. | added lines | yes | error |
| `merge-conflict` | A merge conflict marker. | added lines | no | error |
| `private-key` | A private key in the change. | added lines | no | error |
| `trailing-whitespace` | Trailing whitespace. | added lines | yes | warn |
| `final-newline` | A file without a final newline. | whole change | yes | warn |
| `large-file` | A large file is added. | whole change | yes | error |
| `plaintext-env` | A plaintext .env file is committed. | whole change | no | error |
| `out-of-scope` | A changed file outside the task's declared scope. | whole change | yes | error |
| `typo` | A misspelled word (comments and docs only). | added lines | yes | warn |
| `ruff` | A ruff finding on an added line (the repo's ruff config, or ruff's defaults). | added lines | yes | error |
| `shellcheck` | A shellcheck warning or error on an added line. | added lines | yes | error |
| `allow-without-reason` | An agent-checks allow marker without a reason. | whole change | no | error |

## The allow marker

When a flagged line is right, say why in a comment on that line or the one above:

```csharp
// agent-checks: allow suppress-warning -- the source generator needs instance methods
#pragma warning disable CA1822
```

The reason must be there (five characters or more), or the marker itself fails as `allow-without-reason`.
`focused-test`, `tautology`, `merge-conflict`, `private-key` and `plaintext-env` cannot be allowed. A
suppression that already carries its reason passes without a marker: biome's `biome-ignore rule: reason`,
ESLint's `-- reason`, `SuppressMessage(..., Justification = "...")`, or a trailing comment of three or more
words.

Whole-change rules have no line to put a marker on. Allow them for one run with an environment variable
that carries the reason:

```bash
AGENT_CHECKS_ALLOW='deleted-tests: FooTests moved into BarTests in this change' git commit
```

## Scope

An orchestrator can pin the files a task may touch. Every changed file outside the globs fails as
`out-of-scope`:

```bash
AGENT_CHECKS_SCOPE='src/Billing/**,tests/Billing/**' agent-checks check --base origin/main
```

or one glob per line in `.git/agent-checks-scope`.

## `.agent-checks.toml`

Its presence also turns on the Claude Code hook for the repo.

```toml
disable = ["todo-comment"]          # rule ids switched off
exclude = ["website/site/**"]       # never checked, on top of lockfiles, generated and vendored code
tests = ["**/selftest.sh"]          # extra test-file globs for the test-only rules
error = ["final-newline"]           # promote warnings to errors
warn = ["sleep-in-test"]            # or demote errors to warnings
linters = ["typos", "ruff", "shellcheck"]
assert_helpers = ["shows", "golden"] # shared test helpers that assert, defined outside the test file
max_file_kb = 512

[rules.commented-out-code]
exclude = ["docs/examples/**"]
```

ruff uses the repo's own config when it has one (`ruff.toml`, `.ruff.toml` or `[tool.ruff]` in
`pyproject.toml`); otherwise a bug-only set: `E9,F,B006,B008,B012,B015,B017,B018,B023,B904,PLE`. typos
checks comments in code and all text in docs, because identifiers and string data produce mostly false hits.

## Commands

| Command | Use |
|---|---|
| `agent-checks check [--staged \| --base REF \| --commit SHA \| --all] [paths]` | the check; `--base auto` picks the PR base in GitHub Actions |
| `agent-checks check --format json\|github` | machine output, or GitHub annotations |
| `agent-checks hook claude` | Claude Code PostToolUse hook; exit 2 hands the message to the agent |
| `agent-checks install [DIR]` | lefthook.yml + .agent-checks.toml, existing `.githooks` scripts moved under lefthook |
| `agent-checks bench -C DIR -n 20` | time the check over a repo's last commits |
| `agent-checks doctor` | which engines are installed |

Exit codes: 0 clean, 1 findings, 3 a usage or git error.
