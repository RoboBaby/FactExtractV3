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


def clean_argument_text(text: str) -> str:
    """
    Clean argument text by removing leading/trailing punctuation and normalizing.
    
    Args:
        text: Raw argument text
        
    Returns:
        Cleaned text
    """
    if not text:
        return ""
    
    # Remove leading/trailing punctuation except periods in abbreviations
    text = text.strip(".,!?;:")
    
    # Normalize whitespace
    text = " ".join(text.split())
    
    return text


def build_proto_fact(frame: SRLFrame, sent: str) -> ProtoFact:
    """
    Build a proto-fact from an SRL frame using dependency-based arguments.

    Maps SRL roles to standardized positions:
    - A0 (Agent) -> subject
    - A1 (Patient/Theme) -> object
    - A2+ and AM-* -> qualifiers/adjuncts

    Handles special cases:
    - Copula: "X is Y" -> subject=X, object=Y
    - Imperative: implicit "you" as subject
    - Passive voice: nsubjpass indicates passive construction
    - Complex noun phrases: already extracted by dependency parser

    Args:
        frame: SRL frame output (from dependency-based extraction)
        sent: Original sentence text

    Returns:
        ProtoFact with extracted arguments
    """
    args = frame.arguments

    proto = ProtoFact(
        predicate_lemma=frame.predicate_lemma.lower(),
        raw_args=args
    )

    # Extract core arguments and clean them
    proto.A0 = clean_argument_text(args.get("ARG0") or args.get("A0") or "")
    proto.A1 = clean_argument_text(args.get("ARG1") or args.get("A1") or "")
    proto.A2 = clean_argument_text(args.get("ARG2") or args.get("A2") or "")

    # Extract adjuncts
    proto.AM_LOC = clean_argument_text(args.get("ARGM-LOC") or args.get("AM-LOC") or "")
    proto.AM_TMP = clean_argument_text(args.get("ARGM-TMP") or args.get("AM-TMP") or "")
    proto.AM_MNR = clean_argument_text(args.get("ARGM-MNR") or args.get("AM-MNR") or "")
    proto.AM_PRP = clean_argument_text(args.get("ARGM-PRP") or args.get("AM-PRP") or "")

    # Handle special cases

    # Copula: "X is Y" pattern
    if proto.predicate_lemma in ("be", "become", "seem", "appear", "is", "are", "was", "were"):
        # For copulas, A1 is typically the complement/attribute
        # If we have A0 but no A1, try to find the complement
        if proto.A0 and not proto.A1:
            # Look for attribute complement after the verb
            words = sent.lower().split()
            pred_words = frame.predicate.lower().split()
            if pred_words:
                pred_idx = sent.lower().find(pred_words[0])
                if pred_idx >= 0:
                    # Get text after predicate
                    after_pred = sent[pred_idx + len(pred_words[0]):].strip()
                    # Remove leading "the", "a", etc.
                    after_pred = after_pred.lstrip("the a an ").strip()
                    if after_pred:
                        proto.A1 = clean_argument_text(after_pred.split(".")[0])

    # Imperative: implicit "you" as subject
    if not proto.A0 and proto.A1:
        # Check if sentence might be imperative (starts with verb)
        words = sent.strip().split()
        if words:
            first_word = words[0].lower().rstrip(".,!?")
            # Check if first word matches predicate or is imperative form
            if first_word == frame.predicate.lower() or first_word == frame.predicate_lemma:
                proto.A0 = "you"  # Implicit subject for imperative

    # Handle passive voice: if we have A1 but no A0, might be passive
    # (The dependency parser should handle this, but double-check)
    if proto.A1 and not proto.A0:
        # Check for passive indicators in sentence
        sent_lower = sent.lower()
        if any(marker in sent_lower for marker in [" was ", " were ", " is ", " are ", " been "]):
            # Might be passive, but we'll keep A1 as object
            pass

    # Validate argument boundaries - ensure they're reasonable
    # Arguments from dependency parsing should already be good, but clean up edge cases
    if proto.A0:
        # Remove any trailing verbs or prepositions that shouldn't be there
        proto.A0 = proto.A0.split()[0] if len(proto.A0.split()) == 1 else proto.A0
    
    if proto.A1:
        # Remove trailing prepositions that are part of other phrases
        a1_words = proto.A1.split()
        if len(a1_words) > 1 and a1_words[-1].lower() in ("with", "using", "by", "to", "for"):
            proto.A1 = " ".join(a1_words[:-1])

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
