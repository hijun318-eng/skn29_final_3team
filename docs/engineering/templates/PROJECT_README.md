# 호텔 VOC/운영 이슈 분석 Agent

고객 review와 호텔 운영 데이터를 연결해 VOC 증가 원인, 반복 불만, 운영 이상징후를 분석하고 대응 근거와 정기 보고서를 제공하는 프로젝트다.

## 현재 상태

- 세부 주제: 확정
- 개발환경과 협업 규칙: 초기화
- frontend/backend/database/model/deployment stack: 미정
- 데이터: 합성 Raw data 생성 기준 수립 예정

## 팀원과 개인 branch

| 이름 | Branch | 역할 | GitHub |
|---|---|---|---|
| 준희 | `junhee` | 미정 | 입력 필요 |
| 민지 | `minji` | 미정 | 입력 필요 |
| 승 | `seung` | 미정 | 입력 필요 |
| 대성 | `daesung` | 미정 | 입력 필요 |
| 재홍 | `jaehong` | 미정 | 입력 필요 |

## Local 실행 준비

```powershell
python -m venv .venv
Copy-Item -LiteralPath .env.example -Destination .env
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

실제 실행 명령은 framework와 entrypoint를 확정하고 검증한 뒤 이 절에 추가한다. `.env`에는 개인 key를 입력하되 commit하지 않는다.

## 협업 시작

- [팀원 개발환경 세팅](./docs/engineering/TEAM_DEVELOPMENT_SETUP_GUIDE.md)
- [Git branch 전략](./docs/engineering/GIT_BRANCH_STRATEGY.md)
- [최소 프로젝트 폴더 구조](./docs/engineering/PROJECT_STRUCTURE.md)
- [기여 방법](./CONTRIBUTING.md)
- [품질 평가](./docs/engineering/QUALITY_EVALUATION_GUIDE.md)

## 주의

합성 데이터와 분석 결과를 실제 호텔 운영 사실이나 실제 고객 행동으로 표현하지 않는다.
