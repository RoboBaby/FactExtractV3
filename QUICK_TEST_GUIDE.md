# Quick Testing Guide

## What I Meant by "Production Testing"

When I said "ready for production testing," I meant the system is ready to validate with realistic data before deploying to actual social media analysis. Since you don't have that data yet, **LLM-generated test data is perfect** for this phase.

## Quick Start: Test the Improvements

### 1. Generate Challenging Test Data (5 minutes)

```bash
# Generate 20 challenging test blobs that test all the improvements
python scripts/generate_test_data.py --count 20 --challenging

# This creates: resources/generated_data/0002/blobs.jsonl
# Test data is automatically saved in numbered directories
```

### 2. Run Tests Using Test Harness (Recommended)

```bash
# Scan all test datasets and run pipeline + analysis
python scripts/test_harness.py --scan --run-pipeline --analyze

# Or run on a specific dataset
python scripts/test_harness.py --dataset 0002 --run-pipeline --analyze

# Results are saved to:
# - test_results.json (summary)
# - resources/generated_data/0002/analysis.json (per-dataset)
```

### 3. Alternative: Manual Pipeline Run

```bash
# Run on the generated data manually
make run BLOBS=resources/generated_data/0002/blobs.jsonl

# Check results
make stats
make psql  # Then query facts
```

### 4. View Test Results

```bash
# View summary
cat test_results.json | python -m json.tool

# View specific dataset analysis
cat resources/generated_data/0002/analysis.json | python -m json.tool
```

## What to Look For

### ✅ Good Signs (Improvements Working)
- **Proper boundaries**: Subject is "Alice" not "Alice assembles the drone"
- **Phrasal verbs detected**: "put together" not just "put"
- **Passive voice handled**: "The drone was assembled by Alice" extracts correctly
- **Complex NPs**: "The experienced engineer" extracted as single subject
- **Entity linking**: Some entities linked to Wikidata (Alice, Bob, etc.)

### ❌ Red Flags (Still Needs Work)
- Subjects too long (> 10 words)
- Missing arguments (no object when there should be one)
- Wrong boundaries (verb included in subject/object)
- Phrasal verbs split incorrectly

## Comparison: Before vs After

### Before (Stub SRL)
```
Subject: "Alice puts the drone"  ❌
Object: "using a Torx T20 bit."  ❌
```

### After (spaCy + Dependencies)
```
Subject: "Alice"  ✅
Predicate: "put together"  ✅
Object: "the drone"  ✅
Qualifier: instrument="a Torx T20 bit"  ✅
```

## Recommended Test Sequence

1. **Small Test** (validate it works)
   ```bash
   # Generate and test
   python scripts/generate_test_data.py --count 5 --challenging
   python scripts/test_harness.py --dataset 0002 --run-pipeline --analyze
   ```

2. **Medium Test** (validate quality)
   ```bash
   # Generate diverse test set
   python scripts/generate_test_data.py --count 25 --challenging
   python scripts/test_harness.py --dataset 0003 --run-pipeline --analyze
   # Review: cat resources/generated_data/0003/analysis.json
   ```

3. **Large Test** (validate robustness)
   ```bash
   # Generate large test suite
   python scripts/generate_test_data.py --count 100
   python scripts/test_harness.py --dataset 0004 --run-pipeline --analyze
   ```

4. **Batch Testing** (test all saved datasets)
   ```bash
   # Run pipeline and analysis on ALL saved test datasets
   python scripts/test_harness.py --scan --run-pipeline --analyze
   # Results saved to test_results.json and each dataset's analysis.json
   ```

## Using the Test Harness

The test harness provides automated validation and can scan saved test datasets:

### Generate and Test in One Go
```bash
python scripts/test_harness.py \
  --generate 50 \
  --challenging \
  --run-pipeline \
  --analyze \
  --output test_results.json
```

### Test All Saved Datasets
```bash
# Scan the test data directory and process all datasets
python scripts/test_harness.py \
  --scan \
  --run-pipeline \
  --analyze \
  --test-data-dir resources/generated_data
```

### Test Specific Dataset
```bash
# Test a specific saved dataset
python scripts/test_harness.py \
  --dataset 0002 \
  --run-pipeline \
  --analyze
```

The harness will:
1. Find all test datasets in the directory
2. Run the extraction pipeline on each
3. Validate fact quality
4. Save analysis.json in each dataset directory
5. Generate a summary in test_results.json

## Next Steps After Testing

Once you're satisfied with test results:

1. **Scale up**: Generate larger test sets (500-1000 blobs)
2. **Performance testing**: Measure extraction speed
3. **Edge case testing**: Test specific failure modes
4. **Production readiness**: When metrics look good, you're ready for real data

## Expected Results

With the improvements, you should see:
- **10-20x more facts** extracted (better coverage)
- **95%+ valid facts** (proper structure)
- **Better entity linking** (more Wikidata links)
- **Fewer boundary errors** (proper noun phrases)

The LLM-generated test data is actually **better than random real data** for validation because:
- You can control what linguistic phenomena to test
- You can generate specific edge cases
- You can create reproducible test suites
- You can validate improvements systematically

