"""SRL microservice using spaCy transformer pipeline with dependency parsing."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import spacy
from spacy import displacy

app = FastAPI(title="SRL Service", version="2.0.0")

# Lazy load spaCy model
_nlp = None


def get_nlp():
    """Lazy load the spaCy transformer model."""
    global _nlp
    if _nlp is None:
        try:
            # Try to load transformer model first (best accuracy)
            _nlp = spacy.load("en_core_web_trf")
        except OSError:
            try:
                # Fallback to large model
                _nlp = spacy.load("en_core_web_lg")
            except OSError:
                # Last resort: medium model
                _nlp = spacy.load("en_core_web_md")
    return _nlp


def extract_args_from_deps(doc, verb_token):
    """
    Extract SRL arguments from dependency tree.
    
    Args:
        doc: spaCy Doc object
        verb_token: Token that is the predicate verb
        
    Returns:
        Dict with ARG0, ARG1, ARG2, etc.
    """
    args = {}
    
    # Find subject (ARG0) - nsubj or nsubjpass for passive
    for child in verb_token.children:
        if child.dep_ in ("nsubj", "nsubjpass"):
            # Extract the full noun phrase
            arg0_span = extract_noun_phrase(doc, child)
            if arg0_span:
                args["ARG0"] = arg0_span.text
            break
    
    # Find direct object (ARG1) - dobj
    for child in verb_token.children:
        if child.dep_ == "dobj":
            arg1_span = extract_noun_phrase(doc, child)
            if arg1_span:
                args["ARG1"] = arg1_span.text
            break
    
    # Find indirect object or second object (ARG2) - dative, or second dobj
    for child in verb_token.children:
        if child.dep_ in ("dative", "pobj"):
            # Check if it's an instrument (with/using)
            if child.head.dep_ == "prep" and child.head.lemma_ in ("with", "using", "by"):
                arg2_span = extract_noun_phrase(doc, child)
                if arg2_span:
                    args["ARG2"] = arg2_span.text
            break
    
    # Find instrument via prepositional phrases (nmod:with, agent)
    for child in verb_token.children:
        if child.dep_ in ("prep", "agent"):
            # Check for "with" or "using" prepositions
            if child.lemma_ in ("with", "using", "by"):
                # Get the object of the preposition
                for prep_child in child.children:
                    if prep_child.dep_ == "pobj":
                        arg2_span = extract_noun_phrase(doc, prep_child)
                        if arg2_span and "ARG2" not in args:
                            args["ARG2"] = arg2_span.text
                        break
    
    # Find location (ARGM-LOC)
    for child in verb_token.children:
        if child.dep_ in ("prep",) and child.lemma_ in ("at", "in", "on", "near"):
            for prep_child in child.children:
                if prep_child.dep_ == "pobj":
                    loc_span = extract_noun_phrase(doc, prep_child)
                    if loc_span:
                        args["ARGM-LOC"] = loc_span.text
                    break
    
    # Find time (ARGM-TMP)
    for child in verb_token.children:
        if child.dep_ in ("prep", "npadvmod") and child.lemma_ in ("at", "before", "after", "during"):
            for prep_child in child.children:
                if prep_child.dep_ == "pobj":
                    tmp_span = extract_noun_phrase(doc, prep_child)
                    if tmp_span:
                        args["ARGM-TMP"] = tmp_span.text
                    break
    
    return args


def extract_noun_phrase(doc, head_token):
    """
    Extract complete noun phrase starting from head token.
    
    Args:
        doc: spaCy Doc object
        head_token: Head token of the noun phrase
        
    Returns:
        Span object representing the noun phrase
    """
    # Start with the head token
    start_idx = head_token.i
    end_idx = head_token.i + 1
    
    # Collect all tokens that are part of this noun phrase
    # Include: det, amod, compound, nmod, acl, etc.
    def collect_np_tokens(token, visited=None):
        if visited is None:
            visited = set()
        if token.i in visited:
            return
        visited.add(token.i)
        
        tokens = [token]
        for child in token.children:
            if child.dep_ in ("det", "amod", "compound", "nummod", "nmod", "acl", "advmod"):
                tokens.extend(collect_np_tokens(child, visited))
        return tokens
    
    np_tokens = collect_np_tokens(head_token)
    if np_tokens:
        indices = [t.i for t in np_tokens]
        start_idx = min(indices)
        end_idx = max(indices) + 1
    
    # Return span
    return doc[start_idx:end_idx]


def detect_phrasal_verb(doc, verb_token):
    """
    Detect if verb is part of a phrasal verb (e.g., "put together", "heat up").
    
    Args:
        doc: spaCy Doc object
        verb_token: Verb token
        
    Returns:
        Tuple of (is_phrasal, full_verb_text, full_lemma) or (False, None, None)
    """
    # Common phrasal verb particles
    particles = ["up", "down", "out", "in", "on", "off", "over", "under", "away", "back", "together", "apart"]
    
    # Check for particle in children or following tokens
    for child in verb_token.children:
        if child.dep_ == "prt" and child.text.lower() in particles:
            # Found phrasal verb
            full_verb = f"{verb_token.text} {child.text}"
            full_lemma = f"{verb_token.lemma_} {child.text}"
            return True, full_verb, full_lemma
    
    # Check for light verb constructions (e.g., "make a decision", "take a break")
    # These have a direct object that's a noun derived from a verb
    for child in verb_token.children:
        if child.dep_ == "dobj":
            # Check if object is a deverbal noun
            if child.tag_ in ("NN", "NNS") and any(suffix in child.lemma_ for suffix in ["tion", "ment", "ing"]):
                # Light verb construction
                full_verb = f"{verb_token.text} {child.text}"
                full_lemma = f"{verb_token.lemma_} {child.lemma_}"
                return True, full_verb, full_lemma
    
    return False, None, None


def extract_srl_frames(doc):
    """
    Extract SRL frames from spaCy document using dependency parsing.
    
    Handles:
    - Regular verbs
    - Phrasal verbs (put together, heat up)
    - Light verb constructions (make a decision)
    
    Args:
        doc: spaCy Doc object
        
    Returns:
        List of frame dictionaries
    """
    frames = []
    
    # Find all verbs (potential predicates)
    verbs = [token for token in doc if token.pos_ == "VERB" or token.tag_.startswith("VB")]
    
    processed_indices = set()  # Track processed tokens to avoid duplicates
    
    for verb_token in verbs:
        # Skip if already processed as part of a phrasal verb
        if verb_token.i in processed_indices:
            continue
        
        # Skip auxiliary verbs unless they're the main verb
        if verb_token.dep_ == "aux" and verb_token.head.pos_ == "VERB":
            continue
        
        # Check for phrasal verbs or light verb constructions
        is_phrasal, full_verb, full_lemma = detect_phrasal_verb(doc, verb_token)
        
        if is_phrasal:
            # Use the full phrasal verb as predicate
            predicate_text = full_verb
            predicate_lemma = full_lemma
            # Mark particle as processed
            for child in verb_token.children:
                if child.dep_ == "prt":
                    processed_indices.add(child.i)
        else:
            predicate_text = verb_token.text
            predicate_lemma = verb_token.lemma_.lower()
        
        # Extract arguments using dependency tree
        args = extract_args_from_deps(doc, verb_token)
        
        # Only create frame if we have at least a subject or object
        if args or verb_token.dep_ != "aux":
            # Create frame
            frame = {
                "verb": predicate_text,
                "verb_idx": verb_token.i,
                "lemma": predicate_lemma,
                "arguments": args,
                "confidence": 0.9  # High confidence for dependency-based extraction
            }
            frames.append(frame)
    
    return frames


class PredictRequest(BaseModel):
    text: str


class SRLFrame(BaseModel):
    predicate: str
    predicate_lemma: str
    arguments: Dict[str, str]
    confidence: float = 1.0


class PredictResponse(BaseModel):
    frames: List[SRLFrame]


@app.get("/health")
def health():
    """Health check endpoint."""
    try:
        nlp = get_nlp()
        return {"status": "healthy", "model": nlp.meta.get("name", "unknown")}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest):
    """
    Run SRL prediction on input text using spaCy dependency parsing.
    
    Returns list of frames with predicate and arguments.
    """
    if not request.text.strip():
        return PredictResponse(frames=[])
    
    try:
        nlp = get_nlp()
        doc = nlp(request.text)
        
        # Extract SRL frames
        frames_data = extract_srl_frames(doc)
        
        # Convert to response format
        frames = []
        for frame_data in frames_data:
            # Convert arguments to standard format
            std_args = {}
            for key, value in frame_data["arguments"].items():
                if key == "ARG0":
                    std_args["ARG0"] = value
                elif key == "ARG1":
                    std_args["ARG1"] = value
                elif key == "ARG2":
                    std_args["ARG2"] = value
                elif key == "ARGM-LOC":
                    std_args["ARGM-LOC"] = value
                elif key == "ARGM-TMP":
                    std_args["ARGM-TMP"] = value
                elif key == "ARGM-MNR":
                    std_args["ARGM-MNR"] = value
            
            frame = SRLFrame(
                predicate=frame_data["verb"],
                predicate_lemma=frame_data["lemma"],
                arguments=std_args,
                confidence=frame_data.get("confidence", 0.9)
            )
            frames.append(frame)
        
        return PredictResponse(frames=frames)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SRL prediction failed: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
