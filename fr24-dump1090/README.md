# FR24 dump1090 Bridge

## v0.7.0-dev.13 — Live map theme selector

Choose **Auto / Light / Dark** from **Map theme** in the map toolbar. The palette changes immediately without an App restart, page reload or density query. Auto continues to follow browser/device preference. Your choice remains active for that open map page, including periodic configuration refreshes. The App's saved `map_theme` setting is the default when opening/reloading a map page; it remains covered by settings backup/recovery.


## v0.7.0-dev.12 — Selectable map theme

Set `map_theme` to `auto` (default), `light`, or `dark` in App Configuration. Save and restart the App, then reload the map. Auto follows the browser/device color preference and responds when it changes; it does not read Home Assistant's separately selected frontend theme. Light and dark explicitly choose the basemap palette. Motion/aircraft, density, range and envelope colors remain unchanged. The setting is included in persistent settings backup/recovery; older configurations and snapshots default to auto.


## v0.7.0-dev.11 — SFDPS reported speed and modeled arrival preview

SFDPS speed primitives now use fresh **reported ground speed**. Position-derived speed remains visible in diagnostics and is the fallback when reported speed is missing/stale. Course/turns still use observed positions; altitude trends still use observed altitude. Each speed-dependent result records its basis, and the SFDPS popup shows **Motion speed source**. Speed-basis switches close previous speed events rather than merging unlike series. SBS/aircraft.json retain their existing position-derived detection. TFMS remains excluded from motion.

The existing **ETA · current ground speed** stays as a baseline and is now available on SFDPS local views. A separate **Estimated arrival · modeled** range is available for recognizable transport jets with fresh supported inbound motion, fresh reported ground speed, observed altitude provenance, and known airport elevation. It integrates descent and linear slowdown together; it does not add an entire descent duration to overlapping travel time. Expand Arrival assumptions for the two experimental profiles. They are assumed ground-speed scenarios, not indicated-airspeed rules or validated landing forecasts. Unknown types, stale/missing inputs, climbing/turning/outbound aircraft fall back with an explicit reason; short-distance/high-altitude cases report that extra route distance would be needed rather than force an impossible direct scenario.

Airport data now includes validated elevation and airport type from the October 12 pinned public-domain/PDDL snapshot. FAA data outputs remain disabled; arrival estimates are local map presentation only. See `docs/v0.7.0-dev.11-testing.md` and `docs/motion-analytics-engineering.md` for source selection, equations, profiles and limitations.


## v0.7.0-dev.10 — Automatic cached views and speed diagnostics

After pan/zoom or altitude changes, a fully cached, fresh density view loads automatically once movement settles. Missing or stale tiles keep **Load density needed** and require a manual load. Automatic requests are cache-only: an expiry or clear between the inventory check and load returns a pending view without starting SQL/rebuild work. **Refresh now** still explicitly forces rebuilding. Density loading on enable is unchanged.

With `verbose_logging` enabled, expand **Speed diagnostics** in an aircraft popup to see position-derived ground speed, reported speed, the latest-leg versus latest-report difference, derived speed min/median/max, range, fit residual, trend, accepted position intervals, and the exact stable-speed blockers. Verbose Motion diagnostics now summarize these values across fresh tracks without recording aircraft identifiers or positions. SBS/aircraft.json reported speed is labeled reported ground speed; SFDPS remains **reported speed (meaning unverified)**. Missing/stale reported fields are omitted from comparisons; unknown field timing is labeled snapshot assumption. These are diagnostic comparisons, not validation that the reported field and derived leg measure the same interval or speed quantity.

Detection thresholds, motion labels, SFDPS local-view isolation and source exclusions are unchanged. See `docs/v0.7.0-dev.10-testing.md` and the motion engineering notes. Repeated geometry remains the next increment, v0.7.1-dev.1.


## v0.7.0-dev.9 — Compact density status and SFDPS analytics

