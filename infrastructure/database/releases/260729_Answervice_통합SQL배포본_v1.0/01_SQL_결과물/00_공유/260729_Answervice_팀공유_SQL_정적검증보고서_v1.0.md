# Answervice 팀공유 SQL 결과물 정적 검증보고서 v1.0

- SQL 파일: 21개
- 정적 검증: PASS
- 실제 DB 실행: NOT_RUN
- Trino Query: NOT_RUN
- P2 SQL: 0개

## 역할별 산출물

- R2 Source DDL: 5개
- R2 Source seed: 5개
- R2 Trino View: 1개
- R4 Application DDL: 1개
- R5 실행형 DDL: 0개, read-only 검토 SQL만 포함
- R1 실행형 DDL: 0개, read-only Gate만 포함
- ML Source write SQL: 0개

## 파일 검증

- PASS `ML_작업카드_객실수요예측/sql/260729_room_demand_feature_query_all_sources_v1.4.sql`
- PASS `ML_작업카드_객실수요예측/sql/260729_room_demand_feature_query_pms_only_v1.4.sql`
- PASS `ML_작업카드_객실수요예측/validation/260729_room_demand_source_leakage_preflight.sql`
- PASS `R1_박준희_통합검증/validation/260729_00_r1_application_integration_gate.sql`
- PASS `R1_박준희_통합검증/validation/260729_01_r1_trino_integration_gate.sql`
- PASS `R2_정승_Source_Seed_Trino/ddl/260729_01_hotel_pms_postgresql_ddl.sql`
- PASS `R2_정승_Source_Seed_Trino/ddl/260729_02_hotel_pos_mysql_ddl.sql`
- PASS `R2_정승_Source_Seed_Trino/ddl/260729_03_hotel_crm_sqlserver_ddl.sql`
- PASS `R2_정승_Source_Seed_Trino/ddl/260729_04_hotel_facility_clickhouse_ddl.sql`
- PASS `R2_정승_Source_Seed_Trino/ddl/260729_05_hotel_banquet_postgresql_ddl.sql`
- PASS `R2_정승_Source_Seed_Trino/seed/260729_01_pms_postgresql_2022_2026_v2.3.sql`
- PASS `R2_정승_Source_Seed_Trino/seed/260729_02_pos_mysql_2022_2026_v2.3.sql`
- PASS `R2_정승_Source_Seed_Trino/seed/260729_03_crm_sqlserver_2022_2026_v2.3.sql`
- PASS `R2_정승_Source_Seed_Trino/seed/260729_04_facility_clickhouse_2022_2026_v2.3.sql`
- PASS `R2_정승_Source_Seed_Trino/seed/260729_05_banquet_postgresql_2022_2026_v2.3.sql`
- PASS `R2_정승_Source_Seed_Trino/trino/260729_06_trino_analytics_views.sql`
- PASS `R2_정승_Source_Seed_Trino/validation/260729_07_r2_source_trino_readonly_validation.sql`
- PASS `R4_김재홍_ApplicationDB/ddl/260729_00_answervice_app_postgresql_p0_p1.sql`
- PASS `R4_김재홍_ApplicationDB/validation/260729_00_answervice_app_preflight_postgresql.sql`
- PASS `R4_김재홍_ApplicationDB/validation/260729_01_answervice_app_postflight_validation.sql`
- PASS `R5_송민지_Report_Migration_초안/review/260729_R5_report_schema_contract_review_READ_ONLY.sql`

## 판정

파일 생성과 정적 계약 검증만 완료했다. 엔진별 실제 parser·DB catalog·권한·데이터 실행 결과는 확인하지 않았으므로 공유 환경 적용 판정은 `CONDITIONAL_PASS`다.
각 담당자는 자신의 폴더만 수정하고, 다른 역할 산출물 변경은 변경요청서로 전달해야 한다.