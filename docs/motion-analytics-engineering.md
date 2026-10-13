# Motion Analytics — Living Engineering Notes

Status: design draft, October 10, 2026. Companion to [the v0.7 roadmap](motion-pattern-roadmap.md). This document records mathematical definitions, candidate heuristics, validation results and decisions as each increment is built. The basic motion engine and primitives are implemented in 0.7.0-dev.1; circle fitting and pattern grammar here remain reference designs. See [Implemented motion primitives](motion-primitives-v0.7.0-dev.1.md) for the actual preview formulas, thresholds, timings and limits. Thresholds below are experiments, not frozen defaults.

## Pipeline and contracts

| Stage | Input | Output | Key constraint |
| --- | --- | --- | --- |
| Observations | Source identity, source/receipt timestamps, position, altitude reference, reported motion | Distinct ordered samples with freshness and continuity flags | Repeated publication of the same source report is not new motion evidence |
| Motion states | Valid samples in one continuity segment | Velocity, speed, vertical rate, signed course change, quality | No measured derivative across an observation gap |
| Primitives | Motion states over sustained windows | Stable leg, turn, climb/descent, speed trend, reversal, GAP | Tolerances, minimum support and hysteresis are explicit |
| Pattern grammar | Primitive sequence plus observed geometry | Candidate orbit, racetrack, parallel passes, figure-eight | Sequence alone is insufficient; test geometry and repetition |
| Geometric patterns | Supported candidates over time | Provisional/established/exited result with evidence | Intent and mission remain separate interpretations |

Increment 0.7.0 establishes the first three contracts. Increment 0.7.1 evaluates individual geometry. Later increments add destination divergence, pair predictions and formations without replacing these contracts.

## 1. Observation time and continuity

Retain `aircraft_id`, flight-occurrence key where available, `source_time`, `received_time`, latitude/longitude, observed altitude/reference and optional reported motion. Keep timestamps for individual fields when available; SBS messages update different fields independently. If source time is absent, use receipt time and mark that limitation.

Deduplicate known source reports before extracting derivatives. A stationary aircraft can produce genuinely new reports with unchanged coordinates, so coordinate equality alone is insufficient evidence of a duplicate. Out-of-order samples must not silently create negative elapsed time. State eligibility uses age and supported ADS-B cadence; it cannot reuse the Bridge's one-second publication period as an independent source-report interval. TFMS and flights.js are excluded from the motion engine. These increments do not expand motion-source eligibility.

Start a new analytical segment after a configured gap, identity/occurrence change, or physically implausible discontinuity. Store the reason. Never smooth through the break. Historical map rendering may connect plausible endpoints without making that connection eligible as observed motion.

Use bounded raw buffers and longer-lived primitive summaries. A fixed five-minute window can miss a large racetrack or slow orbit. Retention must accommodate the intended pattern duration, or return insufficient history; compact summaries do not recreate missing turn samples.

## 2. Local coordinates and motion

For a small local pattern, project positions into a consistent East/North plane. A first-order approximation around latitude/longitude `(phi0, lambda0)`, with angles in radians, is:

```text
x = R * cos(phi0) * wrap_longitude(lambda - lambda0)
y = R * (phi - phi0)
```

Choose units once (metres and seconds internally). This approximation has no fixed accuracy guarantee across large extents or high latitudes. Validate it over the detector footprint; use a suitable geodesic/local tangent projection for larger patterns. Do not mix different projection origins when comparing centers. Longitude wrapping must handle the antimeridian.

For eligible consecutive samples, `vx = delta_x / delta_t`, `vy = delta_y / delta_t`, speed `v = hypot(vx, vy)`, and ground course `theta = atan2(vx, vy)` clockwise from North. Position-derived values represent average motion over the interval. They are not instantaneous measurements; attribute them to an interval/midpoint and compare reported values at compatible times.

Compute signed course change as `atan2(sin(theta2-theta1), cos(theta2-theta1))`. Divide by the elapsed time between compatible course estimates for turn rate. Derive acceleration from compatible speed estimates. Vertical rate needs a consistent observed altitude reference. Assigned TFMS altitude is not an observed altitude measurement.

Wrapped differences are ambiguous if more than 180° of turning could occur between observations. Sparse reports can therefore leave turn direction/accumulation unresolved. Return uncertainty instead of unwrapping a presumed path.

## 3. Primitives and segmentation

