"""
LangChain/LangGraph + AI Flight Recorder — Instrumented Example

Demonstrates how to add Flight Recorder instrumentation to a
LangGraph multi-agent workflow with:
- Automatic OTel spans for each agent node
- Reasoning traces at decision points
- Tool call logging with latency
- Guardrail checks with pass/fail
- PII redaction on outputs

Prerequisites:
    pip install langchain-core langchain-openai langgraph
    pip install -r requirements.txt
    docker compose up -d

    export OPENAI_API_KEY=sk-...

Run:
    python examples/langchain_instrumented.py
"""

import asyncio
import sys
import time
import random

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
# Initialize
# ---------------------------------------------------------------------------

tracer = init_flight_recorder(
    service_name="langchain-agents-demo",
    otlp_endpoint="http://localhost:4317",
    capture_content=False,
)

redactor = PIIRedactor(patterns=["email", "phone", "credit_card"], strategy="hash")


# ---------------------------------------------------------------------------
# Simulated LangGraph Nodes (instrumented with Flight Recorder)
# ---------------------------------------------------------------------------

@flight_recorder_middleware(
    agent_id="router-v1",
    agent_name="RouterAgent",
    agent_version="1.0.0",
    operation_type="invoke_agent",
)
async def router_node(state: dict) -> dict:
    """Routes the user query to the appropriate specialist agent."""
    query = state.get("query", "")

    # Classify intent
    if any(kw in query.lower() for kw in ["weather", "temperature", "forecast"]):
        route = "weather_agent"
        confidence = 0.95
    elif any(kw in query.lower() for kw in ["search", "find", "research", "what is"]):
        route = "research_agent"
        confidence = 0.88
    else:
        route = "general_agent"
        confidence = 0.72

    log_reasoning(
        strategy="keyword_classification",
        confidence=confidence,
        rationale=f"Query '{query[:50]}' matched route '{route}'",
        alternatives_considered=3,
        selected_action=f"route_to_{route}",
    )

    # Input guardrails
    scan = redactor.scan(query)
    log_guardrail_check("input_pii_scan", passed=not scan.pii_detected, score=len(scan.detections))
    log_guardrail_check("toxicity_filter", passed=True, score=0.02, threshold=0.5)

    await asyncio.sleep(random.uniform(0.02, 0.05))

    return {
        **state,
        "route": route,
        "tokens": {"input": 50, "output": 20},
        "cost_usd": 0.0002,
        "model": "gpt-4o-mini",
    }


@flight_recorder_middleware(
    agent_id="weather-v2",
    agent_name="WeatherAgent",
    agent_version="2.0.0",
    operation_type="invoke_agent",
)
async def weather_node(state: dict) -> dict:
    """Fetches weather information using external API."""
    query = state.get("query", "")

    log_reasoning(
        strategy="api_selection",
        confidence=0.96,
        rationale="Query requests weather data; calling OpenWeatherMap API",
        alternatives_considered=2,
        selected_action="call_weather_api",
    )

    # Simulate weather API call
    start = time.monotonic()
    await asyncio.sleep(random.uniform(0.1, 0.25))
    latency = int((time.monotonic() - start) * 1000)

    log_tool_call(
        tool_name="openweathermap_api",
        tool_type="function",
        parameters={"query": query, "units": "metric"},
        response_status=200,
        latency_ms=latency,
    )

    return {
        **state,
        "response": "Tokyo: 22°C, partly cloudy. Humidity 65%. Wind 12 km/h NE.",
        "tokens": {"input": 120, "output": 60},
        "cost_usd": 0.0008,
        "model": "gpt-4o",
    }


@flight_recorder_middleware(
    agent_id="research-v3",
    agent_name="ResearchAgent",
    agent_version="3.1.0",
    operation_type="invoke_agent",
)
async def research_node(state: dict) -> dict:
    """Searches knowledge base and synthesizes an answer."""
    query = state.get("query", "")

    log_reasoning(
        strategy="retrieval_augmented_generation",
        confidence=0.84,
        rationale="Query requires factual lookup; using RAG pipeline with vector search",
        alternatives_considered=2,
        selected_action="vector_search_then_synthesize",
    )

    # Simulate vector search
    start = time.monotonic()
    await asyncio.sleep(random.uniform(0.15, 0.35))
    latency = int((time.monotonic() - start) * 1000)

    log_tool_call(
        tool_name="vector_search",
        tool_type="function",
        parameters={"query": query, "top_k": 5, "threshold": 0.7},
        response_status=200,
        latency_ms=latency,
    )

    # Simulate LLM synthesis
    log_tool_call(
        tool_name="llm_synthesize",
        tool_type="function",
        parameters={"context_chunks": 5, "max_tokens": 500},
        response_status=200,
        latency_ms=random.randint(300, 800),
    )

    return {
        **state,
        "response": f"Based on 5 relevant sources, here is what we found about: {query[:50]}...",
        "tokens": {"input": 800, "output": 250},
        "cost_usd": 0.0035,
        "model": "gpt-4o",
    }


@flight_recorder_middleware(
    agent_id="output-guard-v1",
    agent_name="OutputGuardrailAgent",
    agent_version="1.0.0",
    operation_type="invoke_agent",
)
async def output_guardrail_node(state: dict) -> dict:
    """Final guardrail check on the output before returning to user."""
    response = state.get("response", "")

    # Check output for PII
    scan = redactor.scan(response)
    log_guardrail_check(
        "output_pii_scan",
        passed=not scan.pii_detected,
        score=len(scan.detections),
        threshold=0,
    )

    # Check output for hallucination indicators
    hallucination_score = random.uniform(0.0, 0.15)
    log_guardrail_check(
        "hallucination_detector",
        passed=hallucination_score < 0.3,
        score=hallucination_score,
        threshold=0.3,
    )

    # Redact if needed
    clean_response = redactor.redact(response) if scan.pii_detected else response

    log_reasoning(
        strategy="output_validation",
        confidence=1.0 - hallucination_score,
        rationale="Output passed all guardrail checks; safe to return",
        selected_action="return_to_user",
    )

    return {
        **state,
        "response": clean_response,
        "guardrails_passed": True,
        "tokens": {"input": 30, "output": 10},
        "cost_usd": 0.0001,
        "model": "gpt-4o-mini",
    }


# ---------------------------------------------------------------------------
# Simulated LangGraph Execution
# ---------------------------------------------------------------------------

async def run_graph(query: str) -> str:
    """
    Simulates a LangGraph execution flow:
    Router → Specialist (Weather/Research/General) → Output Guardrail
    """
    state = {"query": query}

    # Step 1: Route
    state = await router_node(state)
    route = state.get("route", "general_agent")

    # Step 2: Execute specialist
    if route == "weather_agent":
        state = await weather_node(state)
    elif route == "research_agent":
        state = await research_node(state)
    else:
        state["response"] = "I can help with weather and research queries."

    # Step 3: Output guardrail
    state = await output_guardrail_node(state)

    return state.get("response", "No response generated.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("\n" + "=" * 60)
    print("  LangChain/LangGraph + AI Flight Recorder")
    print("  Traces visible at: http://localhost:16686 (Jaeger)")
    print("=" * 60 + "\n")

    queries = [
        "What's the weather in Mumbai?",
        "What is retrieval augmented generation and how does it work?",
        "Tell me about the EU AI Act compliance timeline",
    ]

    for query in queries:
        print(f"\n{'─' * 50}")
        print(f"Query: {query}")
        response = await run_graph(query)
        print(f"Response: {response[:150]}")

    print(f"\n{'=' * 60}")
    print("  Done! Check traces at http://localhost:16686")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
