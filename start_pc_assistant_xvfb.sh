#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
fi

if [[ -n "${DISPLAY:-}" ]]; then
    exec "$PYTHON" "$SCRIPT_DIR/controller.py" "$@"
fi

if ! command -v xvfb-run >/dev/null 2>&1; then
    printf '%s\n' "Xvfb is required. Install xvfb, then run this launcher again." >&2
    exit 127
fi

"$PYTHON" "$SCRIPT_DIR/emergency_stop.py" --watch "$$" &
WATCHER_PID=$!
cleanup() {
    kill "$WATCHER_PID" 2>/dev/null || true
    wait "$WATCHER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

set +e
xvfb-run -a -s "-screen 0 1920x1080x24" \
    "$PYTHON" "$SCRIPT_DIR/controller.py" "$@"
STATUS=$?
set -e
exit "$STATUS"