# Makefile for FactExtractV3

.PHONY: help build up down restart logs psql stats test generate-test-data test-harness

help:
	@echo "Available commands:"
	@echo "  make build          - Build Docker images"
	@echo "  make up             - Start all services"
	@echo "  make down           - Stop all services"
	@echo "  make restart        - Restart all services"
	@echo "  make logs           - Show logs"
	@echo "  make psql           - Connect to PostgreSQL"
	@echo "  make stats          - Show database statistics"
	@echo "  make test           - Run pytest tests"
	@echo "  make generate-test-data - Generate test data (N=20)"
	@echo "  make test-harness   - Run test harness on all datasets"
	@echo ""
	@echo "Test data generation:"
	@echo "  make generate-test-data N=50 CHALLENGING=1"
	@echo ""
	@echo "Test harness:"
	@echo "  make test-harness DATASET=0001"
	@echo "  make test-harness SCAN=1"

build:
	docker compose -f docker/docker-compose.yml build

up:
	docker compose -f docker/docker-compose.yml up -d

down:
	docker compose -f docker/docker-compose.yml down

restart: down up

logs:
	docker compose -f docker/docker-compose.yml logs -f

psql:
	docker compose -f docker/docker-compose.yml exec db psql -U postgres -d facts

stats:
	@docker compose -f docker/docker-compose.yml exec db psql -U postgres -d facts -c "\
		SELECT \
			(SELECT COUNT(*) FROM entities) as entities, \
			(SELECT COUNT(*) FROM videos) as videos, \
			(SELECT COUNT(*) FROM facts) as facts, \
			(SELECT COUNT(*) FROM clusters) as clusters;"

test:
	docker compose -f docker/docker-compose.yml run --rm pipeline python -m pytest tests/ -v

generate-test-data:
	@if [ ! -f .env ]; then \
		echo "Error: .env file not found. Create one with ANTHROPIC_API_KEY=your_key"; \
		exit 1; \
	fi; \
	N=$${N:-20}; \
	CHALLENGING=$${CHALLENGING:-}; \
	CMD="python scripts/generate_test_data.py --count $$N"; \
	if [ "$$CHALLENGING" = "1" ]; then \
		CMD="$$CMD --challenging"; \
	fi; \
	docker compose -f docker/docker-compose.yml --env-file .env run --rm pipeline $$CMD

test-harness:
	@if [ -n "$$DATASET" ]; then \
		docker compose -f docker/docker-compose.yml --env-file .env run --rm pipeline \
			python scripts/test_harness.py --dataset $$DATASET --run-pipeline --analyze; \
	elif [ "$$SCAN" = "1" ]; then \
		docker compose -f docker/docker-compose.yml --env-file .env run --rm pipeline \
			python scripts/test_harness.py --scan --run-pipeline --analyze; \
	else \
		echo "Usage: make test-harness DATASET=0001 or make test-harness SCAN=1"; \
	fi

run:
	@if [ -z "$$BLOBS" ]; then \
		echo "Usage: make run BLOBS=path/to/blobs.jsonl"; \
		exit 1; \
	fi
	docker compose -f docker/docker-compose.yml run --rm pipeline \
		python src/cli.py --blobs $$BLOBS --config configs/app.yaml --init-db

run-demo:
	docker compose -f docker/docker-compose.yml run --rm pipeline \
		python src/cli.py --blobs /data/blobs.jsonl --config configs/app.yaml --init-db

show-test-data:
	@./scripts/show_latest_test_data.sh
