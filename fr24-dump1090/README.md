# FR24 dump1090 Bridge

Home Assistant App that normalizes an explicitly selected local aircraft source into conservative dump1090/readsb-compatible aircraft feeds.

The recommended/default source is an FR24 receiver's SBS/BaseStation TCP feed on port `30003`. The authenticated FR24 `/flights.js` web feed and a standard dump1090/readsb `aircraft.json` URL are alternate, mutually exclusive sources. The app does **not** decode ADS-B RF data and does not alter an FR24 receiver's normal uplink. v0.4.0 also displays the Home Assistant `zone.home` location on the Raw ADS-B Map when it is available.

## Endpoints

- `/` — Raw ADS-B Map
- `/aircraft.json`
- `/data/aircraft.json`
- `/status` 
- `/health`
- `/status-page` — human-readable status page

The service listens on container port `8085`. LAN publication is disabled by default.

See the app **Documentation** tab and the repository README for installation, source selection, mapping, security, and compatibility details.
