# Valence Development Makefile
# Usage: make <target>

.PHONY: help install dev lint test test-unit test-integration test-all clean docker-up docker-down docker-test

# Default target
help:
	@echo "Valence Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install        Install production dependencies"
	@echo "  make dev            Install development dependencies"
	@echo ""
	@echo "Quality:"
	@echo "  make lint           Run linters (ruff, black, mypy)"
	@echo "  make format         Format code with black"
	@echo ""
	@echo "Testing:"
	@echo "  make test           Run unit tests (fast)"
	@echo "  make test-unit      Run unit tests only"
	@echo "  make test-int       Run integration tests (requires DB)"
	@echo "  make test-all       Run all tests"
	@echo "  make test-cov       Run tests with coverage report"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up      Start test environment (postgres + servers)"
	@echo "  make docker-down    Stop test environment"
	@echo "  make docker-test    Run integration tests in Docker"
	@echo "  make docker-logs    Show container logs"
	@echo ""
	@echo "Database:"
	@echo "  make db-init        Initialize local test database"
	@echo "  make db-reset       Reset test database"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean          Remove build artifacts and caches"

# =============================================================================
# Setup
# =============================================================================

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

# =============================================================================
# Quality
# =============================================================================

lint:
	ruff check src/valence tests/
	black --check src/valence tests/
	mypy src/valence --ignore-missing-imports

format:
	black src/valence tests/
	ruff check src/valence tests/ --fix

# =============================================================================
# Testing
# =============================================================================

test: test-unit

test-unit:
	pytest tests/ -m "not integration and not slow" -v --ignore=tests/integration/

test-int: test-integration

test-integration:
	pytest tests/integration/ -m "integration" -v --timeout=60

test-all:
	pytest tests/ -v --timeout=120

test-cov:
	pytest tests/ -m "not slow" -v \
		--cov=src/valence \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		--ignore=tests/integration/

test-fed:
	pytest tests/integration/test_federation_sync.py -v --timeout=120

test-trust:
	pytest tests/integration/test_trust_propagation.py -v

test-belief:
	pytest tests/integration/test_belief_lifecycle.py -v

# =============================================================================
# Docker
# =============================================================================

docker-up:
	docker compose -f docker-compose.test.yml up -d postgres postgres-peer
	@echo "Waiting for databases..."
	@sleep 5
	docker compose -f docker-compose.test.yml up -d valence-primary valence-peer
	@echo "Waiting for servers..."
	@sleep 10
	@echo "Environment ready. Primary: http://localhost:8080, Peer: http://localhost:8081"

docker-down:
	docker compose -f docker-compose.test.yml down -v

docker-test:
	docker compose -f docker-compose.test.yml up --build --abort-on-container-exit test-runner

docker-logs:
	docker compose -f docker-compose.test.yml logs -f

docker-build:
	docker compose -f docker-compose.test.yml build

# =============================================================================
# Database
# =============================================================================

# For local development with docker postgres on port 5433
DB_HOST ?= localhost
DB_PORT ?= 5433
DB_NAME ?= valence_test
DB_USER ?= valence
DB_PASS ?= testpass

db-init:
	PGPASSWORD=$(DB_PASS) psql -h $(DB_HOST) -p $(DB_PORT) -U $(DB_USER) -d $(DB_NAME) \
		-f src/valence/substrate/schema.sql
	PGPASSWORD=$(DB_PASS) psql -h $(DB_HOST) -p $(DB_PORT) -U $(DB_USER) -d $(DB_NAME) \
		-f src/valence/substrate/procedures.sql

db-reset:
	PGPASSWORD=$(DB_PASS) psql -h $(DB_HOST) -p $(DB_PORT) -U $(DB_USER) -d postgres \
		-c "DROP DATABASE IF EXISTS $(DB_NAME);"
	PGPASSWORD=$(DB_PASS) psql -h $(DB_HOST) -p $(DB_PORT) -U $(DB_USER) -d postgres \
		-c "CREATE DATABASE $(DB_NAME);"
	$(MAKE) db-init

db-shell:
	PGPASSWORD=$(DB_PASS) psql -h $(DB_HOST) -p $(DB_PORT) -U $(DB_USER) -d $(DB_NAME)

# =============================================================================
# Cleanup
# =============================================================================

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf coverage-*.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
