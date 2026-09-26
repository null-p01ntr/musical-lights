FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py entrypoint.sh ./
COPY static/ static/
COPY tests/ tests/
RUN chmod +x entrypoint.sh

VOLUME /data
EXPOSE 8443
ENTRYPOINT ["./entrypoint.sh"]
