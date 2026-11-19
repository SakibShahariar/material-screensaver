# Commit CI Audit Ledger

Persistent repository-specific record of commit-level CI checks and red-cross investigations.

## How to use this ledger

1. Read this file before auditing commit checks.
2. Check only commits newer than the checkpoint, plus older **red**, **pending**, or explicitly unresolved entries.
3. Record exact commit SHAs and observed results; never infer from missing badges or empty API responses.
4. Preserve failures and append diagnosis, fix, rerun, and final-outcome evidence.
5. Advance the checkpoint only after reviewing the range; carry unresolved entries forward.

## Result meanings

| Result | Meaning |
|---|---|
| **green** | Completed successful check/run directly observed. |
| **red** | Completed failing check/run directly observed. |
| **pending** | Check/run exists but is unfinished. |
| **unavailable** | Available evidence did not expose a result; not a pass or failure. |
| **not applicable** | Workflow configuration confirms no relevant check is triggered. |

## Checkpoint

- Repository: `SakibShahariar/material-screensaver`
- Default branch: `master`
- Checkpoint SHA: `814afc697af08133c3c378ef3989d235e9fdacbf`
- Initialized: 2026-11-02
- Baseline correction: a workflow run for the checkpoint commit was later found and inspected; it failed in the test-suite step. The failure is recorded below rather than treating the earlier empty combined-status response as authoritative.
- Next session: review commits after `814afc697af08133c3c378ef3989d235e9fdacbf`; retain the historical red, pending, and unavailable entries below for audit context.

## Initial baseline

