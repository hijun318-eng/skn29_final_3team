# 내부업무매뉴얼 RAG 통합 경계

이 디렉터리는 `text-embedding-3-large:d1024`와 pgvector·BM25 Hybrid 검색을 저장소 구조에 맞춰 통합한 코드다. 승인 후보 내부업무매뉴얼 PDF와 월간 경영보고서 DOCX는 `data/rag/`에 포함하며, secret, `.env`, DB dump와 실행 증적은 포함하지 않는다.

## 현재 적용 상태

| 항목 | 값 |
|---|---|
| 구현 상태 | `INTEGRATED_RC` |
| 기술 Gate | `TECHNICALLY_VALIDATED` |
| 내부 HTTP | `AVAILABLE` |
| 제품 Tool 활성화 | `DISABLED` |
| 로컬 통합 | `LOCAL_DOCKER_VALIDATED` |
| P0/P1 완료 판정 영향 | 없음 |

`004_p2_contract_foundation.sql`은 Tool Registry, SQL·문서 Evidence 분리 계약,
요청 추적 필드와 문서 유효기간 필드를 준비한다. Registry의 검색 Tool은 migration 후에도
`enabled=false`, `approval_status=NOT_APPROVED`로 유지되며 MCP `tools/list`·`tools/call`이나
기존 backend router를 활성화하지 않는다.

2026-08-30 당시 통합 checkout에서 `text-embedding-3-large:d1024`, PDF 승인 후보 문서 17개·
363 chunk로 서명 검색→근거 제한 답변 E2E와 정상 서명·재전송·미등록 역할·만료 서명 4개
보안 경로를 실제 Docker에서 확인했다. 이 결과는 기술 후보 검증이며 제품 feature flag,
App Tool Registry, MCP `rag.answer` 또는 자동 Agent route를 승인하지 않는다.

## Embedding 후보 선택 원칙

`text-embedding-3-large:d1024`는 한국어를 포함한 비영어 검색 품질을 우선 확인하기 위한
후보다. OpenAI가 제공하는 `dimensions` 옵션으로 pgvector 계약은 1024차원에 고정한다.
공식 embedding 모델 목록에는 `text-embedding-3-small`과 `text-embedding-3-large`가
있으며 `text-embedding-3-medium`은 없으므로 런타임에서 거부한다.

`large`는 `small`보다 비용이 높으므로 운영 기본값으로 승인한 것이 아니다. 활성화 전 같은
한국어 Gold set, chunk와 Hybrid 검색 설정으로 recall, nDCG, 근거 적합도, 지연, 비용을
비교한다. 유의미한 품질 이점이 확인되지 않으면 `small:d1024`로 내리고 전 문서를 같은
revision으로 다시 적재한다. 모델 선택과 무관하게 `RAG_FEATURE_ENABLED=0`이 기본값이다.

