#!/bin/bash
# ============================================================
# Universal XR Touchpad Reliability Test Launcher
# Automatically delegates to xr_touchpad.py
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/xr_touchpad.py"

if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "❌ Error: xr_touchpad.py not found in $SCRIPT_DIR"
    exit 1
fi

python3 "$PYTHON_SCRIPT" "$@"
