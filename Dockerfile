# Stage 1: Builder
FROM python:3.13.14-slim-bookworm@sha256:9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64 AS builder

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

# Create dummy files to satisfy build requirements for caching
# This allows us to install dependencies without invalidating the cache when source code changes
RUN mkdir -p cogs handlers utils config && \
    touch cogs/__init__.py handlers/__init__.py utils/__init__.py config/__init__.py && \
    touch main.py

# Install dependencies into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies only (using the dummy files)
RUN pip install .

# Now copy the real source code
COPY cogs/ cogs/
COPY handlers/ handlers/
COPY utils/ utils/
COPY main.py .
COPY config/ config/

# Re-install the package to ensure any package-specific metadata is updated
# This is fast because dependencies are already installed
RUN pip install .

# Stage 2: Runtime
FROM python:3.13.14-slim-bookworm@sha256:9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64

ARG APP_REVISION=development

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    BOT_REVISION="$APP_REVISION"

LABEL org.opencontainers.image.revision="$APP_REVISION"

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy only runtime application files. Список намеренно явный: новый локальный
# артефакт не должен случайно оказаться в production-образе.
COPY cogs/ cogs/
COPY handlers/ handlers/
COPY utils/ utils/
COPY config/ config/
COPY assets/ assets/
COPY main.py .

# Create necessary directories for data persistence
RUN mkdir -p data logs assets

# Create a non-root user for security
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app
USER botuser

# Command to run the bot
CMD ["python", "main.py"]
