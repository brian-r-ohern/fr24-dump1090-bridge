# Changelog

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
- Increment 4: preserve an accurate origin-only web Referer through Home Assistant Ingress for upstream map-tile requests.
- Increment 4: reject `X-Blocked` or non-PNG upstream tile responses and never write them to the tile cache.
- Increment 4: start with a fresh versioned tile cache so blocked images cached by the Increment 3 test are not reused.


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
