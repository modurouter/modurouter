FROM ghcr.io/astral-sh/uv:0.11.3 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home app
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend ./backend
COPY alembic.ini ./
RUN uv sync --frozen --no-dev && mkdir -p /data/uploads && chown -R app:app /data /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER app
CMD ["uvicorn", "modurouter.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "asyncio", "--no-access-log"]
