"""Allowlisted URI scheme for loading screensaver scenes and their assets.

WebKit no longer permits overriding the ``file`` scheme, and its file-access
settings do not stop subresources such as ``<script src="../other.js">`` from
loading. Scenes are therefore served through a custom scheme whose handler only
reads from the directory that contains the bundled screensavers.
"""
from __future__ import annotations

import mimetypes
import os
from urllib.parse import quote, unquote, urlencode, urlsplit

SCENE_SCHEME = "material-scene"
SCENE_HOST = "scene"


def scene_uri(scene_path: str, params: dict | None = None) -> str:
    """Build the URI used to load a scene and pass clock/option parameters."""
    name = quote(os.path.basename(scene_path))
    query = urlencode(params or {})
    return f"{SCENE_SCHEME}://{SCENE_HOST}/{name}?{query}"


def register_scene_scheme(ctx, root: str, debug=None) -> bool:
    """Register a handler on ``ctx`` that serves only files inside ``root``."""
    from gi.repository import Gio, GLib

    allowed_root = os.path.normpath(os.path.abspath(root))
    if getattr(ctx, "_material_scene_scheme", False):
        return True

    def _log(message: str) -> None:
        if debug is not None:
            debug(message)

    def _deny(request, reason: str) -> None:
        # An empty response is a safe denial and behaves the same in every
        # PyGObject/WebKit version; GError marshalling is not portable.
        _log(f"scene_resource_rejected reason='{reason}'")
        try:
            empty = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(b""))
            request.finish(empty, 0, "text/plain")
        except Exception as exc:
            _log(f"Suppressed non-fatal exception rejecting scene resource: {exc}")

    def _on_request(request):
        uri = request.get_uri()
        try:
            path = unquote(urlsplit(uri).path).lstrip("/")
            candidate = os.path.normpath(os.path.join(allowed_root, path))
        except Exception as exc:
            _log(f"Suppressed non-fatal exception parsing scene resource: {exc}")
            _deny(request, "Invalid scene resource")
            return
        if not (candidate == allowed_root or candidate.startswith(allowed_root + os.sep)):
            _log(f"scene_resource_blocked uri='{uri}'")
            _deny(request, "Scene resource outside the screensavers directory")
            return
        try:
            with open(candidate, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            _log(f"scene_resource_missing uri='{uri}' error='{exc}'")
            _deny(request, "Scene resource not available")
            return
        try:
            stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
            content_type = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
            request.finish(stream, len(data), content_type)
            _log(f"scene_resource_allowed uri='{uri}'")
        except Exception as exc:
            _log(f"Suppressed non-fatal exception serving scene resource: {exc}")
            _deny(request, "Could not serve scene resource")

    try:
        ctx.register_uri_scheme(SCENE_SCHEME, _on_request)
        ctx._material_scene_scheme = True
        return True
    except Exception as exc:
        _log(f"Could not register scene URI scheme: {exc}")
        return False
