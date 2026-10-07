# FR24 dump1090 Bridge for Home Assistant
<img width="256" height="256" alt="Concept1" src="https://github.com/user-attachments/assets/b0ca6d94-d950-4c36-82c2-39d909fb79ba" />

FR24 dump1090 Bridge functions as a lightweight, non-invasive local aircraft-data layer for Home Assistant:
- 🗺️ Live Visualization: Displays aircraft on an interactive, real-time map with live statistics.
- ⚙️ Normalization: Accepts one explicitly selected source and publishes consistent dump1090/readsb-compatible aircraft.json endpoints.
- 🔒 Zero Interference: It does not alter an FR24 receiver's normal upstream feed, replace receiver hardware, or attempt to decode raw ADS-B RF signals.
If you're looking for a lightweight way to visualize and expose local aircraft data inside Home Assistant, check out the repository.

The recommended/default input is a receiver's SBS/BaseStation TCP feed on port 30003. An authenticated FR24 /flights.js feed or an existing dump1090/readsb aircraft.json feed can be selected as mutually exclusive alternatives. An FR24 receiver is therefore not required when a compatible aircraft.json source is already available. Lastly, if you have an FAA SWIM / SWIFT Portal account and a TFMS feed set up, you can use that.

## Home Assistant installation

1. In Home Assistant, open **Settings → Apps → Install app**.
2. Open the three-dot menu in the upper-right, select Repositories, and add: https://github.com/brian-r-ohern/fr24-dump1090-bridge 
3. Refresh/reload the App Store if necessary.
4. Install **FR24 dump1090 Bridge**.
5. Choose exactly one aircraft source. Enable **Show unused optional configuration options** to enter the source-specific connection settings.
6. For the recommended/default configuration, leave **SBS/BaseStation (`sbs_30003`)** selected and enter the FR24 receiver host.
7. Start the app and enable **Start on boot** after confirming operation.

For the alternate `flights_js` source, configure the receiver host, HTTP port, username, and password. For `aircraft_json`, configure the full URL of the dump1090/readsb-compatible feed.

The app currently supports `amd64` Home Assistant systems.

## Home Assistant App
<img width="991" height="857" alt="image" src="https://github.com/user-attachments/assets/a7be378b-2772-4c62-9306-bcb95435872f" />

## Raw ADS-B Map with density and range ring
<img width="1024" height="566" alt="image" src="https://github.com/user-attachments/assets/efe60542-bb0b-41df-a8bf-b38eb26aacf3" />

## Maximum observed range

The Raw ADS-B Map maintains a persistent empirical coverage envelope from positioned aircraft received through the selected aircraft source. For each 0.5° bearing sector, the bridge retains the farthest observed aircraft and displays that maximum across the sector.

The envelope grows as farther observations are received and is intentionally not smoothed, preserving the actual observed maxima and directional variations in reception. The maximum observed distance is also shown in the map status display.

Coverage is stored in the App's persistent /data storage. It is preserved across App upgrades, but not if the App is uninstalled and reinstalled or rebuilt. Coverage can be exported as JSON or GeoJSON; JSON exports can be restored using the import/merge function, which retains the farther observation for each bearing sector. Export the coverage JSON before uninstalling, reinstalling, or rebuilding the App, then import it afterward to restore the accumulated coverage.

## Input sources

### SBS/BaseStation — recommended/default

The bridge connects continuously to the receiver's local TCP port `30003`. SBS messages update an in-memory state table keyed by ICAO address. The input stream is consumed at full rate; it is not throttled.

Once per second the bridge publishes a consolidated snapshot with one record per active aircraft. Different SBS messages can therefore contribute callsign, position, altitude, speed, track, vertical rate, squawk, and on-ground state to the same aircraft record.

### flights.js — alternate

The original v0.1.x path remains available. It polls the receiver's authenticated `/flights.js` endpoint and conservatively translates the aircraft-state snapshot.

### dump1090/readsb aircraft.json — alternate

The bridge can poll a standard dump1090/readsb `aircraft.json` URL, normalize the snapshot, and publish it through the same bridge endpoints and Raw ADS-B Map.

Source selection is explicit. The bridge uses exactly one source and does not merge or automatically fail over between sources.

### FAA SWIM TFMS
The **Traffic Flow Management System (TFMS)** is an FAA platform used to monitor, manage, and balance air traffic flow across the United States National Airspace System (NAS).

