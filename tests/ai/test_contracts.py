import copy
import json
import unittest

from src.ai.schema import ContractError, schema_version, validate_payload


EXECUTION_TIME = {
    "as_of": "2026-07-30T12:00:00+09:00",
    "timezone": "Asia/Seoul",
    "calendar_id": "gregorian-kr",
    "period_start": "2026-07-01T00:00:00+09:00",
    "period_end_exclusive": "2026-07-30T12:00:00+09:00",
}

def qualified_field(asset_fqn, column):
    return {"asset_fqn": asset_fqn, "column": column}


def _payload_shape(value):
    if isinstance(value, dict):
        return {key: _payload_shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_payload_shape(item) for item in value]
    return type(value).__name__


def arbitrary_node2_request(namespace):
    catalog = f"{namespace}_catalog"
    fact_fqn = f"{catalog}.semantic.fact_observations"
    dimension_fqn = f"{catalog}.semantic.dim_entities"
    metric_id = f"{namespace}_measure"
    join_id = f"{namespace}_fact_to_dimension"
    status_parameter = f"{namespace}_status"

    return {
        "question_id": f"question-{namespace}",
        "normalized_question": (
            "aggregate the resolved measure by the resolved dimension"
        ),
        "resolved_request": {
            "intent": "aggregate",
            "metric_ids": [metric_id],
            "output_metric_ids": [metric_id],
            "dimensions": [qualified_field(dimension_fqn, "category_code")],
            "filters": [
                {
                    "field": qualified_field(fact_fqn, "status_code"),
                    "operator": "eq",
                    "parameter": status_parameter,
                }
            ],
            "time_bucket": "none",
            "result_limit": None,
        },
        "schema_context": {
            "version": f"schema-{namespace}",
            "assets": [
                {
                    "urn": f"urn:example:dataset:{namespace}:observations",
                    "fqn": fact_fqn,
                    "grain": {
                        "kind": "event",
                        "keys": ["observation_id"],
                    },
                    "columns": [
                        {
                            "name": "observation_id",
                            "native_type": "varchar",
                            "nullable": False,
                            "role": "identifier",
                        },
                        {
                            "name": "entity_id",
                            "native_type": "bigint",
                            "nullable": False,
                            "role": "identifier",
                        },
                        {
                            "name": "observed_at",
                            "native_type": "timestamp with time zone",
                            "nullable": False,
                            "role": "time",
                        },
                        {
                            "name": "amount",
                            "native_type": "decimal(18,2)",
                            "nullable": False,
                            "role": "measure",
                        },
                        {
                            "name": "status_code",
                            "native_type": "varchar",
                            "nullable": False,
                            "role": "attribute",
                        },
                    ],
                },
                {
                    "urn": f"urn:example:dataset:{namespace}:entities",
                    "fqn": dimension_fqn,
                    "grain": {"kind": "row", "keys": ["entity_id"]},
                    "columns": [
                        {
                            "name": "entity_id",
                            "native_type": "bigint",
                            "nullable": False,
                            "role": "identifier",
                        },
                        {
                            "name": "category_code",
                            "native_type": "varchar",
                            "nullable": False,
                            "role": "dimension",
                        },
                        {
                            "name": "valid_from",
                            "native_type": "timestamp with time zone",
                            "nullable": False,
                            "role": "time",
                        },
                        {
                            "name": "valid_to",
                            "native_type": "timestamp with time zone",
                            "nullable": True,
                            "role": "time",
                        },
                    ],
                },
            ],
        },
        "metric_rules": [
            {
                "id": metric_id,
                "source": {
                    "kind": "column",
                    "field": qualified_field(fact_fqn, "amount"),
                },
                "aggregation": "sum",
                "result_field": "resolved_measure",
                "unit": "arbitrary_unit",
                "time_field": qualified_field(fact_fqn, "observed_at"),
                "dimensions": [
                    qualified_field(dimension_fqn, "category_code")
                ],
                "required_filters": [
                    {
                        "field": qualified_field(fact_fqn, "status_code"),
                        "operator": "eq",
                        "parameter": status_parameter,
                    }
                ],
            }
        ],
        "join_graph": {
            "edges": [
                {
                    "id": join_id,
                    "left": fact_fqn,
                    "right": dimension_fqn,
                    "kind": "left",
                    "cardinality": "many_to_one",
                    "equality_conditions": [
                        {
                            "left_column": "entity_id",
                            "right_column": "entity_id",
                        }
                    ],
                    "temporal_conditions": [
                        {
                            "event_field": qualified_field(
                                fact_fqn, "observed_at"
                            ),
                            "validity_asset_fqn": dimension_fqn,
                            "valid_from_column": "valid_from",
                            "valid_to_column": "valid_to",
                            "end_exclusive": True,
                        }
                    ],
                    "preaggregation": {
                        "required": False,
                        "grain": [
                            qualified_field(fact_fqn, "entity_id"),
                            qualified_field(fact_fqn, "observed_at"),
                        ],
                        "keys": [qualified_field(fact_fqn, "entity_id")],
                    },
                }
            ]
        },
        "time_rules": {
            "timezone": "UTC",
            "calendar_id": "gregorian",
            "interval": "[start,end)",
            "start_parameter": f"{namespace}_window_start",
            "end_parameter": f"{namespace}_window_end",
            "fields": [
                {
                    "field": qualified_field(fact_fqn, "observed_at"),
                    "native_type": "timestamp with time zone",
                    "bucket": "month",
                    "timezone_mode": "preserve",
                }
            ],
        },
        "parameter_contract": {
            "style": "named",
            "parameters": [
                {
                    "name": f"{namespace}_window_start",
                    "type": "timestamp",
                    "scope": "time",
                },
                {
                    "name": f"{namespace}_window_end",
                    "type": "timestamp",
                    "scope": "time",
                },
                {
                    "name": status_parameter,
                    "type": "string",
                    "scope": "filter",
                },
            ],
        },
        "query_policy": {
            "dialect": "trino",
            "statement_type": "select",
            "read_only": True,
            "require_limit": True,
            "max_limit": 500,
            "allowed_functions": ["date_trunc", "from_iso8601_timestamp", "sum"],
            "allowed_catalogs": [catalog],
        },
    }


