#!/usr/bin/env bash
set -euo pipefail

Xvfb :99 -screen 0 1440x900x24 -ac -listen tcp &
xvfb_pid=$!
trap 'kill "$xvfb_pid" "${vnc_pid:-}" "${web_pid:-}" 2>/dev/null || true' EXIT
for attempt in {1..30}; do
    if DISPLAY=:99 xdpyinfo >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
DISPLAY=:99 xdpyinfo >/dev/null
x11vnc -display :99 -forever -shared -nopw -localhost -rfbport 5900 &
vnc_pid=$!
websockify --web /usr/share/novnc 6080 localhost:5900 &
web_pid=$!
wait -n "$xvfb_pid" "$vnc_pid" "$web_pid"
echo "Browser desktop process exited unexpectedly" >&2
exit 1
