# Flight Record Schema — Field Guide

> A single flight record = one auditable event in your multi-agent system

---

## Canonical Flight Record (JSON)

```json
{
  "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "span_id": "1a2b3c4d5e6f7a8b",
  "parent_span_id": "9f8e7d6c5b4a3210",
  "timestamp": "2026-03-27T14:32:01.123Z",
  "duration_ms": 847,

  "agent": {
    "id": "agent-planner-v3",
    "name": "PlannerAgent",
    "version": "3.2.1",
    "config_hash": "sha256:a4f8c2..."
  },

  "operation": {
    "name": "invoke_agent",
    "type": "planning",
    "status": "ok"
  },

  "model": {
    "request_model": "gpt-4o",
    "response_model": "gpt-4o-2025-08-06",
    "temperature": 0.3,
    "max_tokens": 2048
  },

  "tokens": {
    "input": 1247,
    "output": 389,
    "cache_read": 512,
    "cost_usd": 0.0043
  },

  "reasoning": {
    "strategy": "chain_of_thought",
    "confidence": 0.87,
    "alternatives_considered": 3,
    "selected_action": "delegate_to_executor",
    "rationale": "User query requires real-time data; routing to API executor"
  },

  "tool_calls": [
    {
      "tool_name": "search_api",
      "tool_type": "function",
      "call_id": "call_abc123",
      "parameters": {"query": "quarterly revenue"},
      "response_status": 200,
      "latency_ms": 234,
      "retry_count": 0
    }
  ],

  "inter_agent": {
    "delegation_type": "handoff",
    "target_agent": "agent-executor-v2",
    "message_payload_hash": "sha256:b7d3e1...",
    "protocol": "A2A"
  },

  "state": {
    "context_window_hash": "sha256:c9f2a4...",
    "memory_reads": ["user_preferences", "session_history"],
    "memory_writes": ["task_plan_v3"],
    "state_diff_hash": "sha256:d1e5f7..."
  },

  "outcome": {
    "task_result": "success",
    "user_feedback": null,
    "error_code": null,
    "eval_scores": {
      "relevance": 0.91,
      "faithfulness": 0.88
    }
  },

  "compliance": {
    "pii_detected": false,
    "pii_redacted_fields": [],
    "guardrail_checks": ["toxicity_filter", "pii_scanner"],
    "guardrail_passed": true,
    "human_in_loop": false
  }
}
```

---

## Field-by-Field Guide

### Correlation Fields (The Thread)

| Field | Purpose | Why It Matters |
|-------|---------|---------------|
| `trace_id` | Global request ID (W3C Trace Context) | One trace = one user request, regardless of how many agents touch it |
| `span_id` | This specific operation | Uniquely identifies this flight record |
| `parent_span_id` | Who triggered this operation | Follow the chain: output → executor → planner → orchestrator → user |
| `timestamp` | ISO 8601, UTC, millisecond precision | Enables timeline reconstruction |
| `duration_ms` | Wall-clock time for this operation | Find your slow agents |

### Agent Identity (The WHO)

| Field | Purpose | Debug Value |
|-------|---------|-------------|
| `agent.id` | Stable identifier across restarts | Filter all records from one agent |
| `agent.name` | Human-readable | Dashboard labels |
| `agent.version` | Semver | "Was this the version with the regression?" |
| `agent.config_hash` | SHA-256 of full config | Reproducibility — pin exact behavior |

### Reasoning (The WHY) — *Most underlogged field*

| Field | Purpose |
|-------|---------|
| `reasoning.strategy` | CoT, ReAct, plan-and-execute, reflection |
| `reasoning.confidence` | Model's self-assessed confidence (0-1) |
| `reasoning.alternatives_considered` | How many paths were evaluated |
| `reasoning.selected_action` | What the agent decided to do |
| `reasoning.rationale` | Free-text explanation of *why* |

> 💡 **Pro tip:** This is what separates "logs" from "audit trails." Without reasoning, you have input/output pairs. With reasoning, you have accountability.

### Tool Invocations (The HOW)

Log **every** external call:
- `tool_name` + `tool_type` → What was called
- `parameters` → What was sent (redact PII!)
- `response_status` + `latency_ms` → Did it work? How fast?
- `retry_count` → Was it flaky?

### Inter-Agent Communication (The HANDOFF)

| Field | Purpose |
|-------|---------|
| `delegation_type` | `handoff`, `broadcast`, `request_response`, `pub_sub` |
| `target_agent` | Who received the work |
| `message_payload_hash` | Integrity verification (don't log raw payloads in prod) |
| `protocol` | `A2A`, `MCP`, `HTTP`, `gRPC`, custom |

### Compliance Fields (The AUDIT)

| Field | EU AI Act Relevance |
|-------|-------------------|
| `pii_detected` / `pii_redacted_fields` | GDPR + Art. 12 data protection |
| `guardrail_checks` | Art. 9 risk management evidence |
| `guardrail_passed` | Proof of safety controls |
| `human_in_loop` | Art. 14 human oversight evidence |

---

## Storage Strategy

```
Hot tier   (0-7 days)   → PostgreSQL / ClickHouse   → Full records, queryable
Warm tier  (7-90 days)  → Object storage (S3/GCS)   → Compressed JSON, searchable
Cold tier  (90+ days)   → Archive (Glacier/Archive)  → Compliance retention
```

**Estimated storage:** ~2-5 KB per flight record → 1M requests/day ≈ 2-5 GB/day uncompressed, ~500 MB compressed.

---

## Query Patterns

```sql
-- Find all records in a trace (full request reconstruction)
SELECT * FROM flight_records WHERE trace_id = 'a1b2c3d4...' ORDER BY timestamp;

-- Find expensive agents (cost attribution)
SELECT agent_name, SUM(cost_usd), AVG(duration_ms)
FROM flight_records
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY agent_name ORDER BY SUM(cost_usd) DESC;

-- Find failed guardrail checks (compliance audit)
SELECT * FROM flight_records
WHERE guardrail_passed = false
AND timestamp BETWEEN '2026-03-01' AND '2026-03-31';

-- Trace reasoning for a specific decision
SELECT agent_name, reasoning_rationale, reasoning_confidence
FROM flight_records
WHERE trace_id = 'a1b2c3d4...'
ORDER BY timestamp;
```