참고: [OpenAI embedding 모델](https://developers.openai.com/api/docs/models/text-embedding-3-large),
[Embedding API의 dimensions 계약](https://developers.openai.com/api/reference/ruby/resources/embeddings/methods/create)

## 서비스 연동 기반

`src/rag/integration/`은 Backend Gateway와 Supervisor가 호출할 수 있는 비활성 통합 경계다.

| 구성 | 역할 |
|---|---|
| `EvidenceRouter` | 상위 오케스트레이터가 승인한 route·decision receipt만 실행 계획으로 변환 |
| `AnswerviceContextAdapter` | `request_id`, `trace_id`, 사용자, 역할, 기준일, 대화 ID 전달 |
| `PgToolRegistryRepository` | Tool 버전·승인·활성·허용 역할을 DB에서 읽기 |
| `EvidenceCoordinator` | Tool별 권한 확인, 부분 실패 처리, Evidence 유형 분리 |
| `LocalRagEvidenceAdapter` | 승인된 역할 매핑 후 OpenAI embedding 기반 검색 호출 |
| `InternalGuidelineCapabilityProbe` | 답변 생성 없이 승인 검색 결과의 release·evidence 식별자만 route receipt로 봉인 |
| `ApprovedSqlEvidenceAdapter` | 승인 SQL·G2 token만 기존 DataPlatform으로 실행 |
| `DevP2EvidenceBridge` | 최신 `dev RequestContext`와 통합 Coordinator 연결 |
| `McpJsonRpcDispatcher` | 네트워크 listener 없이 MCP `tools/list`·`tools/call` 계약 처리 |
| `InMemoryToolRateLimiter` | 단일 instance PoC 호출 제한, 운영 시 공유 저장소 필요 |

이 모듈은 검색 근거를 구조화할 뿐 답변 문장을 생성하지 않는다. Registry가 승인·활성화되지
않으면 호출을 차단하며, 역할 매핑도 담당자가 `approved=true`로 제공하기 전에는 실패한다.
현재 일반 분석 요청을 RAG로 임의 전환하지 않는다. 검색 전용 probe는 구현됐지만 production
registry와 `CapabilityEvidenceRouteResolver`에는 연결하지 않았으며, 제품 Tool 활성화와
0개·복수 매칭 사용자 계약을 검증한 뒤에만 자동 route Gate를 열 수 있다.
MCP dispatcher는 2025-06-18 Tool 계약 형식에 맞추되 transport endpoint는 열지 않는다.

## 저장소 경로

| 구분 | 경로 |
|---|---|
| 핵심 코드 | `src/rag/` |
| 설정 | `config/rag/` |
| DB migration·Compose fragment | `infrastructure/rag/` |
| 단위 테스트 | `tests/rag/` |
| 평가 입력 | `evals/testsets/rag/` |
| 검증 보고서 | `evals/reports/rag/` |
| 로컬 평가 실행 결과 | `evals/runs/rag/` (`gitignore`) |
| 검색 대상 문서 | `data/rag/manuals/` (PDF 17개, DOCX 24개) |

## 활성화 전 확인 순서

1. 별도 `rag` profile로 PostgreSQL·RAG API·답변 서비스를 기동한다.
2. `RAG_DB_PASSWORD`, `RAG_GATEWAY_HMAC_SECRET`, `OPENAI_API_KEY`를 저장소 밖에서 주입한다.
3. manifest의 41개 문서를 현재 embedding revision으로 적재하고 문서별 승인·역할·유효기간을 검증한다.
4. Backend Gateway의 health·HMAC·역할 매핑과 검색·답변 E2E를 같은 source revision에서 검증한다.
5. 업무 담당자 Gold 승인을 기록한 뒤에만 Registry와 `RAG_FEATURE_ENABLED`를 활성화한다.

## 로컬 입력 경로

| 환경변수 | 기본값 |
|---|---|
| `RAG_CONFIG_DIR` | `config/rag` |
| `RAG_MIGRATIONS_DIR` | `infrastructure/rag/db/init` |
| `RAG_MANUALS_DIR` | `data/rag/manuals` |
| `RAG_EMBEDDING_PROVIDER` | `openai` |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-large` |
| `OPENAI_EMBEDDING_DIMENSIONS` | `1024` |
| `OPENAI_EMBEDDING_ENDPOINT` | `https://api.openai.com/v1/embeddings` |
| `RAG_MODEL_PATH` | Qwen fallback를 명시적으로 빌드할 때만 사용 |
| `RAG_ANSWER_ENDPOINT` | `https://api.openai.com/v1/chat/completions` |
| `RAG_ANSWER_MODEL` | `gpt-5.4-mini` |
| `RAG_DEVICE` | `cpu` |
| `RAG_SMOKE_QUERIES_PATH` | `evals/testsets/rag/smoke_queries.json` |
| `RAG_EVIDENCE_DIR` | `evals/runs/rag` |
| `RAG_BACKUP_DIR` | `backups/rag` |

기본 적재는 `config/rag/corpus_manifest.json`이 `MANUAL` 또는 `INTERNAL_REPORT`로 선언한 PDF·DOCX만 사용한다. v2 manifest는 하위 디렉터리를 포함한 모든 지원 문서, 문서 ID, source version, owner, period·department, 명시 역할과 원본 bytes SHA-256을 exact-match하며 `REFERENCE`는 제외한다. 이 저장소에서 checksum과 접근 정책까지 봉인된 included 문서는 curated publication receipt로 간주해 staging에 `APPROVED`·`VALID`를 명시하며, parser를 직접 호출한 임의 문서는 기본 `NOT_APPROVED`·`UNRESOLVED`라 release에 들어갈 수 없다. release는 PDF·DOCX parser 계약과 chunker 설정 hash가 같은 byte-identical 문서만 이전 승인 상태와 chunk를 승계한다. 적재 후에도 문서별 `approval_status`, 역할 범위, 유효기간 Gate를 모두 통과한 문서만 검색·목록·원문 경로에 노출된다.

## DOCX 무손실 우선 수집 계약

DOCX는 ZIP 기반 OPC package를 immutable bytes 한 번으로 읽고 checksum과 같은 bytes를 파싱한다. 본문 문단과 표를 document order로 교차 유지하며 heading/style, 번호 목록, table row·column·`gridSpan`·`vMerge`, section, header/footer, footnote/endnote, comment body·anchor·reference, hyperlink target, 이미지 alt text와 media SHA-256을 구조 표식과 함께 보존한다. heading은 현재 제목과 최대 두 ancestor의 경로를 section context로 유지한다. 긴 표는 원본 cell marker를 한 번만 유지하면서 각 chunk에 table identity와 첫 행 header context·digest를 반복한다. layout engine 없이 실제 페이지를 추정하지 않으며 `w:br type=page`와 `lastRenderedPageBreak`만 `explicit-segment` locator로 기록한다.

DB에 저장하고 retrieval evidence로 반환하는 `chunk.content`는 추출 원문을 유지한다. dense embedding 입력만 별도 결정론적 계약으로 `document title/version/document_type/owner_team + section path + chunk.content`를 조합하며, `role_scope`는 입력에 넣지 않고 DB 접근 필터로만 사용한다. 이 변환 버전은 processing profile hash에 포함되고 설정된 context 한도를 넘으면 조용히 자르지 않고 ingestion을 실패시킨다. 현재 embedding API에 없는 token-level late pooling은 사용하지 않는다.

암호화 entry, macro, OLE·chart·SmartArt·ActiveX처럼 현재 보존할 수 없는 embedded part, path traversal, duplicate part, ZIP bomb, DTD/entity, 누락 relationship, 허용되지 않은 외부 relationship은 fail-closed다. comment body·range·reference identity가 맞지 않아도 실패한다. 외부 hyperlink는 가져오지 않고 target과 diagnostic만 남기며, 이미지 OCR을 수행하지 못한 경우 media digest와 alt-text 누락 diagnostic을 남긴다. `INTERNAL_REPORT`는 manifest가 source version·period·department·role scope를 명시해야 하고 source/parser 계약, content unit·chunk count, 비음수 구조 receipt가 맞아야 한다. 표·header·footer가 반드시 존재한다고 가정하지 않으며, 이번 24개 corpus의 형식별 exact coverage는 별도 audit test로 고정한다.

원문 조회는 `/v1/documents/{manual_id}/source`가 checksum을 재검증한 뒤 PDF 또는 DOCX media type으로 응답한다. 기존 `/source.pdf`는 PDF에만 유지되며 DOCX bytes를 PDF로 잘못 표시하지 않는다.

답변 입력은 질문·intent·서버 소유 evidence를 하나의 canonical JSON object로 직렬화한다. 질문이나 승인 문서 본문에 과거 prompt delimiter와 같은 문자열이 들어 있어도 명령·경계로 재해석하지 않는다. `config/rag/answer.json`의 전체 context에서 system·질문·출력 예약분을 먼저 차감하고, 남은 예산에는 완전한 evidence block만 검색 순서대로 넣는다. 제외 개수와 보수적 UTF-8 token 상한 사용량은 `context_receipt`와 `limitations`에 기록되며, 로컬 answer endpoint도 한도를 넘은 근거를 조용히 자르지 않고 fail-closed 처리한다.

현재 candidate image에는 reranker dependency/release가 포함되지 않는다. `RAG_RERANKER_PATH` 또는 과거 `RERANKER_PATH`를 설정하면 startup이 실패하며 `HYBRID_RERANK`도 silent fallback 없이 거부된다.

`RAG_GATEWAY_HMAC_SECRET`은 32자 이상이어야 하며 저장소에 기록하지 않는다.
환경변수 이름과 컨테이너 경로 예시는 `infrastructure/rag/.env.example`을 사용하되 `REQUIRED` 값을 실제 운영 secret으로 교체해 로컬 `.env` 또는 secret manager에만 둔다.

HTTP 검색 요청의 `X-Request-Signature`는 질문만이 아니라 다음 JSON 전체를 key 정렬·공백 없는 UTF-8 문자열로 만든 뒤 서명한다. `recent_utterances`와 `selected_document_ids`를 서명 후 바꾸면 401로 차단된다.

```json
{
  "query": "그 다음은?",
  "recent_utterances": ["객실 소음 민원"],
  "selected_document_ids": ["SOP-ROOM-003"],
  "top_k": 3
}
```

서명 입력 생성은 `src.rag.request_auth.canonical_search_request`를 사용한다. 최근 대화는 최대 3개, 선택 문서는 최대 10개이며 검색·감사 hash에도 함께 반영된다.

저장소 루트에서 실행한다.

Windows와 NVIDIA CUDA 12.4 환경에서는 저장소 내부에 로컬 실행 환경을 만든다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r infrastructure\rag\requirements-cuda.txt
.\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Qwen/Qwen3-Embedding-0.6B', revision='97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3', local_dir='models/Qwen3-Embedding-0.6B')"
```

`.venv`와 `models/Qwen3-Embedding-0.6B`는 로컬 실행 자산이며 Git에 포함하지 않는다. CPU 검증은 `infrastructure/rag/requirements.txt`를 설치하면 되며, `RAG_DEVICE=auto`가 CUDA 사용 가능 여부에 따라 `cuda` 또는 `cpu`를 선택한다. 특정 장치를 강제할 때만 `RAG_DEVICE=cuda` 또는 `RAG_DEVICE=cpu`를 설정한다.

```powershell
.\.venv\Scripts\python.exe -m src.rag migrate
.\.venv\Scripts\python.exe -m src.rag status
.\.venv\Scripts\python.exe -m src.rag search "객실 소음 대응 절차" --role MANAGER --top-k 3
```

## 베이스라인 모델 비교 및 답변 평가

RAG 성능 보완 및 베이스라인 모델 비교가 별도 실험 트랙으로 추가되었다. `config/rag/benchmark.json`과 `config/rag/embedding_models.json`을 사용하여 다음 실행 순서를 따른다.

```powershell
# 베이스라인 평가
python -m src.rag benchmark --config config/rag/benchmark.json --split dev
python -m src.rag benchmark --config config/rag/benchmark.json --split test

# 단일 답변 테스트 및 답변 평가
python -m src.rag answer "객실 소음과 냉난방 고장이 동시에 발생하면 어떻게 대응하나요?" --role MANAGER
python -m src.rag evaluate-answer evals/testsets/rag/answer_gold_v1.jsonl
```

비교는 `Qwen3-Embedding-0.6B`, `BGE-M3`, `multilingual-e5-large`, `lexical_pgtrgm` 간에 진행된다.

## 남은 위험

기존 결과보고서의 운영 리스크는 그대로 유지한다. secret manager·HTTPS·실제 gateway·기존 인증 연동, 담당자 승인 질문 80개 이상, 30분 이상 목표 부하, DB·GPU·model 장애와 RPO·RTO 훈련, 주차·개인정보·안전 실패 3건 재검수가 필요하다. RAG 답변 생성은 별도 실험 트랙에서 검증 중이나, 운영 환경에는 아직 적용(활성화)되지 않았다.


## Manual/Policy RAG 서비스와 E2E

보조 RAG는 분석 Core의 G1/G2/G3 또는 Trino 경로를 대체하지 않는다. `rag-api`는 내부 매뉴얼 검색과 근거 답변만 담당하며, 검색 결과의 `evidence_id` 밖 인용은 E2E에서 실패 처리한다.

1. `infrastructure/rag/.env.example`의 RAG DB, 모델 경로, 답변 endpoint, HMAC secret을 채운다.
2. 승인 전 candidate 검증은 `docker compose --profile rag-candidate up -d --build rag-postgres rag-api`로 서비스와 pgvector를 시작한다.
3. 문서 ingestion을 수행한 뒤 `docker compose --profile rag-e2e run --rm rag-e2e`를 실행한다.
4. 결과 JSON은 `evals/runs/rag/manual_rag_e2e_<request_id>.json`에 저장한다.

E2E는 `/health/live` → `/health/ready` → signed search → evidence-bound answer 순서로 검증한다. 실제 모델·pgvector·답변 endpoint가 준비되지 않은 상태에서는 `SUCCEEDED`로 표시하지 않는다.

## Portable self-contained E2E

Run the complete local Manual/Policy RAG stack without an external LLM API key:

```powershell
python infrastructure/rag/bootstrap_portable_e2e.py --download-model
```

The bootstrap downloads `Qwen/Qwen3-Embedding-0.6B` only when it is absent, prepares `tmp/rag-build-context`, starts `rag-postgres`, `rag-local-answer`, `rag-api`, and `rag-e2e`, then exits successfully only when the E2E contract succeeds. The portable profile explicitly injects the deterministic local answer service and does not use facts outside the retrieved evidence. The regular RAG profile uses the configured OpenAI answer endpoint.

`RAG_ANSWER_ENDPOINT`는 HTTPS host allowlist를 통과해야 한다. 평문 HTTP는 `config/rag/answer.json`의 `allowed_http_hosts`에 명시된 내부 service hostname만 허용되며 redirect와 환경 proxy는 사용하지 않는다. 모델은 strict JSON schema로 원문 claim을 선택하고 최종 답변·인용·문서 metadata는 서버가 검색 evidence와 다시 대조해 봉인한다.
