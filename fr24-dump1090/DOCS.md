> **Before installing an update, press Ctrl+Shift+R to refresh this page.**

## v0.7.3 — usability, history and reliability

- Selected aircraft show a reported-destination × and dashed line that persist after popup closure and update with the aircraft until another track is selected.
- Cyan rings highlight projected passes within 3 NM slant range of Home in the next five minutes. A separate purple dashed halo marks fresh aircraft currently within 0.3333 NM horizontally, at any altitude. Both controls are under Motion.
- Qualifying local routes retain up to 24 hours of observed sampled history on disk; other traffic keeps a rolling hour. Both reported airports must be covered, with observations within 10 NM of an endpoint. Export all combines both stores. Collection gaps and late acquisition can leave incomplete trips.
- Configuration groups separate basic setup, personalization, integrations, additional local feeds, FAA SWIM and developer/troubleshooting options. Existing flat settings migrate with compatibility support.
- Expanded popup facets survive SBS and other supported feed updates. Experimental day recording is hidden unless enabled in Developer / troubleshooting.

Home predictions use constant observed velocity and approximate altitude references; they describe geometry, not intent or operational separation. Automatic FAA feed bridging remains disabled.

# FR24 dump1090 Bridge — Home Assistant

## Current operation (v0.7.2)

The map offers an immediate **Auto / Light / Dark** theme selector. Destination popups may show a direct-distance/current-ground-speed ETA and, for qualifying aircraft, a separately labeled **experimental** modeled touchdown range. Motion classifications and activity coloring depend on source quality; TFMS and coarse `flights.js` reports are excluded. Traffic density uses cached tiles and daily rollups. Density envelopes use optimized SQL aggregation and bounded NumPy batches; separate Load/Build controls preserve the last successful set across restarts. See the [changelog](CHANGELOG.md) for development history and the `docs/` testing records for validation.

## Configuration

The bridge supports five mutually exclusive aircraft input sources. Exactly one source is selected at startup.

- **SBS/BaseStation (`sbs_30003`) — recommended/default for FR24 receivers.** Connects to the receiver's local TCP BaseStation feed, normally on port `30003`. Only the receiver host is required for this mode.
- **FR24 web feed (`flights_js`) — alternate.** Polls the receiver's authenticated `/flights.js` endpoint. This mode requires the receiver HTTP port, username, and password.
- **dump1090/readsb JSON (`aircraft_json`) — alternate.** Polls a configured HTTP or HTTPS `aircraft.json` URL. The bridge validates the standard top-level aircraft array, normalizes ICAO `hex` values, preserves supplied aircraft fields, and republishes the selected source through the bridge endpoints.

- **FAA SWIM TFMS (`swim_tfms`) — local-view-only.** Uses an authorized FAA Solace subscription; requires broker host/port, message VPN, username, password and queue. Positioned tracks are gated around Home Assistant Home.
- **FAA SWIM SFDPS (`swim_sfdps`) — local-view-only.** Uses an authorized FAA Solace subscription for FIXM surveillance tracks, with local density and motion display. **Neither FAA source publishes an automatic aircraft feed. Deliberate local analytical downloads are available.**

Default operational values:

- Input source: `sbs_30003`
- SBS/BaseStation port: `30003`
- FR24 HTTP port: `80`
- flights.js poll interval: `2` seconds
- aircraft.json poll interval: `1` second
- HTTP request timeout: `3` seconds per attempt

Changing the source requires an app restart. The bridge does not automatically fail over between sources.

## SBS/BaseStation behavior

The SBS reader consumes the TCP stream continuously and updates an in-memory aircraft state table keyed by ICAO address. The input stream is not throttled. Once per second the bridge publishes a consolidated dump1090/readsb-style snapshot containing one record per active aircraft.

Aircraft state is removed after 60 seconds without an SBS message. `seen` reports the age of the aircraft's most recent SBS message, while `seen_pos` reports the age of its most recent position. The top-level `messages` value is the cumulative count of valid SBS `MSG` records received since the bridge started.

The bridge maps supported SBS fields including callsign, barometric altitude/on-ground state, ground speed, track, position, barometric vertical rate, and squawk. Different SBS message types contribute fields to the same aircraft state; an individual SBS line is not emitted as an individual aircraft record.

