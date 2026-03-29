"""
OTel Instrumentation for Multi-Agent AI Systems

Provides:
- init_flight_recorder(): One-line setup for OTel tracing + metrics
- flight_recorder_middleware(): Decorator for agent functions
- AgentSpanProcessor: Custom span processor that writes to event store
"""

import functools
import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.trace import StatusCode
from opentelemetry.context import attach, detach
from opentelemetry.trace.propagation import TraceContextTextMapPropagator


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_flight_recorder(
    service_name: str,
    otlp_endpoint: str = "http://localhost:4317",
    capture_content: bool = False,
    additional_exporters: Optional[List[SpanExporter]] = None,
    event_store=None,
) -> trace.Tracer:
    """
    One-line initialization for the AI Flight Recorder.

    Args:
        service_name: Name of your agent system (e.g., "pharma-agent-platform")
        otlp_endpoint: OTel Collector gRPC endpoint
        capture_content: If True, log prompt/response content (opt-in for privacy)
        additional_exporters: Extra span exporters (e.g., for event store)
        event_store: Optional EventStore instance for direct writes

    Returns:
        Configured OpenTelemetry Tracer

    Usage:
        tracer = init_flight_recorder(
            service_name="my-agent-system",
            otlp_endpoint="http://otel-collector:4317"
        )
    """
    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: service_name,
        "flight_recorder.version": "0.1.0",
        "flight_recorder.capture_content": str(capture_content),
    })

    # -- Traces --
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
    )
    if additional_exporters:
        for exporter in additional_exporters:
            provider.add_span_processor(BatchSpanProcessor(exporter))

    if event_store:
        provider.add_span_processor(EventStoreSpanProcessor(event_store))

    trace.set_tracer_provider(provider)

    # -- Metrics --
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True),
        export_interval_millis=30_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # Set environment flag for content capture
    import os
    if capture_content:
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"

    return trace.get_tracer("flight_recorder", "0.1.0")


# ---------------------------------------------------------------------------
# Agent Middleware Decorator
# ---------------------------------------------------------------------------

def flight_recorder_middleware(
    agent_id: str,
    agent_name: str,
    agent_version: str = "1.0.0",
    operation_type: str = "invoke_agent",
    risk_level: str = "standard",
):
    """
    Decorator that wraps any agent function with Flight Recorder instrumentation.

    Captures:
    - Agent identity (id, name, version, config hash)
    - Operation timing (start, duration)
    - Token usage and cost (if returned by the function)
    - Reasoning traces (if set via span attributes)
    - Error states with full context

    Usage:
        @flight_recorder_middleware(
            agent_id="planner-v3",
            agent_name="PlannerAgent",
            agent_version="3.2.1",
        )
        async def plan_task(user_query: str) -> dict:
            # ... agent logic ...
            return {"result": "...", "tokens": {"input": 100, "output": 50}}
    """
    def decorator(func: Callable) -> Callable:
        # Compute config hash from function source + agent params
        config_str = f"{agent_id}:{agent_version}:{func.__name__}"
        config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:16]

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = trace.get_tracer("flight_recorder")
            span_name = f"{operation_type} {agent_name}"

            with tracer.start_as_current_span(
                span_name,
                kind=trace.SpanKind.INTERNAL,
            ) as span:
                # -- Agent Identity --
                span.set_attribute("gen_ai.agent.id", agent_id)
                span.set_attribute("gen_ai.agent.name", agent_name)
                span.set_attribute("gen_ai.agent.version", agent_version)
                span.set_attribute("gen_ai.operation.name", operation_type)
                span.set_attribute("agent.config_hash", f"sha256:{config_hash}")
                span.set_attribute("agent.risk_level", risk_level)

                start_time = time.monotonic()
                try:
                    result = await func(*args, **kwargs)
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    span.set_attribute("duration_ms", duration_ms)

                    # Extract token usage if returned
                    if isinstance(result, dict):
                        _extract_usage(span, result)

                    span.set_status(StatusCode.OK)
                    return result

                except Exception as e:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    span.set_attribute("duration_ms", duration_ms)
                    span.set_status(StatusCode.ERROR, str(e))
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e)[:500])
                    span.record_exception(e)
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = trace.get_tracer("flight_recorder")
            span_name = f"{operation_type} {agent_name}"

            with tracer.start_as_current_span(
                span_name,
                kind=trace.SpanKind.INTERNAL,
            ) as span:
                span.set_attribute("gen_ai.agent.id", agent_id)
                span.set_attribute("gen_ai.agent.name", agent_name)
                span.set_attribute("gen_ai.agent.version", agent_version)
                span.set_attribute("gen_ai.operation.name", operation_type)
                span.set_attribute("agent.config_hash", f"sha256:{config_hash}")
                span.set_attribute("agent.risk_level", risk_level)

                start_time = time.monotonic()
                try:
                    result = func(*args, **kwargs)
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    span.set_attribute("duration_ms", duration_ms)

                    if isinstance(result, dict):
                        _extract_usage(span, result)

                    span.set_status(StatusCode.OK)
                    return result

                except Exception as e:
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    span.set_attribute("duration_ms", duration_ms)
                    span.set_status(StatusCode.ERROR, str(e))
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e)[:500])
                    span.record_exception(e)
                    raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# Helper: Extract token usage from agent response
# ---------------------------------------------------------------------------

