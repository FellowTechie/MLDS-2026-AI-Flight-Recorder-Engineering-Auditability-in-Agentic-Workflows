# 4-Week Implementation Playbook — AI Flight Recorder

> From zero observability to production-grade agentic auditability in 4 weeks.
> Assumes: Python stack, 1-2 engineers, existing multi-agent system.

---

## Week 1: Foundation — OTel Instrumentation

### Goals
- [ ] OTel SDK installed and exporting spans
- [ ] Every LLM call produces a trace
- [ ] Basic Jaeger/Langfuse UI operational

### Day 1-2: Infrastructure
```bash
# Install core dependencies
pip install opentelemetry-api opentelemetry-sdk \
    opentelemetry-exporter-otlp-proto-grpc \
    opentelemetry-instrumentation-openai

# Docker: Jaeger + OTel Collector
docker compose up -d  # See docker-compose.yaml in this repo
```

### Day 3-4: Instrument LLM Calls
```python
# Add to your application entry point
from flight_recorder.instrumentation import init_flight_recorder

init_flight_recorder(
    service_name="my-agent-system",
    otlp_endpoint="http://localhost:4317",
    capture_content=False  # Start with metadata only
)
```

### Day 5: Verify
- Open Jaeger UI (localhost:16686) — confirm traces appear
- Verify: `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.operation.name`
- Confirm parent-child span relationships across agent calls

### Deliverable
Screenshot of a multi-agent trace in Jaeger with proper span hierarchy.

---

## Week 2: Depth — Event Store + Reasoning Traces

### Goals
- [ ] PostgreSQL event store operational (append-only)
- [ ] Reasoning fields populated on every agent decision
- [ ] Cost attribution per agent per trace

### Day 1-2: Event Store
```sql
-- Deploy the schema (see src/flight_recorder/event_store.py)
CREATE TABLE flight_records (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        CHAR(32) NOT NULL,
    span_id         CHAR(16) NOT NULL,
    parent_span_id  CHAR(16),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_id        VARCHAR(128) NOT NULL,
    agent_name      VARCHAR(256),
    operation_name  VARCHAR(64),
    duration_ms     INTEGER,
    model_name      VARCHAR(128),
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        DECIMAL(10, 6),
    reasoning       JSONB,
    tool_calls      JSONB,
    outcome         JSONB,
    compliance      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX idx_flight_records_trace ON flight_records(trace_id);
CREATE INDEX idx_flight_records_agent ON flight_records(agent_id, timestamp);
CREATE INDEX idx_flight_records_time  ON flight_records(timestamp);
```

### Day 3-4: Reasoning Enrichment
Add reasoning capture to every agent decision point:
```python
with tracer.start_as_current_span("invoke_agent PlannerAgent") as span:
    span.set_attribute("gen_ai.agent.name", "PlannerAgent")
    # ... agent logic ...
    span.set_attribute("reasoning.strategy", "chain_of_thought")
    span.set_attribute("reasoning.confidence", confidence_score)
    span.set_attribute("reasoning.rationale", rationale_text)
    span.set_attribute("reasoning.alternatives_considered", len(alternatives))
```

### Day 5: Cost Dashboard
Query to build your first cost dashboard:
```sql
SELECT
    agent_name,
    DATE_TRUNC('hour', timestamp) AS hour,
    COUNT(*) AS invocations,
    SUM(cost_usd) AS total_cost,
    AVG(duration_ms) AS avg_latency_ms,
    SUM(input_tokens + output_tokens) AS total_tokens
FROM flight_records
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY agent_name, hour
ORDER BY total_cost DESC;
```

### Deliverable
Event store with 24h of production data; cost attribution dashboard.

---

## Week 3: Safety — PII Redaction + Guardrails

### Goals
- [ ] PII detection & redaction running on all trace payloads
- [ ] Guardrail check results logged with every agent call
- [ ] Human-in-the-loop approval gates on sensitive operations

### Day 1-2: PII Pipeline
```python
from flight_recorder.pii_redactor import PIIRedactor

redactor = PIIRedactor(
    patterns=["email", "phone", "ssn", "credit_card", "ip_address"],
    strategy="hash"  # or "mask", "remove"
)

# In your OTel SpanProcessor
clean_payload = redactor.redact(raw_payload)
```

### Day 3-4: Guardrail Logging
```python
# Log every guardrail check as a span event
span.add_event("guardrail_check", attributes={
    "guardrail.name": "toxicity_filter",
    "guardrail.passed": True,
    "guardrail.score": 0.02,
    "guardrail.threshold": 0.5
})

span.add_event("guardrail_check", attributes={
    "guardrail.name": "pii_scanner",
    "guardrail.passed": True,
    "guardrail.fields_detected": 0
})
```