Enabling **Traffic Density** loads the selected view automatically. The compact summary shows the window, altitude selection, displayed cell count, oldest tile generation time, and **cached / to build / stale** tile counts. These counts describe the current requested viewport, not the previous request's hits/misses. Pan, zoom or change bands, then use **Load density**; **Refresh now** forces recomputation. The previous layer remains visible until the next load. When the view changes, its cell count/time still describe that displayed layer and the banner marks **Load density needed**. Cache inventory is checked without querying observations or building grids; stale tiles are checked once per minute while density is enabled. Grid resolution, timing and SQL details remain in `/traffic-density/status` and diagnostic logs.

SFDPS now collects source-separated density and supports local motion colors, filters and popup primitives. Density credits eligible reported-position cells in each Bridge publication snapshot, including repeated retained positions; it does not count only distinct FAA reports or fill paths between reports. Motion instead deduplicates actual SFDPS position timestamps and derives ground speed/course from independent positions. Its preview profile uses a 120-second window, at least five samples spanning 60 seconds, and a 45-second gap/freshness limit. Reported altitude retains the label `sfdps_reported_altitude`; its datum is not assumed to be ADS-B barometric altitude. These thresholds require validation against the user's authorized feed.

SFDPS range-bearing collection and density-derived envelopes remain disabled. FAA aircraft, density and per-track motion outputs remain unavailable as general feed/export APIs; SFDPS motion and density are rendered through the local viewer. Safe aggregate status and cache-inventory counters remain available. TFMS remains excluded from motion analytics; coarse `flights.js` positions remain excluded too. Existing source histories are preserved.


## Earlier preview: v0.7.0-dev.4 — SFDPS local view and larger aircraft

Aircraft markers are now 36 × 36 px (1.5×), with centered anchors. Select `swim_sfdps` to view authorized FAA SFDPS FIXM surveillance tracks using the existing SWIM connection fields and Home geographic gate. In dev.4, SFDPS had no density, range collection, motion analytics or data exports; existing histories are preserved. Both FAA sources now reject dump1090 aircraft feed URLs and general data exports. Native O/D metadata remains visible. See [dev.4 setup and verification](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/docs/v0.7.0-dev.4-testing.md).


Home Assistant App that normalizes real-time aircraft data from an explicitly selected source into consistent, dump1090/readsb-compatible aircraft feeds.

## 🌐 Architectural Overview

FR24 dump1090 Bridge acts as a local aircraft-data normalization layer. It accepts one explicitly selected aircraft source, maintains or translates the available aircraft state, and republishes that data through consistent dump1090/readsb-compatible `aircraft.json` endpoints.

The bridge does **not** decode ADS-B RF data, replace receiver hardware, or alter an FR24 receiver's normal uplink.

Source selection is explicit: exactly one aircraft source is active at a time. The bridge does **not** merge aircraft from multiple sources and does not automatically fail over between them.

## 📡 Supported Input Data Sources

1. **SBS/BaseStation TCP — Recommended/default**

   Connects continuously to an FR24 receiver's local TCP port `30003`. Individual SBS messages are assembled into an in-memory aircraft state table, from which the bridge publishes normalized aircraft snapshots once per second.

2. **FR24 `/flights.js` — Alternate**

   Periodically polls the local FR24 receiver's authenticated `/flights.js` endpoint and conservatively translates the receiver's aircraft snapshot into the common bridge output.

3. **dump1090/readsb `aircraft.json` — Alternate**

   Polls an existing dump1090/readsb-compatible `aircraft.json` URL, allowing the bridge and Raw ADS-B Map to operate with another standard aircraft-data source instead of an FR24 receiver.

4. **FAA SWIM TFMS — Alternate (v0.5.3)**

   Connects to the user's authorized FAA SWIM Solace queue, consumes TFMS messages, selects `trackInformation`, and retains positioned tracks inside a configurable radius around Home Assistant Home. The FAA-provided broker host, VPN, subscription username/password, and queue/JMS name are required. Credentials and queue identifiers are not returned by bridge diagnostics or logs. The Bridge treats TFMS as a mutually exclusive aircraft source; it does not merge TFMS with ADS-B sources.

## 🗺️ Raw ADS-B Map & Home Assistant Integration

The bridge provides a self-contained **Raw ADS-B Map** through Home Assistant Ingress.

