# FR24 dump1090 Bridge for Home Assistant

A Home Assistant App that converts already-decoded aircraft data exposed locally by a Flightradar24 receiver into conservative dump1090/readsb-compatible `aircraft.json` endpoints.

The recommended/default input is the receiver's **SBS/BaseStation TCP feed on port 30003**. The receiver's authenticated `/flights.js` web feed remains available as an alternate source. The bridge does **not** decode ADS-B RF data, does not replace the FR24 receiver, and does not interact with or modify the receiver's normal FR24 uplink.

## Home Assistant installation

1. In Home Assistant, open **Settings → Apps → Install app**.
2. Open the repository menu and add: `https://github.com/brian-r-ohern/fr24-dump1090-bridge`
3. Refresh/reload the App Store if necessary.
4. Install **FR24 dump1090 Bridge**.
5. Enter the FR24 receiver host. Leave **SBS/BaseStation (`sbs_30003`)** selected for the recommended configuration.
6. Start the app and enable **Start on boot** after confirming operation.

For the alternate `flights_js` source, also configure the receiver HTTP port, username, and password.

The app currently supports `amd64` Home Assistant systems.

## Input sources

### SBS/BaseStation — recommended/default

The bridge connects continuously to the receiver's local TCP port `30003`. SBS messages update an in-memory state table keyed by ICAO address. The input stream is consumed at full rate; it is not throttled.

Once per second the bridge publishes a consolidated snapshot with one record per active aircraft. Different SBS messages can therefore contribute callsign, position, altitude, speed, track, vertical rate, squawk, and on-ground state to the same aircraft record.

### flights.js — alternate

The original v0.1.x path remains available. It polls the receiver's authenticated `/flights.js` endpoint and conservatively translates the aircraft-state snapshot.

Source selection is explicit. v0.2.0 does not automatically fail over between SBS and flights.js.

## Endpoints

- `/aircraft.json` — dump1090-style aircraft feed
- `/data/aircraft.json` — readsb/dump1090-compatible alias
- `/status` — detailed bridge/feed status
- `/health` — bridge process health
- `/` — human-readable status page

The service listens on container port `8085`. It is not exposed to the LAN by default. A host port can be assigned in the app's Network settings when an external client needs access.

The human-readable status page is also available through Home Assistant Ingress. Use **Open Web UI** on the app Info page, or enable **Show in sidebar**, without exposing port `8085` to the LAN.

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

The bridge avoids inventing information not supported by the selected receiver source. Aircraft without a position are retained and `alt_geom` is not synthesized.

SBS mode provides genuine message-age information: `seen` is the age of the aircraft's latest SBS message and `seen_pos` is the age of its latest position. Top-level `messages` is the cumulative number of valid SBS `MSG` records received since startup. Aircraft are removed after 60 seconds without an SBS message.

In flights.js mode, the original conservative behavior remains: ambiguous zero altitude/speed values are omitted, zero altitude is not automatically treated as on-ground, `seen: 0` is synthetic, and top-level `messages` is the number of aircraft in the current snapshot.

Consumers performing geographic functions such as closest/nearest-aircraft calculations should ignore aircraft without a usable position.

## Status and failure behavior

Feed state is reported independently of process health so an upstream receiver outage does not cause a Home Assistant restart loop. `/status` adapts to the selected source: SBS mode reports message/connection statistics; flights.js mode reports polling statistics. `/health` reports the health of the bridge service itself.

## Security

SBS mode requires no receiver credentials. When flights.js mode is selected, receiver credentials are stored in Home Assistant App configuration and used only for HTTP Digest authentication to the configured local receiver. The bridge does not return credentials from its status endpoints or intentionally log them.

The aircraft feed is unauthenticated. Keep port 8085 internal unless LAN access is actually required.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Known consumers and integrations

FR24 dump1090 Bridge publishes dump1090/readsb-compatible aircraft JSON
intended for use by local applications that consume `aircraft.json`.

The following applications have been used with the bridge:

- **ADSB Aircraft Tracker for Home Assistant**  
  https://github.com/hook-365/adsb-aircraft-tracker

  A Home Assistant integration for monitoring aircraft from a
  dump1090/readsb-compatible data source. Its documentation includes
  configuration guidance specifically for FR24 dump1090 Bridge.

- **ADS-B SkyVista for Home Assistant**  
  https://github.com/aplittlecub/ADS-B-SkyVista

  A Home Assistant aircraft visualization/integration that can consume
  dump1090-compatible aircraft data.

These are independent projects. They are not included with, maintained by,
or affiliated with FR24 dump1090 Bridge.
