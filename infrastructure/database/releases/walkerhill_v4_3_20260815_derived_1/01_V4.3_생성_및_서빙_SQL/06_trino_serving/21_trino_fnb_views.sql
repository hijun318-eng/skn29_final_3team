-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING_FNB; script_type=VIEW; execution_order=21
-- dependency=pos.walkerhill_v4_3; execution_default=NOT_RUN

CREATE OR REPLACE VIEW serving.analytics_v4_3.fnb_daily AS
SELECT o.business_date,m.hotel_code,
       COUNT(*) FILTER(WHERE o.order_status IN ('PAID','PARTIAL_REFUND')) completed_orders,
       COUNT(*) FILTER(WHERE o.order_status IN ('VOID','REFUNDED')) reversed_orders,
       SUM(CASE WHEN o.order_status<>'VOID' THEN o.guest_count ELSE 0 END) covers,
       SUM(o.item_gross_amount) item_gross_amount_krw,SUM(o.discount_amount) discount_amount_krw,
       SUM(o.service_charge_amount) service_charge_amount_krw,SUM(o.tax_amount) tax_amount_krw,
       SUM(o.refund_amount+o.void_amount) reversal_amount_krw,SUM(o.net_amount) net_revenue_krw,
       CAST(SUM(o.net_amount) AS double)/NULLIF(COUNT(*) FILTER(WHERE o.order_status IN ('PAID','PARTIAL_REFUND')),0) average_check_krw
FROM pos.walkerhill_v4_3.pos_orders o JOIN pos.walkerhill_v4_3.pos_outlets m ON m.outlet_id=o.outlet_id
GROUP BY 1,2;
COMMENT ON VIEW serving.analytics_v4_3.fnb_daily IS '호텔·영업일 단위 POS 주문, 커버, 세금·봉사료·환불을 분리한 합성 식음 KPI';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.business_date IS 'POS 주문이 귀속되는 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.hotel_code IS '업장 소속 GRAND·VISTA·DOUGLAS 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.completed_orders IS '완료 상태 합성 주문 수';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.reversed_orders IS '취소 또는 환불 상태 합성 주문 수';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.covers IS '완료 주문의 합성 고객 커버 수';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.item_gross_amount_krw IS '할인 전 메뉴 품목 총액';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.discount_amount_krw IS '주문 할인 합계';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.service_charge_amount_krw IS '주문 봉사료 합계';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.tax_amount_krw IS '주문 세액 합계';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.reversal_amount_krw IS '환불액과 취소액 합계';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.net_revenue_krw IS '할인·환불·취소를 반영한 합성 POS 순매출';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_daily.average_check_krw IS '합성 순매출/완료 주문 수';
