# Scene performance measurements

The CI workflow collects repeatable **headless** startup, CPU, and memory samples for two representative scenes:

- `flow.html` — Canvas 2D
- `organic-harmonic-field.html` — WebGL

Each scene is measured three times at 30 FPS and 15 FPS using the same viewer setup and its injected frame-rate wrapper. The report includes every sample plus per-scene/FPS medians to reduce the influence of one-off runner noise. CI uploads the JSON report as the `scene-performance-metrics` artifact.

## Run locally

On a Linux desktop with GTK4, WebKitGTK 6.0, PyGObject, and Xvfb installed:

```sh
LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a python3 scripts/measure-scene-performance.py \
  --fps 30,15 --warmup 1 --duration 4 --repeat 3 --output scene-performance.json
```

The report includes time to WebKit load completion, aggregate process-tree CPU percentage, and summed resident memory at the start and end of the sample. CPU usage may exceed 100% when multiple processes use multiple cores. Summed RSS can count shared pages more than once.

## Interpreting the results

These are diagnostic baselines, not pass/fail thresholds. Hosted CI uses Xvfb and software rendering; it cannot provide representative GPU utilization or prove visual smoothness on a user's compositor and hardware. GPU utilization is therefore recorded as unavailable. Do not compare small differences across unrelated hosted runners as regressions.

Before enforcing budgets, collect repeatable measurements on target GNOME hardware, including GPU utilization and visual-smoothness checks, then choose limits from observed baselines rather than arbitrary numbers.


## First CI reference sample

The first repeated Canvas/WebGL comparison was recorded on 2026-11-03 in [CI run 41656846195](https://github.com/SakibShahariar/material-screensaver/actions/runs/41656846195). Values below are medians of three four-second samples per scene/FPS pair.

| Scene | FPS | Startup median | Process-tree CPU median | Summed RSS median |
|---|---:|---:|---:|---:|
| `flow.html` (Canvas 2D) | 30 | 372.21 ms | 323.32% | 748.07 MiB |
| `flow.html` (Canvas 2D) | 15 | 383.84 ms | 247.34% | 726.12 MiB |
| `organic-harmonic-field.html` (WebGL) | 30 | 337.81 ms | 265.77% | 695.04 MiB |
| `organic-harmonic-field.html` (WebGL) | 15 | 350.95 ms | 182.79% | 692.03 MiB |

In this runner, the 15 FPS setting reduced median process-tree CPU by about 23.5% for the Canvas scene and 31.2% for the WebGL scene compared with the 30 FPS reference. Treat these values as a recorded CI reference, not portable budgets: the renderer is software-based, CPU percentages aggregate several processes, and summed RSS can double-count shared pages. GPU utilization is unavailable.
