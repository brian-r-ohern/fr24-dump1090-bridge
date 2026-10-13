# Changelog

## v0.7.0 — 2026-10-13 (Stable Release)

Promoted **v0.7.0-dev.13** to **v0.7.0** following development and validation of the v0.7.0 feature set. This release consolidates all changes from dev.1 through dev.13.

### Release highlights

- Added FAA SFDPS authorized local-only surveillance viewing; both FAA sources disable aircraft-feed and general data-export endpoints.
- Added airport lookup, direct ETA, and separately labeled experimental modeled-arrival range for qualifying aircraft.
- Added motion primitives, activity coloring, filtering, and source-specific diagnostics.
- Improved traffic density with spatial SQL, rollups, cached tiles, and refresh controls.
- Added live Auto/Light/Dark map theme selection and expanded regression tests.

Development entries below document the progression; they are not separate stable releases.

### v0.7.0-dev.13 — Final development build

- Add live Map theme Auto/Light/Dark toolbar selector, applying the palette immediately without restart or reload.
- Preserve the user's open-page choice across periodic map-config refreshes; the App setting remains the default for newly loaded map pages.
- Retain basemap-only palette changes and dynamic browser preference handling in Auto.


## 0.7.0-dev.12

- Add map_theme auto/light/dark, default auto, with App configuration labels, strict validation and persistent settings recovery.
- Auto follows browser/device color preference changes; explicit light/dark overrides it. Palette styling is scoped to basemap tiles so aircraft and analytical layers retain their colors.
- Preserve existing tile provider/cache and document theme behavior and testing. Make the audit-log test independent of concurrent response-completion order.


## 0.7.0-dev.11

- Prefer fresh SFDPS reported ground speed for stable-speed/acceleration/deceleration; retain position-derived fallback, comparison and course/turn analysis.
- Record speed basis in states/primitives/log counts and terminate speed events on basis switches. Preserve existing ADS-B behavior and TFMS exclusion.
- Enable direct-speed ETA on the SFDPS local map and add a separately labeled experimental transport-jet descent/slowdown arrival range with input gates and explicit unresolved/fallback reasons.
- Refresh the pinned PDDL airport snapshot with elevation/type and document exact equations, profile values, source provenance and validation limitations.


## 0.7.0-dev.10

- Automatically load pending, fully cached fresh density views after pan/zoom/band changes, with server-enforced cache-only mode and safe expiry/invalidation handling.
- Add opt-in popup speed diagnostics and bounded aggregate verbose logs for every motion-enabled source.
- Explain stable-speed blockers, accepted position intervals, position-derived speed range/residual/trend and reported-speed comparisons, preserving SFDPS speed semantics and field timing provenance.
- Leave detector thresholds, FAA output isolation and source exclusions unchanged.


## 0.7.0-dev.9

- Automatically load density on enable and show compact current-viewport cached/missing/stale tile counts through a metadata-only cache inventory route.
- Keep detailed grid/timing diagnostics off the main banner; retain explicit load and forced refresh controls.
- Enable SFDPS density in its own store and local motion analysis with independent report timestamps, a source-specific quality profile and reported-altitude provenance.
- Preserve FAA local-view isolation, disabled range/envelopes, and TFMS/flights.js motion exclusions.
- Document validation and preview limits in `docs/v0.7.0-development-validation.md` and the motion engineering notes.
- Add rebuildable daily parent totals at zooms 8/11/14 with transactional live maintenance.
- Add bounded two-hour density tile caching, generation time and explicit Refresh now.
- Invalidate caches on restore, clear and retention pruning; keep full backups authoritative.
- Preserve fine observations, source separation and FAA output restrictions.

## 0.7.0-dev.7

- Use existing spatial and cell/date indexes before aggregating viewport density.
- Group numeric coordinates instead of repeatedly parsing text cell IDs.
- Add query-strategy diagnostics and baseline SQL equivalence tests.
- Preserve schema, collection statistics, export formats and source eligibility.

