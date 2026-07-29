-- ============================================================================
-- Answervice 팀공유 SQL 산출물
-- ownership_contract=team-ownership-v2.1
-- schema_version=schema-v4.6-websql
-- snapshot_as_of_at=2026-07-28T05:00:00Z
-- generation_as_of_at=2026-07-28T05:00:00Z
-- evaluation_as_of=2026-07-28T14:00:00+09:00
-- GENERATE_FILES=true / RUN_STATIC_VALIDATION=true / EXECUTE_DB=false
-- 접속정보·healthy 컨테이너는 실행 승인으로 간주하지 않는다.
-- 실제 실행 전 해당 owner의 approval_id가 필요하다.
-- ============================================================================
-- owner=R4_김재홍
-- work_card=R4-APP-DB
-- output=260729_00_answervice_app_postgresql_p0_p1.sql

-- ============================================================================
-- 00_answervice_app_postgresql.sql
-- Answervice schema contract v4.6
-- PostgreSQL 15+ / psql
-- schema_version=schema-v4.6-websql
-- 생성 범위: DDL, 제약조건, 인덱스, 주석, 구조 검증
-- 대량 운영 데이터와 실제 연결 자격정보는 포함하지 않는다.
-- 동일 객체의 컬럼 계약이 다르면 SCHEMA_CONTRACT_MISMATCH로 중단한다.
-- 실제 DB 실행 상태: 이 파일 자체에는 실행 성공을 주장하지 않는다.
-- ============================================================================
\set ON_ERROR_STOP on


SELECT 'CREATE DATABASE answervice_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'answervice_app')\gexec
\connect answervice_app

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS "connection";
CREATE SCHEMA IF NOT EXISTS "context";
CREATE SCHEMA IF NOT EXISTS "chat";
CREATE SCHEMA IF NOT EXISTS "query";
CREATE SCHEMA IF NOT EXISTS "artifact";
CREATE SCHEMA IF NOT EXISTS "report";
CREATE SCHEMA IF NOT EXISTS "governance";
CREATE SCHEMA IF NOT EXISTS "model";
CREATE SCHEMA IF NOT EXISTS "reference";
CREATE SCHEMA IF NOT EXISTS "analytics";

