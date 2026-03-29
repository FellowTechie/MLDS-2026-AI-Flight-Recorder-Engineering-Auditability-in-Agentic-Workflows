# ✈️ AI Flight Recorder — Engineering Auditability in Agentic Workflows

> **MLDS 2026 Talk Companion Repository**
> Speaker: FellowTechie · Associate Director, GenAI Products · Novartis

Production-ready reference implementation and quick-reference cheat sheets for building auditable multi-agent AI systems using OpenTelemetry, event sourcing, and compliance-grade logging.

---

## 📂 Repository Structure

```
├── cheatsheets/
│   ├── 01-otel-genai-semconv.md        # OTel GenAI Semantic Conventions quick ref
│   ├── 02-flight-record-schema.md      # Flight Record JSON schema + field guide
│   ├── 03-tool-comparison-matrix.md    # 6-tool observability comparison
│   ├── 04-eu-ai-act-compliance.md      # EU AI Act Art. 12/14/19 cheat sheet
│   └── 05-implementation-playbook.md   # 4-week implementation plan
│
├── src/flight_recorder/
│   ├── __init__.py
│   ├── instrumentation.py              # OTel instrumentation middleware
│   ├── event_store.py                  # PostgreSQL event store (append-only)
│   ├── replay_engine.py                # Time-travel debugging / trace replay
│   ├── pii_redactor.py                 # PII detection & redaction pipeline
│   ├── collector_config.yaml           # OTel Collector config (gRPC + OTLP)
│   └── sampling_config.yaml            # Tail-based sampling rules
│
├── examples/
│   ├── langchain_instrumented.py       # LangChain multi-agent + Flight Recorder
│   ├── openai_agents_instrumented.py   # OpenAI Agents SDK + Flight Recorder
│   └── fastapi_middleware_demo.py      # FastAPI app with OTel middleware
│
├── tests/
│   └── test_event_store.py             # Event store unit tests
│
├── requirements.txt
├── docker-compose.yaml                 # Jaeger + OTel Collector + PostgreSQL
└── LICENSE
```

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/<your-org>/ai-flight-recorder.git
cd ai-flight-recorder

# Install
pip install -r requirements.txt

# Run supporting infrastructure
docker compose up -d   # Jaeger UI at localhost:16686, PostgreSQL at 5432

# Try the FastAPI demo
python examples/fastapi_middleware_demo.py
```

## 🔑 Key Takeaways from the Talk

1. **Multi-agent systems need aviation-grade auditability** — structured, tamper-evident, machine-readable logs of every decision, communication, tool call, and state change.

2. **OpenTelemetry is the standard** — GenAI semantic conventions (agent spans, tool spans, evaluation events) are converging rapidly. Adopt `gen_ai.*` attributes now.

3. **Three capabilities: Record → Replay → Regulate** — immutable traces, time-travel debugging, and compliance-grade audit trails (EU AI Act, SOC 2, ISO 42001).

4. **EU AI Act Article 12 deadline: August 2, 2026** — automatic logging for high-risk AI systems is not optional. Start instrumenting today.

5. **Overhead is manageable** — async OTel export adds <5ms P99 latency per span. The cost of *not* logging is orders of magnitude higher.

## 📜 License

Apache 2.0 — Use freely, contribute back.

---

*Built with care for the MLDS 2026 community. PRs welcome.*