## 0.7.0-dev.6

- Add verbose SQLite query plans, page/cache settings, approximate VM instruction counts and query-thread CPU timing.
- Add explicit density cache bypass for repeatable diagnostics.
- Preserve counters, datasets, source eligibility, query results and existing index structure.

## 0.7.0-dev.5

- Optional bounded verbose motion rejection and density phase timing diagnostics; settings backups retain the toggle.
- Zoom-dependent 24/36 px aircraft icons with centered anchors.
- Relocate motion display help to status page; show intentionally disabled Tracker correctly.
- Preserve existing analytics thresholds, source eligibility and histories.

## 0.7.0-dev.4

- Increase aircraft SVG/marker dimensions 1.5× to 36 px, with centered 18 px anchors.
- Add local-view `swim_sfdps` FIXM surveillance parsing, shared Solace transport and geographic filtering, GUFI identity, reported metadata and course from successive observed positions.
- Disable SFDPS density storage/collection/import/export, range and motion processing; preserve existing source histories.
- Block dump1090 aircraft output and history/data exports for both FAA sources; refresh their local map through embedded HTML display state. Dashboard titles identify local-view mode.
- Bound SFDPS view state, reject stale/future/out-of-order updates, and sanitize SWIM exception reporting.
- Add synthetic parser/isolation tests and setup/engineering notes; no captured FAA records included.

Version 0.6.8 is the public release of the traffic-density work. Entries 0.6.0–0.6.7 preserve its development sequence; they do not imply separate public releases.

## v0.7.0-dev.3 — Motion exploration (local preview)

- Motion panel offers live counts and any-label filtering. Fit aircraft fits the shown subset.
- Optional motion colors with legend/overlap priority, retaining O/D badges, military popup labels and closest glow.
- ETA labels identify stale/unknown position age; baseline calculation unchanged.
- Configurable Tracker aggregate/closest/military entities with sanitized failure diagnostics. Optional sensor failures no longer block route metadata.
- Updated engineering notes document a future coupled descent/approach model and validation prerequisites; modeled arrival is not implemented here.
- No data migration or motion-threshold changes.

## 0.7.0-dev.2 (local development diagnostics)

- Add current motion-quality and primitive counts to collection logs at most once per minute, without aircraft identities.
- Explain warming-up eligibility, overlapping labels, freshness, support durations and observed versus reported vertical rate.
- No data migration or motion-threshold changes.

## 0.7.0-dev.1 (local motion-foundation preview)

- Add map-only destination distance and a constant-current-ground-speed ETA with UTC arrival time. Use Tracker destination enrichment for ADS-B and native arrival metadata for TFMS; omit unavailable/invalid estimates.
- Bundle a local airport lookup generated from a pinned October 10, 2026 OurAirports-derived PDDL CSV, with unambiguous IATA/ICAO alias matching and provenance. No Internet airport lookup or feed changes.
- Add bounded in-memory position history and basic observed motion primitives for SBS and standard aircraft.json. Exclude TFMS and flights.js; preserve their existing feed/density/ETA behavior.
- Publish current states and exact threshold/counter diagnostics through /motion and /motion/status; show labels and derived trends in aircraft popups. Keep active/completed primitive summaries bounded and reset continuity at gaps/discontinuities.
- Document implemented calculations and provisional thresholds separately from future geometric detectors. No settings, range or density migration.

## 0.6.9.3

- Prefer each App’s registered sidebar route (such as `/local_fr24_dump1090`), with `/app/<full-slug>` as the current generic fallback when the sidebar is disabled. The old `/hassio/ingress/<full-slug>` destination could fall back to the default dashboard even with a valid routing event.
- Publish the current App path on the status entity and translate old paths already saved in cards. Use the registered frontend panels to retain compatibility with older HA; preserve explicit dedicated-sidebar paths. Map/status/settings handoffs use the resolved destination and keep instance identities separate.
- Add route-selection regression checks for both local and repository instances and all three buttons. Existing integration entries and cards remain valid.