| Commit SHA | Subject | CI result | Checked | Follow-up |
|---|---|---|---|---|
| `44ec3498851aff1735124f2d80ef232f35af6c84` | docs: improve maintenance workflow guidance | red | 2026-11-02 | [Run 41401009285](https://github.com/SakibShahariar/material-screensaver/actions/runs/41401009285): tests failed; lint passed. |

## Red-cross investigation log

The following commits all have an observed failed test job and successful lint job. The same two assertions failed in `tests/test_lock_logic.py`: `test_lock_when_inactive_is_noop` (unexpected hide count 1) and `test_repeat_active_changed_only_hides_once` (unexpected hide count 2). The test fixture leaked the daemon's `_is_showing` state between cases; the production hide path clears that flag, but the fake hide callback did not. The spawn-race test added in `930e51d` sets `_is_showing=True` without restoring it. Classification: test-fixture regression, not evidence of a production lock-handling regression.

| Commit SHA | Subject | CI result | Workflow run | Failed job / step |
|---|---|---|---|---|
| `b7856e4c6b5f29bf5fe94c8288c817416ba3e200` | docs: add persistent commit CI audit ledger | red | [41456575938](https://github.com/SakibShahariar/material-screensaver/actions/runs/41456575938) | tests / Run test suite |
| `6495447b0262de2312dfbc6cfab77db49a2eff88` | docs: document incremental commit CI auditing | red | [41456581218](https://github.com/SakibShahariar/material-screensaver/actions/runs/41456581218) | tests / Run test suite |
| `ffb4e1bd8cb11bba701086956712ab0f104a9b47` | docs: define issue triage categories | red | [41573380962](https://github.com/SakibShahariar/material-screensaver/actions/runs/41573380962) | tests / Run test suite |
| `aaff2f7ec7fd9110075b4dcc6a301e25246b1083` | docs(agents): define administrative commit hygiene | red | [41597938193](https://github.com/SakibShahariar/material-screensaver/actions/runs/41597938193) | tests / Run test suite |

### 2026-11-03 follow-up audit

| Commit SHA | Subject | CI result | Workflow run | Outcome |
|---|---|---|---|---|
| `423eebfea83295f4f4949806623f5b094074619a` | test(lock): isolate viewer state between lock cases (#8) | green | [41644027097](https://github.com/SakibShahariar/material-screensaver/actions/runs/41644027097) | Tests and lint passed; repaired shared test-fixture state leakage. |
| `34ae3fe8f490a7bdb6146e861ae2cffc63f8a386` | perf(gui): cache scene titles between searches (#59) | red | [41644489962](https://github.com/SakibShahariar/material-screensaver/actions/runs/41644489962) | Tests failed because the title regex was over-escaped; fallback titles appeared instead of HTML titles. |
| `779623c6f085247b8c0f9e0b83cbd96242ffed4d` | fix(gui): preserve scene title matching in cache (#59) | green | [41644554326](https://github.com/SakibShahariar/material-screensaver/actions/runs/41644554326) | Corrected regex; tests and lint passed. |
| `a78e130f1b626369e4fc14a1357fc0a11860dc71` | perf(ctl): reuse one config snapshot per viewer setup (#61) | red | [41645272969](https://github.com/SakibShahariar/material-screensaver/actions/runs/41645272969) | Tests exposed stale source assertions after config reads moved to the shared snapshot; implementation lint passed. |
| `0e63ed30c42ccbab98860f82db4f6bd4ec5543a1` | test(ctl): align config snapshot assertions (#61) | green | [41645513300](https://github.com/SakibShahariar/material-screensaver/actions/runs/41645513300) | Updated static assertions; tests and lint passed. |

| `594faa8b64a59ed673d073c6db4bc46abd4c8e2d` | perf(gui): debounce settings group filtering (#62) | red | [41645968803](https://github.com/SakibShahariar/material-screensaver/actions/runs/41645968803) | Test fixture lacked the debounced callback method; product code lint passed. |
| `31593d7c6070a55a47eac129f53c9a40b03e3726` | test(gui): exercise debounced filter callback (#62) | green | [41646183571](https://github.com/SakibShahariar/material-screensaver/actions/runs/41646183571) | Corrected test fixture; tests and lint passed. |

The lock-test fixture failure was resolved by `423eebf`; the GUI title-regex failure by `779623c`; the config-snapshot test assertion failure by `0e63ed3`; and the debounce test fixture failure by `31593d7`. The checkpoint advances through the last fully verified commit. The next substantive commit remains outside this checkpoint until its own CI result is observed.

| `ca24a0968bd42f6ec721badcaa8f129ba80974da` | perf(ctl): cache UPower state for viewer setup (#63) | red | [41646623211](https://github.com/SakibShahariar/material-screensaver/actions/runs/41646623211) | Tests failed because a mock command result used a literal escaped newline, so the parser did not see a state line. |
| `3540595a6b72aad4a12f3cea79dab1d2c3c89519` | test(ctl): provide realistic UPower output (#63) | green | [41646860228](https://github.com/SakibShahariar/material-screensaver/actions/runs/41646860228) | Corrected mock stdout; tests and lint passed. |

### README streamlining follow-up

| `eb19a5567b1b03918d45cbdb508a4896f32c758b` | docs: streamline README and move troubleshooting details | red | [41649597941](https://github.com/SakibShahariar/material-screensaver/actions/runs/41649597941) | Lint passed; tests failed because the shortened README omitted the reduced-motion cap description expected by an existing test. |
| `14bcaaba2f45acb3d97865e4b624f36e132262e4` | docs: restore reduced-motion detail and audit CI failure | green | [41650136466](https://github.com/SakibShahariar/material-screensaver/actions/runs/41650136466) | Restored the 10 FPS detail; tests and lint passed. |

### Issue #60 — descendant-only WebKit cleanup

| `abf6091025dcd9d69700c22e817787e9f8c333d6` | perf(ctl): walk WebKit descendants without global proc scan (#60) | red | [41650565668](https://github.com/SakibShahariar/material-screensaver/actions/runs/41650565668) | Tests failed: the PID-reuse fixture changed identity during descendant discovery; other cleanup tests passed. |
| `2fc1ef9191dc630527d3a90d456fa57598db0bc9` | fix(ctl): preserve null-separated proc cmdlines (#60) | red | [41650972275](https://github.com/SakibShahariar/material-screensaver/actions/runs/41650972275) | Tests still failed in the PID-reuse fixture; lint passed. |
| `417da93872c26a14018d4598e93e04cfd5bf7f1d` | test(ctl): check PID reuse immediately before signalling (#60) | red | [41651166171](https://github.com/SakibShahariar/material-screensaver/actions/runs/41651166171) | PID-reuse fixture still did not persist the replacement parent identity, so the original process's child was still selected; lint passed. |
| `8750e9a04ac22ba378a579cf7cb499b18621b438` | test(ctl): persist reused PID identity in cleanup test (#60) | green | [41651416134](https://github.com/SakibShahariar/material-screensaver/actions/runs/41651416134) | Persisted the synthetic PID replacement; tests and lint passed. |
| `a3aab7ea1cbbd3e14bdd1b841de90c04c77d9739` | test(ctl): cover large unrelated process tables (#60) | green | [41651797696](https://github.com/SakibShahariar/material-screensaver/actions/runs/41651797696) | Added a 300-process synthetic table check proving unrelated PIDs are not read; tests and lint passed. |

| `e4e71e2e07511d2cee4e63ee34bae7ff5e5744b6` | fix(ctl): reset lock timer on viewer activity (#47) | green | [41652543288](https://github.com/SakibShahariar/material-screensaver/actions/runs/41652543288) | Added the daemon Activity D-Bus method and rate-limited viewer input notifications; tests and lint passed. |
| `2295a9dc94f828b804b89531fe57ad1665ad8572` | fix(ctl): throttle activity resets for short lock delays (#47) | pending | [41652880519](https://github.com/SakibShahariar/material-screensaver/actions/runs/41652880519) | Adjusted the activity notification interval to 250 ms; syntax/CI verification pending. |

| `2295a9dc94f828b804b89531fe57ad1665ad8572` | fix(ctl): throttle activity resets for short lock delays (#47) | red | [41652880519](https://github.com/SakibShahariar/material-screensaver/actions/runs/41652880519) | Tests and lint failed because a literal `\\n` was inserted into a Python condition; syntax error. |
| `816826d5f0e96f470a19d8653aa638bf70855b9e` | fix(ctl): correct activity throttle condition syntax (#47) | green | [41653026291](https://github.com/SakibShahariar/material-screensaver/actions/runs/41653026291) | Replaced the escaped sequence with a real multiline condition; tests and lint passed. |

| `419563f6116c2449263c9e272ab43889b1cc7f4c` | perf(ci): collect scene startup CPU and memory baselines (#44) | pending | [41654229895](https://github.com/SakibShahariar/material-screensaver/actions/runs/41654229895) | Added a headless WebKit performance sampler and CI artifact; first workflow run is still in progress. |


| `419563f6116c2449263c9e272ab43889b1cc7f4c` | perf(ci): collect scene startup CPU and memory baselines (#44) | pending | [41654229895](https://github.com/SakibShahariar/material-screensaver/actions/runs/41654229895) | The first benchmark implementation used a nonexistent load-event constant; run remained in progress when checked. Corrected in the next commit. |
| `675a0fcf80498f792b57f273f50d43d7271c194c` | fix(perf): use WebKit load events and viewer teardown (#44) | green | [41654457749](https://github.com/SakibShahariar/material-screensaver/actions/runs/41654457749) | Used the WebKit load-finished enum and the application's teardown path; tests, lint, benchmark, and artifact upload passed. |
| `e2b5cd0facd475e945f847d84f61e638ccb7f07c` | perf(ci): repeat scene samples and report medians (#44) | green | [41655018836](https://github.com/SakibShahariar/material-screensaver/actions/runs/41655018836) | Three samples per scene/FPS pair; median startup, CPU, and RSS metrics reported and uploaded as an artifact. Tests, lint, and benchmark passed. |

| `d422454238068f55f3f457c6a90f6cabb34e6dab` | perf(ctl): avoid display-rate polling in FPS throttle (#38) | red | [41656115584](https://github.com/SakibShahariar/material-screensaver/actions/runs/41656115584) | The three Node harness tests could not extract the embedded script because the regex was over-escaped; the wrapper itself parsed. |

| `d5b1c33ac47226570555a11c0be41ba5de0d1c55` | test(perf): verify timer-paced frame scheduling (#38) | green | [41656290095](https://github.com/SakibShahariar/material-screensaver/actions/runs/41656290095) | Corrected the extraction regex and added deterministic timer/native-RAF harnesses; tests, lint, and repeated scene benchmark passed. |

| `5be984faac60e80ed9ecebd29ca5cf11f9ea5942` | perf(ci): benchmark a focused Canvas animation scene (#44) | green | [41656846195](https://github.com/SakibShahariar/material-screensaver/actions/runs/41656846195) | Switched the Canvas sample to the RAF-driven flow scene; tests, lint, repeated benchmark, and artifact upload passed. |

| `69a3aba75bb9a8f138ff4826ac5d789e69975f9e` | docs(perf): record first Canvas and WebGL CI baseline (#44) | green | [41657508932](https://github.com/SakibShahariar/material-screensaver/actions/runs/41657508932) | Recorded the first three-sample Canvas/WebGL CI median reference; tests and lint passed. |

| `48a9c4214a92f62b6815e4d8ec464c4b9a39bcf8` | feat(settings): add visual descriptions for all scenes (#64) | green | [41658677951](https://github.com/SakibShahariar/material-screensaver/actions/runs/41658677951) | Added descriptions for all 31 scenes, displayed the selected description in Settings, updated README preview captions, and added coverage tests; tests, lint, and performance workflow passed. |

### 2026-11-19 follow-up audit (README streamline regression)

Reviewed the range after the previous checkpoint `48a9c4214a92f62b6815e4d8ec464c4b9a39bcf8` through HEAD `41dc4df3219166884aa73c14fb3ed4e1b6200919`. Nine intermediate commits have zero recorded check runs in the GitHub API and are marked **unavailable** (absence of evidence is not a pass). The other three pushes are **red** because the README streamline at `43ac3f4` removed content asserted by the test suite; lint is green in all four observed runs.

| Commit SHA | Subject | CI result | Workflow run | Outcome |
|---|---|---|---|---|
| `f6f8352c1272ecde78b92bea89ffc943300439d7` | docs(scenes): keep captions aligned with theme colors (#64) | green | [41659146125](https://github.com/SakibShahariar/material-screensaver/actions/runs/41659146125) | Tests and lint passed. |
| `30dc4aada0cb53b1ea70c5342ae15438a559c319` | docs(agents): clarify acceptance criteria evidence | green | [41864231334](https://github.com/SakibShahariar/material-screensaver/actions/runs/41864231334) | Tests and lint passed. |
| `43ac3f4333af82aec8af8be08dded52c408cfa05` | docs: streamline Material Screensaver README | red | [42514687798](https://github.com/SakibShahariar/material-screensaver/actions/runs/42514687798) | Removed the canonical preview captions, `**31 animated scenes**` count wording, and `requestAnimationFrame-driven scenes at **10 FPS**` line; six tests failed, lint passed. Resolved by `814afc6`. |
| `23ac781063cbbddf67ad94bd41404a500bce0a7b` | fix(ctl): resolve graphical session for logind lock monitoring | unavailable | none | No check runs recorded. |
| `3b79a19f07f7ca7de96b246c2aabc9a73f81f23d` | fix(gui): handle subprocess result tuple from PyGObject | unavailable | none | No check runs recorded. |
| `f523ec6bc366ca40248f9cd2655d7b30c11f2333` | feat(gui): organize settings into sidebar sections | unavailable | none | No check runs recorded. |
| `0ae760fa464cfac656319209e69cf915de7f0d16` | refactor(gui): use native libadwaita preferences navigation | unavailable | none | No check runs recorded. |
| `f3d6e41737989bc5f319382b9f486479db837c9b` | fix(viewer): retry Wayland fullscreen requests | unavailable | none | No check runs recorded. |
| `89d51eeb23cfce725865c20368e75550ebfa6697` | fix(viewer): reliably dismiss with Super+Q | unavailable | none | No check runs recorded. |
| `7e447e90ae1f573d695a797b3e705dddecd8596d` | fix(viewer): exit process when window closes | unavailable | none | No check runs recorded. |
| `4cb20e42a9ae6781842ce34f966e7794f07414ed` | fix(lock): attempt lock during viewer transition | unavailable | none | No check runs recorded. |
| `429c384bcf09893d7aa0d0fab366cd3aef223771` | fix(lock): complete lock commands off the GTK callback | unavailable | none | No check runs recorded. |
| `cb59bee332e88566129bd76262070d22ff2e24bf` | feat(viewer): style lock countdown with accent colors | red | [42800117819](https://github.com/SakibShahariar/material-screensaver/actions/runs/42800117819) | Same six README test failures; lint passed. Resolved by `814afc6`. |
| `6bd6319e90a35e479d1001390426b166048ff872` | feat(scenes): validate versioned scene manifests (#55) | red | [42801759473](https://github.com/SakibShahariar/material-screensaver/actions/runs/42801759473) | Same six README test failures; lint passed. Resolved by `814afc6`. |
| `41dc4df3219166884aa73c14fb3ed4e1b6200919` | fix(gui): persist resized settings window | red | [42808498997](https://github.com/SakibShahariar/material-screensaver/actions/runs/42808498997) | Same six README test failures; lint passed. Resolved by `814afc6`. |
| `814afc697af08133c3c378ef3989d235e9fdacbf` | fix(docs): restore README content required by CI tests | green | [44498147410](https://github.com/SakibShahariar/material-screensaver/actions/runs/44498147410) | 2026-11-19. Restored the three test-guarded README strings; lint and tests passed, along with scene validation, payload budget, WebKit CSP, and performance steps. |

Diagnosis: one root cause. `43ac3f4` dropped three README strings asserted by `tests/test_scene_descriptions.py` and `tests/test_static.py`. Every later push re-ran the same failing tree, so three otherwise-unrelated feature/fix commits inherited red status. This repeats the earlier `eb19a55` streamline failure resolved by `14bcaab`.

Fix: `814afc697af08133c3c378ef3989d235e9fdacbf` restored the canonical preview captions, the `**31 animated scenes**` feature wording, and the `requestAnimationFrame-driven scenes at **10 FPS**` reduced-motion line in `README.md`; kept the remainder of the streamline. Local verification: 216/216 unit tests pass, `validate-scenes.py` 31/31 pass, `check-scene-payload-budget.py` passes. Ruff is not installed locally; the change is README-only. Pushed to `master` on 2026-11-19 and verified green in [run 44498147410](https://github.com/SakibShahariar/material-screensaver/actions/runs/44498147410) (lint success, tests success). The four red entries above are therefore resolved; the nine unavailable entries remain without evidence and are carried forward.

### Failure record template

- Commit SHA:
- Commit subject:
- First observed (date):
- Workflow / run URL:
- Failed job / step:
- Failure summary:
- Classification: regression / pre-existing / inconclusive
- Fix commit(s):
- Rerun attempt(s) and result:
- Final verified outcome:
- Remaining follow-up:

## Session history

| Date | Reviewed range / checkpoint | Result summary |
|---|---|---|
| 2026-11-02 | Initial checkpoint: `44ec3498851aff1735124f2d80ef232f35af6c84` | Latest commit queried; empty status response recorded as unavailable. Earlier history not retroactively audited. |
| 2026-11-19 | `48a9c421` → `814afc69` (16 commits) | Two green, nine unavailable (no check runs), four red from the README-streamline regression at `43ac3f4`. Fix `814afc69` pushed and verified green in run 44498147410; red entries resolved, unavailable entries carried forward. |
