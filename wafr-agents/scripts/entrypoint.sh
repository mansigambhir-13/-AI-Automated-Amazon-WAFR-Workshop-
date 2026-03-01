#!/bin/bash
set -e

echo "=== Starting uvicorn server ==="
cd /app
exec uvicorn wafr.ag_ui.server:app \
  --host 0.0.0.0 \
  --port 8000 \
  --timeout-keep-alive 300 \
  --workers 1 \
  --log-level info
