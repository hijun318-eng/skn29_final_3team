# Walkerhill 공개 구조 기반 합성 데이터 v4

## 결론

이 데이터 제품은 **조건부 GO**입니다. 프로젝트의 당위성은 “Walkerhill 실제 경영 성과를 분석한다”가 아니라, **공개 구조를 참고한 비공식 합성 호텔 데이터에서 DataHub 기반 탐색, 승인 Metric·JOIN, Trino 교차 소스 조회, G1·G2·G3 통제를 재현한다**는 데 있습니다.

따라서 다음 주장은 금지합니다.

- Walkerhill 내부 데이터·운영 스키마·실제 성과라는 주장
- Walkerhill의 승인·제휴·감수를 받았다는 주장
- 지원 질문 계약 밖 자유 분석의 정확성을 보장한다는 주장

화면과 보고서에는 항상 `Walkerhill 공개 기준정보 기반 비공식 교육용 합성 데이터`를 표시합니다.

## 왜 이 구조가 프로젝트에 필요한가

PMS, POS, CRM, 연회, 시설·자원 원천을 분리하는 이유는 서로 다른 원천의 소유권·식별자·시간 의미를 DataHub와 계약으로 통제하기 위해서입니다. 단순히 DB 개수를 늘리기 위한 분리는 프로젝트 당위성이 없습니다. 아래 능력을 실제로 시연할 때만 다중 원천이 정당화됩니다.

1. DataHub에서 owner, domain, grain, provenance, sensitivity와 lineage를 발견한다.
2. Metric과 event-time JOIN 계약으로 허용된 분석만 선택한다.
3. 원시 fact-to-fact JOIN을 금지하고, 회원·일 또는 호텔·일 단위로 사전 집계한다.
4. Trino 조회 전후 G1·G2·G3가 권한, SQL, 결과를 검증한다.
5. 답변에 사용 Dataset·Metric·기간·합성 여부를 근거로 남긴다.

이 중 어느 것도 시연하지 않는다면 하나의 분석 DB와 승인 View만으로 단순화하는 편이 낫습니다.

## 데이터 계약

- `product_contract.v2.json`: 주장 경계, 10개 지원 질문군, 23개 Metric, 6개 승인 JOIN, 승격 Gate
- `schema_contract.v2.json`: 33개 reference/source/serving 자산의 grain, PK/FK, 필드형, 단위, 민감도, 설명
- `generate.py`: 하나의 공통 일별 수요·날씨·프로모션 driver에서 원천 간 연관성을 갖는 거래 생성
- `validate.py`: 생성기와 별도로 원천을 다시 집계하여 구조·재무·시계열·용량·Serving 동등성 검증

공개 페이지에서 확인한 것은 명칭과 상품 구조뿐입니다. 객실 수, 정원, 가격, 매출, 점유율, 고객 행동은 모두 합성 가정 또는 생성 사실입니다. 공식 참고 페이지는 [객실](https://www.walkerhill.com/grandwalkerhillseoul/en/room/Intro), [Vista 객실](https://www.walkerhill.com/vistawalkerhillseoul/en/room/), [Dining](https://www.walkerhill.com/en/book/Dining), [Meeting](https://www.walkerhill.com/en/convention/Meeting), [Rewards](https://www.walkerhill.com/en/membership/Rewards)입니다.

## DataHub metadata 원칙

설명은 필요하지만 설명만으로는 부족합니다. 노출되는 모든 Dataset에는 다음 항목을 채웁니다.

- business name, description, grain, owner, domain, layer
- provenance class, synthetic 여부, schema version, quality status
- preferred/deprecated 상태와 time field
- 모든 필드의 qualified key, type, nullable, unit, sensitivity, description

DataHub description은 검색과 설명에만 사용합니다. 권한, Metric 승인, JOIN 승인 또는 품질 통과를 대신하지 않습니다. 의미가 같은 호환 View는 `deprecated=true`, `preferred_asset=false`로 처리하고 기본 검색에서 숨깁니다.

## Qwen 영향

스키마나 데이터가 바뀐다는 이유만으로 Qwen을 다시 학습하지 않습니다. 먼저 catalog retrieval, prompt의 계약 버전, few-shot SQL, schema cache를 갱신하고 held-out 질문으로 재평가합니다. 승인 밖 자산·컬럼·JOIN 선택이 남고 그 원인이 모델 일반화 부족으로 확인될 때만 fine-tuning을 검토합니다. 데이터·계약 오류를 모델 학습으로 덮지 않습니다.

## 생성과 검증

```powershell
python infrastructure/database/walkerhill_v4/generate.py `
  --output output/walkerhill_v4_candidate

python infrastructure/database/walkerhill_v4/generate.py `
  --output output/walkerhill_v4_replay

python infrastructure/database/walkerhill_v4/validate.py `
  --candidate output/walkerhill_v4_candidate `
  --determinism-reference output/walkerhill_v4_replay
```

`data_gates_passed=true`여도 DataHub exact URN binding, Qwen/SQL held-out 평가, 전체 runtime canary 전에는 `promotion_eligible=false`입니다. DataHub URN은 connector가 실제 적재한 결과에서 발견·검증하며 논리 FQN으로 미리 추측하지 않습니다. 현재 Compose volume이나 기존 `service_demo_v3`를 자동 교체하지 않습니다. 평가 통과 후 별도 Slice에서 physical DDL·load·DataHub ingestion·Trino catalog를 연결합니다.
