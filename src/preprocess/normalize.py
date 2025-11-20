"""Text normalization and sentence splitting."""

import re
from typing import List, Tuple, Optional
import ftfy
import spacy

from src.util.types import BlobInput, SentenceSpan
from src.util.logging import get_logger

logger = get_logger("preprocess.normalize")

# Lazy load spaCy model for sentence segmentation
_nlp = None


def get_nlp():
    """Lazy load spaCy model for sentence segmentation."""
    global _nlp
    if _nlp is None:
        try:
            # Try transformer model first (best accuracy)
            _nlp = spacy.load("en_core_web_trf")
        except OSError:
            try:
                # Fallback to large model
                _nlp = spacy.load("en_core_web_lg")
            except OSError:
                try:
                    # Fallback to medium model
                    _nlp = spacy.load("en_core_web_md")
                except OSError:
                    # Last resort: small model
                    _nlp = spacy.load("en_core_web_sm")
    return _nlp


def normalize_text(text: str) -> str:
    """
    Normalize text by fixing encoding issues and cleaning up whitespace.

    Args:
        text: Raw input text

    Returns:
        Normalized text
    """
    # Fix encoding issues
    text = ftfy.fix_text(text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    # Remove control characters except newlines
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    return text.strip()


def sentence_split(blob: BlobInput) -> List[Tuple[str, SentenceSpan]]:
    """
    Split blob text into sentences using spaCy's sentence segmenter.
    
    Uses NLP-aware sentence segmentation that handles:
    - Abbreviations (e.g., "Dr. Smith")
    - Decimals (e.g., "3.14")
    - Ellipses (e.g., "...")
    - Quoted sentences
    - Proper sentence boundaries

    Args:
        blob: Input blob

    Returns:
        List of (sentence_text, SentenceSpan) tuples with character offsets
    """
    text = normalize_text(blob["text"])
    
    if not text.strip():
        return []

    try:
        nlp = get_nlp()
        # Process text with spaCy
        # For sentence splitting only, we could disable parser/NER, but they're needed for SRL
        # So we keep them enabled
        doc = nlp(text)
        
        sentences = []
        sent_idx = 0
        
        for sent in doc.sents:
            sent_text = sent.text.strip()
            if not sent_text:
                continue
            
            # Get character offsets from spaCy span
            start_char = sent.start_char
            end_char = sent.end_char
            
            # Create sentence span
            span = SentenceSpan(
                text=sent_text,
                start=start_char,
                end=end_char,
                sent_idx=sent_idx
            )
            
            sentences.append((sent_text, span))
            sent_idx += 1
        
        logger.debug(f"Split blob {blob['blob_id']} into {len(sentences)} sentences using spaCy")
        return sentences
        
    except Exception as e:
        logger.warning(f"spaCy sentence splitting failed: {e}, falling back to regex")
        # Fallback to regex-based splitting
        return _regex_sentence_split(blob, text)


def _regex_sentence_split(blob: BlobInput, text: str) -> List[Tuple[str, SentenceSpan]]:
    """
    Fallback regex-based sentence splitting.
    
    Args:
        blob: Input blob
        text: Normalized text
        
    Returns:
        List of (sentence_text, SentenceSpan) tuples
    """
    # Simple sentence boundary detection
    # Handles: period, question mark, exclamation followed by space or end
    sentence_pattern = r"(?<=[.!?])\s+(?=[A-Z])|(?<=[.!?])$"

    sentences = []
    current_pos = 0
    sent_idx = 0

    # Split on sentence boundaries
    parts = re.split(sentence_pattern, text)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Find the actual position in the normalized text
        start = text.find(part, current_pos)
        if start == -1:
            start = current_pos

        end = start + len(part)

        span = SentenceSpan(
            text=part,
            start=start,
            end=end,
            sent_idx=sent_idx
        )

        sentences.append((part, span))
        current_pos = end
        sent_idx += 1

    logger.debug(f"Split blob {blob['blob_id']} into {len(sentences)} sentences (regex fallback)")
    return sentences


def get_sentence_id(blob: BlobInput, span: SentenceSpan) -> str:
    """
    Generate a unique sentence ID.

    Args:
        blob: Source blob
        span: Sentence span

    Returns:
        Sentence ID string
    """
    return f"{blob['video_id']}:{blob['blob_id']}:s{span.sent_idx}"


def get_evidence_window(
    sentences: List[Tuple[str, SentenceSpan]],
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
