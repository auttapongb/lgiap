#!/bin/bash
# LGIAP Analyzer Wrapper — reads env from running workers, runs analyzer
# Called by cron every 5 minutes

set -e
cd /data/lgiap/backend

# Read environment from a running dramatiq worker that has GEMINI_API_KEY
WORKER_PID=""
for pid in $(pgrep -f "dramatiq.*ingest"); do
    if grep -q "GEMINI_API_KEY" /proc/$pid/environ 2>/dev/null; then
        WORKER_PID=$pid
        break
    fi
done

if [ -z "$WORKER_PID" ]; then
    # Fallback: try main.py
    for pid in $(pgrep -f "main.py.*8085"); do
        if grep -q "GEMINI_API_KEY" /proc/$pid/environ 2>/dev/null; then
            WORKER_PID=$pid
            break
        fi
    done
fi

if [ -n "$WORKER_PID" ]; then
    # Export env vars from the worker
    while IFS='=' read -r -d '' key value; do
        if [ -n "$key" ]; then
            export "$key=$value"
        fi
    done < /proc/$WORKER_PID/environ
    echo "Loaded env from PID $WORKER_PID"
else
    echo "WARNING: No worker process found, using current env"
fi

# Run analyzer
exec python3 app/analyzer.py