Estimate trends from several samples and actual elapsed time. A single noisy difference should not trigger a maneuver. Begin with robust/weighted local regressions or another explicitly documented filter; preserve the raw observations for validation. Avoid a filter that makes sharp reversals appear like prolonged smooth turns.

| Primitive | Evidence | Exit / rejection considerations |
| --- | --- | --- |
| Stable leg | Small course variation and line-fit cross-track residual | Sustained turning, excessive residual or GAP |
| Level altitude | Small altitude trend and variation | Reference mismatch, insufficient altitude or sustained vertical trend |
| Climb / descent | Sustained signed altitude slope | Trend fades/reverses, reference changes or GAP |
| Speed trend | Sustained speed slope; constant trend additionally needs low residual/variance | Noise, stale speed, slope reversal or GAP |
| Left / right turn | Sustained signed course change and geometric support | Sign reversal, stable leg or GAP |
| Reversal event | Coherent approximately 180° directional change | Ambiguous sampling, discontinuity or insufficient support |

Each primitive should retain start/end time, sample support, duration, segment id, signed accumulated turn where eligible, fitted geometry/residuals and quality flags. Use separate entry/exit tolerances and a minimum duration to prevent label flicker. Tolerances must account for position precision and reporting cadence.

## 4. Turn centers: curvature center, not sample centroid

An average of arc positions is a **sample centroid**, not generally the center of the turn. For a uniformly sampled semicircle it lies inside the arc away from the circle center. Even a complete circle can have a biased sample centroid when sample spacing is uneven. Use a fitted curvature center and retain fit uncertainty.

For projected arc points, a simple algebraic circle model is:

```text
x_i^2 + y_i^2 = 2*a*x_i + 2*b*y_i + c
center = (a, b)
radius^2 = a^2 + b^2 + c
```

Solve the overdetermined system with a stable least-squares method after translating/scaling coordinates. This is an initial fit, not a production robust estimator. Short/near-collinear arcs can yield unstable centers or enormous radii. Assess design-matrix conditioning, radial residuals, angular support and sensitivity to outliers; consider geometric-distance refinement and robust rejection after validation.

For each candidate arc retain center, radius, radial RMS/robust residual, signed angular sweep, duration, sampling/gap flags and uncertainty estimate. Signed sweep about the fitted center and course accumulation should agree within their uncertainties. Neither an algebraic fit nor a 180°/360° heading total alone proves an orbit.

### Reference fit code

This standalone example uses NumPy for the least-squares solve. It is illustrative and does **not** add NumPy to the App's dependencies. Inputs must already be one valid, ordered, continuity-checked arc in a shared projection. The minimum sample count and conditioning limit are reference guards, not chosen operational defaults.

```python
import numpy as np

def fit_turn_center(points):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 6 or not np.isfinite(p).all():
        return None
    origin = p.mean(axis=0)
    scale = np.sqrt(np.mean(np.sum((p - origin) ** 2, axis=1)))
    if scale <= 0:
        return None
    q = (p - origin) / scale
    A = np.column_stack((2*q[:, 0], 2*q[:, 1], np.ones(len(q))))
    rhs = np.sum(q*q, axis=1)
    params, _, rank, singular = np.linalg.lstsq(A, rhs, rcond=None)
    if rank < 3 or singular[-1] <= 0 or singular[0]/singular[-1] > 1e6:
        return None
    a, b, c = params
    radius_squared = a*a + b*b + c
    if radius_squared <= 0:
        return None
    center = origin + scale*np.array([a, b])
    radius = scale*np.sqrt(radius_squared)
    radial_error = np.linalg.norm(p - center, axis=1) - radius
    return {
        "center": center.tolist(),
        "radius": float(radius),
        "radial_rms": float(np.sqrt(np.mean(radial_error**2))),
        "condition": float(singular[0]/singular[-1]),
        "samples": len(p),
    }
```

The fit returns geometry, not a pattern label or confidence probability. Production acceptance still needs independent angular-support, continuity, temporal, uncertainty and residual gates. NumPy's solver contract is documented in [numpy.linalg.lstsq](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html).

## 5. Center clustering and pattern grammar

### Repeated orbits

Accepted completed arcs should have compatible turn sign, radius and centers. An experimental center gate can compare center distance with both a radius-relative tolerance and estimated center uncertainty. Choose/calibrate those tolerances from test data; do not declare arbitrary fixed metre thresholds authoritative.

