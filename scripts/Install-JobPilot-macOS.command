#!/bin/bash
# Install a downloaded native bundle without Python, administrator access or model downloads.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Run this installer on macOS."
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ARCHIVE="${1:-$SCRIPT_DIR/JobPilot-$(uname -m).app.zip}"
DESTINATION="$HOME/Applications/JobPilot.app"

if [[ ! -f "$ARCHIVE" ]]; then
  echo "Download JobPilot-$(uname -m).app.zip alongside this installer, or pass its path."
  exit 1
fi
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/jobpilot-install.XXXXXX")"
trap 'rm -rf -- "$STAGING"' EXIT
/usr/bin/ditto -x -k "$ARCHIVE" "$STAGING"
if [[ ! -x "$STAGING/JobPilot.app/Contents/MacOS/JobPilot" ]]; then
  echo "The archive does not contain a runnable JobPilot.app."
  exit 1
fi
mkdir -p "$HOME/Applications"
if [[ -e "$DESTINATION" ]]; then
  if /usr/bin/pgrep -f "$DESTINATION/Contents/MacOS/JobPilot" >/dev/null; then
    echo "Quit JobPilot before installing the update."
    exit 1
  fi
  /bin/mv "$DESTINATION" "$STAGING/previous.app"
fi
if ! /usr/bin/ditto "$STAGING/JobPilot.app" "$DESTINATION"; then
  rm -rf -- "$DESTINATION"
  if [[ -d "$STAGING/previous.app" ]]; then
    /bin/mv "$STAGING/previous.app" "$DESTINATION"
  fi
  echo "Installation failed; the previous app was restored."
  exit 1
fi
echo "Installed $DESTINATION"
echo "Open it in Finder. For an unsigned build, use macOS Privacy & Security > Open Anyway if prompted."
echo "No Python, Ollama model, or browser download is required to open the app."
