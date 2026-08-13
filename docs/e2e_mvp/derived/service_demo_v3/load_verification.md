# service-demo-v3 load verification

| 항목 | 상태 | 실제값 |
|---|---|---|
| fresh volumes | PASS | PMS·Facility는 수정 후 전용 volume 재생성, POS·CRM·Banquet는 2026-08-12 생성 전용 volume 확인 |
| PMS/POS/CRM/Banquet/Facility/Trino | PASS | 6개 컨테이너 healthy, Trino state `ACTIVE` |
| PMS | PASS | inventory 2,308 / guests 16,000 / reservations 43,200 / stays 37,800 |
| POS | PASS | stores 9 / orders 100,000 / items per order min 4, max 5 |
| CRM | PASS | members 13,500 / maps 11,475 / point transactions 45,000 |
| Banquet | PASS | bookings 2,400 |
| Facility | PASS | master 20 / events 20,000 / staffing 5,770 / resource 4,616 |
| validation 10~15 invalid rows | PASS | PMS 0 / POS 0 / CRM 0 / Banquet 0 / Facility 0 / cross-source 0 |
| Trino read-only write probes | PASS | 5 Source 모두 `Access Denied`, 전후 seed metadata count 동일 |
| Golden 20 | PASS | 864 rows / `a1b101528e4098b8c523c3a6f7eb03546fec9445a55e432e873dde7eb43bfffe` |
| Golden 21 | PASS | 4 rows / `13e0eb9d2f56357c780a1d768a3e44b51852d1280ef3ae2d05835d144396b97e` |
| Golden 22 | PASS | 4 rows / `462c1aae3a490da10f4340f6da99f55b96d8ab6e205e74b6bf171c8031e7c96e` |
| Golden 23 | PASS | 5 rows / `50e3465581d6032ab6e962a85cfb4e5182965a1f51afa0c302130339009070e9` |
| deterministic repeat | PASS | 20~23 모두 연속 2회 canonical SHA-256 일치 |

검증 시각: 2026-08-12T18:56:33+09:00. PMS stay의 checkout이 inventory 범위를 벗어나지 않는지 추가 검증했고 위반은 0건이었다. 같은 결과를 공식 `hotel-synthetic-db`의 새 versioned volume 5개에 적용했으며 service-demo와 공식 Trino의 Golden 20~23 결과가 두 번 연속 동일했다. 기존 공식 volume은 rollback 대상으로 보존했다. DataHub v1.7.0 재ingestion과 8개 AssetBinding 검증도 통과했지만, 이 기록만으로 제품 P0 전체 완료를 의미하지는 않는다.
