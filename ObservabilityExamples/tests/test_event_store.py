"""
Unit Tests for Flight Recorder Event Store

Run:
    pytest tests/test_event_store.py -v

Note: These tests use in-memory mocking for the database.
For integration tests, set FLIGHT_RECORDER_DSN env var.
"""

import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, "src")

from flight_recorder.event_store import FlightRecord, EventStore


# ---------------------------------------------------------------------------
# FlightRecord Tests
# ---------------------------------------------------------------------------

class TestFlightRecord:
    """Tests for the FlightRecord dataclass."""

    def test_create_minimal(self):
        record = FlightRecord(
            trace_id="a" * 32,
            span_id="b" * 16,
            agent_id="test-agent-v1",
        )
        assert record.trace_id == "a" * 32
        assert record.span_id == "b" * 16
        assert record.agent_id == "test-agent-v1"
        assert record.status == "ok"
        assert record.timestamp is not None

    def test_create_full(self):
        now = datetime.now(timezone.utc)
        record = FlightRecord(
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id="c" * 16,
            agent_id="planner-v3",
            agent_name="PlannerAgent",
            agent_version="3.2.1",
            config_hash="sha256:abcdef1234567890",
            operation_name="invoke_agent",
            duration_ms=847,
            model_name="gpt-4o",
            temperature=0.3,
            max_tokens=2048,
            input_tokens=1247,
            output_tokens=389,
            cache_read_tokens=512,
            cost_usd=Decimal("0.0043"),
            reasoning={
                "strategy": "chain_of_thought",
                "confidence": 0.87,
                "rationale": "Routing to executor for real-time data",
            },
            tool_calls=[{
                "tool_name": "search_api",
                "response_status": 200,
                "latency_ms": 234,
            }],
            compliance={
                "guardrail_checks": [{"name": "toxicity", "passed": True}],
                "all_passed": True,
                "human_in_loop": False,
            },
            timestamp=now,
        )

        assert record.agent_name == "PlannerAgent"
        assert record.input_tokens == 1247
        assert record.cost_usd == Decimal("0.0043")
        assert record.reasoning["confidence"] == 0.87
        assert len(record.tool_calls) == 1
        assert record.compliance["all_passed"] is True

    def test_default_timestamp_is_utc(self):
        record = FlightRecord(
            trace_id="a" * 32,
            span_id="b" * 16,
            agent_id="test",
        )
        assert record.timestamp.tzinfo is not None

    def test_error_record(self):
        record = FlightRecord(
            trace_id="a" * 32,
            span_id="b" * 16,
            agent_id="test",
            status="error",
            error_type="ValueError",
            error_message="Invalid input format",
        )
        assert record.status == "error"
        assert record.error_type == "ValueError"


# ---------------------------------------------------------------------------
# PII Redactor Tests (inline, since it's a dependency)
# ---------------------------------------------------------------------------

class TestPIIRedactor:
    """Tests for PII redaction pipeline."""

    def setup_method(self):
        from flight_recorder.pii_redactor import PIIRedactor
        self.redactor = PIIRedactor(
            patterns=["email", "phone", "ssn", "credit_card"],
            strategy="hash",
        )

    def test_redact_email(self):
        result = self.redactor.redact("Contact john@example.com for details")
        assert "john@example.com" not in result
        assert "[email:sha256:" in result

    def test_redact_phone(self):
        result = self.redactor.redact("Call me at +1-555-123-4567")
        assert "555-123-4567" not in result

    def test_redact_ssn(self):
        result = self.redactor.redact("My SSN is 123-45-6789")
        assert "123-45-6789" not in result
        assert "[ssn:sha256:" in result

    def test_redact_credit_card(self):
        result = self.redactor.redact("Card: 4111 1111 1111 1111")
        assert "4111" not in result

    def test_no_pii_unchanged(self):
        text = "The weather in Tokyo is 22 degrees"
        result = self.redactor.redact(text)
        assert result == text

    def test_scan_detects_pii(self):
        result = self.redactor.scan("Email: test@example.com, Phone: 555-123-4567")
        assert result.pii_detected is True
        assert "email" in result.pii_types_found
        assert len(result.detections) >= 1

    def test_scan_no_pii(self):
        result = self.redactor.scan("Just a normal sentence without PII")
        assert result.pii_detected is False
        assert len(result.detections) == 0

    def test_redact_dict_recursive(self):
        data = {
            "user_query": "My email is john@test.com",
            "nested": {
                "response": "Contact support@company.com",
                "metadata": {"safe": "no PII here"},
            },
        }
        result = self.redactor.redact_dict(data)
        assert "john@test.com" not in json.dumps(result)
        assert "support@company.com" not in json.dumps(result)
        assert "no PII here" in json.dumps(result)

    def test_mask_strategy(self):
        from flight_recorder.pii_redactor import PIIRedactor
        masker = PIIRedactor(patterns=["email"], strategy="mask")
        result = masker.redact("test@example.com")
        assert "test@example.com" not in result
        assert "*" in result

    def test_remove_strategy(self):
        from flight_recorder.pii_redactor import PIIRedactor
        remover = PIIRedactor(patterns=["ssn"], strategy="remove")
        result = remover.redact("SSN: 123-45-6789")
        assert "123-45-6789" not in result
        assert "REDACTED" in result

    def test_allowlist(self):
        from flight_recorder.pii_redactor import PIIRedactor
        r = PIIRedactor(
            patterns=["email"],
            strategy="hash",
            allowlist={"noreply@system.com"},
        )
        result = r.redact("From noreply@system.com to user@private.com")
        assert "noreply@system.com" in result  # Allowlisted
        assert "user@private.com" not in result  # Redacted


