---
type: Operations Guide
title: 저장소 운영·보안 통제
description: SensePlace 저장소의 데이터·비밀 보호, Git hooks, 문서 작업 경계 및 OpenWiki 자동화 설정을 실제 설정 파일 기준으로 정리한 안내서
tags: [senseplace, operations, security, git, openwiki]
---

# 저장소 운영·보안 통제

## 민감 데이터와 생성물 경계

`AGENTS.md`와 `.gitignore`는 `.env`, key 파일, 실제 고객 데이터, 생성된 raw/processed 데이터와 모델·캐시·eval 실행 산출물을 저장소에서 제외한다. 이 위키도 `.env`, API key, 실제 고객 데이터, `data/raw`, `data/processed` 생성 파일의 내용을 읽거나 복사하지 않는다.

합성 데이터도 무조건 공개 가능한 것으로 간주하지 않는다. 구현 시 데이터에는 synthetic 여부와 seed·schema version 등 재현 metadata를 남기되, 생성물 자체는 `data/raw/**`, `data/processed/**` 등의 ignore 규칙과 pre-commit 보호를 따른다. 이 제약은 [현재 아키텍처 상태](../architecture/current-state.md)의 데이터 계약과 [핵심 업무 흐름](../workflows/product-flows.md)의 품질 Gate가 실제 데이터 노출 없이 재현성을 확보하도록 만든다.

## Git hooks로 확인되는 통제

`.githooks/pre-commit`은 staged 변경에서 다음을 차단하거나 검사한다.

- `.env`(단 `.env.example` 제외), `*.pem`, `*.key`
- `data/raw`, `data/interim`, `data/processed`, `data/mart`, `data/ground_truth`의 일반 생성 파일
- 10 MB 초과 파일
- 대표적인 secret 문자열
- `docs/*.md`의 Python 문서 정책 검사

`.githooks/commit-msg`는 `<type>(<scope>): <한국어 summary>` 형식, 허용 type, 소문자 scope, 72자 이하 subject, 한국어 summary, 마침표 없음 규칙을 검사한다.

이는 hook 파일이 존재한다는 증거일 뿐 모든 개발자·CI 환경에 자동 설치되거나 앱 보안을 완성한다는 증거는 아니다. 앱 수준 PII·권한·read-only enforcement와 테스트는 아직 구현 증거가 없으며 [요구사항·화면·검증 추적](../workflows/traceability.md)의 Baseline evidence로 추가되어야 한다.

## 문서 작업 경계

- `docs/markdown/01_요구사항정의서.md`는 범위와 수용 기준, `02_WBS.md`는 일정·담당·상태, `05_화면설계서.md`는 화면 상세의 우선 기준이다.
- `docs/markdown/ai_docs/`는 참고 자료이며 활성 번호 문서·코드·테스트를 덮어쓰지 않는다.
- `docs/templates/`는 읽기 전용이다.
- WBS에 연결된 일정·상태·담당·산출물·근거가 바뀌면 전용 skill과 WBS 규칙을 적용한다. 단순 조사·설명처럼 저장소 변경이 없으면 WBS를 갱신하지 않는다.

이 위키는 공식 제출물이 아니라 보조 문서다. 요구사항과 화면의 미동기화 문제를 포함한 변경 추적 기준은 [요구사항·화면·검증 추적](../workflows/traceability.md)을 확인한다.

## OpenWiki의 Codex OAuth 운영

OpenWiki 0.2.2는 로컬 `openai-chatgpt` provider로 실행한다. 최초 `openwiki code --init`에서 ChatGPT OAuth 승인을 받고 `gpt-5.6-terra`를 선택했으며 LangSmith tracing과 OpenWiki telemetry는 비활성화했다. 이후에는 같은 provider에서 `openwiki code --update --print`를 수동 실행한다.

OAuth access token, refresh token, 만료 시각과 account ID는 사용자 경로 `~/.openwiki/.env`에 저장된다. 이 파일과 값을 저장소, 일일보고, 위키 본문 또는 CI Secret으로 복사하지 않는다. refresh token은 password와 같은 수준으로 취급한다.

OpenWiki 실행은 저장소 내용을 Codex backend로 전송하고 ChatGPT plan의 Codex 사용량을 소비할 수 있다. 자동 schedule이나 저장소 쓰기 권한을 가진 GitHub Actions workflow는 사용하지 않는다. 생성된 `openwiki/` 문서는 source·공식 문서와 함께 검토해야 하며 [현재 아키텍처 상태](../architecture/current-state.md)의 구현 사실을 대체할 수 없다.

## 운영 변경 체크

1. 실제 데이터·비밀·외부 전송·비용이 영향을 받는지 먼저 확인하고 승인을 받는다.
2. code 또는 문서의 source of truth를 바꾸기 전에 [요구사항·화면·검증 추적](../workflows/traceability.md)의 ID·WBS 영향 여부를 확인한다.
3. hook이 설치되어 있다는 가정을 하지 말고, CI 또는 명시적 실행으로 필요한 검사를 재현한다.
4. OpenWiki 갱신 전에는 `openai-chatgpt` provider, tracing 비활성, OAuth credential 저장 위치와 외부 전송 범위를 확인한다.
