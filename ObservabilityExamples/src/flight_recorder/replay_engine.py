"""
Replay Engine — Time-Travel Debugging for Multi-Agent Systems

Capabilities:
- Reconstruct full execution timeline from any trace_id
- Diff analysis: compare two traces side-by-side
- Identify bottlenecks, cost hotspots, and failure points
- Generate human-readable execution summaries
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .event_store import EventStore, FlightRecord


@dataclass
class ReplayStep:
    """A single step in a replayed execution timeline."""
    sequence: int
    timestamp: datetime
    agent_name: str
    agent_id: str
    operation: str
    duration_ms: int
    status: str
    model: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    cost_usd: Optional[float]
    reasoning_rationale: Optional[str]
    reasoning_confidence: Optional[float]
    tool_calls: List[Dict]
    error: Optional[str]
    children: List["ReplayStep"]
    span_id: str
    parent_span_id: Optional[str]


@dataclass
class TraceAnalysis:
    """Analysis summary for a replayed trace."""
    trace_id: str
    total_duration_ms: int
    total_cost_usd: float
    total_tokens: int
    agent_count: int
    span_count: int
    error_count: int
    tool_call_count: int
    guardrail_failures: int
    bottleneck_agent: Optional[str]  # Slowest agent
    costliest_agent: Optional[str]   # Most expensive agent
    critical_path: List[str]         # Agent chain on the longest path


class ReplayEngine:
    """
    Time-travel debugging engine for multi-agent traces.

    Usage:
        engine = ReplayEngine(event_store=store)

        # Replay a trace
        timeline = engine.replay("a1b2c3d4...")
        for step in timeline:
            print(f"[{step.timestamp}] {step.agent_name}: {step.operation}")

        # Analyze a trace
        analysis = engine.analyze("a1b2c3d4...")
        print(f"Total cost: ${analysis.total_cost_usd:.4f}")
        print(f"Bottleneck: {analysis.bottleneck_agent}")

        # Diff two traces
        diff = engine.diff("trace_a", "trace_b")
    """

    def __init__(self, event_store: EventStore):
        self.store = event_store

    def replay(self, trace_id: str) -> List[ReplayStep]:
        """
        Reconstruct a full execution timeline from a trace_id.

        Returns a flat list of ReplaySteps ordered by timestamp.
        Each step includes the reasoning rationale and tool calls.
        """
        records = self.store.get_trace(trace_id)
        if not records:
            return []

        steps = []
        for i, record in enumerate(records):
            # Extract reasoning
            rationale = None
            confidence = None
            if record.reasoning:
                rationale = record.reasoning.get("rationale")
                confidence = record.reasoning.get("confidence")

            # Extract tool call names
            tool_calls = record.tool_calls or []

            # Extract error info
            error = None
            if record.status == "error":
                error = f"{record.error_type}: {record.error_message}"

            steps.append(ReplayStep(
                sequence=i + 1,
                timestamp=record.timestamp,
                agent_name=record.agent_name or record.agent_id,
                agent_id=record.agent_id,
                operation=record.operation_name or "unknown",
                duration_ms=record.duration_ms or 0,
                status=record.status,
                model=record.model_name,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                cost_usd=float(record.cost_usd) if record.cost_usd else 0.0,
                reasoning_rationale=rationale,
                reasoning_confidence=confidence,
                tool_calls=tool_calls,
                error=error,
                children=[],
                span_id=record.span_id,
                parent_span_id=record.parent_span_id,
            ))

        return steps

    def replay_tree(self, trace_id: str) -> List[ReplayStep]:
        """
        Reconstruct as a tree (parent-child hierarchy).

        Returns only root-level steps; children are nested.
        """
        flat = self.replay(trace_id)
        if not flat:
            return []

        by_span = {s.span_id: s for s in flat}
        roots = []

        for step in flat:
            if step.parent_span_id and step.parent_span_id in by_span:
                by_span[step.parent_span_id].children.append(step)
            else:
                roots.append(step)

        return roots

    def analyze(self, trace_id: str) -> TraceAnalysis:
        """
        Produce a summary analysis of a trace.

        Identifies bottlenecks, cost hotspots, and failure points.
        """
        steps = self.replay(trace_id)
        if not steps:
            return TraceAnalysis(
                trace_id=trace_id,
                total_duration_ms=0, total_cost_usd=0.0, total_tokens=0,
                agent_count=0, span_count=0, error_count=0,
                tool_call_count=0, guardrail_failures=0,
                bottleneck_agent=None, costliest_agent=None,
                critical_path=[],
            )

        agents = set()
        agent_duration: Dict[str, int] = {}
        agent_cost: Dict[str, float] = {}
        total_tokens = 0
        tool_call_count = 0
        error_count = 0

        for step in steps:
            agents.add(step.agent_id)
            agent_duration[step.agent_name] = (
                agent_duration.get(step.agent_name, 0) + step.duration_ms
            )
            agent_cost[step.agent_name] = (
                agent_cost.get(step.agent_name, 0.0) + step.cost_usd
            )
            total_tokens += (step.input_tokens or 0) + (step.output_tokens or 0)
            tool_call_count += len(step.tool_calls)
            if step.status == "error":
                error_count += 1

        # Total trace duration: first timestamp to last timestamp + last duration
        first_ts = steps[0].timestamp
        last_step = steps[-1]
        total_duration = int(
            (last_step.timestamp - first_ts).total_seconds() * 1000
        ) + (last_step.duration_ms or 0)

        bottleneck = max(agent_duration, key=agent_duration.get) if agent_duration else None
        costliest = max(agent_cost, key=agent_cost.get) if agent_cost else None

        # Critical path: trace the longest parent→child chain
        critical_path = self._find_critical_path(steps)

        return TraceAnalysis(
            trace_id=trace_id,
            total_duration_ms=total_duration,
            total_cost_usd=sum(agent_cost.values()),
            total_tokens=total_tokens,
            agent_count=len(agents),
            span_count=len(steps),
            error_count=error_count,
            tool_call_count=tool_call_count,
            guardrail_failures=0,  # TODO: count from compliance field
            bottleneck_agent=bottleneck,
            costliest_agent=costliest,
            critical_path=critical_path,
        )

    def diff(self, trace_id_a: str, trace_id_b: str) -> Dict[str, Any]:
        """
        Compare two traces side-by-side.

        Useful for regression analysis: "Why did this trace cost $5 but yesterday's
        was $0.50?"
        """
        analysis_a = self.analyze(trace_id_a)
        analysis_b = self.analyze(trace_id_b)

        return {
            "trace_a": trace_id_a,
            "trace_b": trace_id_b,
            "duration_diff_ms": analysis_b.total_duration_ms - analysis_a.total_duration_ms,
            "cost_diff_usd": analysis_b.total_cost_usd - analysis_a.total_cost_usd,
            "token_diff": analysis_b.total_tokens - analysis_a.total_tokens,
            "span_count_diff": analysis_b.span_count - analysis_a.span_count,
            "error_count_diff": analysis_b.error_count - analysis_a.error_count,
            "analysis_a": {
                "duration_ms": analysis_a.total_duration_ms,
                "cost_usd": analysis_a.total_cost_usd,
                "tokens": analysis_a.total_tokens,
                "agents": analysis_a.agent_count,
                "errors": analysis_a.error_count,
                "bottleneck": analysis_a.bottleneck_agent,
                "costliest": analysis_a.costliest_agent,
            },
            "analysis_b": {
                "duration_ms": analysis_b.total_duration_ms,
                "cost_usd": analysis_b.total_cost_usd,
                "tokens": analysis_b.total_tokens,
                "agents": analysis_b.agent_count,
                "errors": analysis_b.error_count,
                "bottleneck": analysis_b.bottleneck_agent,
                "costliest": analysis_b.costliest_agent,
            },
        }

    def print_timeline(self, trace_id: str):
        """Pretty-print a trace timeline to stdout."""
        steps = self.replay(trace_id)
        if not steps:
            print(f"No records found for trace {trace_id}")
            return

        print(f"\n{'='*80}")
        print(f"TRACE REPLAY: {trace_id}")
        print(f"{'='*80}\n")

        for step in steps:
            status_icon = "✅" if step.status == "ok" else "❌"
            cost_str = f"${step.cost_usd:.4f}" if step.cost_usd else "—"
            tokens_str = f"{(step.input_tokens or 0) + (step.output_tokens or 0)} tok"

            print(f"  [{step.sequence:02d}] {status_icon} {step.agent_name}")
            print(f"       Operation: {step.operation}")
            print(f"       Duration:  {step.duration_ms}ms | Cost: {cost_str} | {tokens_str}")

            if step.model:
                print(f"       Model:     {step.model}")

            if step.reasoning_rationale:
                print(f"       Reasoning: {step.reasoning_rationale[:100]}...")

            if step.tool_calls:
                tools = [tc.get("gen_ai.tool.name", "?") for tc in step.tool_calls]
                print(f"       Tools:     {', '.join(tools)}")

            if step.error:
                print(f"       Error:     {step.error[:100]}")

            print()

        # Summary
        analysis = self.analyze(trace_id)
        print(f"{'─'*80}")
        print(f"  SUMMARY")
        print(f"  Total: {analysis.total_duration_ms}ms | ${analysis.total_cost_usd:.4f} | {analysis.total_tokens} tokens")
        print(f"  Agents: {analysis.agent_count} | Spans: {analysis.span_count} | Errors: {analysis.error_count}")
        if analysis.bottleneck_agent:
            print(f"  Bottleneck: {analysis.bottleneck_agent}")
        if analysis.costliest_agent:
            print(f"  Costliest:  {analysis.costliest_agent}")
        print(f"{'='*80}\n")

    # -- Internal --

    @staticmethod
    def _find_critical_path(steps: List[ReplayStep]) -> List[str]:
        """Find the longest-duration path through the span tree."""
        if not steps:
            return []

        # Build adjacency from parent→children
        children_map: Dict[str, List[ReplayStep]] = {}
        roots = []
        for step in steps:
            if step.parent_span_id:
                children_map.setdefault(step.parent_span_id, []).append(step)
            else:
                roots.append(step)

        def longest_path(step: ReplayStep) -> Tuple[int, List[str]]:
            kids = children_map.get(step.span_id, [])
            if not kids:
                return step.duration_ms, [step.agent_name]
            best_dur, best_path = 0, []
            for child in kids:
                dur, path = longest_path(child)
                if dur > best_dur:
                    best_dur, best_path = dur, path
            return step.duration_ms + best_dur, [step.agent_name] + best_path

        if not roots:
            return [steps[0].agent_name]

        overall_dur, overall_path = 0, []
        for root in roots:
            dur, path = longest_path(root)
            if dur > overall_dur:
                overall_dur, overall_path = dur, path

        return overall_path
