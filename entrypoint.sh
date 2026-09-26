#!/bin/sh
# Browsers only grant microphone access in a secure context, so this has to be HTTPS
# even on the LAN. Self-signed, generated once into the data volume.
set -e
mkdir -p /data/certs
if [ ! -f /data/certs/cert.pem ] || [ ! -f /data/certs/key.pem ]; then
  echo "Generating self-signed certificate..."
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout /data/certs/key.pem -out /data/certs/cert.pem \
    -subj "/CN=${CERT_CN:-musical-lights}" \
    -addext "subjectAltName=${CERT_SAN:-DNS:localhost,IP:127.0.0.1}"
fi
export TLS_CERT=/data/certs/cert.pem TLS_KEY=/data/certs/key.pem
exec python -u app.py
