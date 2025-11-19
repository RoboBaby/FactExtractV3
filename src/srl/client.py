"""SRL client for calling local SRL pipeline or microservice."""

import requests
from typing import List, Dict, Optional

from src.util.types import SRLFrame, ProtoFact
from src.util.logging import get_logger

logger = get_logger("srl.client")


def srl_predict(endpoint: str, sent: str, timeout: int = 30) -> List[SRLFrame]:
    """
    Call SRL microservice to get predicate-argument structures.

    Expects SRL microservice with POST /predict { "text": "..." }
    Returns list of frames with props: predicate_lemma, arguments{A0, A1, ...}

    Args:
        endpoint: SRL service endpoint URL
        sent: Sentence text to analyze
        timeout: Request timeout in seconds

    Returns:
        List of SRLFrame objects
    """
    try:
        r = requests.post(endpoint, json={"text": sent}, timeout=timeout)
        r.raise_for_status()
        data = r.json()

        frames = []
        for frame_data in data.get("frames", []):
            frame = SRLFrame(
                predicate=frame_data.get("predicate", ""),
                predicate_lemma=frame_data.get("predicate_lemma", frame_data.get("predicate", "")),
                arguments=frame_data.get("arguments", {}),
                confidence=frame_data.get("confidence", 1.0)
            )
            frames.append(frame)

        logger.debug(f"SRL returned {len(frames)} frames for: {sent[:50]}...")
        return frames

    except requests.exceptions.Timeout:
        logger.error(f"SRL request timed out for: {sent[:50]}...")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"SRL request failed: {e}")
        return []
    except (KeyError, ValueError) as e:
        logger.error(f"Invalid SRL response format: {e}")
        return []


def build_proto_fact(frame: SRLFrame, sent: str) -> ProtoFact:
    """
    Build a proto-fact from an SRL frame.

    Maps SRL roles to standardized positions:
    - A0 (Agent) -> subject
    - A1 (Patient/Theme) -> object
    - A2+ and AM-* -> qualifiers/adjuncts

    Handles special cases:
    - Copula: "X is Y" -> subject=X, object=Y
    - Imperative: implicit "you" as subject

    Args:
        frame: SRL frame output
        sent: Original sentence text

    Returns:
        ProtoFact with extracted arguments
    """
    args = frame.arguments

    proto = ProtoFact(
        predicate_lemma=frame.predicate_lemma.lower(),
        raw_args=args
    )

    # Extract core arguments
    proto.A0 = args.get("ARG0") or args.get("A0")
    proto.A1 = args.get("ARG1") or args.get("A1")
    proto.A2 = args.get("ARG2") or args.get("A2")

    # Extract adjuncts
    proto.AM_LOC = args.get("ARGM-LOC") or args.get("AM-LOC")
    proto.AM_TMP = args.get("ARGM-TMP") or args.get("AM-TMP")
    proto.AM_MNR = args.get("ARGM-MNR") or args.get("AM-MNR")
    proto.AM_PRP = args.get("ARGM-PRP") or args.get("AM-PRP")

    # Handle special cases

    # Copula: "X is Y" pattern
    if proto.predicate_lemma in ("be", "become", "seem", "appear"):
        # For copulas, A1 is typically the complement
        if proto.A1 and not proto.A0:
            # Try to find subject from sentence structure
            pass  # Keep as is, will be handled downstream

    # Imperative: implicit "you" as subject
    if not proto.A0 and proto.A1:
        # Check if sentence might be imperative (starts with verb)
        words = sent.strip().split()
        if words and words[0].lower() == frame.predicate_lemma:
            proto.A0 = "you"  # Implicit subject for imperative

    # Handle instrument in A2 or with-phrase
    if proto.A2 and "with" in sent.lower():
        # A2 might be instrument; keep for qualifier extraction
        pass

    return proto


def extract_mentions_from_proto(proto: ProtoFact) -> List[Dict[str, str]]:
    """
    Extract entity mentions from proto-fact for entity linking.

    Args:
        proto: ProtoFact with extracted arguments

    Returns:
        List of mention dictionaries with 'surface' and 'role' keys
    """
    mentions = []

    if proto.A0:
        mentions.append({"surface": proto.A0, "role": "subject"})

    if proto.A1:
        mentions.append({"surface": proto.A1, "role": "object"})

    if proto.A2:
        mentions.append({"surface": proto.A2, "role": "instrument"})

    if proto.AM_LOC:
        mentions.append({"surface": proto.AM_LOC, "role": "location"})

    return mentions
