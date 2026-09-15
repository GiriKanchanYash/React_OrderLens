#!/usr/bin/env bash
# Azure App Service (Linux) startup for Order Lens FastAPI backend.
set -e
cd /home/site/wwwroot
if [ -f "/home/site/wwwroot/antenv/bin/activate" ]; then
    source /home/site/wwwroot/antenv/bin/activate
else
    python -m pip install --upgrade pip -q
    pip install -r requirements.txt -q
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