## 0.6.9.2

- Register the versioned card automatically as a Lovelace module resource. Load the existing resource collection before creating/updating only the Bridge entry; preserve other resources. YAML resource mode retains frontend loading without editing YAML.
- Correct all three card buttons to send Home Assistant a CustomEvent with routing options rather than an incomplete Event. Preserve the constrained map/status/settings Ingress handoff.
- Serialize shared card registration across multiple App entries. Existing integration entries and cards remain valid; restart the App and HA Core, then reload the browser after upgrading.

## 0.6.9.1

- Correct card feed status by reading the entity state when no feed_status attribute exists. Default titles follow the selected feed; hide unavailable source-specific message rates.
- Add opt-in automatic installation of the bundled HA companion integration, separate internal status polling per App instance, frontend card loading and a visual entity/title editor. Users enable the option, restart the App and HA Core, add Aircraft Bridge in Devices & services, then select the card in the picker.
- Preserve old settings snapshots with a default-disabled dashboard option. Add only the required Home Assistant configuration mount and self-info Supervisor access. No density/range migration or consumer-counting changes.

## 0.6.9

- Add a dashboard status card with source/version header, status diagnostics and Ingress navigation to the map, status and settings recovery. Read status from an HA REST entity without publishing a host port.
- Track successful aircraft-feed requests for 60 seconds and expose recent internal/external client groups through `/status` and the status page. Support self-reported `client_id` labels; explicitly mark address/User-Agent fallback grouping as an estimate. Exclude non-feed requests and keep tracking bounded and volatile.
- Document feed dependencies before stopping/uninstalling, two-instance card configuration and an optional HA count sensor. No dataset/settings migration.

## 0.6.8

- Log data import/export/generation/clear starts and outcomes with source, dataset, available counts, bytes, duration and HTTP status. Distinguish rejection and disconnected transfer outcomes; keep automatic range polling out of export logs.
- Document refreshing displayed layers after restore/clear and restarting after Network port changes. Settings, storage and collection behavior are unchanged.

## 0.6.7

- Persist valid App settings in the dedicated host configuration folder; offer explicit Supervisor restore and a recovery page when feed settings are incomplete. Preserve damaged snapshots and include credentials without exposing them in the UI.
- Place density altitude and envelope controls side by side; move Refresh density beside Fit aircraft and rename the comparison action Generate envelopes. Keep Range ring on the main toolbar.
- Border endpoints green and the three data sections yellow; move the red Danger Zone below all Diagnostics text.

## 0.6.6

- Index spatial cells and filter viewport before aggregation; preserve zoom-17 collection and 0.5° range bins.
- Load density on enable and explicit Refresh density; pan/zoom/band changes mark the view pending. Show actual grid zoom and reuse small interactive aggregates for up to 30 seconds.
- Document direct LAN access for large restores outside Ingress.
- Add defaults for all optional fields, including SWIM message VPN; retain source-specific startup validation.
- Add confirmed selective and all-source collected-data clearing below Diagnostics.

## 0.6.5

- Let interactive density requests finish without cancellation by the refresh timer.
- Aggregate requested display cells in SQLite, use zoom-appropriate geometry, and cap interactive responses at 6,000 cells by merging observed children. Fine-resolution storage and full-resolution exports remain intact.
- Report query timing, lock wait, returned cells and display zoom through logs and collection status; show timeout and request errors in the map.

## 0.6.4

