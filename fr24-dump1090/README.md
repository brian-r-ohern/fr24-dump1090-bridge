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

Process health and aircraft-source health are intentionally separate. A temporary loss of the selected aircraft source does not by itself mean that the bridge process has failed.

See the app Documentation tab for detailed configuration, source behavior, Home Assistant integration, security, and compatibility information.

## Maximum observed range coverage

The Raw ADS-B Map learns a persistent receiver-coverage outline from the selected bridge aircraft source. Positioned aircraft are measured from Home Assistant `zone.home` and assigned to 360 one-degree bearing bins. Each bin retains only its farthest observed aircraft. The map connects successive populated bins, including across currently empty bearings, without storing synthetic observations. Coverage is saved under `/data` and continues learning across app and HAOS restarts.

