#!/usr/bin/env python3
"""
Script to generate synthetic test data for the video facts canonicalizer.

Usage:
    python scripts/generate_test_data.py --count 1
    python scripts/generate_test_data.py --count 5 --topic "drone assembly"
    python scripts/generate_test_data.py --count 10 --batch
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env file
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.data_generator import TestDataGenerator
from src.util.logging import setup_logging, get_logger

logger = get_logger("generate_test_data")


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic test data for video facts canonicalizer"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of narrative blobs to generate"
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help="Specific topic for generation (random if not specified)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration in seconds the narrative should cover"
    )
    parser.add_argument(
        "--style",
        type=str,
        default="instructional",
        choices=["instructional", "documentary", "tutorial", "review"],
        help="Style of the narrative"
    )
    parser.add_argument(
        "--challenging",
        action="store_true",
        help="Use challenging prompt that tests specific linguistic phenomena"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-20250514",
        help="Anthropic model to use"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="resources/generated_data",
        help="Output directory for generated data"
    )
    parser.add_argument(
        "--resource-id",
        type=int,
        default=None,
        help="Specific resource ID (auto-increments if not specified)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without calling API"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)

    if args.dry_run:
        logger.info("DRY RUN - No API calls will be made")
        logger.info(f"Would generate {args.count} blobs")
        logger.info(f"Topic: {args.topic or 'random'}")
        logger.info(f"Duration: {args.duration}s")
        logger.info(f"Style: {args.style}")
        logger.info(f"Model: {args.model}")
        logger.info(f"Output: {args.output_dir}")
        return

    # Initialize generator
    try:
        generator = TestDataGenerator(
            model=args.model,
            output_dir=args.output_dir
        )
    except ValueError as e:
        logger.error(f"Failed to initialize generator: {e}")
        logger.error("Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)

    # Generate data - save each blob incrementally
    logger.info(f"Generating {args.count} narrative blob(s)...")

    # Select prompt based on challenging flag
    prompt_name = "challenging_prompt" if args.challenging else "narrative_prompt"
    
    # Get topics for batch generation
    topics = [args.topic] if args.topic else None
    if topics is None:
        topics = generator._get_default_topics()
    
    saved_directories = []
    
    # Generate and save each blob individually
    for i in range(args.count):
        topic = topics[i % len(topics)]
        try:
            logger.info(f"Generating blob {i+1}/{args.count} (topic: {topic})...")
            
            # Generate single blob
            blob = generator.generate_narrative(
                topic=topic,
                duration_seconds=args.duration,
                style=args.style,
                prompt_name=prompt_name
            )
            
            # Save immediately to its own directory
            resource_dir = generator.save_single_blob(
                blob,
                resource_id=args.resource_id if args.resource_id and i == 0 else None
            )
            saved_directories.append(resource_dir)
            
            logger.info(f"✓ Saved blob {i+1}/{args.count} to {resource_dir}")
            
        except Exception as e:
            logger.error(f"Failed to generate blob {i+1}/{args.count}: {e}")

    # Print summary
    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)
    print(f"Generated: {len(saved_directories)} blob(s)")
    print(f"Saved to directories:")
    for i, dir_path in enumerate(saved_directories, 1):
        print(f"  {i}. {dir_path}")
    print("=" * 60)

    # Print first blob preview
    if saved_directories:
        first_dir = saved_directories[0]
        first_blob_file = first_dir / "blobs.jsonl"
        if first_blob_file.exists():
            import json
            with open(first_blob_file, "r") as f:
                first_blob = json.loads(f.readline())
            print("\nFirst blob preview:")
            print("-" * 60)
            text = first_blob.get("text", "")[:500]
            print(f"{text}...")
            print("-" * 60)


if __name__ == "__main__":
    main()
