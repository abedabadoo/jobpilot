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
if [[ -d /Applications/JobPilot.app && ! -e "$DESTINATION" ]]; then
  DESTINATION=/Applications/JobPilot.app
fi

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
DESTINATION_DIR="$(dirname -- "$DESTINATION")"
SWAP="$(mktemp -d "$DESTINATION_DIR/.jobpilot-update.XXXXXX")"
trap 'rm -rf -- "$STAGING"; rmdir -- "$SWAP" 2>/dev/null || true' EXIT
/usr/bin/ditto "$STAGING/JobPilot.app" "$SWAP/JobPilot.app"
/usr/bin/codesign --verify --deep --strict "$SWAP/JobPilot.app"

BINARY="$DESTINATION/Contents/MacOS/JobPilot"
BASE=http://127.0.0.1:8765
if [[ -d "$DESTINATION" ]]; then
  if /bin/ps -axo command= | /usr/bin/awk -v bin="$BINARY" 'index($0, bin " --resumeforge-child") == 1 { found=1 } END { exit !found }'; then
    echo "Save and close the open ResumeForge editor, then run the update again."
    exit 1
  fi
  health="$(/usr/bin/curl -fsS --max-time 2 "$BASE/api/health" 2>/dev/null || true)"
  if [[ -n "$health" ]] && pid="$(/usr/bin/plutil -extract pid raw -o - - <<<"$health" 2>/dev/null)" &&
     [[ "$(/bin/ps -p "$pid" -o command=)" == "$BINARY --service-child "* ]]; then
    token="$(/usr/bin/curl -fsS --max-time 3 "$BASE/api/session" | /usr/bin/plutil -extract token raw -o - -)"
    echo "Waiting for JobPilot to finish active work…"
    for ((attempt=0; attempt<60; attempt++)); do
      if /usr/bin/curl -fsS --max-time 3 -o /dev/null -H "X-JobPilot-Token: $token" \
          -H 'Content-Type: application/json' --data '{"action":"shutdown","preserve_preferences":true}' \
          "$BASE/api/control" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    for ((attempt=0; attempt<20; attempt++)); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "JobPilot is still finishing work. The existing app is intact."
      exit 1
    fi
  fi
  while IFS= read -r dashboard; do
    if [[ -n "$dashboard" ]]; then kill -TERM "$dashboard" 2>/dev/null || true; fi
  done < <(/bin/ps -axo pid=,command= | /usr/bin/awk -v bin="$BINARY" '{pid=$1; sub(/^[[:space:]]*[0-9]+[[:space:]]+/, ""); if ($0 == bin) print pid}')
  /bin/mv "$DESTINATION" "$SWAP/previous.app"
fi
if ! /bin/mv "$SWAP/JobPilot.app" "$DESTINATION"; then
  if [[ -d "$SWAP/previous.app" ]]; then
    /bin/mv "$SWAP/previous.app" "$DESTINATION"
  fi
  echo "Installation failed; the previous app was restored."
  exit 1
fi
rm -rf -- "$SWAP/previous.app"
/usr/bin/open -a "$DESTINATION"
echo "Installed $DESTINATION"
echo "Open it in Finder. For an unsigned build, use macOS Privacy & Security > Open Anyway if prompted."
echo "No Python, Ollama model, or browser download is required to open the app."