# ---------------------------------------------------------------------------
# Replay Engine Tests
# ---------------------------------------------------------------------------

class TestReplayEngine:
    """Tests for the replay engine."""

    def setup_method(self):
        from flight_recorder.replay_engine import ReplayEngine
        self.mock_store = MagicMock(spec=EventStore)
        self.engine = ReplayEngine(event_store=self.mock_store)

    def test_replay_empty_trace(self):
        self.mock_store.get_trace.return_value = []
        steps = self.engine.replay("nonexistent")
        assert steps == []

    def test_replay_single_span(self):
        now = datetime.now(timezone.utc)
        self.mock_store.get_trace.return_value = [
            FlightRecord(
                trace_id="a" * 32,
                span_id="b" * 16,
                agent_id="test-v1",
                agent_name="TestAgent",
                operation_name="invoke_agent",
                duration_ms=500,
                cost_usd=Decimal("0.001"),
                input_tokens=100,
                output_tokens=50,
                reasoning={"strategy": "cot", "confidence": 0.9, "rationale": "test"},
                timestamp=now,
            )
        ]

        steps = self.engine.replay("a" * 32)
        assert len(steps) == 1
        assert steps[0].agent_name == "TestAgent"
        assert steps[0].duration_ms == 500
        assert steps[0].reasoning_confidence == 0.9

    def test_analyze_trace(self):
        now = datetime.now(timezone.utc)
        self.mock_store.get_trace.return_value = [
            FlightRecord(
                trace_id="a" * 32, span_id="1" * 16,
                agent_id="a1", agent_name="Agent1",
                duration_ms=200, cost_usd=Decimal("0.002"),
                input_tokens=100, output_tokens=50,
                timestamp=now,
            ),
            FlightRecord(
                trace_id="a" * 32, span_id="2" * 16,
                parent_span_id="1" * 16,
                agent_id="a2", agent_name="Agent2",
                duration_ms=800, cost_usd=Decimal("0.005"),
                input_tokens=500, output_tokens=200,
                timestamp=now + timedelta(milliseconds=200),
            ),
        ]

        analysis = self.engine.analyze("a" * 32)
        assert analysis.agent_count == 2
        assert analysis.span_count == 2
        assert analysis.total_tokens == 850
        assert analysis.bottleneck_agent == "Agent2"
        assert analysis.costliest_agent == "Agent2"

    def test_diff_traces(self):
        now = datetime.now(timezone.utc)

        def mock_get_trace(trace_id):
            if trace_id == "trace_a":
                return [FlightRecord(
                    trace_id="trace_a", span_id="1" * 16,
                    agent_id="a1", agent_name="Agent1",
                    duration_ms=200, cost_usd=Decimal("0.001"),
                    input_tokens=100, output_tokens=50,
                    timestamp=now,
                )]
            else:
                return [FlightRecord(
                    trace_id="trace_b", span_id="2" * 16,
                    agent_id="a1", agent_name="Agent1",
                    duration_ms=500, cost_usd=Decimal("0.005"),
                    input_tokens=300, output_tokens=150,
                    timestamp=now,
                )]

        self.mock_store.get_trace.side_effect = mock_get_trace
        diff = self.engine.diff("trace_a", "trace_b")
        assert diff["cost_diff_usd"] > 0
        assert diff["duration_diff_ms"] > 0
        assert diff["token_diff"] > 0


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
