# Spec: candidate rules mined from rejected PRs

**Issue:** Egoushka/agent-checks#8
**Status:** implemented, `agent-checks mine` and `agent-checks replay` (`src/agent_checks/candidates.py`)

## Goal

Every chargehand PR a reviewer rejects is a labelled example of what an agent got wrong. `mine` turns a pile of
those rejections into candidate rules without a human writing a regex by hand; `replay` calibrates each candidate
against real history the way AGENTS.md already asks a hand-written rule change to be calibrated, so a candidate
only gets proposed for promotion when it fires on zero commits of accepted code.

This is scaffolding, not a weekly job: nothing here talks to GitHub. A separate process (today, a person; later,
automation someone reviews) exports rejected-PR records as local JSON files and feeds them to `mine`.

## Input: a rejected-PR record

```json
{
  "pr": "owner/repo#123",
  "path": "src/foo.py",
  "lang": "python",
  "line": "except Exception:\n",
  "category": "swallowed-retry",
  "reason": "a retry swallows the exception it was retrying on"
}
```

`agent-checks mine <file-or-dir>` reads one JSON file (a record, or a list of them) or a directory of such files.
`category` is a short slug, the same shape a review tool already gives a finding (`correctness`, `swallowed-retry`,
...); it is the grouping key, not free text, so wording differences in `reason` don't split one mistake into many
candidates.

## Mining

Records are grouped by `(category, lang)`. A group becomes a candidate only once it carries `--min-support`
(default 2) **distinct** PRs: one rejection is an incident, not a pattern. The candidate's regex is built from the
group's `line` values: tokens every line shares, in order, become literal (escaped); a run of tokens that differs
becomes `\S+`. A group whose lines share nothing usable (the whole line would be a wildcard) is dropped rather than
emitting a pattern broad enough to match anything.

Each surviving candidate is written to `<out>/<category>.<lang>.json` (default `--out candidates/`):
`{id, lang, pattern, summary, message, support}` — `support` is the sorted list of PRs it was mined from.

## Replay: calibrating a candidate on history

`agent-checks replay <candidate.json> -C <repo> [-n 360]` runs the candidate's pattern over the added lines of the
last `n` non-merge commits (default 360, matching the calibration window AGENTS.md already uses for hand-written
rules), the same commit-by-commit walk `agent-checks bench` uses for timing. A hit on a line real history added and
a reviewer let through is a false positive for the candidate — it is not evidence; it is the thing a merged rule
must avoid.

Exit 0 and "0 false positives on N commits" means the candidate is ready to go through the same path a
hand-written rule does: a `Rule(..., severity="warn")` entry in `rules.py` with a test in `tests/test_rules.py`,
calibrated further the normal way before ever reaching `error`. Any hit keeps it a candidate.

## Stop condition

Per the issue: three candidates in a row that come back with false positives on replay means this category of
mistake is not mining cleanly from the records available, and the next rule in that area should be hand-written
instead of mined.

## Out of scope here

Fetching PRs from GitHub, deciding a PR was "rejected," and turning a clean replay into a merged `rules.py` entry
are all left to whatever runs `mine`/`replay` and to a human reviewing the result — not to this tool.
