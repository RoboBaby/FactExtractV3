# Docker Testing Setup

## Overview

Docker has been configured to support the testing infrastructure:
- Test data generation scripts
- Test harness for validation
- Test data directory mounting
- Test results directory

## Volumes

The following directories are mounted in Docker containers:

### Pipeline Service
- `/data` - Input blobs (from `../data/`)
- `/app/configs` - Configuration files
- `/app/resources/generated_data` - Generated test datasets
- `/app/test_results` - Test results output

### API Service
- `/app/resources/generated_data` - Generated test datasets
- `/app/test_results` - Test results output

## Environment Variables

### ANTHROPIC_API_KEY
Required for test data generation. Set in `.env` file or pass via docker-compose:

```bash
# In .env file
ANTHROPIC_API_KEY=your_key_here

# Or via command line
ANTHROPIC_API_KEY=your_key_here docker compose -f docker/docker-compose.yml up
```

## Running Tests in Docker

### Generate Test Data

```bash
# Generate test data inside Docker
docker compose -f docker/docker-compose.yml run --rm pipeline \
  python scripts/generate_test_data.py --count 20 --challenging

# Test data saved to: resources/generated_data/XXXX/
```

### Run Test Harness

```bash
# Scan all test datasets and run tests
docker compose -f docker/docker-compose.yml run --rm pipeline \
  python scripts/test_harness.py --scan --run-pipeline --analyze

# Test specific dataset
docker compose -f docker/docker-compose.yml run --rm pipeline \
  python scripts/test_harness.py --dataset 0001 --run-pipeline --analyze
```

### Run Unit Tests

```bash
# Run pytest tests
docker compose -f docker/docker-compose.yml run --rm pipeline \
  python -m pytest tests/ -v
```

## Database Connection

The test harness connects to the database using:
- Default: `postgresql://postgres:postgres@db:5432/facts`
- Override with `--db-dsn` flag

```bash
docker compose -f docker/docker-compose.yml run --rm pipeline \
  python scripts/test_harness.py \
    --scan \
    --run-pipeline \
    --analyze \
    --db-dsn "postgresql://postgres:postgres@db:5432/facts"
```

## Accessing Results

Test results are saved to:
- `test_results/test_results.json` - Summary
- `resources/generated_data/XXXX/analysis.json` - Per-dataset analysis

These are accessible from the host machine since volumes are mounted.

## Example Workflow

```bash
# 1. Start services
docker compose -f docker/docker-compose.yml up -d db qdrant srl timex

# 2. Generate test data
docker compose -f docker/docker-compose.yml run --rm pipeline \
  python scripts/generate_test_data.py --count 10 --challenging

# 3. Run tests
docker compose -f docker/docker-compose.yml run --rm pipeline \
  python scripts/test_harness.py --scan --run-pipeline --analyze

# 4. View results
cat test_results/test_results.json | python -m json.tool
cat resources/generated_data/0001/analysis.json | python -m json.tool
```

## Troubleshooting

### Missing ANTHROPIC_API_KEY
If you see errors about missing API key:
```bash
# Check .env file exists and has the key
cat .env | grep ANTHROPIC_API_KEY

# Or set it explicitly
export ANTHROPIC_API_KEY=your_key_here
```

### Database Connection Issues
Make sure database is running:
```bash
docker compose -f docker/docker-compose.yml ps db
```

### Volume Mount Issues
Check volumes are mounted correctly:
```bash
docker compose -f docker/docker-compose.yml run --rm pipeline ls -la /app/resources/generated_data
```

