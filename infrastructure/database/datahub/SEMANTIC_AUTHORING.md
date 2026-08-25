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
3. Require every approved policy asset to exist in the live scope and retain every
   asset in the active governed manifest. Newly ingested but ungoverned assets are
   not inferred or added to the release; unknown assets, governed removals, and
   missing columns fail closed.
4. Take URNs, platform identity, table type, ordinals, native types, and nullability
   only from the live systems. The policy cannot supply or override those fields.
5. Validate all governed metrics, terms, joins, time rules, entitlements, and schema
   links with the shared publication contract.
6. Publish the legacy and native semantic surfaces derived from the same in-memory
   canonical bundle to DataHub.
7. Re-read the active DataHub manifest, native semantic aspects, and live Trino until
   their exact checksums converge within the bounded timeout. Partial or drifting
   publication returns a non-zero result.

New publications use `answervice.semantic_authoring.v3` for the all-public metric
contract or `answervice.semantic_authoring.v4` for the visibility- and
execution-governed metric contract. The legacy v1/v2 envelopes remain parseable but
are not emitted by migration or policy compilation. Its top-level fields are:

- `contract_version`, `catalog_version`, `policy_version`,
  `schema_context_version`
- `governance_entities`, `assets`, `metric_rules`, `metric_terms`
- `dimensions`, `join_graph`, `time_rules`, `parameter_contract`, `query_policy`

An authoring envelope and every Metric Rule in that envelope must use the same
governance generation. A v1 envelope accepts only the v1 Rule shape. A v2 envelope
requires every Rule to include one exact `governance` object containing semantic,
grain, time, join, permission, visibility, and allowed query-strategy facts. Mixed
or partially upgraded releases fail before publication.

In v2, only `BUSINESS` Rules have exactly one reviewed DataHub Glossary Term and
field/dataset term association. `SUPPORT` Rules are executable operands, not
business concepts: they must not have a Glossary Term or association. They are not
removed from governance. The complete BUSINESS and SUPPORT registry is checksum-
bound into every release Dataset property, read back after publication, and used by
the Backend to enforce metric role, PII, join-edge, grain/time, and query-strategy
boundaries. Runtime ratio calculation can therefore consume hidden operands without
exposing them as selectable business metrics.

## Runtime natural-language resolution

The runtime follows the same separation used by mature semantic BI products:
business names and synonyms belong to governed semantic metadata, while selectable
dimension values come from the approved field rather than from application phrase
rules. Looker filter suggestions query the field's distinct values, Snowflake Cortex
Analyst combines semantic synonyms and sample values with reviewed queries, and
Power BI Q&A relies on model names, synonyms, and row-label modeling. These are
reference patterns, not runtime dependencies:

