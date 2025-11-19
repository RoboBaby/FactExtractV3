"""Predicate canonicalization using FrameNet/VerbAtlas/PropBank mappings."""

import yaml
from pathlib import Path
from typing import Dict, Optional, Any

from src.util.types import PredicateRef
from src.util.logging import get_logger

logger = get_logger("canonicalize.predicates")


class PredicateMapper:
    """Maps predicate lemmas to canonical frames."""

    def __init__(self, predicate_map_path: str = "configs/predicate_map.yaml"):
        """
        Initialize predicate mapper.

        Args:
            predicate_map_path: Path to predicate mapping YAML file
        """
        self.map_path = Path(predicate_map_path)
        self._mapping: Dict[str, Dict[str, Any]] = {}
        self._load_mapping()

    def _load_mapping(self):
        """Load predicate mapping from YAML file."""
        if not self.map_path.exists():
            logger.warning(f"Predicate map not found at {self.map_path}, using empty mapping")
            return

        try:
            with open(self.map_path, "r", encoding="utf-8") as f:
                self._mapping = yaml.safe_load(f) or {}
            logger.info(f"Loaded {len(self._mapping)} predicate mappings")
        except Exception as e:
            logger.error(f"Failed to load predicate map: {e}")

    def map_predicate(self, lemma: str) -> PredicateRef:
        """
        Map a predicate lemma to its canonical frame.

        Args:
            lemma: Predicate lemma (lowercase)

        Returns:
            PredicateRef with frame, sense, and optional PID
        """
        lemma = lemma.lower().strip()

        if lemma in self._mapping:
            entry = self._mapping[lemma]
            return PredicateRef(
                frame=entry.get("frame", lemma.capitalize()),
                sense=entry.get("sense"),
                pid=entry.get("pid")
            )

        # Default: capitalize lemma as frame name
        logger.debug(f"No mapping for lemma '{lemma}', using default")
        return PredicateRef(
            frame=lemma.capitalize(),
            sense=f"{lemma}.01",
            pid=None
        )

    def get_frame_info(self, lemma: str) -> Optional[Dict[str, Any]]:
        """
        Get full frame information for a lemma.

        Args:
            lemma: Predicate lemma

        Returns:
            Full mapping entry or None
        """
        return self._mapping.get(lemma.lower())


# Global mapper instance
_mapper: Optional[PredicateMapper] = None


def get_predicate_mapper(config_path: str = "configs/predicate_map.yaml") -> PredicateMapper:
    """
    Get or create the global predicate mapper.

    Args:
        config_path: Path to predicate map YAML

    Returns:
        PredicateMapper instance
    """
    global _mapper
    if _mapper is None:
        _mapper = PredicateMapper(config_path)
    return _mapper


def map_predicate(lemma: str, config_path: str = "configs/predicate_map.yaml") -> PredicateRef:
    """
    Convenience function to map a predicate lemma.

    Args:
        lemma: Predicate lemma
        config_path: Path to predicate map YAML

    Returns:
        PredicateRef with canonical frame
    """
    mapper = get_predicate_mapper(config_path)
    return mapper.map_predicate(lemma)
