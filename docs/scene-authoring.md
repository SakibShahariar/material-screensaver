# Scene authoring guide

Material Screensaver discovers `.html` files in its installed `screensavers/` directory. Keep each scene self-contained and compatible with a local `file://` URL.

## Start from the template

Copy [`scene-template.html`](scene-template.html) into the repository's `screensavers/` directory, give it a descriptive filename, and replace the example drawing with your scene. The settings picker discovers HTML files automatically after installation.

## Requirements and conventions

- **Offline by default:** bundle the assets needed by a scene. Do not load scripts, fonts, images, stylesheets, or other resources from the network.
- **No dynamic code execution:** do not use `eval`, `new Function`, or equivalent string-to-code mechanisms.
- **Theme support:** use CSS variables from the Matugen stylesheet when available, and provide readable built-in fallback colors when it is absent. The viewer's local-file resource policy and content-security policy are defense in depth, not a reason to add remote resources.
- **Animation efficiency:** use `requestAnimationFrame` for visual updates, stop scheduling frames when the page is not visible where practical, and avoid unnecessary work in each frame. The viewer currently injects a frame-rate wrapper for `requestAnimationFrame` callbacks; scenes that replace it or run independent timers may bypass that cap.
- **Accessibility and motion:** avoid flashing content and keep contrast readable. The viewer globally caps requestAnimationFrame-driven scenes at 10 FPS when the system requests reduced motion; still provide a static or low-motion fallback for intense animations and avoid independent timer loops that bypass the cap.
- **Clock helpers:** `clock-shared.js` provides `formatClock()` and `startClock(clockEl, dateEl)` for scenes that need a shared clock. Include the helper locally only when needed.
- **Cleanup:** do not create persistent timers, workers, audio playback, or other background work that continues after the scene is no longer active.
- **Naming:** use a clear filename and an informative HTML `<title>` so the scene is identifiable in the source and tools.

## Validate a scene

Run the dedicated package validator before enabling or distributing a scene. It checks required HTML structure, a non-empty title, viewport and Content Security Policy metadata, and referenced local assets. The generated `matugen-colors.css` link is the one intentional exception because installation creates it for each user.

```sh
python3 scripts/validate-scenes.py /path/to/scene-directory
```

The repository's built-in scenes are validated by default when the directory is omitted. The same validation is covered by the automated test suite. From the repository root, run the full checks used by CI:

```sh
python3 scripts/validate-scenes.py
python3 -m unittest discover -s tests -v
npx --yes eslint@9 screensavers/clock-shared.js extensions/material-screensaver-gestures@io.github.sakib/extension.js
```

Also inspect browser-console errors and confirm the scene behaves acceptably in a real GNOME Wayland session. Automated checks do not prove visual quality, power use, multi-monitor behavior, or correct cleanup under session lock.
