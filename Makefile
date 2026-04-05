.PHONY: help up down build test test-sdk test-backend test-frontend lint bench clean dev

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Start all services (docker compose up -d --build)
	docker compose up -d --build

down: ## Stop all services
	docker compose down

build: ## Rebuild all containers without cache
	docker compose build --no-cache

test: test-sdk test-backend ## Run all tests

test-sdk: ## Run SDK tests
	cd sdk && pip install -e ".[dev]" -q && pytest -v

test-backend: ## Run backend tests
	cd backend && pip install -e ".[dev]" -q && pytest -v

test-frontend: ## Type-check and build frontend
	cd frontend && npm run build

lint: ## Lint Python code with ruff
	ruff check sdk/ backend/

bench: ## Run overhead benchmark
	python benchmarks/overhead_test.py

dev-backend: ## Run backend in dev mode (hot reload)
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run frontend in dev mode (hot reload)
	cd frontend && npm run dev

clean: ## Remove build artifacts, caches, temp files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	rm -rf sdk/dist sdk/build
	rm -rf sdk/tmp_test_queues
	rm -rf frontend/dist

install: ## Install SDK + backend in dev mode
	cd sdk && pip install -e ".[dev]"
	cd backend && pip install -e ".[dev]"
	cd frontend && npm install

demo: ## Run the multi-agent demo
	python examples/multi_agent_demo.py
