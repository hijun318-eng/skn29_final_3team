# Semantic catalog authoring boundary

Answervice runtime never reads a release-specific JSON file. It resolves datasets,
schemas, glossary terms, governance details, and semantic rules from live DataHub,
then verifies physical schema fingerprints against live Trino
`information_schema`.

The first release still needs business meaning that cannot be inferred safely from
column names. The operator therefore supplies one reviewed policy through stdin to
`author_semantic_catalog.py`. The command does not accept a policy file path and does
not persist the input locally.

The authoring transaction performs these gates in order:

1. Discover the complete physical scope from environment-backed ingestion recipes.
2. Read matching dataset identities and fields from DataHub and table metadata from
   Trino.
3. Require the approved policy to cover that live scope exactly. Unknown or missing
   assets and columns fail closed.
4. Take URNs, platform identity, table type, ordinals, native types, and nullability
   only from the live systems. The policy cannot supply or override those fields.
5. Validate all governed metrics, terms, joins, time rules, entitlements, and schema
   links with the shared publication contract.
6. Publish the in-memory canonical bundle to DataHub.
7. Re-read DataHub and Trino until the exact catalog hash converges within the bounded
   timeout. Partial or drifting publication returns a non-zero result.

The stdin object uses contract version
`answervice.semantic_authoring.v1`. Its top-level fields are:

- `contract_version`, `catalog_version`, `policy_version`,
  `schema_context_version`
- `governance_entities`, `assets`, `metric_rules`, `metric_terms`
- `dimensions`, `join_graph`, `time_rules`, `parameter_contract`, `query_policy`

Each policy asset identifies only its three-part `fqn` and approved semantic facts:
description, semantic/data versions, provenance, approval, entitlements, grain,
column roles/descriptions/key claims, and native governance references. A policy
asset cannot contain a dataset URN, platform, table type, native type, ordinal, or
nullability.

Every referenced CorpGroup owner must already be provisioned by the organization’s
IdP/DataHub administration process. Authoring checks its URN, display name,
description, and active status before any mutation; it never creates or repairs an
identity owner.

Operational invocation is a two-step check-and-publish flow. Install the pinned dependencies from
`requirements.authoring.txt`. Both steps require `TRINO_DATAHUB_USER`, the
environment-only secret `TRINO_DATAHUB_PASSWORD`, an HTTPS `TRINO_URL`, and the
absolute CA PEM path `TRINO_TLS_CA_FILE` (or host-side
`TRINO_TLS_CA_HOST_FILE`). They also require `DATAHUB_PUBLISH_ACTOR_URN`,
the recipe environment variables, and the canonical `DATAHUB_GMS_URL`,
mutation-only `DATAHUB_PUBLISH_API_TOKEN`,
`DATAHUB_PUBLISH_ACTOR_URN`, and absolute `DATAHUB_TLS_CA_FILE` (or host-side
`DATAHUB_TLS_CA_HOST_FILE`). The command has
no token or password option because argv and shell history are not credential
channels. A missing credential, non-HTTPS URL, or unavailable CA file fails
before the first network request.

First, pipe the reviewed policy to `--check`. This read-only operation discovers the
live physical scope and emits the policy hash, physical-scope hash, current
predecessor catalog hash, target catalog hash, actor, and subject.

When the approval system stores only business decisions rather than 578 copied
physical fields, pipe the compact `answervice.policy_decisions.v1` object to
`preflight_policy_decisions.py`. The compiler takes dataset URNs, domains, column
order, native types, nullability, and descriptions from the same live DataHub and
Trino release, then runs the normal authoring discovery a second time to reject
drift. Its output contains the expanded policy and publication check that the
operator reviews together. The compact decision file is not a runtime metadata
source.

```powershell
$checkResult = $compactDecisionJson | python `
  infrastructure/database/datahub/preflight_policy_decisions.py `
    --serving-schema analytics_v4_3
if ($LASTEXITCODE -ne 0) { throw 'Policy decision check failed.' }
```

```powershell
$checkResult = $policyJson | python `
  infrastructure/database/datahub/author_semantic_catalog.py `
    --check --serving-schema analytics_v4_3
if ($LASTEXITCODE -ne 0) { throw 'Semantic catalog check failed.' }
```

Review the returned asset counts and hashes. Publication is a separate explicit
command and requires both the target `catalog_sha256` and the
`previous_catalog_sha256` returned by that check. It re-discovers the complete live
scope and rejects either checksum if anything changed between the two commands.

```powershell
$policyJson | python `
  infrastructure/database/datahub/author_semantic_catalog.py `
    --publish --serving-schema analytics_v4_3 `
    --expected-catalog-sha256 $checkedCatalogSha256 `
    --expected-previous-catalog-sha256 $checkedPreviousCatalogSha256
if ($LASTEXITCODE -ne 0) { throw 'Checked semantic publication was not verified.' }
```

There is no implicit publish mode and no file-based policy fallback. An old check
cannot overwrite a newer catalog because its predecessor checksum no longer matches.
This is an operator safety check, not a DataHub-required approval protocol. If a
future deployment needs two-person or regulated approval, that control belongs in a
separate change-management system rather than a development-only bypass in this CLI.

`PUBLISHED_AND_VERIFIED` means the same content-derived catalog hash was rebuilt from
live DataHub and Trino after publication. Unit tests using `MockTransport` prove only
wire and validation contracts; they are not live publication evidence.

Pinned DataHub v1.7 exposes different authoritative fields across its read APIs.
GlossaryTerm status/lifecycle and editable field-term associations are verified from
Rest.li aspects. GraphQL independently verifies entity identity, owner, domain, the
dataset-level term set, and schema values; it returns null for the two field surfaces
above. The verifier never fills those nulls from a fixture or local JSON.
