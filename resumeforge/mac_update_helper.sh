#!/bin/sh
# Run by ResumeForge after the existing application has closed.
# Only operates on the verified, staged ResumeForge.app passed by the GUI.
set -eu
old_pid="$1"
target="$2"
source_app="$3"
work="$4"
log="$5"

exec >>"$log" 2>&1
printf 'ResumeForge update helper started\n'

case "$target" in
  */ResumeForge.app) ;;
  *) echo "Refusing invalid destination"; exit 1 ;;
esac
test -f "$source_app/Contents/MacOS/ResumeForge" || exit 1
test -f "$source_app/Contents/Info.plist" || exit 1

counter=0
while kill -0 "$old_pid" 2>/dev/null; do
  counter=$((counter + 1))
  if [ "$counter" -ge 120 ]; then
    echo "Old application did not close; cancelling update"
    exit 1
  fi
  sleep 1
done

parent=$(dirname "$target")
mkdir -p "$parent"
next="$parent/.ResumeForge-update-$$.app"
backup="$parent/.ResumeForge-previous.app"

if [ -e "$next" ]; then
  echo "Unexpected staging path already exists; cancelling update"
  exit 1
fi

/usr/bin/ditto "$source_app" "$next"
/usr/bin/codesign --verify --deep --strict "$next"

if [ -e "$target" ]; then
  # Retain one rollback version in the same Applications directory.
  if [ -e "$backup" ]; then
    /bin/rm -rf "$backup"
  fi
  /bin/mv "$target" "$backup"
fi

if ! /bin/mv "$next" "$target"; then
  if [ -e "$backup" ] && [ ! -e "$target" ]; then
    /bin/mv "$backup" "$target" || true
  fi
  echo "Could not install the new application"
  exit 1
fi

if ! /usr/bin/open "$target"; then
  echo "New application could not be opened; restoring previous app"
  /bin/rm -rf "$target"
  if [ -e "$backup" ]; then
    /bin/mv "$backup" "$target"
    /usr/bin/open "$target" || true
  fi
  exit 1
fi

echo "Update applied; previous version retained as $backup"
/bin/rm -rf "$work"
