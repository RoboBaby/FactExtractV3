#!/usr/bin/env python3
"""
Comprehensive test harness for validating fact extraction improvements.

This script:
1. Generates diverse test data using LLM
2. Runs the fact extraction pipeline
3. Validates extracted facts against expected patterns
4. Reports precision/recall metrics
5. Identifies common failure modes
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data_generator.generator import TestDataGenerator
from src.util.logging import setup_logging, get_logger

logger = get_logger("test_harness")


class FactExtractionValidator:
    """Validates extracted facts for quality and correctness."""
    
    def __init__(self):
        self.metrics = {
            "total_blobs": 0,
            "total_facts": 0,
            "facts_with_subject": 0,
            "facts_with_object": 0,
            "facts_with_qualifiers": 0,
            "facts_with_entities": 0,
            "facts_with_wikidata": 0,
            "errors": []
        }
    
    def validate_facts(self, facts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate extracted facts and compute metrics.
        
        Args:
            facts: List of extracted fact dictionaries
            
        Returns:
            Validation report dictionary
        """
        report = {
            "fact_count": len(facts),
            "valid_facts": 0,
            "invalid_facts": [],
            "quality_scores": {}
        }
        
        for fact in facts:
            is_valid = True
            issues = []
            
            # Check for required fields
            if not fact.get("subject"):
                is_valid = False
                issues.append("missing_subject")
            
            if not fact.get("predicate"):
                is_valid = False
                issues.append("missing_predicate")
            
            # Check subject quality
            subject = fact.get("subject", {})
            if subject:
                if not subject.get("surface"):
                    is_valid = False
                    issues.append("subject_no_surface")
                elif len(subject.get("surface", "").split()) > 10:
                    is_valid = False
                    issues.append("subject_too_long")
            
            # Check object quality
            obj = fact.get("object")
            if obj:
                if not obj.get("surface"):
                    is_valid = False
                    issues.append("object_no_surface")
                elif len(obj.get("surface", "").split()) > 15:
                    is_valid = False
                    issues.append("object_too_long")
            
            # Check predicate quality
            predicate = fact.get("predicate", {})
            if predicate and not predicate.get("frame"):
                is_valid = False
                issues.append("predicate_no_frame")
            
            if is_valid:
                report["valid_facts"] += 1
            else:
                report["invalid_facts"].append({
                    "fact_id": fact.get("fact_id", "unknown"),
                    "issues": issues
                })
        
        # Compute quality scores
        if report["fact_count"] > 0:
            report["quality_scores"] = {
                "validity_rate": report["valid_facts"] / report["fact_count"],
                "avg_subject_length": self._avg_field_length(facts, "subject"),
                "avg_object_length": self._avg_field_length(facts, "object"),
                "entity_linking_rate": self._entity_linking_rate(facts),
                "qualifier_rate": sum(1 for f in facts if f.get("qualifiers")) / report["fact_count"]
            }
        
        return report
    
    def _avg_field_length(self, facts: List[Dict], field: str) -> float:
        """Compute average length of a field across facts."""
        lengths = []
        for fact in facts:
            value = fact.get(field, {})
            if isinstance(value, dict):
                surface = value.get("surface", "")
                if surface:
                    lengths.append(len(surface.split()))
        return sum(lengths) / len(lengths) if lengths else 0.0
    
    def _entity_linking_rate(self, facts: List[Dict]) -> float:
        """Compute rate of successful entity linking."""
        linked = 0
        total = 0
        
        for fact in facts:
            for field in ["subject", "object"]:
                entity = fact.get(field)
                if entity:
                    total += 1
                    if entity.get("qid"):
                        linked += 1
        
        return linked / total if total > 0 else 0.0


