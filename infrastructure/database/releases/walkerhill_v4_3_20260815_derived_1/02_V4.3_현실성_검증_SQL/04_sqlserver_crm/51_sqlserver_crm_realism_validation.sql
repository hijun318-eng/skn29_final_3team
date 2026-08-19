-- Walkerhill V4.3 CRM and VOC realism pilot. SQL Server 2022. Read-only.

;WITH scored AS (
  SELECT r.hotel_code,r.touchpoint,r.source_channel,r.visit_cohort,r.rating_overall,
         PERCENTILE_CONT(0.10) WITHIN GROUP(ORDER BY CONVERT(float,r.rating_overall))
           OVER(PARTITION BY r.hotel_code,r.touchpoint,r.source_channel,r.visit_cohort) AS p10_rating,
         PERCENTILE_CONT(0.50) WITHIN GROUP(ORDER BY CONVERT(float,r.rating_overall))
           OVER(PARTITION BY r.hotel_code,r.touchpoint,r.source_channel,r.visit_cohort) AS median_rating,
         PERCENTILE_CONT(0.90) WITHIN GROUP(ORDER BY CONVERT(float,r.rating_overall))
           OVER(PARTITION BY r.hotel_code,r.touchpoint,r.source_channel,r.visit_cohort) AS p90_rating
  FROM [walkerhill_v4_3].[crm_voc_reviews] r
)
SELECT hotel_code,touchpoint,source_channel,visit_cohort,
       COUNT(*) AS review_count,MIN(rating_overall) AS min_rating,
       CASE WHEN COUNT(*)>=30 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       AVG(CONVERT(decimal(10,4),rating_overall)) AS average_rating,
       MAX(p10_rating) AS p10_rating,MAX(median_rating) AS median_rating,MAX(p90_rating) AS p90_rating,
       MAX(rating_overall) AS max_rating,STDEV(CONVERT(float,rating_overall)) AS stddev_rating
FROM scored
GROUP BY hotel_code,touchpoint,source_channel,visit_cohort
ORDER BY hotel_code,touchpoint,source_channel,visit_cohort;

SELECT r.hotel_code,r.touchpoint,a.primary_topic,a.sentiment_label,a.urgency_level,
       COUNT(*) AS review_count,
       CASE WHEN COUNT(*)>=30 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       AVG(CONVERT(decimal(10,4),r.rating_overall)) AS average_rating,
       AVG(a.sentiment_score) AS average_sentiment,
       SUM(CASE WHEN a.requires_followup=1 THEN 1 ELSE 0 END) AS followup_count,
       SUM(CASE WHEN a.requires_followup=1 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS followup_rate
FROM [walkerhill_v4_3].[crm_voc_reviews] r
JOIN [walkerhill_v4_3].[crm_voc_analysis] a ON a.voc_review_id=r.voc_review_id
GROUP BY r.hotel_code,r.touchpoint,a.primary_topic,a.sentiment_label,a.urgency_level
ORDER BY r.hotel_code,r.touchpoint,a.primary_topic,a.sentiment_label,a.urgency_level;

SELECT TOP(100) review_text_original,COUNT(*) AS duplicate_count,
       MIN(rating_overall) AS min_rating,MAX(rating_overall) AS max_rating,
       COUNT(DISTINCT hotel_code) AS hotel_count,COUNT(DISTINCT touchpoint) AS touchpoint_count
FROM [walkerhill_v4_3].[crm_voc_reviews]
GROUP BY review_text_original
HAVING COUNT(*)>1
ORDER BY duplicate_count DESC,review_text_original;

;WITH normalized AS (
  SELECT LOWER(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(review_text_original)),N' ',N''),N'.',N''),N',',N''),N'!',N'')) AS normalized_text,
         hotel_code,touchpoint,rating_overall
  FROM [walkerhill_v4_3].[crm_voc_reviews]
)
SELECT TOP(100) normalized_text,COUNT(*) AS normalized_duplicate_count,
       COUNT(DISTINCT hotel_code) AS hotel_count,COUNT(DISTINCT touchpoint) AS touchpoint_count,
       MIN(rating_overall) AS min_rating,MAX(rating_overall) AS max_rating
FROM normalized
GROUP BY normalized_text
HAVING COUNT(*)>1
ORDER BY normalized_duplicate_count DESC,normalized_text;

;WITH analysis_counts AS (
  SELECT voc_review_id,COUNT(*) AS analysis_count
  FROM [walkerhill_v4_3].[crm_voc_analysis] GROUP BY voc_review_id
), checks AS (
  SELECT 'rating_out_of_range' AS check_name,COUNT_BIG(*) AS violation_count
  FROM [walkerhill_v4_3].[crm_voc_reviews]
  WHERE rating_overall NOT BETWEEN 1 AND 5 OR rating_service NOT BETWEEN 1 AND 5
     OR rating_value NOT BETWEEN 1 AND 5
  UNION ALL
  SELECT 'sentiment_rating_contradiction',COUNT_BIG(*)
  FROM [walkerhill_v4_3].[crm_voc_reviews] r
  JOIN [walkerhill_v4_3].[crm_voc_analysis] a ON a.voc_review_id=r.voc_review_id
  WHERE (r.rating_overall<=2 AND a.sentiment_label='POSITIVE')
     OR (r.rating_overall>=4 AND a.sentiment_label='NEGATIVE')
  UNION ALL
  SELECT 'source_submission_time_violation',COUNT_BIG(*)
  FROM [walkerhill_v4_3].[crm_voc_reviews]
  WHERE CONVERT(date,submitted_at)<source_business_date
  UNION ALL
  SELECT 'touchpoint_dimension_mismatch',COUNT_BIG(*)
  FROM [walkerhill_v4_3].[crm_voc_reviews]
  WHERE (touchpoint='FNB' AND outlet_id IS NULL)
     OR (touchpoint='FACILITY' AND facility_id IS NULL)
     OR (touchpoint NOT IN('FNB') AND outlet_id IS NOT NULL)
     OR (touchpoint NOT IN('FACILITY') AND facility_id IS NOT NULL)
  UNION ALL
  SELECT 'voc_analysis_cardinality_mismatch',COUNT_BIG(*)
  FROM [walkerhill_v4_3].[crm_voc_reviews] r
  LEFT JOIN analysis_counts a ON a.voc_review_id=r.voc_review_id
  WHERE ISNULL(a.analysis_count,0)<>1
  UNION ALL
  SELECT 'member_points_negative',COUNT_BIG(*)
  FROM [walkerhill_v4_3].[crm_members] WHERE points_balance<0
)
SELECT check_name,violation_count,
       CASE WHEN violation_count=0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM checks ORDER BY check_name;

SELECT m.current_tier_code,m.member_status,
       COUNT(*) AS members,MIN(m.points_balance) AS min_points,
       AVG(CONVERT(decimal(18,2),m.points_balance)) AS average_points,
       MAX(m.points_balance) AS max_points,STDEV(CONVERT(float,m.points_balance)) AS stddev_points
FROM [walkerhill_v4_3].[crm_members] m
GROUP BY m.current_tier_code,m.member_status
ORDER BY m.current_tier_code,m.member_status;
