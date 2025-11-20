"""Coreference resolution for resolving pronouns and references."""

from typing import List, Dict, Optional, Tuple
import spacy

from src.util.logging import get_logger

logger = get_logger("preprocess.coref")

# Lazy load spaCy model with coreference
_nlp = None


def get_nlp():
    """Lazy load spaCy model with coreference resolution."""
    global _nlp
    if _nlp is None:
        try:
            # Try spacy-experimental coref first (better Python 3.11 support)
            import spacy_experimental
            _nlp = spacy.load("en_core_web_trf")
            _nlp.add_pipe("experimental_coref")
            logger.info("Loaded spaCy with experimental coref")
        except (ImportError, Exception) as e1:
            try:
                # Fallback: try neuralcoref (may have Python 3.11 issues)
                import neuralcoref
                _nlp = spacy.load("en_core_web_sm")
                neuralcoref.add_to_pipe(_nlp)
                logger.info("Loaded spaCy with neuralcoref for coreference resolution")
            except (ImportError, Exception) as e2:
                # Last resort: basic spaCy without coref
                try:
                    _nlp = spacy.load("en_core_web_trf")
                except OSError:
                    _nlp = spacy.load("en_core_web_lg")
                logger.warning(f"Coreference resolution not available (experimental: {e1}, neuralcoref: {e2}), using basic spaCy")
    return _nlp


def resolve_coreferences(text: str) -> str:
    """
    Resolve pronouns and references in text.
    
    Replaces pronouns (it, this, that, they, etc.) with their referents.
    
    Args:
        text: Input text with potential coreferences
        
    Returns:
        Text with resolved coreferences
    """
    if not text or not text.strip():
        return text
    
    try:
        nlp = get_nlp()
        doc = nlp(text)
        
        # Check if coreference resolution is available
        if hasattr(doc, '_') and hasattr(doc._, 'coref_clusters'):
            # Use neuralcoref clusters
            clusters = doc._.coref_clusters
            if clusters:
                # Replace pronouns with their main mentions
                resolved_text = text
                # Sort clusters by start position (reverse to replace from end)
                sorted_clusters = sorted(clusters, key=lambda c: c.main.start, reverse=True)
                
                for cluster in sorted_clusters:
                    main_mention = cluster.main.text
                    # Replace all mentions in cluster with main mention
                    for mention in cluster.mentions:
                        if mention != cluster.main:
                            # Replace the mention with the main mention
                            start = mention.start_char
                            end = mention.end_char
                            resolved_text = resolved_text[:start] + main_mention + resolved_text[end:]
                
                logger.debug(f"Resolved {len(clusters)} coreference clusters")
                return resolved_text
        
        # If no coreference resolution available, return original
        return text
        
    except Exception as e:
        logger.warning(f"Coreference resolution failed: {e}")
        return text


def resolve_pronouns_in_sentences(sentences: List[Tuple[str, any]]) -> List[Tuple[str, any]]:
    """
    Resolve pronouns across multiple sentences.
    
    This is more effective than single-sentence resolution as it can
    resolve references across sentence boundaries.
    
    Args:
        sentences: List of (sentence_text, span) tuples
        
    Returns:
        List of (resolved_sentence_text, span) tuples
    """
    if not sentences:
        return sentences
    
    # Join sentences for better cross-sentence resolution
    full_text = " ".join([sent[0] for sent in sentences])
    
    try:
        nlp = get_nlp()
        doc = nlp(full_text)
        
        # Check if coreference resolution is available
        if hasattr(doc, '_') and hasattr(doc._, 'coref_clusters'):
            clusters = doc._.coref_clusters
            if clusters:
                # Map character positions to resolved text
                resolved_text = full_text
                sorted_clusters = sorted(clusters, key=lambda c: c.main.start, reverse=True)
                
                for cluster in sorted_clusters:
                    main_mention = cluster.main.text
                    for mention in cluster.mentions:
                        if mention != cluster.main:
                            start = mention.start_char
                            end = mention.end_char
                            resolved_text = resolved_text[:start] + main_mention + resolved_text[end:]
                
                # Split back into sentences
                # Use original sentence boundaries
                resolved_sentences = []
                current_pos = 0
                
                for sent_text, span in sentences:
                    # Find this sentence in the resolved text
                    # Use approximate matching since positions may have shifted
                    sent_start = resolved_text.find(sent_text[:20], current_pos) if len(sent_text) > 20 else current_pos
                    sent_end = sent_start + len(sent_text)
                    
                    if sent_start >= 0 and sent_end <= len(resolved_text):
                        resolved_sent = resolved_text[sent_start:sent_end]
                        resolved_sentences.append((resolved_sent, span))
                        current_pos = sent_end
                    else:
                        # Fallback: use original
                        resolved_sentences.append((sent_text, span))
                
                logger.debug(f"Resolved coreferences across {len(sentences)} sentences")
                return resolved_sentences
        
        # If no coreference available, return original
        return sentences
        
    except Exception as e:
        logger.warning(f"Cross-sentence coreference resolution failed: {e}")
        return sentences


def get_pronoun_referents(text: str) -> Dict[str, str]:
    """
    Get mapping of pronouns to their referents.
    
    Args:
        text: Input text
        
    Returns:
        Dict mapping pronoun text to referent text
    """
    referents = {}
    
    try:
        nlp = get_nlp()
        doc = nlp(text)
        
        if hasattr(doc, '_') and hasattr(doc._, 'coref_clusters'):
            clusters = doc._.coref_clusters
            for cluster in clusters:
                main_mention = cluster.main.text
                for mention in cluster.mentions:
                    if mention != cluster.main:
                        # Check if mention is a pronoun
                        if mention.root.pos_ == "PRON":
                            referents[mention.text] = main_mention
        
        return referents
        
    except Exception as e:
        logger.warning(f"Failed to get pronoun referents: {e}")
        return referents

