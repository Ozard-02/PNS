FROM python:3.11-slim

# cron nativo + tzdata per orario corretto
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Rome

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/
COPY crontab /etc/cron.d/event-tracker-cron

RUN chmod 0644 /etc/cron.d/event-tracker-cron \
    && crontab /etc/cron.d/event-tracker-cron \
    && touch /var/log/cron.log \
    && mkdir -p /data

# Avvia cron in foreground, così il container resta vivo e i log sono visibili
CMD ["cron", "-f"]
