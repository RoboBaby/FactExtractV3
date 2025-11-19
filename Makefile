.PHONY: build up down run test psql init-db clean logs

# Default target
all: build

# Build all Docker images
build:
	docker compose -f docker/docker-compose.yml build

# Start all services
up:
	docker compose -f docker/docker-compose.yml up -d db srl timex

# Stop all services
down:
	docker compose -f docker/docker-compose.yml down

# Run pipeline with blobs file
# Usage: make run BLOBS=/path/to/blobs.jsonl
run:
	docker compose -f docker/docker-compose.yml run --rm pipeline \
		python src/cli.py --blobs /data/$(notdir $(BLOBS)) --config configs/app.yaml --init-db

# Run pipeline with default toy data
run-demo:
	docker compose -f docker/docker-compose.yml run --rm pipeline \
		python src/cli.py --blobs /data/blobs.jsonl --config configs/app.yaml --init-db

# Initialize database schema only
init-db:
	docker compose -f docker/docker-compose.yml run --rm pipeline \
		python -c "from src.storage.db import Database; db = Database('postgresql://postgres:postgres@db:5432/facts'); db.connect(); db.init_schema(); print('Schema initialized')"

# Connect to PostgreSQL
psql:
	docker compose -f docker/docker-compose.yml exec db psql -U postgres -d facts

# Run tests
test:
	docker compose -f docker/docker-compose.yml run --rm pipeline \
		pytest tests/ -v

# Run tests locally (without Docker)
test-local:
	PYTHONPATH=. pytest tests/ -v

# View logs
logs:
	docker compose -f docker/docker-compose.yml logs -f

# View logs for specific service
logs-%:
	docker compose -f docker/docker-compose.yml logs -f $*

# Clean up Docker resources
clean:
	docker compose -f docker/docker-compose.yml down -v --rmi local

# Install development dependencies locally
install-dev:
	pip install -r requirements.txt
	pip install -e .

# Format code (if black is available)
format:
	black src/ tests/

# Lint code (if ruff is available)
lint:
	ruff check src/ tests/

# Show database stats
stats:
	docker compose -f docker/docker-compose.yml exec db psql -U postgres -d facts -c \
		"SELECT 'entities' as table_name, COUNT(*) as count FROM entities UNION ALL \
		 SELECT 'videos', COUNT(*) FROM videos UNION ALL \
		 SELECT 'facts', COUNT(*) FROM facts UNION ALL \
		 SELECT 'clusters', COUNT(*) FROM clusters;"

# Help
help:
	@echo "Available targets:"
	@echo "  build      - Build Docker images"
	@echo "  up         - Start database and microservices"
	@echo "  down       - Stop all services"
	@echo "  run        - Run pipeline (BLOBS=/path/to/file.jsonl)"
	@echo "  run-demo   - Run pipeline with toy data"
	@echo "  init-db    - Initialize database schema"
	@echo "  psql       - Connect to PostgreSQL"
	@echo "  test       - Run tests in Docker"
	@echo "  test-local - Run tests locally"
	@echo "  logs       - View service logs"
	@echo "  clean      - Remove Docker resources"
	@echo "  stats      - Show database statistics"
