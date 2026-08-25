# Answervice Admin System

기존 Answervice 서비스와 코드, DB, Migration, 인증을 공유하지 않는 독립 관리자 시스템이다.

## 제공 기능

- 독립 관리자 로그인과 `ADMIN`, `VIEWER` Role
- 관리자 계정 목록, 생성, 수정, soft delete
- 마지막 활성 `ADMIN` 계정 보호
- PMS, POS, CRM, Facility, Banquet, App PostgreSQL, Trino, DataHub, Model API 상태 조회
- 관리자 로그인, 계정 변경, 연결 점검 감사 이력
- 감사 로그 20건 고정 페이지네이션
- DB Trigger로 감사 이벤트 수정과 삭제 차단

## 실행

PowerShell에서 전용 환경 파일을 만든다.

```powershell
Copy-Item admin/.env.example admin/.env
```

`admin/.env`의 비밀번호와 Secret을 실제 값으로 변경한 뒤 저장소 루트에서 실행한다.

```powershell
docker context use desktop-linux
docker --context desktop-linux compose -p answervice --env-file admin/.env -f admin/compose.yml up -d --build
```

관리자 화면:

```text
http://127.0.0.1:28080
```

종료:

```powershell
docker --context desktop-linux compose -p answervice --env-file admin/.env -f admin/compose.yml down
```

DB까지 초기화할 때만 명시적으로 volume을 제거한다.

```powershell
docker --context desktop-linux compose -p answervice --env-file admin/.env -f admin/compose.yml down -v
```

## 권한

| 기능 | ADMIN | VIEWER |
|---|---|---|
| 관리자 계정 조회 | 허용 | 허용 |
| 관리자 계정 생성·수정·삭제 | 허용 | 차단 |
| 연결 상태 조회 | 허용 | 허용 |
| 감사 로그 조회 | 허용 | 허용 |

## 독립성 경계

- 기존 Backend와 Frontend package를 import하지 않는다.
- 기존 App PostgreSQL에 table이나 migration을 추가하지 않는다.
- 연결 상태는 환경변수로 전달된 endpoint에 읽기 요청만 수행한다.
- 연결 등록, 수정, 삭제, SQL 실행 API는 존재하지 않는다.
- Admin System의 중단과 재시작은 기존 사용자 서비스에 영향을 주지 않는다.

## 운영 전 변경

- HTTPS 환경에서는 `ADMIN_COOKIE_SECURE=true`를 사용한다.
- Bootstrap 비밀번호는 최초 로그인 후 관리자 수정 화면에서 변경한다.
- DSN과 Secret이 포함된 `admin/.env`는 Git에 추가하지 않는다.
- Probe 계정은 대상 시스템에서 상태 조회에 필요한 최소 read-only 권한만 부여한다.
