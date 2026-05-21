#!/usr/bin/env bash
APP="$HOME/holder/Projects/fastnotes/app.py"

if pgrep -f "Projects/fastnotes/app\.py" > /dev/null 2>&1; then
    pkill -f "Projects/fastnotes/app\.py"
else
    python "$APP" &
fi
