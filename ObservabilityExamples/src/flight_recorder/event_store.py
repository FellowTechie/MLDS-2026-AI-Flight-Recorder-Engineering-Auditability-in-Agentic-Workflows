"""
PostgreSQL Event Store — Append-Only Flight Record Storage

Features:
- Immutable, append-only writes (no UPDATE, no DELETE)
- Structured JSON fields for reasoning, tool calls, compliance
- Query helpers for trace reconstruction, cost attribution, compliance reports
- Async insert for non-blocking writes from SpanProcessor
"""

import json
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

import psycopg2
from psycopg2.extras import Json, execute_values


# ---------------------------------------------------------------------------
# Flight Record Data Class
# ---------------------------------------------------------------------------

@dataclass
class FlightRecord:
    """A single auditable event in a multi-agent system."""

    trace_id: str
    span_id: str
    agent_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parent_span_id: Optional[str] = None
    agent_name: Optional[str] = None
    agent_version: Optional[str] = None
    config_hash: Optional[str] = None
    operation_name: Optional[str] = None
    duration_ms: Optional[int] = None

    # Model
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    # Tokens & Cost
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cost_usd: Optional[Decimal] = None

    # Structured fields (stored as JSONB)
    reasoning: Optional[Dict[str, Any]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    inter_agent: Optional[Dict[str, Any]] = None
    state: Optional[Dict[str, Any]] = None
    outcome: Optional[Dict[str, Any]] = None
    compliance: Optional[Dict[str, Any]] = None

    # Status
    status: str = "ok"  # ok, error
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    @classmethod
    def from_otel_span(cls, span) -> "FlightRecord":
        """
        Convert an OpenTelemetry ReadableSpan to a FlightRecord.
        This is called by EventStoreSpanProcessor.on_end().
        """
        attrs = dict(span.attributes or {})
        ctx = span.get_span_context()

        # Extract reasoning attributes
        reasoning = None
        reasoning_keys = [k for k in attrs if k.startswith("reasoning.")]
        if reasoning_keys:
            reasoning = {k.replace("reasoning.", ""): attrs[k] for k in reasoning_keys}

        # Extract tool call events
        tool_calls = []
        guardrail_checks = []
        for event in (span.events or []):
            if event.name == "tool_call":
                tc = dict(event.attributes or {})
                if "tool.parameters" in tc:
                    try:
                        tc["tool.parameters"] = json.loads(tc["tool.parameters"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                tool_calls.append(tc)
            elif event.name == "guardrail_check":
                guardrail_checks.append(dict(event.attributes or {}))

        compliance = None
        if guardrail_checks:
            compliance = {
                "guardrail_checks": guardrail_checks,
                "all_passed": all(gc.get("guardrail.passed", True) for gc in guardrail_checks),
                "human_in_loop": attrs.get("compliance.human_in_loop", False),
            }

        return cls(
            trace_id=format(ctx.trace_id, "032x"),
            span_id=format(ctx.span_id, "016x"),
            parent_span_id=(
                format(span.parent.span_id, "016x") if span.parent else None
            ),
            agent_id=attrs.get("gen_ai.agent.id", "unknown"),
            agent_name=attrs.get("gen_ai.agent.name"),
            agent_version=attrs.get("gen_ai.agent.version"),
            config_hash=attrs.get("agent.config_hash"),
            operation_name=attrs.get("gen_ai.operation.name"),
            duration_ms=attrs.get("duration_ms"),
            model_name=attrs.get("gen_ai.response.model") or attrs.get("gen_ai.request.model"),
            input_tokens=attrs.get("gen_ai.usage.input_tokens"),
            output_tokens=attrs.get("gen_ai.usage.output_tokens"),
            cache_read_tokens=attrs.get("gen_ai.usage.cache_read.input_tokens"),
            cost_usd=Decimal(str(attrs["gen_ai.cost_usd"])) if "gen_ai.cost_usd" in attrs else None,
            reasoning=reasoning,
            tool_calls=tool_calls if tool_calls else None,
            compliance=compliance,
            status="error" if span.status.status_code == 2 else "ok",
            error_type=attrs.get("error.type"),
            error_message=attrs.get("error.message"),
        )


# ---------------------------------------------------------------------------
# Event Store
# ---------------------------------------------------------------------------

# SQL: Table creation
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS flight_records (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        CHAR(32) NOT NULL,
    span_id         CHAR(16) NOT NULL,
    parent_span_id  CHAR(16),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_id        VARCHAR(128) NOT NULL,
    agent_name      VARCHAR(256),
    agent_version   VARCHAR(64),
    config_hash     VARCHAR(80),
    operation_name  VARCHAR(64),
    duration_ms     INTEGER,
    model_name      VARCHAR(128),
    temperature     REAL,
    max_tokens      INTEGER,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cache_read_tokens INTEGER,
    cost_usd        DECIMAL(10, 6),
    reasoning       JSONB,
    tool_calls      JSONB,
    inter_agent     JSONB,
    state           JSONB,
    outcome         JSONB,
    compliance      JSONB,
    status          VARCHAR(16) DEFAULT 'ok',
    error_type      VARCHAR(128),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_fr_trace     ON flight_records(trace_id);
CREATE INDEX IF NOT EXISTS idx_fr_agent     ON flight_records(agent_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_fr_time      ON flight_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_fr_status    ON flight_records(status) WHERE status = 'error';
CREATE INDEX IF NOT EXISTS idx_fr_compliance ON flight_records USING GIN (compliance);

-- Prevent mutations: revoke UPDATE/DELETE from application role
-- REVOKE UPDATE, DELETE ON flight_records FROM app_user;
"""

INSERT_SQL = """
INSERT INTO flight_records (
    trace_id, span_id, parent_span_id, timestamp,
    agent_id, agent_name, agent_version, config_hash,
    operation_name, duration_ms,
    model_name, temperature, max_tokens,
    input_tokens, output_tokens, cache_read_tokens, cost_usd,
    reasoning, tool_calls, inter_agent, state, outcome, compliance,
    status, error_type, error_message
) VALUES (
    %(trace_id)s, %(span_id)s, %(parent_span_id)s, %(timestamp)s,
    %(agent_id)s, %(agent_name)s, %(agent_version)s, %(config_hash)s,
    %(operation_name)s, %(duration_ms)s,
    %(model_name)s, %(temperature)s, %(max_tokens)s,
    %(input_tokens)s, %(output_tokens)s, %(cache_read_tokens)s, %(cost_usd)s,
    %(reasoning)s, %(tool_calls)s, %(inter_agent)s, %(state)s, %(outcome)s, %(compliance)s,
    %(status)s, %(error_type)s, %(error_message)s
)
"""


class EventStore:
    """
    Append-only event store for Flight Records.

    Usage:
        store = EventStore(dsn="postgresql://user:pass@localhost:5432/flight_recorder")
        store.initialize()  # Creates table + indexes

        store.insert(record)  # Sync insert
        store.insert_async(record)  # Non-blocking insert (for SpanProcessor)

        timeline = store.get_trace("a1b2c3d4...")  # Reconstruct a trace
    """

    def __init__(self, dsn: str = "postgresql://localhost:5432/flight_recorder"):
        self.dsn = dsn
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fr-store")

    def _get_conn(self):
        return psycopg2.connect(self.dsn)

    def initialize(self):
        """Create table and indexes. Idempotent."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLE_SQL)
            conn.commit()

    def insert(self, record: FlightRecord):
        """Synchronous insert of a single flight record."""
        params = self._record_to_params(record)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(INSERT_SQL, params)
            conn.commit()

    def insert_async(self, record: FlightRecord):
        """Non-blocking insert — fires and forgets via thread pool."""
        self._pool.submit(self._safe_insert, record)

    def _safe_insert(self, record: FlightRecord):
        try:
            self.insert(record)
        except Exception:
            pass  # Log to stderr in production; never crash the app

    def insert_batch(self, records: List[FlightRecord]):
        """Batch insert for bulk loading."""
        if not records:
            return
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                for record in records:
                    cur.execute(INSERT_SQL, self._record_to_params(record))
            conn.commit()

    # -- Query Methods --

    def get_trace(self, trace_id: str) -> List[FlightRecord]:
        """Reconstruct a full trace timeline, ordered by timestamp."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM flight_records WHERE trace_id = %s ORDER BY timestamp",
                    (trace_id,)
                )
                columns = [desc[0] for desc in cur.description]
                return [self._row_to_record(dict(zip(columns, row))) for row in cur.fetchall()]

    def get_agent_records(
        self, agent_id: str, start: datetime, end: datetime, limit: int = 1000
    ) -> List[FlightRecord]:
        """Get all records for a specific agent in a time range."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM flight_records
                       WHERE agent_id = %s AND timestamp BETWEEN %s AND %s
                       ORDER BY timestamp LIMIT %s""",
                    (agent_id, start, end, limit)
                )
                columns = [desc[0] for desc in cur.description]
                return [self._row_to_record(dict(zip(columns, row))) for row in cur.fetchall()]

    def get_errors(self, start: datetime, end: datetime, limit: int = 500) -> List[FlightRecord]:
        """Get all error records in a time range."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM flight_records
                       WHERE status = 'error' AND timestamp BETWEEN %s AND %s
                       ORDER BY timestamp DESC LIMIT %s""",
                    (start, end, limit)
                )
                columns = [desc[0] for desc in cur.description]
                return [self._row_to_record(dict(zip(columns, row))) for row in cur.fetchall()]

    def get_guardrail_failures(self, start: datetime, end: datetime) -> List[FlightRecord]:
        """Get records where any guardrail check failed."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM flight_records
                       WHERE compliance->>'all_passed' = 'false'
                       AND timestamp BETWEEN %s AND %s
                       ORDER BY timestamp DESC""",
                    (start, end)
                )
                columns = [desc[0] for desc in cur.description]
                return [self._row_to_record(dict(zip(columns, row))) for row in cur.fetchall()]

    def cost_attribution(self, start: datetime, end: datetime) -> List[Dict]:
        """Aggregate cost by agent for a time range."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT
                        agent_name,
                        COUNT(*) AS invocations,
                        SUM(cost_usd) AS total_cost,
                        AVG(duration_ms) AS avg_latency_ms,
                        SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) AS total_tokens
                       FROM flight_records
                       WHERE timestamp BETWEEN %s AND %s
                       GROUP BY agent_name
                       ORDER BY total_cost DESC""",
                    (start, end)
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def compliance_report(
        self,
        start_date: str,
        end_date: str,
        include_sections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate EU AI Act Article 12 compliance evidence.

        Returns a structured report with:
        - usage_periods: Session start/end (Art. 12)
        - reference_databases: Tools/APIs accessed (Art. 12)
        - human_oversight_events: Human-in-loop actions (Art. 14)
        - guardrail_summary: Risk management evidence (Art. 9)
        """
        sections = include_sections or [
            "usage_periods", "reference_databases",
            "human_oversight_events", "guardrail_summary",
        ]
        report = {
            "report_date": datetime.now(timezone.utc).isoformat(),
            "period": {"start": start_date, "end": end_date},
            "sections": {},
        }

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                if "usage_periods" in sections:
                    cur.execute(
                        """SELECT
                            DATE_TRUNC('day', timestamp) AS day,
                            MIN(timestamp) AS first_use,
                            MAX(timestamp) AS last_use,
                            COUNT(*) AS total_operations
                           FROM flight_records
                           WHERE timestamp BETWEEN %s AND %s
                           GROUP BY day ORDER BY day""",
                        (start_date, end_date)
                    )
                    columns = [desc[0] for desc in cur.description]
                    report["sections"]["usage_periods"] = [
                        {k: str(v) for k, v in zip(columns, row)} for row in cur.fetchall()
                    ]

                if "reference_databases" in sections:
                    cur.execute(
                        """SELECT DISTINCT
                            jsonb_array_elements(tool_calls)->>'gen_ai.tool.name' AS tool_name,
                            jsonb_array_elements(tool_calls)->>'gen_ai.tool.type' AS tool_type,
                            COUNT(*) AS usage_count
                           FROM flight_records
                           WHERE tool_calls IS NOT NULL
                           AND timestamp BETWEEN %s AND %s
                           GROUP BY tool_name, tool_type
                           ORDER BY usage_count DESC""",
                        (start_date, end_date)
                    )
                    columns = [desc[0] for desc in cur.description]
                    report["sections"]["reference_databases"] = [
                        dict(zip(columns, row)) for row in cur.fetchall()
                    ]

                if "human_oversight_events" in sections:
                    cur.execute(
                        """SELECT trace_id, agent_name, timestamp, operation_name
                           FROM flight_records
                           WHERE compliance->>'human_in_loop' = 'true'
                           AND timestamp BETWEEN %s AND %s
                           ORDER BY timestamp""",
                        (start_date, end_date)
                    )
                    columns = [desc[0] for desc in cur.description]
                    report["sections"]["human_oversight_events"] = [
                        {k: str(v) for k, v in zip(columns, row)} for row in cur.fetchall()
                    ]

                if "guardrail_summary" in sections:
                    cur.execute(
                        """SELECT
                            COUNT(*) AS total_records,
                            COUNT(*) FILTER (WHERE compliance->>'all_passed' = 'true') AS passed,
                            COUNT(*) FILTER (WHERE compliance->>'all_passed' = 'false') AS failed
                           FROM flight_records
                           WHERE compliance IS NOT NULL
                           AND timestamp BETWEEN %s AND %s""",
                        (start_date, end_date)
                    )
                    row = cur.fetchone()
                    report["sections"]["guardrail_summary"] = {
                        "total_checked": row[0],
                        "passed": row[1],
                        "failed": row[2],
                        "pass_rate": f"{row[1] / max(row[0], 1) * 100:.1f}%",
                    }

        return report

    # -- Internal Helpers --

    @staticmethod
    def _record_to_params(record: FlightRecord) -> Dict:
        return {
            "trace_id": record.trace_id,
            "span_id": record.span_id,
            "parent_span_id": record.parent_span_id,
            "timestamp": record.timestamp,
            "agent_id": record.agent_id,
            "agent_name": record.agent_name,
            "agent_version": record.agent_version,
            "config_hash": record.config_hash,
            "operation_name": record.operation_name,
            "duration_ms": record.duration_ms,
            "model_name": record.model_name,
            "temperature": record.temperature,
            "max_tokens": record.max_tokens,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cache_read_tokens": record.cache_read_tokens,
            "cost_usd": record.cost_usd,
            "reasoning": Json(record.reasoning) if record.reasoning else None,
            "tool_calls": Json(record.tool_calls) if record.tool_calls else None,
            "inter_agent": Json(record.inter_agent) if record.inter_agent else None,
            "state": Json(record.state) if record.state else None,
            "outcome": Json(record.outcome) if record.outcome else None,
            "compliance": Json(record.compliance) if record.compliance else None,
            "status": record.status,
            "error_type": record.error_type,
            "error_message": record.error_message,
        }

    @staticmethod
    def _row_to_record(row: Dict) -> FlightRecord:
        return FlightRecord(
            trace_id=row.get("trace_id", "").strip(),
            span_id=row.get("span_id", "").strip(),
            parent_span_id=row.get("parent_span_id", "").strip() if row.get("parent_span_id") else None,
            timestamp=row.get("timestamp"),
            agent_id=row.get("agent_id", ""),
            agent_name=row.get("agent_name"),
            agent_version=row.get("agent_version"),
            config_hash=row.get("config_hash"),
            operation_name=row.get("operation_name"),
            duration_ms=row.get("duration_ms"),
            model_name=row.get("model_name"),
            temperature=row.get("temperature"),
            max_tokens=row.get("max_tokens"),
            input_tokens=row.get("input_tokens"),
            output_tokens=row.get("output_tokens"),
            cache_read_tokens=row.get("cache_read_tokens"),
            cost_usd=row.get("cost_usd"),
            reasoning=row.get("reasoning"),
            tool_calls=row.get("tool_calls"),
            inter_agent=row.get("inter_agent"),
            state=row.get("state"),
            outcome=row.get("outcome"),
            compliance=row.get("compliance"),
            status=row.get("status", "ok"),
            error_type=row.get("error_type"),
            error_message=row.get("error_message"),
        )
