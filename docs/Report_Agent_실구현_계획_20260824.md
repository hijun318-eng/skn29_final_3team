# Report Agent 실구현 계획

기준일: 2026-08-24
상태: 실구현 4단계 완료, 외부 dependency 및 모델 live 검증 미실행

## 실구현 단계

전체는 5단계다.

1. 제한된 ReportPatch 계약과 순수 적용기
2. 기존 Artifact 기반 모델 patch를 실제 CAS 새 Revision으로 저장
3. 새 분석 승인·AnalysisController·새 Artifact를 ReportPatch로 합성
4. 대화 이력·명확화·재계획을 포함한 multi-turn 지능
5. Model·App DB·DataHub·Trino·Browser가 같은 request로 연결된 live E2E

## 2단계 완료 범위

- `report_assistant_turn` 입력에 현재 draft 제목·표시 설정·전체 block context를 추가
- 모델 출력은 제목 변경, text 추가·수정, 검증 Artifact view 추가의 strict patch로 제한
- 실제 Artifact ID 대신 서버 별칭 `source_artifact`만 모델의 patch 참조로 허용
- `existing_artifact`는 analysis plan 없이 patch가 필수이고 `new_data`는 patch를 금지
- 모델 patch를 서버의 `ReportAssistantPatch`와 순수 적용기로 이중 검증
- owner·session·ready phase·base revision·최신 version을 한 transaction에서 CAS 확인
- 성공 시 원본 version을 수정하지 않고 모든 block을 새 draft version에 저장
- 검증 patch JSON·모델/prompt hash·결정 hash와 완료 revision을 Assistant 감사 이력에 저장
- 프런트는 `completed` revision을 서버에서 다시 조회한 뒤에만 보고서 상태에 반영

2단계 검증은 테스트 전용 fake model/Artifact/repository 경계를 사용한다. migration은 소스만
추가했으며 운영 DB에는 적용하지 않았다. 실제 모델 호출이나 DataHub·Trino 조회도 수행하지 않았다.

검증 결과:

- AI 계약·migration·patch·Assistant session 관련 unittest 57개 통과
- 프런트엔드 전체 24개 테스트 통과 및 production build 통과
- 코드 문서화, 아키텍처 불변식, 855개 파일 repository 무결성 감사 통과
- Python compileall과 `git diff --check` 통과
- 운영 DB migration 적용, 실제 모델 endpoint, DataHub, Trino, 브라우저 E2E는 미실행

## 3단계 완료 범위

- 사용자 승인과 최초 DB claim 뒤에만 기존 `AnalysisController`를 한 번 실행
- controller가 반환한 Artifact를 owner·request·승인 상태·query lineage·checksum으로 재검증
- 검증 Artifact를 `saving_revision`에 고정한 뒤 현재 draft와 함께 두 번째 strict 모델 turn에 전달
- 실제 Artifact ID와 query ID는 모델에 노출하지 않고 `source_artifact`·`source_query` 별칭 사용
- 두 번째 모델이 `existing_artifact`와 제한 `ReportPatch`를 반환해야만 저장 진행
- 모델이 추가 분석을 요구하거나 허용되지 않은 block·Artifact를 참조하면 typed 실패
- 새 Artifact chart/table과 근거 요약 text를 동일 patch 적용기로 구성
- 기존 block·Artifact lineage를 보존하면서 새 patch 결과를 data request ID가 포함된 CAS로 저장
- `saving_revision` 재진입은 AnalysisController를 호출하지 않고 합성·저장만 재개
- 완료된 revision은 기존 프런트 승인 흐름이 다시 조회해 Canvas에 반영

3단계도 `tests/` 아래 fake controller·Artifact·model·repository만 사용했다. 실제 분석 결과가
생성되거나 운영 DB에 revision이 저장됐다는 의미는 아니며, live 검증은 5단계 범위다.

## 4단계 완료 범위

- strict 모델 판단 종류에 `clarification`을 추가하고 plan·patch 동시 생성을 금지
- 사용자 지시와 Assistant 응답을 세션별 증가 turn 번호로 같은 transaction에 저장
- history 조회는 현재 owner 세션으로 제한하고 최근 6개 상호작용만 시간순 반환
- 다음 모델 turn에 role·content 외 필드가 없는 최대 12개 bounded message를 제공
- 모델은 history를 근거나 권한으로 사용하지 않고 현재 지시의 모호성 해소에만 사용
- 명확화 응답은 `ready`를 유지해 사용자 답변을 다음 재계획 입력으로 연결
- 기존 Artifact 변경, 새 분석 계획, 명확화 응답 모두 같은 turn 감사 경계를 사용
- 프런트는 clarification을 완료나 승인 대기로 오인하지 않고 후속 입력을 허용
- model schema·prompt를 `MODEL-RELEASE-v1.25.0`·`PROMPT-v1.2.0`에 결속