Aircraft positions are displayed directly from the currently selected source. When ADSB Aircraft Tracker is installed, the Bridge can optionally use its Home Assistant entities for map-only military, closest-aircraft, and configured origin/destination-airport highlighting and richer aircraft popups. Tracker enrichment never changes the normalized aircraft feed, and the map retains its existing behavior when Tracker data is unavailable.

When available, the map can also obtain the location of Home Assistant's `zone.home` through the Home Assistant API and display it as a Home marker.

Home coordinates support the Home marker, ADS-B range calculations, density-envelope distances, and the TFMS geographic filter. They are not added to `/status`, `/aircraft.json`, `/data/aircraft.json`, application logs, or tile-proxy diagnostics.

The map interface also includes a responsive header designed to preserve the existing desktop presentation while fitting narrow mobile displays.

## 🔌 Downstream Endpoints & Compatibility

The bridge serves HTTP on container port `8085`. LAN publication is disabled by default; Home Assistant Ingress provides access to the Raw ADS-B Map without requiring the port to be exposed to the LAN.

Existing consumers such as **ADSB Aircraft Tracker for Home Assistant** can continue to use the bridge's dump1090/readsb-compatible endpoints regardless of which input source is selected.

- `/` — Raw ADS-B Map
- `/aircraft.json` — dump1090/readsb-compatible aircraft feed
- `/data/aircraft.json` — compatibility alias for the aircraft feed
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
- `/traffic-density/envelopes` — density-derived range comparison
- `/traffic-density/envelopes.geojson` — range-comparison GeoJSON export
- `/range-coverage-baseline` — preserved 1° baseline, when available
- `POST /data/clear` — confirmed selective or all-source data clearing
- `/tiles/{z}/{x}/{y}.png` — internal map-tile proxy route used by the map

Process health and aircraft-source health are intentionally separate. A temporary loss of the selected aircraft source does not by itself mean that the bridge process has failed.

See the app Documentation tab for detailed configuration, source behavior, Home Assistant integration, security, and compatibility information.

## Maximum observed range coverage

The Raw ADS-B Map learns a persistent receiver-coverage outline from the selected bridge aircraft source. Positioned aircraft are measured from Home Assistant `zone.home` and assigned to 720 half-degree bearing bins. Each bin retains only its farthest observed aircraft. The map draws successive populated bin footprints and breaks the outline at every empty bin. Coverage is saved under `/data` and continues learning across app and HAOS restarts.


### Range coverage backup / restore

Before uninstalling/reinstalling the app, use the status page to export the accumulated range-coverage JSON. After reinstall, import the saved JSON; the bridge validates it and merges each bearing bin by keeping the farther observed range. The restore endpoint is `POST /range-coverage/import`. The same status page can export the live coverage as GeoJSON from `/range-coverage.geojson` for GIS tools such as QGIS; the GeoJSON contains ordered empirical points plus the rendered envelope, with gaps retained and a polygon only for complete coverage.


### Optional map enrichment

Map enrichment can be selected with `enrichment_source`. The default `adsb_tracker` preserves existing behavior; set it to `none` to disable ADSB Aircraft Tracker enrichment without changing the selected aircraft data source.

### TFMS airport matching and map display

When using TFMS, enter the full four-letter airport identifier in `destination_airport`, matching the feed (for example, `KSYR` rather than `SYR`). For most airports in the contiguous United States, this means adding `K` to the three-letter code. Alaska and Hawaii use different prefixes; use the actual identifier rather than automatically adding `K`. Origin (O) and destination (D) badges compare this setting directly with TFMS departure and arrival airport codes, ignoring case.

The observed coverage outline is hidden for TFMS because its boundary reflects the configured geographic filter rather than radio reception. Numeric track/course remains visible with a 16-point compass label, such as `274.4° (W)`; calculated course retains its `(course)` label.

Track history is a developer-only tool shown only when `history_url` is configured. Contact the author for an API description. The configured base URL receives `/flight?callsign=...` for TFMS or `/flight?hex=...` for ADS-B.


### Coverage migration in v0.5.4