## flights.js behavior

The alternate `flights_js` mode retains the v0.1.1 mapping behavior. It keeps aircraft without positions, omits ambiguous zero altitude/speed values, does not invent an on-ground state, and does not synthesize geometric altitude from the single altitude exposed by `/flights.js`.

The last good aircraft snapshot remains available if the receiver becomes unavailable. `/status` reports the feed as degraded after 10 seconds without fresh input and unhealthy after 30 seconds. `/health` remains healthy while the bridge process itself is responsive so an upstream receiver outage does not create a Supervisor restart loop.

## aircraft.json behavior

The `aircraft_json` source polls the configured `aircraft_json_url` and republishes one normalized snapshot at a time. Aircraft records must be objects with a non-empty `hex` field; the bridge lowercases `hex` and otherwise preserves supplied fields. If the source omits a numeric top-level `now` or `messages`, the bridge supplies a current timestamp or current aircraft count respectively.

The last good snapshot remains available during temporary upstream failures. Source selection is explicit; the bridge does not merge sources and does not automatically fail over between them.

## Optional ADSB Aircraft Tracker map enrichment

The Bridge can use the Home Assistant entities provided by **ADSB Aircraft Tracker** to enrich the Raw ADS-B Map. Tracker remains optional and is not an aircraft input source. The bridge matches Tracker information to currently mapped aircraft by ICAO `hex` only.

When Tracker data is available, military aircraft are shown in green and Tracker's current closest aircraft receives a red halo. An optional **Origin/destination airport highlight** setting accepts an IATA airport code and marks aircraft with **O** when Tracker `route_origin` matches or **D** when `route_destination` matches. Tracker metadata also enriches aircraft popups when available. These states can overlap on the same aircraft. The map uses reported track when available and derives course over ground from successive positions as a fallback for stale/missing orientation.

Tracker enrichment is presentation-only. It does not modify `/aircraft.json` or `/data/aircraft.json`, does not merge aircraft sources, and does not duplicate Tracker's military or route logic. If Tracker is not installed, its entities are unavailable, or enrichment cannot be read, the map continues with available source data.

### TFMS airport matching and map display

When using TFMS, enter the full four-letter airport identifier in `destination_airport`, matching the feed (for example, `KSYR` rather than `SYR`). For most airports in the contiguous United States, this means adding `K` to the three-letter code. Alaska and Hawaii use different prefixes; use the actual identifier rather than automatically adding `K`. Origin (O) and destination (D) badges compare this setting directly with TFMS departure and arrival airport codes, ignoring case.

The observed coverage outline is hidden for TFMS because its boundary reflects the configured geographic filter rather than radio reception. Numeric track/course remains visible with a 16-point compass label, such as `274.4° (W)`; calculated course retains its `(course)` label.

Track history is a developer-only tool shown only when `history_url` is configured. Contact the author for an API description. The configured base URL receives `/flight?callsign=...` for TFMS or `/flight?hex=...` for ADS-B.


## Home marker

The bridge requests `zone.home` from Home Assistant through the supported Supervisor/Core API proxy enabled by `homeassistant_api: true`. When latitude and longitude are available, the Raw ADS-B Map displays a Home marker and the zone radius. The coordinates also support ADS-B range calculations, density-envelope distances, and the TFMS geographic filter. They are not added to `/status`, `/aircraft.json`, logs, or tile diagnostics. If `zone.home` cannot be read, aircraft mapping continues normally without a Home marker.

## Internal Home Assistant access

Home Assistant generates an app's internal DNS name as `{REPO}_{SLUG}`, with underscores changed to hyphens for use as a hostname. A local development installation therefore uses a name such as `local-fr24-dump1090`.

A GitHub repository installation uses a repository identifier generated by Home Assistant, so its hostname will **not** retain the `local-` prefix. Do not copy the development hostname into a production configuration without checking the installed app's actual network identity.

For non-FAA sources, consumers can use `/aircraft.json` or `/data/aircraft.json` as required. Both routes are unavailable for FAA sources.

## Home Assistant web UI (Ingress)

