# FR24 dump1090 Bridge — Home Assistant

## Configuration

The bridge supports three mutually exclusive aircraft input sources. Exactly one source is selected at startup.

- **SBS/BaseStation (`sbs_30003`) — recommended/default for FR24 receivers.** Connects to the receiver's local TCP BaseStation feed, normally on port `30003`. Only the receiver host is required for this mode.
- **FR24 web feed (`flights_js`) — alternate.** Polls the receiver's authenticated `/flights.js` endpoint. This mode requires the receiver HTTP port, username, and password.
- **dump1090/readsb JSON (`aircraft_json`) — alternate.** Polls a configured HTTP or HTTPS `aircraft.json` URL. The bridge validates the standard top-level aircraft array, normalizes ICAO `hex` values, preserves supplied aircraft fields, and republishes the selected source through the bridge endpoints.

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

v0.5.0 can use the Home Assistant entities provided by **ADSB Aircraft Tracker** to enrich the Raw ADS-B Map. Tracker remains optional and is not an aircraft input source. The bridge matches Tracker information to currently mapped aircraft by ICAO `hex` only.

When Tracker data is available, military aircraft are shown in green and Tracker's current closest aircraft receives a red halo. An optional **Origin/destination airport highlight** setting accepts an IATA airport code and marks aircraft with **O** when Tracker `route_origin` matches or **D** when `route_destination` matches. Tracker metadata also enriches aircraft popups when available. These states can overlap on the same aircraft. The map uses reported track when available and derives course over ground from successive positions as a fallback for stale/missing orientation.

Tracker enrichment is presentation-only. It does not modify `/aircraft.json` or `/data/aircraft.json`, does not merge aircraft sources, and does not duplicate Tracker's military or route logic. If Tracker is not installed, its entities are unavailable, or enrichment cannot be read, the map retains the v0.4.0 appearance and behavior.

## Home marker

v0.4.0 requests `zone.home` from Home Assistant through the supported Supervisor/Core API proxy enabled by `homeassistant_api: true`. When latitude and longitude are available, the Raw ADS-B Map displays a Home marker and the zone radius. The coordinates are used only by the map presentation path and are not added to `/status`, `/aircraft.json`, logs, or tile diagnostics. If `zone.home` cannot be read, aircraft mapping continues normally without a Home marker.

## Internal Home Assistant access

Home Assistant generates an app's internal DNS name as `{REPO}_{SLUG}`, with underscores changed to hyphens for use as a hostname. A local development installation therefore uses a name such as `local-fr24-dump1090`.

A GitHub repository installation uses a repository identifier generated by Home Assistant, so its hostname will **not** retain the `local-` prefix. Do not copy the development hostname into a production configuration without checking the installed app's actual network identity.

Consumers can use `/aircraft.json` or `/data/aircraft.json` as required.

## Home Assistant web UI (Ingress)

The app supports Home Assistant Ingress for the **Raw ADS-B Map**, which is the default web interface in v0.5.0. Use **Open Web UI** from the app Info page to open the map through Home Assistant without publishing port `8085` to the LAN.

If desired, enable **Show in sidebar** on the app Info page for direct access from the Home Assistant sidebar. The detailed human-readable status page is available from the map or at `/status-page`. Integrations such as ADSB Aircraft Tracker can continue to use the app's internal hostname and port `8085`.

## Optional LAN access

The app declares container port 8085 with no host mapping by default. If a client outside Home Assistant needs the feed, assign a host port in the app's **Network** settings, then configure the consumer to use the Home Assistant host address and that port.

## Status endpoints

`/status` reports bridge uptime, selected input source, receiver/feed state, aircraft totals, and source-specific statistics. SBS mode reports message rate/count, last-message age, parse errors, and connection/reconnection counts. flights.js and aircraft.json modes report poll timing and success/failure counts. aircraft.json mode also reports upstream message count/rate when the source supplies a cumulative numeric `messages` value.

`/health` intentionally reports process/service health rather than upstream FR24 receiver health.

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
attributes. Failure to obtain `zone.home` does not affect aircraft processing.

If another Home Assistant integration cannot reach the bridge, verify the
installed app's internal hostname and use port `8085`. The hostname assigned
to a GitHub-installed app differs from the `local-` hostname used for local
development installations.

## Maximum observed range coverage

The Raw ADS-B Map learns a persistent receiver-coverage outline from the selected bridge aircraft source. Positioned aircraft are measured from Home Assistant `zone.home` and assigned to 360 one-degree bearing bins. Each bin retains only its farthest observed aircraft. The map connects successive populated bins, including across currently empty bearings, without storing synthetic observations. Coverage is saved under `/data` and continues learning across app and HAOS restarts.



## Maximum observed range coverage

The Raw ADS-B Map maintains 360 persistent 1-degree bearing bins under `/data/range-coverage.json`. Distance is the sole record-selection metric: a bin is replaced only when a farther positioned aircraft is observed. Altitude, aircraft identity, callsign, position, and timestamps are metadata for the winning distance observation. Empty bins are not populated by interpolation; the map only connects populated vertices for display.

The `/range-coverage` diagnostic endpoint includes convergence metadata: collection start, total updates, first fills, record replacements, last update, hourly update counts, and each bin's first-observed time and update count. Existing v0.5.1 coverage files are migrated without resetting learned ranges.

### Coverage backup and restore

The status page provides **Export coverage JSON** and **Import / merge coverage** controls. Export saves the current `/range-coverage` payload before an uninstall/reinstall. Import posts that JSON to `/range-coverage/import`, validates the 1-degree bin data, and merges it with the current history by bearing. The farther `distance_nm` wins, so importing an older backup cannot replace a newer maximum. The merged result is flushed immediately to `/data/range-coverage.json`.

