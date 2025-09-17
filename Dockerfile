FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver fonts-liberation xvfb dumb-init ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY karriere_scraper.py app.py /app/

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    SEL_TIMEOUT_SEC=25 \
    SELENIUM_CHROME_ARGS="--headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu --window-size=1366,768" \
    PAGE_LIMIT_DEFAULT=3

EXPOSE 8000
CMD ["dumb-init", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
