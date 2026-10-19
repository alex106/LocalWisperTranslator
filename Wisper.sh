#!/usr/bin/env bash
# Start the Linux Wisper tray app when it is not already running.
# Use this after Quit, the same way Wisper.bat starts the Windows app.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
APP="$ROOT/linux/app.py"

if [[ ! -x "$PY" ]]; then
  echo "Wisper is not installed. Run: python3 install.py" >&2
  exit 1
fi

# The bracket keeps this check from matching its own command line.
if pgrep -u "$(id -u)" -f "[.]venv/bin/python.*${APP}" >/dev/null 2>&1; then
  echo "Wisper is already running."
  exit 0
fi

export YDOTOOL_SOCKET="${YDOTOOL_SOCKET:-/tmp/.ydotool_socket}"

shopt -s nullglob
lib_dirs=("$ROOT"/.venv/lib/python*/site-packages/nvidia/*/lib)
if ((${#lib_dirs[@]})); then
  IFS=:
  export LD_LIBRARY_PATH="${lib_dirs[*]}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  unset IFS
fi

cd "$ROOT"
nohup "$PY" "$APP" >/dev/null 2>&1 &
echo "Wisper started."
