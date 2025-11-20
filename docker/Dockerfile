FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential curl wget ca-certificates \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY ./requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

# Download spaCy models (try transformer first, fallback to large/medium/small)
RUN python -m spacy download en_core_web_trf || \
    python -m spacy download en_core_web_lg || \
    python -m spacy download en_core_web_md || \
    python -m spacy download en_core_web_sm

# Copy application code
COPY ./src /app/src
COPY ./configs /app/configs
COPY ./resources /app/resources
COPY ./tests /app/tests

# Set Python path
ENV PYTHONPATH=/app

CMD ["python", "src/cli.py", "--blobs", "/data/blobs.jsonl", "--config", "configs/app.yaml"]
