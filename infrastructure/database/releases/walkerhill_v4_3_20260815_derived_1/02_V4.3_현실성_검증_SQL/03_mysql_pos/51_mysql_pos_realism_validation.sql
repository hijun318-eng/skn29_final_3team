-- Walkerhill V4.3 POS realism pilot. MySQL 8.4. Read-only.
-- Holiday segmentation is performed in the Trino script because the POS source has no holiday column.

WITH base AS (
  SELECT x.hotel_code,x.outlet_category,o.order_id,o.business_date,o.service_period,o.net_amount,
         CASE WHEN WEEKDAY(o.business_date)=4 THEN 'FRIDAY'
              WHEN WEEKDAY(o.business_date)=5 THEN 'SATURDAY'
              ELSE 'SUN_THU' END AS room_rate_day_type,
         CASE WHEN o.linked_stay_id IS NULL THEN 'NON_STAY' ELSE 'IN_STAY' END AS stay_link_type
  FROM walkerhill_v4_3.pos_orders o
  JOIN walkerhill_v4_3.pos_outlets x ON x.outlet_id=o.outlet_id
  WHERE o.order_status<>'VOID'
), ranked AS (
  SELECT b.*,
         ROW_NUMBER() OVER(PARTITION BY hotel_code,outlet_category,room_rate_day_type,stay_link_type ORDER BY net_amount) AS rn,
         COUNT(*) OVER(PARTITION BY hotel_code,outlet_category,room_rate_day_type,stay_link_type) AS n
  FROM base b
)
SELECT hotel_code,outlet_category,room_rate_day_type,stay_link_type,
       MAX(n) AS order_count,MIN(net_amount) AS min_net_krw,AVG(net_amount) AS average_net_krw,
       CASE WHEN MAX(n)>=30 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       MIN(CASE WHEN rn>=CEIL(n*0.10) THEN net_amount END) AS p10_net_krw,
       MIN(CASE WHEN rn>=CEIL(n*0.50) THEN net_amount END) AS median_net_krw,
       MIN(CASE WHEN rn>=CEIL(n*0.90) THEN net_amount END) AS p90_net_krw,
       MAX(net_amount) AS max_net_krw,STDDEV_SAMP(net_amount) AS stddev_net_krw
FROM ranked
GROUP BY hotel_code,outlet_category,room_rate_day_type,stay_link_type
ORDER BY hotel_code,outlet_category,room_rate_day_type,stay_link_type;

WITH tendered AS (
  SELECT x.hotel_code,x.outlet_category,
         CASE WHEN o.linked_stay_id IS NULL THEN 'NON_STAY' ELSE 'IN_STAY' END AS stay_link_type,
         CASE WHEN o.net_amount<50000 THEN 'LT_50K'
              WHEN o.net_amount<150000 THEN '50K_150K'
              WHEN o.net_amount<300000 THEN '150K_300K' ELSE 'GE_300K' END AS amount_band,
         p.tender_type,p.transaction_type,p.signed_amount
  FROM walkerhill_v4_3.pos_payment_lines p
  JOIN walkerhill_v4_3.pos_orders o ON o.order_id=p.order_id
  JOIN walkerhill_v4_3.pos_outlets x ON x.outlet_id=o.outlet_id
)
SELECT hotel_code,outlet_category,stay_link_type,amount_band,tender_type,
       COUNT(*) AS payment_lines,
       CASE WHEN COUNT(*)>=30 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       SUM(CASE WHEN transaction_type='SALE' THEN 1 ELSE 0 END) AS sales,
       SUM(CASE WHEN transaction_type='REFUND' THEN 1 ELSE 0 END) AS refunds,
       SUM(ABS(signed_amount)) AS absolute_amount_krw,
       COUNT(*)/SUM(COUNT(*)) OVER(PARTITION BY hotel_code,outlet_category,stay_link_type,amount_band) AS line_share
FROM tendered
GROUP BY hotel_code,outlet_category,stay_link_type,amount_band,tender_type
ORDER BY hotel_code,outlet_category,stay_link_type,amount_band,tender_type;

WITH item_totals AS (
  SELECT order_id,SUM(gross_amount) AS item_gross,SUM(discount_amount) AS item_discount,
         SUM(net_amount) AS item_net
  FROM walkerhill_v4_3.pos_order_items GROUP BY order_id
), payment_totals AS (
  SELECT order_id,SUM(signed_amount) AS signed_paid
  FROM walkerhill_v4_3.pos_payment_lines GROUP BY order_id
), checks AS (
  SELECT 'order_item_amount_mismatch' AS check_name,COUNT(*) AS violation_count
  FROM walkerhill_v4_3.pos_orders o JOIN item_totals i ON i.order_id=o.order_id
  WHERE o.item_gross_amount<>i.item_gross OR o.discount_amount<>i.item_discount
  UNION ALL
  SELECT 'item_equation_mismatch',COUNT(*)
  FROM walkerhill_v4_3.pos_order_items
  WHERE gross_amount<>quantity*unit_price OR net_amount<>gross_amount-discount_amount
  UNION ALL
  SELECT 'payment_sign_mismatch',COUNT(*)
  FROM walkerhill_v4_3.pos_payment_lines
  WHERE (transaction_type='SALE' AND signed_amount<=0)
     OR (transaction_type='REFUND' AND signed_amount>=0)
  UNION ALL
  SELECT 'settled_payment_total_mismatch',COUNT(*)
  FROM walkerhill_v4_3.pos_orders o JOIN payment_totals p ON p.order_id=o.order_id
  WHERE o.payment_status<>'VOIDED' AND p.signed_paid<>o.net_amount
  UNION ALL
  SELECT 'room_charge_without_linked_stay',COUNT(*)
  FROM walkerhill_v4_3.pos_payment_lines p JOIN walkerhill_v4_3.pos_orders o ON o.order_id=p.order_id
  WHERE p.tender_type='ROOM_CHARGE' AND o.linked_stay_id IS NULL
)
SELECT check_name,violation_count,
       CASE WHEN violation_count=0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM checks ORDER BY check_name;