Cluster centers only within the same aircraft/flight occurrence and compatible time/continuity context. Validate cluster spread, radii and actual trajectories. A chain of individually nearby centers can drift over a long distance, so connected components alone do not establish a stable orbit center. Require group-wide dispersion or a constrained representative-center gate.

An established repeated-orbit pattern needs more than one supported circuit. Preserve per-circuit evidence rather than counting the same rolling-window fit repeatedly as a new orbit. Wind can distort ground geometry and move fitted centers even during a coordinated airborne orbit.

### Racetrack / holding-like geometry

The candidate grammar is `LEG_A → TURN_1 → LEG_B → TURN_2`, repeating. Legs should be approximately reciprocal and near-parallel; turns should be approximately 180° in a coherent direction and connect the observed legs. Test lateral leg spacing, turn radius, recurrence and closure as supporting geometry. Standard-rate turns are optional evidence, not a requirement.

The two end-turn centers normally form **two spatial groups**, not one. With repeated laps, `TURN_1` centers recur near one end and `TURN_2` near the other. Compare each end's spread/radius, center-to-center orientation against leg direction, and recurring leg geometry. Irregular timings or unequal turn radii reduce support; they do not automatically disprove every holding-like pattern.

A single reversal or one partial racetrack is provisional. Repetition establishes the geometric pattern; it still does not establish an ATC holding clearance. Large 50-mile racetracks require longer support windows than small airport holds.

### Classification lifecycle and precedence

Use candidate → provisional → established → exited/expired states, with explicit evidence and hysteresis. Avoid repeated notifications on each window evaluation. When an established holding-like/racetrack pattern exists, suppress repetitive destination-divergence notifications while retaining the range trend; reassess after exit. Do not suppress divergence solely because one turn has occurred.

Keep observed geometry, primitive events and interpretations separate. A racetrack contains turns and straight legs without requiring competing alerts for each. Missing observations lower eligibility/confidence; a visual interpolated line supplies no detector support.

## 6. Validation ledger

| Case | Expected behavior | Status |
| --- | --- | --- |
| Exact translated 180° arc | Recover curvature center/radius; sample centroid differs | Reference code checked October 10, 2026 |
| Exact translated 360° circuit | Recover curvature center/radius | Reference code checked October 10, 2026 |
| Straight/collinear samples | Reject degenerate circle fit | Reference code checked October 10, 2026 |
| Identical points / invalid coordinates | Reject unusable input | Reference code checked October 10, 2026 |
| Noisy/outlier arcs and short arcs | Quantify fit bias, uncertainty and false acceptances | Required before production gates |
| Irregular cadence, duplicate/out-of-order reports, gaps | No invented angular support or false confidence | Basic timing/gap tests pass in 0.7.0-dev.1; additional ambiguity cases remain planned |
| Repeated orbit / drifting center / racetrack / isolated reversal | Distinguish repetition and geometric families | Planned with increment 0.7.1 |
| Wind-distorted patterns, coarse or irregular ADS-B, departure vectors | Evaluate false positives and source-specific limits | Live validation pending |

## 7. Maintenance rules

Keep this note alongside the code and roadmap. For each increment record implemented formulas, units, actual thresholds, source-specific limits, test fixture IDs/results and unresolved questions. Distinguish experiments from released behavior. Update the ledger when tests run; do not label planned cases as passed. Retain rationale when a threshold or fit method changes.

Review sample-time attribution, memory bounds and computation cost with every added detector. A pattern result should expose enough evidence to explain both acceptance and rejection. None of the geometric labels establishes aircraft intent or operational safety.

## Development summaries and “Warming up” — dev.2

For SBS and aircraft.json, collection logs `[INFO] Motion summary` on the first publication and then at most once every 60 seconds. The summary counts currently retained tracks by quality and each active primitive. It contains no aircraft identifiers, positions or credentials. It is a current-state snapshot, not a count of detections during the preceding minute. One aircraft may contribute to several primitive counts; quality counts partition the tracked total. Stale tracks contribute no active labels. TFMS and flights.js emit no motion summaries.

**Warming up** means the latest analytical window has fewer than five accepted samples or spans less than 30 seconds. Sampling is limited to one accepted observation per five seconds, so in practice roughly seven regularly spaced samples are needed to span 30 seconds. Duplicate snapshots, rejected positions and throttled reports do not advance that support. The window is at most 60 seconds. A gap exceeding 30 seconds, an implausible position jump or a recognized occurrence change starts a new segment; warming up may recur after any such reset. Explicit ground state also prevents eligibility and currently uses this same quality label. This label describes analytical eligibility, not receiver connection health.