The app supports Home Assistant Ingress for the **Raw ADS-B Map**, which is the default web interface. Use **Open Web UI** from the app Info page to open the map through Home Assistant without publishing port `8085` to the LAN.

If desired, enable **Show in sidebar** on the app Info page for direct access from the Home Assistant sidebar. The detailed human-readable status page is available from the map or at `/status-page`. Integrations such as ADSB Aircraft Tracker can continue to use the app's internal hostname and port `8085`.

## Optional LAN access

The app declares container port 8085 with no host mapping by default. If a client outside Home Assistant needs the feed, assign a host port in the app's **Network** settings, then configure the consumer to use the Home Assistant host address and that port.

## Status endpoints

`/status` reports the build version, coverage resolution, bridge uptime, selected input source, receiver/feed state, aircraft totals, and source-specific statistics. SBS mode reports message rate/count, last-message age, parse errors, and connection/reconnection counts. flights.js and aircraft.json modes report poll timing and success/failure counts. aircraft.json mode also reports upstream message count/rate when the source supplies a cumulative numeric `messages` value.

`/health` intentionally reports process/service health rather than upstream FR24 receiver health.

### HTTP endpoint reference

- `/` — Raw ADS-B Map
- `/aircraft.json` — dump1090/readsb-compatible aircraft feed (non-FAA only)
- `/data/aircraft.json` — compatibility alias (non-FAA only)
- `/status` — machine-readable bridge and active-source status
- `/status-page` — human-readable status page
- `/health` — bridge process/service health
- `/range-coverage` — observed maximum-range coverage and convergence metadata
- `/range-coverage.geojson` — live coverage exported as GeoJSON
- `POST /range-coverage/import` — validated merge/restore of exported coverage JSON
- `/tracker-enrichment` — optional ADSB Aircraft Tracker map enrichment
- `/map-config` — map configuration used by the Raw ADS-B Map
- `/tile-debug` — map tile proxy diagnostics
- `/settings` — settings backup and recovery
- `/traffic-density` — density cell statistics
- `/traffic-density/status` — collection and query diagnostics
- `/traffic-density/export` — density JSON backup (optional `?month=YYYY-MM`)
- `POST /traffic-density/import` — validated density restore
- `/traffic-density.geojson` — spatial density export
- `/traffic-density/envelopes` — density-derived range comparison; legacy requests retain the short-lived calculation cache.
- `/traffic-density/envelopes?action=build` — explicitly rebuild and save the selected/default date window, bypassing the calculation cache.
- `/traffic-density/envelopes?action=load` — load the saved result without rebuilding; returns 400 when no matching set exists.
- `/traffic-density/envelopes?action=status` — saved availability, age, timestamp and date window; does not build. These envelope routes are disabled for FAA sources.
- `/traffic-density/envelopes.geojson` — range-comparison GeoJSON export
- `/range-coverage-baseline` — preserved 1° baseline, when available
- `POST /data/clear` — confirmed selective or all-source data clearing
- `/tiles/{z}/{x}/{y}.png` — internal map-tile proxy route used by the map

## Mobile map behavior

The Raw ADS-B Map uses a responsive header on narrow displays. On mobile
devices, map status information wraps into a two-row layout while preserving
the full desktop presentation on wider screens. Aircraft controls, popups,
status information, and the Home marker remain available on mobile displays.

## Compatibility notes

The output is a conservative compatibility feed, not a byte-for-byte clone of dump1090/readsb.

In SBS mode, `seen`, `seen_pos`, and cumulative `messages` have useful decoder-like semantics. In flights.js mode, `seen` remains synthetic `0` and `messages` remains the current aircraft count because equivalent source information is unavailable. In aircraft.json mode, compatible source fields and top-level counters are preserved when supplied.

`alt_geom` is not synthesized by the SBS or flights.js translators; aircraft.json mode preserves it when the selected source supplies it. Aircraft without positions remain in the feed and should be ignored by consumers for geographic nearest/closest calculations.


## Troubleshooting

If no aircraft are available, first check `/status` or `/status-page` and
confirm that the selected input source is connected or successfully polling.

For `sbs_30003`, verify that the configured receiver is reachable on TCP port
`30003`.

