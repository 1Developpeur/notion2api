@echo off
REM Notion-AI Docker deployment script for Windows.

echo   Notion-AI Docker deployment script

REM Check Docker.
docker --version >nul 2>&1
if errorlevel 1 (
    echo Docker is not installed. Install Docker Desktop first.
    exit /b 1
)

REM Check .env.
if not exist .env (
    echo .env does not exist; creating it from .env.example...
    if exist .env.example (
        copy .env.example .env >nul
        echo Created .env. Edit it before rerunning this script.
        exit /b 1
    ) else (
        echo .env.example does not exist.
        exit /b 1
    )
)

if not exist data mkdir data
if not exist logs mkdir logs

echo Building Docker image...
docker compose build

echo Starting services...
docker compose up -d

echo Waiting for service startup...
timeout /t 5 /nobreak >nul

echo Service status:
docker compose ps

echo Health check:
curl -f http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    echo Service startup failed. Check logs with: docker compose logs -f
    exit /b 1
) else (
    echo Service is healthy.
    echo Web UI: http://localhost:8000
    echo API docs: http://localhost:8000/docs
    echo Health: http://localhost:8000/health
)

echo Deployment complete.
