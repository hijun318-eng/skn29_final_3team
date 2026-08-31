-- release_id=walkerhill-member-revenue-physical-v1.20260830.1
-- source_release_id=walkerhill-analysis-semantics-v1.20260827.1
-- target_dbms=Trino 483; target_schema=serving.analytics_v4_3
-- state=REVIEW_REQUIRED; script_type=MATERIALIZED_VIEW_REFRESH; execution_order=20; execution_default=NOT_RUN
-- purpose=두 원천 도메인의 물리 집계를 독립 쿼리로 갱신해 하나의 대형 교차 도메인 refresh plan을 만들지 않는다.

REFRESH MATERIALIZED VIEW serving.analytics_v4_3.member_room_revenue_daily;
REFRESH MATERIALIZED VIEW serving.analytics_v4_3.member_fnb_revenue_daily;
