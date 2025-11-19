"""Verification module for local NLI-based fact checking."""

from .evidence import get_evidence_window, claim_from_fact
from .nli import LocalVerifier

__all__ = [
    "get_evidence_window",
    "claim_from_fact",
    "LocalVerifier",
]
