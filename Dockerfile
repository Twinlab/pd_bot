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

COPY dependency-snapshot.txt pyproject.toml README.md ./
COPY scripts/dependency_snapshot.py /tmp/dependency_snapshot.py
RUN python /tmp/dependency_snapshot.py validate dependency-snapshot.txt

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN python -m pip install --upgrade --constraint dependency-snapshot.txt pip setuptools wheel

ENV PIP_CONSTRAINT=/app/dependency-snapshot.txt \
    PIP_BUILD_CONSTRAINT=/app/dependency-snapshot.txt

COPY cogs/ cogs/
COPY handlers/ handlers/
COPY utils/ utils/
COPY main.py .
COPY config/ config/

# pip запрещает build constraints без изоляции; снимаем их только для нашего wheel.
RUN env -u PIP_BUILD_CONSTRAINT python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/app-wheel . && \
    python -m pip install /tmp/app-wheel/*.whl && \
    python -m pip check && \
    python /tmp/dependency_snapshot.py check dependency-snapshot.txt

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
COPY --from=builder /app/dependency-snapshot.txt /app/dependency-snapshot.txt

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
