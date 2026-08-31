USE [crm_db];
GO
-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=SQL Server 2022; domain=CRM; script_type=CONSTRAINT_INDEX; execution_order=40
-- dependency=20..33 seed scripts; expected_rows=0; execution_default=NOT_RUN

SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;

ALTER TABLE [walkerhill_v4_3].[crm_membership_tiers] ADD CONSTRAINT PK_crm_membership_tiers PRIMARY KEY(tier_code);
ALTER TABLE [walkerhill_v4_3].[crm_members] ADD CONSTRAINT PK_crm_members PRIMARY KEY(member_no);
ALTER TABLE [walkerhill_v4_3].[crm_member_grade_history] ADD CONSTRAINT PK_crm_member_grade_history PRIMARY KEY(grade_history_id);
ALTER TABLE [walkerhill_v4_3].[crm_point_transactions] ADD CONSTRAINT PK_crm_point_transactions PRIMARY KEY(point_txn_id);
ALTER TABLE [walkerhill_v4_3].[crm_customer_map] ADD CONSTRAINT PK_crm_customer_map PRIMARY KEY(customer_map_id);
ALTER TABLE [walkerhill_v4_3].[crm_voc_reviews] ADD CONSTRAINT PK_crm_voc_reviews PRIMARY KEY(voc_review_id);
ALTER TABLE [walkerhill_v4_3].[crm_voc_analysis] ADD CONSTRAINT PK_crm_voc_analysis PRIMARY KEY(voc_analysis_id);

ALTER TABLE [walkerhill_v4_3].[crm_members] ADD
 CONSTRAINT FK_members_tier FOREIGN KEY(current_tier_code) REFERENCES [walkerhill_v4_3].[crm_membership_tiers](tier_code),
 CONSTRAINT CK_members_status CHECK(member_status IN('ACTIVE','DORMANT','WITHDRAWN')),
 CONSTRAINT CK_members_balance CHECK(points_balance>=0),
 CONSTRAINT CK_members_synthetic CHECK(is_synthetic=1);
ALTER TABLE [walkerhill_v4_3].[crm_member_grade_history] ADD
 CONSTRAINT FK_grade_member FOREIGN KEY(member_no) REFERENCES [walkerhill_v4_3].[crm_members](member_no),
 CONSTRAINT FK_grade_tier FOREIGN KEY(tier_code) REFERENCES [walkerhill_v4_3].[crm_membership_tiers](tier_code),
 CONSTRAINT CK_grade_period CHECK(valid_to IS NULL OR valid_to>valid_from);
ALTER TABLE [walkerhill_v4_3].[crm_point_transactions] ADD
 CONSTRAINT FK_point_member FOREIGN KEY(member_no) REFERENCES [walkerhill_v4_3].[crm_members](member_no),
 CONSTRAINT CK_point_type CHECK(txn_type IN('EARN','REDEEM','EXPIRE')),
 CONSTRAINT CK_point_source CHECK(related_source IN('PMS_GUEST','POS_ORDER','CRM_EXPIRY','CRM_CAMPAIGN')),
 CONSTRAINT CK_point_source_type CHECK((txn_type='EXPIRE' AND related_source='CRM_EXPIRY') OR (txn_type<>'EXPIRE' AND related_source<>'CRM_EXPIRY')),
 CONSTRAINT CK_point_sign CHECK((txn_type='EARN' AND points_delta>0) OR (txn_type IN('REDEEM','EXPIRE') AND points_delta<0));
ALTER TABLE [walkerhill_v4_3].[crm_customer_map] ADD
 CONSTRAINT FK_map_member FOREIGN KEY(member_no) REFERENCES [walkerhill_v4_3].[crm_members](member_no),
 CONSTRAINT CK_map_confidence CHECK(mapping_confidence>=0 AND mapping_confidence<=1),
 CONSTRAINT CK_map_source CHECK(pms_guest_id IS NOT NULL OR pos_customer_ref IS NOT NULL OR facility_user_ref IS NOT NULL OR banquet_customer_id IS NOT NULL);
