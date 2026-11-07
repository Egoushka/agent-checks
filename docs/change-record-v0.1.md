# Change record v0.1

<!-- Licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). The code in this repository is MIT. -->

**Type URI:** `https://github.com/Egoushka/agent-checks/change-record/v0.1`
**Version:** 0.1 (draft; 0.x versions are major versions, so any 0.x change may break)
**Schema:** [`change-record-v0.1.schema.json`](../src/agent_checks/data/change-record-v0.1.schema.json) (JSON Schema 2020-12)
**Verifier:** `agent-checks verify-record FILE`, or the action in [`verify-record/`](../verify-record)
**License of this document:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

## Purpose

A change record says, for one change: what it claims to do, which checks were run to prove that, and a digest of
the evidence each check left. It is an [in-toto attestation](https://github.com/in-toto/attestation) predicate, so
it is carried in a standard Statement, can be wrapped and signed like any other attestation, and sits next to SLSA
provenance instead of replacing it.

It exists because the other records about agent-written code answer other questions. SLSA provenance says how an
artifact was built. [Agent Trace](https://agent-trace.dev) says which lines an AI wrote. Neither says what was
proven about the change. This record does, and links to Agent Trace for the "who".

This is a draft by one author. It has not been submitted to the in-toto maintainers for vetting; the in-toto
guidelines say "New predicate types MAY be vetted by the in-toto attestation maintainers", and the URI is under
this repository's namespace, not `in-toto.io`.

## Use cases

- A reviewer or a merge gate asks "what was proven about this PR?" and gets a machine-checkable answer, not a
  paragraph of agent prose.
- A maintainer receiving an agent-written PR can require a record and run `verify-record` in CI.
- A team keeps records next to its build provenance and queries them with the same tooling.

## Model

The Statement's `subject` is the change: normally the git commit the checks ran against, as
`{"gitCommit": "<sha>"}`. Which revision a record describes is the one thing a consumer must pin, because a record
about another commit proves nothing about this one. v0.1 does not say how to pick the commit for a squash merge;
record the commit the checks ran on.

The predicate has six fields. Each is a claim by the producer. A signature on the Statement says who made the
claims; it does not make them true. What the record adds is a way for a reader to rerun `command` and compare the
output with the `evidence` digest.

## Schema

The schema is [`change-record-v0.1.schema.json`](../src/agent_checks/data/change-record-v0.1.schema.json). It
validates the predicate only. The Statement layer (`_type`, `subject`, `predicateType`) is checked by
`verify-record` against the in-toto spec.

## Parsing rules

The record follows the in-toto framework's standard parsing rules. The one that matters here, from the in-toto
`spec/v1/README.md`: "Consumers MUST ignore unrecognized fields unless otherwise noted in the predicate
specification." This specification notes no exception, so a v0.1 consumer ignores fields it does not know, and a
later 0.1.x may add optional fields. Versioning follows the same document: "Each type has a SemVer2 version number
and the TypeURI reflects the major version number", with "0.X versions ... considered major versions".

## Fields

Names are lowerCamelCase, as the in-toto predicate guidelines recommend. This version defines no timestamps.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `spec` | object | yes | What the change is meant to do. |
| `spec.uri` | string | yes | The issue, ticket or document it implements. |
| `spec.digest` | DigestSet | no | Digest of that document's content, when it is a file that can change. |
| `claim` | string | yes | One statement of what the change does or guarantees. The checks are meant to prove this. |
| `checks` | array, at least 1 | yes | The checks that were run. |
| `checks[].name` | string | no | A label for people. |
| `checks[].command` | string | yes | The command that was run, exactly. |
| `checks[].result` | `pass`, `fail`, `error` or `skipped` | yes | What happened. Only `pass` counts as proof. |
| `checks[].evidence.digest` | DigestSet | yes | Digest of the check's output (log, report, artifact). |
| `checks[].evidence.uri` | string | no | Where the evidence can be read. |
| `scope.paths` | array of string, at least 1 | yes | The paths or globs the claim covers. |
| `risk.level` | `low`, `medium` or `high` | yes | The producer's rating of what a mistake would cost. |
| `risk.rationale` | string | no | Why. |
| `agent.name` | string | yes | The agent that made the change. |
| `agent.version` | string | no | |
| `agent.model` | string | no | `provider/model-name`, the form Agent Trace uses. |
| `agent.trace.id` | string (UUID) | no | The `id` of the Agent Trace record for the same change. |
| `agent.trace.uri` | string | no | Where that record can be read. |

A **DigestSet** is the in-toto type: "a _JSON object_ mapping algorithm name to a string encoding of the digest
using that algorithm", lowercase hex for the standard algorithms. In this predicate `sha256` is required, because
in-toto recommends "at least `sha256` for compatibility between producers and consumers"; other algorithms may sit
beside it.

## Composing with Agent Trace

Agent Trace (v0.1.0, an RFC when this was written) records `files[].conversations[].ranges` with a contributor
type (`human`, `ai`, `mixed`, `unknown`), a `model_id` and the VCS `revision` it describes. It deliberately does
not define storage, and its own record is not an attestation.

The two records meet at the revision. An Agent Trace record's `vcs.revision` and this Statement's
`subject[].digest.gitCommit` name the same commit, and `agent.trace.id` is that record's `id`. A consumer that has
both can say which lines the AI wrote and what was proven about them. Neither record has to know about the other
to be valid; `agent.trace` is optional, and `agent.model` copies Agent Trace's `provider/model-name` convention so
the two agree without translation.

## What `verify-record` checks

`agent-checks verify-record FILE` reads a Statement as JSON and exits:

| Exit | Meaning |
|---|---|
| 0 | The Statement and predicate are well formed and every check's `result` is `pass`. |
| 1 | The file is not JSON, the Statement layer or the predicate breaks this specification, or a check's `result` is not `pass`. |
| 3 | The file cannot be read (missing, a directory, no permission). |

It does **not**: verify a signature (do that first with the tool that signed it, then pass the decoded payload);
fetch the evidence or compare it with its digest; check that `subject` matches the commit you are looking at; or
decide whether `command` is a good check for `claim`. Those are a consumer's policy, and v0.1 leaves them out
rather than guess.

## Example

An entire Statement, as the in-toto template requires:

```json
{
  "_type": "https://in-toto.io/Statement/v1",
  "subject": [
    {
      "name": "git+https://github.com/example/app",
      "digest": { "gitCommit": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0" }
    }
  ],
  "predicateType": "https://github.com/Egoushka/agent-checks/change-record/v0.1",
  "predicate": {
    "spec": { "uri": "https://github.com/example/app/issues/42" },
    "claim": "Retrying a failed webhook delivery no longer sends the payload twice.",
    "checks": [
      {
        "name": "webhook tests",
        "command": "pytest tests/test_webhooks.py",
        "result": "pass",
        "evidence": { "digest": { "sha256": "9f2e8a1b4c6d7e8f0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6071" } }
      }
    ],
    "scope": { "paths": ["src/webhooks/**"] },
    "risk": { "level": "low", "rationale": "Delivery path only; no schema change." },
    "agent": {
      "name": "claude-code",
      "model": "anthropic/claude-opus-4-5-20251101",
      "trace": { "id": "550e8400-e29b-41d4-a716-446655440000" }
    }
  }
}
```

Wrapped in a DSSE envelope, the `payloadType` is `application/vnd.in-toto+json`, as the in-toto envelope spec
allows.

## Use in CI

```yaml
- uses: actions/checkout@v7
- uses: Egoushka/agent-checks/verify-record@main  # pin a release tag once one includes verify-record
  with:
    record: change-record.json
```

## Changelog

- **0.1** (draft): the six fields above.