The original 1° file is archived as `/data/range-coverage.json.1-degree-baseline.json` before migration and retained as `baseline_1_degree` in exported JSON. Use **Export 1° baseline** on the status page to download it. Legacy maxima seed two adjacent bins (12° → 12° and 12.5°), including on restart from a preserved baseline. Each copy is labeled `legacy_adjacent_seed`; it is not a separate observation. Seeding does not require Home. Imports retain the farther maximum and include source-resolution provenance. Previously discarded observations cannot be reconstructed. GeoJSON and the map use the same derived sector boundary; raw source positions retain provenance; duplicated legacy seed points are identified as `legacy_sector_seed` in GeoJSON.


## Traffic Density

The map's **Traffic Density** layer is off by default; collection runs for every selected-source publication whether the layer is enabled or not. Fine geographic quadtree cells are approximately 153 × 227 m at 42°N. Each occupied cell retains observation/passage counts, Low (<1,200 ft), Middle (1,200–17,999 ft), High (≥18,000 ft), Unknown, altitude min/max and daily timestamps. Only actual positioned observations contribute.

Data is separate from 0.5° / 720-bin range coverage, in `/data/traffic-density/<source>/YYYY-MM.dat` SQLite chunks. Eighteen calendar months are retained. The default view covers today plus the preceding 29 UTC dates, reconstructed from daily counters across monthly boundaries; it is not an exact arbitrary-hour rolling window.

Use the status page's density JSON export/import controls for backup and restore. Large histories should be exported/restored by month through its backup selector. Imports choose whole cell/month snapshots without adding overlapping counts and explicitly mark uncertain starts. Recent GeoJSON exports contain occupied cell polygons and statistics; GeoJSON cannot restore history. Back up both datasets before destructive App lifecycle operations.

API: `/traffic-density`, `/traffic-density.geojson`, `/traffic-density/export`, `/traffic-density/export?month=YYYY-MM`, `/traffic-density/status`, and `POST /traffic-density/import`. Query `start`/`end` are inclusive UTC dates; `zoom` selects hierarchy level 0–17 and optional `bbox` limits the viewport. Parent passage counts sum base-cell passages, rather than deduplicating coarse-cell entries. Passage jitter/dropout suppression uses 90 seconds and resets on restart/restore.

The [density schema and sizing notes](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/docs/traffic-density-v0.6.0.md) document sizing, schema, limits and validation. Low/Middle/High selections and All Traffic are available, together with separate density-derived envelope comparisons.


### FAA SWIM/TFMS density limitations

Traffic Density remains available for FAA SWIM/TFMS, but its spatial detail is limited by the position reports supplied by the feed. Report cadence varies by feed and track; observed examples updated approximately once per minute, leaving gaps between occupied cells even along a continuous flight. This is a sampling interval, not a measured minute of delivery latency: a three-image check of one track was consistent with delivery/display delay of only a few seconds, subject to clock and browser timing. These examples do not establish cadence or latency for every TFMS track. An empty cell therefore means no position was observed there; it does not establish that no aircraft passed through it. In the current implementation, observations count aircraft represented in Bridge publication snapshots, not distinct FAA reports: the Bridge republishes retained TFMS positions once per second, so the same reported position can receive multiple observation credits while it remains eligible. Counts consequently reflect both report availability and snapshot retention, and should not be compared directly with ADS-B feeds as independent position-report counts or interpreted as measured time spent in each cell.

The Bridge deliberately does not interpolate between reports or extrapolate beyond the latest report to fill density gaps. Great-circle connections, three-point smoothing and constrained-turn paths can suggest plausible trajectories, but cannot establish which cells an aircraft actually traversed between sparse reports. Filling those cells would turn inferred motion into apparent observations and could introduce false routes or maneuver artifacts, especially during turns, holding patterns or report gaps. Density therefore credits only the reported-position cells represented in eligible snapshots. Any future inferred-track presentation should remain explicitly distinguishable from the observed density dataset.

### TFMS range processing

Selecting `swim_tfms` disables the range-coverage worker entirely, including coverage-file loading, migration and periodic flushing. Existing ADS-B coverage files are preserved for a later switch back to an ADS-B source. The coverage outline remains hidden for TFMS. Home-marker processing and Traffic Density collection continue; TFMS still needs Home for its geographic filter.


### Responsive map controls