def arbitrary_node2_response(namespace):
    fact_fqn = f"{namespace}_catalog.semantic.fact_observations"
    dimension_fqn = f"{namespace}_catalog.semantic.dim_entities"
    return {
        "sql": (
            "SELECT d.category_code, SUM(f.amount) AS resolved_measure "
            f"FROM {fact_fqn} AS f LEFT JOIN {dimension_fqn} AS d "
            "ON f.entity_id = d.entity_id "
            "AND f.observed_at >= d.valid_from AND f.observed_at < d.valid_to "
            "WHERE f.observed_at >= "
            f"from_iso8601_timestamp(:{namespace}_window_start) "
            "AND f.observed_at < "
            f"from_iso8601_timestamp(:{namespace}_window_end) "
            f"AND f.status_code = :{namespace}_status "
            "GROUP BY d.category_code LIMIT 500"
        ),
        "used_assets": [fact_fqn, dimension_fqn],
        "used_columns": [
            qualified_field(fact_fqn, "amount"),
            qualified_field(fact_fqn, "entity_id"),
            qualified_field(fact_fqn, "observed_at"),
            qualified_field(fact_fqn, "status_code"),
            qualified_field(dimension_fqn, "category_code"),
            qualified_field(dimension_fqn, "entity_id"),
            qualified_field(dimension_fqn, "valid_from"),
            qualified_field(dimension_fqn, "valid_to"),
        ],
        "used_joins": [f"{namespace}_fact_to_dimension"],
        "used_metrics": [f"{namespace}_measure"],
    }


NODE2_REQUEST = arbitrary_node2_request("quartz")
NODE2_RESPONSE = arbitrary_node2_response("quartz")

