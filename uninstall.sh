#!/usr/bin/env bash
set -euo pipefail

EXT_UUID="material-screensaver-gestures@io.github.sakib"
DATA_DIR="$HOME/.local/share/material-screensaver"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"
CONFIG_DIR="$HOME/.config/material-screensaver"
CACHE_DIR="$HOME/.cache/material-screensaver"
KEEP_SETTINGS=0

usage() {
  cat <<'EOF'
Usage: ./uninstall.sh [--keep-settings]

Remove Material Screensaver and its project-owned user files.
By default, the application's configuration is removed too.
Pass --keep-settings to preserve ~/.config/material-screensaver.
EOF
}

while (($#)); do
  case "$1" in
    --keep-settings) KEEP_SETTINGS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

echo "Uninstalling Material Screensaver..."

# Ask the running application to hide its viewer before stopping the daemon.
CTL="$HOME/.local/bin/material-screensaver-ctl.py"
if [[ -x "$CTL" ]]; then
  "$CTL" stop || echo "Warning: could not ask the viewer to stop; continuing with service shutdown." >&2
fi

# Stop and disable the user service before removing its executable and unit.
systemctl --user disable --now material-screensaver.service 2>/dev/null || true

# Remove only this extension UUID from GNOME's list; preserve other extensions.
python3 - "$EXT_UUID" <<'PY'
import ast
import subprocess
import sys

uuid = sys.argv[1]
try:
    result = subprocess.run(
        ["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
        check=True, capture_output=True, text=True,
    )
    enabled = ast.literal_eval(result.stdout.strip())
    if not isinstance(enabled, list):
        raise ValueError("enabled-extensions did not return a list")
    if uuid in enabled:
        enabled.remove(uuid)
        value = "[{}]".format(", ".join(repr(item) for item in enabled))
        subprocess.run(
            ["gsettings", "set", "org.gnome.shell", "enabled-extensions", value],
            check=True, capture_output=True, text=True,
        )
except Exception as exc:
    print(f"Warning: could not update GNOME's enabled-extensions setting: {exc}", file=sys.stderr)

# Remove only this app's custom keyboard-shortcut registration.
key_path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/material-screensaver/"
try:
    result = subprocess.run(
        ["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings"],
        check=True, capture_output=True, text=True,
    )
    paths = ast.literal_eval(result.stdout.strip())
    if not isinstance(paths, list):
        raise ValueError("custom-keybindings did not return a list")
    if key_path in paths:
        paths.remove(key_path)
        subprocess.run(
            ["gsettings", "set", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings", repr(paths)],
            check=True, capture_output=True, text=True,
        )
except Exception as exc:
    print(f"Warning: could not remove GNOME keyboard shortcut registration: {exc}", file=sys.stderr)
PY

systemctl --user daemon-reload 2>/dev/null || true

rm -f -- "$HOME/.local/bin/material-screensaver-ctl.py" \
          "$HOME/.local/bin/material-screensaver-gui.py" \
          "$HOME/.config/systemd/user/material-screensaver.service" \
          "$HOME/.local/share/applications/material-screensaver-settings.desktop" \
          "$HOME/.local/share/icons/material-screensaver.png" \
          "$HOME/.local/share/icons/hicolor/48x48/apps/material-screensaver.png" \
          "$HOME/.local/share/icons/hicolor/scalable/apps/material-screensaver.svg"
rm -rf -- "${DATA_DIR:?}" "${EXT_DIR:?}" "${CACHE_DIR:?}"

if ((KEEP_SETTINGS)); then
  echo "User configuration preserved at $CONFIG_DIR."
else
  rm -rf -- "${CONFIG_DIR:?}"
  echo "User configuration removed. Use --keep-settings to preserve it on future uninstallations."
fi

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
gtk-update-icon-cache "$HOME/.local/share/icons" 2>/dev/null || true

echo "Material Screensaver files removed."
echo "Log out and back in if GNOME Shell still has the extension loaded."
