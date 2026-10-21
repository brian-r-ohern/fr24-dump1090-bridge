# Implemented geometry — v0.7.2-dev.1

This is an experimental first increment, not the final v0.7.2 detector set. Geometry is measured; holding-like is a possible interpretation, not evidence of an ATC clearance or intent. Go-around-like detection is planned for a later increment and is not implemented here.

## Data and bounds

Existing source admission, reported position timestamps, duplicate/out-of-order/throttle checks, speed plausibility and gap/discontinuity resets remain authoritative. SBS, aircraft.json and SFDPS are supported; TFMS and flights.js remain excluded. No gap interpolation is introduced. SFDPS still uses reported speed for the existing speed primitives; geometric patterns use positioned observations independently.

Each track additionally retains at most **360 admitted position samples**, accepting one at least **10 seconds** after its previous geometry sample and removing those older than **3,600 seconds**. Evaluation occurs at most once per 10 seconds of admitted source position time. Existing basic-primitives history and source freshness windows are unchanged. A source gap, discontinuity, flight-occurrence change or ground transition clears geometry history. Whole tracks expire after the existing 300-second inactivity limit. Thus two circuits must fit in the retained window; sufficiently slow/large patterns will remain unclassified. This is not permanent flight history. At most 32 completed pattern transitions are retained per aircraft, in addition to the existing primitive-event limit. Overall aircraft limit remains 1,024.

At least 12 geometry samples are needed. The local projection uses the first retained sample as origin:

- x = Earth radius × wrapped longitude difference in radians × cos(origin latitude).
- y = Earth radius × latitude difference in radians.
- Earth radius = 6,371,008.8 m; one NM = 1,852 m.

This local planar approximation is used only for geometric patterns, not ETA or density envelopes. It is not a geodesic fit; distortion grows over large regions. Geometry is suppressed where |cos(origin latitude)| < 0.05 (near the poles). Longitude differences wrap across the antimeridian. Altitude is not a gate for geometric orbit/racetrack labels; climbing or descending circuits can still be recognized geometrically.

## Motion states → turn/straight phases

For every retained endpoint, derive course from the chord to the earliest previous sample needed to span at least 20 seconds, or the first sample when that span is not yet available. At typical 10/12-second cadence this is approximately a 20–30-second chord. Overlapping chords smooth course but are not treated as new independent observations or statistical confidence.

If any chord's position-derived speed is below 30 knots, this dev detector declines the history. It does not infer bank angle, roll, load factor or airspeed.

Successive chord courses use wrapped differences in [-180°, 180°). Divide by their endpoint time difference. Rates with magnitude at least **0.1°/s** are left/right turn phases; lower magnitudes are straight phases. Merge consecutive equal classifications. A phase shorter than **20 seconds** is absorbed only when its immediate neighbors have the same classification. Accumulate both signed angle and absolute angle so direction consistency = |signed sum| / absolute sum. Required turn consistency is at least **0.85**.

Straight length is endpoint displacement, not integrated path length. Its course is the endpoint chord. Turn duration and geometry use the observed positions corresponding to the phase.

## Circle fit and individual turns/orbits

Center the local x/y coordinates on their means. Solve the 2×2 least-squares system:

[sum(x²), sum(xy); sum(xy), sum(y²)] × [cx, cy] = 0.5 × [sum(x(x²+y²)), sum(y(x²+y²))].

Add the means back to obtain the center. Radius is mean distance from that center; residual is radial RMS error divided by radius. Reject fewer than six fit points, singular/near-collinear systems (determinant ≤ max(1, sum(x²)sum(y²)×1e-8)), radius outside **0.25–40 NM**, or relative radial RMS above **0.12**.

| Result | Additional evidence | State |
| --- | --- | --- |
| Constant-radius turn | Latest uninterrupted turn ≥45 s, ≥90° accumulated heading, valid circle fit and direction consistency | Candidate |
| Orbit | Same gates, ≥330° accumulated heading | Candidate; tolerance permits an almost complete observed circuit |
| Repeated orbit | ≥690° accumulated heading; separate circle fits to the first and second halves; centers within 25% of overall radius and radius ratio 0.8–1.25 | Established |
| Course reversal | An approximately half-turn, 150–210°, lasting ≥20 s; supported within the preceding 60 s, when no higher-precedence pattern applies | Candidate/event |