- Rename the static Home Assistant sidebar title to Aircraft Bridge; retain source-specific map and page titles.
- Add Low/Middle/High combination filters and All Traffic including Unknown; color by selected observation counts without changing storage or full backups.
- Add on-demand density-derived All/Low/Middle/High envelopes at 0.5° / 720 bins using observed base-cell centers. Show dashed ADS-B comparison outlines separately from authoritative range coverage.
- Add custom-window envelope JSON/GeoJSON exports and a bounded five-minute cache. FAA products are labeled reported traffic extent and are excluded from receiver range-ring display.
- Include sector observation counts, occupied cells, maximum-cell support and explicitly labeled combined passages in qualifying cells; do not invent altitude-specific passages.
- Document TFMS sampling, repeated snapshot counts, observed delivery timing and the rationale for avoiding interpolation.
- Preserve the existing schema, source separation, retention, backup policy and v0.6.3 large-archive handling.

## 0.6.3

- Use selected-source browser, map and status titles; change the static default Home Assistant sidebar title to Bridge. Document per-installation sidebar labels.
- Separate density history by source, retain all-source collection, tag JSON backups and reject mismatched-source restores. Preserve legacy chunks with explicit one-time source attribution.
- Prefix JSON/GeoJSON backup filenames with sbs-, fr24-, d1090- or faa-. Keep density controls scoped to the current source.
- Add a Range ring checkbox for ADS-B sources; hiding it does not stop collection. Disable range routes and controls for FAA TFMS as well as its existing worker exclusion.
- Replace full-memory density backup/restore with disk snapshots, compact streaming exports and fully validated disk-staged imports; remove the 256 MiB upload ceiling.
- Retain zoom-17 storage, daily altitude/passage counts, 18-month retention, snapshot collision policy and the v0.6.2 responsive layout.
- Include upgrade and test instructions in docs/v0.6.x-development-validation.md.

## 0.6.2

- Place track controls and status in a shared wrapping dock so the panels cannot overlap.
- Make Bridge status collapsible, initially closed on narrow or short viewports; constrain and scroll its contents to the available space below the toolbar.
- Keep the top toolbar clear of Leaflet zoom buttons; recalculate available panel height on resize, orientation changes and dynamic feed/control updates.
- Prevent clicks and scrolling in overlays from propagating to the map. Retain v0.6.1 TFMS range-worker exclusion and all density behavior.
- Include an optional Playwright layout regression harness for phone/desktop viewports, status expansion, track visibility, rotation and keyboard toggling. Browser execution was unavailable in this build environment.

## 0.6.1

- Do not start the range-coverage worker with TFMS input; skip coverage file loading, legacy migration, periodic processing and flushing.
- Guard the worker itself against TFMS invocation. Preserve existing coverage files for a later switch back to an ADS-B source.
- Continue Home-marker processing (needed by the TFMS geographic gate) and Traffic Density collection for TFMS. ADS-B coverage remains 0.5° / 720 bins.

## 0.6.0

- Collect traffic density once per publication from all four selected sources, independently of map visibility and raw message counts.
- Add a sparse global geographic quadtree at base level 17 (approximately 153 × 227 m at 42°N), with parent aggregation for display and no interpolated cell credit.
- Persist daily observation/passage counts, all four altitude counters, min/max altitude and explicit history provenance in monthly SQLite `.dat` chunks; retain 18 calendar months.
- Suppress repeated passages from cell-boundary jitter and short dropouts using a 90-second recent-cell cache.
- Add an off-by-default Traffic Density map layer for the most recent 30 UTC calendar dates, with combined observation colors and cell-statistics popups.
- Add JSON export/restore, monthly backup selection, GeoJSON polygons, query-window/hierarchy APIs and collection status. Restore chooses deterministic whole cell/month snapshots rather than adding overlapping histories; uncertain starts remain null.
- Include reproducible candidate-grid sizing and regression/HTTP/publisher tests; package the new module in Docker and AppArmor.
- Preserve the existing authoritative 0.5° / 720-bin range dataset and legacy migration behavior.

## 0.5.4

