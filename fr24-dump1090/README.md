# FR24 dump1090 Bridge — Home Assistant App

**Version 0.7.0** — Stable release, promoted from `v0.7.0-dev.13`.

FR24 dump1090 Bridge displays aircraft from one selected input source in Home Assistant. For non-FAA sources, it also provides normalized dump1090/readsb-compatible aircraft feeds. It does not alter receiver hardware or the receiver’s upstream feed.

## Supported sources

- **SBS/BaseStation TCP (`sbs_30003`)** — Recommended; typically receiver port `30003`.
- **FR24 `flights.js` (`flights_js`)** — Authenticated receiver snapshot polling.
- **dump1090/readsb (`aircraft_json`)** — Polls a configured compatible aircraft feed.
- **FAA SWIM TFMS (`swim_tfms`)** — Authorized, geographically filtered, local-only map view.
- **FAA SWIM SFDPS (`swim_sfdps`)** — Authorized FIXM surveillance, local-only map, density and motion analysis.

**FAA SWIM restriction:** TFMS and SFDPS are for authorized local consumption and analysis only. Selecting either FAA source disables downstream aircraft-feed and general export endpoints. Do not rebroadcast or redistribute FAA SWIM data.

## What's new in v0.7.0

- Destination airport lookup and direct-distance/current-speed ETA; a separately labeled experimental modeled arrival range is available for qualifying aircraft.
- Motion analytics, activity-based map coloring and filtering.
- FAA SFDPS local-view integration.
- Faster traffic density queries, rollups, cached tiles and clearer refresh controls.
- Auto, Light and Dark map themes, selectable immediately in the map toolbar.
- Expanded diagnostics, tests and settings recovery.

## Installation and documentation

Install from the [Home Assistant repository](https://github.com/brian-r-ohern/fr24-dump1090-bridge) and select exactly one input source. SBS/BaseStation is the default. For the dashboard status card, enable **Dashboard integration** in App configuration; follow the [dashboard installation instructions](../dashboard/README.md).

- [Full configuration, operations, API and troubleshooting guide](DOCS.md)
- [Release history](CHANGELOG.md)
- [Main project README](../README.md)
- [Development validation records](../docs/)

Configuration is retained across normal App upgrades. Uninstalling with **Also delete the app's configuration folder (if used)** selected removes retained App configuration.
