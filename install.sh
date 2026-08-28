#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing Material Screensaver..."

mkdir -p ~/.local/bin ~/.local/share/material-screensaver/screensavers \
         ~/.local/share/icons ~/.config/systemd/user ~/.local/share/applications

# stop daemon briefly to avoid launching a half-written screensaver
systemctl --user stop material-screensaver.service 2>/dev/null || true

cp "$SCRIPT_DIR"/bin/*.py ~/.local/bin/
chmod +x ~/.local/bin/material-screensaver-ctl.py ~/.local/bin/material-screensaver-gui.py

# atomic screensaver install: stage to temp dir then move into place
TMP_DIR="$(mktemp -d)"
cp "$SCRIPT_DIR"/screensavers/* "$TMP_DIR"/
rm -f ~/.local/share/material-screensaver/screensavers/*.html \
      ~/.local/share/material-screensaver/screensavers/*.js
mv "$TMP_DIR"/* ~/.local/share/material-screensaver/screensavers/
rmdir "$TMP_DIR"

cp "$SCRIPT_DIR"/icons/material-screensaver-icon.png ~/.local/share/icons/material-screensaver.png

cp "$SCRIPT_DIR"/systemd/material-screensaver.service ~/.config/systemd/user/
cp "$SCRIPT_DIR"/applications/material-screensaver-settings.desktop ~/.local/share/applications/

systemctl --user daemon-reload
systemctl --user enable --now material-screensaver.service
update-desktop-database ~/.local/share/applications 2>/dev/null || true
gtk-update-icon-cache ~/.local/share/icons 2>/dev/null || true

echo "Done. Launching settings..."
~/.local/bin/material-screensaver-gui.py
