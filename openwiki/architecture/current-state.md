---
type: Architecture Status
title: 현재 아키텍처 상태와 구현 경계
description: SensePlace의 실제 저장소 구조와 활성 문서에 정의된 계획 구조를 구분하고 구현 시작 시 확인할 계약을 정리한 문서
tags: [senseplace, architecture, implementation-status, synthetic-data]
---

# 현재 아키텍처 상태와 구현 경계

## 결론: 계획은 있으나 실행 가능한 제품은 확인되지 않음

저장소에는 `app/django/`, `app/fastapi/`, `app/react/`, `src/analysis/`, `src/common/` 디렉터리가 있으나 각각 `.gitkeep`만 있다. `tests/`, `evals/`, `data/samples/`도 동일하다. `package.json`, `pyproject.toml`, `requirements*.txt`, DB migration/schema, 실행 진입점, 앱 테스트 파일은 확인되지 않았다.

따라서 아래 구조는 `docs/markdown/01_요구사항정의서.md`와 `docs/markdown/03_프로젝트기획서.md`가 정의한 **목표 아키텍처**다. 코드 사실로 전환되기 전까지 API·모델·모듈 세부를 추정해 만들지 않는다. 목표 구조가 제공해야 할 사용자 결과와 안전 경계는 [핵심 업무 흐름](../workflows/product-flows.md)에, 완료 증거의 기준은 [요구사항·화면·검증 추적](../workflows/traceability.md)에 연결된다.

## 저장소의 의도된 경계

`AGENTS.md`는 핵심 로직을 `src/`에, 사용자 노출 서비스 진입점을 `app/`에 둔다고 정한다. 현재는 다음 위치만 예약되어 있다.

| 위치 | 현재 확인된 상태 | 문서상 의도 또는 다음 확인 항목 |
|---|---|---|
| `app/django/` | `.gitkeep`만 존재 | Django session, 공개 `/api/v1/*`, job·polling·권한·감사·보고서 결정은 요구사항/WBS의 계획이다. |
| `app/fastapi/` | `.gitkeep`만 존재 | 내부 `/internal/v1/*` 및 read-only 분석 서비스는 계획이다. |
| `app/react/` | `.gitkeep`만 존재 | 6개 fixture 화면 계약은 존재하지만 React 목업 구현물은 확인되지 않았다. |
| `src/analysis/` | `.gitkeep`만 존재 | KPI, analytical Gate, 규칙 기반 감지, 교차분석·근거 생성은 계획이다. |
| `src/common/` | `.gitkeep`만 존재 | 공통 domain·계약 코드는 확인되지 않았다. |
| `data/samples/` | `.gitkeep`만 존재 | seed, manifest, schema, generator 구현은 확인되지 않았다. |
| `tests/`, `evals/` | `.gitkeep`만 존재 | 21개 반례, intent-role-utterance matrix, Golden Path 검증은 요구사항상 목표일 뿐 실행 자산은 없다. |

## 목표 런타임 흐름 — 문서 기준, 구현 아님

활성 기획 문서는 Django session·DRF/Django worker, 별도 FastAPI, PostgreSQL, 외부 LLM API의 역할 분리를 제안한다. 기능 A는 Django가 검증한 역할 scope를 바탕으로 query job을 만들고, semantic plan·SQL Guard·read-only 조회를 거쳐 결과를 표시한다. 기능 B는 합성 batch의 validation과 analytical Gate 후 결정론적 rule로 이상을 감지하고 Incident·evidence·DRAFT·관리자 결정을 연결한다.

이 흐름은 [핵심 업무 흐름](../workflows/product-flows.md)의 제품 계약을 구현하기 위한 경계다. 아직 서비스 호출, 데이터 저장, 비동기 worker, LLM 연결, SQL builder가 존재한다는 증거는 아니다.

## 구현 전에 고정·검증할 계약

### 데이터와 재현성

기획 문서가 요구하는 모든 데이터는 `synthetic`이다. 구현 시 `is_synthetic`, `dataset_version`, `schema_version`, `generator_version`, `scenario_id`, `seed`, `virtual_as_of_date`, `data_cutoff`을 기록해야 한다. 적재 전에는 schema/PII/정합성을, 적재 후에는 bucket 완전성·집계 정합성·기간/서비스영역/timezone/grain 정렬을 검사하며 실패 시 `NEEDS_DATA`를 유지해야 한다.

기획상 entity는 `dataset_manifest`, 운영·VOC fact, `metric_catalog`, `role_scope`, `job`, `audit_event`, `query_run`, `analysis_run`, `evidence`, `report`, `report_decision`이다. 이는 PK/FK·컬럼이 확정된 schema가 아니라 구현 전 개념 모델이다. 데이터 생성물·실제 데이터의 처리와 Git 보호 방식은 [저장소 운영 통제](../operations/repository-controls.md)를 따른다.

### 신뢰성과 AI 경계

수치·KPI·이상 판단은 SQL/Python/버전이 있는 rule로 결정론적으로 계산하는 것이 요구사항의 기준이다. LLM은 질문 해석 또는 evidence 기반 서술에 실행당 최대 1회만 사용하며, 이상 판정이나 근거 없는 인과 확정에 사용하지 않는다. 실패해도 수치 결과는 남기고 서술/보고서는 template 또는 `PARTIAL` 상태로 처리하는 것이 목표 계약이다.

### 아직 설계로 남은 항목

LLM 공급자와 기본/대안 모델·버전, 성능 목표값, HTTPS와 비밀번호 저장 수준은 요구사항서에서 미결정 또는 가정이다. 실제 dependency, config 변수, 개발·테스트·배포 명령도 파일로 확인되지 않아 문서화할 수 없다.

## 구현 변경 체크

1. [추적 기준](../workflows/traceability.md)에서 대상 `REQ-*`와 관련 WBS 상태·evidence path를 확인한다.
2. [핵심 업무 흐름](../workflows/product-flows.md)의 권한, synthetic 표시, 인과 표현 금지, 자동 조치 금지 조건을 수용 기준으로 구현한다.
3. schema·seed·fixture·test/eval을 코드와 함께 추가하고 실행 명령을 해당 도구 설정에서 검증한다.
4. 비밀·생성 데이터·외부 전송이 관여하면 [저장소 운영 통제](../operations/repository-controls.md)의 경계를 먼저 확인한다.
