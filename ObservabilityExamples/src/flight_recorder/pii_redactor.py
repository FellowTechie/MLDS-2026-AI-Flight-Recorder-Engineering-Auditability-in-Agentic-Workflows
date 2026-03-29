"""
PII Detection & Redaction Pipeline

Scans trace payloads for personally identifiable information and either
masks, hashes, or removes it before storage.

Supports: email, phone, SSN, credit card, IP address, custom patterns.
Strategies: mask (***), hash (SHA-256 truncated), remove (empty string).
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


# ---------------------------------------------------------------------------
# Built-in PII Patterns
# ---------------------------------------------------------------------------

BUILTIN_PATTERNS: Dict[str, re.Pattern] = {
    "email": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    ),
    "phone": re.compile(
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"
    ),
    "ssn": re.compile(
        r"\b\d{3}-\d{2}-\d{4}\b"
    ),
    "credit_card": re.compile(
        r"\b(?:\d{4}[-\s]?){3}\d{4}\b"
    ),
    "ip_address": re.compile(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    ),
    "aadhaar": re.compile(
        r"\b\d{4}\s?\d{4}\s?\d{4}\b"
    ),
    "pan_india": re.compile(
        r"\b[A-Z]{5}\d{4}[A-Z]\b"
    ),
}


# ---------------------------------------------------------------------------
# Redaction Strategies
# ---------------------------------------------------------------------------

def mask_strategy(match: str, pii_type: str) -> str:
    """Replace with asterisks, preserving length hint."""
    if pii_type == "email":
        parts = match.split("@")
        return f"{'*' * len(parts[0])}@{'*' * len(parts[1]) if len(parts) > 1 else '***'}"
    return "*" * min(len(match), 12) + f"[{pii_type}]"


def hash_strategy(match: str, pii_type: str) -> str:
    """Replace with truncated SHA-256 hash (non-reversible but consistent)."""
    h = hashlib.sha256(match.encode()).hexdigest()[:12]
    return f"[{pii_type}:sha256:{h}]"


def remove_strategy(match: str, pii_type: str) -> str:
    """Replace with placeholder."""
    return f"[{pii_type}:REDACTED]"


STRATEGIES: Dict[str, Callable[[str, str], str]] = {
    "mask": mask_strategy,
    "hash": hash_strategy,
    "remove": remove_strategy,
}


# ---------------------------------------------------------------------------
# PII Redactor
# ---------------------------------------------------------------------------

@dataclass
class RedactionResult:
    """Result of a redaction operation."""
    original_length: int
    redacted_length: int
    detections: List[Dict[str, Any]]
    pii_detected: bool
    pii_types_found: Set[str]


class PIIRedactor:
    """
    PII detection and redaction for trace payloads.

    Usage:
        redactor = PIIRedactor(
            patterns=["email", "phone", "ssn", "credit_card"],
            strategy="hash"
        )

        # Redact a string
        clean_text = redactor.redact("Contact john@example.com for details")
        # → "Contact [email:sha256:a1b2c3d4e5f6] for details"

        # Redact a dict (recursive)
        clean_payload = redactor.redact_dict({
            "user_query": "My SSN is 123-45-6789",
            "response": "I found your record..."
        })

        # Scan without redacting
        result = redactor.scan("Call me at +1-555-123-4567")
        print(result.pii_detected)  # True
        print(result.pii_types_found)  # {"phone"}
    """

    def __init__(
        self,
        patterns: Optional[List[str]] = None,
        strategy: str = "hash",
        custom_patterns: Optional[Dict[str, re.Pattern]] = None,
        allowlist: Optional[Set[str]] = None,
    ):
        """
        Args:
            patterns: List of built-in pattern names to enable
                     (default: all built-in patterns)
            strategy: "mask", "hash", or "remove"
            custom_patterns: Additional regex patterns {name: compiled_regex}
            allowlist: Set of strings to never redact (e.g., known safe emails)
        """
        self.strategy_fn = STRATEGIES.get(strategy, hash_strategy)
        self.strategy_name = strategy
        self.allowlist = allowlist or set()

        # Build active pattern set
        self.patterns: Dict[str, re.Pattern] = {}
        if patterns:
            for name in patterns:
                if name in BUILTIN_PATTERNS:
                    self.patterns[name] = BUILTIN_PATTERNS[name]
        else:
            self.patterns = dict(BUILTIN_PATTERNS)

        if custom_patterns:
            self.patterns.update(custom_patterns)

    def redact(self, text: str) -> str:
        """
        Scan and redact PII from a text string.

        Returns the redacted string.
        """
        if not text or not isinstance(text, str):
            return text

        result = text
        for pii_type, pattern in self.patterns.items():
            def replacer(match):
                matched = match.group()
                if matched in self.allowlist:
                    return matched
                return self.strategy_fn(matched, pii_type)
            result = pattern.sub(replacer, result)

        return result

    def scan(self, text: str) -> RedactionResult:
        """
        Scan text for PII without modifying it.

        Returns a RedactionResult with detection details.
        """
        if not text or not isinstance(text, str):
            return RedactionResult(
                original_length=0, redacted_length=0,
                detections=[], pii_detected=False, pii_types_found=set()
            )

        detections = []
        types_found = set()

        for pii_type, pattern in self.patterns.items():
            for match in pattern.finditer(text):
                matched = match.group()
                if matched not in self.allowlist:
                    detections.append({
                        "type": pii_type,
                        "start": match.start(),
                        "end": match.end(),
                        "length": len(matched),
                    })
                    types_found.add(pii_type)

        redacted = self.redact(text) if detections else text
        return RedactionResult(
            original_length=len(text),
            redacted_length=len(redacted),
            detections=detections,
            pii_detected=len(detections) > 0,
            pii_types_found=types_found,
        )

    def redact_dict(self, data: Dict[str, Any], max_depth: int = 10) -> Dict[str, Any]:
        """
        Recursively redact PII from all string values in a dictionary.

        Handles nested dicts and lists. Safe for JSONB payloads.
        """
        return self._redact_recursive(data, depth=0, max_depth=max_depth)

    def _redact_recursive(self, obj: Any, depth: int, max_depth: int) -> Any:
        if depth > max_depth:
            return obj

        if isinstance(obj, str):
            return self.redact(obj)
        elif isinstance(obj, dict):
            return {k: self._redact_recursive(v, depth + 1, max_depth) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._redact_recursive(item, depth + 1, max_depth) for item in obj]
        else:
            return obj

    def scan_dict(self, data: Dict[str, Any]) -> RedactionResult:
        """
        Scan all string values in a dict for PII.

        Returns aggregated RedactionResult.
        """
        all_detections = []
        all_types = set()

        def walk(obj, path=""):
            if isinstance(obj, str):
                result = self.scan(obj)
                for d in result.detections:
                    d["field_path"] = path
                all_detections.extend(result.detections)
                all_types.update(result.pii_types_found)
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, f"{path}.{k}" if path else k)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    walk(item, f"{path}[{i}]")

        walk(data)
        return RedactionResult(
            original_length=0,
            redacted_length=0,
            detections=all_detections,
            pii_detected=len(all_detections) > 0,
            pii_types_found=all_types,
        )
