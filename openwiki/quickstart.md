---
type: Quickstart Guide
title: SensePlace 저장소 Quickstart
description: 호텔 VOC·운영 이슈 분석 PoC인 SensePlace의 현재 구현 상태, 우선 근거, 핵심 흐름과 안전한 탐색 경로
tags: [senseplace, quickstart, repository, synthetic-data]
---

# SensePlace 저장소 Quickstart

## 이 위키가 다루는 범위

SensePlace는 단일 호텔의 **synthetic** 조식 운영 데이터와 VOC를 함께 분석해 관측 사실·원인 후보·반대 근거·관리자 검토용 보고서 초안을 제공하려는 내부 운영 지원 PoC다. 실제 호텔 상태나 성과를 주장하지 않으며, 인과를 확정하거나 운영 조치를 자동 실행하지 않는다. 제품의 두 핵심 경로와 화면 계약은 [핵심 업무 흐름](./workflows/product-flows.md)에서 설명한다.

이 `openwiki/`는 개발자와 AI 에이전트를 위한 보조 지도다. 공식 산출물, WBS, 구현 완료 증거를 대체하지 않는다.

## 먼저 알아둘 현재 상태

**확인된 구현:** `app/django/`, `app/fastapi/`, `app/react/`, `src/analysis/`, `src/common/`, `tests/`, `evals/`에는 모두 `.gitkeep`만 있다. 실행 진입점, dependency manifest, DB schema/migration, synthetic fixture/seed, 애플리케이션 테스트는 확인되지 않았다. 따라서 Django·FastAPI·PostgreSQL·LLM·React는 활성 문서와 WBS의 **계획 구조**이며 현 구현으로 표현하지 않는다. 근거와 구현 착수 시 확인할 경계는 [현재 아키텍처 상태](./architecture/current-state.md)에 정리했다.

## 근거를 읽는 순서

1. `AGENTS.md` — 작업 권한, 데이터·문서 경계와 저장소 규칙
2. `docs/markdown/01_요구사항정의서.md` — 현재 범위와 수용 기준
3. `docs/markdown/02_WBS.md` — 일정·담당·상태·evidence path
4. `docs/markdown/05_화면설계서.md` — 화면 계약과 중간발표 fixture 경로
5. `docs/markdown/03_프로젝트기획서.md` — 제품 맥락과 기획 단계 데이터 개념
6. 코드·테스트·설정 — 실제 구현 여부의 단일 증거

`docs/markdown/ai_docs/`는 AI 작성·외부 조사·과거 스냅샷 참고 자료다. 활성 번호 문서나 코드·테스트와 충돌할 때 이를 우선하지 않는다.

## 문서 지도

- [현재 아키텍처 상태](./architecture/current-state.md) — 실제 디렉터리 상태, 계획 구조, 구현 전 확인 항목
- [핵심 업무 흐름](./workflows/product-flows.md) — 기능 A/B, 6개 데모 화면, synthetic·권한·의사결정 경계
- [요구사항·화면·검증 추적](./workflows/traceability.md) — Baseline, WBS 상태, 화면 문서 동기화 위험, 테스트 기준
- [저장소 운영 통제](./operations/repository-controls.md) — 비밀·데이터 경계, hooks, OpenWiki의 Codex OAuth 운영 방식

## 변경 작업의 시작점

- 기능을 구현하거나 수정하기 전에는 [현재 아키텍처 상태](./architecture/current-state.md)의 계획과 구현 구분을 확인하고, 해당 기능의 [핵심 업무 흐름](./workflows/product-flows.md)과 [추적 기준](./workflows/traceability.md)을 함께 사용한다.
- synthetic 데이터 구현에서는 `is_synthetic`, `dataset_version`, `schema_version`, `generator_version`, `scenario_id`, `seed`, `virtual_as_of_date`, `data_cutoff` 기록과 적재 전/후 품질 검사를 요구사항대로 구현해야 한다.
- `.env`, API key, 실제 고객 데이터, `data/raw`, `data/processed` 생성 파일의 내용은 읽거나 위키에 복사하지 않는다. Git·문서·OpenWiki 작업의 통제는 [저장소 운영 통제](./operations/repository-controls.md)를 따른다.

## Source map

| 탐색 목적 | 우선 source |
|---|---|
| 범위·수용 기준 | `docs/markdown/01_요구사항정의서.md` |
| 일정·상태·담당·evidence path | `docs/markdown/02_WBS.md` |
| 화면·상태·데모 계약 | `docs/markdown/05_화면설계서.md` §0.6 |
| 제품 배경·기획 단계 데이터 개념 | `docs/markdown/03_프로젝트기획서.md` |
| 구현 증거 | `app/`, `src/`, `tests/`, `evals/`와 dependency/config/test 파일 |
| 데이터·Git·문서·OpenWiki 통제 | `AGENTS.md`, `.gitignore`, `.githooks/`, `openwiki/INSTRUCTIONS.md` |

## OpenWiki 갱신

OpenWiki 0.2.2는 로컬 `openai-chatgpt` provider로 ChatGPT/Codex OAuth 계정의 구독 사용량을 이용한다. 최초 설정과 갱신은 PowerShell에서 실행한다.

```powershell
$env:OPENWIKI_PROVIDER = "openai-chatgpt"
$env:OPENWIKI_TELEMETRY_DISABLED = "1"
openwiki code --init
openwiki code --update --print
```

OAuth credential은 `~/.openwiki/.env`에 저장하며 저장소나 CI로 복사하지 않는다. 실행 전 외부 전송 범위와 ChatGPT plan의 Codex 사용량을 확인한다. LangSmith tracing은 사용하지 않는다.

## Backlog

- **화면 설계 동기화** — `docs/markdown/01_요구사항정의서.md`의 `UI-001`~`005` 미결정 행과 `docs/markdown/05_화면설계서.md` §21: 활성 `REQ-*`/`P0-*`와 기존 `SCR-*` 추적 체계의 개정·유지 결정이 필요하다.
- **실행 가능한 개발 기준** — `app/`, `src/`, `tests/`, `evals/`: 코드·dependency manifest·schema·fixture·테스트가 없어 실제 실행/검증 명령을 문서화할 수 없다.
- **LLM·보안 확정** — 요구사항서 미결정 표: LLM 공급자·모델, 성능 목표, HTTPS·비밀번호 저장 수준이 확정되지 않았다.
