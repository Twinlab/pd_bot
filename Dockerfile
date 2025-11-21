# Stage 1: Builder
FROM python:3.13-slim-bookworm as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file (generated from pyproject.toml)
# Since we don't have a requirements.txt, we'll install directly from pyproject.toml
# But first we need to install build tools
RUN pip install --upgrade pip setuptools wheel

# Copy project files needed for installation
COPY pyproject.toml .
COPY README.md .
# Create dummy files to satisfy build if needed, or just copy source
COPY cogs/ cogs/
COPY handlers/ handlers/
COPY utils/ utils/
COPY main.py .
COPY config/ config/

# Install dependencies into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install the package in editable mode or just dependencies
# We use .[dev] to install dev dependencies if needed, but for prod just .
RUN pip install .

# Stage 2: Runtime
FROM python:3.13-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install runtime system dependencies
# ffmpeg is required for music functionality
# git is required for self-update functionality
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY . .

# Create necessary directories for data persistence
RUN mkdir -p data logs downloads assets

# Create a non-root user for security
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app
USER botuser

# Command to run the bot
CMD ["python", "main.py"]