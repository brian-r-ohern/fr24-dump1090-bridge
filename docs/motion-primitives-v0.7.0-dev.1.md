# Implemented motion primitives — v0.7.0-dev.1

This is the calculation contract for the preview's actual implementation in `motion_state.py`. It is intentionally explicit so users need not read code. Thresholds are provisional and can be tuned in later local builds. This preview implements basic states, not holding, orbit, formation, CPA or destination-divergence detectors.

## Source eligibility

| Input mode | Motion analytics | Reason / timing |
| --- | --- | --- |
| SBS/BaseStation TCP | Enabled | Position receipt time is tracked privately; altitude-field receipt time is separate |
| Standard dump1090/readsb aircraft.json | Enabled | Position time is upstream snapshot `now` minus `seen_pos` when available |
| FR24 flights.js | Excluded | Two-decimal coordinate precision is too coarse for this preview's short-window primitives |
| FAA SWIM TFMS | Excluded | Sparse position cadence and limited motion metadata; no motion samples or primitive labels are collected |

All four feed modes retain their existing feed, map, density and source-specific range behavior. Destination ETA remains an independent map feature, including for TFMS and flights.js; its accuracy remains limited by the last reported position, destination and speed.

## Observation admission and time

Only numeric, finite coordinates within latitude ±90° and longitude ±180° qualify. Boolean/string coordinates are rejected. The engine receives copies/references without modifying the normalized feed.

Time priority is private position timestamp (SBS), then upstream `now - seen_pos`, then source snapshot time. If there is no position-age timestamp, identical coordinates are conservatively treated as repeated position evidence, even if a new snapshot is published. A changed position uses snapshot time and is labelled `snapshot_position_change`; this does not prove its true source-report time.

Timestamped identical positions can be genuinely independent reports. A same-coordinate sample within 0.25 seconds of the previously retained position timestamp is considered a duplicate, accommodating rounded `seen_pos`. Other non-increasing timestamps are rejected as out of order. Future timestamps more than five seconds beyond receipt time, or timestamps at/before epoch zero, are rejected.

Retain at most one sample per aircraft every five position-time seconds; intermediate valid updates are counted as throttled. Counters therefore describe the analytics input after Bridge publication/sampling, not all radio messages. Position reports may be omitted between snapshots. This is bounded analytical sampling, not an archival recorder.

## Continuity and storage limits

| Rule | Preview value |
| --- | --- |
| Minimum retained position interval | 5 seconds |
| Analysis recomputation interval | At most once per 5 receipt-time seconds per aircraft |
| Active analysis window | Latest 60 position-time seconds |
| Minimum window support | 5 retained position samples spanning at least 30 seconds |
| Position freshness for displayed primitives | 15 seconds |
| Gap reset | More than 30 position-time seconds between retained samples |
| Implausible step reset | Implied spherical ground speed exceeds 1,500 knots |
| Raw history | At most 600 position-time seconds and 128 samples per aircraft |
| Completed primitive summaries | At most 64 per aircraft |
| Tracked aircraft cap | 1,024; least-recently accepted track evicted at capacity |
| Inactive-track expiry | More than 300 seconds since last accepted receipt |

A gap or implausible step ends active primitives and starts a new segment. Do not derive a leg across the reset. A private occurrence change also resets a segment when an occurrence key is provided; current ADS-B adapters do not supply a reliable flight-occurrence key. Consequently this short-lived engine must not be interpreted as complete flight-history segmentation.

Motion state and primitive summaries are **in memory only**. Restart/reinstall clears them. Density/range persistence and settings recovery are unchanged. Long patterns may eventually require retaining more event context; these limits do not claim to detect a 50-mile racetrack yet.

## Position-derived motion

For adjacent retained samples `(lat1, lon1, t1)` and `(lat2, lon2, t2)`, compute spherical great-circle distance `d` with Earth radius 6,371,008.8 m and initial bearing clockwise from North. Longitude differences wrap across ±180°. Ground speed is:

```text
dt = t2 - t1
speed_knots = d / dt / 0.5144444444444445
interval_time = (t1 + t2) / 2
```

