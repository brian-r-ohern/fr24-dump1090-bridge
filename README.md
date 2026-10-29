> **Before installing an update, press Ctrl+Shift+R to refresh this page.**

## v0.7.3 — usability, history and reliability

- Selected aircraft show a reported-destination × and dashed line that persist after popup closure and update with the aircraft until another track is selected.
- Cyan rings highlight projected passes within 3 NM slant range of Home in the next five minutes. A separate purple dashed halo marks fresh aircraft currently within 0.3333 NM horizontally, at any altitude. Both controls are under Motion.
- Qualifying local routes retain up to 24 hours of observed sampled history on disk; other traffic keeps a rolling hour. Both reported airports must be covered, with observations within 10 NM of an endpoint. Export all combines both stores. Collection gaps and late acquisition can leave incomplete trips.
- Configuration groups separate basic setup, personalization, integrations, additional local feeds, FAA SWIM and developer/troubleshooting options. Existing flat settings migrate with compatibility support.
- Expanded popup facets survive SBS and other supported feed updates. Experimental day recording is hidden unless enabled in Developer / troubleshooting.

Home predictions use constant observed velocity and approximate altitude references; they describe geometry, not intent or operational separation. Automatic FAA feed bridging remains disabled.

# FR24 dump1090 Bridge

**Live Tracking and Statistics in Home Assistant**

<img width="256" height="256" alt="Concept1" src="https://github.com/user-attachments/assets/b0ca6d94-d950-4c36-82c2-39d909fb79ba" />
<img width="512" height="386" alt="image" src="https://github.com/user-attachments/assets/a9017ee1-4e33-49e2-9701-d1e119dc3ad3" />

FR24 dump1090 Bridge functions as a lightweight, non-invasive local aircraft-data layer for Home Assistant:

* 🗺️ Live Visualization: Displays aircraft on an interactive, real-time map with live statistics.
* ⚙️ Normalization: Accepts one explicitly selected source and, for non-FAA sources, publishes dump1090/readsb-compatible `aircraft.json` endpoints.
* 🔒 Zero Interference: It does not alter an FR24 receiver's normal upstream feed, replace receiver hardware, or attempt to decode raw ADS-B RF signals.

The recommended/default input is a receiver's SBS/BaseStation TCP feed on port `30003`. An authenticated FR24 `/flights.js` feed or an existing dump1090/readsb `aircraft.json` feed can be selected as mutually exclusive alternatives. An FR24 receiver is therefore not required when a compatible `aircraft.json` source is already available. Authorized FAA SWIM TFMS and SFDPS are local-view-only alternatives; automatic FAA aircraft-feed routes remain disabled, while deliberate local analytical downloads are supported.

## New in v0.7.2
<img width="1535" height="180" alt="image" src="https://github.com/user-attachments/assets/e55170d6-77da-4574-b7d0-cd5fa6349783" />

* **Repeated motion geometry:** constant-radius turns, orbit candidates, repeated orbits, course reversals and racetrack/holding-like patterns, with supporting evidence and duration.
* **Local track history:** a rolling hour of sampled observations, selected-aircraft trails and compressed GeoJSON exports for selected/all tracks. Selected downloads include the reported ICAO hex, with a local-ID fallback. GeoJSON display has been tested in QGIS.
* **Nearby aircraft:** up to ten neighbors within 10 NM horizontally, ordered by approximate slant range, with horizontal/vertical separation, horizontal closing speed and five-minute constant-velocity CPA/TCPA estimates where supported.
* **Destination movement:** Moving toward / Moving away labels relative to the last reported destination; sustained movement-away evidence is suppressed during established racetrack/repeated-orbit geometry. Destination metadata age is explicitly unknown.
* **Usability and recovery:** expanded popup sections persist through updates, map controls collapse, source changes reload the map, and SBS byte-idle/status-only sessions reconnect.
* **Touchdown estimates:** experimental modeled touchdown scenarios can respond to sustained observed descent.

Motion and prediction thresholds remain experimental. Observations do not establish flight intent, a confirmed diversion, or unsafe separation. Go-around detection, formation analysis and richer composite sequences remain future work. Analytical history is transient and clears on restart. Deliberate local FAA analytical downloads are supported; automatic FAA aircraft-feed bridging remains disabled.


## Home Assistant installation

