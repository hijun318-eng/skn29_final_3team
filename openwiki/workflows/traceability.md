---
type: Traceability Guide
title: 요구사항·화면·구현·검증 추적
description: SensePlace Baseline 요구사항, 중간발표 화면 계약, WBS 상태, 구현·테스트 증거의 현재 연결 상태와 미결정을 정리한 가이드
tags: [senseplace, requirements, wbs, testing, traceability]
---

# 요구사항·화면·구현·검증 추적

## 현재 판정 원칙

`docs/markdown/01_요구사항정의서.md`는 62개 기존 ID를 추적용으로 유지하되, **Baseline 필수 43건**, 독립 실험 8건, 보류·승인 후 후보 11건으로 구분한다. 62개 모두가 확정 구현 범위라는 뜻은 아니다. 일정·담당·상태는 `docs/markdown/02_WBS.md`를 따른다.

현재 저장소의 `app/`, `src/`, `tests/`, `evals/`에는 `.gitkeep`만 있으므로, Baseline 요구사항과 WBS의 계획을 구현 완료로 표시할 수 없다. 실제 공백과 구현 시작점은 [현재 아키텍처 상태](../architecture/current-state.md)가 설명한다. 요구사항이 설명하는 사용자 결과와 안전 경계는 [핵심 업무 흐름](./product-flows.md)이 canonical home이다.

## 상위 Baseline 요구사항과 증거 상태

| ID | 목표 결과 | 관련 흐름 | 현재 evidence |
|---|---|---|---|
| `REQ-F-001` | synthetic 데이터 생성·적재·품질 Gate | 공통 준비 흐름 | WBS `2.x`, `5.3`이 대기이며 fixture/manifest/validation은 미생성 |
| `REQ-F-002` | Django session·3역할 서버 권한 | 기능 A | WBS `6.1`이 대기, `app/django/`는 비어 있음 |
| `REQ-F-003` | 8 intent, SQL Guard, 결과 근거 표시 | 기능 A | WBS `6.4`, `6.9`, `6.12`~`6.14`가 대기, 코드·테스트 없음 |
| `REQ-F-004` | 품질 Gate 이후 결정론적 이상 감지 | 기능 B | WBS `5.9`, `5.10`이 대기, rule/trigger 없음 |
| `REQ-F-005` | Incident evidence 분석 | 기능 B | WBS `5.4`, `6.3`이 대기, evidence 구현 없음 |
| `REQ-F-006` | evidence 기반 주간 `DRAFT`, 실패 시 `PARTIAL` | 기능 B | WBS `6.6`이 대기, report 구현 없음 |
| `REQ-F-007` | 관리자 승인·보류·반려 | 기능 B 종료 | WBS `6.2`, `6.6`이 대기, decision API/UI 없음 |
| `REQ-NF-001` | PII/secret·권한·read-only·자동조치 금지 | 공통 | 저장소 수준 Git 보호 일부만 확인됨; 앱 수준 enforcement 증거 없음 |
| `REQ-NF-002` | version·재현성·fallback | 공통 | WBS Gate/Golden Path가 대기, test asset 없음 |

위 표의 “대기/미생성”은 WBS와 실제 파일의 현 상태이며, 제품 실패 판정이 아니다. 다음 구현은 이 ID를 코드·테스트·실행 evidence와 연결해야 한다.

## 화면 추적: 사용할 수 있는 것과 동기화가 필요한 것

`docs/markdown/05_화면설계서.md` §0.6은 `P0-001`~`P0-030`의 6개 화면을 중간발표 데모 계약으로 정의한다. 이는 합성 fixture와 frontend 상태 전환으로 설명하는 범위이며 backend·DB·LLM 연결을 증명하지 않는다. 각 화면이 기능 A/B에 어떻게 연결되는지는 [핵심 업무 흐름](./product-flows.md)의 6개 화면 표를 따른다.

그러나 활성 요구사항서는 화면설계서가 이번 동기화 범위에서 제외되었다고 밝히며, `UI-001`~`005`와 6화면 제품 계약을 제출 후 개정할지 현행 유지할지 미결정으로 둔다. 화면설계서 §21의 기존 `SCR-*` 요구사항 매트릭스는 “구현 TBD”이고, 그 일부는 현 Baseline의 8 intent·내부 fixed-seed 적재·`P0-*` 계약과 다른 과거 전제를 담고 있다.

**변경 규칙:** 새 기능이나 QA를 `SCR-*` 표만으로 확정하지 않는다. 먼저 활성 `REQ-*`와 `P0-*` 계약의 관계를 팀이 결정하고, 그 뒤 요구사항→화면→구현→테스트 ID를 같은 변경에서 갱신한다.

## 검증 목표와 현 증거

활성 요구사항의 목표 검증은 다음과 같다.

- Baseline Gate: 반례 세트 v2 21건, `8 intent × 3 roles × 3 utterances`, 최소 3개 seed에서 차단 결함 0건
- 공격/안전: 미지원 질문, `UNION`, 주석, 다중 statement, 금지 함수·catalog 접근, scope 우회 차단
- 기능 B: 정상 무경보, 결측 `NEEDS_DATA`, LLM 실패 `PARTIAL`, 중복 실행 방지, 보고서 결정 저장
- 최종 안정화: Gate 이후 회귀와 대표 Golden Path 연속 5회

WBS상 Gate `7.1`, 자동 채점·회귀 `7.6`, Golden Path `8.4`는 모두 대기이고 `tests/`·`evals/`에 해당 자산은 없다. 따라서 지금은 실행 명령이나 통과 결과가 아닌 **필요 증거 목록**으로만 취급한다. 테스트와 fixture가 생기면 [현재 아키텍처 상태](../architecture/current-state.md)의 구현 체크에 따라 명령·범위·결과를 이 페이지와 연결한다.

## 변경 시 최소 추적 단위

1. 활성 요구사항 ID와 acceptance criteria를 선택한다.
2. 영향받는 `P0-*` 화면 또는 실제 UI 상태를 연결한다.
3. 코드·schema·fixture·rule version·권한 scope의 source path를 기록한다.
4. test/eval ID, 입력 seed/scenario, 기대 결과와 실행 결과를 기록한다.
5. 일정·담당·상태·evidence path가 바뀌면 WBS 규칙을 적용한다.

문서와 코드의 변경은 [저장소 운영 통제](../operations/repository-controls.md)의 데이터·Git·문서 정책에 의해 보호된다.