A leg must move at least 25 m to support speed/course trends. Course additionally requires derived speed ≥30 knots. Low-displacement legs provide no reliable course and are omitted from horizontal trend fits. At least four qualifying legs and a leg-midpoint span of at least 25 seconds are required for horizontal primitives.

These values estimate average ground motion over an interval. The latest speed/course metric is the latest eligible leg's value; it is not an instantaneous aircraft-heading/airspeed measurement. Reported `gs`, `track` and `baro_rate` remain in the feed but are not used to establish these motion primitives. They can be compared with the independent estimates during testing.

Course is unwrapped by accumulating signed shortest differences in `[-180°, 180°)`. A large unobserved turn is not recovered by this operation. Gaps and sparse/ambiguous geometry are limitations, not evidence of the interpolated path.

## Trend fitting

Use an equally weighted ordinary least-squares line for `(time, value)` pairs. Subtract the first timestamp before fitting to avoid unnecessary epoch-scale cancellation. For centered times `x` and values `y`:

```text
slope = sum((x - mean(x)) * (y - mean(y))) / sum((x - mean(x))**2)
prediction = mean(y) + slope * (x - mean(x))
residual_RMS = sqrt(mean((y - prediction)**2))
range = max(y) - min(y)
```

At least three pairs are needed to produce a trend metric. Primitive eligibility still requires the larger support thresholds above. Equal weighting means this preview is not a robust outlier estimator or a time-weighted filter. Thresholds and fitted residuals should be reviewed with live data before a public release.

## Primitive definitions

| Primitive | Entry criterion | Continuation / other conditions |
| --- | --- | --- |
| Climbing | Fitted observed-altitude slope ≥300 ft/min | Once active, continue at ≥200 ft/min; altitude RMS residual ≤150 ft; absolute rate ≤10,000 ft/min |
| Descending | Fitted observed-altitude slope ≤−300 ft/min | Once active, continue at ≤−200 ft/min; same altitude-fit checks |
| Level altitude | Absolute fitted altitude slope ≤150 ft/min | Same altitude-fit checks; values between level and climb/descent thresholds may remain unclassified |
| Accelerating | Ground-speed slope ≥0.15 knots/s | Once active, continue at ≥0.10 knots/s; speed RMS residual ≤8 knots |
| Decelerating | Ground-speed slope ≤−0.15 knots/s | Once active, continue at ≤−0.10 knots/s; same speed-fit check |
| Stable speed | Speed range ≤10 knots and absolute fitted slope <0.10 knots/s | Speed RMS residual ≤8 knots; this is not an airspeed/energy assessment |
| Turning right | Unwrapped ground-course slope ≥0.50°/s | Once active, continue at ≥0.30°/s; course RMS residual ≤8°; ≥80% of adjacent eligible-course intervals must turn right at ≥0.30°/s |
| Turning left | Unwrapped ground-course slope ≤−0.50°/s | Once active, continue at ≤−0.30°/s; same residual gate; ≥80% of adjacent eligible-course intervals must turn left at ≥0.30°/s |
| Stable course | Unwrapped course range ≤8° | Course RMS residual ≤8°; requires reliable course support |
| Steady flight | Level altitude + stable speed + stable course simultaneously | Collapse these component labels into one popup label; components remain available in the API |

Positive course-change rate denotes a right turn because bearings increase clockwise from North. Bank angle, roll acceleration, load factor and intent are not measured. “Steady flight” does not establish cruise phase. “Accelerating” denotes an observed ground-speed trend, not constant thrust or a formally established constant-acceleration maneuver.

## Altitude provenance and freshness

Prefer numeric `alt_baro`, then `alt_geom`. Do not mix references in an altitude trend: use only the contiguous suffix with one usable reference. It needs at least five altitude-bearing retained samples spanning 30 seconds. Explicit `ground` inhibits all primitives on the latest sample.

For SBS, an altitude-field receipt timestamp must be within 15 seconds of position time. A stale preferred barometric value is excluded; the engine does not silently substitute another reference within that sample. Missing/stale altitude breaks vertical support without preventing horizontal estimates.