Bridge status is collapsible: tap/click its heading to open or close it. On narrow or short screens it starts closed. Its expanded contents scroll within the available space. Status and track controls share a wrapping bottom dock, while the top toolbar leaves room for the zoom buttons. Layout updates when the screen rotates or controls change. 


## Source identity and legacy density upgrade

Page titles, density stores and backup names identify the selected source. The Range ring checkbox controls ADS-B display; FAA TFMS continues density collection with range processing disabled. Existing untagged density needs explicit `density_legacy_source` attribution on upgrade. See [upgrade and testing notes](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/docs/v0.6.3-testing.md) for large-backup behavior and static Home Assistant sidebar labels.


## Altitude heat maps and consistency envelopes

The default Home Assistant sidebar title is **Aircraft Bridge**. Map and page titles continue to identify the selected source. Traffic Density stays off by default; enable it and expand **Altitude selection** to choose Low (<1,200 ft), Middle (1,200–17,999 ft), High (≥18,000 ft), or any combination. **All Traffic** includes Unknown and is the initial selection. Selecting a band clears All Traffic; selecting All Traffic clears individual bands. No selection displays no density. Filters select observation counts for coloring without changing stored counters or full JSON backups.

For ADS-B sources, expand **Density envelopes · comparison**, generate the recent 30-day comparison, and toggle the dashed All/Low/Middle/High outlines. All four products share a source, Home position, UTC date window and **0.5° / 720-bin** bearings. The existing red range ring remains authoritative. The status page also offers custom dates and JSON/GeoJSON exports. FAA products can be generated there as **reported traffic extent**, but do not appear as receiver range rings. Generation is on demand and cached for up to five minutes; regenerating after that interval incorporates new observations.

Ranges use observed base-cell centers and are approximate. A notch that diminishes with altitude is consistent with screening, but is not a diagnosis: traffic availability, antenna response, propagation and receiver conditions also affect coverage. Sector exports include selected-band observations, occupied cells, furthest-cell support and combined passages in qualifying cells. Those passage counts are not altitude-specific; existing storage does not retain band-specific passage counters. Unknown altitude contributes only to All Traffic, and assigned FAA altitude is not used as observed altitude.

Source-separated history, retention, backups, passage counting and FAA snapshot behavior are unchanged. See [v0.6.4 usage and test notes](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/docs/v0.6.4-testing.md).

## Density refresh and data management

Traffic density loads once when enabled. Pan, zoom or change altitude selections, then press **Refresh density** beside **Fit aircraft**. The previous layer remains visible while loading. The result shows the actual density grid zoom, cell count and elapsed time. Collection continues at zoom 17 regardless of layer visibility; radial coverage remains 0.5° / 720 bins. Indexed viewport filtering avoids aggregating off-screen history. Small interactive results may reuse an all-band aggregate for up to 30 seconds; full exports always read the stored history.

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

The map places **Density altitude selection** and **Density envelopes · comparison** side by side. Expand either or both independently. On small screens they stack. **Refresh density** sits beside **Fit aircraft** and reloads the heat cells for the current viewport and selected altitude bands. **Generate envelopes** builds the separate density-derived range outlines. Panning, zooming, or changing altitude bands still marks the heat view pending until you refresh it. **Range ring** stays on the main toolbar.

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

App logs record timestamped starts and outcomes for density/range imports, data exports, envelope generation, and Danger Zone clears. Entries include the selected source and dataset, elapsed seconds, HTTP status, available merge/bin/feature counts, clear target, and input/response byte counts where applicable. Failed requests and disconnected transfers are distinguished from completed responses. Response completion means the server sent the export, not proof that a browser saved it to disk.

Routine heat-map queries retain their existing timing diagnostics. Automatic five-second range polling is excluded from export audit logs; range JSON download links use `?download=1` to identify explicit exports. Direct `/range-coverage` API reads remain polling reads unless that marker is supplied. Logs do not include feed credentials, configuration contents, or URL query strings.

After restoring or clearing data on the status page, reload the map to discard its displayed snapshot. For heat cells, use Refresh density; for an already generated envelope comparison, use Generate envelopes again. Collection continues after a clear, so new observations can begin accumulating immediately.