- Report build version in `/status`, the human-readable feed status page, and the map bridge status panel.
- Show track history only when a history URL is configured for any input; remove the hardcoded TFMS endpoint.
- Increase active coverage resolution to 0.5° / 720 bins; archive the original 1° file and retain a downloadable baseline.
- Seed each legacy 1° maximum into two adjacent 0.5° bins (12° → 12° and 12.5°); label coarse seed provenance and preserve farther maxima. Reapply the preserved baseline on restart for existing 0.5° installations.
- Export ordered empirical GeoJSON points plus the exact rendered envelope; break at empty bins and emit a polygon only for complete coverage.
- Document the developer-only history tool and range-envelope evolution.

## 0.5.3

- Add FAA SWIM TFMS as a fourth explicitly selectable aircraft source, using independent Solace PubSub+ transport with TLS validation and durable-queue acknowledgements.
- Parse TFMS message attributes and current-position DMS coordinates, including full direction names; exclude upcoming route points from current positions.
- Apply a configurable geographic gate around Home Assistant Home and publish accepted tracks through existing aircraft/map endpoints.
- Calculate course over ground from successive newer timestamped positions, with movement, elapsed-time and implied-speed checks; ignore duplicate/out-of-order fixes.
- Show airline, departure/arrival airports, aircraft/user categories, timestamps and raw assigned-altitude metadata in map popups.
- Match TFMS origin/destination badges directly from airport metadata; document four-letter airport identifiers.
- Query TFMS history by callsign at http://192.168.0.1:8756/flight; retain configured ICAO-hex history queries for ADS-B sources.
- Append a 16-point compass label to numeric track/course while preserving the calculated-course label.
- Hide the observed coverage outline for TFMS; retain the ADS-B coverage display.
- Add bounded parser counters, message types and XML element/attribute-name diagnostics without raw XML values.
- Preserve existing ADS-B input sources and establish a SWIM adapter boundary without incorporating FAA JumpStart source code.

## 0.5.2

- Hardened Leaflet sizing/redraw behavior for Home Assistant Ingress navigation and `fitBounds()` transitions.
- Render maximum-observed-range coverage as 1-degree stepped sectors instead of center-point interpolation.
- Added persistent maximum observed range to the map status panel.
- Added selectable map enrichment (`adsb_tracker` or `none`), retaining Tracker as the upgrade-compatible default.
- Refreshed the Home marker icon.
- Added an optional, configuration-only historical ICAO track overlay for installations with a compatible `/flight?hex=` service.


## 0.5.1

- Add GeoJSON export for observed range coverage, including a closed maximum-range LineString and per-bearing Point features with observation metadata.
- Add range-coverage backup/restore on the status page, with validated merge import that retains the farther maximum in each bearing bin.

- Add a persistent 360-degree maximum-observed-range coverage outline to the Raw ADS-B Map.
- Record the farthest positioned aircraft observed in each 1-degree bearing bin from `zone.home`.
- Persist coverage records under `/data` so the learned envelope survives app and HAOS restarts.
- Connect successive populated bearing bins on the map, spanning empty bins visually without creating synthetic observations.
- Continuously expand a bearing bin only when a farther aircraft is observed; records never shrink automatically.
- Keep coverage collection independent of optional ADSB Aircraft Tracker enrichment.
- Preserve altitude, aircraft identity, callsign, position, and observation time as metadata for each distance record.
- Track coverage convergence metadata: collection start, first observation per bin, per-bin update count, total updates, first fills, record replacements, last update, and hourly update counts.
- Migrate existing v0.5.1 coverage data in place without discarding learned maximum ranges.


## 0.5.0

