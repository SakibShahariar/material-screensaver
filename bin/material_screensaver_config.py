"""Shared configuration and screensaver discovery for GUI and viewer."""
import glob
import json
import os
import tempfile

DEFAULT_MATUGEN_COLORS_PATH = os.path.expanduser("~/.config/matugen/matugen-colors.css")
DEFAULT_CONFIG = {
    "active": None,
    "idle_seconds": 300,
    "clock_format": "24h",
    "random": False,
    "lock_after_seconds": 300,
    "matugen_colors_path": DEFAULT_MATUGEN_COLORS_PATH,
}


def _valid_int(value, minimum, maximum):
    """Return an integer in range without truncating fractions or accepting bools."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if minimum <= value <= maximum else None


def normalize_config(data):
    """Return a safe, complete configuration from untrusted JSON data."""
    cfg = dict(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return cfg
    active = data.get("active")
    if active is None or isinstance(active, str):
        cfg["active"] = active
    if isinstance(data.get("random"), bool):
        cfg["random"] = data["random"]
    idle = _valid_int(data.get("idle_seconds"), 1, 86400)
    if idle is not None:
        cfg["idle_seconds"] = idle
    lock = _valid_int(data.get("lock_after_seconds"), 0, 86400)
    if lock is not None:
        cfg["lock_after_seconds"] = lock
    if data.get("clock_format") in ("12h", "24h"):
        cfg["clock_format"] = data["clock_format"]
    colors_path = data.get("matugen_colors_path", DEFAULT_MATUGEN_COLORS_PATH)
    if isinstance(colors_path, str) and colors_path.strip():
        colors_path = os.path.expanduser(colors_path.strip())
        if os.path.isabs(colors_path):
            cfg["matugen_colors_path"] = os.path.normpath(colors_path)
    return cfg


def load_config(config_path):
    """Load and normalize a config file, returning defaults on missing/bad input."""
    if not os.path.exists(config_path):
        return dict(DEFAULT_CONFIG)
    try:
        with open(config_path, encoding="utf-8") as handle:
            return normalize_config(json.load(handle))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return dict(DEFAULT_CONFIG)


def save_config(config_path, **updates):
    """Atomically persist updates while dropping invalid and unknown values."""
    cfg = load_config(config_path)
    cfg.update(updates)
    cfg = normalize_config(cfg)
    config_dir = os.path.dirname(os.path.abspath(config_path))
    os.makedirs(config_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".material-screensaver-", suffix=".tmp", dir=config_dir
    )
    try:
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = None
        with handle as output:
            json.dump(cfg, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, config_path)
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def list_screensavers(screensaver_dir):
    """Return sorted full paths for HTML screensavers in the given directory."""
    return sorted(glob.glob(os.path.join(screensaver_dir, "*.html")))
