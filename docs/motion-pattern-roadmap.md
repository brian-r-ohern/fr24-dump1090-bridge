# Motion roadmap after v0.7.3

v0.7.3 closes the usability, history and reliability increment. Next work focuses on observed geometry and composable sequences, without inferring intent.

1. Refine existing orbit, reversal and racetrack detection using replay cases, including large patterns, partial observations and exits.
2. Add repeated parallel passes, grid/lawnmower geometry and figure-eights with evidence and counterexamples.
3. Compose primitives and derived geometry into contextual sequences; support partial sequences near airports without assuming takeoff, landing or purpose.
4. Evaluate coordinated multi-aircraft geometry, explicit route baselines and robust flight-occurrence handling.

Live exports verified extended route retention and rolling 24-hour expiration. Full-day detector replay remains unfinished. Earlier planning follows as historical context; version assignments below are superseded.

> Status as of 28 October 2026: range/density, source adapters, motion primitives, orbit/reversal/racetrack geometry, destination movement, selected-aircraft proximity/CPA, trails and GeoJSON export are implemented. v0.7.3 adds selected destination overlays, experimental local-route disk retention, grouped configuration and projected passes near Home. Live validation of the newest features remains open. Remaining geometric work includes repeated parallel passes/grid patterns, figure-eights, coordinated multi-aircraft geometry, Home-relative radial classifications, explicit-baseline route deviation, broader sequence recognition, altitude-colored trails and robust flight-occurrence handling. Interpretive purpose/intent labels are deferred; observed kinematics is the goal. The full-day replay is incomplete.

> Current dev.2 additions: selected trails, sampled analytical history/export across sources, offline motion replay, geometry diagnostics, trusted-network access and observed-descent arrival scenarios. [Exact behavior and validation](v0.7.2-dev.2-testing.md). Earlier no-FAA-history/export statements below describe the prior build; dev.2 permits deliberate analytical history downloads while automatic FAA feed bridging remains disabled.

# v0.7.x — Motion & Pattern Analysis Roadmap

Purpose: analyze what aircraft are doing now, rather than where they have historically been observed. A rolling in-memory history supplies motion context without turning the Bridge into a permanent flight-history database. This roadmap defines the v0.7 series direction. The public v0.7.0 release implements the common short-term motion engine, basic flight-state primitives and the destination ETA and experimental modeled arrival range. v0.7.1 improves envelope performance and persistence. v0.7.2-dev.1 begins experimental circles/orbits, reversals and repeated racetrack geometry; subsequent increments validate/refine these and add pair analysis. Exact feature-to-release assignments remain open. The interim v0.8.x roadmap labels are superseded.

## Evidence and metadata

Separate observed positions and motion estimates from reported metadata and possible interpretations. A reported destination may be the original destination and may not reflect a diversion or updated flight plan. Do not assume enrichment continuously rechecks destinations. Retain destination source and retrieval/update time when available; otherwise mark freshness unknown.

Present observations as “level flight,” “repeated racetrack” or “moving away from last reported destination.” Use holding-like, cruise-like, surveillance-like, crop-dusting-like, survey-like and training-like only as supported interpretations. Motion does not establish intent or a formal destination change.

## Motion-state foundation

For each positioned aircraft retain timestamped history sufficient to derive or validate position, course/velocity vector, ground speed, vertical rate, acceleration/deceleration, turn rate, radial velocity relative to Home, and confidence/quality. Reported ADS-B values can be used when available; observed position history supplies an independent estimate when reported track/speed is absent or questionable.

Track discontinuities are explicit. A rendered line across a gap does not establish the path followed. Repeated Bridge snapshots of an unchanged source report must not be treated as independent motion samples: retain source timestamps and position age. TFMS and flights.js are excluded from motion analytics because of sampling and precision limits.

## Motion primitives and events

Extract time-qualified primitives: stable course, stable speed, level altitude, left/right turn, acceleration/deceleration, climb/descent, course reversal and GAP/discontinuity. Higher-level patterns combine these primitives with geometry and repetition; they are catalogued once below. Derived event history may outlive high-rate raw history at low memory cost.

The sequence is observations → motion state → primitives/events → pattern grammar using sequence, timing and geometry → geometric pattern → possible interpretation. A repeated orbit is observable geometry; surveillance-like is a hypothesis. Parallel passes can have agricultural, survey, mapping or other explanations.

## Formation candidates and coordinated fleets

Spatial proximity alone is insufficient; require kinematic coherence:

1. Spatial gate: candidate horizontal separation within an experimental 3–5 mile range, with units explicitly specified in configuration.
2. Speed gate: absolute difference between speed magnitudes, initially around 20 knots or less.
3. Heading gate: `min(abs(h1-h2), 360-abs(h1-h2))`, initially around 10° or less.
4. Treat aircraft as nodes and qualifying pairs as edges. Connected components or an appropriately defined DBSCAN model can produce candidate formation groups.

Require persistence across observations, relatively stable spacing/geometry and coordinated turns. Evaluate vertical separation as well; similar horizontal vectors at different flight levels need not indicate a formation. Connected components can chain together distant endpoints, so test group-wide geometry before applying a label.