The ADSB-d1090_Bridge supports the **TFMData XML flight-data feed**, which combines correlated flight information from NAS sources and international participants. The feed includes scheduling, routing, and aircraft position information. The bridge processes `trackInformation` messages to display aircraft positions and available flight metadata.

Users with an authorized FAA SWIM subscription will need the connection details provided on their subscription’s feed status page: the broker host and port (Copy the complete JMS Connection URL, including tcps:// and the port, into SWIM broker host), message VPN, username, password, and queue name. Enter these values in the bridge’s SWIM configuration. Connection Factory is not required
<img width="1024" height="623" alt="image" src="https://github.com/user-attachments/assets/00682b22-c111-4b69-8e92-45b6d0fdcff3" />

## Home marker

The bridge can read Home Assistant `zone.home` through the supported App/Core API proxy and display it on the Raw ADS-B Map. Home coordinates are not included in `/status`, aircraft JSON, logs, or tile diagnostics. If the entity is unavailable, the map continues without the marker.

## Endpoints
<img width="790" height="382" alt="image" src="https://github.com/user-attachments/assets/15bfde9b-ff48-4152-8510-3d5f071e7419" />

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
- `/tiles/{z}/{x}/{y}.png` — internal map-tile proxy route used by the map

The service listens on container port `8085`. It is not exposed to the LAN by default. A host port can be assigned in the app's Network settings when an external client needs access.

The **Raw ADS-B Map** is available through Home Assistant Ingress. Use **Open Web UI** on the app Info page, or enable **Show in sidebar**, without exposing port `8085` to the LAN. The detailed human-readable status page is available from the map or directly at `/status-page`.

The Raw ADS-B Map also uses a responsive header that adapts to narrow mobile displays while preserving the full desktop layout.

## Using it with ADSB Aircraft Tracker

The bridge is intended to work as a source for consumers that accept dump1090/readsb-style `aircraft.json`, including the Home Assistant ADSB Aircraft Tracker integration.

### Finding the Home Assistant App hostname

When another Home Assistant integration needs to connect to the bridge, use the **Hostname** shown on the FR24 dump1090 Bridge **Info** page together with port `8085`.

Open **Settings → Apps → FR24 dump1090 Bridge → Info**. The hostname appears under **Controls → Hostname**.

The hostname shown below is an example. Your installation may use a different hostname.

![FR24 dump1090 Bridge hostname in Home Assistant](docs/images/home-assistant-app-hostname.png)

Configure the consuming integration with:

- **Host:** the hostname shown by Home Assistant
- **Port:** `8085`

For consumers that require a complete URL, the dump1090/readsb-compatible aircraft endpoint is `/data/aircraft.json`.

## Mapping philosophy

The bridge avoids inventing information not supported by the selected input source. Aircraft without a position are retained and `alt_geom` is not synthesized.

SBS mode provides genuine message-age information: `seen` is the age of the aircraft's latest SBS message and `seen_pos` is the age of its latest position. Top-level `messages` is the cumulative number of valid SBS `MSG` records received since startup. Aircraft are removed after 60 seconds without an SBS message.

In flights.js mode, the original conservative behavior remains: ambiguous zero altitude/speed values are omitted, zero altitude is not automatically treated as on-ground, `seen: 0` is synthetic, and top-level `messages` is the number of aircraft in the current snapshot.

Consumers performing geographic functions such as closest/nearest-aircraft calculations should ignore aircraft without a usable position.

## Status and failure behavior
Feed state is reported independently of process health so an upstream source outage does not cause a Home Assistant restart loop. `/status` adapts to the selected source: SBS mode reports message and connection statistics, while flights.js and aircraft.json modes report polling statistics. `/health` reports the health of the bridge service itself.

## Security

SBS mode requires no receiver credentials. When flights.js mode is selected, receiver credentials are stored in Home Assistant App configuration and used only for HTTP Digest authentication to the configured local receiver. The bridge does not return credentials from its status endpoints or intentionally log them.

The aircraft.json source requires only the configured feed URL.

Home Assistant `zone.home` coordinates are used only for Raw ADS-B Map presentation and are not included in aircraft feeds, status output, application logs, or tile diagnostics.

The aircraft feed is unauthenticated. Keep port 8085 internal unless LAN access is actually required.

The App runs under a Home Assistant AppArmor profile. The profile has been tested with all three supported input modes: SBS/BaseStation TCP, FR24 `flights.js`, and standard dump1090/readsb `aircraft.json`.

| Capability | AppArmor access | Verified |
|---|---|---|
| SBS/BaseStation TCP input | IPv4/IPv6 stream networking | ✅ |
| FR24 `flights.js` input | HTTP + Digest authentication | ✅ |
| dump1090/readsb `aircraft.json` input | HTTP/HTTPS polling | ✅ |
| Bridge HTTP service | TCP/8085 | ✅ |
| OpenStreetMap tile proxy | HTTPS networking + `/data` cache | ✅ |
| Home Assistant `zone.home` lookup | Supervisor/Core API | ✅ |
| Persistent App data/cache | `/data/**` | ✅ |
| DNS resolution | IPv4/IPv6 datagram networking | ✅ |

The App does not require raw sockets, host filesystem access, Docker access, `/config`, `/share`, `/media`, `/ssl`, `/backup`, `mount`, or `ptrace`.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Known consumers and integrations

FR24 dump1090 Bridge publishes dump1090/readsb-compatible aircraft JSON
intended for use by local applications that consume `aircraft.json`.

The following application has been used with the bridge:

- **ADSB Aircraft Tracker for Home Assistant**  
  https://github.com/hook-365/adsb-aircraft-tracker

  A Home Assistant integration for monitoring aircraft from a
  dump1090/readsb-compatible data source. Its documentation includes
  configuration guidance specifically for FR24 dump1090 Bridge.

This is an independent project. It is not included with, maintained by,
or affiliated with FR24 dump1090 Bridge.


### Optional map enrichment

Map enrichment can be selected with `enrichment_source`. The default `adsb_tracker` preserves existing behavior; set it to `none` to disable ADSB Aircraft Tracker enrichment without changing the selected aircraft data source.


## FAA SWIM TFMS (v0.5.3)

Version 0.5.3 adds FAA SWIM TFMS as a fourth explicitly selected aircraft source for authorized SWIM users. The App uses user-supplied SWIM connection/subscription information, filters TFMS `trackInformation` geographically around Home Assistant Home, and republishes accepted tracks through the existing normalized aircraft endpoints and map. SWIM credentials, queue identifiers, and Home coordinates are not exposed through bridge diagnostics.

### TFMS airport matching and map display

When using TFMS, enter the full four-letter airport identifier in `destination_airport`, matching the feed (for example, `KSYR` rather than `SYR`). For most airports in the contiguous United States, this means adding `K` to the three-letter code. Alaska and Hawaii use different prefixes; use the actual identifier rather than automatically adding `K`. Origin (O) and destination (D) badges compare this setting directly with TFMS departure and arrival airport codes, ignoring case.

The observed coverage outline is hidden for TFMS because its boundary reflects the configured geographic filter rather than radio reception. Numeric track/course remains visible with a 16-point compass label, such as `274.4° (W)`; calculated course retains its `(course)` label.

Track history requires a configured `history_url` for every input. TFMS uses callsign (for example, `UCA4250`); ADS-B uses six-digit ICAO hex. See the developer-only tool note below.


## Developer-only track history

Track history is a developer-only tool and appears only when `history_url` is configured. Contact the author for an API description. TFMS requests use callsign; ADS-B requests use ICAO hex. Configure the history service base URL; the bridge appends `/flight` and the appropriate query parameter.

## Range-envelope resolution and GeoJSON evolution

The active range envelope uses **0.5° / 720 bins**, retained in v0.6.0. Each bin preserves its empirical maximum and provenance. The original legacy 1° dataset remains available as a baseline. GeoJSON exports ordered maxima and the rendered envelope; empty bins break the boundary, and only complete coverage produces a closed envelope polygon.

### Implemented in v0.5.4

The active envelope now uses 0.5° / 720 bins. On upgrade, the original 1° file is preserved byte-for-byte at `/data/range-coverage.json.1-degree-baseline.json` and embedded as `baseline_1_degree` in the new JSON. **Export 1° baseline** on the status page downloads that reference dataset.

Legacy import and migration seed each 1° maximum into two adjacent 0.5° bins: 12° becomes 12° and 12.5°, and 359° becomes 359° and 359.5°. Both copies retain `legacy_adjacent_seed` provenance and the original bearing/coordinates; they are coarse legacy estimates, not two independently observed maxima. Seeding works without Home. Each bin retains the farther maximum until a farther real observation replaces its seed. Existing 0.5° installations also seed the preserved baseline on restart. Only the old winning maxima survive migration; previously discarded observations cannot be recovered.

GeoJSON now contains ordered empirical Point features and the same stepped envelope coordinates used by the map. Incomplete coverage produces open MultiLineString runs, broken at every empty bin; a Polygon is emitted only when all 720 bins are populated. The derived bin footprint is explicitly labeled and remains distinct from the raw observed positions. The 0.25° experiment and optional wedge features remain future work.


## Traffic Density (v0.6.0)

Traffic Density collects every valid positioned aircraft once per selected-source snapshot, independently of whether the map is open. It stores sparse geographic quadtree cells at approximately **153 × 227 m at 42°N**, with observation/passage counts, Low/Middle/High/Unknown altitude counters, altitude bounds and daily timestamps. No interpolated track positions receive density credit.

Monthly files under `/data/traffic-density` retain the current calendar month plus 17 preceding months. The map has one **Traffic Density** layer, off by default, showing the most recent 30 UTC dates. Display cells aggregate through the hierarchy while storage keeps fine cells. Range coverage remains at **0.5° / 720 bins** and is backed up separately.

The status page provides density JSON backup/restore, a monthly backup selector and recent GeoJSON cell export. Restore chooses whole cell/month snapshots without adding overlapping histories; uncertain starts remain null. v0.6.4 adds altitude filters and density-derived range envelopes for consistency comparison.

See [Traffic Density design, sizing and API](docs/traffic-density-v0.6.0.md) for the measured candidate-grid costs, temporal precision, provenance policy and installation checks. Run `python3 -m unittest discover -s tests -v` for regression tests.


### FAA SWIM/TFMS density limitations

Traffic Density remains available for FAA SWIM/TFMS, but its spatial detail is limited by the position reports supplied by the feed. Report cadence varies by feed and track; observed examples updated approximately once per minute, leaving gaps between occupied cells even along a continuous flight. This is a sampling interval, not a measured minute of delivery latency: a three-image check of one track was consistent with delivery/display delay of only a few seconds, subject to clock and browser timing. These examples do not establish cadence or latency for every TFMS track. An empty cell therefore means no position was observed there; it does not establish that no aircraft passed through it. In the current implementation, observations count aircraft represented in Bridge publication snapshots, not distinct FAA reports: the Bridge republishes retained TFMS positions once per second, so the same reported position can receive multiple observation credits while it remains eligible. Counts consequently reflect both report availability and snapshot retention, and should not be compared directly with ADS-B feeds as independent position-report counts or interpreted as measured time spent in each cell.

The Bridge deliberately does not interpolate between reports or extrapolate beyond the latest report to fill density gaps. Great-circle connections, three-point smoothing and constrained-turn paths can suggest plausible trajectories, but cannot establish which cells an aircraft actually traversed between sparse reports. Filling those cells would turn inferred motion into apparent observations and could introduce false routes or maneuver artifacts, especially during turns, holding patterns or report gaps. Density therefore credits only the reported-position cells represented in eligible snapshots. Any future inferred-track presentation should remain explicitly distinguishable from the observed density dataset.

### TFMS range processing — v0.6.1

Selecting `swim_tfms` disables the range-coverage worker entirely, including coverage-file loading, migration and periodic flushing. Existing ADS-B coverage files are preserved for a later switch back to an ADS-B source. The coverage outline remains hidden for TFMS. Home-marker processing and Traffic Density collection continue; TFMS still needs Home for its geographic filter.


### Responsive map controls — v0.6.2

Bridge status is collapsible: tap/click its heading to open or close it. On narrow or short screens it starts closed. Its expanded contents scroll within the available space. Status and track controls share a wrapping bottom dock, while the top toolbar leaves room for the zoom buttons. Layout updates when the screen rotates or controls change. This also includes v0.6.1's TFMS range-processing exclusion.


For layout regression checks in a development environment with Playwright/Chromium installed, extract `MAP_HTML` into an HTML file and run `node tools/check_map_layout.cjs /path/to/map.html`. The harness uses the real overlay HTML/CSS and layout script with sample status text; it does not replace live Leaflet/phone verification. Python regressions and JavaScript syntax checks passed for v0.6.2; the automated browser check could not run here because the browser download was unavailable.


## v0.6.3 upgrade

Source-specific page titles, density stores and backup names are now available. The Range ring checkbox controls ADS-B display; FAA TFMS continues density collection with range processing disabled. Existing untagged density needs explicit `density_legacy_source` attribution on upgrade. See [upgrade and testing notes](docs/v0.6.3-testing.md) for large-backup behavior and static Home Assistant sidebar labels.


## v0.6.4 — altitude heat maps and consistency envelopes

The default Home Assistant sidebar title is now **Aircraft Bridge**. Map and page titles continue to identify the selected source. Traffic Density stays off by default; enable it and expand **Altitude selection** to choose Low (<1,200 ft), Middle (1,200–17,999 ft), High (≥18,000 ft), or any combination. **All Traffic** includes Unknown and is the initial selection. Selecting a band clears All Traffic; selecting All Traffic clears individual bands. No selection displays no density. Filters select observation counts for coloring without changing stored counters or full JSON backups.

For ADS-B sources, expand **Density envelopes · comparison**, generate the recent 30-day comparison, and toggle the dashed All/Low/Middle/High outlines. All four products share a source, Home position, UTC date window and **0.5° / 720-bin** bearings. The existing red range ring remains authoritative. The status page also offers custom dates and JSON/GeoJSON exports. FAA products can be generated there as **reported traffic extent**, but do not appear as receiver range rings. Generation is on demand and cached for up to five minutes; regenerating after that interval incorporates new observations.

Ranges use observed base-cell centers and are approximate. A notch that diminishes with altitude is consistent with screening, but is not a diagnosis: traffic availability, antenna response, propagation and receiver conditions also affect coverage. Sector exports include selected-band observations, occupied cells, furthest-cell support and combined passages in qualifying cells. Those passage counts are not altitude-specific; existing storage does not retain band-specific passage counters. Unknown altitude contributes only to All Traffic, and assigned FAA altitude is not used as observed altitude.

No database migration is required from v0.6.3. Source-separated history, retention, backups, passage counting and FAA snapshot behavior are unchanged. See [v0.6.4 usage and test notes](docs/v0.6.4-testing.md).

## v0.6.5 — large density display

Density refresh waits for active requests, bounds map geometry through observed parent aggregation, and exposes timing diagnostics. Fine-resolution history and full exports are preserved. See docs/v0.6.5-loading.md for reproduction and verification.

## v0.6.6 — density refresh and data management

Traffic density loads once when enabled. Pan, zoom or change altitude selections, then press **Refresh density** in Altitude selection. The previous layer remains visible while loading. The result shows the actual density grid zoom, cell count and elapsed time. Collection continues at zoom 17 regardless of layer visibility; radial coverage remains 0.5° / 720 bins. Indexed viewport filtering avoids aggregating off-screen history. Small interactive results may reuse an all-band aggregate for up to 30 seconds; full exports always read the stored history.

### Large density restores outside Ingress

If a large restore through Home Assistant Ingress reports **Failed to fetch**, use the Bridge directly on your LAN:

1. Open **Settings → Apps → FR24 dump1090 Bridge → Configuration** (called Add-ons on older Home Assistant versions).
2. Under **Network**, assign an unused host port to the `8085/tcp` service, for example `8085`. Enable **Show disabled ports** if the mapping is hidden. Save and restart the App.
3. In a browser on your LAN, open `http://<Home-Assistant-IP>:<assigned-port>/status-page`, for example `http://192.168.0.100:8085/status-page`. Use the Home Assistant host IP, not the receiver IP or App internal hostname. Each Bridge instance needs a different host port.
4. Select the density JSON backup and press **Restore density JSON**. Leave the page open until the restore completes. Confirm the source matches; explicitly attribute older untagged backups only when their source is known.
5. Open `http://<Home-Assistant-IP>:<assigned-port>/` to inspect density, or return to Open Web UI. You can disable the host port after restoring.

The direct HTTP service has no authentication; expose it only on your trusted LAN. Ingress remains available for normal viewing. A failed browser request does not establish whether the server finished the restore; check collection status and logs before retrying.

### Configuration fields

SWIM VPN and the other optional connection fields now have explicit blank defaults. Enable **Show unused optional configuration options** when reviewing an existing installation whose saved options omit fields. Supply only the settings needed by the selected source. TFMS requires SWIM host, message VPN, username, password and queue. The App validates these at startup; the VPN is the Solace message VPN, not a home-network VPN. The Supervisor owns the configuration form; source selection does not dynamically hide unrelated fields.

### Danger Zone

Below Diagnostics on the status page:

- **Clear current-source traffic density** deletes that source's observations, daily statistics and passage state.
- **Clear range coverage and legacy baseline** resets the 720 bins and deletes the saved 1° baseline.
- **Clear all collected data (all sources)** clears density for every source in this App instance plus range coverage and its baseline.

Export backups first. Individual actions require typing `CLEAR`; the all-data action requires `CLEAR ALL`. Configuration, credentials and other App instances are preserved. Collection resumes from empty datasets. Clear operations are serialized with collection and restore.

## v0.6.7 — Settings recovery and compact controls

The map now places **Density altitude selection** and **Density envelopes · comparison** side by side. Expand either or both independently. On small screens they stack. **Refresh density** sits beside **Fit aircraft** and reloads the heat cells for the current viewport and selected altitude bands. **Generate envelopes** builds the separate density-derived range outlines. Panning, zooming, or changing altitude bands still marks the heat view pending until you refresh it. **Range ring** stays on the main toolbar.

Status-page endpoints have a green border; the three density, envelope, and range export sections have yellow borders. The red Danger Zone follows the complete Diagnostics section, including the tile endpoint description.

### Persistent settings and recovery after reinstall

The App mounts its dedicated host configuration folder read/write at `/config` using `addon_config:rw`. Its slug remains `fr24_dump1090`. For a local installation the host folder is `/addon_configs/local_fr24_dump1090/`; repository installations use the repository identifier instead of `local`. Local and repository installations have separate folders.

At each successful configured startup, the App atomically saves its valid configuration to `/config/bridge-settings.json`, including feed credentials. The file uses owner-only permissions. Settings changes made in Home Assistant are captured when you restart the App. **Settings backup / recovery**, linked from the status page, also provides **Save current settings** and **Restore saved settings**. Treat this snapshot as a credential-bearing backup; keep the direct HTTP interface on a trusted LAN.

To test recovery:

1. Upgrade to v0.6.7 and start it with your working feed configuration. Open **Status → Settings backup / recovery** and confirm a saved snapshot is listed.
2. Export density/range backups before any uninstall test. They remain under `/data` and are not preserved by this settings feature.
3. Uninstall while leaving the option to delete the App configuration folder unchecked. Reinstall the same local or repository App identity and start it. Re-enter optional Network port mappings if using direct LAN access.
4. With blank/incomplete feed settings the App serves a recovery page instead of starting collection. Open the Web UI, select **Restore saved settings**, confirm, then restart the App from Home Assistant. The restore writes the App's options through Supervisor; it does not silently override settings at startup.
5. Verify Configuration and `/status` show your chosen source and the feed reconnects.

Deleting the configuration folder also deletes the retained settings snapshot. Home Assistant Home coordinates, Network port mappings, boot/watchdog preferences, density history and range coverage are outside this settings snapshot. No persistent-data migration is performed. A damaged snapshot is preserved and reported rather than overwritten. Settings recovery needs Supervisor; non-HA standalone runs can read the retained JSON manually.

Implementation references: [public App configuration folder](https://developers.home-assistant.io/blog/2023/11/06/public-addon-config/) and [Supervisor App options](https://developers.home-assistant.io/docs/api/supervisor/endpoints/).

## v0.6.8 — Data-operation logging

App logs now record timestamped starts and outcomes for density/range imports, data exports, envelope generation, and Danger Zone clears. Entries include the selected source and dataset, elapsed seconds, HTTP status, available merge/bin/feature counts, clear target, and input/response byte counts where applicable. Failed requests and disconnected transfers are distinguished from completed responses. Response completion means the server sent the export, not proof that a browser saved it to disk.

Routine heat-map queries retain their existing timing diagnostics. Automatic five-second range polling is excluded from export audit logs; range JSON download links use `?download=1` to identify explicit exports. Direct `/range-coverage` API reads remain polling reads unless that marker is supplied. Logs do not include feed credentials, configuration contents, or URL query strings.

After restoring or clearing data on the status page, reload the map to discard its displayed snapshot. For heat cells, use Refresh density; for an already generated envelope comparison, use Generate envelopes again. Collection continues after a clear, so new observations can begin accumulating immediately.

Settings recovery is unchanged from v0.6.7. Port mappings and Show in sidebar remain outside the settings snapshot. After changing a Network port mapping in Home Assistant, restart the App to apply it.