Standard aircraft.json usually lacks independent altitude timestamps. In that case the snapshot altitude is assumed associated with the sampled position and labelled `snapshot_assumption`. Retained/stale fields can therefore affect vertical estimates; the label and provenance must not be interpreted as proof of co-timed measurements. Assigned-altitude metadata is never used as observed altitude.

## State, duration and completed events

Quality is `warming_up` until the independent-position count/span threshold is met; `supported` when one or more primitive criteria qualify; otherwise `insufficient_or_unclassified`. More than 15 seconds of position age yields `stale`, hiding active labels while preserving metrics and timestamps for diagnostics. No numeric confidence probability is emitted.

`duration_seconds` describes the interval from the first supporting window's start to the latest retained position, not how long the detector has been displaying a label. `detected_at` is the first evaluation where criteria qualified. Vertical primitives begin support at the altitude suffix start. Continuous support duration can exceed the raw 60-second analysis window while the criteria continue to hold.

Completed events retain primitive name, segment, first-supported/detected/last-supported times and end reason. When criteria cease, last-supported time is the preceding analyzed position time. Gap/discontinuity resets end events at the preceding retained sample. Samples between evaluations do not independently establish continued primitive qualification.

## API and map

- `/motion/status`: source eligibility, caps, exact thresholds, counters, track/sample/event counts, last collection-batch time and sanitized error type.
- `/status`: includes the same diagnostics in `motion`.
- `/motion`: bounded current derived states for tracked aircraft; no raw coordinates/history are exposed.
- `/motion?hex=abc123`: one aircraft; comma-separated queries allow up to 256 identifiers.
- `/motion?hex=abc123&events=1`: additionally returns bounded completed primitive summaries.

The map obtains motion states at most every five seconds without blocking ordinary aircraft refresh. Popups show supported basic labels, source-position staleness and derived turn/vertical trends. A failed motion fetch discards its cache; locally aged states cannot indefinitely remain fresh. Excluded input modes omit motion rows. Motion/diagnostic requests are not counted as aircraft-feed consumers.

## Validation scope

Synthetic tests cover steady flight, signed turns across North, climb/descent, ground-speed trends, timestamp duplicates, throttling, out-of-order/future input, gaps/discontinuities, bounded/expiring state, stale altitude and antimeridian motion. HTTP checks exercise eligibility, query bounds, unchanged aircraft feeds, independent density collection and source publisher hooks. Browser-code checks exercise labels, stale cache, exclusions and fetch-failure isolation.

Live SBS/aircraft.json validation remains required. Pay particular attention to noisy reported positions, altitude-field age, coarse upstream rounding and state transitions. No pattern detection or safety conclusion follows from passing these foundational tests.

## Development summaries and “Warming up” — dev.2

For SBS and aircraft.json, collection logs `[INFO] Motion summary` on the first publication and then at most once every 60 seconds. The summary counts currently retained tracks by quality and each active primitive. It contains no aircraft identifiers, positions or credentials. It is a current-state snapshot, not a count of detections during the preceding minute. One aircraft may contribute to several primitive counts; quality counts partition the tracked total. Stale tracks contribute no active labels. TFMS and flights.js emit no motion summaries.

**Warming up** means the latest analytical window has fewer than five accepted samples or spans less than 30 seconds. Sampling is limited to one accepted observation per five seconds, so in practice roughly seven regularly spaced samples are needed to span 30 seconds. Duplicate snapshots, rejected positions and throttled reports do not advance that support. The window is at most 60 seconds. A gap exceeding 30 seconds, an implausible position jump or a recognized occurrence change starts a new segment; warming up may recur after any such reset. Explicit ground state also prevents eligibility and currently uses this same quality label. This label describes analytical eligibility, not receiver connection health.

**Supported** means at least one primitive meets its criteria. **Insufficient or unclassified** means the general history requirement is met, but available fields or motion do not support a primitive. **Stale** means the latest accepted position is older than 15 seconds; labels are withheld. Missing or stale altitude can prevent vertical labels even when horizontal history is ready.

“Observed vertical trend” is the least-squares altitude slope over the recent supported window; “Vertical rate” is the source-reported field. They need not match during changing descent/climb or asynchronous reports. “264s support” is elapsed support for a continuing primitive, not a 264-second fitting window.
