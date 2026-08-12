# Answervice — 대화형 데이터 분석·자동 리포팅 플랫폼

Answervice는 여러 업무 데이터 소스를 자연어로 조회하고 근거가 있는 분석 결과를 반복 실행 가능한 보고서로 전환하는 서비스다. 상세 범위·아키텍처·현재 상태는 아래 활성 기준 문서와 실제 코드·테스트에서 확인한다.

## 활성 기준 문서

- 프로젝트 범위·아키텍처: [최종 기획서](./docs/Answervice_기획서.md)
- 실행 일정·담당·상태: [공식 WBS](./docs/markdown/02_WBS.md)
- 화면·상태·사용자 흐름: [화면설계서](./docs/markdown/05_화면설계서.md)
- 문서 위치·번호·보호 규칙: [문서 관리 규칙](./docs/문서관리규칙.md)

CI는 Python·Node 의존성 감사를 수행하고 CycloneDX SBOM을 30일간 보관한다. 또한 backend·frontend 이미지를 직접 빌드해 HIGH·CRITICAL 취약점이 발견되면 품질 게이트를 실패시킨다.

## 개인 branch 시작

```powershell
git clone https://github.com/hijun318-eng/skn29_final_3team.git
Set-Location skn29_final_3team
git switch <본인 branch>
```
