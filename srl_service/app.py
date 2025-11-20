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
    
    Validates NP structure and limits to reasonable size.
    Excludes relative clauses (acl) and stops at sentence boundaries.
    
    Args:
        doc: spaCy Doc object
        head_token: Head token of the noun phrase
        
    Returns:
        Span object representing the noun phrase, or None if invalid
    """
    # Start with the head token
    start_idx = head_token.i
    end_idx = head_token.i + 1
    
    # Get sentence boundaries
    sent_start = head_token.sent.start
    sent_end = head_token.sent.end
    
    # Validate head token is a noun or pronoun
    if head_token.pos_ not in ("NOUN", "PROPN", "PRON"):
        # Not a valid NP head
        return None
    
    # Collect all tokens that are part of this noun phrase
    # Include: det, amod, compound, nummod, nmod (but NOT acl for relative clauses)
    # Exclude: verbs, sentence boundaries, punctuation
    def collect_np_tokens(token, visited=None, depth=0):
        if visited is None:
            visited = set()
        if token.i in visited or depth > 5:  # Limit recursion depth
            return []
        if token.i < sent_start or token.i >= sent_end:
            return []  # Stop at sentence boundaries
        visited.add(token.i)
        
        # Don't include verbs or other non-NP parts
        if token.pos_ in ("VERB", "AUX"):
            return []
        
        tokens = [token]
        for child in token.children:
            # Include: det, amod, compound, nummod, nmod (descriptive), possessive, case
            # Explicitly exclude: relcl (relative clauses), acl (clausal modifiers), appos (appositions), advcl
            if child.dep_ in ("det", "amod", "compound", "nummod", "nmod", "advmod", "poss", "case"):
                # Only include if it's within sentence and not a verb
                if child.i >= sent_start and child.i < sent_end and child.pos_ not in ("VERB", "AUX"):
                    tokens.extend(collect_np_tokens(child, visited, depth + 1))
        return tokens
    
    np_tokens = collect_np_tokens(head_token)
    if np_tokens:
        indices = [t.i for t in np_tokens]
        start_idx = min(indices)
        end_idx = max(indices) + 1
        
        # Limit to max 10 words (reasonable for proper NPs)
        if end_idx - start_idx > 10:
            # Take first 10 words from the NP
            end_idx = start_idx + 10
        
        # Ensure we're within sentence boundaries
        start_idx = max(start_idx, sent_start)
        end_idx = min(end_idx, sent_end)
        
        # Validate the span doesn't start or end with punctuation
        span = doc[start_idx:end_idx]
        if span.text.strip():
            # Remove leading/trailing punctuation
            text = span.text.strip()
            while text and text[0] in ".,!?;:()[]":
                start_idx += 1
                if start_idx >= end_idx:
                    return None
                text = text[1:].strip()
            while text and text[-1] in ".,!?;:()[]":
                end_idx -= 1
                if end_idx <= start_idx:
                    return None
                text = text[:-1].strip()
            
            if start_idx < end_idx:
                return doc[start_idx:end_idx]
    
    return None


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
            
            # Fix common lemmatization issues for be-verbs
            # Explicitly map common auxiliary forms to "be"
            be_forms = {"is", "am", "are", "was", "were", "'s", "'re", "'m", "been", "being", "ai"}
            if predicate_text.lower() in be_forms:
                predicate_lemma = "be"
            # Fix weird spaCy lemmatization where "is" -> "i"
            elif predicate_lemma == "i" and predicate_text.lower().startswith("i"):
                predicate_lemma = "be"
            elif predicate_lemma == "-pron-":
                 predicate_lemma = "be" # simplified assumption for be-verbs labeled as PRON
        
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


class Entity(BaseModel):
    text: str
    label: str
    start: int
    end: int


class PredictResponse(BaseModel):
    frames: List[SRLFrame]
    entities: List[Entity] = []


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
        return PredictResponse(frames=[], entities=[])
    
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
                std_args[key] = value
            
            frame = SRLFrame(
                predicate=frame_data["verb"],
                predicate_lemma=frame_data["lemma"],
                arguments=std_args,
                confidence=frame_data.get("confidence", 0.9)
            )
            frames.append(frame)
            
        # Extract entities
        entities = []
        for ent in doc.ents:
            entities.append(Entity(
                text=ent.text,
                label=ent.label_,
                start=ent.start_char,
                end=ent.end_char
            ))
        
        return PredictResponse(frames=frames, entities=entities)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SRL prediction failed: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
