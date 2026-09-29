# FR24 dump1090 Bridge

Home Assistant App that polls a local Flightradar24 receiver's authenticated `/flights.js` endpoint and exposes conservative dump1090/readsb-compatible aircraft feeds.

This app does **not** decode ADS-B RF data. It converts already-decoded receiver data.

## Endpoints

- `/aircraft.json`
- `/data/aircraft.json`
- `/status`
- `/health`
- `/` — human-readable status page

The service listens on container port `8085`. LAN publication is disabled by default.

See the app **Documentation** tab and the repository README for installation, mapping, security, and compatibility details.
