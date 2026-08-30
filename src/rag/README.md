# 내부업무매뉴얼 RAG 통합 경계

이 디렉터리는 `text-embedding-3-large:d1024`와 pgvector·BM25 Hybrid 검색을 저장소 구조에 맞춰 통합한 코드다. 합성 내부업무매뉴얼 PDF는 `data/rag/`에 포함하며, secret, `.env`, DB dump와 실행 증적은 포함하지 않는다.

## 현재 적용 상태

| 항목 | 값 |
|---|---|
| 구현 상태 | `INTEGRATED_CANDIDATE` |
| P2 Gate | `NOT_APPROVED` |
| Tool 등록 | `DISABLED` |
| 운영 통합 | `DEFAULT_OFF` |
| P0/P1 완료 판정 영향 | 없음 |

`004_p2_contract_foundation.sql`은 Tool Registry, SQL·문서 Evidence 분리 계약,
요청 추적 필드와 문서 유효기간 필드를 준비한다. Registry의 검색 Tool은 migration 후에도
`enabled=false`, `approval_status=NOT_APPROVED`로 유지되며 MCP `tools/list`·`tools/call`이나
기존 backend router를 활성화하지 않는다.

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
| `ApprovedSqlEvidenceAdapter` | 승인 SQL·G2 token만 기존 DataPlatform으로 실행 |
| `DevP2EvidenceBridge` | 최신 `dev RequestContext`와 통합 Coordinator 연결 |
| `McpJsonRpcDispatcher` | 네트워크 listener 없이 MCP `tools/list`·`tools/call` 계약 처리 |
| `InMemoryToolRateLimiter` | 단일 instance PoC 호출 제한, 운영 시 공유 저장소 필요 |

이 모듈은 검색 근거를 구조화할 뿐 답변 문장을 생성하지 않는다. Registry가 승인·활성화되지
않으면 호출을 차단하며, 역할 매핑도 담당자가 `approved=true`로 제공하기 전에는 실패한다.
현재 일반 분석 요청을 RAG로 임의 전환하지 않으며, 명시적으로 승인된 내부 지침 capability에서만 호출한다.
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
| 검색 대상 매뉴얼 | `data/rag/manuals/` (개별 PDF 17개) |

## 활성화 전 확인 순서

1. 별도 `rag` profile로 PostgreSQL·RAG API·답변 서비스를 기동한다.
2. `RAG_DB_PASSWORD`, `RAG_GATEWAY_HMAC_SECRET`, `OPENAI_API_KEY`를 저장소 밖에서 주입한다.
3. 17개 문서를 현재 embedding revision으로 적재하고 문서별 승인·역할·유효기간을 검증한다.
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
| `RAG_RERANKER_PATH` | `models/bge-reranker-v2-m3` |
| `RAG_ANSWER_ENDPOINT` | `http://rag-local-answer:8001/v1/chat/completions` |
| `RAG_ANSWER_MODEL` | `rag-local-answer-v2` |
| `RAG_DEVICE` | `cpu` |
| `RAG_SMOKE_QUERIES_PATH` | `evals/testsets/rag/smoke_queries.json` |
| `RAG_EVIDENCE_DIR` | `evals/runs/rag` |
| `RAG_BACKUP_DIR` | `backups/rag` |

기본 적재는 `data/rag/manuals`의 개별 PDF 17개만 사용한다. 적재 후에도 문서별 `approval_status`, 역할 범위, 유효기간 Gate를 모두 통과한 문서만 검색·목록·PDF 원문 경로에 노출된다.

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
2. 승인 전 candidate 검증은 `docker compose --profile rag-candidate up -d --build rag-postgres rag-api rag-local-answer`로 서비스와 pgvector를 시작한다.
3. 문서 ingestion을 수행한 뒤 `docker compose --profile rag-e2e run --rm rag-e2e`를 실행한다.
4. 결과 JSON은 `evals/runs/rag/manual_rag_e2e_<request_id>.json`에 저장한다.

E2E는 `/health/live` → `/health/ready` → signed search → evidence-bound answer 순서로 검증한다. 실제 모델·pgvector·답변 endpoint가 준비되지 않은 상태에서는 `SUCCEEDED`로 표시하지 않는다.

## Portable self-contained E2E

Run the complete local Manual/Policy RAG stack without an external LLM API key:

```powershell
python infrastructure/rag/bootstrap_portable_e2e.py --download-model
```

The bootstrap downloads `Qwen/Qwen3-Embedding-0.6B` only when it is absent, prepares `tmp/rag-build-context`, starts `rag-postgres`, `rag-local-answer`, `rag-api`, and `rag-e2e`, then exits successfully only when the E2E contract succeeds. The local answer service is deterministic and evidence-bound; it does not use facts outside the retrieved evidence. Override `RAG_ANSWER_ENDPOINT`, `RAG_ANSWER_MODEL`, and `RAG_ANSWER_API_KEY` only when connecting a production OpenAI-compatible endpoint.
