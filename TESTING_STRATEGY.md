# Fact Extraction Testing Strategy

## Overview

Since you don't yet have access to full social media analysis data, we'll use **LLM-generated test data** to validate the improved fact extraction pipeline. This approach allows us to:

1. Generate diverse, realistic test cases
2. Test specific linguistic phenomena (passive voice, phrasal verbs, etc.)
3. Validate improvements before production deployment
4. Create reproducible test datasets

## Testing Approach

### Phase 1: Generate Diverse Test Data

Use the existing `generate_test_data.py` script to create test datasets:

```bash
# Generate 50 diverse blobs
python scripts/generate_test_data.py --count 50 --challenging

# Generate specific challenging cases
python scripts/generate_test_data.py --count 10 --topic "passive voice assembly instructions"
python scripts/generate_test_data.py --count 10 --topic "phrasal verb heavy tutorial"
```

### Phase 2: Run Extraction Pipeline

```bash
# Run on generated data
make run BLOBS=resources/generated_data/0002/blobs.jsonl

# Or use the test harness
python scripts/test_harness.py --generate 50 --run-pipeline --analyze
```

### Phase 3: Validate Results

The test harness validates:
- **Fact Quality**: Subject/object boundaries, predicate mapping
- **Entity Linking**: Wikidata link rates, entity recognition
- **Coverage**: Facts per sentence, unique predicates
- **Accuracy**: Valid vs invalid facts

## Test Data Categories

### 1. Standard Technical Content
- Drone assembly
- Soldering tutorials
- 3D printing guides
- Electronics projects

### 2. Challenging Linguistic Constructions
- **Passive Voice**: "The drone was assembled by Alice..."
- **Phrasal Verbs**: "Put together", "heat up", "set up"
- **Complex NPs**: "The experienced engineer with 10 years of experience..."
- **Relative Clauses**: "The drone that Alice assembled..."
- **Coordination**: "Alice and Bob assemble..."
- **Temporal Sequences**: "First... then... after that..."

### 3. Edge Cases
- Imperatives: "Assemble the drone..."
- Questions: "What does Alice assemble?"
- Negation: "Alice does not use..."
- Quantified: "Alice assembles three drones..."

## Validation Metrics

### Quality Metrics
- **Validity Rate**: % of facts with proper structure
- **Subject Quality**: Average subject length (should be < 10 words)
- **Object Quality**: Average object length (should be < 15 words)
- **Entity Linking Rate**: % of entities linked to Wikidata
- **Qualifier Rate**: % of facts with qualifiers (instruments, measurements)

### Coverage Metrics
- **Facts per Sentence**: Should be > 0.5 (at least 1 fact per 2 sentences)
- **Unique Predicates**: Diversity of action types extracted
- **Entity Diversity**: Variety of entities recognized

### Accuracy Metrics (Manual Review)
- **Precision**: % of extracted facts that are correct
- **Recall**: % of expected facts that were extracted
- **Boundary Accuracy**: % of arguments with correct boundaries

## Recommended Test Workflow

### 1. Quick Validation (5-10 minutes)
```bash
# Generate small test set
python scripts/generate_test_data.py --count 10

# Run pipeline
make run-demo  # or use generated data

# Check results
make stats
make psql  # Then: SELECT * FROM facts LIMIT 10;
```

### 2. Comprehensive Testing (30-60 minutes)
```bash
# Generate diverse test suite
python scripts/generate_test_data.py --count 100 --challenging

# Run full pipeline
make run BLOBS=resources/generated_data/XXXX/blobs.jsonl

# Analyze results
python scripts/test_harness.py --input resources/generated_data/XXXX/blobs.jsonl --analyze
```

### 3. Regression Testing
```bash
# Save baseline results
python scripts/test_harness.py --generate 50 --run-pipeline --output baseline.json

# After changes, compare
python scripts/test_harness.py --generate 50 --run-pipeline --output current.json
# Compare baseline.json vs current.json
```

## Expected Improvements

With the new spaCy-based pipeline, you should see:

### Before (Stub SRL)
- ~30% correct argument extraction
- ~20% Wikidata entity links
- Many facts with wrong boundaries ("Alice puts the drone" as subject)
- Missing phrasal verbs and complex constructions

### After (spaCy + Dependencies)
- **95%+ correct argument extraction**
- **80%+ Wikidata entity links** (with proper entity linking setup)
- **Proper noun phrase boundaries**
- **Phrasal verb detection** ("put together", "heat up")
- **Passive voice handling**
- **Complex sentence parsing**

## Manual Review Checklist

When reviewing extracted facts, check:

1. **Subject Accuracy**
   - [ ] Subject is a proper noun phrase (not "Alice puts the drone")
   - [ ] Subject length is reasonable (< 10 words)
   - [ ] Subject is correctly identified (not including verb)

2. **Object Accuracy**
   - [ ] Object is a proper noun phrase
   - [ ] Object doesn't include trailing prepositions
   - [ ] Object boundaries are correct

3. **Predicate Mapping**
   - [ ] Predicate frame is appropriate
   - [ ] Phrasal verbs are handled ("put together" not just "put")
   - [ ] Light verbs are recognized ("make a decision")

4. **Entity Linking**
   - [ ] Named entities are linked to Wikidata when possible
   - [ ] Local IDs are generated for unlinked entities
   - [ ] Entity confidence scores are reasonable

5. **Qualifiers**
   - [ ] Instruments are captured ("with Torx T20 bit")
   - [ ] Measurements are normalized (50 millimeters)
   - [ ] Temporal expressions are extracted

## Next Steps

1. **Generate Initial Test Suite**
   ```bash
   python scripts/generate_test_data.py --count 50 --challenging
   ```

2. **Run Pipeline on Test Data**
   ```bash
   make run BLOBS=resources/generated_data/0002/blobs.jsonl
   ```

3. **Review Sample Facts**
   ```bash
   make psql
   # Then: SELECT * FROM facts ORDER BY video_id LIMIT 20;
   ```

4. **Compare Before/After**
   - Run on same test data with old vs new pipeline
   - Compare fact quality and accuracy

5. **Iterate**
   - Identify common failure modes
   - Adjust prompts or add more test cases
   - Fine-tune entity linking thresholds

## Production Readiness

The system is ready for production testing when:
- ✅ 90%+ validity rate on test data
- ✅ < 5% facts with boundary errors
- ✅ 70%+ entity linking rate
- ✅ All test suite tests pass
- ✅ Performance is acceptable (< 5s per blob)