ALTER TABLE [walkerhill_v4_3].[crm_voc_reviews] ADD
 CONSTRAINT FK_voc_member FOREIGN KEY(member_no) REFERENCES [walkerhill_v4_3].[crm_members](member_no),
 CONSTRAINT CK_voc_hotel CHECK(hotel_code IN('GRAND','VISTA','DOUGLAS')),
 CONSTRAINT CK_voc_channel CHECK(source_channel IN('POST_STAY_SURVEY','IN_STAY_QR','FNB_QR','FACILITY_QR','BANQUET_SURVEY','PUBLIC_REVIEW_SYNTHETIC')),
 CONSTRAINT CK_voc_touchpoint CHECK(touchpoint IN('CHECKOUT','ROOM','FNB','FACILITY','BANQUET','OVERALL')),
 CONSTRAINT CK_voc_category CHECK(selected_category IN('CHECKOUT_PROCESS','ROOM_CLEANLINESS','ROOM_MAINTENANCE','SLEEP_QUALITY','BREAKFAST_QUEUE','DINING_QUALITY','FACILITY_CROWDING','FACILITY_CONDITION','BANQUET_SERVICE','STAFF_SERVICE','LOCATION_ACCESS','VALUE','GENERAL_EXPERIENCE')),
 CONSTRAINT CK_voc_source CHECK(related_source IN('PMS_STAY','POS_ORDER','FACILITY_USAGE','BANQUET_BOOKING','NONE')),
 CONSTRAINT CK_voc_source_id CHECK((related_source='NONE' AND related_id IS NULL) OR (related_source<>'NONE' AND related_id IS NOT NULL)),
 CONSTRAINT CK_voc_related_touchpoint CHECK((touchpoint IN('CHECKOUT','ROOM') AND related_source='PMS_STAY') OR (touchpoint='FNB' AND related_source='POS_ORDER') OR (touchpoint='FACILITY' AND related_source='FACILITY_USAGE') OR (touchpoint='BANQUET' AND related_source='BANQUET_BOOKING') OR (touchpoint='OVERALL' AND related_source='NONE')),
 CONSTRAINT CK_voc_entity_scope CHECK((touchpoint='FNB' AND outlet_id IS NOT NULL AND facility_id IS NULL) OR (touchpoint='FACILITY' AND facility_id IS NOT NULL AND outlet_id IS NULL) OR (touchpoint NOT IN('FNB','FACILITY') AND outlet_id IS NULL AND facility_id IS NULL)),
 CONSTRAINT CK_voc_visit_cohort CHECK((visit_cohort='NEW' AND prior_visit_count=0) OR (visit_cohort='RETURNING' AND prior_visit_count>0)),
 CONSTRAINT CK_voc_source_date CHECK(source_business_date BETWEEN '2024-01-01' AND '2026-08-31'),
 CONSTRAINT CK_voc_text CHECK(LEN(review_title)>0 AND LEN(review_text_original)>=20 AND language_code='ko'),
 CONSTRAINT CK_voc_rating CHECK(rating_overall BETWEEN 1 AND 5 AND rating_service BETWEEN 1 AND 5 AND rating_value BETWEEN 1 AND 5
   AND (rating_cleanliness IS NULL OR rating_cleanliness BETWEEN 1 AND 5)
   AND (rating_food IS NULL OR rating_food BETWEEN 1 AND 5)
   AND (rating_facility IS NULL OR rating_facility BETWEEN 1 AND 5)),
 CONSTRAINT CK_voc_component_scope CHECK(((touchpoint IN('CHECKOUT','ROOM')) AND rating_cleanliness IS NOT NULL) OR ((touchpoint NOT IN('CHECKOUT','ROOM')) AND rating_cleanliness IS NULL)) ,
 CONSTRAINT CK_voc_food_scope CHECK(((touchpoint IN('FNB','BANQUET')) AND rating_food IS NOT NULL) OR ((touchpoint NOT IN('FNB','BANQUET')) AND rating_food IS NULL)),
 CONSTRAINT CK_voc_facility_scope CHECK((touchpoint='FACILITY' AND rating_facility IS NOT NULL) OR (touchpoint<>'FACILITY' AND rating_facility IS NULL)),
 CONSTRAINT CK_voc_external CHECK((source_channel='PUBLIC_REVIEW_SYNTHETIC' AND is_external=1 AND related_source='NONE') OR (source_channel<>'PUBLIC_REVIEW_SYNTHETIC' AND is_external=0)),
 CONSTRAINT CK_voc_privacy CHECK(consent_for_analysis=1 AND is_synthetic=1);