For `flights_js`, verify the receiver address, HTTP port, username, and
password.

For `aircraft_json`, verify that the configured URL is reachable from the app
and returns a dump1090/readsb-compatible JSON object containing an `aircraft`
array.

If the Raw ADS-B Map contains aircraft but no Home marker, verify that
`zone.home` exists in Home Assistant and contains valid latitude and longitude
attributes. Without `zone.home`, ADS-B feeds and density collection continue, but Home-based range products are unavailable. TFMS needs Home for its geographic filter.

If another Home Assistant integration cannot reach the bridge, verify the
installed app's internal hostname and use port `8085`. The hostname assigned
to a GitHub-installed app differs from the `local-` hostname used for local
development installations.

## Maximum observed range coverage

The Raw ADS-B Map maintains 720 persistent 0.5-degree bearing bins under `/data/range-coverage.json`. Distance is the sole record-selection metric: a bin is replaced only when a farther positioned aircraft is observed. Altitude, aircraft identity, callsign, position, and timestamps are metadata for the winning distance observation. Empty bins remain gaps in the rendered stepped envelope; they are never bridged or populated by interpolation.

The `/range-coverage` diagnostic endpoint includes convergence metadata: collection start, total updates, first fills, record replacements, last update, hourly update counts, and each bin's first-observed time and update count. Existing v0.5.1 coverage files are migrated without resetting learned ranges.

### Coverage backup and restore

The status page provides **Export coverage JSON** and **Import / merge coverage** controls. Export saves the current `/range-coverage` payload before an uninstall/reinstall. Import posts that JSON to `/range-coverage/import`, validates either 1-degree legacy or 0.5-degree native bin data, and merges it with the current history by bearing. The farther `distance_nm` wins, so importing an older backup cannot replace a newer maximum. The merged result is flushed immediately to `/data/range-coverage.json`. **Export coverage GeoJSON** downloads `/range-coverage.geojson`, generated on demand from the same live table. It contains ordered empirical Point features and the exact stepped map envelope: open MultiLineString runs for incomplete data, or a Polygon only when all 720 bins are populated.


### Optional map enrichment

Map enrichment can be selected with `enrichment_source`. The default `adsb_tracker` preserves existing behavior; set it to `none` to disable ADSB Aircraft Tracker enrichment without changing the selected aircraft data source.


### Coverage migration in v0.5.4

The original 1° file is archived as `/data/range-coverage.json.1-degree-baseline.json` before migration and retained as `baseline_1_degree` in exported JSON. Use **Export 1° baseline** on the status page to download it. Legacy maxima seed two adjacent bins (12° → 12° and 12.5°), including on restart from a preserved baseline. Each copy is labeled `legacy_adjacent_seed`; it is not a separate observation. Seeding does not require Home. Imports retain the farther maximum and include source-resolution provenance. Previously discarded observations cannot be reconstructed. GeoJSON and the map use the same derived sector boundary; raw source positions retain provenance; duplicated legacy seed points are identified as `legacy_sector_seed` in GeoJSON.


## Traffic Density

The map's **Traffic Density** layer is off by default; collection runs for every selected-source publication whether the layer is enabled or not. Fine geographic quadtree cells are approximately 153 × 227 m at 42°N. Each occupied cell retains observation/passage counts, Low (<1,200 ft), Middle (1,200–17,999 ft), High (≥18,000 ft), Unknown, altitude min/max and daily timestamps. Only actual positioned observations contribute.

Data is separate from 0.5° / 720-bin range coverage, in `/data/traffic-density/<source>/YYYY-MM.dat` SQLite chunks. Eighteen calendar months are retained. The default view covers today plus the preceding 29 UTC dates, reconstructed from daily counters across monthly boundaries; it is not an exact arbitrary-hour rolling window.

Use the status page's density JSON export/import controls for backup and restore. Large histories should be exported/restored by month through its backup selector. Imports choose whole cell/month snapshots without adding overlapping counts and explicitly mark uncertain starts. Recent GeoJSON exports contain occupied cell polygons and statistics; GeoJSON cannot restore history. Back up both datasets before destructive App lifecycle operations.

