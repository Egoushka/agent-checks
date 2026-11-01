# Test tooling templates (.NET)

Copy a folder into a repo, rename the `.txt` files back, adjust the marked names. Each came out of a measured pilot (`context/ai-setup/audits/2026-10-30-dotnet-test-pilots.md` in the workspace repo); the numbers are there.

| Folder | Tool | Use when | Proven in |
|---|---|---|---|
| `archunitnet/` | [ArchUnitNET](https://github.com/TNG/ArchUnitNET) 0.13.5 | the solution has layers or modules whose references must stay one-way | Catalyst: 10 rules, 1 real violation found on the first run, a seeded one caught by the exact rule |
| `coyote/` | [Coyote](https://github.com/microsoft/coyote) 1.7.11 | async code where an order of awaits (a cancel, a completion, a report) can lose a result | chargehand: finds the PR #308 race in 10 schedules where a plain loop needs ~1,500 runs; blind to unlocked races |
| `hurl/` | [hurl](https://hurl.dev) 8.1.0 | a spec's acceptance table has HTTP calls: write them as `.hurl` files and run `scripts/smoke.sh` in CI | subgate: v0.1 C1 to C6 and v0.2 WC1 to WC4 |
| `oasdiff/` | [oasdiff](https://github.com/oasdiff/oasdiff) 1.35.0 | the repo commits an OpenAPI file: a PR job fails on a breaking change; `selftest.sh` proves the gate can fail | photo-alpha: 9 of 9 seeded breaking edits flagged, 5 of 5 safe edits pass (`--fail-on WARN`) |

Rules that held in every pilot: pin the tool by version and, for a downloaded binary, by SHA-256; write the check so it can fail and show it failing (a stub server, a seeded violation, a mutation) before trusting a green run; Coyote telemetry stays off.
