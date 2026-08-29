# Answervice RAG BM25·Reranker 객관적 평가 및 최종 판정

| 항목 | 내용 |
|---|---|
| 문서 설명 | RAG BM25·reranker 객관적 평가와 운영 적용 판정 |
| 문서 분류 | 일반 문서 |
| 버전 | v1.1 |
| 문서 기준일 | 2026-08-29 18:03 |
| 작성·수정 | Codex |
| 평가 대상 | OpenAI embedding + pgvector + BM25 + reranker |
| 데이터 | 승인 문서 17개, chunk/vector 363개 |
| 평가 질문 | 한국어 96개 |
| 평가 상태 | `ENGINEERING_REVIEW_CANDIDATE_NOT_BUSINESS_GOLD` |
| 최종 판정 | `CONDITIONAL_GO` |

## 1. 최종 결론

| 구성 요소 | 최종 판단 | 근거 |
|---|---|---|
| 임베딩 | `text-embedding-3-large`, 1,024차원 유지 | 기존 동일 코퍼스 비교에서 large hybrid가 최상 |
| 1차 검색 | pgvector Dense + BM25 Hybrid 유지 | BM25-only보다 우수하고 어려운 질문의 Recall@5를 보완 |
| Hybrid 가중치 | Dense 0.65 / BM25 0.35 잠정 유지 | 새 96문항에서 Dense 대비 전체 nDCG@5 우위는 통계적으로 확정되지 않음 |
| 2차 재정렬 | `BAAI/bge-reranker-v2-m3` 기술 후보 확정 | 사전 정의한 정확도·신뢰구간·지연·오류 기준을 모두 통과 |
| 경량 재정렬 | mMARCO multilingual MiniLM 미채택 | 빠르지만 개선 신뢰구간 하한이 0 이하 |
| Jina 재정렬 | 운영 후보 제외 | 공개 모델 라이선스가 `CC-BY-NC-4.0` |
| 즉시 운영 활성화 | 보류 | 업무 담당자 Gold 정답과 통합 Docker E2E가 아직 없음 |

핵심 판정은 다음과 같다.

> 현재 운영 기준은 OpenAI large + pgvector/BM25 Hybrid다. BGE reranker는 기술적으로 채택할 근거가 충분하지만, 업무 담당자 Gold 평가와 장애 fallback을 통과한 뒤 기능 플래그로 활성화해야 한다.

## 2. 심사 대응용 평가 설계

### 2.1 질문 구성

| 구분 | 수량 | 설명 |
|---|---:|---|
| 단일 업무 도메인 | 80 | 16개 업무 문서별 5개 질문 |
| 교차 도메인 | 16 | 두 문서를 함께 찾아야 하는 비교·복합 정책 질문 |
| 표준 난이도 | 64 | 명시적 업무 표현 중심 |
| 고난도 | 32 | 후속 질문, 비교, 모호한 현장 표현 포함 |
| 합계 | 96 | 한국어 질문 |

질문 유형은 `PROCEDURE`, `CRITERIA`, `IMMEDIATE`, `POLICY`, `RECORD`, `FOLLOW_UP`, `COMPARE`, `MULTI_POLICY`를 포함한다.

현재 질문셋은 개발자가 작성한 평가 후보이며 업무 담당자가 승인한 Gold가 아니다. 따라서 이 결과는 기술 후보 선택에는 사용할 수 있지만 최종 업무 의미 정확도 승인에는 사용할 수 없다.

### 2.2 공정성 통제

| 통제 항목 | 적용 내용 |
|---|---|
| 동일 질문 | 모든 시스템에 같은 96개 질문 사용 |
| 동일 코퍼스 | 문서 17개, vector 363개 고정 |
| 동일 후보군 | reranker 모두 같은 Hybrid Top-20 chunk 사용 |
| 정답 강제 삽입 | 사용하지 않음 |
| 관련성 정의 | 문서 ID 기준 이진 관련성 |
| 평가 단위 | 문서 중복 제거 후 순위 평가 |
| 주 지표 | nDCG@5 |
| 보조 지표 | Recall@1·3·5·10, Hit@K, MRR@10, MAP@10 |
| 통계 검정 | paired bootstrap 10,000회, seed `20260829` |
| 모델 재현성 | Hugging Face commit SHA 고정 |

Sentence Transformers 공식 evaluator도 reranking 평가에서 MRR, nDCG, MAP을 사용하고, 실제 검색과 유사한 후보군을 평가하도록 설명한다. 본 평가는 이 원칙에 맞춰 정답 문서를 후보군에 강제로 넣지 않았다.

### 2.3 사전 합격 기준