별도 vector memory, agent framework, 요약 worker는 추가하지 않았다. 6개 상호작용을 넘는 장기
기억이 실제 사용 지표로 필요해질 때만 요약·보존 정책을 별도 설계한다.

## 완료된 첫 경계

- 모델이 임의 JSON Patch, 좌표, Artifact ID, query ID, checksum을 만들 수 없는 strict
  `ReportAssistantPatch` 계약 추가
- 현재 허용 연산을 `set_report_title`, `add_text`, `update_text`,
  `add_artifact_view`로 제한
- Artifact는 상류 repository가 검증한 `VerifiedArtifactBinding`의 서버 별칭으로만 참조
- 새 block ID와 실제 12열 위치·높이는 서버가 결정
- 존재하지 않는 block, text가 아닌 수정 대상, 미등록 Artifact 별칭은 전체 patch를 거부
- 원본 draft는 불변으로 유지하고 성공한 patch만 새 `ReportDefinitionVersion` 값으로 반환
- `tests/` 아래 fake Artifact로 차트·요약 추가와 기존 lineage 보존을 검증

이 결과는 Report Agent의 실제 편집 코어에 대한 unit 증거다. 모델, DataHub, Trino, App DB,
브라우저가 연결된 live Agent 증거는 아니다.

## 목업 경계

허용하는 목업은 `tests/` 아래 명시적으로 주입한 다음 항목뿐이다.

- 분석이 성공했다고 가정한 fake Artifact ID
- fake Trino query ID
- 형식이 유효한 fake checksum
- 모델이 strict 계약으로 반환했다고 가정한 ReportPatch

production 코드에는 질문별 응답, 고정 SQL, fake Artifact fallback, 숨은 인증 우회를 추가하지 않는다.
프런트 Showcase는 실제 Agent 완료 증거로 사용하지 않는다.

## 다음 구현 순서

1. `report_agent_plan` 모델 계약에 현재 definition, 전체 block, 허용 Artifact 별칭과 최근 turn을 제공한다.
2. 모델 응답을 `CLARIFY`, `USE_EXISTING_ARTIFACT`, `RUN_NEW_ANALYSIS`로 제한한다.
3. `USE_EXISTING_ARTIFACT`는 ReportPatch를 즉시 서버 검증하고 CAS 새 revision으로 저장한다.
4. `RUN_NEW_ANALYSIS`는 typed semantic slot을 사용자 승인 뒤 기존 AnalysisController에 전달한다.
5. 새 Artifact를 owner·request·approval·query·checksum으로 검증한 뒤 `report_agent_compose`가
   ReportPatch를 생성한다.
6. 동일 patch 적용기와 CAS 저장 경계를 사용해 새 block을 만들고 Canvas는 completed 응답 뒤 갱신한다.
7. Assistant turn을 저장하고 최근 bounded history로 clarification과 후속 편집을 지원한다.

## DataHub 비의존 후속 고도화 완료

- 모델이 기존 block을 `reposition_block`으로 상대 재배치하고 폭을 `half`·`full`로 조정 가능
- 서버는 block 존재와 자기 참조를 검증하고 실제 좌표를 계산
- 기존 Artifact·query lineage와 block ID는 변경하지 않음
- 새 데이터 분석 기능은 계속 DataHub·Trino readiness가 필요하지만 제목·문구·기존 시각화 배치는
  외부 카탈로그 없이 동작
- 모델이 기존 block을 삭제하거나 서버 발급 ID로 복제할 수 있으며 Artifact lineage는 변경하지 않음
- 명시적인 되돌리기 지시는 직전 version snapshot을 과거 행 수정 없이 새 CAS revision으로 저장

## 실제 완료 조건

`지난달 비교 차트와 세 문장 요약을 추가해 줘` 요청 하나가 다음 증거를 모두 남겨야 한다.

- 승인 전 Trino 호출 0회
- 승인 뒤 실제 model trace와 Trino query ID
- owner와 request에 결속된 APPROVED Artifact 및 SHA-256 checksum
- 기존 block 보존과 새 chart·text block 추가
- CAS로 저장된 새 Report revision
- 새로고침 뒤 동일 Canvas 복구
- Browser, HTTP, App DB, DataHub, Trino, model이 같은 request ID로 연결된 receipt

현재 App PostgreSQL과 Trino가 정상화되고 model endpoint가 주입되기 전에는 마지막 live 검증을
통과했다고 기록하지 않는다.
