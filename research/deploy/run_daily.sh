#!/bin/bash
# בראשית – daily shadow run. Called by launchd (macOS) or cron.
#   plan   at 11:00 local (before the 12:00 CET day-ahead gate closure)
#   settle at 14:30 local (HUPX/SDAC results are public by ~13:00)
cd "$(dirname "$0")/.." || exit 1
source .venv/bin/activate 2>/dev/null
python -m bereshit.shadow "$1" >> shadow_log/run.log 2>&1
