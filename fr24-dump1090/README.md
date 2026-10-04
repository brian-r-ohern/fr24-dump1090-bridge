# FR24 dump1090 Bridge

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

   Connects to the user's authorized FAA SWIM Solace queue, consumes TFMS messages, selects `trackInformation`, and retains positioned tracks inside a configurable radius around Home Assistant Home. The FAA-provided broker host, VPN, subscription username/password, and queue/JMS name are required. Credentials and queue identifiers are not returned by bridge diagnostics or logs. v0.5.3 treats TFMS as a mutually exclusive aircraft source; it does not merge TFMS with ADS-B sources.

## 🗺️ Raw ADS-B Map & Home Assistant Integration

The bridge provides a self-contained **Raw ADS-B Map** through Home Assistant Ingress.

Aircraft positions are displayed directly from the currently selected source. When ADSB Aircraft Tracker is installed, v0.5.0 can optionally use its Home Assistant entities for map-only military, closest-aircraft, and configured origin/destination-airport highlighting and richer aircraft popups. Tracker enrichment never changes the normalized aircraft feed, and the map retains its existing behavior when Tracker data is unavailable.

When available, the map can also obtain the location of Home Assistant's `zone.home` through the Home Assistant API and display it as a Home marker.

Home coordinates are used only for map presentation. They are not added to `/status`, `/aircraft.json`, `/data/aircraft.json`, application logs, or tile-proxy diagnostics.

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
- `/tiles/{z}/{x}/{y}.png` — internal map-tile proxy route used by the map

Process health and aircraft-source health are intentionally separate. A temporary loss of the selected aircraft source does not by itself mean that the bridge process has failed.

See the app Documentation tab for detailed configuration, source behavior, Home Assistant integration, security, and compatibility information.

## Maximum observed range coverage

The Raw ADS-B Map learns a persistent receiver-coverage outline from the selected bridge aircraft source. Positioned aircraft are measured from Home Assistant `zone.home` and assigned to 360 one-degree bearing bins. Each bin retains only its farthest observed aircraft. The map connects successive populated bins, including across currently empty bearings, without storing synthetic observations. Coverage is saved under `/data` and continues learning across app and HAOS restarts.


### Range coverage backup / restore

Before uninstalling/reinstalling the app, use the status page to export the accumulated range-coverage JSON. After reinstall, import the saved JSON; the bridge validates it and merges each bearing bin by keeping the farther observed range. The restore endpoint is `POST /range-coverage/import`. The same status page can export the live coverage as GeoJSON from `/range-coverage.geojson` for GIS tools such as QGIS; the GeoJSON contains a closed maximum-range LineString plus one Point feature per populated bearing bin.


### Optional map enrichment

Map enrichment can be selected with `enrichment_source`. The default `adsb_tracker` preserves existing behavior; set it to `none` to disable ADSB Aircraft Tracker enrichment without changing the selected aircraft data source.

### TFMS airport matching and map display

When using TFMS, enter the full four-letter airport identifier in `destination_airport`, matching the feed (for example, `KSYR` rather than `SYR`). For most airports in the contiguous United States, this means adding `K` to the three-letter code. Alaska and Hawaii use different prefixes; use the actual identifier rather than automatically adding `K`. Origin (O) and destination (D) badges compare this setting directly with TFMS departure and arrival airport codes, ignoring case.

The observed coverage outline is hidden for TFMS because its boundary reflects the configured geographic filter rather than radio reception. Numeric track/course remains visible with a 16-point compass label, such as `274.4° (W)`; calculated course retains its `(course)` label.

TFMS track history accepts a flight callsign (for example, `UCA4250`) and queries `http://192.168.0.1:8756/flight?callsign=uca4250`. ADS-B sources continue to accept a six-digit ICAO hex and use the configured history service.
