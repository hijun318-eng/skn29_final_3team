# DataHub dataset semantic search 운영 절차

`compose.semantic-search.yml`은 DataHub v1.7.0을 Elasticsearch 8.18.2와
로컬 Ollama에 연결하는 운영 overlay다. 기본 `compose.consumer.yml`의 OpenSearch는
`legacy-search` rollback profile에서만 실행된다. OpenSearch가 healthy하다는 사실은
semantic search 완료 증거가 아니다.

고정한 upstream 계약은 다음과 같다.

- DataHub release: `v1.7.0`, commit
  `7f81ccbfe27b9acc947f5f600fcf9ddb72138a80`
- [DataHub v1.7.0 semantic 설정](https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/metadata-service/configuration/src/main/resources/application.yaml#L651-L744)
- [SemanticContent PDL](https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/metadata-models/src/main/pegasus/com/linkedin/common/SemanticContent.pdl)
- [EmbeddingModelData PDL](https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/metadata-models/src/main/pegasus/com/linkedin/common/EmbeddingModelData.pdl)
- [EmbeddingChunk PDL](https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/metadata-models/src/main/pegasus/com/linkedin/common/EmbeddingChunk.pdl)

## 실제 데이터 흐름

`SystemUpdate`는 `datasetindex_v2_semantic` mapping을 만들고 기존 metadata를
새 index에 복사하지만 dataset embedding을 생성하지 않는다. 운영 완료 경로는 다음과
같다.

1. DataHub GMS와 Elasticsearch/Ollama가 준비된다.
2. `datahub-ingestion`이 `/recipes/*.runtime.yml`을 런타임에 탐색하여 전부 실행한다.
   코드나 Compose에 dataset FQN 또는 6개 파일 목록을 복사하지 않는다.
3. `dataset-semantic-content-bootstrap`이 GraphQL로 현재 active dataset, schema field,
   domain, glossary term 속성을 다시 탐색한다.
4. producer가 승인된 Ollama artifact digest를 확인하고 metadata text를 batch
   embedding한다.
5. producer가 DataHub v1.7 Rest.li
   `/aspects?action=ingestProposal`에 `semanticContent` MCP를 동기 발행한다.
6. DataHub readback과 active Elasticsearch index에서 동일 URN, modelVersion,
   text, chunk 수, float32 vector fingerprint와 768차원을 확인한 뒤에만 one-shot이
   성공한다.
7. DataHub Actions와 frontend는 이 one-shot의 성공 후 시작된다.

따라서 mapping 생성이나 mock test만으로 운영 완료를 주장할 수 없다.

## 최초 clean start

Repository 밖에 deployment environment를 만들고 모든 `CHANGE_ME_`·`REQUIRED_` 값을
교체한다. 저장소 로컬 `.env`는 Compose와 script 모두 묵시적으로 읽지 않는다. Ollama
model tag와 전체 artifact digest는 둘 다 필수다.

GMS는 `METADATA_SERVICE_AUTH_ENABLED=true`와 REST authorization을 강제하고
PKCS#12 server certificate로 8443 HTTPS만 제공한다. Backend·readiness·검증기는
`DATAHUB_READ_API_TOKEN`과 그 service actor를 사용하고, ingestion·authoring·publisher·
semantic producer는 별도 `DATAHUB_PUBLISH_API_TOKEN`과 actor를 사용한다. Backend
container에는 publish credential을 주입하지 않는다. 모든 호출자는
`DATAHUB_TLS_CA_FILE`로 peer를 검증하며 GMS keystore·CA·Java truststore와 secret은
repository 밖 절대 경로에서 주입한다. 인증 없는 `/api/graphql`, Rest.li, OpenAPI
mutation은 성공 경로가 아니다.
이 계약은 pinned v1.7.0의
[authentication 설정](https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/metadata-service/configuration/src/main/resources/application.yaml#L15-L81)과
[REST sink token/CA 전달](https://github.com/datahub-project/datahub/blob/7f81ccbfe27b9acc947f5f600fcf9ddb72138a80/metadata-ingestion/src/datahub/ingestion/sink/datahub_rest.py#L276-L290)을 따른다.

```powershell
$deploymentDirectory = Join-Path $env:LOCALAPPDATA 'Answervice\deployment'
New-Item -ItemType Directory -Force -Path $deploymentDirectory | Out-Null
$deploymentEnv = Join-Path $deploymentDirectory 'answervice.env'
Copy-Item infrastructure/database/.env.example $deploymentEnv
# 외부 파일의 placeholder와 PKI/password database 절대 경로를 provisioning한다.
powershell -NoProfile -ExecutionPolicy Bypass `
  -File infrastructure/database/scripts/start.ps1 `
  -EnvFilePath $deploymentEnv -Stage Core
```

`Core`는 source read-only 계정, Trino, 인증된 GMS와 loopback UI까지만 준비하고
`DATABASE_CORE_READY|next=PROVISION_DATAHUB_SERVICE_TOKENS`를 출력한다. 이 단계에는
아직 존재할 수 없는 PAT consumer가 없으므로 clean MySQL에서도 순환 의존이 생기지 않는다.

운영자는 DataHub UI/OIDC에서 서로 다른 read/publish service actor를 만들고, read actor에는
catalog 조회만, publish actor에는 승인된 metadata mutation만 허용하는 정책을 연결한다.
두 PAT와 actor URN을 외부 `$deploymentEnv`에 기록한 뒤 Catalog 단계를 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File infrastructure/database/scripts/start.ps1 `
  -EnvFilePath $deploymentEnv -Stage Catalog
```

`Catalog`는 두 token이 서로 다르고 각 token의 실제 `me.corpUser.urn`이 선언 actor와
일치하는지 먼저 확인한다. 이후 runtime recipe와 semantic producer를 순서대로 실행하며,
이를 건너뛰거나 dataset·권한이 불완전하면 성공 marker 없이 fail-close한다.

애플리케이션까지 기동할 때도 semantic overlay를 포함한다. Root `compose.yml`은
`compose.ingestion.yml`을 include하므로 같은 dependency DAG를 사용한다.

직접 `docker compose up`으로 단계를 우회하지 않는다. `start.ps1 -Stage Catalog`가 Core
실행 상태, service identity, ingestion, semantic readback과 UI/Actions dependency를 한
DAG에서 검증한다.

Overlay 없는 `full` 기동은 OpenSearch rollback 경로이며 production semantic 완료
경로가 아니다.

## metadata 변경 후 refresh

Source schema, description, domain 또는 glossary term이 바뀌면 base ingestion과
embedding을 같은 작업에서 갱신한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File infrastructure/database/datahub/ingest_runtime_catalog.ps1 `
  -EnvFilePath $deploymentEnv -Apply
```

이 스크립트는 모든 현재 `*.runtime.yml`을 실행한 다음
`dataset-semantic-content-bootstrap`을 다시 실행한다. producer는 다른 embedding model
key를 보존하고 현재 `nomic_embed_text` 값만 idempotent하게 upsert한다. 중간 실패는
성공으로 변환하지 않는다.

## image와 model artifact 고정

Compose image는 multi-platform manifest digest까지 고정한다.

- Elasticsearch 8.18.2:
  `sha256:7506a97309af9fa3221ce1d60068223aabb613afe96c1d3a0add5f6bb0e0b61c`
- Ollama 0.6.8:
  `sha256:50ab2378567a62b811a2967759dd91f254864c3495cbe50576bd8a85bc6edd56`
- Semantic producer Python 3.13.7 slim-bookworm:
  `sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d`
- `nomic-embed-text` registry manifest:
  `sha256:0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`

마지막 값은 2026-08-16에 image pull 없이 Ollama registry 원문 manifest의 SHA256을
계산해 확인한 값이다. Model tag는 mutable하므로 producer와 verifier가 `/api/tags`의
실제 전체 digest를 매번 비교한다. digest가 없거나 다르면 결과는 완료가 아니다.

## fail-close live 검증

운영자가 실제 ingest된 dataset metadata에서 검색어를 선택한 뒤 실행한다. 특정 시연
질문을 fallback으로 제공하지 않는다.

```powershell
$digestLine = Get-Content -LiteralPath $deploymentEnv |
  Where-Object { $_.StartsWith('OLLAMA_EMBEDDING_MODEL_DIGEST=') } |
  Select-Object -First 1
if (-not $digestLine) { throw 'OLLAMA_EMBEDDING_MODEL_DIGEST is required.' }
$env:OLLAMA_EMBEDDING_MODEL_DIGEST = $digestLine.Split('=', 2)[1]
python infrastructure/database/datahub/verify_semantic_search.py `
  --probe-query '<live DataHub metadata에서 선택한 검색어>'
```

`VERIFIED`에는 다음 증거가 모두 필요하다.

- GMS와 semantic Elasticsearch가 동일 Compose project/network이며 GMS effective
  environment가 그 Elasticsearch DNS를 가리킨다.
- Elasticsearch가 8.18 이상이고 OpenSearch가 아니며 active
  `datasetindex_v2_semantic` mapping이 공식 768-D cosine contract와 일치한다.
- reindex task가 끝났고 vector가 채워진 document가 있다.
- 고정 DataHub version/commit의 `semanticSearchAcrossEntities`가 DATASET URN을
  반환하고, 반환한 모든 URN이 같은 active index의 vector-backed document다.
- Ollama가 승인된 model digest와 finite 768-D query embedding을 반환한다.

Timeout, 빈 결과, malformed response, version/commit/model/digest/mapping 불일치,
active reindex, 빈 vector population, URN binding 불일치는 모두
`CONFIGURED_NOT_VERIFIED`와 exit code `2`다.

## 테스트와 실제 환경의 경계

`MockTransport` 테스트는 pagination, MCP wire shape, float32 readback, digest/dimension
거부와 cross-system binding 계약을 검증할 뿐 live 완료 증거가 아니다. 준비된 local
stack에서 mutation을 명시적으로 허용할 때만 positive smoke를 opt-in한다.

```powershell
$env:RUN_LIVE_DATAHUB_SEMANTIC_PRODUCER_SMOKE = '1'
$env:OLLAMA_EMBEDDING_MODEL = 'nomic-embed-text'
$env:OLLAMA_EMBEDDING_MODEL_DIGEST = '<approved full sha256>'
python -m pytest -p no:cacheprovider `
  tests/data/test_dataset_semantic_content_producer.py -q
```

Opt-in하지 않은 환경에서는 이 live smoke가 skip되는 것이 정상이다. Opt-in한 뒤
서비스나 digest가 준비되지 않았다면 skip하지 않고 실패한다.
