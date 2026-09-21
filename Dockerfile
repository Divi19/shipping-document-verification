FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SDOC_DATA_DIR=/app/data \
    SDOC_CASE_STORE_PATH=/tmp/sdoc-cases.json \
    PATH=/app/apps/api/.venv/bin:$PATH

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libgl1 \
        libglib2.0-0 \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY apps/api/pyproject.toml apps/api/uv.lock ./apps/api/
RUN cd apps/api && uv sync --frozen --no-dev

COPY apps/api/app ./apps/api/app
COPY local-data/sdoc-hackathon-bundle/inbox ./data/inbox
COPY local-data/sdoc-hackathon-bundle/attachments ./data/attachments

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:' + __import__('os').environ.get('PORT', '8000') + '/health')"

CMD ["sh", "-c", "uvicorn app.main:app --app-dir /app/apps/api --host 0.0.0.0 --port ${PORT:-8000}"]
