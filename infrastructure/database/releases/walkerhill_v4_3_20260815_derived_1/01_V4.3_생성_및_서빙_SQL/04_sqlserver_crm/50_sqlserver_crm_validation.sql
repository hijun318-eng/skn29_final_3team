USE [crm_db];
GO
-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=SQL Server 2022; domain=CRM; script_type=VALIDATION_READONLY; execution_order=50
-- dependency=40_sqlserver_crm_constraints_indexes.sql; execution_default=NOT_RUN

SELECT dataset,row_count,expected_min,expected_max,
       CASE WHEN row_count BETWEEN expected_min AND expected_max THEN 'PASS' ELSE 'FAIL' END status
FROM (VALUES
 ('crm_membership_tiers',(SELECT COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_membership_tiers]),3,3),
 ('crm_members',(SELECT COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_members]),150000,150000),
 ('crm_member_grade_history',(SELECT COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_member_grade_history]),192000,192000),
 ('crm_point_transactions',(SELECT COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_point_transactions]),480000,480000),
 ('crm_customer_map',(SELECT COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_customer_map]),110000,110000),
 ('crm_voc_reviews',(SELECT COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews]),80972,80972),
 ('crm_voc_analysis',(SELECT COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_analysis]),80972,80972)
) v(dataset,row_count,expected_min,expected_max);

SELECT 'orphan_grade_member' check_name,COUNT_BIG(*) violations FROM [walkerhill_v4_3].[crm_member_grade_history] h LEFT JOIN [walkerhill_v4_3].[crm_members] m ON m.member_no=h.member_no WHERE m.member_no IS NULL
UNION ALL SELECT 'orphan_point_member',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_point_transactions] p LEFT JOIN [walkerhill_v4_3].[crm_members] m ON m.member_no=p.member_no WHERE m.member_no IS NULL
UNION ALL SELECT 'point_before_member_join',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_point_transactions] p JOIN [walkerhill_v4_3].[crm_members] m ON m.member_no=p.member_no WHERE p.event_at<m.joined_at
UNION ALL SELECT 'point_outside_release_period_or_lag',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_point_transactions] WHERE event_at<'2024-01-01T00:00:00+09:00' OR event_at>='2026-09-02T00:00:00+09:00'
UNION ALL SELECT 'journey_point_coverage',ABS(COUNT_BIG(*)-972) FROM [walkerhill_v4_3].[crm_point_transactions] WHERE related_source='POS_ORDER' AND related_id BETWEEN 'O_0000000001' AND 'O_0000002914' AND (CONVERT(bigint,SUBSTRING(related_id,3,10))-1)%3=0
UNION ALL SELECT 'journey_point_semantic_mismatch',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_point_transactions]
 WHERE related_source='POS_ORDER' AND related_id BETWEEN 'O_0000000001' AND 'O_0000002914' AND (CONVERT(bigint,SUBSTRING(related_id,3,10))-1)%3=0
   AND (related_id<>CONCAT('O_',RIGHT(REPLICATE('0',10)+CONVERT(varchar(10),(CONVERT(int,SUBSTRING(member_no,3,9))*3)-2),10))
     OR points_delta<>[walkerhill_v4_3].[v43_journey_pos_eligible_amount](CONVERT(int,SUBSTRING(member_no,3,9)))*5/100)
UNION ALL SELECT 'crm_deterministic_known_vector',CASE WHEN ABS([walkerhill_v4_3].[v43_u01]('known-vector')-CONVERT(decimal(19,18),0.956312478577619107))<CONVERT(decimal(19,18),0.000000000000000002) THEN 0 ELSE 1 END
UNION ALL SELECT 'orphan_voc_member',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews] v LEFT JOIN [walkerhill_v4_3].[crm_members] m ON m.member_no=v.member_no WHERE v.member_no IS NOT NULL AND m.member_no IS NULL
UNION ALL SELECT 'orphan_voc_analysis',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews] v LEFT JOIN [walkerhill_v4_3].[crm_voc_analysis] a ON a.voc_review_id=v.voc_review_id WHERE a.voc_review_id IS NULL
UNION ALL SELECT 'voc_analysis_before_submission',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_analysis] a JOIN [walkerhill_v4_3].[crm_voc_reviews] v ON v.voc_review_id=a.voc_review_id WHERE a.analyzed_at<v.submitted_at
UNION ALL SELECT 'voc_sentiment_rating_mismatch',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews] v JOIN [walkerhill_v4_3].[crm_voc_analysis] a ON a.voc_review_id=v.voc_review_id WHERE a.sentiment_label<>CASE WHEN v.rating_overall<=2 THEN 'NEGATIVE' WHEN v.rating_overall=3 THEN 'NEUTRAL' ELSE 'POSITIVE' END
UNION ALL SELECT 'voc_followup_rating_mismatch',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews] v JOIN [walkerhill_v4_3].[crm_voc_analysis] a ON a.voc_review_id=v.voc_review_id WHERE a.requires_followup<>CASE WHEN v.rating_overall<=2 THEN 1 ELSE 0 END
UNION ALL SELECT 'voc_outside_release_period_or_lag',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews] WHERE submitted_at<'2024-01-01T00:00:00+09:00' OR submitted_at>='2026-09-02T00:00:00+09:00'
UNION ALL SELECT 'voc_source_date_outside_release',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews] WHERE source_business_date<'2024-01-01' OR source_business_date>'2026-08-31'
UNION ALL SELECT 'voc_submission_lag_mismatch',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews]
 WHERE CONVERT(date,SWITCHOFFSET(submitted_at,'+09:00'))<source_business_date
    OR CONVERT(date,SWITCHOFFSET(submitted_at,'+09:00'))>DATEADD(day,1,source_business_date)
