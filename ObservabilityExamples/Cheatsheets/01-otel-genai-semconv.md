# OpenTelemetry GenAI Semantic Conventions — Quick Reference

> Status: **Development** (experimental, stabilizing fast)
> Opt-in: `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`

---

## Span Types for Agentic Systems

| Operation | `gen_ai.operation.name` | Span Kind | When to Use |
|-----------|------------------------|-----------|-------------|
| LLM Call | `chat`, `text_completion` | `CLIENT` | Every model invocation |
| Agent Invoke | `invoke_agent` | `CLIENT` (remote) / `INTERNAL` (in-process) | Agent entry point |
| Agent Create | `create_agent` | `CLIENT` | Remote agent provisioning |
| Tool Execution | `execute_tool` | `INTERNAL` | Tool/function calls |
| Embeddings | `embeddings` | `CLIENT` | Embedding generation |

---

## Core Attributes (copy-paste ready)

### Agent Attributes
```
gen_ai.agent.id            → Unique agent identifier
gen_ai.agent.name          → Human-readable agent name (e.g., "PlannerAgent")
gen_ai.agent.description   → Agent purpose description
gen_ai.agent.version       → Agent version string
```

### Request/Response Attributes
```
gen_ai.request.model           → Model name (e.g., "gpt-4o", "claude-sonnet-4-20250514")
gen_ai.request.max_tokens      → Max tokens requested
gen_ai.request.temperature     → Sampling temperature
gen_ai.request.top_p           → Top-p sampling
gen_ai.response.model          → Actual model used (may differ from request)
gen_ai.response.id             → Provider response ID
gen_ai.response.finish_reasons → ["stop", "tool_calls", "length"]
```

### Token Usage Attributes
```
gen_ai.usage.input_tokens              → Input tokens consumed
gen_ai.usage.output_tokens             → Output tokens generated
gen_ai.usage.cache_read.input_tokens   → Tokens served from provider cache
gen_ai.usage.cache_creation.input_tokens → Tokens written to provider cache
```

### Tool Attributes
```
gen_ai.tool.name        → Tool/function name (e.g., "get_weather")
gen_ai.tool.call.id     → Unique tool call identifier
gen_ai.tool.type        → "function", "mcp", "code_interpreter"
```

### Provider Identification
```
gen_ai.provider.name    → "openai", "anthropic", "aws.bedrock", "azure.ai.inference"
gen_ai.system           → (deprecated, use gen_ai.provider.name)
```

---

## Span Naming Conventions

```
# LLM calls
chat {gen_ai.request.model}              → "chat gpt-4o"
text_completion {gen_ai.request.model}    → "text_completion claude-sonnet-4-20250514"

# Agent operations
invoke_agent {gen_ai.agent.name}          → "invoke_agent PlannerAgent"
create_agent {gen_ai.agent.name}          → "create_agent ResearchAssistant"

# Tool calls
execute_tool {gen_ai.tool.name}           → "execute_tool get_weather"

# Embeddings
embeddings {gen_ai.request.model}         → "embeddings text-embedding-3-large"
```

---

## Events (Logs API)

| Event | Purpose | Key Fields |
|-------|---------|------------|
| `gen_ai.system.message` | System prompt | `content` |
| `gen_ai.user.message` | User input | `content` |
| `gen_ai.assistant.message` | Model output | `content`, `tool_calls` |
| `gen_ai.tool.message` | Tool result | `content`, `id` |
| `gen_ai.evaluation` | Quality scores | `score.value`, `score.label` |

**Content capture is opt-in:**
```bash
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
```

---

## Metrics

| Metric | Unit | Description |
|--------|------|-------------|
| `gen_ai.client.operation.duration` | `s` | End-to-end operation latency |
| `gen_ai.client.token.usage` | `{token}` | Token consumption histogram |
| `gen_ai.server.request.duration` | `s` | Server-side processing time |
| `gen_ai.server.time_per_output_token` | `s` | Time-to-first-token proxy |

**Recommended histogram buckets for token usage:**
```
[1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]
```

---

## W3C Trace Context Propagation

Every span carries:
```
trace_id      → 32-hex-char global trace identifier
span_id       → 16-hex-char span identifier
parent_span_id → Links child to parent (causality chain)
trace_flags   → Sampling decisions
```

**Cross-agent propagation:** Inject `traceparent` header in inter-agent HTTP/gRPC calls:
```
traceparent: 00-{trace_id}-{span_id}-{trace_flags}
```

---

## Python Quick Start

```bash
pip install opentelemetry-api opentelemetry-sdk \
    opentelemetry-instrumentation-openai \
    opentelemetry-exporter-otlp-proto-grpc
```

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
```

---

## References

- [OTel GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [Agent Span Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)
- [OTel Python GenAI Instrumentation](https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation-genai)
- [Agentic Systems SemConv Proposal (Issue #2664)](https://github.com/open-telemetry/semantic-conventions/issues/2664)
