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
if [[ -e "$DESTINATION" ]]; then
  echo "JobPilot already exists at $DESTINATION. Move it aside before installing this version."
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
/usr/bin/ditto "$STAGING/JobPilot.app" "$DESTINATION"
echo "Installed $DESTINATION"
echo "Open it in Finder. For an unsigned build, use macOS Privacy & Security > Open Anyway if prompted."
echo "No Python, Ollama model, or browser download is required to open the app."