NODE1_INTERPRETATION_CONTEXT = {
    "schema_version": "Node1InterpretationContext.v1",
    "source_authority": "DATAHUB_NATIVE_METRIC_V1",
    "release_evidence": {
        "product_release_id": "test-product-release",
        "semantic_release_id": "test-semantic-release",
        "catalog_sha256": "1" * 64,
        "canonical_sha256": "2" * 64,
        "runtime_projection_sha256": "3" * 64,
    },
    "permission_snapshot_id": "test-permission-receipt",
    "retrieval_evidence": {
        "mode": "datahub_lexical",
        "asset_urns": ["urn:li:dataset:(urn:li:dataPlatform:trino,serving.room_daily,PROD)"],
        "metric_ranks": [{"metric_id": "room_revenue", "rank": 1}],
    },
    "metrics": [
        {
            "datahub_urn": "urn:li:metric:room_revenue",
            "canonical_id": "room_revenue",
            "canonical_name": "room_revenue",
            "label": "객실 매출",
            "definition": "승인된 객실 매출 합계",
            "synonyms": ["객실 매출"],
            "unit": "KRW",
            "aggregation": "sum",
            "time_semantics": {
                "mode": "range",
                "calendar_id": "gregorian-kr",
                "time_field": "business_date",
            },
            "allowed_dimension_ids": [],
            "allowed_filter_ids": [],
            "positive_examples": [],
            "negative_examples": [],
            "approval_status": "APPROVED",
            "quality_status": "ACTIVE_RELEASE_VERIFIED",
            "source_authority": "DATAHUB_NATIVE_METRIC_V1",
        }
    ],
    "dimensions": [],
}


VALID_PAYLOADS = {
    "node1_request": {
        "question": "이번 달 객실 매출을 보여줘",
        "role_hint": "analyst",
        "as_of": "2026-07-30T12:00:00+09:00",
        "timezone": "Asia/Seoul",
        "calendar_id": "gregorian-kr",
        "allowed_routes": ["analysis"],
        "business_terms": {
            "room_revenue": {"kind": "metric", "aliases": ["객실 매출"]}
        },
        "interpretation_context": copy.deepcopy(NODE1_INTERPRETATION_CONTEXT),
    },
    "node1_response": {
        "normalized_question": "이번 달 객실 매출을 보여줘",
        "intent_candidates": ["aggregate"],
        "measurement_source_text": "객실 매출",
        "measurement_source_texts": ["객실 매출"],
        "metric_candidates": ["room_revenue"],
        "metric_resolution": "selected",
        "selected_metric_id": "room_revenue",
        "selected_metric_ids": ["room_revenue"],
        "analysis_operation": "aggregate",
        "analysis_time_bucket": None,
        "result_limit": None,
        "dimension_candidates": [],
        "filter_candidates": [],
        "period_candidates": [
            {
                "start": "2026-07-01T00:00:00+09:00",
                "end_exclusive": "2026-07-30T12:00:00+09:00",
                "source_text": "이번 달",
            }
        ],
        "period_relationship": "single",
        "ambiguity": {
            "is_ambiguous": False,
            "reasons": [],
            "clarification_question": None,
        },
    },
    "node2_request": NODE2_REQUEST,
    "node2_response": NODE2_RESPONSE,
    "node2_repair_request": {
        "trace_id": "trace-1",
        "attempt": 1,
        "rejected_sql": "SELECT invalid_identifier",
        **{
            field: copy.deepcopy(NODE2_REQUEST[field])
            for field in (
                "normalized_question",
                "resolved_request",
                "schema_context",
                "metric_rules",
                "join_graph",
                "time_rules",
                "parameter_contract",
                "query_policy",
            )
        },
        "normalized_error_code": "UNKNOWN_COLUMN",
        "repair_scope": ["column"],
    },
    "node2_repair_response": {
        "corrected_sql": NODE2_RESPONSE["sql"],
    },
    "node3_request": {
        "g3_result": "pass",
        "shaped_result": {
            "columns": [{"name": "room_revenue", "type": "decimal"}],
            "rows": [{"room_revenue": 1000}],
        },
        "metric": "room_revenue",
        "metric_label": "객실 매출",
        "period": EXECUTION_TIME,
        "filters": [],
        "unit": "KRW",
        "sampling": False,
        "masking": True,
        "partial": False,
        "source_ids": ["pms.public.reservations"],
        "result_reference": {"kind": "query_execution_id", "value": "query-1"},
    },
    "node3_response": {
        "explanation": "fixture",
        "conditions": [],
        "sources": [],
        "limitations": [],
    },
}