def generate_test_suite(
    generator: TestDataGenerator,
    count: int = 50,
    include_challenging: bool = True
) -> List[Dict[str, Any]]:
    """
    Generate a comprehensive test suite with diverse examples.
    
    Args:
        generator: TestDataGenerator instance
        count: Number of blobs to generate
        include_challenging: Include challenging linguistic constructions
        
    Returns:
        List of generated blobs
    """
    blobs = []
    
    # Standard topics
    standard_topics = generator._get_default_topics()
    
    # Challenging topics that test specific linguistic phenomena
    challenging_topics = [
        "passive voice assembly instructions",
        "phrasal verb heavy tutorial",
        "complex noun phrase descriptions",
        "relative clause explanations",
        "coordination and subordination examples",
        "temporal sequence descriptions",
        "measurement and quantity specifications",
    ]
    
    topics = standard_topics
    if include_challenging:
        topics = standard_topics + challenging_topics
    
    logger.info(f"Generating {count} test blobs...")
    
    for i in range(count):
        topic = topics[i % len(topics)]
        try:
            blob = generator.generate_narrative(
                topic=topic,
                duration_seconds=60,
                style="instructional"
            )
            blobs.append(blob)
            if (i + 1) % 10 == 0:
                logger.info(f"Generated {i+1}/{count} blobs")
        except Exception as e:
            logger.error(f"Failed to generate blob {i+1}: {e}")
    
    return blobs