- [Looker filter suggestions](https://docs.cloud.google.com/looker/docs/changing-filter-suggestions)
- [Snowflake verified query suggestions](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/verified-query-suggestions)
- [Power BI Q&A linguistic schema](https://learn.microsoft.com/en-us/power-bi/natural-language/q-and-a-tooling-advanced)

Answervice applies that boundary as follows:

1. DataHub supplies the approved dimension ID, aliases, asset FQN, and column. No
   hotel name, Korean transliteration table, or request-specific phrase branch is
   embedded in production code.
2. Node 1 first detects a named filter from the user's text without touching Trino.
   Presentation and report-action turns, and analysis questions with no named
   filter, perform no dimension suggestion query.
3. Only the referenced approved dimension may run a bounded live `SELECT DISTINCT`
   query. A domain with more than 64 values is treated as high-cardinality and no
   partial candidate list is sent to the model. Complete low-cardinality domains
   use a short process-local TTL controlled by
   `DIMENSION_VALUE_CACHE_TTL_SECONDS` (30--3,600 seconds; default 300).
4. If canonicalization is needed, Node 1 receives the complete candidate list once.
   The selected value is still untrusted until the server performs a parameterized,
   case-insensitive exact lookup against the same approved field.
5. A stated restriction is never silently dropped. A candidate that cannot be
   canonicalized remains the exact source span and ends in a typed unresolved-filter
   response if the live lookup cannot prove one match.

Relative dates use the request's governed `as_of`, timezone, and calendar rather
than the runtime clock. A month with no year inherits the year of `as_of`. Any
current, incomplete interval is capped to `[start, as_of)`; the `as_of` business date
itself is excluded, future-only intervals are rejected, and user-facing explanations
must describe `end_exclusive` as "before" that date. This is deliberately stricter
than products that expose an `includeToday` toggle: Answervice's data contract fixes
that toggle to false for reproducible analysis.

The existing v1 catalog remains readable. Creating a v2 check result does not
publish or activate it; publication still requires the explicit optimistic-
concurrency command below, and runtime activation remains a separate operator
action.

Before compiling a reviewed Metric candidate into a v2 policy decision, compare it
with the current live release. This gate validates the candidate against its SQL
release, reconstructs the current semantic bundle from DataHub and Trino, and
computes added, retained, and retirement-candidate BUSINESS Metric IDs. It has no
mutation path and always returns `publishable: false`.

```powershell
python infrastructure/database/datahub/check_metric_review_transition.py `
  --candidate evals/semantic_review/answervice_d2_metrics.v1.json `
  --sql-directory <reviewed-serving-sql-directory> `
  --serving-schema <selected-live-serving-schema> `
  --check
```

`DEPRECATION_REVIEW_REQUIRED` exits with code 3. A missing live BUSINESS Metric is
not interpreted as an approved deletion, even when the new candidate itself has
already passed review. The operator must either add the existing Metric to the new
review or record an explicit retirement decision in the external change-management
boundary before policy compilation. This prevents a D2 rollout from silently
removing previously published service capabilities.

An approved product-scope removal uses the separate, versioned Metric retirement
transaction. A decision binds each Metric ID to its exact Glossary Term URN, the
predecessor catalog version and checksum, a new target catalog version, authority,
timestamp, and reason. The implementation is entity-agnostic: Metric names live only
in the reviewed decision, never in runtime branching code. It also rejects a removal
that leaves a retained ratio Metric pointing to a retired operand.

Run the mutation-free check first. It re-discovers the full DataHub and Trino release
and returns decision, predecessor, and target SHA-256 values.

```powershell
$retirement = 'infrastructure/database/datahub/decisions/<decision>.json'
$checked = python infrastructure/database/datahub/retire_semantic_metrics.py `
  --decision $retirement --serving-schema <selected-live-serving-schema> --check
if ($LASTEXITCODE -ne 0) { throw 'Metric retirement check failed.' }
```

Pass all three returned hashes to the explicit publish command. It first upserts the
new complete Dataset release, then soft-deletes the retired Glossary Terms. A retry
after an interruption detects an already-converged target release and completes only
the missing Term status updates.

```powershell
python infrastructure/database/datahub/retire_semantic_metrics.py `
  --decision $retirement --serving-schema <selected-live-serving-schema> `
  --publish `
  --expected-decision-sha256 $checkedDecisionSha256 `
  --expected-previous-catalog-sha256 $checkedPreviousCatalogSha256 `
  --expected-target-catalog-sha256 $checkedTargetCatalogSha256
if ($LASTEXITCODE -ne 0) { throw 'Metric retirement publication failed.' }
```

Finally, use the read-only identity for a separate read-back. Verification requires
the target catalog to reconstruct from DataHub and live Trino and every retired Term
to retain its identity while reporting `status.removed=true`.

```powershell
python infrastructure/database/datahub/retire_semantic_metrics.py `
  --decision $retirement --serving-schema <selected-live-serving-schema> `
  --verify `
  --expected-decision-sha256 $checkedDecisionSha256 `
  --expected-target-catalog-sha256 $checkedTargetCatalogSha256
if ($LASTEXITCODE -ne 0) { throw 'Metric retirement read-back failed.' }
```

Each current policy asset identifies only its three-part `fqn` and approved semantic
facts: semantic/data versions, provenance, approval, entitlements, grain, column
logical roles/key claims, and native governance references. Dataset and field
descriptions come only from live DataHub connector read-back. A policy asset cannot
contain a dataset URN, platform, table type, native type, ordinal, nullability, or a
copied physical description.

Every referenced CorpGroup owner must already be provisioned by the organization’s
IdP/DataHub administration process. Authoring checks its URN, display name,
description, and active status before any mutation; it never creates or repairs an
identity owner.

Runtime source recipes own physical discovery and `schemaMetadata`. Their pinned
DataHub v1.7 `simple_add_dataset_properties` transformer uses `PATCH` with
`replace_existing: false`, so a later base ingestion merges connector properties
without deleting `answervice.*` semantic properties. Base ingestion is nevertheless
only `BASE_METADATA_INGESTED`: schema changes remain connector-owned and the semantic
release becomes ready only after the authoring check/publish transaction re-reads the
complete manifest and verifies every physical fingerprint against Trino.

The semantic publisher never writes `schemaMetadata`; it only verifies the connector-
owned schema against the live Trino relation before and after semantic publication.
This prevents two writers from racing over physical field order, types, and schema hash.

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
predecessor catalog hash, target catalog hash, native semantic projection hash,
actor, and subject.

When the approval system stores only business decisions rather than 578 copied
physical fields, pipe the compact `answervice.policy_decisions.v1` or matching v2
object to `preflight_policy_decisions.py`. The compiler takes dataset URNs, domains,
column order, native types, nullability, and descriptions from the same live DataHub
and Trino release, then runs the normal authoring discovery a second time to reject
drift. A v1 decision compiles only to a v1 authoring envelope and a v2 decision only
to v2; cross-version input fails closed. Its output contains the expanded policy and
publication check that the operator reviews together. The compact decision file is
not a runtime metadata source.

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
the active DataHub manifest and Trino, and the native semantic projection passed
exact Rest.li aspect read-back. Unit tests using `MockTransport` prove only wire and
validation contracts; they are not live publication evidence.

## Standalone DataHub v1.7 native Metric maintenance Gate

The main authoring command publishes the complete legacy and native semantic
surfaces. This narrower standalone command remains available for independently
checking or repairing only approved `BUSINESS` Metrics in DataHub's native `metric`
entity and its `metricUpstreams` / `metricRelationships` edges. It does not copy the
complete capability, permission, grain, fan-out, or query-policy JSON into another
DataHub custom property. `SUPPORT` operands remain checksum-bound execution facts
and are not searchable native Metric entities.

The workflow always rediscovers the current active manifest from the complete scoped
catalog. Completely ungoverned, base-ingested candidates may coexist outside that
manifest; a Dataset with even one partial `answervice.*` property is not silently
excluded. Every active member is also compared with live Trino before a shadow
projection is accepted.

Run the read-only check first:

```powershell
$nativeCheck = python infrastructure/database/datahub/author_native_metric_shadow.py `
  --check --serving-schema analytics_v4_3 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Native Metric shadow check failed.' }
```

Publication is a separate operation with the mutation-only DataHub identity. Both
the active catalog checksum and projection checksum from that exact check are
required, so a changed release cannot reuse an older receipt:

```powershell
python infrastructure/database/datahub/author_native_metric_shadow.py `
  --publish --serving-schema analytics_v4_3 `
  --expected-catalog-sha256 $nativeCheck.catalog_sha256 `
  --expected-projection-sha256 $nativeCheck.projection_sha256
if ($LASTEXITCODE -ne 0) { throw 'Native Metric shadow publication failed.' }
```

Finally, use the read-only identity for independent Rest.li and GraphQL read-back.
The GraphQL check verifies Metric identity plus exact Dataset, SchemaField, and Metric
edge membership rather than treating stored JSON alone as graph evidence:

```powershell
python infrastructure/database/datahub/author_native_metric_shadow.py `
  --verify --serving-schema analytics_v4_3 `
  --expected-catalog-sha256 $nativeCheck.catalog_sha256 `
  --expected-projection-sha256 $nativeCheck.projection_sha256
if ($LASTEXITCODE -ne 0) { throw 'Native Metric shadow read-back failed.' }
```

`SHADOW_READBACK_VERIFIED_NOT_ACTIVE` is intentionally not a runtime cutover state.
Native reader parity, permission/fan-out policy coverage, release approval, and the
same-release Backend/Trino/browser gates are still required before changing the
runtime source.

The Backend keeps the verified catalog snapshot and readiness receipt for the shared
`86400` second operational TTL. After a new semantic release reaches
`PUBLISHED_AND_VERIFIED`, recreate the Backend before routing analysis traffic to that
release so no process can retain the predecessor snapshot for the remainder of its TTL.

Pinned DataHub v1.7 exposes different authoritative fields across its read APIs.
GlossaryTerm status/lifecycle and editable field-term associations are verified from
Rest.li aspects. GraphQL independently verifies entity identity, owner, domain, the
dataset-level term set, and schema values; it returns null for the two field surfaces
above. The verifier never fills those nulls from a fixture or local JSON.
