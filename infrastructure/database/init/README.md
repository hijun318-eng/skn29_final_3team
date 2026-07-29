# 초기화 파일 매핑

`init/`은 서비스별 초기화 구성을 확인하기 위한 논리 구조다. 실제 실행 파일은 역할을 중복하지 않도록 `sql/ddl`, `sql/data`, `security`에 한 번만 보관하고 `compose.yml`이 직접 마운트한다.

| 서비스 | DDL | 합성 데이터 | 권한 |
|---|---|---|---|
| app-postgres | `sql/ddl/00_answervice_app_postgresql.sql` | `sql/app/10-reference-data.sql` | `security/provision-app-postgres.sh` |
| pms-postgres | `sql/ddl/01_hotel_pms_postgresql.sql` | `sql/data/260728_01_pms_postgresql_2022_2026_v2.2.sql` | `security/provision-source-postgres.sh` |
| banquet-postgres | `sql/ddl/05_hotel_banquet_postgresql.sql` | `sql/data/260728_05_banquet_postgresql_2022_2026_v2.2.sql` | `security/provision-source-postgres.sh` |
| pos-mysql | `sql/ddl/02_hotel_pos_mysql.sql` | `sql/data/260728_02_pos_mysql_2022_2026_v2.2.sql` | `security/provision-pos-mysql.sh` |
| crm-mssql | `sql/ddl/03_hotel_crm_sqlserver.sql` | `sql/data/260728_03_crm_sqlserver_2022_2026_v2.2.sql` | `security/provision-crm-mssql.sh` |
| facility-clickhouse | `sql/ddl/04_hotel_facility_clickhouse.sql` | `sql/data/260728_04_facility_clickhouse_2022_2026_v2.2.sql` | `security/provision-facility-clickhouse.sh` |