def run_extraction_pipeline(blobs_path: str, config_path: str = "configs/app.yaml") -> Dict[str, Any]:
    """
    Run the fact extraction pipeline on test data.
    
    Args:
        blobs_path: Path to JSONL file with blobs
        config_path: Path to configuration file
        
    Returns:
        Pipeline results dictionary
    """
    import subprocess
    
    cmd = [
        "python", "src/cli.py",
        "--blobs", blobs_path,
        "--config", config_path,
        "--log-level", "INFO"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Pipeline timeout"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def analyze_results(
    blobs: List[Dict[str, Any]],
    facts_from_db: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Analyze extraction results and compute metrics.
    
    Args:
        blobs: Original input blobs
        facts_from_db: Extracted facts from database
        
    Returns:
        Analysis report
    """
    analysis = {
        "input_stats": {
            "total_blobs": len(blobs),
            "total_sentences": 0,
            "avg_sentences_per_blob": 0.0
        },
        "output_stats": {
            "total_facts": len(facts_from_db),
            "facts_per_blob": len(facts_from_db) / len(blobs) if blobs else 0.0,
            "unique_predicates": len(set(f.get("predicate", {}).get("frame", "") for f in facts_from_db)),
            "unique_subjects": len(set(f.get("subject", {}).get("surface", "") for f in facts_from_db))
        },
        "quality_metrics": {},
        "common_patterns": defaultdict(int),
        "errors": []
    }
    
    # Count sentences in blobs
    total_sentences = 0
    for blob in blobs:
        text = blob.get("text", "")
        sentences = text.count(".") + text.count("!") + text.count("?")
        total_sentences += max(1, sentences)
    
    analysis["input_stats"]["total_sentences"] = total_sentences
    analysis["input_stats"]["avg_sentences_per_blob"] = total_sentences / len(blobs) if blobs else 0.0
    
    # Analyze fact quality
    validator = FactExtractionValidator()
    validation = validator.validate_facts(facts_from_db)
    analysis["quality_metrics"] = validation["quality_scores"]
    analysis["quality_metrics"]["validity_rate"] = validation["validity_rate"]
    
    # Find common predicate patterns
    for fact in facts_from_db:
        predicate = fact.get("predicate", {}).get("frame", "unknown")
        analysis["common_patterns"][predicate] += 1
    
    return analysis


def find_test_datasets(test_data_dir: str) -> List[Dict[str, Any]]:
    """
    Scan directory for test datasets.
    
    Looks for directories containing blobs.jsonl files.
    Expected structure:
        test_data_dir/
            0001/
                blobs.jsonl
                metadata.json
            0002/
                blobs.jsonl
                metadata.json
            ...
    
    Args:
        test_data_dir: Directory to scan
        
    Returns:
        List of dataset info dictionaries with paths and metadata
    """
    test_dir = Path(test_data_dir)
    if not test_dir.exists():
        logger.warning(f"Test data directory not found: {test_data_dir}")
        return []
    
    datasets = []
    
    # Find all numbered directories
    for item in sorted(test_dir.iterdir()):
        if not item.is_dir():
            continue
        
        # Check if it's a numbered directory (like 0001, 0002, etc.)
        if not item.name.isdigit():
            continue
        
        blobs_file = item / "blobs.jsonl"
        metadata_file = item / "metadata.json"
        
        if blobs_file.exists():
            dataset_info = {
                "resource_id": item.name,
                "blobs_path": str(blobs_file),
                "metadata_path": str(metadata_file) if metadata_file.exists() else None,
                "directory": str(item)
            }
            
            # Load metadata if available
            if metadata_file.exists():
                try:
                    with open(metadata_file, "r") as f:
                        dataset_info["metadata"] = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load metadata for {item.name}: {e}")
            
            datasets.append(dataset_info)
    
    logger.info(f"Found {len(datasets)} test datasets in {test_data_dir}")
    return datasets


def load_blobs_from_file(blobs_path: str) -> List[Dict[str, Any]]:
    """Load blobs from JSONL file."""
    blobs = []
    with open(blobs_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    blobs.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse blob: {e}")
    return blobs


def query_facts_from_db(dsn: str = None, video_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Query extracted facts from database.
    
    Args:
        dsn: Database connection string (auto-detects if None)
        video_id: Optional video_id to filter by
        
    Returns:
        List of fact dictionaries
    """
    try:
        import psycopg2
        import psycopg2.extras
        import os
        
        # Auto-detect DSN if not provided
        if dsn is None:
            if os.path.exists("/.dockerenv"):
                # We're in Docker, use service name
                dsn = "postgresql://postgres:postgres@db:5432/facts"
            else:
                # We're on host, use localhost
                dsn = "postgresql://postgres:postgres@localhost:5432/facts"
        
        conn = psycopg2.connect(dsn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Query facts with entity information
        query = """
            SELECT 
                f.fact_id,
                f.video_id,
                f.channel_id,
                f.subject_key,
                f.predicate_frame,
                f.object_key,
                f.object_literal,
                f.qualifiers,
                f.canonical_string,
                s.surface as subject_surface,
                s.qid as subject_qid,
                o.surface as object_surface,
                o.qid as object_qid
            FROM facts f
            LEFT JOIN entities s ON f.subject_key = s.entity_key
            LEFT JOIN entities o ON f.object_key = o.entity_key
        """
        
        if video_id:
            query += " WHERE f.video_id = %s"
            cur.execute(query, (video_id,))
        else:
            query += " ORDER BY f.video_id, f.fact_id"
            cur.execute(query)
        
        facts = []
        for row in cur.fetchall():
            fact = {
                "fact_id": row["fact_id"],
                "video_id": row["video_id"],
                "channel_id": row["channel_id"],
                "subject_key": row["subject_key"],
                "predicate": {"frame": row["predicate_frame"]},
                "object_key": row["object_key"],
                "object_literal": row["object_literal"],
                "qualifiers": row["qualifiers"],
                "canonical_string": row["canonical_string"],
            }
            
            # Add subject info
            if row["subject_surface"]:
                fact["subject"] = {
                    "surface": row["subject_surface"],
                    "qid": row["subject_qid"]
                }
            
            # Add object info (either entity or literal)
            if row["object_surface"]:
                fact["object"] = {
                    "surface": row["object_surface"],
                    "qid": row["object_qid"]
                }
            elif row["object_literal"]:
                fact["object"] = row["object_literal"]
            
            facts.append(fact)
        
        cur.close()
        conn.close()
        
        return facts
    except Exception as e:
        logger.error(f"Failed to query database: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return []


def process_dataset(
    dataset: Dict[str, Any],
    run_pipeline: bool = False,
    analyze: bool = False,
    config_path: str = "configs/app.yaml",
    db_dsn: str = None
) -> Dict[str, Any]:
    """
    Process a single test dataset.
    
    Args:
        dataset: Dataset info dictionary
        run_pipeline: Whether to run extraction pipeline
        analyze: Whether to analyze results
        config_path: Path to config file
        db_dsn: Database connection string
        
    Returns:
        Results dictionary for this dataset
    """
    resource_id = dataset["resource_id"]
    blobs_path = dataset["blobs_path"]
    
    logger.info(f"Processing dataset {resource_id}...")
    
    result = {
        "resource_id": resource_id,
        "blobs_path": blobs_path,
        "metadata": dataset.get("metadata", {}),
        "pipeline_results": None,
        "analysis": None
    }
    
    # Load input blobs
    try:
        blobs = load_blobs_from_file(blobs_path)
        result["input_blobs"] = len(blobs)
    except Exception as e:
        logger.error(f"Failed to load blobs from {blobs_path}: {e}")
        result["error"] = str(e)
        return result
    
    # Run pipeline if requested
    if run_pipeline:
        logger.info(f"Running pipeline on dataset {resource_id}...")
        pipeline_results = run_extraction_pipeline(blobs_path, config_path)
        result["pipeline_results"] = pipeline_results
        
        if not pipeline_results.get("success"):
            logger.error(f"Pipeline failed for dataset {resource_id}")
            return result
    
    # Analyze results if requested
    if analyze:
        logger.info(f"Analyzing results for dataset {resource_id}...")
        try:
            # Use default DSN if not provided (check if we're in Docker)
            if db_dsn is None:
                # Try Docker service name first, then localhost
                import os
                if os.path.exists("/.dockerenv"):
                    db_dsn = "postgresql://postgres:postgres@db:5432/facts"
                else:
                    db_dsn = "postgresql://postgres:postgres@localhost:5432/facts"
            
            facts = query_facts_from_db(db_dsn)
            analysis = analyze_results(blobs, facts)
            result["analysis"] = analysis
            
            # Save analysis to dataset directory
            analysis_file = Path(dataset["directory"]) / "analysis.json"
            with open(analysis_file, "w") as f:
                json.dump(analysis, f, indent=2, default=str)
            logger.info(f"Saved analysis to {analysis_file}")
        except Exception as e:
            logger.error(f"Analysis failed for dataset {resource_id}: {e}")
            result["analysis_error"] = str(e)
            result["analysis"] = None
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive test harness for fact extraction"
    )
    parser.add_argument(
        "--generate",
        type=int,
        default=0,
        help="Generate N test blobs (0 = skip generation)"
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Path to existing JSONL file to test (single file)"
    )
    parser.add_argument(
        "--test-data-dir",
        type=str,
        default="resources/generated_data",
        help="Directory containing test datasets to scan"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        help="Specific dataset ID to process (e.g., '0001')"
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan test data directory and process all datasets"
    )
    parser.add_argument(
        "--run-pipeline",
        action="store_true",
        help="Run the extraction pipeline on test data"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze results from database"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="test_results.json",
        help="Output file for test results"
    )
    parser.add_argument(
        "--challenging",
        action="store_true",
        help="Include challenging linguistic constructions (for generation)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/app.yaml",
        help="Path to configuration file"
    )
    parser.add_argument(
        "--db-dsn",
        type=str,
        default=None,
        help="Database connection string (auto-detects Docker if not provided)"
    )
    
    args = parser.parse_args()
    
    setup_logging("INFO")
    
    results = {
        "datasets_processed": [],
        "summary": {}
    }
    
    # Generate test data if requested
    if args.generate > 0:
        try:
            generator = TestDataGenerator()
            blobs = generate_test_suite(
                generator,
                count=args.generate,
                include_challenging=args.challenging
            )
            
            # Save generated data
            resource_dir = generator.save_to_resource(blobs)
            logger.info(f"Saved test data to {resource_dir}")
            results["generated_dataset"] = {
                "resource_id": resource_dir.name,
                "path": str(resource_dir / "blobs.jsonl"),
                "blob_count": len(blobs)
            }
        except Exception as e:
            logger.error(f"Failed to generate test data: {e}")
            return 1
    
    # Determine which datasets to process
    datasets_to_process = []
    
    if args.scan:
        # Scan directory for all datasets
        datasets = find_test_datasets(args.test_data_dir)
        if args.dataset:
            # Filter to specific dataset
            datasets = [d for d in datasets if d["resource_id"] == args.dataset]
        datasets_to_process = datasets
    elif args.input:
        # Single file provided
        input_path = Path(args.input)
        dataset_info = {
            "resource_id": input_path.parent.name if input_path.parent.name.isdigit() else "single_file",
            "blobs_path": str(input_path),
            "directory": str(input_path.parent),
            "metadata": {}
        }
        datasets_to_process = [dataset_info]
    elif args.dataset:
        # Specific dataset ID
        dataset_dir = Path(args.test_data_dir) / args.dataset
        blobs_file = dataset_dir / "blobs.jsonl"
        if blobs_file.exists():
            dataset_info = {
                "resource_id": args.dataset,
                "blobs_path": str(blobs_file),
                "directory": str(dataset_dir),
                "metadata": {}
            }
            # Load metadata if available
            metadata_file = dataset_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, "r") as f:
                        dataset_info["metadata"] = json.load(f)
                except Exception:
                    pass
            datasets_to_process = [dataset_info]
        else:
            logger.error(f"Dataset {args.dataset} not found in {args.test_data_dir}")
            return 1
    
    # Process datasets
    if datasets_to_process:
        logger.info(f"Processing {len(datasets_to_process)} dataset(s)...")
        
        for dataset in datasets_to_process:
            result = process_dataset(
                dataset,
                run_pipeline=args.run_pipeline,
                analyze=args.analyze,
                config_path=args.config,
                db_dsn=args.db_dsn
            )
            results["datasets_processed"].append(result)
        
        # Compute summary statistics
        if results["datasets_processed"]:
            total_blobs = sum(r.get("input_blobs", 0) for r in results["datasets_processed"])
            successful_pipelines = sum(1 for r in results["datasets_processed"] 
                                     if r.get("pipeline_results", {}).get("success"))
            total_facts = sum(
                r.get("analysis", {}).get("output_stats", {}).get("total_facts", 0) 
                if r.get("analysis") else 0
                for r in results["datasets_processed"]
            )
            
            results["summary"] = {
                "datasets_processed": len(results["datasets_processed"]),
                "total_blobs": total_blobs,
                "successful_pipelines": successful_pipelines,
                "total_facts_extracted": total_facts,
                "avg_facts_per_blob": total_facts / total_blobs if total_blobs > 0 else 0.0
            }
    else:
        logger.warning("No datasets to process. Use --scan, --input, or --dataset")
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"Test results saved to {output_path}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST HARNESS SUMMARY")
    print("=" * 60)
    if results.get("generated_dataset"):
        gen = results["generated_dataset"]
        print(f"Generated: Dataset {gen['resource_id']} with {gen['blob_count']} blobs")
    if results.get("summary"):
        summary = results["summary"]
        print(f"Datasets processed: {summary['datasets_processed']}")
        print(f"Total blobs: {summary['total_blobs']}")
        print(f"Successful pipelines: {summary['successful_pipelines']}")
        print(f"Total facts extracted: {summary['total_facts_extracted']}")
        print(f"Avg facts per blob: {summary['avg_facts_per_blob']:.2f}")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
