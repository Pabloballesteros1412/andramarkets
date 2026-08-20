FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 TZ=America/New_York

RUN apt-get update && apt-get install -y --no-install-recommends \
      fonts-texgyre fonts-liberation2 fonts-dejavu \
      tzdata cron ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/andramarkets
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .
RUN mkdir -p out logs

# Ejecucion puntual: docker run --env-file .env andramarkets
CMD ["python", "run_daily.py"]