API: `/traffic-density`, `/traffic-density.geojson`, `/traffic-density/export`, `/traffic-density/export?month=YYYY-MM`, `/traffic-density/status`, and `POST /traffic-density/import`. Query `start`/`end` are inclusive UTC dates; `zoom` selects hierarchy level 0–17 and optional `bbox` limits the viewport. Parent passage counts sum base-cell passages, rather than deduplicating coarse-cell entries. Passage jitter/dropout suppression uses 90 seconds and resets on restart/restore.

The [density schema and sizing notes](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/docs/traffic-density-v0.6.0.md) document sizing, schema, limits and validation. Low/Middle/High selections and All Traffic are available, together with separate density-derived envelope comparisons.


### FAA SWIM/TFMS density limitations

Traffic Density remains available for FAA SWIM/TFMS, but its spatial detail is limited by the position reports supplied by the feed. Report cadence varies by feed and track; observed examples updated approximately once per minute, leaving gaps between occupied cells even along a continuous flight. This is a sampling interval, not a measured minute of delivery latency: a three-image check of one track was consistent with delivery/display delay of only a few seconds, subject to clock and browser timing. These examples do not establish cadence or latency for every TFMS track. An empty cell therefore means no position was observed there; it does not establish that no aircraft passed through it. Observations count eligible retained positions in local map snapshots, not distinct FAA reports: the same reported position can receive multiple observation credits while it remains eligible. This is local density accounting, not redistribution. Counts consequently reflect both report availability and snapshot retention, and should not be compared directly with ADS-B feeds as independent position-report counts or interpreted as measured time spent in each cell.

The Bridge deliberately does not interpolate between reports or extrapolate beyond the latest report to fill density gaps. Great-circle connections, three-point smoothing and constrained-turn paths can suggest plausible trajectories, but cannot establish which cells an aircraft actually traversed between sparse reports. Filling those cells would turn inferred motion into apparent observations and could introduce false routes or maneuver artifacts, especially during turns, holding patterns or report gaps. Density therefore credits only the reported-position cells represented in eligible snapshots. Any future inferred-track presentation should remain explicitly distinguishable from the observed density dataset.

### TFMS range processing

Selecting `swim_tfms` disables the range-coverage worker entirely, including coverage-file loading, migration and periodic flushing. Existing ADS-B coverage files are preserved for a later switch back to an ADS-B source. The coverage outline remains hidden for TFMS. Home-marker processing and Traffic Density collection continue; TFMS still needs Home for its geographic filter.


### Responsive map controls

Bridge status is collapsible: tap/click its heading to open or close it. On narrow or short screens it starts closed. Its expanded contents scroll within the available space. Status and track controls share a wrapping bottom dock, while the top toolbar leaves room for the zoom buttons. Layout updates when the screen rotates or controls change. 


## Source identity and legacy density upgrade

Page titles, density stores and backup names identify the selected source. The Range ring checkbox controls ADS-B display; FAA TFMS continues density collection with range processing disabled. Existing untagged density needs explicit `density_legacy_source` attribution on upgrade. See [upgrade and testing notes](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/docs/v0.6.x-development-validation.md) for large-backup behavior and static Home Assistant sidebar labels.


## Altitude heat maps and consistency envelopes

The static sidebar title is Aircraft Bridge. Traffic Density supports Low/Middle/High combinations and All Traffic including Unknown. ADS-B maps offer on-demand dashed density envelopes for consistency comparison at 0.5°; the status page provides custom dates and JSON/GeoJSON exports. FAA data remains restricted to authorized local viewing; deliberate density, envelope and history downloads are available for local retention and analysis. See [usage and verification notes](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/docs/v0.6.x-development-validation.md). Stored altitude counters and backup schema are preserved.

## Density refresh and data management

Traffic density loads once when enabled. After panning, zooming or changing altitude selections, a fully cached fresh view loads automatically; otherwise use **Load density** or **Refresh now** beside **Fit aircraft** as indicated. The previous layer remains visible while loading. The compact result shows the date window, selected bands, cell count, timestamp and cached/to-build/stale tile inventory. Collection continues at zoom 17 regardless of layer visibility; radial coverage remains 0.5° / 720 bins. Indexed viewport queries and parent daily rollups accelerate uncached views; density tiles can be reused for up to two hours. Full exports read stored history rather than the displayed tile snapshot.