def _extract_usage(span, result: dict):
    """Extract token/cost metadata from agent response dict."""
    tokens = result.get("tokens") or result.get("usage") or {}
    if tokens:
        if "input" in tokens or "input_tokens" in tokens:
            span.set_attribute("gen_ai.usage.input_tokens",
                             tokens.get("input") or tokens.get("input_tokens", 0))
        if "output" in tokens or "output_tokens" in tokens:
            span.set_attribute("gen_ai.usage.output_tokens",
                             tokens.get("output") or tokens.get("output_tokens", 0))
        if "cache_read" in tokens:
            span.set_attribute("gen_ai.usage.cache_read.input_tokens", tokens["cache_read"])

    cost = result.get("cost_usd") or result.get("cost")
    if cost is not None:
        span.set_attribute("gen_ai.cost_usd", float(cost))

    model = result.get("model") or result.get("response_model")
    if model:
        span.set_attribute("gen_ai.response.model", model)


# ---------------------------------------------------------------------------
# Helper: Log tool calls as span events
# ---------------------------------------------------------------------------

def log_tool_call(
    tool_name: str,
    tool_type: str = "function",
    parameters: Optional[Dict] = None,
    response_status: Optional[int] = None,
    latency_ms: Optional[int] = None,
    retry_count: int = 0,
):
    """
    Log a tool invocation as a span event on the current span.

    Usage:
        from flight_recorder.instrumentation import log_tool_call

        result = call_external_api(query)
        log_tool_call(
            tool_name="search_api",
            parameters={"query": query},
            response_status=200,
            latency_ms=234,
        )
    """
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return

    attributes = {
        "gen_ai.tool.name": tool_name,
        "gen_ai.tool.type": tool_type,
        "tool.retry_count": retry_count,
    }
    if parameters:
        attributes["tool.parameters"] = json.dumps(parameters)[:1000]
    if response_status is not None:
        attributes["tool.response_status"] = response_status
    if latency_ms is not None:
        attributes["tool.latency_ms"] = latency_ms

    span.add_event("tool_call", attributes=attributes)


# ---------------------------------------------------------------------------
# Helper: Log guardrail checks
# ---------------------------------------------------------------------------

def log_guardrail_check(
    guardrail_name: str,
    passed: bool,
    score: Optional[float] = None,
    threshold: Optional[float] = None,
    details: Optional[str] = None,
):
    """
    Log a guardrail check as a span event.

    Usage:
        log_guardrail_check("toxicity_filter", passed=True, score=0.02, threshold=0.5)
    """
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return

    attributes = {
        "guardrail.name": guardrail_name,
        "guardrail.passed": passed,
    }
    if score is not None:
        attributes["guardrail.score"] = score
    if threshold is not None:
        attributes["guardrail.threshold"] = threshold
    if details:
        attributes["guardrail.details"] = details[:500]

    span.add_event("guardrail_check", attributes=attributes)


# ---------------------------------------------------------------------------
# Helper: Log reasoning traces
# ---------------------------------------------------------------------------

def log_reasoning(
    strategy: str,
    confidence: float,
    rationale: str,
    alternatives_considered: int = 0,
    selected_action: Optional[str] = None,
):
    """
    Log agent reasoning as span attributes.

    Usage:
        log_reasoning(
            strategy="chain_of_thought",
            confidence=0.87,
            rationale="User query requires real-time data; routing to API executor",
            alternatives_considered=3,
            selected_action="delegate_to_executor",
        )
    """
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return

    span.set_attribute("reasoning.strategy", strategy)
    span.set_attribute("reasoning.confidence", confidence)
    span.set_attribute("reasoning.rationale", rationale[:1000])
    span.set_attribute("reasoning.alternatives_considered", alternatives_considered)
    if selected_action:
        span.set_attribute("reasoning.selected_action", selected_action)


# ---------------------------------------------------------------------------
# Custom SpanProcessor: Write to EventStore
# ---------------------------------------------------------------------------

class EventStoreSpanProcessor:
    """
    OTel SpanProcessor that writes completed spans to the Flight Recorder EventStore.

    This runs in the background and does NOT block your agent's execution.
    """

    def __init__(self, event_store):
        self.event_store = event_store

    def on_start(self, span, parent_context=None):
        pass

    def on_end(self, span: ReadableSpan):
        """Convert OTel span to FlightRecord and persist."""
        try:
            from .event_store import FlightRecord
            record = FlightRecord.from_otel_span(span)
            self.event_store.insert_async(record)
        except Exception:
            pass  # Never crash the application for observability

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=None):
        pass


# ---------------------------------------------------------------------------
# Trace Context Propagation Helpers
# ---------------------------------------------------------------------------

_propagator = TraceContextTextMapPropagator()


def inject_trace_context(headers: Optional[Dict] = None) -> Dict[str, str]:
    """
    Inject W3C Trace Context into HTTP headers for cross-agent propagation.

    Usage:
        headers = inject_trace_context()
        response = httpx.post(agent_b_url, headers=headers, json=payload)
    """
    if headers is None:
        headers = {}
    _propagator.inject(headers)
    return headers


def extract_trace_context(headers: Dict[str, str]):
    """
    Extract W3C Trace Context from incoming headers.

    Usage:
        ctx = extract_trace_context(request.headers)
        token = attach(ctx)
        try:
            # ... process within the extracted context
        finally:
            detach(token)
    """
    return _propagator.extract(headers)
