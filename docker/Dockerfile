
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies for psycopg2 / healthchecks
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY bot /app/bot
COPY backend /app/backend
COPY database /app/database
COPY alembic.ini /app/alembic.ini

RUN mkdir -p /app/logs && useradd -m trader && chown -R trader:trader /app
USER trader

EXPOSE 8000

CMD ["python", "-m", "bot.main"]
