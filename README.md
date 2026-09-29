# FR24 dump1090 Bridge for Home Assistant

A Home Assistant App that converts the already-decoded aircraft data exposed by a local Flightradar24 receiver into conservative dump1090/readsb-compatible `aircraft.json` endpoints.

The bridge does **not** decode ADS-B RF data and does not replace the FR24 receiver. It polls the receiver's authenticated `/flights.js` endpoint and republishes the supported aircraft fields in a form that dump1090/readsb consumers can use.

## Home Assistant installation

1. In Home Assistant, open **Settings → Apps → Install app**.
2. Open the repository menu and add:
   `https://github.com/brian-r-ohern/fr24-dump1090-bridge`
3. Refresh/reload the App Store if necessary.
4. Install **FR24 dump1090 Bridge**.
5. Configure the FR24 receiver host, port, username, and password.
6. Start the app and enable **Start on boot** after confirming operation.

The app currently supports `amd64` Home Assistant systems.

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

Home Assistant generates the internal app hostname from the repository identifier and app slug. 

### Finding the Home Assistant App hostname

When another Home Assistant integration needs to connect to the bridge, use the
**Hostname** shown on the FR24 dump1090 Bridge **Info** page together with port
`8085`.

Open **Settings → Apps → FR24 dump1090 Bridge → Info**. The hostname appears
under **Controls → Hostname**.

The hostname shown below is an example. Your installation may use a different
hostname.

![FR24 dump1090 Bridge hostname in Home Assistant](docs/images/home-assistant-app-hostname.png)

Configure the consuming integration with:

- **Host:** the hostname shown by Home Assistant
- **Port:** `8085`

For consumers that require a complete URL, the dump1090/readsb-compatible
aircraft endpoint is `/data/aircraft.json`.

## Mapping philosophy

The bridge deliberately avoids inventing information that is not present in FR24 `/flights.js`:

- Aircraft without a position are retained.
- Latitude/longitude are emitted only when present.
- Ambiguous zero altitude and speed values are omitted.
- A zero altitude is not automatically converted to an on-ground state.
- `alt_geom` is not synthesized from the single altitude supplied by FR24.
- `seen: 0` is synthetic because `/flights.js` does not provide equivalent message-age semantics.
- Top-level `messages` is the number of aircraft in the current snapshot for compatibility; it is not a dump1090 cumulative message counter.

Consumers performing geographic functions such as closest/nearest-aircraft calculations should ignore aircraft without a usable position.

## Status and failure behavior

The last good aircraft snapshot is retained if the FR24 receiver becomes temporarily unavailable. Feed state is reported independently of process health so an upstream receiver outage does not cause a Home Assistant restart loop.

- up to 10 seconds since a successful poll: `ok`
- over 10 through 30 seconds: `degraded`
- over 30 seconds (or no successful connection): `unhealthy`

`/health` reports the health of the bridge service itself.

## Security

FR24 receiver credentials are stored in Home Assistant App configuration and used only for HTTP Digest authentication to the configured local receiver. The bridge does not return credentials from its status endpoints or intentionally log them.

The aircraft feed is unauthenticated. Keep port 8085 internal unless LAN access is actually required.

## License

Apache License 2.0. See [LICENSE](LICENSE).
