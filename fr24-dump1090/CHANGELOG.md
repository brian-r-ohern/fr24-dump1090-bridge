# Changelog

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
