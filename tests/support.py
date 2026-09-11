"""Shared helpers for the Material screensaver test suite."""
import atexit
import glob
import importlib.util
import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_SAVERS = os.path.join(REPO_ROOT, "screensavers")


def load_ctl():
    mod = _load_module("ms_ctl_under_test",
                       os.path.join(REPO_ROOT, "bin", "material-screensaver-ctl.py"))
    # ctl.py registers atexit handlers that restore the real session's
    # overlay-key gsettings setting on process exit. The test suite must stay
    # hermetic, so detach them right after loading.
    for fn in (getattr(mod, "_restore_overview", None),
               getattr(mod, "_stop_overview_block", None)):
        if fn is not None:
            try:
                atexit.unregister(fn)
            except Exception:
                pass
    return mod


def load_gui():
    return _load_module("ms_gui_under_test",
                        os.path.join(REPO_ROOT, "bin", "material-screensaver-gui.py"))


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

SCRIPT_RE = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.S | re.I)
CDN_RE = re.compile(r"https?://(cdn\.|unpkg\.|jsdelivr|googleapis)", re.I)
RGBA_VAR_RE = re.compile(r"rgba\s*\(\s*var\(", re.I)
RGB_VAR_COMMA_RE = re.compile(r"rgb\(\s*var\(--[\w-]+\)\s*,", re.I)


def screensavers_dir():
    """Directory under test. Overridable so the suite can target an installed copy."""
    return os.environ.get("MS_TEST_SCREENSAVERS_DIR", DEFAULT_SAVERS)


def using_default_dir():
    return not os.environ.get("MS_TEST_SCREENSAVERS_DIR")


def html_files():
    return sorted(glob.glob(os.path.join(screensavers_dir(), "*.html")))


def shared_helpers():
    base = screensavers_dir()
    return [os.path.join(base, n) for n in ("clock-shared.js", "theme-shared.js")]


def extract_scripts(text):
    """Return (attrs, body) for every <script> tag. Skips non-JS typed payloads."""
    out = []
    for m in SCRIPT_RE.finditer(text):
        attrs = m.group("attrs")
        body = m.group("body")
        stype = re.search(r"type\s*=\s*[\"']([^\"']+)[\"']", attrs, re.I)
        if stype and stype.group(1).lower() not in ("", "text/javascript", "module", "application/javascript"):
            continue
        out.append((attrs, body))
    return out