Port mappings and Show in sidebar remain outside the settings snapshot. After changing a Network port mapping in Home Assistant, restart the App to apply it.

## Release history

See the [changelog](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/fr24-dump1090/CHANGELOG.md) for the development sequence and earlier releases. The v0.6.0–v0.6.7 entries describe development iterations included in the public v0.6.8 release.

## Dashboard status card and feed dependencies — v0.6.9.3

Enable **Dashboard integration** in the App configuration, save and restart the App. After first installation or a companion integration upgrade, restart **Home Assistant Core**. In **Settings → Devices & services → Add integration**, choose **Aircraft Bridge** and select the App instance. Refresh the browser, edit a dashboard, and choose **Aircraft Bridge** from the card picker. Select its status entity in the visual editor. No manual file copying, YAML editing, REST sensor setup or exposed host port is required. See [dashboard setup and upgrade notes](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/dashboard/README.md).

The companion integration polls `/status` every ten seconds through the App’s internal hostname. Each local/repository App has a separate entity and Ingress path. The card defaults to a source-aware title and shows feed status, aircraft counts, version and recent dependencies; a custom title is optional. Map/status/settings buttons open the matching Ingress page. Status polling does not count as aircraft-feed consumption.

`/status` includes `feed_consumers`: recent internal/external client groups, a 60-second activity window, last-seen timestamps, mean polling intervals, and identification confidence. The built-in map identifies itself separately; external apps can append a non-sensitive `client_id` to their aircraft-feed URL. Without identifiers, shared gateway/User-Agent clients may collapse into one group, so the count is an estimate. Only successful aircraft-feed responses count; diagnostics do not. Tracking resets on restart. Recent activity helps identify dependencies before stopping or uninstalling, but zero recent consumers does not prove that no application relies on the feed.

The optional installer requires a read/write mount of Home Assistant’s configuration folder. It writes only its managed `custom_components/aircraft_bridge` package and nonsecret instance registrations under `aircraft-bridge/instances`; it does not edit `configuration.yaml` or dashboard storage. Aircraft credentials remain outside these registrations. Settings recovery retains the enable flag. Disabling the option unregisters this App on its next restart; remove the corresponding Devices & services entry if you no longer want it polled. The shared package is retained for other instances. No density/range migration is required.

### v0.6.9.2 dashboard fixes

The integration automatically registers a versioned dashboard module resource while preserving existing resources. Card navigation now supplies Home Assistant’s routing options for all three Ingress buttons. After upgrading, restart the App with Dashboard integration enabled, restart Home Assistant Core, and reload the browser; existing integration entries and cards remain valid. YAML-managed resources use frontend loading without editing YAML.

### v0.6.9.3 App navigation

Card links prefer the registered App sidebar route, such as `/local_fr24_dump1090`, and fall back to `/app/<full-slug>` when Show in sidebar is disabled. Old Ingress paths saved in cards are converted using the registered frontend panels, with compatibility for older HA. After upgrading, restart the App and Home Assistant Core, then reload the browser. Existing integration entries and cards remain valid.

## Destination estimate — v0.8.0 preview

Aircraft popups can show **Direct to destination** distance and **ETA · current ground speed**, including an approximate remaining duration and UTC arrival time. ADS-B destinations come from Tracker enrichment; TFMS uses the feed's arrival airport. The local airport lookup accepts exact identifiers and unambiguous IATA/ICAO aliases.

The estimate divides great-circle distance by the current reported ground speed in knots. It assumes direct flight and constant speed; routing, wind changes, descent, approach and holding can change arrival time substantially. It is an approximate map aid, not a flight-plan or operational ETA. TFMS sparse reports and retained positions also affect freshness. No estimate appears without a known destination, valid position and positive numeric ground speed, or when the aircraft is explicitly on the ground.

Airport coordinates are bundled from the OurAirports-derived `datasets/airport-codes` snapshot updated October 10, 2026, declared under PDDL. The Bridge remains Apache-2.0. See `fr24-dump1090/third_party/airports/` for provenance and regeneration instructions. Lookup is local through `/airport-lookup?codes=SYR,KSYR`; no external airport request is needed. The normalized aircraft feed and stored density/range history are unchanged.

