---
type: Product Workflow
title: SensePlace 핵심 업무 흐름
description: 합성 호텔 VOC·운영 데이터를 사용하는 권한 기반 분석과 이상 감지·보고서 검토의 목표 업무 흐름 및 안전 경계
tags: [senseplace, workflow, voc, operations, synthetic-data, rbac]
---

# SensePlace 핵심 업무 흐름

## 공통 제품 경계

SensePlace는 단일 호텔의 합성 조식 운영 데이터와 합성 VOC만 사용한다. 모든 결과는 `synthetic`과 한계를 표시해야 하며, 관측된 동시 변화는 원인이 아니라 **원인 후보**로 표현한다. 실제 PMS/POS/CRM/VOC 연동, 실제 개인 데이터, 다호텔 비교, 완전 자유형 BI, 자동 운영 조치는 범위 밖이다.

역할은 `HOTEL_MANAGER`, `FNB_MANAGER`, `ROOMS_MANAGER`다. 시스템의 최종 종료점은 `HOTEL_MANAGER`가 보고서에 내리는 승인·보류·반려이며, 그 결정도 고객 응대·보상·인력 배치 같은 외부 조치를 자동 실행하지 않는다. 이 업무 계약은 구현 시 [현재 아키텍처 상태](../architecture/current-state.md)의 서비스 경계에 반영되어야 하고, 구현·테스트 증거는 [요구사항·화면·검증 추적](./traceability.md)으로 관리한다.

## 공통 준비 흐름: synthetic 데이터와 2단계 품질 검사

목표 파이프라인은 고정 seed 생성기 → 정상/이상/충돌/결측 scenario → 적재 전 validation → PostgreSQL 적재 → 적재 후 analytical Gate → 정답 manifest 회귀 검증이다.

- **적재 전 validation:** schema·형식·필수값, PK/FK, 시간·shift/bucket 정합, PII·secret 부재, 행 단위 범위를 검사한다. 실패 batch는 적재하지 않는다.
- **적재 후 analytical Gate:** 15분/일 집계 정합, 필수 bucket coverage, VOC·운영지표의 서비스영역·기간·timezone·grain 정렬, 비가산 지표의 재계산 가능성을 확인한다. 실패하면 분석 상태는 `NEEDS_DATA`다.
- `NORMAL`, `BREAKFAST_CONGESTION`, `VOC_ONLY_SPIKE`, `OPS_ONLY_SPIKE` 같은 scenario는 기대 결과를 검증하기 위한 기획상 예시다. seed·schema·manifest 구현물은 아직 확인되지 않았다.

이 품질 흐름은 기능 A와 B 모두가 신뢰할 수 있는 입력을 공유하게 한다. 실제 데이터와 생성 데이터의 저장·노출 통제는 [저장소 운영 통제](../operations/repository-controls.md)에 따른다.

## 기능 A: 권한 기반 대화형 분석

1. 사용자는 Django session으로 인증되며 서버가 역할 scope를 강제한다.
2. 시스템은 보장된 8개 intent 안에서 질문을 해석해 semantic query plan을 만든다.
3. 허용 scope·metric·dimension·grain에 맞는 read-only SQL만 SQL Guard를 거쳐 실행한다. 미지원 질문, SQL 공격, 범위 이탈, 금지 재집계는 실행하지 않고 안전하게 거부한다.
4. 결과에는 표·차트·설명과 함께 기간, 단위, 표본 수, timezone, evidence를 표시한다.

목표는 자연어로 SQL을 자유 편집하는 기능이 아니다. LLM은 질문 해석이나 evidence 기반 설명에 제한하고, 수치 계산·권한 판정·SQL 안전성은 결정론적 경계에 둔다. 이 구조의 현재 구현 여부와 향후 코드 위치는 [현재 아키텍처 상태](../architecture/current-state.md)에서 확인한다.

## 기능 B: 이상 감지에서 관리자 결정까지

1. validation과 analytical Gate를 통과한 합성 batch를 대상으로 versioned deterministic rule이 이상을 감지한다. LLM은 이상 여부를 판정하지 않는다.
2. Incident는 **관측 사실**, **원인 후보**, **반대 근거**, **부족 데이터**, **현장 점검 항목/대응 옵션**을 분리한다.
3. 결정론적 수치와 evidence를 사용해 주간 HTML 보고서 `DRAFT`를 생성·보존한다. LLM 서술이 실패하면 수치와 template 보고서를 유지하고 `PARTIAL`을 표시한다.
4. `HOTEL_MANAGER`만 승인·보류·반려를 저장한다. 승인본을 덮어쓰지 않으며 어떤 외부 조치도 자동 실행하지 않는다.

이 흐름의 목표는 “원인을 찾아 자동 조치”하는 시스템이 아니라, 관리자가 근거와 한계를 검토할 수 있게 하는 의사결정 지원이다. 해당 요구사항의 Gate 증거와 구현 공백은 [요구사항·화면·검증 추적](./traceability.md)에 연결된다.

## 6개 중간발표 화면 계약

화면설계서는 중간발표 경로를 backend·DB·LLM 연결 없이 합성 fixture와 frontend 상태 전환으로 설명한다고 명시한다. 현재 `app/react/`에는 구현물이 없으므로 다음은 화면 계약이지 실행 화면 증거가 아니다.

| 화면 | 핵심 결과 | 연결되는 흐름 |
|---|---|---|
| `P0-001` 가상 로그인·역할 선택 | 합성 데이터 안내와 가상 역할 선택 | 공통 권한 안내 |
| `P0-010` 호텔 운영 홈 | 권한 범위, 질의 진입, 조식 대기 이상 카드 | A/B 분기 |
| `P0-015` 대화형 분석 | 질문, scope, `query_plan`, read-only 목업 SQL, 표·차트·근거 | 기능 A |
| `P0-020` 이상징후 상세 | trigger rule, 비교 기간, 데이터/job 상태 | 기능 B 감지 |
| `P0-025` 이슈 브리프 | 관측·후보·반대 근거·부족 데이터의 분리 | 기능 B 조사 |
| `P0-030` 주간 보고서 초안 | evidence·한계·상태 이력 및 관리자 결정 | 기능 B 종료 |

경로 A는 결과 확인에서 끝나며 보고서로 강제 연결되지 않는다. 경로 B만 이상 카드 → 상세 → 이슈 브리프 → `DRAFT` → 관리자 결정을 따른다. 화면 ID와 활성 요구사항 ID의 동기화 상태는 [요구사항·화면·검증 추적](./traceability.md)의 미결정 항목을 확인한다.
