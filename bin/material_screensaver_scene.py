"""Pure scene-selection helpers shared by the viewer and control script."""
from __future__ import annotations


def rotation_scene_names(cfg, available_scenes):
    """Ordered scene list: configured favorites when valid, else all scenes."""
    favorites = cfg.get("favorites", []) if isinstance(cfg, dict) else []
    chosen = [name for name in favorites if name in available_scenes]
    return chosen if chosen else sorted(available_scenes)


def next_scene_name(cfg, available_scenes, current=None):
    """Return the scene after ``current`` in the rotation order."""
    names = rotation_scene_names(cfg, available_scenes)
    if not names:
        return None
    if isinstance(cfg, dict) and cfg.get("active") in names and current is None:
        current = cfg["active"]
    if current not in names:
        current = names[0]
    return names[(names.index(current) + 1) % len(names)]
