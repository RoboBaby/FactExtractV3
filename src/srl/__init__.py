"""SRL module for semantic role labeling."""

from .client import srl_predict, build_proto_fact, extract_mentions_from_proto

__all__ = ["srl_predict", "build_proto_fact", "extract_mentions_from_proto"]
