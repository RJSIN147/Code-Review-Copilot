#!/bin/sh
# Exit immediately if a command exits with a non-zero status
set -e

echo "Running database migrations..."
uv run alembic upgrade head

echo "Starting FastAPI application..."
exec uv run uvicorn app.main:app --port 8000 --host 0.0.0.0