This test build is **0.7.0-dev.1**. The motion/pattern roadmap is recorded in `docs/motion-pattern-roadmap.md`; basic motion primitives are included, while geometric pattern detectors remain future work. See `docs/v0.7.0-eta-testing.md` for validation.

## Motion foundation — v0.7.0-dev.1 preview

SBS and standard `aircraft.json` sources now collect bounded, transient motion history and derive basic observed states: steady flight, climb/descent, acceleration/deceleration and sustained left/right turns. Popups include supported labels and observed turn/vertical trends. `/motion/status` exposes eligibility, counters, limits and provisional thresholds; `/motion` returns derived states. Raw positions and primitive summaries remain in memory and reset on restart.

TFMS and FR24 `flights.js` are excluded from motion analytics because of sparse reports and coarse position precision respectively. Their existing feed, density, map and destination-ETA behavior continues. The normalized aircraft endpoints and persisted range/density datasets are unchanged.

For exact inputs, equations, thresholds, sampling, duration semantics and limitations, read [the implemented primitive guide](https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/docs/motion-primitives-v0.7.0-dev.1.md). This is a local test build; orbit/holding patterns, destination divergence, CPA/TCPA and formations are later work. The first public motion release is reserved as **v0.7.0**, after validation.

### v0.7.0-dev.2 diagnostics

Development builds log current motion quality and primitive counts once per minute. See `docs/motion-analytics-engineering.md` for warming-up eligibility, support durations, overlapping labels and observed versus reported vertical rate. This update changes no motion thresholds or persistent data.

## v0.7.0-dev.3 — Motion exploration (local preview)

- Motion panel offers live counts and any-label filtering. Fit aircraft fits the shown subset.
- Optional motion colors with legend/overlap priority, retaining O/D badges, military popup labels and closest glow.
- ETA labels identify stale/unknown position age; baseline calculation unchanged.
- Configurable Tracker aggregate/closest/military entities with sanitized failure diagnostics. Optional sensor failures no longer block route metadata.
- Updated engineering notes document a future coupled descent/approach model and validation prerequisites; modeled arrival is not implemented here.
- No data migration or motion-threshold changes.

Tracker options: `tracker_aircraft_entity`, `tracker_closest_entity`, `tracker_military_entity`. Previous names are defaults; enter exact suffixed sensor IDs if needed, save and restart. `/tracker-enrichment` exposes selected entities and safe failure details.

Motion controls affect only map display and reset on reload to All aircraft with colors off.


## v0.7.0-dev.5 diagnostic preview

Enable **Verbose diagnostic logging** in App Configuration, save and restart for bounded motion rejection summaries and density timing breakdowns. The toggle defaults off and is retained in settings backups. Aircraft icons use 24 px below zoom 6 and 36 px from zoom 6 upward. Motion color/filter help is on the status page. See [diagnostic testing](../docs/v0.7.0-dev.5-testing.md).


## v0.7.0-dev.6 SQL diagnostics

With verbose logging enabled, uncached density queries report SQLite query plans, page/cache settings, approximate VM work and executing-thread CPU time. `bypass_cache=1` forces recomputation for diagnostic comparisons. The plan does not run a second density scan. Missing-coordinate motion rejections are expected for aircraft without positions; the existing `invalid` counter remains for compatibility. See ../docs/v0.7.0-dev.6-testing.md.


## v0.7.0-dev.7 density SQL preview

Viewport density queries now select spatial cells before reading daily records and group numeric coordinates instead of parsing text cell IDs. Existing observations, histories and schemas remain unchanged. Keep verbose logging enabled to compare the new query plan and uncached timings. See ../docs/v0.7.0-dev.7-testing.md.


## v0.7.0-dev.8 density preview

Daily parent totals accelerate broad views while retaining fine observations. **Load density** reuses two-hour cached tiles; **Refresh now** rebuilds the visible view. The map displays an As of time. Restore/clear invalidate caches. The first view can backfill parent totals and increase database storage; progress appears in logs. Full JSON backups remain fine-resolution. See ../docs/v0.7.0-dev.8-testing.md.