ALTER TABLE [walkerhill_v4_3].[crm_voc_analysis] ADD
 CONSTRAINT FK_voc_analysis_review FOREIGN KEY(voc_review_id) REFERENCES [walkerhill_v4_3].[crm_voc_reviews](voc_review_id),
 CONSTRAINT UQ_voc_analysis_review UNIQUE(voc_review_id),
 CONSTRAINT CK_voc_sentiment CHECK(sentiment_label IN('POSITIVE','NEUTRAL','NEGATIVE') AND sentiment_score BETWEEN -1 AND 1),
 CONSTRAINT CK_voc_urgency CHECK(urgency_level IN('LOW','MEDIUM','HIGH')),
 CONSTRAINT CK_voc_analysis_confidence CHECK(analysis_confidence BETWEEN 0 AND 1),
 CONSTRAINT CK_voc_analysis_synthetic CHECK(is_synthetic=1);

CREATE INDEX IX_members_tier_status ON [walkerhill_v4_3].[crm_members](current_tier_code,member_status);
CREATE INDEX IX_grade_member_period ON [walkerhill_v4_3].[crm_member_grade_history](member_no,valid_from,valid_to);
CREATE INDEX IX_point_member_time ON [walkerhill_v4_3].[crm_point_transactions](member_no,event_at) INCLUDE(points_delta,txn_type);
CREATE UNIQUE INDEX UX_map_member_active ON [walkerhill_v4_3].[crm_customer_map](member_no) WHERE valid_to IS NULL;
CREATE UNIQUE INDEX UX_map_pms_active ON [walkerhill_v4_3].[crm_customer_map](pms_guest_id) WHERE pms_guest_id IS NOT NULL AND valid_to IS NULL;
CREATE UNIQUE INDEX UX_map_pos_active ON [walkerhill_v4_3].[crm_customer_map](pos_customer_ref) WHERE pos_customer_ref IS NOT NULL AND valid_to IS NULL;
CREATE UNIQUE INDEX UX_map_facility_active ON [walkerhill_v4_3].[crm_customer_map](facility_user_ref) WHERE facility_user_ref IS NOT NULL AND valid_to IS NULL;
CREATE UNIQUE INDEX UX_map_banquet_active ON [walkerhill_v4_3].[crm_customer_map](banquet_customer_id) WHERE banquet_customer_id IS NOT NULL AND valid_to IS NULL;
CREATE INDEX IX_voc_hotel_time ON [walkerhill_v4_3].[crm_voc_reviews](hotel_code,source_business_date) INCLUDE(submitted_at,rating_overall,source_channel,touchpoint,selected_category);
CREATE INDEX IX_voc_low_rating ON [walkerhill_v4_3].[crm_voc_reviews](source_business_date,hotel_code) INCLUDE(submitted_at,selected_category,review_title) WHERE rating_overall<=2;
CREATE INDEX IX_voc_analysis_issue ON [walkerhill_v4_3].[crm_voc_analysis](urgency_level,primary_topic) INCLUDE(sentiment_label,requires_followup);
IF DATABASE_PRINCIPAL_ID(N'crm_query') IS NOT NULL
  GRANT SELECT ON SCHEMA::[walkerhill_v4_3] TO [crm_query];
GO
