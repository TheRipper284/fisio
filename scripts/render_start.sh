#!/usr/bin/env bash
# Respaldo local / Docker: mismo comando que render.yaml (startCommand).
set -euo pipefail
exec gunicorn app:app --bind "0.0.0.0:${PORT:-5000}" --workers 1 --timeout 180 --graceful-timeout 30 --access-logfile - --error-logfile - --forwarded-allow-ips='*'
