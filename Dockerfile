FROM python:3.12-slim

WORKDIR /app
COPY bot.py polymarket.py storage.py telegram_api.py ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data
USER appuser

ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
