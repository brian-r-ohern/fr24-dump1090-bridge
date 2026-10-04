# FR24 dump1090 Bridge for Home Assistant
<img width="256" height="256" alt="Concept1" src="https://github.com/user-attachments/assets/b0ca6d94-d950-4c36-82c2-39d909fb79ba" />

FR24 dump1090 Bridge functions as a lightweight, non-invasive local aircraft-data layer for Home Assistant:
- 🗺️ Live Visualization: Displays aircraft on an interactive, real-time map with live statistics.
- ⚙️ Normalization: Accepts one explicitly selected source and publishes consistent dump1090/readsb-compatible aircraft.json endpoints.
- 🔒 Zero Interference: It does not alter an FR24 receiver's normal upstream feed, replace receiver hardware, or attempt to decode raw ADS-B RF signals.
If you're looking for a lightweight way to visualize and expose local aircraft data inside Home Assistant, check out the repository.

The recommended/default input is a receiver's SBS/BaseStation TCP feed on port 30003. An authenticated FR24 /flights.js feed or an existing dump1090/readsb aircraft.json feed can be selected as mutually exclusive alternatives. An FR24 receiver is therefore not required when a compatible aircraft.json source is already available.

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

## Raw ADS-B Map
<img width="1024" height="552" alt="image" src="https://github.com/user-attachments/assets/19d7cfd2-adfd-426d-a9b1-c0947be7b559" />

## Input sources

### SBS/BaseStation — recommended/default

The bridge connects continuously to the receiver's local TCP port `30003`. SBS messages update an in-memory state table keyed by ICAO address. The input stream is consumed at full rate; it is not throttled.

Once per second the bridge publishes a consolidated snapshot with one record per active aircraft. Different SBS messages can therefore contribute callsign, position, altitude, speed, track, vertical rate, squawk, and on-ground state to the same aircraft record.

### flights.js — alternate

The original v0.1.x path remains available. It polls the receiver's authenticated `/flights.js` endpoint and conservatively translates the aircraft-state snapshot.

### dump1090/readsb aircraft.json — alternate

The bridge can poll a standard dump1090/readsb `aircraft.json` URL, normalize the snapshot, and publish it through the same bridge endpoints and Raw ADS-B Map.

Source selection is explicit. The bridge uses exactly one source and does not merge or automatically fail over between sources.

## Home marker

The bridge can read Home Assistant `zone.home` through the supported App/Core API proxy and display it on the Raw ADS-B Map. Home coordinates are not included in `/status`, aircraft JSON, logs, or tile diagnostics. If the entity is unavailable, the map continues without the marker.

## Endpoints
<img width="588" height="509" alt="image" src="https://github.com/user-attachments/assets/2ee5e12f-6e84-4fb2-87c3-10367df07840" />

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