CREATE OR REPLACE FUNCTION pg_temp.assert_table_contract(
    p_schema text,
    p_table text,
    p_expected text[]
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_actual text[];
    v_reg regclass;
BEGIN
    v_reg := to_regclass(format('%I.%I', p_schema, p_table));
    IF v_reg IS NULL THEN
        RETURN;
    END IF;

    SELECT array_agg(
               a.attname || ':' || format_type(a.atttypid, a.atttypmod) || ':' || a.attnotnull::text
               ORDER BY a.attnum
           )
      INTO v_actual
      FROM pg_attribute a
     WHERE a.attrelid = v_reg
       AND a.attnum > 0
       AND NOT a.attisdropped;

    IF v_actual IS DISTINCT FROM p_expected THEN
        RAISE EXCEPTION 'SCHEMA_CONTRACT_MISMATCH %.% expected %, actual %',
            p_schema, p_table, p_expected, v_actual;
    END IF;
END
$$;

-- 1. P0/P1 및 reference 물리 테이블 19개

-- C01 connection.data_sources: 논리 source·DataHub recipe·Trino catalog 연결 1건
SELECT pg_temp.assert_table_contract('connection', 'data_sources', ARRAY['data_source_id:uuid:true', 'source_code:character varying(32):true', 'source_name:character varying(120):true', 'engine_type:character varying(24):true', 'platform_instance:character varying(128):true', 'trino_catalog:character varying(128):true', 'datahub_recipe_ref:character varying(255):true', 'connection_ref:character varying(255):true', 'owner_team:character varying(100):true', 'status:character varying(16):true', 'last_health_status:character varying(16):false', 'last_health_at:timestamp with time zone:false', 'created_at:timestamp with time zone:true', 'updated_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS "connection"."data_sources" (
    "data_source_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "source_code" varchar(32) NOT NULL,
    "source_name" varchar(120) NOT NULL,
    "engine_type" varchar(24) NOT NULL,
    "platform_instance" varchar(128) NOT NULL,
    "trino_catalog" varchar(128) NOT NULL,
    "datahub_recipe_ref" varchar(255) NOT NULL,
    "connection_ref" varchar(255) NOT NULL,
    "owner_team" varchar(100) NOT NULL,
    "status" varchar(16) NOT NULL,
    "last_health_status" varchar(16),
    "last_health_at" timestamptz,
    "created_at" timestamptz NOT NULL,
    "updated_at" timestamptz NOT NULL,
    CONSTRAINT "uq_connection_data_sources_source_code" UNIQUE ("source_code"),
    CONSTRAINT "uq_connection_data_sources_platform_instance" UNIQUE ("platform_instance"),
    CONSTRAINT "uq_connection_data_sources_trino_catalog" UNIQUE ("trino_catalog"),
    CONSTRAINT "ck_connection_data_sources_source_code" CHECK (source_code IN ('PMS','POS','CRM','FACILITY','BANQUET')),
    CONSTRAINT "ck_connection_data_sources_engine_type" CHECK (engine_type IN ('POSTGRESQL','MYSQL','SQLSERVER','CLICKHOUSE')),
    CONSTRAINT "ck_connection_data_sources_status" CHECK (status IN ('DRAFT','ACTIVE','ERROR','DISABLED')),
    CONSTRAINT "ck_connection_data_sources_last_health_status" CHECK (last_health_status IS NULL OR last_health_status IN ('HEALTHY','DEGRADED','DOWN','UNKNOWN')),
    CONSTRAINT "ck_connection_data_sources_rule_1" CHECK (btrim(source_code) <> ''),
    CONSTRAINT "ck_connection_data_sources_rule_2" CHECK (btrim(platform_instance) <> ''),
    CONSTRAINT "ck_connection_data_sources_rule_3" CHECK (btrim(trino_catalog) <> ''),
    CONSTRAINT "ck_connection_data_sources_rule_4" CHECK (last_health_at IS NULL OR last_health_status IS NOT NULL)
);
COMMENT ON TABLE "connection"."data_sources" IS '논리 source·DataHub recipe·Trino catalog 연결 1건';
COMMENT ON COLUMN "connection"."data_sources"."data_source_id" IS '데이터 소스 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."source_code" IS '소스 코드. PMS/POS/CRM/FACILITY/BANQUET [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."source_name" IS '소스명. 관리자 표시명 [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."engine_type" IS '엔진. POSTGRESQL/MYSQL/SQLSERVER/CLICKHOUSE [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."platform_instance" IS 'DataHub platform instance. 5개 소스 구분자 [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."trino_catalog" IS 'Trino catalog. 5개 catalog 구분자 [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."datahub_recipe_ref" IS 'recipe 참조. 버전 고정 recipe 경로 [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."connection_ref" IS 'credential 참조. env 또는 Secret Manager 참조만 [classification=SECRET_REF]';
COMMENT ON COLUMN "connection"."data_sources"."owner_team" IS '담당 조직. source owner [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."status" IS '상태. DRAFT/ACTIVE/ERROR/DISABLED [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."last_health_status" IS '최근 health. HEALTHY/DEGRADED/DOWN/UNKNOWN [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."last_health_at" IS '최근 점검 시각. UTC [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."created_at" IS '생성 시각. UTC [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."data_sources"."updated_at" IS '수정 시각. UTC [classification=INTERNAL]';

-- C02 connection.ingestion_runs: DataHub ingestion 실행 1건
SELECT pg_temp.assert_table_contract('connection', 'ingestion_runs', ARRAY['ingestion_run_id:uuid:true', 'data_source_id:uuid:true', 'datahub_run_id:character varying(160):false', 'recipe_version:character varying(64):true', 'status:character varying(16):true', 'asset_count:integer:true', 'column_count:integer:true', 'started_at:timestamp with time zone:false', 'completed_at:timestamp with time zone:false', 'error_code:character varying(64):false', 'error_message_redacted:text:false']::text[]);
CREATE TABLE IF NOT EXISTS "connection"."ingestion_runs" (
    "ingestion_run_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "data_source_id" uuid NOT NULL,
    "datahub_run_id" varchar(160),
    "recipe_version" varchar(64) NOT NULL,
    "status" varchar(16) NOT NULL,
    "asset_count" integer NOT NULL,
    "column_count" integer NOT NULL,
    "started_at" timestamptz,
    "completed_at" timestamptz,
    "error_code" varchar(64),
    "error_message_redacted" text,
    CONSTRAINT "uq_connection_ingestion_runs_data_source_id_da_15a2e746" UNIQUE ("data_source_id", "datahub_run_id"),
    CONSTRAINT "ck_connection_ingestion_runs_status" CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','PARTIAL','FAILED')),
    CONSTRAINT "ck_connection_ingestion_runs_rule_1" CHECK (asset_count >= 0),
    CONSTRAINT "ck_connection_ingestion_runs_rule_2" CHECK (column_count >= 0),
    CONSTRAINT "ck_connection_ingestion_runs_rule_3" CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);
COMMENT ON TABLE "connection"."ingestion_runs" IS 'DataHub ingestion 실행 1건';
COMMENT ON COLUMN "connection"."ingestion_runs"."ingestion_run_id" IS 'ingestion 실행 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."data_source_id" IS '데이터 소스 ID. 대상 source [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."datahub_run_id" IS 'DataHub 실행 ID. GMS/CLI 실행 추적 [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."recipe_version" IS 'recipe 버전. image·recipe 고정 [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."status" IS '상태. PENDING/RUNNING/SUCCEEDED/PARTIAL/FAILED [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."asset_count" IS '자산 수. fixture 대조 [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."column_count" IS '컬럼 수. fixture 대조 [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."started_at" IS '시작 시각. [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."completed_at" IS '완료 시각. [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."error_code" IS '오류 코드. [classification=INTERNAL]';
COMMENT ON COLUMN "connection"."ingestion_runs"."error_message_redacted" IS '비식별 오류. credential 제거 [classification=CONFIDENTIAL]';

-- CTX01 context.context_records: 승인 Context record 버전 1건
SELECT pg_temp.assert_table_contract('context', 'context_records', ARRAY['context_record_id:uuid:true', 'record_type:character varying(32):true', 'record_key:character varying(160):true', 'version_no:integer:true', 'payload_json:jsonb:true', 'status:character varying(16):true', 'owner_role:character varying(64):true', 'approved_by:uuid:false', 'approved_at:timestamp with time zone:false', 'valid_from:timestamp with time zone:true', 'valid_to:timestamp with time zone:false', 'checksum:character varying(64):true']::text[]);
CREATE TABLE IF NOT EXISTS "context"."context_records" (
    "context_record_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "record_type" varchar(32) NOT NULL,
    "record_key" varchar(160) NOT NULL,
    "version_no" integer NOT NULL,
    "payload_json" jsonb NOT NULL,
    "status" varchar(16) NOT NULL,
    "owner_role" varchar(64) NOT NULL,
    "approved_by" uuid,
    "approved_at" timestamptz,
    "valid_from" timestamptz NOT NULL,
    "valid_to" timestamptz,
    "checksum" varchar(64) NOT NULL,
    CONSTRAINT "uq_context_context_records_record_type_record__e4e20849" UNIQUE ("record_type", "record_key", "version_no"),
    CONSTRAINT "ck_context_context_records_record_type" CHECK (record_type IN ('ASSET_BINDING','METRIC_DEFINITION','TIME_POLICY','DIMENSION_HISTORY_POLICY','JOIN_POLICY','TERM_ALIAS','COLUMN_POLICY_REF')),
    CONSTRAINT "ck_context_context_records_status" CHECK (status IN ('DRAFT','APPROVED','DEPRECATED')),
    CONSTRAINT "ck_context_context_records_rule_1" CHECK (version_no > 0),
    CONSTRAINT "ck_context_context_records_rule_2" CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT "ck_context_context_records_rule_3" CHECK ((status <> 'APPROVED') OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
COMMENT ON TABLE "context"."context_records" IS '승인 Context record 버전 1건';
COMMENT ON COLUMN "context"."context_records"."context_record_id" IS 'Context record ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."record_type" IS 'record 유형. ASSET_BINDING/METRIC_DEFINITION/TIME_POLICY/DIMENSION_HISTORY_POLICY/JOIN_POLICY/TERM_ALIAS/COLUMN_POLICY_REF [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."record_key" IS '안정 업무 키. 유형 내 고유 키 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."version_no" IS '버전. record_key별 증가 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."payload_json" IS 'record 본문. record_type별 JSON Schema 검증 [classification=POLICY]';
COMMENT ON COLUMN "context"."context_records"."status" IS '상태. DRAFT/APPROVED/DEPRECATED [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."owner_role" IS '승인 책임 역할. data engineer/steward/source owner [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."approved_by" IS '승인자 ID. Django/SSO 논리 참조 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."approved_at" IS '승인 시각. [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."valid_from" IS '유효 시작. [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."valid_to" IS '유효 종료. [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_records"."checksum" IS 'record checksum. SHA-256 [classification=INTERNAL]';

-- CTX02 context.context_releases: 승인 record 집합의 불변 release 1건
SELECT pg_temp.assert_table_contract('context', 'context_releases', ARRAY['context_release_id:uuid:true', 'release_key:character varying(128):true', 'version_no:integer:true', 'included_record_refs_json:jsonb:true', 'status:character varying(16):true', 'release_hash:character varying(64):true', 'published_by:uuid:false', 'published_at:timestamp with time zone:false', 'rollback_release_id:uuid:false']::text[]);
CREATE TABLE IF NOT EXISTS "context"."context_releases" (
    "context_release_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "release_key" varchar(128) NOT NULL,
    "version_no" integer NOT NULL,
    "included_record_refs_json" jsonb NOT NULL,
    "status" varchar(16) NOT NULL,
    "release_hash" varchar(64) NOT NULL,
    "published_by" uuid,
    "published_at" timestamptz,
    "rollback_release_id" uuid,
    CONSTRAINT "uq_context_context_releases_release_key_version_no" UNIQUE ("release_key", "version_no"),
    CONSTRAINT "ck_context_context_releases_status" CHECK (status IN ('DRAFT','PUBLISHED','RETIRED')),
    CONSTRAINT "ck_context_context_releases_rule_1" CHECK (version_no > 0),
    CONSTRAINT "ck_context_context_releases_rule_2" CHECK ((status <> 'PUBLISHED') OR (published_at IS NOT NULL))
);
COMMENT ON TABLE "context"."context_releases" IS '승인 record 집합의 불변 release 1건';
COMMENT ON COLUMN "context"."context_releases"."context_release_id" IS 'Context release ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_releases"."release_key" IS 'release 키. 환경·용도 안정 키 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_releases"."version_no" IS 'release 버전. [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_releases"."included_record_refs_json" IS '포함 record 참조. record key·version 목록 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_releases"."status" IS '상태. DRAFT/PUBLISHED/RETIRED [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_releases"."release_hash" IS 'release hash. 불변 package 기준 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_releases"."published_by" IS 'publish 승인자. Django/SSO 논리 참조 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_releases"."published_at" IS 'publish 시각. PUBLISHED 이후 수정 금지 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_releases"."rollback_release_id" IS 'rollback 대상. 이전 안정 버전 [classification=INTERNAL]';

-- CTX03 context.context_packages: 질문별 LLM 입력 package 1건
SELECT pg_temp.assert_table_contract('context', 'context_packages', ARRAY['context_package_id:uuid:true', 'request_id:uuid:true', 'context_release_id:uuid:true', 'user_scope_json:jsonb:true', 'assets_json:jsonb:true', 'metrics_json:jsonb:true', 'joins_json:jsonb:true', 'policies_json:jsonb:true', 'dataset_count:smallint:true', 'column_count:smallint:true', 'token_count:integer:true', 'package_hash:character varying(64):true', 'created_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS "context"."context_packages" (
    "context_package_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "request_id" uuid NOT NULL,
    "context_release_id" uuid NOT NULL,
    "user_scope_json" jsonb NOT NULL,
    "assets_json" jsonb NOT NULL,
    "metrics_json" jsonb NOT NULL,
    "joins_json" jsonb NOT NULL,
    "policies_json" jsonb NOT NULL,
    "dataset_count" smallint NOT NULL,
    "column_count" smallint NOT NULL,
    "token_count" integer NOT NULL,
    "package_hash" varchar(64) NOT NULL,
    "created_at" timestamptz NOT NULL,
    CONSTRAINT "uq_context_context_packages_request_id" UNIQUE ("request_id"),
    CONSTRAINT "ck_context_context_packages_rule_1" CHECK (dataset_count BETWEEN 0 AND 8),
    CONSTRAINT "ck_context_context_packages_rule_2" CHECK (column_count BETWEEN 0 AND 60),
    CONSTRAINT "ck_context_context_packages_rule_3" CHECK (token_count BETWEEN 0 AND 6000)
);
COMMENT ON TABLE "context"."context_packages" IS '질문별 LLM 입력 package 1건';
COMMENT ON COLUMN "context"."context_packages"."context_package_id" IS 'Context Package ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_packages"."request_id" IS '요청 ID. 요청당 1개 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_packages"."context_release_id" IS 'Context release ID. 승인 release [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_packages"."user_scope_json" IS '사용자 scope. role·allowed domains [classification=POLICY]';
COMMENT ON COLUMN "context"."context_packages"."assets_json" IS '선택 자산. URN·Trino FQN·컬럼 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_packages"."metrics_json" IS '승인 지표. metric ID·field·aggregation [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_packages"."joins_json" IS '승인 JOIN. key·cardinality·status [classification=POLICY]';
COMMENT ON COLUMN "context"."context_packages"."policies_json" IS '실행 정책. read-only·limit·timeout·column policy [classification=POLICY]';
COMMENT ON COLUMN "context"."context_packages"."dataset_count" IS 'dataset 수. 최대 8 [classification=POLICY]';
COMMENT ON COLUMN "context"."context_packages"."column_count" IS 'column 수. 최대 60 [classification=POLICY]';
COMMENT ON COLUMN "context"."context_packages"."token_count" IS 'token 수. 최대 min(6000, context 25%) [classification=POLICY]';
COMMENT ON COLUMN "context"."context_packages"."package_hash" IS 'package hash. LLM 입력 감사 [classification=INTERNAL]';
COMMENT ON COLUMN "context"."context_packages"."created_at" IS '생성 시각. 불변 [classification=INTERNAL]';

-- CH01 chat.conversations: 사용자 분석 대화 1건
SELECT pg_temp.assert_table_contract('chat', 'conversations', ARRAY['conversation_id:uuid:true', 'owner_user_id:uuid:true', 'title:character varying(255):true', 'status:character varying(16):true', 'created_at:timestamp with time zone:true', 'updated_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS "chat"."conversations" (
    "conversation_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "owner_user_id" uuid NOT NULL,
    "title" varchar(255) NOT NULL,
    "status" varchar(16) NOT NULL,
    "created_at" timestamptz NOT NULL,
    "updated_at" timestamptz NOT NULL,
    CONSTRAINT "ck_chat_conversations_status" CHECK (status IN ('ACTIVE','ARCHIVED'))
);
COMMENT ON TABLE "chat"."conversations" IS '사용자 분석 대화 1건';
COMMENT ON COLUMN "chat"."conversations"."conversation_id" IS '대화 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."conversations"."owner_user_id" IS '소유 사용자 ID. Django/SSO 논리 참조 [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."conversations"."title" IS '대화 제목. [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."conversations"."status" IS '상태. ACTIVE/ARCHIVED [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."conversations"."created_at" IS '생성 시각. [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."conversations"."updated_at" IS '수정 시각. [classification=INTERNAL]';

-- CH02 chat.analysis_requests: 질문·보고서 블록 분석 요청 1건
SELECT pg_temp.assert_table_contract('chat', 'analysis_requests', ARRAY['request_id:uuid:true', 'conversation_id:uuid:false', 'request_type:character varying(24):true', 'user_id:uuid:true', 'user_role:character varying(64):true', 'question_text_redacted:text:true', 'question_hash:character varying(64):true', 'ambiguity_status:character varying(16):true', 'context_release_id:uuid:false', 'context_package_id:uuid:false', 'sql_generation_model_id:uuid:false', 'sql_policy_version:character varying(64):true', 'status:character varying(20):true', 'error_type:character varying(24):false', 'trace_id:character varying(128):true', 'started_at:timestamp with time zone:true', 'completed_at:timestamp with time zone:false']::text[]);
CREATE TABLE IF NOT EXISTS "chat"."analysis_requests" (
    "request_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "conversation_id" uuid,
    "request_type" varchar(24) NOT NULL,
    "user_id" uuid NOT NULL,
    "user_role" varchar(64) NOT NULL,
    "question_text_redacted" text NOT NULL,
    "question_hash" varchar(64) NOT NULL,
    "ambiguity_status" varchar(16) NOT NULL,
    "context_release_id" uuid,
    "context_package_id" uuid,
    "sql_generation_model_id" uuid,
    "sql_policy_version" varchar(64) NOT NULL,
    "status" varchar(20) NOT NULL,
    "error_type" varchar(24),
    "trace_id" varchar(128) NOT NULL,
    "started_at" timestamptz NOT NULL,
    "completed_at" timestamptz,
    CONSTRAINT "ck_chat_analysis_requests_request_type" CHECK (request_type IN ('CHAT','BLOCK_PREVIEW','REPORT_BLOCK','MODEL_EVAL')),
    CONSTRAINT "ck_chat_analysis_requests_ambiguity_status" CHECK (ambiguity_status IN ('CLEAR','NEEDS_CLARIFICATION','RESOLVED')),
    CONSTRAINT "ck_chat_analysis_requests_status" CHECK (status IN ('RECEIVED','CLARIFYING','CONTEXT_BUILDING','GENERATING','VALIDATING','RUNNING','SUCCEEDED','PARTIAL','FAILED','DENIED')),
    CONSTRAINT "ck_chat_analysis_requests_error_type" CHECK (error_type IS NULL OR error_type IN ('AMBIGUOUS','UNSUPPORTED','PERMISSION','QUERY','PARTIAL','INSUFFICIENT_EVIDENCE')),
    CONSTRAINT "ck_chat_analysis_requests_rule_1" CHECK (completed_at IS NULL OR completed_at >= started_at)
);
COMMENT ON TABLE "chat"."analysis_requests" IS '질문·보고서 블록 분석 요청 1건';
COMMENT ON COLUMN "chat"."analysis_requests"."request_id" IS '요청 ID. 전체 trace 루트 [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."conversation_id" IS '대화 ID. 보고서 실행은 NULL 가능 [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."request_type" IS '요청 유형. CHAT/BLOCK_PREVIEW/REPORT_BLOCK/MODEL_EVAL [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."user_id" IS '사용자 ID. Django/SSO 논리 참조 [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."user_role" IS '요청 역할. 시점 역할 snapshot [classification=POLICY]';
COMMENT ON COLUMN "chat"."analysis_requests"."question_text_redacted" IS '비식별 질문. 외부 모델 전송 정책 적용 [classification=CONFIDENTIAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."question_hash" IS '질문 hash. [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."ambiguity_status" IS '모호성 상태. CLEAR/NEEDS_CLARIFICATION/RESOLVED [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."context_release_id" IS 'Context release. 실행 기준 [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."context_package_id" IS 'Context package. 완성 후 연결 [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."sql_generation_model_id" IS 'SQL 생성 모델. sLLM version [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."sql_policy_version" IS 'SQL 정책 버전. [classification=POLICY]';
COMMENT ON COLUMN "chat"."analysis_requests"."status" IS '상태. RECEIVED/CLARIFYING/CONTEXT_BUILDING/GENERATING/VALIDATING/RUNNING/SUCCEEDED/PARTIAL/FAILED/DENIED [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."error_type" IS '오류 유형. AMBIGUOUS/UNSUPPORTED/PERMISSION/QUERY/PARTIAL/INSUFFICIENT_EVIDENCE [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."trace_id" IS 'OTel trace ID. [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."started_at" IS '시작 시각. [classification=INTERNAL]';
COMMENT ON COLUMN "chat"."analysis_requests"."completed_at" IS '완료 시각. [classification=INTERNAL]';

-- Q01 query.query_executions: SQL 생성·검증·Trino 실행 시도 1건
SELECT pg_temp.assert_table_contract('query', 'query_executions', ARRAY['query_execution_id:uuid:true', 'request_id:uuid:true', 'attempt_no:smallint:true', 'generation_mode:character varying(20):true', 'generated_sql_redacted:text:true', 'sql_hash:character varying(64):true', 'ast_validation_json:jsonb:true', 'join_validation_json:jsonb:true', 'permission_validation_json:jsonb:true', 'explain_json:jsonb:true', 'validation_status:character varying(16):true', 'trino_query_id:character varying(128):false', 'execution_status:character varying(16):true', 'row_count:integer:true', 'scan_bytes:bigint:true', 'duration_ms:integer:false', 'result_checksum:character varying(64):false', 'source_urns_json:jsonb:true', 'source_cutoff_json:jsonb:true', 'error_code:character varying(64):false', 'error_message_redacted:text:false']::text[]);
CREATE TABLE IF NOT EXISTS "query"."query_executions" (
    "query_execution_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "request_id" uuid NOT NULL,
    "attempt_no" smallint NOT NULL,
    "generation_mode" varchar(20) NOT NULL,
    "generated_sql_redacted" text NOT NULL,
    "sql_hash" varchar(64) NOT NULL,
    "ast_validation_json" jsonb NOT NULL,
    "join_validation_json" jsonb NOT NULL,
    "permission_validation_json" jsonb NOT NULL,
    "explain_json" jsonb NOT NULL,
    "validation_status" varchar(16) NOT NULL,
    "trino_query_id" varchar(128),
    "execution_status" varchar(16) NOT NULL,
    "row_count" integer NOT NULL,
    "scan_bytes" bigint NOT NULL,
    "duration_ms" integer,
    "result_checksum" varchar(64),
    "source_urns_json" jsonb NOT NULL,
    "source_cutoff_json" jsonb NOT NULL,
    "error_code" varchar(64),
    "error_message_redacted" text,
    CONSTRAINT "uq_query_query_executions_request_id_attempt_no" UNIQUE ("request_id", "attempt_no"),
    CONSTRAINT "ck_query_query_executions_generation_mode" CHECK (generation_mode IN ('SLLM','TEMPLATE','FALLBACK')),
    CONSTRAINT "ck_query_query_executions_validation_status" CHECK (validation_status IN ('PENDING','ALLOWED','BLOCKED','FAILED')),
    CONSTRAINT "ck_query_query_executions_execution_status" CHECK (execution_status IN ('NOT_STARTED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    CONSTRAINT "ck_query_query_executions_rule_1" CHECK (attempt_no > 0),
    CONSTRAINT "ck_query_query_executions_rule_2" CHECK (row_count >= 0),
    CONSTRAINT "ck_query_query_executions_rule_3" CHECK (scan_bytes >= 0),
    CONSTRAINT "ck_query_query_executions_rule_4" CHECK (duration_ms IS NULL OR duration_ms >= 0)
);
COMMENT ON TABLE "query"."query_executions" IS 'SQL 생성·검증·Trino 실행 시도 1건';
COMMENT ON COLUMN "query"."query_executions"."query_execution_id" IS 'query 실행 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."request_id" IS '요청 ID. 상위 요청 [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."attempt_no" IS '시도 번호. 재생성·fallback 구분 [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."generation_mode" IS '생성 방식. SLLM/TEMPLATE/FALLBACK [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."generated_sql_redacted" IS '생성 SQL. parameter·민감 literal 분리 [classification=CONFIDENTIAL]';
COMMENT ON COLUMN "query"."query_executions"."sql_hash" IS 'SQL hash. [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."ast_validation_json" IS 'AST 검증. statement·자산·컬럼·함수 [classification=POLICY]';
COMMENT ON COLUMN "query"."query_executions"."join_validation_json" IS 'JOIN 검증. 승인 key·방향·cardinality [classification=POLICY]';
COMMENT ON COLUMN "query"."query_executions"."permission_validation_json" IS '권한 검증. role·dataset·column [classification=POLICY]';
COMMENT ON COLUMN "query"."query_executions"."explain_json" IS 'Trino EXPLAIN. TYPE VALIDATE/IO·scan [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."validation_status" IS '검증 상태. PENDING/ALLOWED/BLOCKED/FAILED [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."trino_query_id" IS 'Trino query ID. 실행 전 NULL [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."execution_status" IS '실행 상태. NOT_STARTED/RUNNING/SUCCEEDED/FAILED/CANCELLED [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."row_count" IS '행수. [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."scan_bytes" IS 'scan bytes. [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."duration_ms" IS '실행시간. [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."result_checksum" IS '결과 checksum. gold·report 재현 [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."source_urns_json" IS '사용 source URN. Context와 일치 검증 [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."source_cutoff_json" IS 'source 기준 시각. source별 cutoff/freshness [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."error_code" IS '오류 코드. [classification=INTERNAL]';
COMMENT ON COLUMN "query"."query_executions"."error_message_redacted" IS '비식별 오류. [classification=CONFIDENTIAL]';

-- A01 artifact.analysis_artifacts: 표·차트·KPI·설명·출처 artifact 1건
SELECT pg_temp.assert_table_contract('artifact', 'analysis_artifacts', ARRAY['artifact_id:uuid:true', 'request_id:uuid:true', 'query_execution_id:uuid:false', 'artifact_type:character varying(20):true', 'title:character varying(255):true', 'data_snapshot_json:jsonb:true', 'chart_spec_json:jsonb:true', 'narrative_markdown:text:false', 'evidence_json:jsonb:true', 'freshness_status:character varying(16):true', 'status:character varying(16):true', 'artifact_checksum:character varying(64):true']::text[]);
CREATE TABLE IF NOT EXISTS "artifact"."analysis_artifacts" (
    "artifact_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "request_id" uuid NOT NULL,
    "query_execution_id" uuid,
    "artifact_type" varchar(20) NOT NULL,
    "title" varchar(255) NOT NULL,
    "data_snapshot_json" jsonb NOT NULL,
    "chart_spec_json" jsonb NOT NULL,
    "narrative_markdown" text,
    "evidence_json" jsonb NOT NULL,
    "freshness_status" varchar(16) NOT NULL,
    "status" varchar(16) NOT NULL,
    "artifact_checksum" varchar(64) NOT NULL,
    CONSTRAINT "ck_artifact_analysis_artifacts_artifact_type" CHECK (artifact_type IN ('TABLE','CHART','KPI','TEXT','COMPOSITE')),
    CONSTRAINT "ck_artifact_analysis_artifacts_freshness_status" CHECK (freshness_status IN ('FRESH','STALE','PARTIAL')),
    CONSTRAINT "ck_artifact_analysis_artifacts_status" CHECK (status IN ('DRAFT','APPROVED','INVALIDATED'))
);
COMMENT ON TABLE "artifact"."analysis_artifacts" IS '표·차트·KPI·설명·출처 artifact 1건';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."artifact_id" IS 'artifact ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."request_id" IS '요청 ID. 원 질문 [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."query_execution_id" IS 'query 실행 ID. SQL 근거 [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."artifact_type" IS '산출물 유형. TABLE/CHART/KPI/TEXT/COMPOSITE [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."title" IS '제목. [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."data_snapshot_json" IS '결과 snapshot. 제한 결과 또는 ref [classification=CONFIDENTIAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."chart_spec_json" IS '차트 사양. 검증된 ECharts subset [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."narrative_markdown" IS '결과 설명. 수치를 변경하지 않음 [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."evidence_json" IS '근거. URN·지표·필터·기간·JOIN·query ID [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."freshness_status" IS 'freshness. FRESH/STALE/PARTIAL [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."status" IS '상태. DRAFT/APPROVED/INVALIDATED [classification=INTERNAL]';
COMMENT ON COLUMN "artifact"."analysis_artifacts"."artifact_checksum" IS 'artifact checksum. 왕복·재현 [classification=INTERNAL]';

-- R01 report.report_definitions: 보고서 정의 버전 1건
SELECT pg_temp.assert_table_contract('report', 'report_definitions', ARRAY['report_definition_id:uuid:true', 'report_key:character varying(128):true', 'version_no:integer:true', 'title:character varying(255):true', 'period_type:character varying(16):true', 'owner_user_id:uuid:true', 'timezone_name:character varying(64):true', 'layout_columns:smallint:true', 'schedule_cron:character varying(64):false', 'schedule_enabled:boolean:true', 'status:character varying(16):true', 'approved_by:uuid:false', 'approved_at:timestamp with time zone:false']::text[]);
CREATE TABLE IF NOT EXISTS "report"."report_definitions" (
    "report_definition_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "report_key" varchar(128) NOT NULL,
    "version_no" integer NOT NULL,
    "title" varchar(255) NOT NULL,
    "period_type" varchar(16) NOT NULL,
    "owner_user_id" uuid NOT NULL,
    "timezone_name" varchar(64) NOT NULL,
    "layout_columns" smallint NOT NULL,
    "schedule_cron" varchar(64),
    "schedule_enabled" boolean NOT NULL,
    "status" varchar(16) NOT NULL,
    "approved_by" uuid,
    "approved_at" timestamptz,
    CONSTRAINT "uq_report_report_definitions_report_key_version_no" UNIQUE ("report_key", "version_no"),
    CONSTRAINT "ck_report_report_definitions_period_type" CHECK (period_type IN ('DAILY','WEEKLY','MONTHLY')),
    CONSTRAINT "ck_report_report_definitions_status" CHECK (status IN ('DRAFT','APPROVED','RETIRED')),
    CONSTRAINT "ck_report_report_definitions_rule_1" CHECK (layout_columns = 12)
);
COMMENT ON TABLE "report"."report_definitions" IS '보고서 정의 버전 1건';
COMMENT ON COLUMN "report"."report_definitions"."report_definition_id" IS '보고서 정의 ID. 버전 row PK [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_definitions"."report_key" IS '보고서 안정 키. 버전 간 동일 보고서 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_definitions"."version_no" IS '정의 버전. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_definitions"."title" IS '제목. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_definitions"."period_type" IS '주기. DAILY/WEEKLY/MONTHLY [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_definitions"."owner_user_id" IS '소유자. 관리자 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_definitions"."timezone_name" IS 'timezone. MVP 하나의 timezone [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_definitions"."layout_columns" IS 'grid column 수. 12 고정 [classification=POLICY]';
COMMENT ON COLUMN "report"."report_definitions"."schedule_cron" IS 'schedule cron. gate 통과 후 [classification=POLICY]';
COMMENT ON COLUMN "report"."report_definitions"."schedule_enabled" IS '스케줄 활성. 수동 반복 성공 후 true [classification=POLICY]';
COMMENT ON COLUMN "report"."report_definitions"."status" IS '정의 상태. DRAFT/APPROVED/RETIRED [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_definitions"."approved_by" IS '승인자. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_definitions"."approved_at" IS '승인 시각. [classification=INTERNAL]';

-- R02 report.report_blocks: 보고서 블록 정의 1건
SELECT pg_temp.assert_table_contract('report', 'report_blocks', ARRAY['report_block_id:uuid:true', 'report_definition_id:uuid:true', 'block_key:character varying(128):true', 'block_type:character varying(16):true', 'source_mode:character varying(16):true', 'source_artifact_id:uuid:false', 'question_text_redacted:text:false', 'filter_json:jsonb:true', 'grid_x:smallint:true', 'grid_y:smallint:true', 'grid_w:smallint:true', 'grid_h:smallint:true', 'display_config_json:jsonb:true', 'approval_status:character varying(16):true']::text[]);
CREATE TABLE IF NOT EXISTS "report"."report_blocks" (
    "report_block_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "report_definition_id" uuid NOT NULL,
    "block_key" varchar(128) NOT NULL,
    "block_type" varchar(16) NOT NULL,
    "source_mode" varchar(16) NOT NULL,
    "source_artifact_id" uuid,
    "question_text_redacted" text,
    "filter_json" jsonb NOT NULL,
    "grid_x" smallint NOT NULL,
    "grid_y" smallint NOT NULL,
    "grid_w" smallint NOT NULL,
    "grid_h" smallint NOT NULL,
    "display_config_json" jsonb NOT NULL,
    "approval_status" varchar(16) NOT NULL,
    CONSTRAINT "uq_report_report_blocks_report_definition_id_block_key" UNIQUE ("report_definition_id", "block_key"),
    CONSTRAINT "ck_report_report_blocks_block_type" CHECK (block_type IN ('TEXT','KPI','TABLE','CHART')),
    CONSTRAINT "ck_report_report_blocks_source_mode" CHECK (source_mode IN ('ARTIFACT','QUESTION')),
    CONSTRAINT "ck_report_report_blocks_approval_status" CHECK (approval_status IN ('DRAFT','APPROVED','REJECTED')),
    CONSTRAINT "ck_report_report_blocks_rule_1" CHECK (grid_x BETWEEN 0 AND 11),
    CONSTRAINT "ck_report_report_blocks_rule_2" CHECK (grid_y >= 0),
    CONSTRAINT "ck_report_report_blocks_rule_3" CHECK (grid_w BETWEEN 1 AND 12),
    CONSTRAINT "ck_report_report_blocks_rule_4" CHECK (grid_h >= 1),
    CONSTRAINT "ck_report_report_blocks_rule_5" CHECK (grid_x + grid_w <= 12)
);
COMMENT ON TABLE "report"."report_blocks" IS '보고서 블록 정의 1건';
COMMENT ON COLUMN "report"."report_blocks"."report_block_id" IS '블록 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."report_definition_id" IS '보고서 정의 ID. 정의 버전 귀속 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."block_key" IS '블록 안정 키. 교체·버전 추적 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."block_type" IS '블록 유형. TEXT/KPI/TABLE/CHART [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."source_mode" IS '원천 모드. ARTIFACT/QUESTION [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."source_artifact_id" IS '원본 artifact. 챗→보고서 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."question_text_redacted" IS '실행 질문. 재실행형 블록 [classification=CONFIDENTIAL]';
COMMENT ON COLUMN "report"."report_blocks"."filter_json" IS '필터. 기간·사업부·등급 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."grid_x" IS 'grid x. 0~11 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."grid_y" IS 'grid y. 0 이상 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."grid_w" IS 'grid width. 1~12 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."grid_h" IS 'grid height. 1 이상 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."display_config_json" IS '표시 설정. 단위·축·범례 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_blocks"."approval_status" IS '승인 상태. DRAFT/APPROVED/REJECTED [classification=INTERNAL]';

-- R03 report.report_runs: 수동·스케줄 보고서 실행 1건
SELECT pg_temp.assert_table_contract('report', 'report_runs', ARRAY['report_run_id:uuid:true', 'report_definition_id:uuid:true', 'trigger_type:character varying(16):true', 'triggered_by:uuid:false', 'status:character varying(16):true', 'context_release_id:uuid:true', 'sql_policy_version:character varying(64):true', 'period_start:timestamp with time zone:true', 'period_end:timestamp with time zone:true', 'source_cutoff_json:jsonb:true', 'snapshot_checksum:character varying(64):false']::text[]);
CREATE TABLE IF NOT EXISTS "report"."report_runs" (
    "report_run_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "report_definition_id" uuid NOT NULL,
    "trigger_type" varchar(16) NOT NULL,
    "triggered_by" uuid,
    "status" varchar(16) NOT NULL,
    "context_release_id" uuid NOT NULL,
    "sql_policy_version" varchar(64) NOT NULL,
    "period_start" timestamptz NOT NULL,
    "period_end" timestamptz NOT NULL,
    "source_cutoff_json" jsonb NOT NULL,
    "snapshot_checksum" varchar(64),
    CONSTRAINT "ck_report_report_runs_trigger_type" CHECK (trigger_type IN ('MANUAL','SCHEDULE')),
    CONSTRAINT "ck_report_report_runs_status" CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','PARTIAL','FAILED','CANCELLED')),
    CONSTRAINT "ck_report_report_runs_rule_1" CHECK (period_end > period_start)
);
COMMENT ON TABLE "report"."report_runs" IS '수동·스케줄 보고서 실행 1건';
COMMENT ON COLUMN "report"."report_runs"."report_run_id" IS '보고서 실행 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_runs"."report_definition_id" IS '보고서 정의 ID. 정확한 정의 버전 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_runs"."trigger_type" IS '실행 방식. MANUAL/SCHEDULE [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_runs"."triggered_by" IS '실행자. 스케줄이면 NULL [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_runs"."status" IS '전체 상태. PENDING/RUNNING/SUCCEEDED/PARTIAL/FAILED/CANCELLED [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_runs"."context_release_id" IS 'Context release. 실행 기준 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_runs"."sql_policy_version" IS 'SQL 정책 버전. [classification=POLICY]';
COMMENT ON COLUMN "report"."report_runs"."period_start" IS '기간 시작. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_runs"."period_end" IS '기간 종료. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_runs"."source_cutoff_json" IS 'source cutoff. source별 기준 시각 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."report_runs"."snapshot_checksum" IS 'snapshot checksum. 블록 checksum 집합 [classification=INTERNAL]';

-- R04 report.block_runs: 보고서 개별 블록 실행 1건
SELECT pg_temp.assert_table_contract('report', 'block_runs', ARRAY['block_run_id:uuid:true', 'report_run_id:uuid:true', 'report_block_id:uuid:true', 'request_id:uuid:false', 'query_execution_id:uuid:false', 'artifact_id:uuid:false', 'status:character varying(16):true', 'fallback_mode:character varying(24):true', 'source_cutoff_json:jsonb:true', 'result_checksum:character varying(64):false', 'error_code:character varying(64):false', 'error_message_redacted:text:false']::text[]);
CREATE TABLE IF NOT EXISTS "report"."block_runs" (
    "block_run_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "report_run_id" uuid NOT NULL,
    "report_block_id" uuid NOT NULL,
    "request_id" uuid,
    "query_execution_id" uuid,
    "artifact_id" uuid,
    "status" varchar(16) NOT NULL,
    "fallback_mode" varchar(24) NOT NULL,
    "source_cutoff_json" jsonb NOT NULL,
    "result_checksum" varchar(64),
    "error_code" varchar(64),
    "error_message_redacted" text,
    CONSTRAINT "uq_report_block_runs_report_run_id_report_block_id" UNIQUE ("report_run_id", "report_block_id"),
    CONSTRAINT "ck_report_block_runs_status" CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','SKIPPED')),
    CONSTRAINT "ck_report_block_runs_fallback_mode" CHECK (fallback_mode IN ('NONE','LAST_SUCCESS','TEMPLATE'))
);
COMMENT ON TABLE "report"."block_runs" IS '보고서 개별 블록 실행 1건';
COMMENT ON COLUMN "report"."block_runs"."block_run_id" IS '블록 실행 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."report_run_id" IS '보고서 실행 ID. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."report_block_id" IS '보고서 블록 ID. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."request_id" IS '분석 요청 ID. 재실행 요청 [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."query_execution_id" IS 'query 실행 ID. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."artifact_id" IS '결과 artifact ID. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."status" IS '상태. PENDING/RUNNING/SUCCEEDED/FAILED/SKIPPED [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."fallback_mode" IS 'fallback. NONE/LAST_SUCCESS/TEMPLATE [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."source_cutoff_json" IS 'source cutoff. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."result_checksum" IS '결과 checksum. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."error_code" IS '오류 코드. [classification=INTERNAL]';
COMMENT ON COLUMN "report"."block_runs"."error_message_redacted" IS '비식별 오류. [classification=CONFIDENTIAL]';

-- G01 governance.audit_events: 추적·권한·변경 감사 이벤트 1건
SELECT pg_temp.assert_table_contract('governance', 'audit_events', ARRAY['audit_event_id:uuid:true', 'request_id:uuid:false', 'actor_user_id:uuid:false', 'actor_role:character varying(64):true', 'action_code:character varying(96):true', 'object_type:character varying(64):true', 'object_id:character varying(128):true', 'context_release_id:uuid:false', 'model_version_id:uuid:false', 'sql_policy_version:character varying(64):false', 'query_execution_id:uuid:false', 'artifact_id:uuid:false', 'report_run_id:uuid:false', 'details_json_redacted:jsonb:true', 'trace_id:character varying(128):false', 'created_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS "governance"."audit_events" (
    "audit_event_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "request_id" uuid,
    "actor_user_id" uuid,
    "actor_role" varchar(64) NOT NULL,
    "action_code" varchar(96) NOT NULL,
    "object_type" varchar(64) NOT NULL,
    "object_id" varchar(128) NOT NULL,
    "context_release_id" uuid,
    "model_version_id" uuid,
    "sql_policy_version" varchar(64),
    "query_execution_id" uuid,
    "artifact_id" uuid,
    "report_run_id" uuid,
    "details_json_redacted" jsonb NOT NULL,
    "trace_id" varchar(128),
    "created_at" timestamptz NOT NULL
);
COMMENT ON TABLE "governance"."audit_events" IS '추적·권한·변경 감사 이벤트 1건';
COMMENT ON COLUMN "governance"."audit_events"."audit_event_id" IS '감사 이벤트 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."request_id" IS '요청 ID. trace 루트 [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."actor_user_id" IS '행위자 ID. system은 NULL [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."actor_role" IS '행위자 역할. [classification=POLICY]';
COMMENT ON COLUMN "governance"."audit_events"."action_code" IS '행위 코드. CONTEXT_PUBLISH/QUERY_BLOCK/REPORT_RUN 등 [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."object_type" IS '대상 유형. [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."object_id" IS '대상 ID. [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."context_release_id" IS 'Context release. [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."model_version_id" IS '모델 버전. [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."sql_policy_version" IS 'SQL 정책 버전. 실행에 적용된 SQL 정책 버전 [classification=POLICY]';
COMMENT ON COLUMN "governance"."audit_events"."query_execution_id" IS 'query ID. [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."artifact_id" IS 'artifact ID. [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."report_run_id" IS 'report run ID. [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."details_json_redacted" IS '비식별 상세. 민감값 최소화 [classification=CONFIDENTIAL]';
COMMENT ON COLUMN "governance"."audit_events"."trace_id" IS 'OTel trace ID. [classification=INTERNAL]';
COMMENT ON COLUMN "governance"."audit_events"."created_at" IS '발생 시각. UPDATE/DELETE 금지 [classification=INTERNAL]';

-- M01 model.model_versions: sLLM·embedding·ML 모델 버전 1건
SELECT pg_temp.assert_table_contract('model', 'model_versions', ARRAY['model_version_id:uuid:true', 'model_role:character varying(24):true', 'model_name:character varying(160):true', 'checkpoint_ref:character varying(255):true', 'model_revision:character varying(128):true', 'variant_type:character varying(16):true', 'parent_model_version_id:uuid:false', 'license_name:character varying(128):true', 'runtime_name:character varying(64):true', 'container_image_digest:character varying(255):true', 'precision_quantization:character varying(64):false', 'artifact_ref:character varying(512):false', 'status:character varying(16):true']::text[]);
CREATE TABLE IF NOT EXISTS "model"."model_versions" (
    "model_version_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "model_role" varchar(24) NOT NULL,
    "model_name" varchar(160) NOT NULL,
    "checkpoint_ref" varchar(255) NOT NULL,
    "model_revision" varchar(128) NOT NULL,
    "variant_type" varchar(16) NOT NULL,
    "parent_model_version_id" uuid,
    "license_name" varchar(128) NOT NULL,
    "runtime_name" varchar(64) NOT NULL,
    "container_image_digest" varchar(255) NOT NULL,
    "precision_quantization" varchar(64),
    "artifact_ref" varchar(512),
    "status" varchar(16) NOT NULL,
    CONSTRAINT "uq_model_model_versions_model_name_model_revis_d19fad17" UNIQUE ("model_name", "model_revision", "variant_type"),
    CONSTRAINT "ck_model_model_versions_model_role" CHECK (model_role IN ('SQL_GENERATION','EXPLANATION','EMBEDDING','RERANKER','ML_PREDICT')),
    CONSTRAINT "ck_model_model_versions_variant_type" CHECK (variant_type IN ('BASELINE','LORA','QLORA','ONNX')),
    CONSTRAINT "ck_model_model_versions_status" CHECK (status IN ('CANDIDATE','APPROVED','REJECTED','DEPLOYED'))
);
COMMENT ON TABLE "model"."model_versions" IS 'sLLM·embedding·ML 모델 버전 1건';
COMMENT ON COLUMN "model"."model_versions"."model_version_id" IS '모델 버전 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."model_role" IS '모델 역할. SQL_GENERATION/EXPLANATION/EMBEDDING/RERANKER/ML_PREDICT [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."model_name" IS '모델명. [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."checkpoint_ref" IS 'checkpoint. revision과 함께 [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."model_revision" IS 'revision/SHA. [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."variant_type" IS 'variant. BASELINE/LORA/QLORA/ONNX [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."parent_model_version_id" IS '부모 모델. 동일 checkpoint 비교 [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."license_name" IS '라이선스. [classification=POLICY]';
COMMENT ON COLUMN "model"."model_versions"."runtime_name" IS '서빙 runtime. vLLM/SGLang/Transformers/ONNXRuntime [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."container_image_digest" IS 'container image. 재현성 [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."precision_quantization" IS '정밀도·양자화. [classification=INTERNAL]';
COMMENT ON COLUMN "model"."model_versions"."artifact_ref" IS '모델 위치. 영속 storage·외부 백업 [classification=CONFIDENTIAL]';
COMMENT ON COLUMN "model"."model_versions"."status" IS '상태. CANDIDATE/APPROVED/REJECTED/DEPLOYED [classification=INTERNAL]';

-- M02 model.evaluation_runs: baseline·adapter 평가 실행 1건
SELECT pg_temp.assert_table_contract('model', 'evaluation_runs', ARRAY['evaluation_run_id:uuid:true', 'model_version_id:uuid:true', 'comparison_group_id:uuid:false', 'evaluation_set_version:character varying(64):true', 'context_release_id:uuid:true', 'sql_policy_version:character varying(64):true', 'runpod_environment_json:jsonb:true', 'generation_config_json:jsonb:true', 'metrics_json:jsonb:true', 'failure_counts_json:jsonb:true', 'pod_runtime_seconds:integer:false', 'experiment_cost:numeric(14,2):false', 'status:character varying(16):true']::text[]);
CREATE TABLE IF NOT EXISTS "model"."evaluation_runs" (
    "evaluation_run_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "model_version_id" uuid NOT NULL,
    "comparison_group_id" uuid,
    "evaluation_set_version" varchar(64) NOT NULL,
    "context_release_id" uuid NOT NULL,
    "sql_policy_version" varchar(64) NOT NULL,
    "runpod_environment_json" jsonb NOT NULL,
    "generation_config_json" jsonb NOT NULL,
    "metrics_json" jsonb NOT NULL,
    "failure_counts_json" jsonb NOT NULL,
    "pod_runtime_seconds" integer,
    "experiment_cost" numeric(14,2),
    "status" varchar(16) NOT NULL,
    CONSTRAINT "ck_model_evaluation_runs_status" CHECK (status IN ('RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    CONSTRAINT "ck_model_evaluation_runs_rule_1" CHECK (pod_runtime_seconds IS NULL OR pod_runtime_seconds >= 0),
    CONSTRAINT "ck_model_evaluation_runs_rule_2" CHECK (experiment_cost IS NULL OR experiment_cost >= 0)
);
COMMENT ON TABLE "model"."evaluation_runs" IS 'baseline·adapter 평가 실행 1건';
COMMENT ON COLUMN "model"."evaluation_runs"."evaluation_run_id" IS '평가 실행 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."model_version_id" IS '모델 버전. [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."comparison_group_id" IS '비교 그룹. baseline/adapter 동일 그룹 [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."evaluation_set_version" IS '평가 세트 버전. acceptance-30/gold-120/dev [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."context_release_id" IS 'Context release. [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."sql_policy_version" IS 'SQL 정책 버전. [classification=POLICY]';
COMMENT ON COLUMN "model"."evaluation_runs"."runpod_environment_json" IS 'RunPod 환경. GPU·VRAM·region·Cloud·CUDA·storage [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."generation_config_json" IS '생성 설정. max output·temperature·seed [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."metrics_json" IS '평가 지표. accuracy·F1·success·block·p50/p95·VRAM [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."failure_counts_json" IS '실패 유형. schema/field/join/permission/parse/policy/timeout [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."pod_runtime_seconds" IS 'Pod 실행시간. [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."experiment_cost" IS '실험 비용. 통화·환산 기준 별도 [classification=INTERNAL]';
COMMENT ON COLUMN "model"."evaluation_runs"."status" IS '상태. RUNNING/SUCCEEDED/FAILED/CANCELLED [classification=INTERNAL]';

-- REF01 reference.market_benchmark_annual: 시장 모집단·기준연도별 호텔 운영 기준점 1건
SELECT pg_temp.assert_table_contract('reference', 'market_benchmark_annual', ARRAY['benchmark_id:uuid:true', 'benchmark_year:smallint:true', 'population_code:character varying(64):true', 'occupancy_rate:numeric(9,6):false', 'adr_krw:numeric(14,2):false', 'revpar_krw:numeric(14,2):false', 'reference_status:character varying(32):true', 'source_name:character varying(255):true', 'source_url:text:true', 'published_at:date:false', 'extracted_at:timestamp with time zone:true', 'notes:text:false']::text[]);
CREATE TABLE IF NOT EXISTS "reference"."market_benchmark_annual" (
    "benchmark_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "benchmark_year" smallint NOT NULL,
    "population_code" varchar(64) NOT NULL,
    "occupancy_rate" numeric(9,6),
    "adr_krw" numeric(14,2),
    "revpar_krw" numeric(14,2),
    "reference_status" varchar(32) NOT NULL,
    "source_name" varchar(255) NOT NULL,
    "source_url" text NOT NULL,
    "published_at" date,
    "extracted_at" timestamptz NOT NULL,
    "notes" text,
    CONSTRAINT "uq_reference_market_benchmark_annual_benchmark_00cf0410" UNIQUE ("benchmark_year", "population_code"),
    CONSTRAINT "ck_reference_market_benchmark_annual_reference_status" CHECK (reference_status IN ('PUBLISHED','NOT_AVAILABLE')),
    CONSTRAINT "ck_reference_market_benchmark_annual_rule_1" CHECK (benchmark_year BETWEEN 2022 AND 2026),
    CONSTRAINT "ck_reference_market_benchmark_annual_rule_2" CHECK (occupancy_rate IS NULL OR occupancy_rate BETWEEN 0 AND 1),
    CONSTRAINT "ck_reference_market_benchmark_annual_rule_3" CHECK (adr_krw IS NULL OR adr_krw >= 0),
    CONSTRAINT "ck_reference_market_benchmark_annual_rule_4" CHECK (revpar_krw IS NULL OR revpar_krw >= 0)
);
COMMENT ON TABLE "reference"."market_benchmark_annual" IS '시장 모집단·기준연도별 호텔 운영 기준점 1건';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."benchmark_id" IS '기준점 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."benchmark_year" IS '기준연도. 2022~2026 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."population_code" IS '모집단 코드. HOTEL_INDUSTRY 등 [classification=POLICY]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."occupancy_rate" IS 'OCC 기준점. 0~1, 2025·2026 NULL 가능 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."adr_krw" IS 'ADR 기준점. KRW, 2025·2026 NULL 가능 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."revpar_krw" IS 'RevPAR 기준점. KRW, 2025·2026 NULL 가능 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."reference_status" IS '기준 상태. PUBLISHED/NOT_AVAILABLE [classification=POLICY]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."source_name" IS '출처명. 공식 통계·공시 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."source_url" IS '출처 URL. 원문 URL [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."published_at" IS '공표일. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."extracted_at" IS '확인 시각. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."market_benchmark_annual"."notes" IS '비고. 모집단·사용 제한 [classification=INTERNAL]';

-- REF02 reference.demand_index_monthly: 연월·수요유형별 외부 수요 가중치 1건
SELECT pg_temp.assert_table_contract('reference', 'demand_index_monthly', ARRAY['demand_index_id:uuid:true', 'year:smallint:true', 'month:smallint:true', 'demand_type:character varying(24):true', 'index_value:numeric(12,6):true', 'yoy_growth_rate:numeric(12,6):false', 'influence_weight:numeric(12,6):true', 'population_code:character varying(64):true', 'data_status:character varying(32):true', 'source_name:character varying(255):true', 'source_url:text:true', 'published_at:date:false', 'extracted_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS "reference"."demand_index_monthly" (
    "demand_index_id" uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    "year" smallint NOT NULL,
    "month" smallint NOT NULL,
    "demand_type" varchar(24) NOT NULL,
    "index_value" numeric(12,6) NOT NULL,
    "yoy_growth_rate" numeric(12,6),
    "influence_weight" numeric(12,6) NOT NULL,
    "population_code" varchar(64) NOT NULL,
    "data_status" varchar(32) NOT NULL,
    "source_name" varchar(255) NOT NULL,
    "source_url" text NOT NULL,
    "published_at" date,
    "extracted_at" timestamptz NOT NULL,
    CONSTRAINT "uq_reference_demand_index_monthly_year_month_d_043a8907" UNIQUE ("year", "month", "demand_type", "population_code"),
    CONSTRAINT "ck_reference_demand_index_monthly_demand_type" CHECK (demand_type IN ('DOMESTIC','INBOUND','EVENT')),
    CONSTRAINT "ck_reference_demand_index_monthly_data_status" CHECK (data_status IN ('FINAL','PRELIMINARY','FORECAST')),
    CONSTRAINT "ck_reference_demand_index_monthly_rule_1" CHECK (year BETWEEN 2022 AND 2026),
    CONSTRAINT "ck_reference_demand_index_monthly_rule_2" CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT "ck_reference_demand_index_monthly_rule_3" CHECK (index_value >= 0),
    CONSTRAINT "ck_reference_demand_index_monthly_rule_4" CHECK (influence_weight BETWEEN 0 AND 1)
);
COMMENT ON TABLE "reference"."demand_index_monthly" IS '연월·수요유형별 외부 수요 가중치 1건';
COMMENT ON COLUMN "reference"."demand_index_monthly"."demand_index_id" IS '수요지수 ID. PK [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."year" IS '연도. 2022~2026 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."month" IS '월. 1~12 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."demand_type" IS '수요 유형. DOMESTIC/INBOUND/EVENT [classification=POLICY]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."index_value" IS '정규화 지수. 평균 1 근처 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."yoy_growth_rate" IS '전년동월 증감률. 원 비율, NULL 가능 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."influence_weight" IS '호텔 반영 가중치. 직접 복사 방지 [classification=POLICY]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."population_code" IS '모집단 코드. 여행조사/입국통계 구분 [classification=POLICY]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."data_status" IS '자료 상태. FINAL/PRELIMINARY/FORECAST [classification=POLICY]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."source_name" IS '출처명. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."source_url" IS '출처 URL. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."published_at" IS '공표일. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."demand_index_monthly"."extracted_at" IS '확인 시각. [classification=INTERNAL]';

-- REF03 reference.calendar_daily: 영업일자별 달력·기간 상태·수요 시나리오 1건
SELECT pg_temp.assert_table_contract('reference', 'calendar_daily', ARRAY['business_date:date:true', 'year:smallint:true', 'quarter:smallint:true', 'month:smallint:true', 'week_of_year:smallint:true', 'day_of_week:smallint:true', 'is_weekend:boolean:true', 'is_public_holiday:boolean:true', 'is_holiday_eve:boolean:true', 'season_code:character varying(24):true', 'school_vacation_code:character varying(24):false', 'domestic_travel_index:numeric(12,6):true', 'inbound_travel_index:numeric(12,6):true', 'event_demand_index:numeric(12,6):true', 'weather_scenario_code:character varying(32):true', 'data_period_status:character varying(32):true', 'is_forecast:boolean:true', 'created_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS "reference"."calendar_daily" (
    "business_date" date NOT NULL PRIMARY KEY,
    "year" smallint NOT NULL,
    "quarter" smallint NOT NULL,
    "month" smallint NOT NULL,
    "week_of_year" smallint NOT NULL,
    "day_of_week" smallint NOT NULL,
    "is_weekend" boolean NOT NULL,
    "is_public_holiday" boolean NOT NULL,
    "is_holiday_eve" boolean NOT NULL,
    "season_code" varchar(24) NOT NULL,
    "school_vacation_code" varchar(24),
    "domestic_travel_index" numeric(12,6) NOT NULL,
    "inbound_travel_index" numeric(12,6) NOT NULL,
    "event_demand_index" numeric(12,6) NOT NULL,
    "weather_scenario_code" varchar(32) NOT NULL,
    "data_period_status" varchar(32) NOT NULL,
    "is_forecast" boolean NOT NULL,
    "created_at" timestamptz NOT NULL,
    CONSTRAINT "ck_reference_calendar_daily_season_code" CHECK (season_code IN ('SPRING','SUMMER','AUTUMN','WINTER')),
    CONSTRAINT "ck_reference_calendar_daily_data_period_status" CHECK (data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    CONSTRAINT "ck_reference_calendar_daily_rule_1" CHECK (year BETWEEN 2022 AND 2026),
    CONSTRAINT "ck_reference_calendar_daily_rule_2" CHECK (quarter BETWEEN 1 AND 4),
    CONSTRAINT "ck_reference_calendar_daily_rule_3" CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT "ck_reference_calendar_daily_rule_4" CHECK (week_of_year BETWEEN 1 AND 53),
    CONSTRAINT "ck_reference_calendar_daily_rule_5" CHECK (day_of_week BETWEEN 1 AND 7),
    CONSTRAINT "ck_reference_calendar_daily_rule_6" CHECK (domestic_travel_index >= 0),
    CONSTRAINT "ck_reference_calendar_daily_rule_7" CHECK (inbound_travel_index >= 0),
    CONSTRAINT "ck_reference_calendar_daily_rule_8" CHECK (event_demand_index >= 0),
    CONSTRAINT "ck_reference_calendar_daily_rule_9" CHECK ((business_date < DATE '2026-07-29' AND is_forecast = false) OR (business_date >= DATE '2026-07-29' AND is_forecast = true)),
    CONSTRAINT "ck_reference_calendar_daily_rule_10" CHECK ((business_date BETWEEN DATE '2022-01-01' AND DATE '2024-12-31' AND data_period_status='REFERENCE_CALIBRATED') OR (business_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' AND data_period_status='SYNTHETIC_ACTUAL_LIKE') OR (business_date BETWEEN DATE '2026-01-01' AND DATE '2026-07-28' AND data_period_status='YTD_SYNTHETIC') OR (business_date BETWEEN DATE '2026-07-29' AND DATE '2026-12-31' AND data_period_status='FORECAST_SCENARIO'))
);
COMMENT ON TABLE "reference"."calendar_daily" IS '영업일자별 달력·기간 상태·수요 시나리오 1건';
COMMENT ON COLUMN "reference"."calendar_daily"."business_date" IS '영업일자. PK [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."year" IS '연도. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."quarter" IS '분기. 1~4 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."month" IS '월. 1~12 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."week_of_year" IS '주차. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."day_of_week" IS '요일. 1~7 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."is_weekend" IS '주말 여부. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."is_public_holiday" IS '공휴일 여부. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."is_holiday_eve" IS '연휴 전일 여부. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."season_code" IS '계절 코드. SPRING/SUMMER/AUTUMN/WINTER [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."school_vacation_code" IS '방학 코드. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."domestic_travel_index" IS '국내여행 지수. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."inbound_travel_index" IS '외래관광 지수. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."event_demand_index" IS '행사 수요 지수. [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."weather_scenario_code" IS '기상 시나리오. 합성 시나리오 [classification=INTERNAL]';
COMMENT ON COLUMN "reference"."calendar_daily"."data_period_status" IS '기간 상태. 4개 고정 상태 [classification=POLICY]';
COMMENT ON COLUMN "reference"."calendar_daily"."is_forecast" IS '전망 여부. 2026-07-29 이후 true [classification=POLICY]';
COMMENT ON COLUMN "reference"."calendar_daily"."created_at" IS '생성 시각. [classification=INTERNAL]';

-- 2. 물리 FK

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_connection_ingestion_runs_data_source_id_co_48384c19'
      AND conrelid = 'connection.ingestion_runs'::regclass
  ) THEN
    ALTER TABLE "connection"."ingestion_runs"
      ADD CONSTRAINT "fk_connection_ingestion_runs_data_source_id_co_48384c19" FOREIGN KEY ("data_source_id") REFERENCES "connection"."data_sources" ("data_source_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_context_context_releases_rollback_release_i_9c1c95d6'
      AND conrelid = 'context.context_releases'::regclass
  ) THEN
    ALTER TABLE "context"."context_releases"
      ADD CONSTRAINT "fk_context_context_releases_rollback_release_i_9c1c95d6" FOREIGN KEY ("rollback_release_id") REFERENCES "context"."context_releases" ("context_release_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_context_context_packages_request_id_chat_an_b6baff05'
      AND conrelid = 'context.context_packages'::regclass
  ) THEN
    ALTER TABLE "context"."context_packages"
      ADD CONSTRAINT "fk_context_context_packages_request_id_chat_an_b6baff05" FOREIGN KEY ("request_id") REFERENCES "chat"."analysis_requests" ("request_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_context_context_packages_context_release_id_d5608a93'
      AND conrelid = 'context.context_packages'::regclass
  ) THEN
    ALTER TABLE "context"."context_packages"
      ADD CONSTRAINT "fk_context_context_packages_context_release_id_d5608a93" FOREIGN KEY ("context_release_id") REFERENCES "context"."context_releases" ("context_release_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_chat_analysis_requests_conversation_id_chat_29afa8fc'
      AND conrelid = 'chat.analysis_requests'::regclass
  ) THEN
    ALTER TABLE "chat"."analysis_requests"
      ADD CONSTRAINT "fk_chat_analysis_requests_conversation_id_chat_29afa8fc" FOREIGN KEY ("conversation_id") REFERENCES "chat"."conversations" ("conversation_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_chat_analysis_requests_context_release_id_c_f3f67b18'
      AND conrelid = 'chat.analysis_requests'::regclass
  ) THEN
    ALTER TABLE "chat"."analysis_requests"
      ADD CONSTRAINT "fk_chat_analysis_requests_context_release_id_c_f3f67b18" FOREIGN KEY ("context_release_id") REFERENCES "context"."context_releases" ("context_release_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_chat_analysis_requests_context_package_id_c_a1aa7160'
      AND conrelid = 'chat.analysis_requests'::regclass
  ) THEN
    ALTER TABLE "chat"."analysis_requests"
      ADD CONSTRAINT "fk_chat_analysis_requests_context_package_id_c_a1aa7160" FOREIGN KEY ("context_package_id") REFERENCES "context"."context_packages" ("context_package_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_chat_analysis_requests_sql_generation_model_6eabdd74'
      AND conrelid = 'chat.analysis_requests'::regclass
  ) THEN
    ALTER TABLE "chat"."analysis_requests"
      ADD CONSTRAINT "fk_chat_analysis_requests_sql_generation_model_6eabdd74" FOREIGN KEY ("sql_generation_model_id") REFERENCES "model"."model_versions" ("model_version_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_query_query_executions_request_id_chat_anal_40a1fcb7'
      AND conrelid = 'query.query_executions'::regclass
  ) THEN
    ALTER TABLE "query"."query_executions"
      ADD CONSTRAINT "fk_query_query_executions_request_id_chat_anal_40a1fcb7" FOREIGN KEY ("request_id") REFERENCES "chat"."analysis_requests" ("request_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_artifact_analysis_artifacts_request_id_chat_8ab8e8d0'
      AND conrelid = 'artifact.analysis_artifacts'::regclass
  ) THEN
    ALTER TABLE "artifact"."analysis_artifacts"
      ADD CONSTRAINT "fk_artifact_analysis_artifacts_request_id_chat_8ab8e8d0" FOREIGN KEY ("request_id") REFERENCES "chat"."analysis_requests" ("request_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_artifact_analysis_artifacts_query_execution_1e4a990d'
      AND conrelid = 'artifact.analysis_artifacts'::regclass
  ) THEN
    ALTER TABLE "artifact"."analysis_artifacts"
      ADD CONSTRAINT "fk_artifact_analysis_artifacts_query_execution_1e4a990d" FOREIGN KEY ("query_execution_id") REFERENCES "query"."query_executions" ("query_execution_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_report_report_blocks_report_definition_id_r_32727520'
      AND conrelid = 'report.report_blocks'::regclass
  ) THEN
    ALTER TABLE "report"."report_blocks"
      ADD CONSTRAINT "fk_report_report_blocks_report_definition_id_r_32727520" FOREIGN KEY ("report_definition_id") REFERENCES "report"."report_definitions" ("report_definition_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_report_report_blocks_source_artifact_id_art_20b5bf76'
      AND conrelid = 'report.report_blocks'::regclass
  ) THEN
    ALTER TABLE "report"."report_blocks"
      ADD CONSTRAINT "fk_report_report_blocks_source_artifact_id_art_20b5bf76" FOREIGN KEY ("source_artifact_id") REFERENCES "artifact"."analysis_artifacts" ("artifact_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_report_report_runs_report_definition_id_rep_28aa2dd7'
      AND conrelid = 'report.report_runs'::regclass
  ) THEN
    ALTER TABLE "report"."report_runs"
      ADD CONSTRAINT "fk_report_report_runs_report_definition_id_rep_28aa2dd7" FOREIGN KEY ("report_definition_id") REFERENCES "report"."report_definitions" ("report_definition_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_report_report_runs_context_release_id_conte_74ce933e'
      AND conrelid = 'report.report_runs'::regclass
  ) THEN
    ALTER TABLE "report"."report_runs"
      ADD CONSTRAINT "fk_report_report_runs_context_release_id_conte_74ce933e" FOREIGN KEY ("context_release_id") REFERENCES "context"."context_releases" ("context_release_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_report_block_runs_report_run_id_report_report_runs'
      AND conrelid = 'report.block_runs'::regclass
  ) THEN
    ALTER TABLE "report"."block_runs"
      ADD CONSTRAINT "fk_report_block_runs_report_run_id_report_report_runs" FOREIGN KEY ("report_run_id") REFERENCES "report"."report_runs" ("report_run_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_report_block_runs_report_block_id_report_re_29f3fe52'
      AND conrelid = 'report.block_runs'::regclass
  ) THEN
    ALTER TABLE "report"."block_runs"
      ADD CONSTRAINT "fk_report_block_runs_report_block_id_report_re_29f3fe52" FOREIGN KEY ("report_block_id") REFERENCES "report"."report_blocks" ("report_block_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_report_block_runs_request_id_chat_analysis_requests'
      AND conrelid = 'report.block_runs'::regclass
  ) THEN
    ALTER TABLE "report"."block_runs"
      ADD CONSTRAINT "fk_report_block_runs_request_id_chat_analysis_requests" FOREIGN KEY ("request_id") REFERENCES "chat"."analysis_requests" ("request_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_report_block_runs_query_execution_id_query__68278c33'
      AND conrelid = 'report.block_runs'::regclass
  ) THEN
    ALTER TABLE "report"."block_runs"
      ADD CONSTRAINT "fk_report_block_runs_query_execution_id_query__68278c33" FOREIGN KEY ("query_execution_id") REFERENCES "query"."query_executions" ("query_execution_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_report_block_runs_artifact_id_artifact_anal_59dd1721'
      AND conrelid = 'report.block_runs'::regclass
  ) THEN
    ALTER TABLE "report"."block_runs"
      ADD CONSTRAINT "fk_report_block_runs_artifact_id_artifact_anal_59dd1721" FOREIGN KEY ("artifact_id") REFERENCES "artifact"."analysis_artifacts" ("artifact_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_governance_audit_events_request_id_chat_ana_1000c01f'
      AND conrelid = 'governance.audit_events'::regclass
  ) THEN
    ALTER TABLE "governance"."audit_events"
      ADD CONSTRAINT "fk_governance_audit_events_request_id_chat_ana_1000c01f" FOREIGN KEY ("request_id") REFERENCES "chat"."analysis_requests" ("request_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_governance_audit_events_context_release_id__c142237b'
      AND conrelid = 'governance.audit_events'::regclass
  ) THEN
    ALTER TABLE "governance"."audit_events"
      ADD CONSTRAINT "fk_governance_audit_events_context_release_id__c142237b" FOREIGN KEY ("context_release_id") REFERENCES "context"."context_releases" ("context_release_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_governance_audit_events_model_version_id_mo_ed9d2887'
      AND conrelid = 'governance.audit_events'::regclass
  ) THEN
    ALTER TABLE "governance"."audit_events"
      ADD CONSTRAINT "fk_governance_audit_events_model_version_id_mo_ed9d2887" FOREIGN KEY ("model_version_id") REFERENCES "model"."model_versions" ("model_version_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_governance_audit_events_query_execution_id__9d2bc271'
      AND conrelid = 'governance.audit_events'::regclass
  ) THEN
    ALTER TABLE "governance"."audit_events"
      ADD CONSTRAINT "fk_governance_audit_events_query_execution_id__9d2bc271" FOREIGN KEY ("query_execution_id") REFERENCES "query"."query_executions" ("query_execution_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_governance_audit_events_artifact_id_artifac_b554f96a'
      AND conrelid = 'governance.audit_events'::regclass
  ) THEN
    ALTER TABLE "governance"."audit_events"
      ADD CONSTRAINT "fk_governance_audit_events_artifact_id_artifac_b554f96a" FOREIGN KEY ("artifact_id") REFERENCES "artifact"."analysis_artifacts" ("artifact_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_governance_audit_events_report_run_id_repor_6e2fec76'
      AND conrelid = 'governance.audit_events'::regclass
  ) THEN
    ALTER TABLE "governance"."audit_events"
      ADD CONSTRAINT "fk_governance_audit_events_report_run_id_repor_6e2fec76" FOREIGN KEY ("report_run_id") REFERENCES "report"."report_runs" ("report_run_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_model_model_versions_parent_model_version_i_a3041017'
      AND conrelid = 'model.model_versions'::regclass
  ) THEN
    ALTER TABLE "model"."model_versions"
      ADD CONSTRAINT "fk_model_model_versions_parent_model_version_i_a3041017" FOREIGN KEY ("parent_model_version_id") REFERENCES "model"."model_versions" ("model_version_id");
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_model_evaluation_runs_model_version_id_mode_576d162d'
      AND conrelid = 'model.evaluation_runs'::regclass
  ) THEN
    ALTER TABLE "model"."evaluation_runs"
      ADD CONSTRAINT "fk_model_evaluation_runs_model_version_id_mode_576d162d" FOREIGN KEY ("model_version_id") REFERENCES "model"."model_versions" ("model_version_id");
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_model_evaluation_runs_context_release_id_co_91348998'
      AND conrelid = 'model.evaluation_runs'::regclass
  ) THEN
    ALTER TABLE "model"."evaluation_runs"
      ADD CONSTRAINT "fk_model_evaluation_runs_context_release_id_co_91348998" FOREIGN KEY ("context_release_id") REFERENCES "context"."context_releases" ("context_release_id");
  END IF;
END
$$;

-- 3. FK 및 권고 인덱스

CREATE INDEX IF NOT EXISTS "ix_connection_ingestion_runs_data_source_id" ON "connection"."ingestion_runs" ("data_source_id");

CREATE INDEX IF NOT EXISTS "ix_context_context_records_record_type_status__a6378550" ON "context"."context_records" ("record_type", "status", "record_key", "version_no");

CREATE INDEX IF NOT EXISTS "ix_context_context_releases_rollback_release_id" ON "context"."context_releases" ("rollback_release_id");

CREATE INDEX IF NOT EXISTS "ix_context_context_packages_request_id" ON "context"."context_packages" ("request_id");
CREATE INDEX IF NOT EXISTS "ix_context_context_packages_context_release_id" ON "context"."context_packages" ("context_release_id");

CREATE INDEX IF NOT EXISTS "ix_chat_analysis_requests_conversation_id" ON "chat"."analysis_requests" ("conversation_id");
CREATE INDEX IF NOT EXISTS "ix_chat_analysis_requests_context_release_id" ON "chat"."analysis_requests" ("context_release_id");
CREATE INDEX IF NOT EXISTS "ix_chat_analysis_requests_context_package_id" ON "chat"."analysis_requests" ("context_package_id");
CREATE INDEX IF NOT EXISTS "ix_chat_analysis_requests_sql_generation_model_id" ON "chat"."analysis_requests" ("sql_generation_model_id");
CREATE INDEX IF NOT EXISTS "ix_chat_analysis_requests_status_started_at" ON "chat"."analysis_requests" ("status", "started_at");

CREATE INDEX IF NOT EXISTS "ix_query_query_executions_request_id" ON "query"."query_executions" ("request_id");
CREATE INDEX IF NOT EXISTS "ix_query_query_executions_request_id_execution_status" ON "query"."query_executions" ("request_id", "execution_status");

CREATE INDEX IF NOT EXISTS "ix_artifact_analysis_artifacts_request_id" ON "artifact"."analysis_artifacts" ("request_id");
CREATE INDEX IF NOT EXISTS "ix_artifact_analysis_artifacts_query_execution_id" ON "artifact"."analysis_artifacts" ("query_execution_id");
CREATE INDEX IF NOT EXISTS "ix_artifact_analysis_artifacts_request_id_status" ON "artifact"."analysis_artifacts" ("request_id", "status");

CREATE INDEX IF NOT EXISTS "ix_report_report_blocks_report_definition_id" ON "report"."report_blocks" ("report_definition_id");
CREATE INDEX IF NOT EXISTS "ix_report_report_blocks_source_artifact_id" ON "report"."report_blocks" ("source_artifact_id");

CREATE INDEX IF NOT EXISTS "ix_report_report_runs_report_definition_id" ON "report"."report_runs" ("report_definition_id");
CREATE INDEX IF NOT EXISTS "ix_report_report_runs_context_release_id" ON "report"."report_runs" ("context_release_id");
CREATE INDEX IF NOT EXISTS "ix_report_report_runs_report_definition_id_per_d6269048" ON "report"."report_runs" ("report_definition_id", "period_start", "status");

CREATE INDEX IF NOT EXISTS "ix_report_block_runs_report_run_id" ON "report"."block_runs" ("report_run_id");
CREATE INDEX IF NOT EXISTS "ix_report_block_runs_report_block_id" ON "report"."block_runs" ("report_block_id");
CREATE INDEX IF NOT EXISTS "ix_report_block_runs_request_id" ON "report"."block_runs" ("request_id");
CREATE INDEX IF NOT EXISTS "ix_report_block_runs_query_execution_id" ON "report"."block_runs" ("query_execution_id");
CREATE INDEX IF NOT EXISTS "ix_report_block_runs_artifact_id" ON "report"."block_runs" ("artifact_id");

CREATE INDEX IF NOT EXISTS "ix_governance_audit_events_request_id" ON "governance"."audit_events" ("request_id");
CREATE INDEX IF NOT EXISTS "ix_governance_audit_events_context_release_id" ON "governance"."audit_events" ("context_release_id");
CREATE INDEX IF NOT EXISTS "ix_governance_audit_events_model_version_id" ON "governance"."audit_events" ("model_version_id");
CREATE INDEX IF NOT EXISTS "ix_governance_audit_events_query_execution_id" ON "governance"."audit_events" ("query_execution_id");
CREATE INDEX IF NOT EXISTS "ix_governance_audit_events_artifact_id" ON "governance"."audit_events" ("artifact_id");
CREATE INDEX IF NOT EXISTS "ix_governance_audit_events_report_run_id" ON "governance"."audit_events" ("report_run_id");
CREATE INDEX IF NOT EXISTS "ix_governance_audit_events_request_id_created_at" ON "governance"."audit_events" ("request_id", "created_at");

CREATE INDEX IF NOT EXISTS "ix_model_model_versions_parent_model_version_id" ON "model"."model_versions" ("parent_model_version_id");

CREATE INDEX IF NOT EXISTS "ix_model_evaluation_runs_model_version_id" ON "model"."evaluation_runs" ("model_version_id");
CREATE INDEX IF NOT EXISTS "ix_model_evaluation_runs_context_release_id" ON "model"."evaluation_runs" ("context_release_id");

-- 4. 구조 검증
WITH expected(schema_name, expected_count) AS (
  VALUES
    ('connection', 2), ('context', 3), ('chat', 2), ('query', 1),
    ('artifact', 1), ('report', 4), ('governance', 1), ('model', 2),
    ('reference', 3)
),
actual AS (
  SELECT table_schema, count(*)::integer AS actual_count
  FROM information_schema.tables
  WHERE table_type='BASE TABLE'
    AND table_catalog=current_database()
    AND table_schema IN ('connection','context','chat','query','artifact','report','governance','model','reference')
  GROUP BY table_schema
)
SELECT e.schema_name, e.expected_count, coalesce(a.actual_count,0) AS actual_count,
       CASE WHEN e.expected_count=coalesce(a.actual_count,0) THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM expected e
LEFT JOIN actual a ON a.table_schema=e.schema_name
ORDER BY e.schema_name;

SELECT count(*) AS application_base_table_count,
       CASE WHEN count(*)=19 THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM information_schema.tables
WHERE table_type='BASE TABLE'
  AND table_schema IN ('connection','context','chat','query','artifact','report','governance','model','reference');

SELECT count(*) AS application_base_column_count,
       CASE WHEN count(*)=250 THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM information_schema.columns
WHERE table_schema IN ('connection','context','chat','query','artifact','report','governance','model','reference');

SELECT n.nspname AS schema_name, c.relname AS table_name, con.conname, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class c ON c.oid=con.conrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('connection','context','chat','query','artifact','report','governance','model','reference')
ORDER BY n.nspname,c.relname,con.conname;

SELECT n.nspname AS schema_name, c.relname AS object_name, c.relkind
FROM pg_class c
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('connection','context','chat','query','artifact','report','governance','model','reference','analytics')
  AND c.relkind IN ('r','v','m','i')
ORDER BY n.nspname,c.relkind,c.relname;
