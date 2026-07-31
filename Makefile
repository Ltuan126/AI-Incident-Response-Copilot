.PHONY: help install dev up down logs migrate seed test lint typecheck check demo clean

help:
	@echo "install    Install Python deps (editable, with dev extras)"
	@echo "up         Start the full stack via Docker Compose"
	@echo "down       Stop the stack"
	@echo "logs       Tail stack logs"
	@echo "migrate    Apply Alembic migrations"
	@echo "seed       Seed services, deployment history and runbooks"
	@echo "test       Run the test suite"
	@echo "lint       Ruff lint + format check"
	@echo "typecheck  Mypy"
	@echo "check      lint + typecheck + test"
	@echo "demo       Trigger the deployment-regression scenario"

install:
	python -m pip install -e ".[dev]"

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	alembic upgrade head

seed:
	python scripts/seed_data.py

test:
	pytest

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy apps packages

check: lint typecheck test

demo:
	curl -X POST http://localhost:8000/api/v1/simulator/incidents/deployment-regression

clean:
	docker compose down -v
