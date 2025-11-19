#!/usr/bin/env python3
"""
Script to generate synthetic test data for the video facts canonicalizer.

Usage:
    python scripts/generate_test_data.py --count 1
    python scripts/generate_test_data.py --count 5 --topic "drone assembly"
    python scripts/generate_test_data.py --count 10 --batch
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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

    # Generate data
    logger.info(f"Generating {args.count} narrative blob(s)...")

    if args.count == 1:
        # Single generation
        blob = generator.generate_narrative(
            topic=args.topic,
            duration_seconds=args.duration,
            style=args.style
        )
        blobs = [blob]
    else:
        # Batch generation
        topics = [args.topic] if args.topic else None
        blobs = generator.generate_batch(
            count=args.count,
            topics=topics,
            duration_seconds=args.duration,
            style=args.style
        )

    # Save to resource directory
    resource_dir = generator.save_to_resource(
        blobs,
        resource_id=args.resource_id
    )

    # Print summary
    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)
    print(f"Generated: {len(blobs)} blob(s)")
    print(f"Output: {resource_dir}")
    print(f"Blobs file: {resource_dir / 'blobs.jsonl'}")
    print("=" * 60)

    # Print first blob preview
    if blobs:
        print("\nFirst blob preview:")
        print("-" * 60)
        text = blobs[0].get("text", "")[:500]
        print(f"{text}...")
        print("-" * 60)


if __name__ == "__main__":
    main()
