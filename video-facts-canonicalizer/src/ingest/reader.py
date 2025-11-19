"""Read and parse input blob JSONL files."""

import json
from typing import Iterator, Optional
from pathlib import Path

from src.util.types import BlobInput
from src.util.logging import get_logger

logger = get_logger("ingest.reader")


def read_blobs(filepath: str) -> Iterator[BlobInput]:
    """
    Read blob JSONL file and yield BlobInput objects.

    Args:
        filepath: Path to JSONL file

    Yields:
        BlobInput dictionaries
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Blob file not found: {filepath}")

    logger.info(f"Reading blobs from {filepath}")
    line_num = 0

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line_num += 1
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                blob = validate_blob(data, line_num)
                if blob:
                    yield blob
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON at line {line_num}: {e}")
                continue

    logger.info(f"Finished reading {line_num} lines")


def validate_blob(data: dict, line_num: int) -> Optional[BlobInput]:
    """
    Validate and normalize a blob dictionary.

    Args:
        data: Raw dictionary from JSON
        line_num: Line number for error reporting

    Returns:
        Validated BlobInput or None if invalid
    """
    required_fields = ["blob_id", "video_id", "channel_id", "source", "text"]

    for field in required_fields:
        if field not in data:
            logger.warning(f"Line {line_num}: Missing required field '{field}'")
            return None

    # Normalize source type
    valid_sources = ["transcript", "keyframe", "narrative"]
    if data["source"] not in valid_sources:
        logger.warning(f"Line {line_num}: Invalid source '{data['source']}', expected one of {valid_sources}")
        return None

    # Build normalized blob
    blob: BlobInput = {
        "blob_id": str(data["blob_id"]),
        "video_id": str(data["video_id"]),
        "channel_id": str(data["channel_id"]),
        "source": data["source"],
        "text": str(data["text"]),
        "t_start": float(data["t_start"]) if data.get("t_start") is not None else None,
        "t_end": float(data["t_end"]) if data.get("t_end") is not None else None,
        "frames": data.get("frames"),
    }

    return blob


def read_blobs_batch(filepath: str, batch_size: int = 100) -> Iterator[list[BlobInput]]:
    """
    Read blobs in batches.

    Args:
        filepath: Path to JSONL file
        batch_size: Number of blobs per batch

    Yields:
        Lists of BlobInput dictionaries
    """
    batch = []
    for blob in read_blobs(filepath):
        batch.append(blob)
        if len(batch) >= batch_size:
            yield batch
            batch = []

    if batch:
        yield batch