### Large density restores outside Ingress

The Bridge no longer imposes its original 256 MiB density-import ceiling; imports are disk-staged. Home Assistant Ingress has separate upload/proxy limits, so a large restore may still report **Failed to fetch**. Use the Bridge directly on your LAN for large backups:

1. Open **Settings → Apps → FR24 dump1090 Bridge → Configuration** (called Add-ons on older Home Assistant versions).
2. Under **Network**, assign an unused host port to the `8085/tcp` service, for example `8085`. Enable **Show disabled ports** if the mapping is hidden. Save and restart the App.
3. In a browser on your LAN, open `http://<Home-Assistant-IP>:<assigned-port>/status-page`, for example `http://192.168.0.100:8085/status-page`. Use the Home Assistant host IP, not the receiver IP or App internal hostname. Each Bridge instance needs a different host port.
4. Select the density JSON backup and press **Restore density JSON**. Leave the page open until the restore completes. Confirm the source matches; explicitly attribute older untagged backups only when their source is known.
5. Open `http://<Home-Assistant-IP>:<assigned-port>/` to inspect density, or return to Open Web UI. You can disable the host port after restoring.

The direct HTTP service has no authentication; expose it only on your trusted LAN. Ingress remains available for normal viewing. A failed browser request does not establish whether the server finished the restore; check collection status and logs before retrying.

### Configuration fields

SWIM VPN and the other optional connection fields have explicit blank defaults. Enable **Show unused optional configuration options** when reviewing an existing installation whose saved options omit fields. Supply only the settings needed by the selected source. TFMS requires SWIM host, message VPN, username, password and queue. The App validates these at startup; the VPN is the Solace message VPN, not a home-network VPN. The Supervisor owns the configuration form; source selection does not dynamically hide unrelated fields.

### Danger Zone

Below Diagnostics on the status page:

- **Clear current-source traffic density** deletes that source's observations, daily statistics and passage state.
- **Clear range coverage and legacy baseline** resets the 720 bins and deletes the saved 1° baseline.
- **Clear all collected data (all sources)** clears density for every source in this App instance plus range coverage and its baseline.

Export backups first. Individual actions require typing `CLEAR`; the all-data action requires `CLEAR ALL`. Configuration, credentials and other App instances are preserved. Collection resumes from empty datasets. Clear operations are serialized with collection and restore.

## Settings recovery and compact controls

The map places **Density altitude selection** and **Density envelopes · comparison** side by side. Expand either or both independently. On small screens they stack. **Load density** sits beside **Fit aircraft** and loads the heat cells for the current viewport and selected altitude bands; **Refresh now** explicitly rebuilds visible density tiles. **Build envelopes** generates the separate density-derived range outlines and **Load envelopes** retrieves the last saved build. Pending heat views load automatically when all required tiles are fresh and cached; missing/stale tiles require the corresponding Load/Refresh action. **Range ring** stays on the main toolbar.

Status-page endpoints have a green border; the three density, envelope, and range export sections have yellow borders. The red Danger Zone follows the complete Diagnostics section, including the tile endpoint description.

### Persistent settings and recovery after reinstall

The App mounts its dedicated host configuration folder read/write at `/config` using `addon_config:rw`. Its slug remains `fr24_dump1090`. For a local installation the host folder is `/addon_configs/local_fr24_dump1090/`; repository installations use the repository identifier instead of `local`. Local and repository installations have separate folders.

At each successful configured startup, the App atomically saves its valid configuration to `/config/bridge-settings.json`, including feed credentials. The file uses owner-only permissions. Settings changes made in Home Assistant are captured when you restart the App. **Settings backup / recovery**, linked from the status page, also provides **Save current settings** and **Restore saved settings**. Treat this snapshot as a credential-bearing backup; keep the direct HTTP interface on a trusted LAN.

To test recovery:

