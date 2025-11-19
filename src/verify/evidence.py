"""Evidence retrieval for verification."""

from typing import List, Dict, Any

from src.util.types import BlobInput, SentenceSpan
from src.util.logging import get_logger

logger = get_logger("verify.evidence")


def get_evidence_window(
    sentences: List[tuple],
    target_idx: int,
    window_size: int = 2
) -> List[str]:
    """
    Get surrounding sentences as evidence context.

    Args:
        sentences: List of (text, span) tuples
        target_idx: Index of target sentence
        window_size: Number of sentences before and after

    Returns:
        List of sentence texts in the window
    """
    start = max(0, target_idx - window_size)
    end = min(len(sentences), target_idx + window_size + 1)

    return [sent[0] for sent in sentences[start:end]]


def claim_from_fact(fact: Dict[str, Any]) -> str:
    """
    Generate a natural language claim from a fact for verification.

    Args:
        fact: Canonical fact dictionary

    Returns:
        Natural language claim string
    """
    subject = fact.get("subject", {})
    predicate = fact.get("predicate", {})
    obj = fact.get("object")
    obj_literal = fact.get("object_literal")
    qualifiers = fact.get("qualifiers", {})

    # Get surface forms
    subj_text = subject.get("surface", "Someone")
    pred_frame = predicate.get("frame", "does something")

    # Convert frame to verb form (simplified)
    verb = _frame_to_verb(pred_frame)

    # Build object part
    if obj:
        obj_text = obj.get("surface", "something")
    elif obj_literal:
        obj_text = str(obj_literal)
    else:
        obj_text = ""

    # Build qualifier parts
    qual_parts = []
    for key, val in qualifiers.items():
        if key == "instrument" and isinstance(val, dict):
            qual_parts.append(f"using {val.get('surface', val.get('qid', ''))}")
        elif key == "temperature" and isinstance(val, dict):
            qual_parts.append(f"at {val.get('value')} {val.get('unit', 'degrees')}")
        elif key == "location" and isinstance(val, dict):
            qual_parts.append(f"in {val.get('surface', val.get('qid', ''))}")
        elif key == "time_abs" and isinstance(val, dict):
            start = val.get("start", "")
            if start:
                qual_parts.append(f"at {start}")

    # Assemble claim
    claim_parts = [subj_text, verb]
    if obj_text:
        claim_parts.append(obj_text)
    if qual_parts:
        claim_parts.extend(qual_parts)

    claim = " ".join(claim_parts) + "."
    return claim


def _frame_to_verb(frame: str) -> str:
    """
    Convert a frame name to a simple verb form.

    Args:
        frame: Frame name (e.g., "Assemble", "Apply_heat")

    Returns:
        Verb string
    """
    frame_to_verb_map = {
        "Assemble": "assembles",
        "Apply_heat": "heats",
        "Measure_quantity": "measures",
        "Attribute": "is",
        "Possession": "has",
        "Located": "locates",
        "Placing": "places",
        "Removing": "removes",
        "Attaching": "attaches",
        "Using": "uses",
        "Building": "builds",
        "Creating": "creates",
        "Installing": "installs",
        "Adjusting": "adjusts",
        "Change_operational_state": "changes",
    }

    return frame_to_verb_map.get(frame, frame.lower() + "s")
