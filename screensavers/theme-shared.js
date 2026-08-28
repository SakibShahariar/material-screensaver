// Shared theme helpers for Material screensavers.
// Extracted from duplicated readRGB/rgba/loadTheme blocks across 46 styles.
// Usage: <script src="theme-shared.js"></script> before your main script,
// then call readRGB/rgba or loadThemePalette().
// Backwards compatible: if a file already defines readRGB/rgba, this file's
// definitions are no-ops (preserves its own fallbacks).
(function() {
  if (typeof window.readRGB !== "function") {
    window.readRGB = function(name, fb = [160, 160, 160]) {
      const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      const parts = raw.split(/\s+/).map(Number);
      return (parts.length === 3 && parts.every(n => !isNaN(n))) ? parts : fb;
    };
  }
  if (typeof window.rgba !== "function") {
    window.rgba = function(c, a = 1) {
      return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
    };
  }
  // Convenience: read a set of --foo_rgb vars into an object.
  // Example: loadThemePalette(["--surface_rgb","--primary_rgb"], {[fallback map]})
  if (typeof window.loadThemePalette !== "function") {
    window.loadThemePalette = function(vars, fallbacks = {}) {
      const out = {};
      for (const v of vars) {
        const key = v.replace(/^--/, "").replace(/_rgb$/, "");
        const fb = fallbacks[v] || fallbacks[key] || [160, 160, 160];
        out[key] = window.readRGB(v, fb);
      }
      return out;
    };
  }
  // Optional helper to apply common clock/hint colors if those elements exist
  if (typeof window.applyThemeToChrome !== "function") {
    window.applyThemeToChrome = function(theme, opts = {}) {
      const clockEl = document.getElementById("clock");
      const dateEl = document.getElementById("date");
      const hintEl = document.getElementById("hint");
      if (clockEl && theme.primary) clockEl.style.color = window.rgba(theme.primary, opts.clockAlpha ?? 0.97);
      if (dateEl && theme.secondary) dateEl.style.color = window.rgba(theme.secondary, opts.dateAlpha ?? 0.88);
      if (hintEl && theme.outline) hintEl.style.color = window.rgba(theme.outline, opts.hintAlpha ?? 0.6);
      if (theme.surface) document.body.style.background = window.rgba(theme.surface);
    };
  }
})();
