from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from time import perf_counter
from typing import Any, Iterator

from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Span, Tracer


_LOGGER = logging.getLogger("answervice.telemetry")
_tracer: Tracer = trace.get_tracer("answervice.backend")
_meter: Meter = metrics.get_meter("answervice.backend")
_stage_count = _meter.create_counter("answervice.stage.count")
_stage_duration = _meter.create_histogram("answervice.stage.duration", unit="s")


def configure_telemetry(*, span_exporter=None, metric_reader=None) -> None:
    """SDK exporter가 명시된 경우에만 계측을 활성화한다."""
    global _tracer, _meter, _stage_count, _stage_duration

    if span_exporter is None and metric_reader is None:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not endpoint:
            return
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        span_exporter = OTLPSpanExporter()
        metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())

    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    resource = Resource.create(
        {"service.name": os.getenv("OTEL_SERVICE_NAME", "answervice-backend")}
    )
    trace_provider = TracerProvider(resource=resource)
    if span_exporter is not None:
        trace_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader] if metric_reader is not None else [],
    )
    _tracer = trace_provider.get_tracer("answervice.backend")
    _meter = meter_provider.get_meter("answervice.backend")
    _stage_count = _meter.create_counter("answervice.stage.count")
    _stage_duration = _meter.create_histogram("answervice.stage.duration", unit="s")


def _correlation_attributes(
    context: Any | None,
    request_id: str | None,
    trace_id: str | None,
) -> dict[str, str]:
    if context is not None:
        request_id = str(getattr(context, "request_id", request_id or ""))
        trace_id = str(getattr(context, "trace_id", trace_id or ""))
    role = getattr(getattr(context, "role", None), "value", None)
    return {
        key: value
        for key, value in {
            "answervice.request_id": request_id,
            "answervice.trace_id": trace_id,
            "answervice.role": role,
            "answervice.access_profile": getattr(context, "access_profile", None),
            "answervice.policy_version": getattr(
                context, "access_policy_version", None
            ),
        }.items()
        if value
    }


@contextmanager
def observe_stage(
    stage: str,
    *,
    context: Any | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    attributes: dict[str, str | bool | int | float] | None = None,
) -> Iterator[Span]:
    safe_attributes = _correlation_attributes(context, request_id, trace_id)
    safe_attributes.update(attributes or {})
    metric_attributes = {"answervice.stage": stage}
    started = perf_counter()
    status = "ok"
    with _tracer.start_as_current_span(
        f"answervice.{stage}", attributes=safe_attributes
    ) as span:
        try:
            yield span
        except Exception:
            status = "error"
            raise
        finally:
            metric_attributes["answervice.status"] = status
            _stage_count.add(1, metric_attributes)
            _stage_duration.record(perf_counter() - started, metric_attributes)
            span_context = span.get_span_context()
            _LOGGER.info(
                "observability stage completed",
                extra={
                    **safe_attributes,
                    "answervice.stage": stage,
                    "answervice.status": status,
                    "otel.trace_id": format(span_context.trace_id, "032x"),
                    "otel.span_id": format(span_context.span_id, "016x"),
                },
            )


configure_telemetry()