**Supported** means at least one primitive meets its criteria. **Insufficient or unclassified** means the general history requirement is met, but available fields or motion do not support a primitive. **Stale** means the latest accepted position is older than 15 seconds; labels are withheld. Missing or stale altitude can prevent vertical labels even when horizontal history is ready.

“Observed vertical trend” is the least-squares altitude slope over the recent supported window; “Vertical rate” is the source-reported field. They need not match during changing descent/climb or asynchronous reports. “264s support” is elapsed support for a continuing primitive, not a 264-second fitting window.

## Motion exploration — implemented in dev.3

The Motion panel counts positioned aircraft currently present in the map feed. Minute-summary logs count all retained engine tracks, so totals can differ. Filters match any selected label; All clears individual selections, selecting a label clears All, and no selection hides aircraft. Fit aircraft uses the visible subset. Filters change presentation only; feeds, density and analytics continue. On page reload, All is selected and colors are off.

Color priority: turns (purple), descending (orange), climbing (green), decelerating (pink), accelerating (yellow), steady flight (cyan). Other/stale/warming tracks keep ordinary coloring. Motion color replaces military green, but its popup label remains; O/D badges and closest glow remain. This is display priority, not detector precedence. Counts overlap. Local cache aging removes stale tracks from active-label counts and colors between requests. The panel is hidden for excluded sources.

Tracker aggregate, closest and military sensor IDs are configurable; previous names remain defaults. The aggregate sensor requires total_aircraft. Optional closest/military failures do not block route metadata. Diagnostics report entity IDs, safe reason/type and HTTP status, excluding exception messages, URLs and credentials. Aggregate failure warnings occur at most once per minute. Save and restart after changing entity settings.

## Arrival model — design context (dev.11 preview implemented below)

### Output and required evidence

The current estimate is great-circle distance divided by current reported ground speed, not touchdown time. Dev.3 labels position ages over 15 seconds as last-known-position estimates and marks unknown age. Speed-field freshness is not independently available; this label does not certify fresh speed.

A future model should retain that baseline and add **Estimated arrival · modeled descent/approach** as a scenario interval, with an exposed profile and assumptions. Interval endpoints are not statistical confidence limits. No profile speeds, phase transitions, descent rates or routing allowances are frozen yet.

Require fresh position, positive ground speed, destination coordinates/elevation, observed altitude with reference, and trustworthy aircraft category/type where available. The compact airport lookup currently lacks elevation: add validated elevation/provenance first. Pressure altitude and airport elevation can be inconsistent under nonstandard pressure; expose that approximation or require compatible geometric altitude. Missing inputs should fall back to direct time, not invented defaults.

### Coupled distance and altitude calculation

Model remaining cruise, initial descent, terminal descent/deceleration and final approach. Integrate travel and altitude loss simultaneously:

```text
remaining_height_ft = max(observed_altitude_ft - destination_elevation_ft, 0)
distance_nm_step = ground_speed_knots(t) * dt_seconds / 3600
height_loss_ft_step = descent_rate_fpm(t) * dt_seconds / 60
arrival_time = sum(phase durations), satisfying both distance and altitude constraints
```

Do not add full descent duration to an overlapping travel estimate. Losing 28,000 ft at constant 1,500–3,000 ft/min takes 9.3–18.7 minutes; these are arithmetic scenarios, not universally appropriate rates. Observed descent slope is evidence but extrapolating it unchanged to touchdown is not a validated forecast. Account explicitly for phase changes and level-offs.

A jet profile can initially evaluate about 3 NM per 1,000 ft lost as a plausibility check. It does not prove the aircraft's future path. If direct distance cannot satisfy the candidate altitude/speed profile, mark the scenario unresolved or requiring extra route distance rather than force an impossible descent. Apply documented category-specific deceleration/approach profiles; do not extrapolate measured deceleration indefinitely toward zero.

The US 250-knot restriction below 10,000 ft concerns indicated airspeed, not the ground speed we have. Do not impose it as a universal ground-speed cap or apply a US rule to every destination. Unknown wind and indicated/true/ground-speed conversion remain assumptions. 130–150 kt is not an all-aircraft approach default.

### Route and interpretation limits

Airport-center distance cannot establish runway, STAR, vectors, approach direction or holding. Extra path length is an explicit scenario allowance, not an observed route. Initially limit modeled arrivals to suitable fresh inbound tracks; retain direct time or mark unavailable for outbound/tangential, holding-like or destination-divergent motion. Steady flight alone does not establish cruise/arrival phase. Never extrapolate derivatives across observation gaps.

