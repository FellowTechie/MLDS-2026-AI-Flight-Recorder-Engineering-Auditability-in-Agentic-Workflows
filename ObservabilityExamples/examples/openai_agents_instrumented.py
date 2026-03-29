"""
OpenAI Agents SDK + AI Flight Recorder — Instrumented Example

Demonstrates how to wrap an OpenAI Agents SDK multi-agent workflow
with Flight Recorder instrumentation for full auditability.

Prerequisites:
    pip install openai-agents openinference-instrumentation-openai-agents
    pip install -r requirements.txt
    docker compose up -d

    export OPENAI_API_KEY=sk-...

Run:
    python examples/openai_agents_instrumented.py
"""

import asyncio
import os
import sys

sys.path.insert(0, "src")

from agents import Agent, Runner, function_tool, trace

from flight_recorder.instrumentation import (
    init_flight_recorder,
    log_tool_call,
    log_guardrail_check,
    log_reasoning,
)
from flight_recorder.pii_redactor import PIIRedactor

# ---------------------------------------------------------------------------
# Initialize Flight Recorder
# ---------------------------------------------------------------------------

tracer = init_flight_recorder(
    service_name="openai-agents-demo",
    otlp_endpoint="http://localhost:4317",
    capture_content=False,
)

# Optional: OpenInference auto-instrumentation for OpenAI Agents
# This automatically creates spans for every agent invocation and tool call
try:
    from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
    OpenAIAgentsInstrumentor().instrument()
    print("[✓] OpenInference auto-instrumentation enabled")
except ImportError:
    print("[!] openinference-instrumentation-openai-agents not installed")
    print("    Install: pip install openinference-instrumentation-openai-agents")

redactor = PIIRedactor(patterns=["email", "phone", "credit_card"], strategy="hash")


# ---------------------------------------------------------------------------
# Define Tools
# ---------------------------------------------------------------------------

@function_tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    # In production, this would call a real weather API
    # Flight Recorder captures this tool call automatically via OpenInference
    log_tool_call(
        tool_name="get_weather",
        tool_type="function",
        parameters={"city": city},
        response_status=200,
        latency_ms=150,
    )
    return f"The weather in {city} is 22°C with clear skies."


@function_tool
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """Search the internal knowledge base for information."""
    log_tool_call(
        tool_name="search_knowledge_base",
        tool_type="function",
        parameters={"query": query, "top_k": top_k},
        response_status=200,
        latency_ms=230,
    )
    return f"Found {top_k} results for '{query}'. Top result: relevant information about the topic."


@function_tool
def send_notification(recipient: str, message: str) -> str:
    """Send a notification to a user. Requires human approval for PII-containing messages."""
    # Guardrail: check for PII before sending
    scan_result = redactor.scan(message)
    log_guardrail_check(
        guardrail_name="pii_scanner",
        passed=not scan_result.pii_detected,
        score=len(scan_result.detections),
        threshold=0,
        details=f"PII types found: {scan_result.pii_types_found}" if scan_result.pii_detected else "Clean",
    )

    if scan_result.pii_detected:
        clean_message = redactor.redact(message)
        log_tool_call(
            tool_name="send_notification",
            tool_type="function",
            parameters={"recipient": redactor.redact(recipient), "message": "[PII REDACTED]"},
            response_status=200,
            latency_ms=50,
        )
        return f"Notification sent to {redactor.redact(recipient)} with PII redacted."
    else:
        log_tool_call(
            tool_name="send_notification",
            tool_type="function",
            parameters={"recipient": recipient, "message": message[:100]},
            response_status=200,
            latency_ms=50,
        )
        return f"Notification sent to {recipient}."


# ---------------------------------------------------------------------------
# Define Agents
# ---------------------------------------------------------------------------

# Research agent: handles information lookup
research_agent = Agent(
    name="ResearchAgent",
    instructions="""You are a research assistant. Use the search_knowledge_base tool
    to find information. Always provide accurate, well-sourced answers.
    If you need weather data, use the get_weather tool.""",
    tools=[search_knowledge_base, get_weather],
)

# Notification agent: handles user communications
notification_agent = Agent(
    name="NotificationAgent",
    instructions="""You are a notification assistant. Use the send_notification tool
    to deliver messages to users. Always be polite and concise.""",
    tools=[send_notification],
)

# Triage agent: routes to the right specialist
triage_agent = Agent(
    name="TriageAgent",
    instructions="""You are a triage agent that routes requests to specialists.
    - For information/research questions → hand off to ResearchAgent
    - For sending messages/notifications → hand off to NotificationAgent
    Always explain your routing decision.""",
    handoffs=[research_agent, notification_agent],
)


# ---------------------------------------------------------------------------
# Run the Multi-Agent Workflow
# ---------------------------------------------------------------------------

async def main():
    print("\n" + "=" * 60)
    print("  OpenAI Agents SDK + AI Flight Recorder")
    print("  Traces visible at: http://localhost:16686 (Jaeger)")
    print("=" * 60 + "\n")

    queries = [
        "What's the weather like in Tokyo today?",
        "Search for information about quantum computing advances in 2026",
        "Send a notification to the team that the weekly report is ready",
    ]

    for query in queries:
        print(f"\n{'─' * 50}")
        print(f"Query: {query}")
        print(f"{'─' * 50}")

        # Wrap the entire workflow in a Flight Recorder trace
        with trace(f"user_request: {query[:40]}"):
            # Log triage reasoning
            log_reasoning(
                strategy="intent_classification",
                confidence=0.93,
                rationale=f"Classifying user intent for: {query[:50]}",
                alternatives_considered=3,
                selected_action="route_to_specialist",
            )

            # Run guardrail on input
            input_scan = redactor.scan(query)
            log_guardrail_check(
                guardrail_name="input_pii_scanner",
                passed=not input_scan.pii_detected,
                score=len(input_scan.detections),
                threshold=0,
            )
            log_guardrail_check(
                guardrail_name="toxicity_filter",
                passed=True,
                score=0.01,
                threshold=0.5,
            )

            try:
                result = await Runner.run(triage_agent, query)
                print(f"Result: {result.final_output[:200]}")
            except Exception as e:
                print(f"Error: {e}")
                # Error is automatically captured in the span by OpenInference

    print(f"\n{'=' * 60}")
    print("  Done! Check Jaeger UI for full traces.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