UNION ALL SELECT 'voc_source_metadata_mismatch',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews]
 WHERE (related_source='PMS_STAY' AND (touchpoint NOT IN('CHECKOUT','ROOM') OR related_id NOT LIKE 'S[_]%'))
    OR (related_source='POS_ORDER' AND (touchpoint<>'FNB' OR related_id NOT LIKE 'O[_]%' OR outlet_id IS NULL))
    OR (related_source='FACILITY_USAGE' AND (touchpoint<>'FACILITY' OR related_id NOT LIKE 'FUEV[_]%' OR facility_id IS NULL))
    OR (related_source='BANQUET_BOOKING' AND (touchpoint<>'BANQUET' OR related_id NOT LIKE 'BE[_]%'))
    OR (related_source='NONE' AND (touchpoint<>'OVERALL' OR related_id IS NOT NULL))
UNION ALL SELECT 'generic_voc_reserved_journey_order_collision',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews]
 WHERE voc_review_id NOT LIKE 'VR_JOURNEY[_]%' AND related_source='POS_ORDER'
   AND related_id BETWEEN 'O_0000000001' AND 'O_0000002916'
UNION ALL SELECT 'journey_voc_coverage',ABS(COUNT_BIG(*)-972) FROM [walkerhill_v4_3].[crm_voc_reviews] WHERE voc_review_id LIKE 'VR_JOURNEY[_]%'
UNION ALL SELECT 'journey_voc_semantic_mismatch',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_voc_reviews]
 WHERE voc_review_id LIKE 'VR_JOURNEY[_]%' AND (related_source<>'PMS_STAY' OR related_id<>CONCAT('S_JOURNEY_',RIGHT(voc_review_id,10))
   OR member_no<>CONCAT('M_',RIGHT(REPLICATE('0',9)+CONVERT(varchar(9),CONVERT(int,RIGHT(voc_review_id,10))),9)))
UNION ALL SELECT 'overlapping_grade_period',COUNT_BIG(*) FROM [walkerhill_v4_3].[crm_member_grade_history] a JOIN [walkerhill_v4_3].[crm_member_grade_history] b ON a.member_no=b.member_no AND a.grade_history_id<b.grade_history_id AND a.valid_from<COALESCE(b.valid_to,'9999-12-31') AND b.valid_from<COALESCE(a.valid_to,'9999-12-31');

;WITH b AS (SELECT member_no,SUM(points_delta) expected_balance FROM [walkerhill_v4_3].[crm_point_transactions] GROUP BY member_no)
SELECT 'point_balance_reconciliation' check_name,COUNT_BIG(*) violations
FROM [walkerhill_v4_3].[crm_members] m LEFT JOIN b ON b.member_no=m.member_no
WHERE m.points_balance<>COALESCE(b.expected_balance,0);

;WITH running AS (
 SELECT member_no,event_at,point_txn_id,
        SUM(points_delta) OVER(PARTITION BY member_no ORDER BY event_at,point_txn_id ROWS UNBOUNDED PRECEDING) running_balance
 FROM [walkerhill_v4_3].[crm_point_transactions]
)
SELECT 'negative_running_point_balance' check_name,COUNT_BIG(*) violations
FROM running WHERE running_balance<0;

SELECT 'voc_distribution_bounds' check_name,
       CASE WHEN AVG(CONVERT(float,rating_overall)) BETWEEN 3.50 AND 4.40
                  AND AVG(CASE WHEN rating_overall<=2 THEN 1.0 ELSE 0.0 END) BETWEEN 0.05 AND 0.25
                  AND COUNT(DISTINCT review_text_original)>=50000 THEN 0 ELSE 1 END violations,
       AVG(CONVERT(decimal(10,4),rating_overall)) avg_rating,
       AVG(CONVERT(decimal(10,4),CASE WHEN rating_overall<=2 THEN 1.0 ELSE 0.0 END)) low_rating_share,
       COUNT(DISTINCT review_text_original) distinct_review_texts
FROM [walkerhill_v4_3].[crm_voc_reviews];

SELECT hotel_code,source_channel,COUNT_BIG(*) reviews,AVG(CONVERT(decimal(10,4),rating_overall)) avg_rating,
       SUM(CASE WHEN rating_overall<=2 THEN 1 ELSE 0 END) low_rating_reviews
FROM [walkerhill_v4_3].[crm_voc_reviews]
GROUP BY hotel_code,source_channel ORDER BY hotel_code,source_channel;

SELECT TOP (200) v.submitted_at,v.hotel_code,v.source_channel,v.touchpoint,v.rating_overall,
       v.review_title,v.review_text_original,a.sentiment_label,a.primary_topic,a.urgency_level,a.requires_followup
FROM [walkerhill_v4_3].[crm_voc_reviews] v
JOIN [walkerhill_v4_3].[crm_voc_analysis] a ON a.voc_review_id=v.voc_review_id
ORDER BY v.submitted_at DESC,v.voc_review_id;

SELECT current_tier_code,member_status,COUNT_BIG(*) members,AVG(CONVERT(float,points_balance)) avg_points
FROM [walkerhill_v4_3].[crm_members] GROUP BY current_tier_code,member_status ORDER BY current_tier_code,member_status;
GO
