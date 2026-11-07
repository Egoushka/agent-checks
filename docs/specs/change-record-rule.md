# Spec: the change-record rule

**Issue:** Egoushka/agent-checks#14
**Status:** implemented, `agent-checks change-record` and the action in [`change-record/`](../../change-record)
**Related:** [change record v0.1](../change-record-v0.1.md), the JSON in-toto form of the same six fields

## Goal

A reviewer of an agent-written pull request should not have to read prose to learn what the change implements,
what it claims, what proved it, what it may touch, what it risks and who wrote it. The PR body carries those six
facts as labelled lines, and a check fails the PR when one is missing or when the change touches a file it did not
declare.

## Input

The PR body, from `--body FILE` (`-` for stdin) or, in GitHub Actions, the `pull_request.body` of the event in
`$GITHUB_EVENT_PATH`. With `--base REF` the rule also reads the changed files, diffing the working tree against
`merge-base(REF, HEAD)`; `--base auto` picks the PR base as `agent-checks check` does.

```
Spec:   docs/specs/<file>.md or an issue URL
Claim:  owner/repo#n
Checks: <test id>  pass  run <id>
Scope:  globs of files the change may touch
Risk:   none | migration | secrets | deploy | public-api
Agent:  run id, model, cost
```

A label may be bold (`**Spec:**`), in a list item (`- Spec:`) or any case. A value may sit on the label's line, or
on the indented or list lines below it (one check per line, for instance); a blank line or the next label ends it.

## Behaviour

The rule fails (exit 1) on each of these, with a message that says what to write instead:

| Field | Fails when |
|---|---|
| any | the label is absent or has no value |
| `Spec` | the value is neither a `docs/specs/*.md` path nor an `http(s)` URL |
| `Claim` | the value is not `owner/repo#n` |
| `Checks` | a line is not `<test id> <result> run <id>`, or its result is not `pass` |
| `Scope` | `--base` is given and a changed file matches none of the globs (comma or space separated, gitignore-flavoured as in `.agent-checks.toml`) |
| `Risk` | a value is not one of the five, or `none` is combined with another |
| `Agent` | the value is not three comma-separated parts; `none` is accepted for a change written by hand |

Exit 0 when nothing fails, 3 when the body cannot be read. `--format github` prints one annotation per problem;
a scope problem is annotated on the file.

## Wiring

`uses: Egoushka/agent-checks/change-record@<tag>` on `pull_request` (and `edited`, so fixing the body reruns it),
with `fetch-depth: 2`. A repository requires it by making the job a required status check.

## Acceptance

- `tests/test_change_record.py::test_missing_spec_fails`: a body without `Spec:` fails and the message names `Spec`.
- `tests/test_change_record.py::test_scope_violation_flags`: a change to a file outside `Scope:` fails and names
  the file.
- A complete body with every changed file in scope passes.

## Out of scope

- Checking that the run ids in `Checks:` exist or that the cost in `Agent:` is right; the rule checks the form, a
  record with evidence digests is the JSON change record.
- Turning the PR body into a change-record JSON Statement.