### Day 5: Approval Gates
```python
# For high-risk operations (e.g., sending emails, modifying records)
if operation.risk_level == "high":
    approval = await request_human_approval(
        agent=agent_name,
        action=operation.description,
        trace_id=current_trace_id
    )
    span.set_attribute("compliance.human_in_loop", True)
    span.set_attribute("compliance.approval_status", approval.status)
```

### Deliverable
PII-redacted traces; guardrail audit trail; approval gate on one high-risk action.

---

## Week 4: Production — Replay Engine + Compliance Report

### Goals
- [ ] Trace replay operational (time-travel debugging)
- [ ] Tail-based sampling configured (keep errors, sample successes)
- [ ] Compliance report generator producing Art. 12 evidence
- [ ] Alerting on anomalies (cost spikes, guardrail failures, latency)

### Day 1-2: Replay Engine
```python
from flight_recorder.replay_engine import ReplayEngine

engine = ReplayEngine(event_store=store)

# Reconstruct full execution from any trace
timeline = engine.replay(trace_id="a1b2c3d4...")
for record in timeline:
    print(f"[{record.timestamp}] {record.agent_name}: {record.operation_name}")
    print(f"  Reasoning: {record.reasoning.rationale}")
    print(f"  Duration: {record.duration_ms}ms, Cost: ${record.cost_usd}")
```

### Day 3: Tail-Based Sampling
```yaml
# OTel Collector config — keep errors, sample successes
processors:
  tail_sampling:
    decision_wait: 10s
    policies:
      - name: errors-always
        type: status_code
        status_code: { status_codes: [ERROR] }
      - name: high-latency
        type: latency
        latency: { threshold_ms: 5000 }
      - name: guardrail-failures
        type: string_attribute
        string_attribute:
          key: guardrail.passed
          values: ["false"]
      - name: sample-successes
        type: probabilistic
        probabilistic: { sampling_percentage: 10 }
```

### Day 4: Compliance Report
```python
from flight_recorder.event_store import EventStore

store = EventStore()

# Generate Art. 12 compliance evidence
report = store.compliance_report(
    start_date="2026-03-01",
    end_date="2026-03-31",
    include_sections=[
        "usage_periods",          # Art. 12: period of each use
        "reference_databases",     # Art. 12: databases checked
        "human_oversight_events",  # Art. 14: oversight actions
        "guardrail_summary",       # Art. 9: risk management
        "pii_redaction_summary"    # GDPR: data protection
    ]
)
report.export_pdf("compliance_report_march_2026.pdf")
```

### Day 5: Alerting
Set up alerts for:
- Cost per trace > $X threshold
- Guardrail failure rate > Y%
- Agent latency P99 > Z ms
- Error rate spike (>2σ from baseline)

### Deliverable
Full stack operational: instrumentation → event store → PII redaction → replay → compliance reports → alerting.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│                YOUR AGENT SYSTEM                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │Orchestr. │→ │ Planner  │→ │ Executor │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │ OTel         │ OTel        │ OTel        │
└───────┼──────────────┼─────────────┼─────────────┘
        ▼              ▼             ▼
┌──────────────────────────────────────────────────┐
│          OTEL COLLECTOR (gRPC :4317)             │
│  ┌───────────┐  ┌───────────┐  ┌──────────────┐ │
│  │PII Redact │  │Tail Sample│  │ Batch Export │ │
│  └───────────┘  └───────────┘  └──────────────┘ │
└──────────┬──────────────┬──────────────┬─────────┘
           ▼              ▼              ▼
    ┌────────────┐  ┌──────────┐  ┌────────────┐
    │ PostgreSQL │  │  Jaeger  │  │  Langfuse  │
    │ Event Store│  │  (Traces)│  │  (Evals)   │
    └────────────┘  └──────────┘  └────────────┘
```

---

## Overhead Benchmarks

| Operation | Added Latency | Notes |
|-----------|--------------|-------|
| Span creation | <0.1ms | In-process, negligible |
| Span export (async batch) | <5ms P99 | Background thread, non-blocking |
| PII regex scan (per payload) | ~1-3ms | Depends on payload size |
| Event store write (async) | ~2-5ms | Batched PostgreSQL inserts |
| **Total overhead** | **<10ms P99** | Compared to 500ms-5s LLM calls |

> The LLM call itself dominates latency. Observability overhead is <2% of total request time.
