"""Type definitions for the video facts canonicalizer."""

from typing import TypedDict, Optional, List, Dict, Any
from dataclasses import dataclass, field


class BlobInput(TypedDict):
    """Input blob from JSONL."""
    blob_id: str
    video_id: str
    channel_id: str
    source: str  # "transcript" | "keyframe" | "narrative"
    text: str
    t_start: Optional[float]
    t_end: Optional[float]
    frames: Optional[List[str]]


class EntityRef(TypedDict, total=False):
    """Entity reference with optional QID or local ID."""
    qid: Optional[str]
    local_id: Optional[str]
    surface: str
    el_conf: float


class PredicateRef(TypedDict, total=False):
    """Predicate reference with frame and optional PID."""
    frame: str
    sense: Optional[str]
    pid: Optional[str]


class Evidence(TypedDict, total=False):
    """Evidence linking fact to source."""
    blob_id: str
    sent_id: str
    char_span: List[int]
    frames: Optional[List[str]]


class Confidence(TypedDict, total=False):
    """Confidence scores for a fact."""
    el: float
    srl: float
    verify_support: float


class CanonicalFact(TypedDict, total=False):
    """Canonical fact output."""
    fact_id: str
    video_id: str
    channel_id: str
    subject: EntityRef
    predicate: PredicateRef
    object: Optional[EntityRef]
    object_literal: Optional[Any]
    qualifiers: Dict[str, Any]
    evidence: Evidence
    conf: Confidence
    canonical_string: str
    canonical_embedding: Optional[List[float]]
    t_start: Optional[float]
    t_end: Optional[float]


@dataclass
class ProtoFact:
    """Intermediate fact representation from SRL."""
    predicate_lemma: str
    A0: Optional[str] = None  # Agent/Subject
    A1: Optional[str] = None  # Patient/Object
    A2: Optional[str] = None  # Instrument/Beneficiary
    AM_LOC: Optional[str] = None  # Location
    AM_TMP: Optional[str] = None  # Temporal
    AM_MNR: Optional[str] = None  # Manner
    AM_PRP: Optional[str] = None  # Purpose
    raw_args: Dict[str, str] = field(default_factory=dict)


@dataclass
class SentenceSpan:
    """Sentence with character offsets."""
    text: str
    start: int
    end: int
    sent_idx: int


@dataclass
class SRLFrame:
    """SRL frame output."""
    predicate: str
    predicate_lemma: str
    arguments: Dict[str, str]
    confidence: float = 1.0
