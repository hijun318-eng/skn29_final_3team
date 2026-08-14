# ADR: 확정 Report의 HTML-to-PDF renderer

- 상태: Accepted
- 결정일: 2026-08-14

## 배경

현재 Backend와 `python:3.12-slim` 이미지에는 HTML-to-PDF 도구, Chromium, 한글 폰트가 없다. 브라우저에서 만든 PDF를 업로드하면 서버가 Report revision과 Artifact checksum을 독립적으로 동결할 수 없고, 클라이언트 환경에 따라 출력이 달라진다.

## 결정

Backend가 저장된 Report 블록과 승인된 Artifact snapshot으로 외부 resource가 없는 canonical HTML을 만들고, WeasyPrint 69로 PDF/A-3u를 생성한다. 이미지에는 WeasyPrint의 필수 Pango library와 Noto CJK font만 추가한다. renderer major version, canonical source checksum, HTML/PDF checksum, Artifact ID/checksum manifest를 Report revision과 함께 저장한다.

승인 순서는 `source read -> render -> transaction lock -> source checksum 재검증 -> HTML/PDF insert -> status update`이다. 어느 단계든 실패하면 Report는 draft로 남는다. 확정 document는 DB trigger와 권한으로 update/delete를 거부한다.

## 대안

- Chromium/Playwright: 브라우저와 sandbox 운영 비용이 크다.
- ReportLab: HTML/CSS와 동일한 layout을 재현하려면 별도 layout engine이 필요하다.
- Client PDF upload: 출력과 lineage를 서버가 보증할 수 없다.

## 운영 조건

WeasyPrint major upgrade는 PDF visual regression 후에만 수행한다. renderer는 HTTP/file/data URL fetch를 허용하지 않으며 inline HTML/CSS/SVG만 처리한다.

## 결정론 보장 범위

Canonical source checksum과 고정한 renderer version으로 승인 입력을 식별하고 감사할 수 있다. 다만 WeasyPrint의 font subsetting 결과가 별도 렌더링마다 byte-identical하다고 가정하지 않는다. 승인 시 한 번만 렌더링하고 그 PDF 원본 byte와 checksum을 수정 불가능하게 저장하며, 열람 API는 승인된 PDF를 재생성하지 않는다.
