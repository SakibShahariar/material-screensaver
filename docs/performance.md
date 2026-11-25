# Scene performance measurements

The CI workflow collects repeatable **headless** startup, CPU, and memory samples for two representative scenes:

- `flow.html` — Canvas 2D
- `organic-harmonic-field.html` — WebGL

Each scene is measured three times at 30 FPS, 15 FPS, and with the cap disabled (`--fps 0`, labelled "native (uncapped)") using the same viewer setup. The uncapped sample skips the injected frame-rate wrapper entirely, giving a headless reference for how much CPU the cap saves; on Xvfb's 60 Hz display it is effectively native pacing. The report includes every sample plus per-scene/FPS medians to reduce the influence of one-off runner noise. CI uploads the JSON report as the `scene-performance-metrics` artifact.

## Run locally

On a Linux desktop with GTK4, WebKitGTK 6.0, PyGObject, and Xvfb installed:

```sh
LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a python3 scripts/measure-scene-performance.py \
  --fps 30,15,0 --warmup 1 --duration 4 --repeat 3 --output scene-performance.json
```

The report includes time to WebKit load completion, aggregate process-tree CPU percentage, and summed resident memory at the start and end of the sample. CPU usage may exceed 100% when multiple processes use multiple cores. Summed RSS can count shared pages more than once.

## Interpreting the results

These are diagnostic baselines, not pass/fail thresholds. Hosted CI uses Xvfb and software rendering; it cannot provide representative GPU utilization or prove visual smoothness on a user's compositor and hardware. GPU utilization is therefore recorded as unavailable. Do not compare small differences across unrelated hosted runners as regressions.

Before enforcing budgets, collect repeatable measurements on target GNOME hardware, including GPU utilization and visual-smoothness checks, then choose limits from observed baselines rather than arbitrary numbers.


## Latest CI reference sample

Recorded in [CI run 45676694299](https://github.com/SakibShahariar/material-screensaver/actions/runs/45676694299). Values are medians of three four-second samples per scene/cap pair; `native (uncapped)` skips the injected frame wrapper entirely.

| Scene | Cap | Startup median | Process-tree CPU median | Summed RSS median |
|---|---:|---:|---:|---:|
| `flow.html` (Canvas 2D) | native | 256.31 ms | 315.06% | 729.54 MiB |
| `flow.html` (Canvas 2D) | 30 FPS | 274.87 ms | 281.28% | 731.02 MiB |
| `flow.html` (Canvas 2D) | 15 FPS | 264.32 ms | 189.50% | 730.49 MiB |
| `organic-harmonic-field.html` (WebGL) | native | 253.43 ms | 325.20% | 692.73 MiB |
| `organic-harmonic-field.html` (WebGL) | 30 FPS | 246.37 ms | 188.91% | 687.00 MiB |
| `organic-harmonic-field.html` (WebGL) | 15 FPS | 249.99 ms | 140.00% | 690.03 MiB |

In this runner the cap reduced median process-tree CPU by about 11% (Canvas) and 42% (WebGL) at 30 FPS versus native, and by about 40% and 57% at 15 FPS. The earlier [run 41656846195](https://github.com/SakibShahariar/material-screensaver/actions/runs/41656846195) recorded only 30/15 FPS and no native reference. Treat these as diagnostic CI references, not portable budgets: the renderer is software-based, CPU percentages aggregate several processes, and summed RSS can double-count shared pages. GPU utilization is unavailable.