모델 결과를 본 뒤 기준을 바꾸지 않도록 아래 조건을 추론 전에 고정했다.

| 판정 항목 | 합격 기준 |
|---|---:|
| nDCG@5 개선 | Hybrid 대비 `+0.0200` 이상 |
| 통계적 개선 | nDCG@5 차이의 95% CI 하한 `> 0` |
| Recall@5 회귀 | `-0.0100` 이내 |
| GPU P95 | `300ms` 이하 |
| 실행 오류 | 0건 |

## 3. 후보군 품질

| 지표 | 결과 |
|---|---:|
| 질문 수 | 96 |
| 질문당 후보 chunk | 20 |
| 기대 문서를 하나 이상 포함한 질문 | 95/96, 98.96% |
| 기대 문서를 모두 포함한 질문 | 95/96, 98.96% |
| 기대 문서 라벨 포괄률 | 111/112, 99.11% |
| 검색 평균 | 471.15ms |
| 검색 P50 | 370.11ms |
| 검색 P95 | 1,087.87ms |

누락 질문은 `Q003 여러 부서에 걸친 업무는 어떻게 인계해야 해?`이며 기대 문서는 공통 업무 문서다. reranker는 후보에 없는 문서를 복구할 수 없으므로 이 1건은 1차 검색 개선 대상으로 남긴다.

## 4. BM25 적정성 평가

### 4.1 기존 80문항 전체검색 A/B

아래 결과는 동일 문서, 동일 질문, 동일 OpenAI large embedding에서 Dense와 Hybrid를 전체 검색 경로로 비교한 기존 실측이다.

| 지표 | Dense | Hybrid 0.65/0.35 | 차이 |
|---|---:|---:|---:|
| Recall@1 | 0.66 | 0.68 | +0.02 |
| Recall@3 | 0.86 | 0.91 | +0.05 |
| Recall@5 | 0.94 | 0.96 | +0.02 |
| MRR | 0.77 | 0.80 | +0.03 |
| nDCG@5 | 0.81 | 0.84 | +0.03 |
| 고난도 Recall@5 | 0.93 | 0.98 | +0.05 |

이 결과는 BM25 결합 방향을 지지하지만 질문이 80개이고 paired 신뢰구간이 없으므로 단독 확정 근거로 사용하지 않는다.

### 4.2 새 96문항 고정 후보군 절제실험

같은 Hybrid Top-20 후보를 Dense 점수, BM25 점수, 기존 Hybrid 순위로 각각 재정렬했다. 이는 점수 기여도를 분리하는 실험이며 Dense-only 또는 BM25-only가 원래 Top-20 밖에서 가져올 후보는 관찰하지 못한다.

| 시스템 | Recall@1 | Recall@3 | Recall@5 | nDCG@5 | MRR@10 |
|---|---:|---:|---:|---:|---:|
| Dense-only | 0.6771 | 0.8802 | 0.9323 | 0.8445 | 0.8345 |
| BM25-only | 0.4948 | 0.7500 | 0.8958 | 0.7236 | 0.6925 |
| Hybrid 0.65/0.35 | 0.6771 | 0.8906 | 0.9531 | 0.8521 | 0.8378 |

| 비교 | 평균 차이 | 95% CI | 판정 |
|---|---:|---:|---|
| Hybrid - Dense nDCG@5 | +0.0076 | -0.0413 ~ +0.0593 | 통계적 우위 미확정 |
| Hybrid - Dense MRR@10 | +0.0034 | -0.0543 ~ +0.0625 | 통계적 우위 미확정 |
| Hybrid - BM25 nDCG@5 | +0.1285 | +0.0817 ~ +0.1788 | Hybrid 우위 |
| Hybrid - BM25 MRR@10 | +0.1454 | +0.0960 ~ +0.1980 | Hybrid 우위 |

고난도 Recall@5는 Dense `0.8594`에서 Hybrid `0.9219`로 `+6.25%p` 증가했다. 교차 도메인 Recall@5도 Dense `0.8438`에서 Hybrid `0.9063`으로 `+6.25%p` 증가했다.

BM25 최종 판정은 `보조 검색 유지, BM25-only 거부, 가중치 최적화 미완료`다. 전체 평균 우위는 새 표본에서 통계적으로 확정되지 않았으므로 0.35를 최적값이라고 주장하지 않는다.

## 5. Reranker 모델 비교

### 5.1 전체 결과

| 시스템 | Recall@1 | Recall@3 | Recall@5 | nDCG@5 | MRR@10 |
|---|---:|---:|---:|---:|---:|
| Hybrid baseline | 0.6771 | 0.8906 | 0.9531 | 0.8521 | 0.8378 |
| BGE reranker v2-m3 | 0.7865 | 0.9219 | 0.9844 | 0.9204 | 0.9118 |
| mMARCO multilingual MiniLM | 0.7188 | 0.9063 | 0.9844 | 0.8888 | 0.8681 |