- Add optional Raw ADS-B Map enrichment from ADSB Aircraft Tracker when its Home Assistant entities are available.
- Highlight Tracker-classified military aircraft in green.
- Add a red halo to Tracker's current closest aircraft.
- Add an optional configured origin/destination airport highlight using Tracker route data.
- Enrich aircraft popups with Tracker identity/route metadata and explicit military/closest/O/D status.
- Improve marker orientation with calculated course-over-ground fallback and correct the airplane glyph rotation offset.
- Prevent open aircraft popups from forcing map recentering during refresh.
- Report Tracker enrichment discovery in the app log and status page.
- Match enrichment to bridge aircraft only by ICAO hex; the selected bridge source remains authoritative for map position/state.
- Keep `/aircraft.json` and `/data/aircraft.json` unchanged by Tracker enrichment.
- Preserve the v0.4.0 Raw ADS-B Map behavior when ADSB Aircraft Tracker is absent or unavailable.

## 0.4.0

- Add a third mutually exclusive input source for a standard dump1090/readsb `aircraft.json` URL.
- Preserve explicit source selection: SBS/BaseStation, FR24 flights.js, or aircraft.json; no source merging or automatic fallback.
- Normalize and republish the selected aircraft.json source through the existing bridge endpoints and Raw ADS-B Map.
- Enable the supported Home Assistant Core API proxy and display `zone.home` on the map when available.
- Keep Home coordinates out of bridge status, aircraft output, logs, and tile diagnostics.
- Add a responsive two-row map header for narrow/mobile displays while preserving the desktop layout.
- Retain v0.3.0 map, tile proxy, SBS/flights.js behavior, and endpoint compatibility.

## 0.3.0

- Add a Raw ADS-B Map as the default Home Assistant Ingress/sidebar view.
- Plot all currently positioned aircraft from the bridge snapshot.
- Update markers once per second without resetting user pan/zoom.
- Fit the initial map to all positioned aircraft and provide a manual **Fit aircraft** control.
- Rotate aircraft symbols using reported track and show raw ADS-B/SBS fields in popups.
- Keep the existing bridge input, state assembly, and JSON endpoints unchanged.
- Move the existing human-readable status page to `/status-page`.
- Route map tiles through the bridge with an identifiable OpenStreetMap User-Agent, viewport-only requests, HTTP cache-header preservation, and conditional cache revalidation.
- Add a compact lower-right operational status panel to the Raw ADS-B Map.
- Preserve an origin-only web Referer through Home Assistant Ingress for upstream map-tile requests.
- Reject blocked or non-PNG upstream tile responses so invalid responses are never written to the tile cache.

## 0.2.0

- Adds the receiver's SBS/BaseStation TCP feed on port `30003` as the recommended/default input source.
- Retains the authenticated `/flights.js` feed as an explicitly selectable alternate source.
- Continuously consumes SBS messages and consolidates them into one aircraft state record per ICAO address.
- Publishes SBS-derived aircraft snapshots once per second without throttling the receiver input stream.
- Adds decoder-like `seen`, `seen_pos`, cumulative `messages`, barometric vertical rate, and squawk data when supplied by SBS.
- Adds SBS connection, message-rate, parse-error, and reconnection information to `/status` and the Ingress status page.
- Keeps the existing dump1090/readsb endpoints and v0.1.1 flights.js mapping behavior.
- Does not automatically fail over between input sources; source selection remains explicit.

## 0.1.1

- Adds Home Assistant Ingress support for the human-readable bridge status page.
- Adds an optional Home Assistant sidebar panel through the app's **Show in sidebar** setting.
- Makes status-page endpoint links relative so they continue to work through the Ingress path.
- Keeps port `8085` unpublished to the LAN by default.

## 0.1.0

- Initial HAOS app package based on the tested FR24-to-dump1090 Python service.
- Adds Supervisor configuration for receiver host, credentials, polling, and timeout.
- Uses Python HTTP Digest authentication instead of an external curl subprocess.
- Preserves `/aircraft.json`, `/data/aircraft.json`, `/status`, `/health`, and the human status page.
- Keeps service health separate from upstream FR24 feed health.
- Uses conservative FR24-to-dump1090 field mapping.
