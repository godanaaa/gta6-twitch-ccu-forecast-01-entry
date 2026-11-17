[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/godanaaa/gta6-twitch-ccu-forecast-01-entry/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/godanaaa/gta6-twitch-ccu-forecast-01-entry/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

# GTA VI Twitch CCU forecast

`main.py` reads every `*.in` case from `MAKEFUN_INPUT_DIR` (default `/input`) and writes `<id>.out` JSON into `MAKEFUN_OUTPUT_DIR` (default `/output`). It uses Python 3.13's standard library only and needs no network or credentials.

## Model and cutoff

The hour-one known print anchors each forecast. Past comparable launch curves supply log viewer ratios by hour, weighted for first-hour scale, recency, and console-only platform, then capped, median-aggregated, smoothed, and blended toward a flat curve. The recorded LOO grid selected `A=0.0` and a sigma floor of `0.10 * sqrt(hour - 1)`. Spread comes from the weighted launch-ratio standard deviation with a time-growing floor. A conservative decline in the final half-hour can lower only hours 2–6. Pre-release history never raises the anchor: the forecast remains anchored to the known hour-one print.

Target `history` and `history_hourly` are filtered against `checkpoint` before use. Comparable launches are past launches (2018–2026) whose full release-day curves are legitimate training data; their later hourly points do not constitute target-case leakage. The target's forecast truth is never read. The `streams` and `categories_hourly` fields are ignored because the sandbox has no Twitch access or credentials.

The competition kit's rules take precedence over Ryan's brief: output quantiles are 5/25/50/75/95 percent, and scoring uses natural log of raw viewer counts (`ln`), not `log1p`. The requested live Twitch ingestion system is a deliberate deviation because the grader is offline and the supplied case already contains permitted data.

## Run locally

```sh
MAKEFUN_INPUT_DIR=/path/to/input MAKEFUN_OUTPUT_DIR=/path/to/output python3 main.py
```

## Validation

Run `/home/hatch/workspace/gta6-validation/validate.py` to check practice output shape, repeatability, cutoff handling, runtime, and pooled comparable leave-one-out pinball loss against the house persistence baseline. Its report is `/home/hatch/workspace/gta6-validation/report.txt`. The final shipped blend and sigma floor are chosen by the validation sweep; the measured winner in this session was `A=0.0`, floor `0.10` (LOO loss 0.489671 versus 0.929650 baseline).

## Limitations

Launch comparables are a small and imperfect analogue set. The scale weighting gives larger past launches more influence for a much larger target, but cannot model unprecedented external events or platform-specific viewing behavior. Quantile spread uses a normal-style log-space approximation around an empirical median curve.
