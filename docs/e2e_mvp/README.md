# Answervice MVP E2E 참고 문서

> **문서 상태: SUPPORTING / NON-NORMATIVE**
> 현재 제품 기준은 [`../README.md`](../README.md)와 [`../product/`](../product/)의 4개 문서다. 이 폴더는 원문·과거 E2E 계약·실행 이력을 보존한다. 과거 완료 상태를 현재 V4.1 완료 증거로 사용하지 않는다.

## 현재 작업의 읽는 순서

1. `../product/00_기획서.md`
2. `../product/01_PRD.md`
3. `../product/02_유저플로우.md`
4. `../product/03_아키텍처.md`

## 이 폴더를 참고할 때의 읽는 순서

1. 보존 원문이 필요하면 `source/`에서 사용자가 지정한 00~04를 읽는다.
2. 과거 contract가 필요하면 `derived/01_MVP_PRD.md` → `02_Golden_Path_유저플로우.md`를 읽되, 아키텍처는 과거 사본을 두지 않고 [`../product/03_아키텍처.md`](../product/03_아키텍처.md)만 사용한다.
3. 과거 진행 기록과 RunPod 운영 가이드는 현재 작업 트리에서 제거됐으므로 현재 코드·runtime에서 다시 확인한다.

원문 사이에 범위 차이가 있으면 현재 `docs/product/` 계약을 우선한다. 원문의 보안 경계, read-only, G1·G2·G3, Definition/Run/Result 분리는 현재 문서가 명시적으로 대체하지 않는 한 보존한다.

## 정리 문서

| 파일 | 용도 |
|---|---|
| `derived/01_MVP_PRD.md` | 과거 MVP 범위와 완료 조건 |
| `derived/02_Golden_Path_유저플로우.md` | 과거 화면부터 분석 결과까지의 정상·실패 흐름 |

## 고정 원문

아래 SHA-256은 2026-08-12에 사용자가 제공한 파일을 그대로 복사한 값이다.

```text
d257c7222279d698eaab2be0ef7f98b7bb2003a4ef61b3e8c836284578355f5f  00_Answervice_프로젝트_기획서.md
63261f0ef888a7c57c9a73d4095b8766c9b8eac65d0c735b6395855fef22f097  01_Answervice_데이터_분석_Core_설계.md
64b775512fdedd87bbd88b2a56550d4417d9d1c19192820e342a943b988d95e9  02_Answervice_sLLM_모델_학습_평가.md
19e2b66630d7d9ca62f8340992b10106560481a9b7dad29ff1b2d881a3afe88d  03_Answervice_구현_운영_검증.md
d4752286098dde36e2217e8f7abb2904fd319c0a454598838ef4899cc3dca571  04_Answervice_단계별_구현_가이드.md
```

외부 모델 ZIP은 크기와 weight 때문에 저장소에 복사하지 않으며 현재 runtime 증거로 간주하지 않는다.
