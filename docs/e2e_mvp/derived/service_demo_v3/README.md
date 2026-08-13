# service-demo-v3 deterministic 5DB dataset

## 범위

이 폴더의 SQL은 service-demo-v3 전용 fresh volume에만 적재한다. 기존 업무 DDL, 업무 테이블, 기존 volume, hotel-synthetic-db, answervice-v3-smoke는 변경하지 않는다. 데이터는 SYNTHETIC_HOTEL_001의 교육용 결정적 합성 데이터이며 실제 워커힐 또는 고객 운영 데이터가 아니다.

## 공통 계약

| 항목 | 값 |
|---|---|
| deterministic seed | 290613 |
| property | SYNTHETIC_HOTEL_001 |
| event period | 2025-01-01 이상, 2026-08-01 미만 |
| snapshot | 2026-08-01T00:00:00+09:00 |
| synthetic flag | true 또는 1 |
| period status | SYNTHETIC_ACTUAL_LIKE |
| interval rule | 모든 유효기간은 [start, end) |

## 생성 목표

| Source | 목표 규모 |
|---|---:|
| PMS | guests 16,000, reservations 43,200, completed stays 37,800, room inventory 2,308 |
| POS | 9 stores, 100,000 orders, 주문당 1~6 items |
| CRM | 13,500 members, maps 11,475, point transactions 45,000 |
| Banquet | 2,400 bookings 및 상태별 revenue |
| Facility | master 20, events 20,000, staffing/resource 577일 |

## 검증 원칙

각 10~15번 validation은 형식적 성공값이 아닌 실제 위반 행을 반환한다. 20~23번 Golden SQL은 Trino에서 실행하고, canonical TSV와 SHA-256은 실제 실행 뒤에만 manifest 및 load_verification에 기록한다.
