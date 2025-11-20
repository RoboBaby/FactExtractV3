"""SRL client for calling local SRL pipeline or microservice."""

import requests
from typing import List, Dict, Optional, Tuple, Any

from src.util.types import SRLFrame, ProtoFact
from src.util.logging import get_logger

logger = get_logger("srl.client")

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


def validate_noun_phrase(text: str, max_words: int = 10, role: str = "argument") -> Optional[str]:
    """
    Validate that text is a reasonable noun phrase.
    
    Args:
        text: Text to validate
        max_words: Maximum number of words allowed
        role: Role name for logging
        
    Returns:
        Validated text or None if invalid
    """
    if not text:
        return None
    
    words = text.split()
    
    # Check word limit
    if len(words) > max_words:
        logger.debug(f"{role} too long ({len(words)} words, max {max_words}): {text[:50]}...")
        return None
    
    # Check for sentence-initial fragments (common issue)
    sentence_fragments = [
        "alright", "okay", "ok", "first", "second", "third", "next", "then", 
        "now", "finally", "after", "before", "while", "when", "if", "because",
        "so", "let", "let's", "let'", "let'", "welcome", "here", "there"
    ]
    
    first_word_lower = words[0].lower().rstrip(".,!?;:")
    if first_word_lower in sentence_fragments:
        # This is likely a sentence fragment, not a proper NP
        logger.debug(f"{role} starts with sentence fragment '{first_word_lower}': {text[:50]}...")
        return None
    
    # Check that it doesn't start with a verb (common mistake)
    # Simple heuristic: if first word ends in -ing, -ed, -s (could be verb)
    first_word = words[0].lower()
    if any(first_word.endswith(suffix) for suffix in ["ing", "ed", "s", "es"]) and len(words) == 1:
        # Might be a verb, but could also be a noun - be lenient for single words
        pass
    
    # Check for trailing verbs (shouldn't be in NP)
    last_word = words[-1].lower().rstrip(".,!?;:")
    verb_indicators = ["is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "have", "has", "had", "will", "would", "can", "could", "should", "may", "might"]
    if last_word in verb_indicators and len(words) > 1:
        # Remove trailing verb
        logger.debug(f"{role} ends with verb '{last_word}', removing: {text[:50]}...")
        return " ".join(words[:-1])
    
    # Check for standalone "I" mixed with other words (e.g., "Sarah I" -> invalid)
    if len(words) > 1 and any(w.lower().rstrip(".,!?;:") == "i" for w in words):
        # If "I" appears with other words, it's likely a parsing error
        # Keep only the non-"I" words
        filtered_words = [w for w in words if w.lower().rstrip(".,!?;:") != "i"]
        if filtered_words:
            logger.debug(f"{role} contains 'I' with other words, filtering: {text[:50]}...")
            return " ".join(filtered_words)
        else:
            # If only "I" remains, that's valid
            return "I"
    
    return text


def build_proto_fact(frame: SRLFrame, sent: str, entities: Optional[List[Dict[str, Any]]] = None) -> ProtoFact:
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
        entities: Optional list of entities from NER for argument snapping

    Returns:
        ProtoFact with extracted arguments
    """
    args = frame.arguments

    proto = ProtoFact(
        predicate_lemma=frame.predicate_lemma.lower(),
        raw_args=args
    )

    # Helper to snap argument to entity
    def snap_to_entity(arg_text: str, role_name: str) -> str:
        if not arg_text or not entities:
            return arg_text
            
        # Look for entities contained in the argument
        contained_entities = []
        for ent in entities:
            # Simple check: is entity text inside argument text?
            # And is it significant? (e.g. "Sarah" in "The girl named Sarah")
            if ent["surface"] in arg_text:
                contained_entities.append(ent)
        
        if not contained_entities:
            return arg_text
            
        # Sort by length (longest first) - prefer specific entities
        contained_entities.sort(key=lambda x: len(x["surface"]), reverse=True)
        best_ent = contained_entities[0]
        
        # Snap logic: if argument is much longer than entity (e.g. > 2x words or > 5 words difference)
        # But we must be careful not to lose context if the entity is just a modifier
        # E.g. "Sarah's car" -> don't snap to "Sarah"
        # E.g. "The battery connector that Sarah is installing" -> "Sarah" is NOT the head.
        # This relies on the fact that we already cleaned up relative clauses in srl_service
        # So we should be safer now.
        
        # If argument is significantly longer and contains a PERSON, ORG, GPE
        arg_words = arg_text.split()
        ent_words = best_ent["surface"].split()
        
        if len(arg_words) > len(ent_words) + 3 and best_ent.get("label") in ("PERSON", "ORG", "GPE"):
            # Check if the entity is likely the head (heuristic)
            # If the entity is at the start or end, it's a good candidate
            if arg_text.startswith(best_ent["surface"]) or arg_text.endswith(best_ent["surface"]):
                logger.debug(f"Snapping {role_name} '{arg_text}' to entity '{best_ent['surface']}'")
                return best_ent["surface"]
                
        return arg_text

    # Extract core arguments and clean them with validation
    arg0_raw = clean_argument_text(args.get("ARG0") or args.get("A0") or "")
    # Try to snap to entity first
    arg0_snapped = snap_to_entity(arg0_raw, "ARG0")
    proto.A0 = validate_noun_phrase(arg0_snapped, max_words=8, role="ARG0")
    
    arg1_raw = clean_argument_text(args.get("ARG1") or args.get("A1") or "")
    arg1_snapped = snap_to_entity(arg1_raw, "ARG1")
    proto.A1 = validate_noun_phrase(arg1_snapped, max_words=12, role="ARG1")
    
    arg2_raw = clean_argument_text(args.get("ARG2") or args.get("A2") or "")
    proto.A2 = validate_noun_phrase(arg2_raw, max_words=10, role="ARG2")

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

    # Additional validation and cleanup
    if proto.A0:
        # Final cleanup: remove any remaining sentence fragments
        a0_words = proto.A0.split()
        # Remove leading fragments if they somehow got through
        while a0_words and a0_words[0].lower().rstrip(".,!?;:") in ["alright", "okay", "first", "now", "let", "let's"]:
            a0_words = a0_words[1:]
        
        # Remove standalone "I" if it appears with other words (e.g., "Sarah I" -> "Sarah")
        if len(a0_words) > 1:
            a0_words = [w for w in a0_words if w.lower().rstrip(".,!?;:") != "i"]
        
        # Remove verbs that shouldn't be in NP
        verb_words = ["is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "have", "has", "had", "will", "would", "can", "could", "should", "may", "might"]
        a0_words = [w for w in a0_words if w.lower().rstrip(".,!?;:") not in verb_words]
        
        if a0_words:
            proto.A0 = " ".join(a0_words)
        else:
            proto.A0 = None
    
    if proto.A1:
        # Remove trailing prepositions that are part of other phrases
        a1_words = proto.A1.split()
        if len(a1_words) > 1 and a1_words[-1].lower().rstrip(".,!?;:") in ("with", "using", "by", "to", "for", "from", "in", "on", "at"):
            # Check if it's actually part of the NP or a separate phrase
            # If the preposition is followed by something in the original sentence, it's likely separate
            a1_words = a1_words[:-1]
        if a1_words:
            proto.A1 = " ".join(a1_words)
        else:
            proto.A1 = None

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
