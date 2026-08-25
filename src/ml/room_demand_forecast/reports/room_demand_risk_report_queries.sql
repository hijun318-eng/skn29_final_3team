-- Local SQLite report queries over reviewed artifact tables.
SELECT wape AS test_wape
FROM test_metrics
WHERE model = 'XGBRegressor'
  AND split = 'TEST'
  AND prediction_type = 'clipped';

SELECT target_coverage, actual_coverage, mean_width, row_count
FROM interval_metrics;

SELECT wape AS hidden_wape, mae, within_3_rooms, interval_coverage, row_count
FROM hidden_qa;

SELECT scenario, feature_count, mae, wape, within_3_rooms, split
FROM feature_ablation_metrics
WHERE split = 'TEST'
ORDER BY CASE scenario
  WHEN 'FULL' THEN 1
  WHEN 'NO_BOOKING_ON_HAND' THEN 2
  WHEN 'NO_RECENT_DEMAND' THEN 3
  WHEN 'NO_SCALE_PROXY' THEN 4
  ELSE 5
END;

SELECT risk_id, risk, status, evidence, control
FROM risk_register
ORDER BY risk_id;

SELECT CASE
  WHEN SUM(CASE WHEN status IN ('WARN', 'OPEN') THEN 1 ELSE 0 END) > 0
    THEN 'PASS_WITH_LIMITATIONS'
  ELSE 'PASS'
END AS final_status
FROM risk_register;