### 5.2 합격 기준 판정

| 항목 | BGE v2-m3 | MiniLM |
|---|---:|---:|
| nDCG@5 개선 | +0.0683, PASS | +0.0366, PASS |
| nDCG@5 95% CI | +0.0201 ~ +0.1178, PASS | -0.0111 ~ +0.0842, FAIL |
| Recall@5 변화 | +0.0313, PASS | +0.0313, PASS |
| GPU P95 | 154.69ms, PASS | 78.86ms, PASS |
| 오류 | 0, PASS | 0, PASS |
| 최종 | 적격 | 부적격 |

### 5.3 BGE 세부 결과

| 항목 | 결과 |
|---|---:|
| paired MRR 승/동률/패 | 20 / 69 / 7 |
| MRR@10 개선 | +0.0740 |
| MRR@10 개선 95% CI | +0.0144 ~ +0.1332 |
| 고난도 Recall@5 | 0.9844 |
| 고난도 nDCG@5 | 0.8870 |
| 교차 도메인 Recall@5 | 0.9688 |
| 교차 도메인 nDCG@5 | 0.8639 |
| 캐시 후 모델 로드 | 9.98초 |
| 첫 다운로드 포함 로드 | 179.89초 |
| 평균 재정렬 지연 | 132.50ms |
| P95 재정렬 지연 | 154.69ms |
| 최대 재정렬 지연 | 172.88ms |
| 처리량 | 150.95 pair/s |
| peak VRAM | 1.182GB |
| 모델 revision | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |

BGE는 전체 기준을 통과했지만 교차 도메인 nDCG@1은 baseline `0.8750`에서 `0.8125`로 낮아졌고 MRR@10도 `0.9271`에서 `0.9063`으로 낮아졌다. 반면 교차 도메인 Recall@5와 nDCG@5는 개선됐다. 비교 답변은 두 문서를 함께 사용하므로 Top-5 개선이 유효하지만, 업무 Gold 평가에서 이 회귀를 별도 Gate로 확인해야 한다.

### 5.4 다른 후보를 채택하지 않은 이유

| 후보 | 제외 이유 |
|---|---|
| mMARCO MiniLM | 0.1B 규모, P95 78.86ms, VRAM 0.274GB로 효율적이나 nDCG@5 개선 CI가 0을 포함 |
| Jina reranker v2 multilingual | 공개 모델이 비상업 `CC-BY-NC-4.0`이고 원격 사용자 정의 코드가 필요해 운영 후보에서 제외 |
| 대형 LLM reranker | 17문서·363 vector 규모에 비해 지연, VRAM, 배포 복잡도가 과도해 YAGNI 원칙으로 제외 |

## 6. 운영 적용 판정

### 6.1 지금 확정 가능한 것

| 항목 | 판정 |
|---|---|
| BM25가 구현돼 있는가 | YES |
| BM25-only를 사용해야 하는가 | NO |
| Hybrid를 유지할 근거가 있는가 | YES, 단 가중치 최적값 주장은 불가 |
| reranker가 품질을 개선하는가 | BGE에 한해 YES |
| BGE 개선이 통계적으로 확인됐는가 | YES, 개발자 평가셋 기준 |
| BGE를 지금 기본 활성화해도 되는가 | NO |
| 기술 후보 모델이 확정됐는가 | YES, BGE v2-m3 |

### 6.2 즉시 운영 활성화를 보류한 이유

1. 질문 96개가 업무 담당자 승인 Gold가 아니다.
2. 현재 RAG Docker image에 BGE runtime과 모델이 포함되지 않았다.
3. GPU가 없는 환경의 CPU 지연과 자동 fallback을 측정하지 않았다.
4. 통합 후 질문 → 검색 → rerank → 답변 → citation의 E2E P95를 측정하지 않았다.
5. 모델 서버 장애 시 Hybrid 원순위로 복귀하는 동작을 검증하지 않았다.
6. 교차 도메인 Top-1 회귀를 업무 담당자가 수용할 수 있는지 확인하지 않았다.

평가 결과가 좋다는 이유만으로 미검증 GPU 의존성을 운영 기본값에 넣는 것은 심사와 운영 모두에서 감점 요인이다.

## 7. 권장 적용 순서

