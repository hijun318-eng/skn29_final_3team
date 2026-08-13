# Walkerhill v4 데이터 전환 결정

## 결론

**기존 golden-path 데이터는 기본 경로에서 교체해야 합니다.** 데이터·Trino·DataHub 계층에서는 v4를 기본 후보로 승격했고, 기존 데이터는 삭제하지 않고 rollback 전용 deprecated 상태로 유지합니다.

현재 애플리케이션은 아직 old 8-view 계약에 결합돼 있으므로 앱 runtime까지 전환된 것은 아닙니다. 사용자 변경이 진행 중인 backend 파일을 덮어쓰지 않고 별도 앱 계약 전환과 canary를 남겼습니다.

RAG 문서·VectorDB 연계와 Qwen live 평가는 이번 데이터 교체의 차단 조건에서 제외합니다.

## 왜 교체해야 하는가

기존 데이터는 정해진 질문과 화면을 재현하는 데 유리하지만 다음 프로젝트 주장과 충돌합니다.

1. DataHub에서 여러 원천 자산을 탐색한다.
2. 질문에 따라 Metric과 허용 JOIN을 선택한다.
3. Trino가 PMS·POS·CRM·연회·시설을 교차 분석한다.
4. G1·G2·G3가 임의 질문의 권한·SQL·결과 근거를 통제한다.

golden-path 데이터와 고정 8개 View를 계속 기본값으로 두면 이는 범용 데이터 분석 제품이 아니라 준비된 답을 재생하는 데모에 가깝습니다. 따라서 v4 전환은 선택이 아니라 프로젝트 당위성을 위한 필수 조건입니다.

단, 올바른 대외 표현은 **Walkerhill 공개 구조를 참고한 비공식 합성 운영 데이터 분석**입니다. Walkerhill 실제 내부 데이터 또는 공식 성과 분석이라고 주장해서는 안 됩니다.

## 완료된 전환

- v4 데이터: 33개 데이터셋, 308개 컬럼, 225,481행
- 동일 seed 재생성 및 데이터 gate 통과
- 5개 원천 DB의 `walkerhill_v4` namespace 적재 완료
- Trino 33개 자산의 기대·실제 행 수 일치, 불일치 0건
- serving 7개를 미리 계산한 파일이 아닌 실제 원천 SQL View로 교체
- 원천 SQL과 기존 v4 정답의 행 수 및 양방향 차집합 0건
- DataHub exact binding: 33개 데이터셋, 308개 컬럼
- DataHub 실제 connector lineage: serving 7개, upstream 13개, 컬럼 lineage 52개
- 가상 Trino upstream 자산: 0개
- DataHub description, grain, owner, domain, 합성 태그, 컬럼 민감도 게시·재조회 통과
- 구형 원천 18개와 serving 8개, 총 26개 자산: `deprecated=true`, 물리 삭제 없음
- held-out gold SQL 10개: G2 및 read-only Trino 실행 10/10 통과

## 아직 완료되지 않은 전환

1. 애플리케이션 adapter는 old 8-view 계약·컬럼·검증 hash를 읽습니다.
2. v4 전용 analytics/context 계약을 앱에 연결해야 합니다.
3. 앱 경로에서 G1·G2·Trino·G3 canary와 rollback rehearsal이 필요합니다.
4. ClickHouse connector의 `DateTime64(3, 'Asia/Seoul')` native type 경고를 별도로 정리해야 합니다.

이 네 항목은 데이터 품질 실패가 아니라 애플리케이션 cutover 작업입니다.

## 교체 방식

- 논리적 교체: v4를 DataHub·Trino·앱의 기본 분석 자산으로 사용
- 구형 자산: deprecated 및 기본 선택 제외
- 물리적 보존: v4 앱 canary와 rollback rehearsal 전까지 유지
- 물리적 삭제: 별도 승인 후 수행

이 방식은 중복 테이블을 영구 운영하려는 것이 아닙니다. 현재 중복은 cutover 중 rollback을 위한 임시 공존입니다.

## Qwen 판단

Qwen endpoint 상태와 재학습 여부는 데이터 전환을 막지 않습니다. 스키마 변경만으로 재학습하지 않으며, 추후 endpoint가 준비되면 v4 catalog와 held-out으로 별도 평가합니다.

## 다음 순서

1. v4 analytics/context 계약을 현재 애플리케이션 adapter에 연결
2. v4 전용 G1·G2·Trino·G3 application canary
3. 앱 기본 경로를 v4로 전환
4. rollback rehearsal
5. 구형 물리 자산 삭제 여부 별도 결정