Completed-orbit count uses floor((absolute accumulated angle + 30°)/360°); it is a tolerance-based geometric count. Turning direction comes from the observed course changes. A latest straight phase shorter than 30 seconds can bridge the turn exit; at 30 seconds the orbit/constant-turn label is removed. Reversal visibility expires 60 seconds after the qualifying turn support ends.

## Pattern grammar → racetrack/holding-like

Search recent alternating straight/turn sequences, most recent first:

- **Candidate:** four alternating phases (two straights, two turns), representing roughly one circuit.
- **Established:** eight alternating phases (four straights, four turns), representing roughly two circuits. Established searches take precedence over candidate searches.
- Every phase spans ≥20 s. Every straight is ≥0.5 NM. Longest/shortest straight length ≤4.
- All turns share direction. Each accumulates 145–215° with direction consistency ≥0.85 and a valid circle fit. Largest/smallest turn radius ≤1.8.
- Adjacent straight courses are reciprocal within 20°.
- Endpoint closure is within max(1 NM, 0.6×median turn radius).
- For two circuits, turn centers 1↔3 and 2↔4 must repeat within max(0.5 NM, 0.35×median radius). This distinguishes a repeated racetrack from a migrating zigzag.

An established historical sequence remains supported while current motion stays near its observed path. The path corridor is max(0.5 NM, 0.35×median turn radius), measured to the retained template points. If all recent points within the last 30 seconds are outside that corridor and span at least 20 seconds, the old sequence is rejected. This prevents a straight departure extension from leaving the holding label latched. This is a sampled-path corridor rather than a runway or route model. Self-intersections, sparse sampling, long extensions and reentry need live empirical review.

Synthetic tests include racetracks with 50-NM straight legs completed twice within an hour. This does not imply recognition of every 50-NM pattern at every speed.

## Precedence, lifecycle and evidence

Return one primary geometric result, in order: established racetrack → candidate racetrack → repeated orbit → orbit → constant-radius turn → recent reversal. Existing climb/descent/speed primitives remain independent and may overlap it. A phase inside an established racetrack is not separately reported as an orbit/reversal. On departure or changed geometry the label is removed; transitions retain first support, detection time, last support, ending time/reason and segment. Promotion/precedence changes end the old result as superseded. Stale server and browser states suppress geometry, like primitives.

Each visible detection includes its candidate/established status, support duration, evidence and **uncalibrated evidence score**. The score is not a probability: racetrack = 0.55 candidate or 0.85 established; circle-based result = (0.60 candidate or 0.85 established)×(1−radial residual), capped at 0.95; reversal = 0.60. No false-positive calibration has been performed. Scores and gates are experimental.

Popups expose cumulative turn, radius/residual, half-fit center/radius agreement, racetrack straight lengths, reciprocal-heading errors, closure and repeated turn-center errors as applicable. Verbose popups show geometry-history sample count/span and collecting/no-qualifying/detected reason. Minute Motion summary logs contain aggregate `patterns` counts by name:status; verbose diagnostics/status add retained geometry samples and completed events. No identifiers/coordinates are added to aggregate logs. Per-track motion APIs remain blocked for FAA, with SFDPS results embedded only in the authorized local map.

## Display and touchdown companion

Map filters include racetrack/holding-like, repeated orbit, orbit candidate, constant-radius turn and reversal. Filters match any selected label. Geometry colors take priority over primitive colors: racetrack → repeated orbit → orbit → constant-radius turn → reversal → turn → descent → climb → slowing → speeding → steady. Military/O/D badges and closest glow remain.

The top Map controls panel is collapsible with native details/summary; collapsing does not reset selections. It opens on a fresh page load. The modeled-arrival label becomes **Estimated touchdown · modeled**, with **Touchdown assumptions**. Its numerical scenarios are unchanged, but a fresh observed orbit/racetrack defers that direct-arrival scenario; direct/current-speed ETA remains visible. This remains an approximate airport-center scenario, without runway, vectors, holding, wind or taxi modeling. A climb after an approach is not yet classified as a go-around.

## Validation limits

Synthetic checks cover clockwise/counterclockwise circuits, partial turns, two-cycle racetracks, 50-NM legs, exits, reversal expiry, straight flight, elliptical/drifting negatives, small position noise, antimeridian handling, source exclusion, gap resets, stale suppression and bounded history. Live false-positive rates and SFDPS sampling robustness remain unvalidated. Browser logic is tested; automated visual layout testing could not run because the browser executable was unavailable and its download failed. HAOS image/AppArmor and phone layout need user validation.
