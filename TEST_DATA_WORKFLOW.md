# Test Data Workflow

## Overview

Test data is now organized in a directory structure that allows you to:
1. **Generate** test datasets and save them
2. **Preserve** important test datasets for regression testing
3. **Scan** the directory to run tests on all saved datasets
4. **Track** results per dataset with analysis files

## Directory Structure

```
resources/generated_data/
  0001/
    blobs.jsonl          # Input test data
    metadata.json        # Generation info (topics, model, timestamp)
    analysis.json        # Test results (created by test harness)
  0002/
    blobs.jsonl
    metadata.json
    analysis.json
  ...
```

## Workflow

### Step 1: Generate Test Data

```bash
# Generate test data - automatically saved to numbered directory
python scripts/generate_test_data.py --count 20 --challenging

# Output: resources/generated_data/0002/
#   - blobs.jsonl (20 test blobs)
#   - metadata.json (generation metadata)
```

### Step 2: Run Tests on Saved Datasets

#### Option A: Test All Datasets
```bash
# Scan directory and process all datasets
python scripts/test_harness.py --scan --run-pipeline --analyze

# This will:
# - Find all datasets in resources/generated_data/
# - Run pipeline on each
# - Generate analysis.json in each dataset directory
# - Create test_results.json with summary
```

#### Option B: Test Specific Dataset
```bash
# Test a specific dataset
python scripts/test_harness.py --dataset 0002 --run-pipeline --analyze

# Output: resources/generated_data/0002/analysis.json
```

#### Option C: Test Single File
```bash
# Test a single JSONL file
python scripts/test_harness.py --input path/to/blobs.jsonl --run-pipeline --analyze
```

### Step 3: Review Results

```bash
# View summary
cat test_results.json | python -m json.tool

# View specific dataset analysis
cat resources/generated_data/0002/analysis.json | python -m json.tool
```

## Preserving Test Datasets

### Save Important Datasets

```bash
# Copy dataset to backup location
cp -r resources/generated_data/0002 /backup/test_datasets/baseline_001

# Or create a symlink
ln -s resources/generated_data/0002 /backup/test_datasets/baseline_001
```

### Archive Test Results

```bash
# Archive entire test run
tar -czf test_run_$(date +%Y%m%d).tar.gz \
  resources/generated_data/ \
  test_results.json
```

## Common Use Cases

### Regression Testing

```bash
# 1. Generate baseline test data
python scripts/generate_test_data.py --count 50 --challenging
# Saves to: resources/generated_data/0001/

# 2. Run baseline tests
python scripts/test_harness.py --dataset 0001 --run-pipeline --analyze
# Saves: resources/generated_data/0001/analysis.json

# 3. Make changes to pipeline...

# 4. Run same tests again
python scripts/test_harness.py --dataset 0001 --run-pipeline --analyze
# Compare new analysis.json with previous

# 5. Compare results
diff resources/generated_data/0001/analysis.json.old \
     resources/generated_data/0001/analysis.json
```

### Batch Testing

```bash
# Generate multiple test sets
python scripts/generate_test_data.py --count 10 --challenging
python scripts/generate_test_data.py --count 10  # standard
python scripts/generate_test_data.py --count 10 --challenging

# Run all at once
python scripts/test_harness.py --scan --run-pipeline --analyze
```

### Continuous Testing

```bash
# Generate new test data daily
python scripts/generate_test_data.py --count 20 --challenging

# Run tests on all datasets (including new ones)
python scripts/test_harness.py --scan --run-pipeline --analyze
```

## Test Harness Options

```bash
# Scan directory for all datasets
--scan

# Process specific dataset
--dataset 0001

# Process single file
--input path/to/blobs.jsonl

# Run extraction pipeline
--run-pipeline

# Analyze results from database
--analyze

# Custom test data directory
--test-data-dir /path/to/test/data

# Custom database connection
--db-dsn "postgresql://user:pass@host:port/db"

# Custom config file
--config configs/app.yaml
```

## Output Files

### test_results.json
Summary of all processed datasets:
```json
{
  "datasets_processed": [
    {
      "resource_id": "0001",
      "input_blobs": 20,
      "pipeline_results": {...},
      "analysis": {
        "input_stats": {...},
        "output_stats": {...},
        "quality_metrics": {...}
      }
    }
  ],
  "summary": {
    "datasets_processed": 1,
    "total_blobs": 20,
    "total_facts_extracted": 45,
    "avg_facts_per_blob": 2.25
  }
}
```

### analysis.json (per dataset)
Detailed analysis for each dataset:
```json
{
  "input_stats": {
    "total_blobs": 20,
    "total_sentences": 150,
    "avg_sentences_per_blob": 7.5
  },
  "output_stats": {
    "total_facts": 45,
    "facts_per_blob": 2.25,
    "unique_predicates": 12,
    "unique_subjects": 8
  },
  "quality_metrics": {
    "validity_rate": 0.95,
    "avg_subject_length": 2.1,
    "avg_object_length": 3.4,
    "entity_linking_rate": 0.65,
    "qualifier_rate": 0.40
  }
}
```

## Tips

1. **Name datasets meaningfully**: Add notes in metadata.json about what each dataset tests
2. **Keep baselines**: Copy important datasets before major changes
3. **Compare analyses**: Use `diff` or `jq` to compare analysis.json files
4. **Automate**: Set up cron jobs to generate and test regularly
5. **Version control**: Consider committing important test datasets to git

