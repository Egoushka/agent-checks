# Templates

Copyable scaffolds that came out of the retired engineering-standards repo. None is a diff check, so none runs
in agent-checks; copy a file into your repo and adjust the marked names.

| Path | What | Related rule |
|---|---|---|
| `dotnet/Directory.Build.props` | locked restore and NuGet audit for every project | `weakened-gate` flags a change that turns either off |
| `dotnet/nuget.config` | one source plus source mapping, against dependency confusion | |
| `dotnet/mutation.yml` | Stryker.NET mutation testing on a schedule, report only until you raise `BREAK_AT` | see `docs/beyond.md` item 2 |
| `dotnet-tests/` | ArchUnitNET, Coyote, hurl and oasdiff test tooling, each from a measured pilot (see its README) | |
| `dependabot-automerge.yml` | squash-merges Dependabot patch and minor bumps once checks are green | |