### Validation before defaults

Evaluate jets, turboprops and light aircraft separately. Include airports above sea level, short distance/high altitude, stale/missing fields, strong winds, level-offs, departure, wrong/stale destination, vectors and holds. Compare successive predictions against observed arrival trajectories or independently established arrival times; loss of reception is not evidence of landing. Record bias, absolute errors, scenario-interval coverage and fallback frequency. Freeze defaults only after documenting evidence; display measured versus assumed inputs distinctly.

References: [FAA jet descent planning, Instrument Procedures Handbook chapter 3](https://www.faa.gov/sites/faa.gov/files/regulations_policies/handbooks_manuals/aviation/instrument_procedures_handbook/FAA-H-8083-16B_Chapter_3.pdf) and [14 CFR 91.117, indicated-airspeed restrictions](https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-B/subject-group-ECFRe4c59b5f5506932/section-91.117). These establish constraints, not validation of this proposed estimator.

## v0.7.0-dev.4 — Source eligibility and display

SFDPS is a local surveillance-view source in this increment, not a motion source. Motion eligibility remains SBS and standard aircraft.json only; FAA TFMS/SFDPS and coarse flights.js are excluded. SFDPS reported speed/altitude and its map course do not bypass these gates. No density state is created for SFDPS. Its parser/continuity/local-view contract and validation are in [dev.4 notes](v0.7.0-development-validation.md#original-record-v070-dev4-testingmd).

Aircraft SVGs and Leaflet markers grow from 24 px to 36 px, with center anchors adjusted from 12 px to 18 px. Screen size stays constant with zoom; motion thresholds, filters and color priority are unchanged. Both FAA sources now reject dump1090 feed output and general data exports. Local map display state is embedded in its HTML rather than exposed through a separate aircraft feed API.


## dev.5 diagnostic instrumentation

Motion diagnostics appear at most once per minute beside the ordinary Motion summary. They include interval counter deltas, cumulative rejection reasons, retained samples/events, and latest batch time. Fixed categories: missing coordinates, invalid coordinate values (including non-finite/non-numeric values), out-of-range coordinates, nonpositive selected position time, and future selected position time. Reasons sum to `invalid`; duplicates, throttled updates, gaps, out-of-order observations, and discontinuities stay separate. Missing coordinates are often expected for partially populated SBS aircraft. Counts represent snapshot attempts, not distinct aircraft or malformed SBS messages. Malformed optional timestamp metadata still follows existing fallback rules; it is not newly rejected. First verbose delta covers activity since startup (or since the prior verbose summary), not necessarily exactly one minute.

Density diagnostics break down lock wait, database preparation, SQLite execute/fetch, Python aggregation, display aggregation and GeoJSON geometry creation. SQLite time includes database work, I/O and scheduling; it is not a measurement of disk time alone. `aggregated_rows_read` counts grouped SQL results, not scanned underlying observations. Monthly timing entries identify which retained chunk consumed time, without logging coordinates. Geometry time is separate from `query_seconds`; `geojson_seconds` includes query and geometry. HTTP serialization/network/browser rendering are outside those timers. Cached queries may have zero SQL time.



## dev.6 SQL diagnostic boundary

Density query plans and approximate SQLite VM work are diagnostic evidence, not aircraft observations. Motion rejection semantics and current geometry thresholds remain unchanged. See [dev.6 testing](v0.7.0-development-validation.md#original-record-v070-dev6-testingmd).


## dev.7 density execution optimization

Viewport-first numeric aggregation changes query work only. Motion state/admission and empirical observation statistics remain unchanged. See [validation and live tests](v0.7.0-development-validation.md#original-record-v070-dev7-testingmd).


## dev.8 empirical density acceleration

Parent-day statistics are exact aggregates of observed base cells, not inferred aircraft motion. Passage aggregation remains the sum of base-cell passages. Display tiles are temporary snapshots with explicit generation times. Neither parent aggregation nor cache reuse creates credits in unobserved fine cells. See [dev.8 implementation and validation](v0.7.0-development-validation.md#original-record-v070-dev8-testingmd).


## dev.9 — SFDPS observation and quality contract

This section supersedes dev.4's SFDPS exclusion. TFMS and flights.js remain excluded. SFDPS requires the parser's timezone-qualified surveillance `positionTime`; the publisher passes its exact epoch to the motion engine rather than generating a timestamp on each one-second publication. Repeated retained snapshots are deduplicated. Older reports are rejected by admission/continuity checks; a change to the GUFI-derived local identity creates a different track.

| Parameter | SBS / aircraft.json | SFDPS preview |
| --- | ---: | ---: |
| Analysis window | 60 s | 120 s |
| Minimum independent samples | 5 | 5 |
| Minimum observed span | 30 s | 60 s |
| Gap reset threshold | 30 s | 45 s |
| Position/field freshness | 15 s | 45 s |
| Movement floor | 25 m | 25 m |

Ground speed and course use observed position differences divided by actual report intervals. `actualSpeed` and ambiguous `trackVelocity` axes do not substitute for ground vectors. Altitude fits retain `sfdps_reported_altitude` provenance; no barometric/geometric datum equivalence is established. Thresholds are experimental, based on the expected more sparse report cadence, and must be evaluated with live logs. No turns, acceleration or vertical change is inferred across a segment reset or observation gap.

SFDPS density uses the existing Bridge snapshot convention, not motion deduplication: an eligible retained reported-position cell can receive repeated credits. Paths between observed positions never receive density credit. Local motion state is embedded in the viewer HTML; the general `/motion` route is denied for both FAA sources. `/motion/status` exposes bounded aggregate diagnostics only.

## dev.9 — Density cache inventory semantics

`/traffic-density/cache-status` accepts the same source/date/band/grid/viewport identity as cached map views. It reports valid cached tiles, missing tiles (`to_build`) and expired or clock-invalid tiles (`stale`). It neither queries SQLite nor builds geometry or parent grids. TTL is two hours; absent/capacity-evicted tiles are missing. Views over the tile limit or without a usable bbox are explicitly uncached. A completed view returns its current inventory; old request hit/miss totals remain available in diagnostics rather than being relabeled as pending work.

The browser checks inventory after pan/zoom/band changes and once a minute while enabled. Displayed cell count/time remain associated with the previous layer until a load succeeds; a pending-view label makes this explicit. Revision/sequence guards prevent stale inventory requests from overwriting a completed load. Enabling the layer loads automatically; viewport/filter changes do not silently force rebuilding.


## dev.10 — Explainable speed diagnostics (thresholds unchanged)

Each analysis window keeps a compact `speed_diagnostics` result, not a second raw-track database. Speed legs use observed spherical displacement divided by actual position time difference. The 25 m displacement floor, independent-sample admission, gap reset and original OLS fit remain unchanged. Window-derived speed min/median/max and raw range, fit RMS residual and slope expose their behavior. Intervals are between accepted motion position samples; source throttling may make them longer than raw report cadence.

Stable-speed blockers mirror every existing gate, including position support, usable leg count/span, residual <=8 kt, range <=10 kt and absolute slope <0.1 kt/s. Multiple blockers can coexist. On SFDPS, the unchanged usable-leg midpoint span must reach minimum_span_seconds (60) minus sample_interval_seconds (5), i.e. 55 seconds. With six reports 12 seconds apart the position span is 60 seconds, but leg-midpoint span is only 48; one more report can establish support. Diagnostics expose both spans rather than changing this gate.

Reported speed is admitted for comparison only when numeric, nonnegative, bounded by the existing 1,500 kt limit and sufficiently aligned with the position field time where known. SBS field receipt timestamps and SFDPS report timestamps are retained; sources without a speed field timestamp are labeled snapshot assumption. The comparison subtracts the latest admitted reported value from the latest leg-derived speed. That leg is an interval average while the reported field may describe a different instant/quantity. SFDPS actualSpeed remains unverified, never substituted into ground-vector detection.

Verbose logs aggregate current fresh tracks: blocker counts and min/median/max distributions of latest reported/derived speeds, their differences, per-track speed range/residual/trend and per-track median accepted intervals. Aircraft IDs/positions/routes are not logged. Popup details are opt-in through verbose_logging, preserve source semantics, and remain local viewer data on FAA sources. Normal motion summaries remain unchanged. No detector thresholds or event persistence semantics change.

## dev.10 — Automatic cache-only loading

A debounced viewport/filter inventory check may automatically load a pending view only when every tile is fresh and present. `cached_only=1` on a local map-view request rechecks inventory under the same lock used to consume cache entries. If a clear/restore/expiry invalidates it, HTTP 409 leaves the old rendered layer pending. This path does not build SQL results/rollups; missing/stale views require manual Load density. Refresh now remains an explicit cache bypass. Completed/current views do not auto-load repeatedly on the minute inventory timer.


## dev.11 — Speed-source selection and provenance

The FAA SFDPS Consumer Reference Manual v2.1.4 (December 26, 2017), Appendix B, Track Information [TH], maps `groundSpeed_05b` and track-velocity information to `flight/enRoute/position/actualSpeed/surveillance`. This is the parser's actual path; units must be KNOTS. Accordingly dev.11 replaces the earlier unverified-speed label with **reported ground speed**. The document establishes field meaning, not ERAM's internal estimator/filter algorithm.

Reference: https://nsrr.faa.gov/sites/default/files/enroute-ad-pub-v2/SFDPS%20Data%20Consumer%20Reference%20Manual%20v2.1.4.pdf (mapping, printed pp.178–179; track position/velocity, pp.75–76).

For SFDPS, choose the contiguous suffix of independent report-time samples with usable reported speed. Missing/stale speed at the latest sample selects the independently maintained position-derived legs instead. A speed field is usable when numeric, finite, 0–1,500 kt, and its field timestamp is within the source's 45 s field-freshness tolerance of position time. SFDPS publisher uses report epoch for both fields; retained snapshots remain duplicates. Reported speed is not presumed independent of upstream track filtering.

| Detector | SFDPS input | SBS / aircraft.json input |
| --- | --- | --- |
| Stable speed, acceleration/deceleration | Fresh reported ground speed; derived fallback | Position-derived ground speed, unchanged |
| Course / turns | Independent position/time legs | Independent position/time legs |
| Vertical trend | Observed altitude and provenance | Observed altitude and provenance |
| Steady flight | Level altitude + stable selected speed + stable observed course | Existing three-primitives conjunction |

Reported-speed fitting requires at least five usable reports spanning 60 s, plus the existing position quality gates. Position-derived fallback retains the original midpoint support requirement (four legs, 55 s midpoint span for SFDPS). Both use the same OLS residual/range/trend limits: residual <=8 kt; range <=10 kt and abs(slope)<0.1 kt/s for stable speed; acceleration/deceleration enter at 0.15 kt/s and exit at 0.1 kt/s. A reported suffix with insufficient support warms up; it is not blended with derived legs to satisfy support.

`state.speed_basis`, metrics and speed-dependent primitives expose `reported_ground_speed` or `position_derived_ground_speed`. On basis switches, stable-speed, accelerating, decelerating and steady-flight events close with `speed_basis_changed`. Geometry/altitude events continue only if their own criteria remain supported. Gaps/discontinuities still reset the track normally. TFMS/flights.js remain excluded. Diagnostics retain derived speed min/median/max/range/residual/trend independently from selected-analysis values; blocker counts now explain the selected basis. Aggregate logs include basis counts; no aircraft identity/positions are added to logs or FAA feed APIs.

## dev.11 — Experimental coupled arrival calculation

This implements a deliberately bounded first experiment, not validated flight-performance prediction. Retain `T_direct = D_airport_center / reported_ground_speed * 60`. SFDPS can use this baseline now that its ground-speed field mapping is established. Unknown position age and stale position remain labeled on the baseline. A modeled estimate requires supported/fresh motion, position age <=15 s for ADS-B or <=45 s for SFDPS, admitted reported speed 100–650 kt, validated airport elevation, recognized transport-jet type metadata and fresh observed altitude provenance. No aircraft profile is inferred from speed, airline, callsign or altitude. Initial matching covers recognizable Boeing/Airbus transport identifiers/names, E170/175/190/195/E75L/E75S and CRJ identifiers; unsupported types remain direct-only.

Use compatible engine altitude reference: geometric when the engine's fresh observed reference is alt_geom, otherwise observed reported altitude. Set `H = altitude_ft - airport_elevation_ft`; require 200<=H<=50,000 ft. Reported/pressure altitude minus airport elevation is explicitly an approximate height because datum/pressure differences remain unknown. Missing elevation never becomes zero. Aircraft must be within 60 degrees of the destination bearing using fresh position-derived course; defer when climbing >300 ft/min or turning >0.3 deg/s. These gates prevent obvious departures/tangential/turning examples from receiving a direct arrival model, but do not establish future route or intent and cannot detect all holding patterns.

Two transport-jet scenarios use these experimental assumptions, with altitude bands measured **above the airport**, not regulatory MSL speed boundaries:

| Phase | Height interval | Faster descent | Faster speed endpoint | Slower descent | Slower speed endpoint |
| --- | --- | ---: | ---: | ---: | ---: |
| Initial descent | Above 10,000 ft to 10,000 ft | 3,000 ft/min | 250 kt GS | 1,500 ft/min | 230 kt GS |
| Terminal slowdown | 10,000 ft to 3,000 ft | 1,500 ft/min | 180 kt GS | 1,000 ft/min | 160 kt GS |
| Final approach | Below 3,000 ft to airport elevation | 900 ft/min | 150 kt GS | 600 ft/min | 130 kt GS |

Skip phases above the current height. Each active phase starts at the previous phase's ground speed (first phase starts at current reported GS) and linearly reduces it to min(start_speed, assumed endpoint), so the model never accelerates to reach a profile speed. For height loss `delta_h` and descent rate `r`:

```text
phase_minutes = delta_h / r
phase_distance_nm = ((start_gs + end_gs) / 2) * phase_minutes / 60
descent_minutes = sum(phase_minutes)
descent_distance_nm = sum(phase_distance_nm)
cruise_minutes = max(0, direct_distance_nm - descent_distance_nm) / current_gs * 60
scenario_minutes = cruise_minutes + descent_minutes
```

This couples altitude loss, travel and deceleration. It does not add an overlapping complete descent time to the direct estimate. No legal 250 kt IAS rule is imposed on ground speed. There is no measured wind correction, aircraft-specific performance model, runway/STAR/vector geometry, level-off or hold allowance. Airport-center distance is not runway-threshold distance. The phase endpoints/rates are transparent preview assumptions, not universal performance values or evidence of a safe path.

If either scenario requires more descent/slowdown distance than the direct distance (0.05 NM arithmetic tolerance), do not fabricate a numeric arrival time: label extra route distance needed and show the scenario's additional distance. Otherwise show min/max scenario minutes and UTC arrival times, explicitly a scenario bracket rather than statistical confidence. Wrong/stale destination, missed approach or unobserved future instructions can invalidate either scenario. Unsupported aircraft and missing/stale inputs keep baseline ETA with the specific modeled-arrival fallback reason. SFDPS often lacks usable type metadata; those tracks intentionally remain direct-only.

Airport lookup now retains validated numeric elevation_ft (-1,500 to 30,000 ft) and airport_type from datasets/airport-codes. Closed/invalid-coordinate rows are excluded; unknown elevation remains null/absent. Snapshot updated 2026-10-12, commit 68f7adaf362cea1d7b03a9a80653dfc338a426d5; hashes and reproduction details are in third_party/airports/provenance.json. Dataset is ODC-PDDL-1.0; Bridge remains Apache-2.0. No live external lookup is performed at runtime. FAA arrivals remain local HTML viewer content; no derived feed/export API is created.

Synthetic tests check simultaneous distance/height conservation, slowing versus direct ETA, elevation offsets, infeasible short paths, profile/freshness/course/climb/turn gates and SFDPS freshness. Live validation must compare forecasts against known arrival observations and record bias/absolute error, interval coverage and fallback frequency; reception loss alone does not establish landing.


## dev.12 — Basemap theme separation

`map_theme` is a validated auto/light/dark enum, default auto, carried through App options, `/map-config` and saved settings snapshots. Root HTML includes the configured mode for initial rendering; the map-config refresh applies the same value. Auto uses browser `prefers-color-scheme: dark` and a change listener; explicit modes ignore preference changes. This follows device/browser preference rather than Home Assistant's separately chosen theme.

Palette CSS is scoped to `.leaflet-tile-pane`. Light uses native OpenStreetMap tiles; dark applies invert(100%), hue-rotate(180deg), brightness(.85), contrast(.9) to the basemap pane. Marker/vector/canvas overlays, analysis colors and popups are not filtered. Existing tile proxy, attribution and persistent tile cache are retained; no second provider, fetch pattern, or source-specific data output is introduced. This is presentation-only: motion, ETA, collection and query algorithms do not change.


## dev.13 — Live theme control

The toolbar selector calls setMapTheme(value, true), establishing an in-memory page override. Subsequent map-config refreshes update the saved default only when no local override exists. Auto is itself a valid override and still reacts to prefers-color-scheme events. No settings write, endpoint call, tile fetch or density/motion operation is required for theme selection. A newly loaded map page starts from App map_theme; no per-browser persistent theme preference is introduced. Palette CSS remains scoped to basemap tiles.
