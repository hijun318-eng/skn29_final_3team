# Report Assistant V2 상태 전이 프로토타입

현재 `dev`의 Report Assistant는 승인 Artifact 한 개와 지시문을 받아 제목·요약·표·차트 제목을
한 번 생성한다. 이 폴더는 이미지의 후속 대화 흐름을 실제 제품 경계로 옮길 때 필요한 가장 작은
상태 머신을 검증한다. 운영 API, DB, 모델 호출은 아직 변경하지 않는다.

## 권장 고도화

핵심은 채팅 UI보다 **승인 가능한 상태 전이**다.

```text
수동 선택 ─┐
           ├─ 승인 Artifact 검증 → 초안/편집 세션 → 사용자 지시
스케줄 최신 ┘                                  │
                         ┌──────────────────────┴──────────────────────┐
                         │ 기존 근거로 가능                            │ 새 데이터 필요
                         ▼                                             ▼
                    Revision CAS 저장                           분석 계획 사용자 승인
                                                                       │ 승인
                                                                       ▼
                                                           Data Agent → 새 Artifact 검증
                                                                       │
                                                                       ▼
                                                            기존 보고서에 lineage 추가
                                                                       │
                                                                       ▼
                                                               Revision CAS 저장
```

다음 다섯 가지를 서버 계약으로 둔다.

1. 모델은 `기존 Artifact 편집` 또는 `새 데이터 필요`를 **제안**할 뿐 실행·승인을 결정하지 않는다.
2. 새 데이터 요청은 질문과 필요 이유를 보여 주고 사용자 승인 전에는 Data Agent를 호출하지 않는다.
3. Data Agent 결과는 승인 상태, checksum, 승인된 `request_id` 일치를 검증한 Artifact만 받는다.
4. 모든 편집은 `base_revision`을 포함한 CAS 저장으로 동시 수정 손실을 막는다.
5. 스케줄은 단순 생성 시각이 아니라 운영 구현에서 동일 definition/release 범위의 최신 승인
   Artifact만 선택해야 한다. 이 프로토타입은 그중 승인·시간 조건만 표현한다.

## 기존 코드에 연결할 위치

| 책임 | 현재 위치 | V2에서 추가할 최소 계약 |
|---|---|---|
| 모델 제안 | `app/backend/app/adapters/report_assistant.py` | 변경 종류와 검증된 분석 계획 |
| 상태/API | `app/backend/app/api/report_router_support.py` | 세션, 승인, Artifact attach 명령 |
| 영속화 | `report_v1.report_assistant_requests` | phase, base revision, pending request |
| UI | `ReportAssistantPanel.jsx` | 승인 카드와 실행/실패/저장 receipt |
| Data Agent | 기존 분석 controller | 승인 receipt를 입력받고 Artifact ID만 반환 |

첫 운영 vertical slice는 “현재 보고서에 없는 기간 비교 요청 → 승인 → 기존 분석 controller 실행 →
새 Artifact 연결 → revision 저장” 한 경로면 충분하다. 자유 대화 메모리, 범용 agent framework,
자동 승인, 별도 queue는 이 경로가 실제로 막힐 때까지 추가하지 않는다.

## 실행

외부 패키지 없이 Python 표준 라이브러리만 사용한다.

```powershell
cd prototypes/report_assistant_v2
python -m unittest -v
```
