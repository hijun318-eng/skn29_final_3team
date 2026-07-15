# Versioned evaluation assets

기능별 품질을 version 간 비교하기 위한 저장소다.

- `registry.json`: 현재 평가 대상과 version 인덱스
- `testsets/`: 작고 비식별화된 고정 test set
- `baselines/`: 승인된 기준 결과와 metric
- `reports/`: 사람이 읽을 수 있는 before/after 보고서
- `runs/`: 일회성 raw output, Git ignore
- `templates/`: test case와 report 예시

실제 기능이 생기기 전에는 빈 디렉터리와 template만 유지한다. 자세한 규칙은 `docs/engineering/QUALITY_EVALUATION_GUIDE.md`를 따른다.