1. In Home Assistant, open **Settings → Apps → Install app**.
2. Open the three-dot menu in the upper-right, select Repositories, and add: https://github.com/brian-r-ohern/fr24-dump1090-bridge
3. Refresh/reload the App Store if necessary.
4. Install **FR24 dump1090 Bridge**.
5. Choose exactly one aircraft source. Enable **Show unused optional configuration options** to enter the source-specific connection settings.
6. For the recommended/default configuration, leave **SBS/BaseStation (`sbs\_30003`)** selected and enter the FR24 receiver host.
7. Start the app and enable **Start on boot** after confirming operation.

For the alternate `flights\_js` source, configure the receiver host, HTTP port, username, and password. For `aircraft\_json`, configure the full URL of the dump1090/readsb-compatible feed.

The app currently supports `amd64` Home Assistant systems and VMs.

For authorized FAA SWIM TFMS or SFDPS, enter the subscription connection details described under [Input sources](#faa-swim-tfms).

## Home Assistant App

<img width="1189" height="773" alt="image" src="https://github.com/user-attachments/assets/404b8c9d-86fe-419a-b04b-aa3e0edb04a0" />

## Input sources

Source selection is explicit. The bridge uses exactly one of the five supported sources and does not merge or automatically fail over between sources.

### SBS/BaseStation — recommended/default

The bridge connects continuously to the receiver's local TCP port `30003`. SBS messages update an in-memory state table keyed by ICAO address. The input stream is consumed at full rate; it is not throttled.

Once per second the bridge publishes a consolidated snapshot with one record per active aircraft. Different SBS messages can therefore contribute callsign, position, altitude, speed, track, vertical rate, squawk, and on-ground state to the same aircraft record.

### flights.js — alternate

The original v0.1.x path remains available. It polls the receiver's authenticated `/flights.js` endpoint and conservatively translates the aircraft-state snapshot.  The FR24 flights.js source reports coordinates to two decimal places, compared with five in the SBS and dump1090/readsb feeds. This makes the coordinate increments 1,000 times coarser: approximately 1.1 km versus 1.1 m in latitude. Longitude increments vary with latitude. These figures describe coordinate resolution, not guaranteed position accuracy.

### dump1090/readsb aircraft.json — alternate

The bridge can poll a standard dump1090/readsb `aircraft.json` URL, normalize the snapshot, and publish it through the same bridge endpoints and Raw ADS-B Map.



### FAA SWIM TFMS

The **Traffic Flow Management System (TFMS)** is an FAA platform used to monitor, manage, and balance air traffic flow across the United States National Airspace System (NAS).

FR24 dump1090 Bridge supports the **TFMData XML flight-data feed**, which combines correlated flight information from NAS sources and international participants. The feed includes scheduling, routing, and aircraft position information. The bridge processes `trackInformation` messages to display aircraft positions and available flight metadata.

Users with an authorized FAA SWIM subscription will need the connection details provided on their subscription’s feed status page: the broker connection URL, message VPN, username, password, and queue name. Copy the complete JMS Connection URL, including `tcps://` and the port, into **SWIM broker host**. Enter the remaining values in the bridge’s SWIM configuration. Connection Factory is not required.

<img width="1024" height="623" alt="image" src="https://github.com/user-attachments/assets/00682b22-c111-4b69-8e92-45b6d0fdcff3" />

FAA SWIM TFMS support was introduced in v0.5.3. The App uses user-supplied SWIM connection/subscription information, filters TFMS `trackInformation` geographically around Home Assistant Home, and displays accepted tracks only in the local map; FAA tracks are not available through normalized aircraft-feed endpoints; deliberate aircraft-history downloads are available for local analysis. SWIM credentials, queue identifiers, and Home coordinates are not exposed through bridge diagnostics.

### TFMS airport matching and map display

When using TFMS, enter the full four-letter airport identifier in `destination\_airport`, matching the feed (for example, `KSYR` rather than `SYR`). For most airports in the contiguous United States, this means adding `K` to the three-letter code. Alaska and Hawaii use different prefixes; use the actual identifier rather than automatically adding `K`. Origin (O) and destination (D) badges compare this setting directly with TFMS departure and arrival airport codes, ignoring case.

The observed coverage outline is hidden for TFMS because its boundary reflects the configured geographic filter rather than radio reception. Numeric track/course remains visible with a 16-point compass label, such as `274.4° (W)`; calculated course retains its `(course)` label.

For optional track history, see [Developer-only track history](#developer-only-track-history).

### FAA SWIM SFDPS

SFDPS is a fifth, mutually exclusive source for authorized FAA SWIM subscribers. It displays FIXM surveillance tracks in the local map, with source-specific density and motion analytics. As with TFMS, automatic aircraft-feed endpoints remain disabled; deliberate local analytical density and history downloads are available. See [App documentation](fr24-dump1090/DOCS.md) for setup and limitations.

## Raw ADS-B Map with density and range ring

<img width="1024" height="610" alt="Screenshot 2026-10-13 070000" src="https://github.com/user-attachments/assets/0acd441f-405a-4428-b862-ce1a9fc9ce47" />

The service listens on container port `8085`. It is not exposed to the LAN by default. A host port can be assigned in the app's Network settings when an external client needs access.

The **Raw ADS-B Map** is available through Home Assistant Ingress. Use **Open Web UI** on the app Info page, or enable **Show in sidebar**, without exposing port `8085` to the LAN. The detailed human-readable status page is available from the map or directly at `/status-page`.

The Raw ADS-B Map also uses a responsive header that adapts to narrow mobile displays while preserving the full desktop layout.

## Home marker

The bridge can read Home Assistant `zone.home` through the supported App/Core API proxy and display it on the Raw ADS-B Map. Home coordinates are not included in `/status`, aircraft JSON, logs, or tile diagnostics. Home also supports range and density-envelope calculations and the TFMS geographic filter. Without Home, ADS-B feeds and density collection continue; TFMS needs Home for filtering.

## Range and density

The map provides maximum observed range, density heat maps, source-separated histories, backups, and cached density views. See [operating details](fr24-dump1090/DOCS.md#maximum-observed-range-coverage) for resolution, restore, and query behavior.

## Backup and recovery

Coverage is stored in the App's persistent /data storage. It is preserved across App upgrades, but not if the App is uninstalled and reinstalled or rebuilt. Coverage can be exported as JSON or GeoJSON; JSON exports can be restored using the import/merge function, which retains the farther observation for each bearing sector. Export the coverage JSON before uninstalling, reinstalling, or rebuilding the App, then import it afterward to restore the accumulated coverage.

Settings snapshots are retained in the app’s dedicated `/config` folder for recovery after reinstall. To preserve this folder when uninstalling, leave **Also delete the app's configuration folder (if used)** unchecked. This preserves the configuration folder; coverage and density data in `/data` still require their own backups before uninstalling and reinstalling.

## Known consumer integrations

FR24 dump1090 Bridge publishes dump1090/readsb-compatible aircraft JSON intended for use by local applications that consume `aircraft.json`.

The following applications have been used with the bridge:

* **ADSB Aircraft Tracker for Home Assistant**
https://github.com/hook-365/adsb-aircraft-tracker

  A Home Assistant integration for monitoring aircraft from a dump1090/readsb-compatible data source. Its documentation includes configuration guidance specifically for FR24 dump1090 Bridge.

* **ADSB Sky Vista**
https://github.com/aplittlecub/ADS-B-SkyVista

  A Home Assistant application for aircraft display and enrichment.

Those are independent projects. They are not included with, maintained by, or affiliated with FR24 dump1090 Bridge.

## Using it with ADSB Aircraft Tracker

The bridge is intended to work as a source for consumers that accept dump1090/readsb-style `aircraft.json`, including the Home Assistant ADSB Aircraft Tracker integration. When the default `adsb\_tracker` enrichment source is selected, the app uses enriched aircraft metadata provided by ADSB Aircraft Tracker.

### Finding the Home Assistant App hostname

When another Home Assistant integration, such as those listed above, needs to connect to the bridge, use the **Hostname** shown on the FR24 dump1090 Bridge **Info** page together with port `8085`.

Open **Settings → Apps → FR24 dump1090 Bridge → Info**. The hostname appears under **Controls → Hostname**.

The hostname shown below is an example. Your installation may use a different hostname.

!\[FR24 dump1090 Bridge hostname in Home Assistant](docs/images/home-assistant-app-hostname.png)

Configure the consuming integration with:

* **Host:** the hostname shown by Home Assistant
* **Port:** `8085`

For consumers that require a complete URL, the dump1090/readsb-compatible aircraft endpoint is `/data/aircraft.json`.

### Optional aircraft enrichment

Aircraft enrichment with routes, icons, flight numbers, airlines, military aircraft flagging, and other metadata can be selected with an `enrichment\_source`. The default `adsb\_tracker` preserves existing behavior; set it to `none` to disable ADSB Aircraft Tracker enrichment without changing the selected aircraft data source.

## API and diagnostics

For non-FAA sources, compatible aircraft feeds are available at `/aircraft.json` and `/data/aircraft.json`. The local map, `/status`, `/health`, density diagnostics, and configuration tools are described in the [endpoint reference](fr24-dump1090/DOCS.md#http-endpoint-reference). FAA aircraft-feed routes remain disabled; deliberate local analytical downloads are available.

## Security

SBS mode requires no receiver credentials. When flights.js mode is selected, receiver credentials are stored in Home Assistant App configuration and used only for HTTP Digest authentication to the configured local receiver. The bridge does not return credentials from its status endpoints or intentionally log them.

The aircraft.json source requires only the configured feed URL.

Home Assistant `zone.home` coordinates are used for the Home marker, range and density-envelope calculations, and TFMS geographic filtering and are not included in aircraft feeds, status output, application logs, or tile diagnostics.

For non-FAA sources, the aircraft feed is unauthenticated. Keep port 8085 internal unless LAN access is actually required. **FAA automatic aircraft-feed bridging remains disabled. Deliberate aircraft-history downloads support personal retention and non-operational analysis; applicable access terms and LADD protections still apply.**

The App runs under a Home Assistant AppArmor profile, tested with all five input modes: SBS/BaseStation TCP, FR24 `flights.js`, dump1090/readsb `aircraft.json`, FAA SWIM TFMS, and FAA SWIM SFDPS.

|Capability|AppArmor access|Verified|
|-|-|-|
|SBS/BaseStation TCP input|IPv4/IPv6 stream networking|✅|
|FR24 `flights.js` input|HTTP + Digest authentication|✅|
|dump1090/readsb `aircraft.json` input|HTTP/HTTPS polling|✅|
|FAA SWIM TFMS / SFDPS input|TLS stream networking to the configured SWIM broker|✅|
|Bridge HTTP service|TCP/8085|✅|
|OpenStreetMap tile proxy|HTTPS networking + `/data` cache|✅|
|Home Assistant `zone.home` lookup|Supervisor/Core API|✅|
|Persistent App data/cache|`/data/\*\*`|✅|
|DNS resolution|IPv4/IPv6 datagram networking|✅|

The App does not require raw sockets, unrestricted host filesystem access, Docker access, `/share`, `/media`, `/ssl`, `/backup`, `mount`, or `ptrace`. The app mounts its dedicated `/config` folder for settings recovery; see [Backup and recovery](#backup-and-recovery).

## Developer-only track history

Track history is a developer-only tool and appears only when `history\_url` is configured. Contact the author for an API description. TFMS requests use callsign; ADS-B requests use ICAO hex. Configure the history service base URL; the bridge appends `/flight` and the appropriate query parameter.

## Roadmap

The FR24 dump1090 Bridge was created to normalize local aircraft tracking data into dump1090/readsb-compatible endpoints. It now also provides a native map, persistent altitude-based traffic density, and empirical range envelopes.

v0.7.1 delivers envelope performance and saved-build improvements. The next planned increment, v0.7.2, focuses on repeated single-aircraft geometry: constant-radius turns/orbits, reversals, racetrack/holding-like patterns and precedence. See the [detailed roadmap](docs/motion-pattern-roadmap.md). Later development will explore motion and spatial analysis, including closest point of approach (CPA), time to closest point of approach (TCPA), and identification of patterns such as holding, converging tracks, and recurring traffic concentrations. These capabilities will depend on the selected feed’s position precision, update cadence, and available metadata.

**Any detected motion patterns and proximity alerts will be informational and intended for observation and analysis.**

## Metadata Dependencies \& Safety Disclaimer

The accuracy of all spatial metrics depends entirely on the selected feed’s position precision, update cadence, latency, and underlying metadata quality. All detected motion patterns, tracking metrics, and proximity alerts are purely informational and intended strictly for observation, telemetry research, and analysis. This utility is not a flight safety tool and must never be used for real-world conflict resolution or active air traffic separation.

## Change log

https://github.com/brian-r-ohern/fr24-dump1090-bridge/blob/main/fr24-dump1090/CHANGELOG.md

## License

Apache License 2.0. See [LICENSE](LICENSE).

