# What else raises agent code quality, ranked

agent-checks catches what a diff shows: a skipped test, an empty catch, a silenced warning. It cannot tell
whether the tests that remain would notice a broken change. These techniques can, ranked by quality gained
per minute of CI and per hour of setup, for repos like the ones this kit was built for (.NET services,
Kotlin Android, TypeScript sites, Python scripts).

| Rank | Technique | What it catches that agent-checks misses | Cost | Recommendation |
|---|---|---|---|---|
| 1 | **Diff coverage gate** | New code that no test runs at all | Seconds on top of the existing test run | Adopt in every repo with tests |
| 2 | **Mutation testing on changed code** | Tests that run the code but would not fail if it broke | Minutes per PR on the changed files | Adopt for the .NET repos, PR-only |
| 3 | **Snapshot / approval tests** at boundaries | Silent changes to API output, prompts, generated files | An hour per boundary; cheap to run | Adopt where output is large and structured |
| 4 | **Property-based tests** for parsers and pure logic | Edge cases nobody wrote an example for | A few hours per property; seconds to run | Targeted: parsers, money maths, serializers |
| 5 | **Contract tests** between services | One side changing a shape the other relies on | Ongoing upkeep of a shared contract | Only where two repos talk over HTTP |

## 1. Diff coverage gate

Fail the PR when less than N% of the lines it adds are executed by tests. An agent that writes code
without tests, or a test that never reaches the new branch, fails here. It reuses the coverage report the
test run already produces: Coverlet (`--collect "XPlat Code Coverage"`) for .NET, Kover or JaCoCo for
Kotlin, c8 or Vitest for TypeScript, pytest-cov for Python, all of which can write Cobertura XML.

`agent-checks diffcover` reads that XML plus the same added-line map the rules use and reports the
changed lines' coverage. It is stdlib only, so it adds no dependency to the kit;
[diff-cover](https://github.com/Bachmann1234/diff_cover) does the same job and is the cross-check.

```bash
pytest --cov=mypkg --cov-report=xml        # any runner that writes Cobertura XML
agent-checks diffcover --base auto --report-only      # week one: print, never fail
agent-checks diffcover --base auto                    # then fail under 80
```

A line the report does not list (blank, comment, signature) does not count; a changed file the report
does not mention is named in the summary but not counted. The failure message lists the unrun lines as
`path:3-4` and, with `--format github`, annotates each one.

**Check.** On a PR, the share of added executable lines that tests run is at least 80%.
Measured by `agent-checks diffcover` over the PR's diff and the test run's `coverage.xml`.

**Stop.** Drop back to `--report-only` (or remove the step) if, after the first week of report-only data,
either (a) more than 1 in 5 PRs that would fail do so on lines not worth a test (generated code, thin
glue, platform entry points), or (b) the step adds more than 10 seconds to a PR run. Raise the threshold
only after a month under 80 with no stop line hit. All three numbers, 80, 20% and 10 s, are starting
values from this document, not calibrated ones; replace them with the week's data.

**This repo.** `ci.yml` runs the gate on pull requests in report-only mode from 2026-11-07. The week
ends 2026-11-14; read the PR logs, then drop `--report-only` or apply the stop line.

## 2. Mutation testing on changed code

A mutation tool flips an operator or deletes a statement and reruns the tests; a mutant that survives
means no test would catch that bug. This is the direct answer to "tests that assert nothing useful",
the failure chargehand's baseline found. Full runs are slow, so run it only on what the PR changes:
Stryker.NET has a `--since` mode that mutates code changed against a target branch
([Stryker docs](https://stryker-mutator.io/blog/azure-pipelines-integration/)), and
[`templates/dotnet/mutation.yml`](../templates/dotnet/mutation.yml) is a ready workflow for it. Wire it as a PR job with a
break threshold on the changed files (start at 0, report only, then raise to 60). StrykerJS covers the
TypeScript repos the same way; PIT works for Kotlin/JVM but is heavier on Android.

## 3. Snapshot / approval tests

Record the full output of a boundary (an HTTP response, a rendered prompt, a generated config) and fail on
any difference. Agents change outputs as a side effect more often than humans do, and a snapshot diff
shows it in review. Verify (.NET), Paparazzi or Roborazzi (Android UI), and Vitest/Jest snapshots
cover the stacks here. The risk is rubber-stamping: an agent can re-record a snapshot to make a test pass,
so treat a changed `*.verified.*` or `__snapshots__` file as a change that needs its own justification in
the PR.

## 4. Property-based tests

State a rule ("parse(format(x)) == x", "a total never goes negative") and let the library generate
hundreds of inputs. They find the edge cases example tests miss, and they are hard for an agent to game,
because the agent does not choose the inputs. CsCheck or FsCheck (.NET), Kotest properties (Kotlin),
fast-check (TypeScript) and Hypothesis (Python). Worth it for parsers, validators and arithmetic; not
worth it for glue code.

## 5. Contract tests

Pin the request and response shapes two services agree on (Pact, or a shared JSON Schema checked on both
sides). Only pays off where two repos actually talk to each other over HTTP; the upkeep is real.

## What does not help much

- **Raising coverage targets on the whole repo.** Agents meet them with tests that execute code without
  asserting; diff coverage plus mutation testing measures the right thing.
- **More prompt rules.** A rule in CLAUDE.md is a hope; a failing check with a corrective message is a
  mechanism. That is the point of this kit.