class ContractTests(unittest.TestCase):
    def test_schema_version_is_explicit(self):
        self.assertEqual(schema_version(), "MODEL-v1.28.0")

    def test_valid_examples(self):
        for definition, payload in VALID_PAYLOADS.items():
            with self.subTest(definition=definition):
                validate_payload(definition, payload)

    def test_node1_accepts_progressive_kpi_and_full_presentation_types(self):
        for presentation_type in ("KPI", "FULL"):
            payload = copy.deepcopy(VALID_PAYLOADS["node1_response"])
            payload["requested_route"] = "PRESENTATION"
            payload["presentation_type"] = presentation_type
            with self.subTest(presentation_type=presentation_type):
                validate_payload("node1_response", payload)

    def test_node1_selected_metric_is_required_and_nullable(self):
        missing = copy.deepcopy(VALID_PAYLOADS["node1_response"])
        missing.pop("selected_metric_id")
        with self.assertRaises(ContractError):
            validate_payload("node1_response", missing)

        ambiguous = copy.deepcopy(VALID_PAYLOADS["node1_response"])
        ambiguous["metric_candidates"] = ["room_revenue", "fnb_revenue"]
        ambiguous["metric_resolution"] = "ambiguous"
        ambiguous["selected_metric_id"] = None
        ambiguous["selected_metric_ids"] = []
        validate_payload("node1_response", ambiguous)

    def test_node1_metric_resolution_is_required_and_typed(self):
        missing = copy.deepcopy(VALID_PAYLOADS["node1_response"])
        missing.pop("metric_resolution")
        with self.assertRaises(ContractError):
            validate_payload("node1_response", missing)

        unsupported = copy.deepcopy(VALID_PAYLOADS["node1_response"])
        unsupported["measurement_source_text"] = "객실 매출"
        unsupported["metric_candidates"] = []
        unsupported["metric_resolution"] = "unsupported"
        unsupported["selected_metric_id"] = None
        unsupported["selected_metric_ids"] = []
        validate_payload("node1_response", unsupported)

        no_measurement = copy.deepcopy(VALID_PAYLOADS["node1_response"])
        no_measurement["measurement_source_text"] = None
        no_measurement["measurement_source_texts"] = []
        no_measurement["metric_candidates"] = []
        no_measurement["metric_resolution"] = "missing"
        no_measurement["selected_metric_id"] = None
        no_measurement["selected_metric_ids"] = []
        no_measurement["analysis_operation"] = None
        validate_payload("node1_response", no_measurement)

    def test_node1_accepts_runtime_owned_business_terms(self):
        request = copy.deepcopy(VALID_PAYLOADS["node1_request"])
        request["business_terms"] = {
            "arbitrary_runtime_measure": {
                "kind": "metric",
                "aliases": ["Reviewed measure", "검토 측정값"],
            }
        }

        validate_payload("node1_request", request)

    def test_node2_requires_every_structured_contract(self):
        required = (
            "normalized_question",
            "resolved_request",
            "schema_context",
            "metric_rules",
            "join_graph",
            "time_rules",
            "parameter_contract",
            "query_policy",
        )
        for field in required:
            missing = copy.deepcopy(NODE2_REQUEST)
            missing.pop(field)
            with self.subTest(missing=field):
                with self.assertRaises(ContractError):
                    validate_payload("node2_request", missing)

    def test_node2_accepts_arbitrary_isomorphic_schema_contexts(self):
        quartz = arbitrary_node2_request("quartz")
        zephyr = arbitrary_node2_request("zephyr")
        for payload in (quartz, zephyr):
            validate_payload("node2_request", payload)
        self.assertNotEqual(
            quartz["schema_context"]["assets"][0]["fqn"],
            zephyr["schema_context"]["assets"][0]["fqn"],
        )
        self.assertEqual(_payload_shape(quartz), _payload_shape(zephyr))

    def test_node2_assets_require_grain_and_typed_columns(self):
        invalid_payloads = []
        missing_grain = copy.deepcopy(NODE2_REQUEST)
        missing_grain["schema_context"]["assets"][0].pop("grain")
        invalid_payloads.append(missing_grain)
        empty_grain = copy.deepcopy(NODE2_REQUEST)
        empty_grain["schema_context"]["assets"][0]["grain"]["keys"] = []
        invalid_payloads.append(empty_grain)
        untyped_column = copy.deepcopy(NODE2_REQUEST)
        untyped_column["schema_context"]["assets"][0]["columns"][0].pop(
            "native_type"
        )
        invalid_payloads.append(untyped_column)
        column_with_sql = copy.deepcopy(NODE2_REQUEST)
        column_with_sql["schema_context"]["assets"][0]["columns"][0][
            "sql"
        ] = "identifier"
        invalid_payloads.append(column_with_sql)

        for invalid in invalid_payloads:
            with self.subTest(payload=invalid):
                with self.assertRaises(ContractError):
                    validate_payload("node2_request", invalid)

    def test_node2_metric_source_rejects_ungoverned_kinds(self):
        formula = copy.deepcopy(NODE2_REQUEST)
        formula["metric_rules"][0]["source"] = {
            "kind": "formula",
            "operator": "divide",
            "operands": ["numerator_measure", "denominator_measure"],
        }
        filter_with_value = copy.deepcopy(NODE2_REQUEST)
        filter_with_value["metric_rules"][0]["required_filters"][0][
            "value"
        ] = "embedded-runtime-value"
        missing_result = copy.deepcopy(NODE2_REQUEST)
        missing_result["metric_rules"][0].pop("result_field")
        unsupported_list_filter = copy.deepcopy(NODE2_REQUEST)
        unsupported_list_filter["metric_rules"][0]["required_filters"][0][
            "operator"
        ] = "in"
        for invalid in (
            formula,
            filter_with_value,
            missing_result,
            unsupported_list_filter,
        ):
            with self.subTest(payload=invalid):
                with self.assertRaises(ContractError):
                    validate_payload("node2_request", invalid)

    def test_node2_metric_source_accepts_governed_ratio_shape(self):
        namespace = "quartz"
        numerator_id = f"{namespace}_measure"
        with_ratio = copy.deepcopy(NODE2_REQUEST)
        with_ratio["metric_rules"].append(
            {
                "id": f"{namespace}_denominator",
                "source": {
                    "kind": "column",
                    "field": qualified_field(
                        f"{namespace}_catalog.semantic.fact_observations", "amount"
                    ),
                },
                "aggregation": "count",
                "result_field": "resolved_denominator",
                "unit": "arbitrary_unit",
                "time_field": qualified_field(
                    f"{namespace}_catalog.semantic.fact_observations", "observed_at"
                ),
                "dimensions": [],
                "required_filters": [],
            }
        )
        with_ratio["metric_rules"].append(
            {
                "id": f"{namespace}_ratio",
                "source": {
                    "kind": "ratio",
                    "numerator_metric_id": numerator_id,
                    "denominator_metric_id": f"{namespace}_denominator",
                    "zero_policy": "null_on_zero_denominator",
                },
                "aggregation": "ratio",
                "result_field": "resolved_ratio",
                "unit": "arbitrary_unit",
                "time_field": None,
                "dimensions": [],
                "required_filters": [],
            }
        )
        validate_payload("node2_request", with_ratio)

        missing_denominator = copy.deepcopy(with_ratio)
        missing_denominator["metric_rules"][-1]["source"].pop("denominator_metric_id")
        unsupported_zero_policy = copy.deepcopy(with_ratio)
        unsupported_zero_policy["metric_rules"][-1]["source"]["zero_policy"] = "zero_fill"
        bad_aggregation = copy.deepcopy(with_ratio)
        bad_aggregation["metric_rules"][-1]["aggregation"] = "divide"
        for invalid in (missing_denominator, unsupported_zero_policy, bad_aggregation):
            with self.subTest(payload=invalid):
                with self.assertRaises(ContractError):
                    validate_payload("node2_request", invalid)

    def test_node2_metric_source_accepts_governed_exists_aggregation(self):
        namespace = "quartz"
        with_exists = copy.deepcopy(NODE2_REQUEST)
        with_exists["metric_rules"].append(
            {
                "id": f"{namespace}_exists",
                "source": {
                    "kind": "column",
                    "field": qualified_field(
                        f"{namespace}_catalog.semantic.fact_observations", "flagged_at"
                    ),
                },
                "aggregation": "exists",
                "result_field": "resolved_exists",
                "unit": "boolean",
                "time_field": qualified_field(
                    f"{namespace}_catalog.semantic.fact_observations", "observed_at"
                ),
                "dimensions": [],
                "required_filters": [],
            }
        )
        validate_payload("node2_request", with_exists)

        bad_aggregation = copy.deepcopy(with_exists)
        bad_aggregation["metric_rules"][-1]["aggregation"] = "boolean"
        with self.assertRaises(ContractError):
            validate_payload("node2_request", bad_aggregation)

    def test_node2_join_graph_requires_declared_join_semantics(self):
        no_equality = copy.deepcopy(NODE2_REQUEST)
        no_equality["join_graph"]["edges"][0]["equality_conditions"] = []
        open_ended_temporal = copy.deepcopy(NODE2_REQUEST)
        open_ended_temporal["join_graph"]["edges"][0][
            "temporal_conditions"
        ][0]["end_exclusive"] = False
        no_preaggregation_keys = copy.deepcopy(NODE2_REQUEST)
        no_preaggregation_keys["join_graph"]["edges"][0][
            "preaggregation"
        ].pop("keys")
        for invalid in (no_equality, open_ended_temporal, no_preaggregation_keys):
            with self.subTest(payload=invalid):
                with self.assertRaises(ContractError):
                    validate_payload("node2_request", invalid)

    def test_node2_time_parameters_and_query_policy_exclude_runtime_values(self):
        for parameter in NODE2_REQUEST["parameter_contract"]["parameters"]:
            self.assertEqual(set(parameter), {"name", "type", "scope"})

        invalid_interval = copy.deepcopy(NODE2_REQUEST)
        invalid_interval["time_rules"]["interval"] = "[start,end]"
        missing_native_type = copy.deepcopy(NODE2_REQUEST)
        missing_native_type["time_rules"]["fields"][0].pop("native_type")
        parameter_value = copy.deepcopy(NODE2_REQUEST)
        parameter_value["parameter_contract"]["parameters"][0]["value"] = 1
        missing_parameter_type = copy.deepcopy(NODE2_REQUEST)
        missing_parameter_type["parameter_contract"]["parameters"][0].pop("type")
        wrong_dialect = copy.deepcopy(NODE2_REQUEST)
        wrong_dialect["query_policy"]["dialect"] = "postgres"
        writable = copy.deepcopy(NODE2_REQUEST)
        writable["query_policy"]["read_only"] = False
        no_limit = copy.deepcopy(NODE2_REQUEST)
        no_limit["query_policy"]["max_limit"] = 0
        no_catalog = copy.deepcopy(NODE2_REQUEST)
        no_catalog["query_policy"]["allowed_catalogs"] = []
        for invalid in (
            invalid_interval,
            missing_native_type,
            parameter_value,
            missing_parameter_type,
            wrong_dialect,
            writable,
            no_limit,
            no_catalog,
        ):
            with self.subTest(payload=invalid):
                with self.assertRaises(ContractError):
                    validate_payload("node2_request", invalid)

    def test_node2_response_accepts_sql_only_or_complete_legacy_lineage(self):
        expected_fields = {
            "sql",
            "used_assets",
            "used_columns",
            "used_joins",
            "used_metrics",
        }
        self.assertEqual(set(NODE2_RESPONSE), expected_fields)
        validate_payload("node2_response", NODE2_RESPONSE)
        validate_payload("node2_response", {"sql": NODE2_RESPONSE["sql"]})

        missing_sql = copy.deepcopy(NODE2_RESPONSE)
        missing_sql.pop("sql")
        with self.assertRaises(ContractError):
            validate_payload("node2_response", missing_sql)

        for field in expected_fields - {"sql"}:
            partial_lineage = copy.deepcopy(NODE2_RESPONSE)
            partial_lineage.pop(field)
            with self.subTest(partial_lineage=field):
                with self.assertRaises(ContractError):
                    validate_payload("node2_response", partial_lineage)
        for forbidden in ("references", "parameters", "model"):
            extra = copy.deepcopy(NODE2_RESPONSE)
            extra[forbidden] = []
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ContractError):
                    validate_payload("node2_response", extra)
        unqualified_column = copy.deepcopy(NODE2_RESPONSE)
        unqualified_column["used_columns"][0] = "amount"
        with self.assertRaises(ContractError):
            validate_payload("node2_response", unqualified_column)

    def test_node2_fixtures_contain_no_scenario_lineage_or_runtime_values(self):
        payload_text = json.dumps(
            {
                "request": NODE2_REQUEST,
                "response": NODE2_RESPONSE,
                "repair": VALID_PAYLOADS["node2_repair_request"],
            },
            ensure_ascii=False,
        ).casefold()
        for forbidden in (
            "pms.public",
            "crm.public",
            "pos.public",
            "room_revenue",
            "전월 대비",
        ):
            self.assertNotIn(forbidden, payload_text)
        self.assertNotRegex(payload_text, r"\b20\d{2}-\d{2}-\d{2}\b")
        self.assertFalse(NODE2_RESPONSE["sql"].lstrip().casefold().startswith("with "))

    def test_missing_and_extra_fields_are_rejected(self):
        for definition, payload in VALID_PAYLOADS.items():
            required_key = next(iter(payload))
            missing = copy.deepcopy(payload)
            missing.pop(required_key)
            extra = copy.deepcopy(payload)
            extra["unexpected"] = True
            with self.subTest(definition=definition, case="missing"):
                with self.assertRaises(ContractError):
                    validate_payload(definition, missing)
            with self.subTest(definition=definition, case="extra"):
                with self.assertRaises(ContractError):
                    validate_payload(definition, extra)

    def test_gate_and_repair_limits_are_schema_enforced(self):
        repair = copy.deepcopy(VALID_PAYLOADS["node2_repair_request"])
        repair["attempt"] = 2
        with self.assertRaises(ContractError):
            validate_payload("node2_repair_request", repair)

        contextual_repair = copy.deepcopy(VALID_PAYLOADS["node2_repair_request"])
        contextual_repair["violation_detail"] = "Context-derived repair constraint"
        validate_payload("node2_repair_request", contextual_repair)

        explanation = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        explanation["g3_result"] = "fail"
        with self.assertRaises(ContractError):
            validate_payload("node3_request", explanation)

    def test_node3_metric_selection_contract_is_strict_and_additive(self):
        legacy = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        selected = copy.deepcopy(legacy)
        selected["metric_selection"] = {
            "selected_metric_id": "room_revenue",
            "context_metric_ids": ["room_revenue"],
            "entitled_metric_ids": ["room_revenue"],
        }

        validate_payload("node3_request", legacy)
        validate_payload("node3_request", selected)

        for field in selected["metric_selection"]:
            missing = copy.deepcopy(selected)
            missing["metric_selection"].pop(field)
            with self.subTest(missing=field):
                with self.assertRaises(ContractError):
                    validate_payload("node3_request", missing)

    def test_nested_missing_and_extra_fields_are_rejected(self):
        missing = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        missing["schema_context"]["assets"][0]["grain"].pop("keys")
        with self.assertRaises(ContractError):
            validate_payload("node2_request", missing)

        extra = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        extra["shaped_result"]["unexpected"] = True
        with self.assertRaises(ContractError):
            validate_payload("node3_request", extra)

    def test_empty_and_offsetless_boundary_values_are_rejected(self):
        empty = copy.deepcopy(VALID_PAYLOADS["node1_request"])
        empty["question"] = ""
        with self.assertRaises(ContractError):
            validate_payload("node1_request", empty)

        offsetless = copy.deepcopy(VALID_PAYLOADS["node1_request"])
        offsetless["as_of"] = "2026-07-30T12:00:00"
        with self.assertRaises(ContractError):
            validate_payload("node1_request", offsetless)


if __name__ == "__main__":
    unittest.main()
