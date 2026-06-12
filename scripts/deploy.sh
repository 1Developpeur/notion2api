#!/bin/bash
# Notion-AI Docker deployment script.

set -e

echo "  Notion-AI Docker deployment script"

# Check Docker.
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Install Docker first."
    exit 1
fi

# Check Docker Compose.
if ! docker compose version &> /dev/null; then
    echo "Docker Compose is not installed. Install Docker Compose first."
    exit 1
fi

# Check .env.
if [ ! -f .env ]; then
    echo ".env does not exist; creating it from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Created .env. Edit it before rerunning this script."
        exit 1
    else
        echo ".env.example does not exist."
        exit 1
    fi
fi

mkdir -p data logs

echo "Building Docker image..."
docker compose build

echo "Starting services..."
docker compose up -d

echo "Waiting for service startup..."
sleep 5

echo "Service status:"
docker compose ps

echo "Health check:"
if curl -f http://localhost:8000/health > /dev/null 2>&1; then
    echo "Service is healthy."
    echo "Web UI: http://localhost:8000"
    echo "API docs: http://localhost:8000/docs"
    echo "Health: http://localhost:8000/health"
else
    echo "Service startup failed. Check logs with: docker compose logs -f"
    exit 1
fi

echo "Deployment complete."