Candidate arrangements include trail, line-abreast, echelon and wedge-like geometry. Military enrichment provides context, not proof of intent. A defensible result describes geometry, aircraft count and supporting confidence; it does not declare an attack formation. Confidence values require validation/calibration and are not automatically probabilities.

## Individual maneuver detection

Use a sliding time window (an initial experiment might use five minutes) with timestamp-aware feature extraction:

| Track pattern | Observable rule / presentation | Possible interpretation |
| --- | --- | --- |
| Steady-state cruise-like / straight-and-level | Sustained near-zero vertical rate, stable ground speed and stable course within configurable tolerances | Steady flight; cruise phase is not established by these measurements alone |
| Sustained climb / descent | Persistent positive/negative altitude trend, supported by usable vertical rate; identify abrupt rate changes separately | Climb/descent; an abrupt descent alone does not establish an emergency |
| Constant acceleration / deceleration | Approximately constant ground-speed derivative over a sustained window, initially over 30 seconds | Speed adjustment; cause undetermined |
| Sustained or rapid left/right turn | Persistent signed course-change rate, corroborated by observed trajectory | Turning motion; bank angle and g-force are not measured |
| Constant-radius turn / repeated orbit | Approximately stable speed, signed turn rate and fitted radius; repeated same-direction circuits about a relatively stable center | Orbit or loitering-like motion; training, photography and other activity remain possible |
| Course reversal | Approximately 180° course change within a bounded interval, corroborated by trajectory | Turnback or procedure-turn-like geometry |
| Racetrack / holding-like | Repeated straight leg → approximately 180° turn → reciprocal leg → approximately 180° turn; turn rate need not be standard | Holding-like geometry; clearance and purpose are unknown |
| Parallel passes / lawnmower / grid | Repeated near-parallel legs, often reciprocal, with consistent lateral spacing and reversals | Mapping, survey, search or agricultural-work-like geometry |
| Figure-eight / other repeated geometry | Repeated opposing loops intersecting near a shared center, supported by trajectory and timing | Training or localized maneuvering; purpose undetermined |

Altitude stability and zero vertical rate mean “within tolerance,” not exact equality. Climb/descent uses measured altitude change; an energy model is unnecessary for initial detection. Keep barometric, geometric and assigned altitude distinct. Assigned FAA altitude is not evidence of an observed climb or descent.

### Turn and banking limits

The current normalized feeds do not provide reliable roll angle, roll acceleration or load factor. Changing ground track can support a sustained-turn detector, but does not directly measure aircraft yaw, bank or g-force. “Steep bank” cannot be established from turn rate alone. A future model-derived bank estimate would need explicit coordinated-turn assumptions, suitable airspeed and quality checks; ground speed is affected by wind. It must be labelled inferred and kept separate from measured values.

Ground track is not necessarily aircraft heading. Use signed, unwrapped course differences for turn rate. Summing absolute changes can confuse alternating turns with an orbit. For `R = v / omega`, angular speed must be in radians per unit time and speed must use consistent units. This is a model estimate; fitted observed geometry should corroborate it. Standard-rate turns may be supporting evidence, but holding-like detection must tolerate nonstandard rates and large racetracks.

### Destination divergence and route deviation

The bundled airport lookup supplies destination coordinates and bearings. Compare successive observed distances to the **last reported destination**, sustained direction of travel, elapsed time and distance travelled. A SYR → MCO aircraft moving away for 50–60 miles is an example for testing, not a fixed universal threshold. A short departure leg or temporary vector is insufficient.

For an explicit route baseline, test sustained cross-track error against a configurable threshold; retain the baseline source and freshness. An initial direction vector alone does not establish the route.

Use the label **Moving away from last reported destination**. Explain that the result is based on observed positions and potentially stale metadata; weather avoidance, vectors, a diversion or a destination update can produce similar motion. This is destination divergence. Route deviation requires an explicitly defined route baseline; a direct origin–destination line does not establish the filed or cleared route.

### Pattern precedence

Once repeated racetrack/holding-like geometry is established, it takes precedence over a destination-divergence notification. Individual racetrack legs naturally point away from the destination. Retain the distance trend as evidence, suppress repetitive divergence notices during the established pattern, and reassess after exit. Before enough repetition exists, describe turns/legs as provisional observations rather than asserting a holding pattern.

Primitive events remain available beneath the higher-level label. For example, holding-like geometry can contain level flight, turns and course reversals without creating separate competing notifications for each event.

## Proximity and separation

Compare nearby aircraft in three dimensions, reporting horizontal and vertical separation separately. Configurable thresholds are display/analysis criteria, not declarations of unsafe separation. Candidate pairs may be highlighted and connected on the map. Unavailable or incompatible altitude references must be explicit.

## CPA / TCPA

Use relative position and velocity, rather than simply extending heading lines. Calculate time to closest approach, horizontal distance at CPA, predicted vertical separation at CPA, and optionally present closure rate. Describe the constant-motion assumption and uncertainty.

Begin gating with information available earliest:

1. Position-based coarse range gate, initially around 100 NM. This is a computational gate, not an alert threshold; it roughly supports a five-minute horizon for rapidly closing passenger aircraft, but needs evaluation against the actual speed range.
2. If motion state is unavailable, retain the nearby candidate and wait.
3. Apply a permissive vector gate that rejects only clearly irrelevant/diverging pairs.
4. Evaluate CPA/TCPA within the prediction horizon, initially around five minutes.
5. Apply horizontal and vertical display criteria and report/highlight qualified candidates.

At large aircraft counts, spatial indexing avoids generating every possible pair. No prediction should bridge an unobserved discontinuity as though motion were measured.

## Radial motion relative to Home

Classify inbound, crossing/tangential and outbound using observed change in range where possible. Heading is secondary evidence. Use a deadband and sustained evidence to avoid noisy changes.

## Explainability

Results can include pattern, provisional/established state, confidence, involved aircraft, first detection, duration, supporting events and measurements, source timestamps, position age and metadata freshness. Distinguish a fleeting coincidence from stable behavior. Synthetic trajectories and negative examples should make detector validation practical. Motion analytics is limited to SBS and standard aircraft.json; TFMS and flights.js remain feed/density/ETA sources without motion primitives.

## Track-history and flight-occurrence semantics

Return the complete history for one contiguous flight occurrence. A fixed observation-gap timeout alone must not terminate a flight. Separate flights on different days must not be joined solely because ICAO hex, callsign/flight number or origin/destination is reused.

Gaps remain important analytical metadata: do not derive observed velocity, turns or CPA behavior across unobserved intervals. Ordinary map history may visually connect plausible endpoints, while explicit breaks should appear when elapsed time, implied motion or testing makes continuity misleading.

Evaluate altitude-coded segments using density's conceptual bands: Low below 1,200 ft; Middle 1,200–17,999 ft; High at or above 18,000 ft; Unknown neutral. These are not airspace classes.

Keep flight-occurrence segmentation empirical. ADS-B identity/time/route evidence and departure/arrival behavior can be combined; TFMS GUFI and flight references may provide stronger flight-instance evidence. Source identifiers still need continuity checks.

## Incremental delivery for v0.7.x

Start with the common motion foundation rather than making destination ETA the prerequisite for analytics. The ETA prototype already exists and can accompany an increment once validated; its simple destination-distance calculation does not need the full motion engine. It must remain visibly approximate and based on the last reported destination.

| Proposed increment | Scope | Completion evidence |
| --- | --- | --- |
| 0.7.0 — foundation and basic flight states | Bounded timestamped history, source-age/duplicate/gap handling, motion quality, steady flight, climb/descent, speed trends and sustained turns; optional validated ETA companion | Stable state labels with duration/support; repeated ADS-B snapshots do not create false confidence; TFMS and flights.js remain excluded |
| 0.7.1 — envelope performance and saved builds | SQL aggregation, bounded NumPy reduction, persistent Load/Build controls, age and diagnostics | Equivalent products; fast saved load after restart; history/source/Home validation |
| 0.7.2 — repeated single-aircraft geometry (dev.1 preview) | Constant-radius turns/orbits, reversals, racetrack/holding-like and pattern precedence | Repetition distinguishes a transient turn from an established pattern; large racetracks and exits behave correctly |
| 0.7.3 — destination and Home trends | Inbound/crossing/outbound and sustained movement away from last reported destination; suppress divergence during established holding-like geometry | Departure vectors and racetrack legs avoid repetitive divergence notices; stale metadata is visible |
| 0.7.4 — proximity and CPA/TCPA | Three-dimensional separation, spatial gating, relative-motion predictions and explainable candidate highlights | Constant-motion assumptions and altitude uncertainty are exposed; bounded processing at high aircraft counts |
| 0.7.5 and later — richer patterns and coordinated groups | Parallel/grid passes, figure-eights, correlated vectors, persistent formations, explicit-route deviation and contextual hypotheses | Positive/negative trajectories distinguish geometry from intent; supporting evidence remains inspectable |

These are proposed feature boundaries, not fixed release promises. Split an increment if validation requires it. Basic primitives feed all later detectors; repeated geometry precedes divergence notifications because its precedence rules reduce predictable false positives. Pair prediction and formation grouping follow after individual motion quality is established.

Use `0.7.2-dev.N` for the next geometry validation builds, however many are needed. v0.7.0 is the first public motion release and v0.7.1 is the envelope follow-up; the phase numbers above describe later capability milestones, not a requirement to publish each local revision. The earlier ETA-only prototype label `0.8.0-dev.1` is superseded.

Most state stays in memory; persistence requires a specific later requirement. No change to authoritative 0.5° / 720-bin coverage or density observation credit is implied.

## Validation and acceptance

Test synthetic positive and negative trajectories alongside live ADS-B and suitable SBS/aircraft.json observations. Include heading wraparound, duplicate reports, out-of-order timestamps, dropout/reacquisition, altitude-reference mismatches, noisy steady flight, departure vectors, weather-like detours, large racetracks and holding exit. Verify repeated snapshots do not increase independent motion support, and gaps do not invent observed turns or acceleration.

Detector outputs must expose evidence, duration and quality. Thresholds remain experiment