1. BGE revision을 `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`로 고정한다.
2. 별도 reranker 서비스 또는 기능 플래그로 구현하고 기본값은 OFF로 둔다.
3. 장애·timeout 시 현재 Hybrid 순서를 그대로 사용하는 fail-open fallback을 둔다.
4. 업무 담당자 2인이 80개 이상 Gold 질문과 기대 문서·조항을 독립 작성한다.
5. Gold에서 nDCG@5, Recall@5, MRR@10, Citation precision·recall, 답변 완전성을 측정한다.
6. 교차 도메인 nDCG@1 회귀 허용폭을 별도 승인한다.
7. 동시성 1·5·10에서 E2E P50·P95·P99, 오류율, GPU 메모리를 측정한다.
8. Docker 재기동·모델 캐시·네트워크 차단·reranker 장애 fallback을 검증한다.
9. 모든 Gate 통과 후 기능 플래그를 ON으로 전환한다.

## 8. 최종 운영 Gate 제안

| Gate | 합격 기준 |
|---|---:|
| Gold 질문 | 80개 이상, 업무 담당자 승인 |
| 평가자 합의 | Cohen's kappa 0.7 이상 |
| nDCG@5 | Hybrid 대비 +0.02 이상, 95% CI 하한 > 0 |
| Recall@5 | Hybrid 대비 -0.01 이내 |
| 교차 도메인 nDCG@1 | Hybrid 대비 -0.02 이내 또는 담당자 승인 |
| Citation precision | 0.95 이상 |
| Citation recall | 0.90 이상 |
| 답변 근거 충실도 | 0.95 이상 |
| 빈 답변·무관 문서율 | 1% 이하 |
| reranker P95 | 300ms 이하 |
| 통합 E2E P95 | 프로젝트 SLA 승인값 이하 |
| fallback 성공률 | 100% |
| 재기동 재현 | PASS |

## 9. 재현 자료

| 자료 | 경로 |
|---|---|
| 고정 평가셋 | `docs/e2e_mvp/derived/rag_evaluation_20260829/evaluation_dataset.json` |
| 평가셋 SHA-256 | `a51e2d8f183e73dc37647cefde98af61b391c19285571d0f278f768c9b4eaaad` |
| Hybrid 후보군 | Git 제외. `scripts/rag_evaluation/generate_candidates.py`로 실제 DB에서 재생성 |
| 후보군 SHA-256 | `9d4985791881a1721be22003bee66d20925da83abfacb420e0112e26d00a6bd4` |
| 후보 생성 코드 | `scripts/rag_evaluation/generate_candidates.py` |
| reranker 평가 코드 | `scripts/rag_evaluation/evaluate_rerankers.py` |
| 경량 후보 평가 코드 | `scripts/rag_evaluation/evaluate_lightweight_reranker.py` |
| BGE·MiniLM 결과 | `docs/e2e_mvp/derived/rag_evaluation_20260829/reranker_bge_minilm_result.json` |
| BM25 절제평가 코드 | `scripts/rag_evaluation/evaluate_bm25_ablation.py` |
| BM25 절제평가 결과 | `docs/e2e_mvp/derived/rag_evaluation_20260829/bm25_ablation_result.json` |
| 기존 embedding·Hybrid 비교 | `docs/e2e_mvp/derived/rag_evaluation_20260829/embedding_hybrid_comparison_result.json` |
| 기존 최종 E2E | `docs/e2e_mvp/derived/rag_evaluation_20260829/rag_live_e2e_result.json` |

Hybrid 후보군에는 승인된 내부 문서 본문이 포함되므로 저장소에는 넣지 않는다. 결과 재현 시 실제 DB에서 다시 생성하고 위 SHA-256과 일치하는지 확인한다.

## 10. 공식 참고자료

- BGE reranker v2-m3 모델 카드: https://huggingface.co/BAAI/bge-reranker-v2-m3
- mMARCO multilingual MiniLM 모델 카드: https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
- Jina reranker 라이선스와 사용 범위: https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual
- Sentence Transformers reranking evaluator: https://sbert.net/docs/package_reference/cross_encoder/evaluation.html

## 11. 최종 한 줄 판정

`OpenAI text-embedding-3-large 1024 + pgvector/BM25 Hybrid 0.65/0.35`를 현재 기준으로 유지하고, `BAAI/bge-reranker-v2-m3`를 통계적으로 검증된 2차 재정렬 기술 후보로 확정한다. 다만 업무 Gold·통합 Docker E2E·fallback 검증 전에는 운영 기본값으로 활성화하지 않는다.

## 변경 내역

| 버전 | 일시 | 요약 |
|---|---|---|
| v1.1 | 2026-08-29 18:03 | 측정 실패 후보를 사용자용 비교 문서에서 제거 |
| v1.0 | 2026-08-29 18:03 | BM25 절제평가와 2개 reranker 후보 비교·운영 판정 최초 작성 |
