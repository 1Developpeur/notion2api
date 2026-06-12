# Use the official Python 3.11 slim image as the base image.
FROM python:3.11-slim

# Set environment variables.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory.
WORKDIR /app

# Copy requirements and install dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source and frontend files into the container.
COPY app ./app
COPY frontend ./frontend
COPY main.py ./main.py

# Create data directory and set permissions.
RUN mkdir -p /app/data

# Switch to a non-root user.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

# Expose the FastAPI runtime port.
EXPOSE 8000

# Health check.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Startup command. Runtime options are controlled by environment variables.
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