1. Install v0.6.8 or later and start it with your working feed configuration. Open **Status → Settings backup / recovery** and confirm a saved snapshot is listed.
2. Export density/range backups before any uninstall test. They remain under `/data` and are not preserved by this settings feature.
3. Uninstall while leaving the option to delete the App configuration folder unchecked. Reinstall the same local or repository App identity and start it. Re-enter optional Network port mappings if using direct LAN access.
4. With blank/incomplete feed settings the App serves a recovery page instead of starting collection. Open the Web UI, select **Restore saved settings**, confirm, then restart the App from Home Assistant. The restore writes the App's options through Supervisor; it does not silently override settings at startup.
5. Verify Configuration and `/status` show your chosen source and the feed reconnects.

Deleting the configuration folder also deletes the retained settings snapshot. Home Assistant Home coordinates, Network port mappings, boot/watchdog preferences, density history and range coverage are outside this settings snapshot. No persistent-data migration is performed. A damaged snapshot is preserved and reported rather than overwritten. Settings recovery needs Supervisor; non-HA standalone runs can read the retained JSON manually.

Implementation references: [public App configuration folder](https://developers.home-assistant.io/blog/2023/11/06/public-addon-config/) and [Supervisor App options](https://developers.home-assistant.io/docs/api/supervisor/endpoints/).

## Data-operation logging

App logs record timestamped starts and outcomes for density/range imports, data exports, envelope generation and saved loads, and Danger Zone clears. Entries include the selected source and dataset, elapsed seconds, HTTP status, available merge/bin/feature counts, clear target, and input/response byte counts where applicable. Failed requests and disconnected transfers are distinguished from completed responses. Response completion means the server sent the export, not proof that a browser saved it to disk.

Routine heat-map queries retain their existing timing diagnostics. Automatic five-second range polling is excluded from export audit logs; range JSON download links use `?download=1` to identify explicit exports. Direct `/range-coverage` API reads remain polling reads unless that marker is supplied. Logs do not include feed credentials, configuration contents, or URL query strings.

After restoring or clearing data on the status page, reload the map to discard its displayed snapshot. For heat cells, use Load density or Refresh now; for envelope comparisons, use Build envelopes again because import/clear invalidates the saved set. Collection continues after a clear, so new observations can begin accumulating immediately.

Port mappings and Show in sidebar remain outside the settings snapshot. After changing a Network port mapping in Home Assistant, restart the App to apply it.



## Saved density envelopes

Use **Build envelopes** to generate a new 30-day comparison, and **Load envelopes** to display the last successful saved build. Saved builds survive restarts. The age next to Load recommends refresh after 12 hours; older builds remain loadable. Source and Home must match. Importing or clearing density history invalidates the saved result.

Saved envelope builds are derived data. Normal new observations do not invalidate them; the displayed age identifies the snapshot. The saved UTC date window remains visible and is not silently shifted at midnight. There is one saved set per source, including when a custom date-window build replaces it. Range coverage remains independent.

With `verbose_logging` enabled, `[DEBUG] Envelope diagnostics` reports a per-request ID, lock waits, snapshot bytes/copy time, SQL aggregation VM steps and grouped-cell counts, NumPy batch/cell counts, and stage elapsed times. Ordinary Data operation entries report total HTTP time. Build is still synchronous: large histories can take more than a minute and a client/proxy timeout does not cancel server work. Load does not perform the expensive calculation. Temporary snapshot/aggregation files require free disk space proportional to the stored history.


## v0.7.2-dev.1 experimental geometry

Map controls can be collapsed without resetting selections. New motion filters cover racetrack/holding-like, repeated orbit, orbit candidate, constant-radius turn and reversal. Expand Observed geometry in an aircraft popup for candidate/established status and evidence. Pattern evidence scores are uncalibrated, not probabilities of intent. Geometry takes color precedence over basic motion; badges/glow remain. Stale data suppresses patterns.

At most 360 independent geometry positions / one hour per aircraft are held in memory. Restart or a source gap resets this history. Two circuits need to fit within that window; slow or large patterns can remain unclassified. Basic motion windows and existing density/range storage are unchanged. Motion summary logs include patterns, while status/verbose diagnostics report retained geometry samples/events. Exact gates and equations: [implemented geometry](../docs/motion-geometry-v0.7.2-dev.1.md).

The experimental modeled ETA is labeled Estimated touchdown · modeled; its assumptions exclude taxiing and actual runway/approach routing. Observed orbit/racetrack defers that model, with direct/current-speed ETA retained. Go-around-like detection is not implemented in this preview.

## Aircraft analytical history (dev.2)

`/aircraft-history?hex=a248f9&download=1` downloads retained JSON by reported ICAO. Use `?track_id=...` for an exact local track, or `?download=1` for all retained tracks. Selected trails and exports work across sources, including FAA inputs, within the configured trusted network boundary. See [history design and tests](../docs/v0.7.2-dev.2-testing.md) for sampling, source provenance, replay, retention and applicable-use details.


## v0.7.2-dev.4: airport context, compression and replay findings

See [dev.4 design and validation](../docs/v0.7.2-dev.4-testing.md) for exact airport-context gates, compression/API compatibility and captured-record replay findings. Geometry remains independent of tentative airport activity; no new holding intent or go-around classifier is claimed. Whole-loop recognition with interrupted/variable-radius turns remains future work. ETT logic is unchanged in dev.4.

History buttons now export selected/all retained aircraft as JSON.gz. Density backups stream JSON.gz and restore accepts JSON or gzip. Offline history replay accepts JSON, gzip and a ZIP containing one JSON file. Existing retention, source attribution and network access rules remain.


## v0.7.2-dev.7 — SBS recovery and selected proximity preview

The selected-aircraft proximity/CPA preview has been brought forward from the later roadmap milestone for evaluation. It does not complete all-pairs encounter detection. See [exact rules and validation](../docs/v0.7.2-dev.7-testing.md) for source-time alignment, altitude reference gates, bounded horizon, model quality, UI, endpoint and replay behavior. SBS byte-idle recovery reconnects silent sessions after 60 seconds.


## Development preview: 24-hour recording

Enable development recording visibility under **Developer / troubleshooting**, then expand **Map controls → Development recording**, then select **Start 24-hour recording**. The recorder is off by default. Controls show the original session deadline, retained snapshots and positioned samples, queue/disk usage, losses, process RSS, and estimated one-hour history RAM.

**Export recorded day** downloads compressed GeoJSON for GIS. **Export replay snapshots** downloads compressed JSONL for local offline motion-model replay. These are deliberate trusted-network downloads, including in FAA local-view mode; existing FAA bridge/feed endpoints remain disabled. Input is the normalized source collection snapshot, not every raw SBS message or Solace envelope. It is captured before the history sampler. Neither export substitutes inferred landing events or fills observation gaps.

A session lasts up to 24 hours and resumes after restart until its original deadline. Its completed window remains available for later download; starting a subsequent session advances the window. Stop can end collection early. Source-specific SQLite files are in `/data/aircraft-recording/`. The default storage limit is 2 GiB per source, including SQLite sidecars, plus a 64 MiB minimum free-space check. Storage checks occur per snapshot; a snapshot/transaction can exceed the ceiling slightly. `FR24_RECORDING_PATH` and `FR24_RECORDING_MAX_BYTES` environment overrides are available for development deployments. Queue bounds are 128 snapshots and 16 MiB of serialized input. Recording faults stop or drop recording input with diagnostics, independently of the live feed.

`GET /recording` exposes diagnostics. `POST /recording/start` and `POST /recording/stop` require `application/json` bodies, such as `{}`. `GET /recording/export?download=1&format=geojson` or `format=jsonl` creates an explicit download. Export reads stream from a stable SQLite transaction to a temporary gzip file; large exports may take time before the download begins and need temporary free space. The temporary file is removed after the response.

Resource samples are retained once per minute when input snapshots arrive. History RAM is an estimate based on container sizes and up to 128 latest per-track samples; shared objects can be counted repeatedly. Process RSS includes the whole app. Disk bytes include database/WAL/SHM and may fluctuate with checkpointing. These measures are not interchangeable with gzip export size.

This preview measures the real cost of longer retention. The live map's existing one-hour trail and Export all remain one-hour views; 24-hour active-track RAM retention and prior-motion highlighting are subsequent work.
