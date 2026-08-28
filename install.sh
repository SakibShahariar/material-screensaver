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

# atomic screensaver install: avoid empty-dir window (rm→mv race)
TMP_DIR="$(mktemp -d)"
cp -a "$SCRIPT_DIR"/screensavers/* "$TMP_DIR"/
chmod 644 "$TMP_DIR"/* 2>/dev/null || true
mkdir -p ~/.local/share/material-screensaver
rm -rf ~/.local/share/material-screensaver/screensavers.tmp
mv "$TMP_DIR" ~/.local/share/material-screensaver/screensavers.tmp
rm -rf ~/.local/share/material-screensaver/screensavers
mv ~/.local/share/material-screensaver/screensavers.tmp ~/.local/share/material-screensaver/screensavers

cp "$SCRIPT_DIR"/icons/material-screensaver-icon.png ~/.local/share/icons/material-screensaver.png

cp "$SCRIPT_DIR"/systemd/material-screensaver.service ~/.config/systemd/user/
cp "$SCRIPT_DIR"/applications/material-screensaver-settings.desktop ~/.local/share/applications/

systemctl --user daemon-reload || true
systemctl --user enable --now material-screensaver.service 2>/dev/null || echo "Enable service failed (no user bus) — run systemctl --user enable --now material-screensaver.service after login" >&2
update-desktop-database ~/.local/share/applications 2>/dev/null || true
gtk-update-icon-cache ~/.local/share/icons 2>/dev/null || true

echo "Done."
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  ~/.local/bin/material-screensaver-gui.py &
else
  echo "No DISPLAY — skipping GUI launch. Run material-screensaver-gui.py manually after login."
fi
