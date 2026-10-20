"""Shared configuration and screensaver discovery for GUI and viewer."""
import glob
import json
import math
import os
import sys
import tempfile

DEFAULT_MATUGEN_COLORS_PATH = os.path.expanduser("~/.config/matugen/matugen-colors.css")
SCENE_OPTION_SCHEMA = {
    "starfield.html": {
        "speed": {
            "label": "Animation speed",
            "min": 0.5,
            "max": 2.0,
            "step": 0.1,
            "default": 1.0,
        }
    }
}
DEFAULT_CONFIG = {
    "active": None,
    "idle_seconds": 300,
    "fps_limit": 30,
    "clock_format": "24h",
    "clock_overlay": False,
    "clock_overlay_position": "bottom-right",
    "clock_overlay_opacity": 80,
    "random": False,
    "lock_after_seconds": 300,
    "matugen_colors_path": DEFAULT_MATUGEN_COLORS_PATH,
    "favorites": [],
    "lock_hook": [],
    "unlock_hook": [],
    "screensaver_options": {},
    "lock_message": "",
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


def _normalize_hook(value):
    """Accept an argv list only; never interpret hook settings through a shell."""
    if not isinstance(value, list) or not value or len(value) > 32:
        return []
    if any(
        not isinstance(arg, str) or not arg or "\0" in arg or len(arg) > 4096
        for arg in value
    ):
        return []
    if not value[0].strip():
        return []
    return list(value)


def _valid_option_value(value, spec):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(number) or not spec["min"] <= number <= spec["max"]:
        return None
    return round(number, 1)


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
    fps_limit = _valid_int(data.get("fps_limit"), 10, 60)
    if fps_limit is not None:
        cfg["fps_limit"] = fps_limit
    lock = _valid_int(data.get("lock_after_seconds"), 0, 86400)
    if lock is not None:
        cfg["lock_after_seconds"] = lock
    if data.get("clock_format") in ("12h", "24h"):
        cfg["clock_format"] = data["clock_format"]
    if isinstance(data.get("clock_overlay"), bool):
        cfg["clock_overlay"] = data["clock_overlay"]
    if data.get("clock_overlay_position") in ("top-left", "top-right", "bottom-left", "bottom-right"):
        cfg["clock_overlay_position"] = data["clock_overlay_position"]
    opacity = _valid_int(data.get("clock_overlay_opacity"), 20, 100)
    if opacity is not None:
        cfg["clock_overlay_opacity"] = opacity
    colors_path = data.get("matugen_colors_path", DEFAULT_MATUGEN_COLORS_PATH)
    if isinstance(colors_path, str) and colors_path.strip():
        colors_path = os.path.expanduser(colors_path.strip())
        if os.path.isabs(colors_path):
            cfg["matugen_colors_path"] = os.path.normpath(colors_path)
    favorites = data.get("favorites", [])
    if isinstance(favorites, list):
        cfg["favorites"] = list(dict.fromkeys(
            name for name in favorites
            if isinstance(name, str) and name.endswith(".html") and os.path.basename(name) == name
        ))
    message = data.get("lock_message", "")
    if isinstance(message, str):
        cfg["lock_message"] = "".join(
            char for char in message.strip() if char.isprintable()
        )[:160]
    cfg["lock_hook"] = _normalize_hook(data.get("lock_hook", []))
    cfg["unlock_hook"] = _normalize_hook(data.get("unlock_hook", []))
    options = data.get("screensaver_options", {})
    clean_options = {}
    if isinstance(options, dict):
        for scene, schema in SCENE_OPTION_SCHEMA.items():
            raw_scene = options.get(scene)
            if not isinstance(raw_scene, dict):
                continue
            clean_scene = {}
            for key, spec in schema.items():
                value = _valid_option_value(raw_scene.get(key), spec)
                if value is not None:
                    clean_scene[key] = value
            if clean_scene:
                clean_options[scene] = clean_scene
    cfg["screensaver_options"] = clean_options
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


def get_scene_options(config, scene):
    """Return validated option values for a scene, using schema defaults safely."""
    schema = SCENE_OPTION_SCHEMA.get(scene, {})
    all_options = config.get("screensaver_options", {}) if isinstance(config, dict) else {}
    raw = all_options.get(scene, {}) if isinstance(all_options, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    result = {}
    for key, spec in schema.items():
        value = _valid_option_value(raw.get(key, spec["default"]), spec)
        result[key] = spec["default"] if value is None else value
    return result


def sync_matugen_colors_link(screensaver_dir, cfg):
    """Atomically point the scene-local stylesheet name at the configured CSS."""
    target = cfg.get("matugen_colors_path", DEFAULT_MATUGEN_COLORS_PATH)
    if not isinstance(target, str) or not os.path.isabs(target):
        target = DEFAULT_MATUGEN_COLORS_PATH
    link = os.path.join(screensaver_dir, "matugen-colors.css")
    if not os.path.isdir(screensaver_dir):
        return False
    tmp = None
    try:
        if os.path.islink(link) and os.readlink(link) == target:
            return True
        # Do not overwrite a regular file a user deliberately placed here.
        if os.path.lexists(link) and not os.path.islink(link):
            print(f"Not replacing non-symlink Matugen stylesheet: {link}", file=sys.stderr)
            return False
        fd, tmp = tempfile.mkstemp(prefix=".matugen-colors-", dir=screensaver_dir)
        os.close(fd)
        os.unlink(tmp)
        os.symlink(target, tmp)
        os.replace(tmp, link)
        tmp = None
        return True
    except OSError as exc:
        print(f"Could not update Matugen stylesheet link: {exc}", file=sys.stderr)
        return False
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


