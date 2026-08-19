-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING_MEMBERSHIP; script_type=VIEW; execution_order=22
-- dependency=crm.walkerhill_v4_3; execution_default=NOT_RUN

CREATE OR REPLACE VIEW serving.analytics_v4_3.membership_daily AS
SELECT CAST(event_at AT TIME ZONE 'Asia/Seoul' AS date) business_date,
       COUNT(*) point_transactions,COUNT(DISTINCT member_no) active_members,
       SUM(CASE WHEN points_delta>0 THEN points_delta ELSE 0 END) points_earned,
       -SUM(CASE WHEN txn_type='REDEEM' THEN points_delta ELSE 0 END) points_redeemed,
       -SUM(CASE WHEN txn_type='EXPIRE' THEN points_delta ELSE 0 END) points_expired,
       SUM(points_delta) net_points_delta
FROM crm.walkerhill_v4_3.crm_point_transactions GROUP BY 1;
COMMENT ON VIEW serving.analytics_v4_3.membership_daily IS '영업일 단위 합성 멤버십 포인트 적립·사용·만료 활동';
COMMENT ON COLUMN serving.analytics_v4_3.membership_daily.business_date IS '포인트 거래의 한국 표준시 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.membership_daily.point_transactions IS '일별 포인트 원장 행 수';
COMMENT ON COLUMN serving.analytics_v4_3.membership_daily.active_members IS '일별 포인트 변동이 있었던 중복 제거 합성 회원 수';
COMMENT ON COLUMN serving.analytics_v4_3.membership_daily.points_earned IS '양수 적립 포인트 합계';
COMMENT ON COLUMN serving.analytics_v4_3.membership_daily.points_redeemed IS '사용 포인트의 절대값 합계';
COMMENT ON COLUMN serving.analytics_v4_3.membership_daily.points_expired IS '만료 포인트의 절대값 합계';
COMMENT ON COLUMN serving.analytics_v4_3.membership_daily.net_points_delta IS '적립에서 사용·만료를 차감한 순변동';
