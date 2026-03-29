"""
AI Flight Recorder — Engineering Auditability in Agentic Workflows

Production-ready instrumentation, event sourcing, and replay engine
for multi-agent AI systems using OpenTelemetry.
"""

__version__ = "0.1.0"
__author__ = "FellowTechie"

from .instrumentation import init_flight_recorder, flight_recorder_middleware
from .event_store import EventStore, FlightRecord
from .replay_engine import ReplayEngine
from .pii_redactor import PIIRedactor

__all__ = [
    "init_flight_recorder",
    "flight_recorder_middleware",
    "EventStore",
    "FlightRecord",
    "ReplayEngine",
    "PIIRedactor",
]
