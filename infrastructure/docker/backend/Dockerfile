# Production-grade Dockerfile for EHR Intelligence Platform Backend
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# Create non-root system user and group for container security
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser

# Copy dependency specifications first to leverage Docker layer caching
COPY requirements.txt pyproject.toml /app/

# Install python dependencies using CPU-only PyTorch to minimize image size and build latency
RUN pip install --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download SentenceTransformer model weights for offline inference and fast cold start
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" && \
    mkdir -p /home/appuser/.cache && \
    cp -r /root/.cache/* /home/appuser/.cache/ 2>/dev/null || true && \
    chown -R appuser:appgroup /home/appuser/.cache

# Pre-create data persistence directories including vector store and assign ownership to appuser
RUN mkdir -p /app/data/storage/vector_store /app/data/input /app/data/processed && \
    chown -R appuser:appgroup /app/data

# Copy project source code, migrations, and tests
COPY app/ /app/app/
COPY scripts/ /app/scripts/
COPY tests/ /app/tests/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Set ownership of application code
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose API port
EXPOSE 8000

# Health check using built-in python urllib against FastAPI health endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Default command starts Uvicorn with hot reload for development
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
