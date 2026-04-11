#!/usr/bin/env bash
# Ejecutar en pre-deploy (Render): migraciones + datos iniciales.
set -euo pipefail
export FLASK_APP=app.py
flask db upgrade
flask seed
