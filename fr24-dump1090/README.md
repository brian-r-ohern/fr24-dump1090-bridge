# FR24 dump1090 Bridge

Home Assistant App that converts already-decoded aircraft data from a local Flightradar24 receiver into conservative dump1090/readsb-compatible aircraft feeds.

The recommended/default source is the receiver's SBS/BaseStation TCP feed on port `30003`. The authenticated `/flights.js` web feed remains available as an alternate source. The app does **not** decode ADS-B RF data and does not alter the receiver's normal FR24 uplink.

## Endpoints

- `/aircraft.json`
- `/data/aircraft.json`
- `/status`
- `/health`
- `/` — human-readable status page

The service listens on container port `8085`. LAN publication is disabled by default.

See the app **Documentation** tab and the repository README for installation, source selection, mapping, security, and compatibility details.
