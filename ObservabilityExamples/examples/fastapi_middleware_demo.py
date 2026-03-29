"""
FastAPI + AI Flight Recorder — Demo Application

Demonstrates:
- One-line OTel initialization
- Agent middleware decorator on endpoint handlers
- Tool call logging
- Guardrail check logging
- Reasoning trace capture
- PII redaction on responses
- Trace context propagation headers

Run:
    pip install -r requirements.txt
    docker compose up -d  # Start Jaeger + OTel Collector + PostgreSQL
    python examples/fastapi_middleware_demo.py

Then:
    curl http://localhost:8000/ask?q=What+is+the+weather+in+Tokyo

View traces:
    http://localhost:16686  (Jaeger UI)
"""

import asyncio
import time
import random
from typing import Optional

import uvicorn
from fastapi import FastAPI, Query

# Flight Recorder imports
import sys
sys.path.insert(0, "src")

from flight_recorder.instrumentation import (
    init_flight_recorder,
    flight_recorder_middleware,
    log_tool_call,
    log_guardrail_check,
    log_reasoning,
)
from flight_recorder.pii_redactor import PIIRedactor

# ---------------------------------------------------------------------------
# Initialize Flight Recorder (one line!)
# ---------------------------------------------------------------------------

tracer = init_flight_recorder(
    service_name="demo-agent-system",
    otlp_endpoint="http://localhost:4317",
    capture_content=False,  # Set True for dev debugging
)

# PII Redactor
redactor = PIIRedactor(
    patterns=["email", "phone", "ssn", "credit_card"],
    strategy="hash",
)

# FastAPI app
app = FastAPI(title="AI Flight Recorder Demo", version="0.1.0")


# ---------------------------------------------------------------------------
# Simulated Agent Functions
# ---------------------------------------------------------------------------

@flight_recorder_middleware(
    agent_id="orchestrator-v1",
    agent_name="OrchestratorAgent",
    agent_version="1.0.0",
    operation_type="invoke_agent",
)
async def orchestrate(user_query: str) -> dict:
    """Top-level orchestrator: routes to planner, then executor."""

    # Log reasoning for routing decision
    log_reasoning(
        strategy="rule_based_routing",
        confidence=0.95,
        rationale=f"Query '{user_query[:50]}' classified as information_retrieval; routing to PlannerAgent",
        alternatives_considered=3,
        selected_action="delegate_to_planner",
    )

    # Run guardrail checks
    log_guardrail_check("toxicity_filter", passed=True, score=0.01, threshold=0.5)
    log_guardrail_check("pii_scanner", passed=True, score=0.0, threshold=0.0)

    # Delegate to planner
    plan = await plan_task(user_query)

    # Delegate to executor
    result = await execute_task(plan)

    return {
        "result": result,
        "tokens": {"input": 150, "output": 80},
        "cost_usd": 0.0012,
        "model": "gpt-4o",
    }


@flight_recorder_middleware(
    agent_id="planner-v2",
    agent_name="PlannerAgent",
    agent_version="2.1.0",
    operation_type="invoke_agent",
)
async def plan_task(user_query: str) -> dict:
    """Plans the execution strategy for a user query."""

    log_reasoning(
        strategy="chain_of_thought",
        confidence=0.88,
        rationale="User wants factual information; plan: 1) search knowledge base, 2) format response",
        alternatives_considered=2,
        selected_action="search_then_format",
    )

    # Simulate planning latency
    await asyncio.sleep(random.uniform(0.05, 0.15))

    return {
        "plan": ["search_knowledge_base", "format_response"],
        "tokens": {"input": 80, "output": 40},
        "cost_usd": 0.0005,
        "model": "gpt-4o-mini",
    }


@flight_recorder_middleware(
    agent_id="executor-v1",
    agent_name="ExecutorAgent",
    agent_version="1.3.0",
    operation_type="invoke_agent",
)
async def execute_task(plan: dict) -> str:
    """Executes the plan by calling tools."""

    log_reasoning(
        strategy="plan_execution",
        confidence=0.92,
        rationale=f"Executing plan steps: {plan.get('plan', [])}",
        alternatives_considered=0,
        selected_action="execute_sequentially",
    )

    # Simulate tool call: search API
    start = time.monotonic()
    await asyncio.sleep(random.uniform(0.1, 0.3))  # Simulate API latency
    latency_ms = int((time.monotonic() - start) * 1000)

    log_tool_call(
        tool_name="knowledge_base_search",
        tool_type="function",
        parameters={"query": "weather information", "top_k": 5},
        response_status=200,
        latency_ms=latency_ms,
    )

    # Simulate tool call: formatter
    log_tool_call(
        tool_name="response_formatter",
        tool_type="function",
        parameters={"template": "factual_answer", "style": "concise"},
        response_status=200,
        latency_ms=12,
    )

    return "The weather in Tokyo is currently 18°C with partly cloudy skies."


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/ask")
async def ask(q: str = Query(..., description="User query")):
    """
    Main endpoint: processes a user query through the multi-agent pipeline.

    The entire request is automatically traced with the Flight Recorder.
    View traces at http://localhost:16686 (Jaeger UI).
    """
    result = await orchestrate(q)

    # Redact PII from response before returning
    clean_result = redactor.redact(result.get("result", ""))

    return {
        "answer": clean_result,
        "trace_info": "View trace at http://localhost:16686",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "demo-agent-system", "flight_recorder": "active"}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  AI Flight Recorder — Demo Application")
    print("  Jaeger UI:  http://localhost:16686")
    print("  API:        http://localhost:8000/ask?q=hello")
    print("  Health:     http://localhost:8000/health")
    print("=" * 60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
