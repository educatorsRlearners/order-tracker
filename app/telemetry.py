import logging
import os

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

EXPORT_INTERVAL_MS = 10_000


def setup_telemetry(app):
    """Export traces, metrics and logs to stdout so `docker compose logs app` shows them."""
    if os.getenv("ORDER_TRACKER_TELEMETRY", "on") == "off":
        return
    resource = Resource.create({"service.name": "order-tracker"})
    # Also ship to the OpenTelemetry Collector when an OTLP endpoint is configured.
    otlp = bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(ConsoleSpanExporter(), schedule_delay_millis=1000)
    )
    if otlp:
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    exporters = [ConsoleMetricExporter()] + ([OTLPMetricExporter()] if otlp else [])
    metrics.set_meter_provider(
        MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(e, export_interval_millis=EXPORT_INTERVAL_MS)
                for e in exporters
            ],
        )
    )

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(ConsoleLogRecordExporter(), schedule_delay_millis=1000)
    )
    if otlp:
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    logging.getLogger().addHandler(LoggingHandler(logger_provider=logger_provider))
    logging.getLogger().setLevel(logging.INFO)

    request_counter = metrics.get_meter("order-tracker").create_counter(
        "order_tracker.http.requests",
        unit="{request}",
        description="HTTP requests handled, by route and response status code",
    )

    app.state.request_counter = request_counter

    @app.middleware("http")
    async def count_requests(request, call_next):
        status_code = 500  # recorded if the handler raises
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            request_counter.add(
                1,
                {
                    "http.route": route.path if route else "unmatched",
                    "http.request.method": request.method,
                    "http.response.status_code": status_code,
                },
            )

    # Instrument last so the tracing middleware is outermost: the server span is then
    # active when the counter is recorded, which attaches the trace as an exemplar.
    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)


def seed_error_series(app):
    """Create a zero-valued 500 series per route.

    Prometheus's increase() ignores a series' first sample, so without this the first
    5xx on a route would never trigger the 5xx alert.
    """
    counter = getattr(app.state, "request_counter", None)
    if counter is None:
        return
    for route in app.routes:
        for method in getattr(route, "methods", None) or ():
            if method != "HEAD":
                counter.add(
                    0,
                    {
                        "http.route": route.path,
                        "http.request.method": method,
                        "http.response.status_code": 500,
                    },
                )
