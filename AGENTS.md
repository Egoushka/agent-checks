# agent-checks — agent notes

Python 3.11+, stdlib only at run time; ast-grep, typos and ruff come in as wheels.

- Set up: `uv sync`
- Test: `uv run pytest -q` (every rule has a bad and a good case in `tests/test_rules.py`)
- Lint: `uv run ruff check src tests`
- Self-check: `uv run agent-checks check --base origin/main`
- Calibrate a rule change on real history before raising it to `error`: `agent-checks bench -C <repo>` and
  `agent-checks check -C <repo> --commit <sha>` over the last 40 commits of a few repos.
- A candidate rule (not yet in `rules.py`) can be replayed the same way without writing the loop by hand:
  put it as an ast-grep YAML file (shaped like `src/agent_checks/data/rules/*.yml`) in a directory and run
  `agent-checks candidates <dir> <repo>...`. It fails (exit 1) if the rule fires on any already-accepted
  commit; only a rule with zero fires is a candidate for promotion. It does not mine rejected PRs into
  candidates itself — that needs a feed of rejected PRs this repo does not have.

Rules:
- A rule's message is an instruction to the agent that wrote the line: what is wrong, what to do instead.
- New rules start as `severity="warn"` until calibration shows they rarely fire on good code.
- Every rule needs a positive and a negative case in `tests/test_rules.py`.
- `docs/rules.md` is generated in part from `agent-checks rules --markdown`; keep the table in sync.
