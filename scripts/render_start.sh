#!/usr/bin/env bash
# Arranque en Render: migraciones Alembic + Gunicorn en $PORT
set -euo pipefail
export FLASK_APP=app.py
flask db upgrade
flask seed
exec gunicorn app:app --bind "0.0.0.0:${PORT:-10000}" --workers 1 --timeout 120
