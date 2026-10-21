> **Before installing an update, press Ctrl+Shift+R to refresh this page.**

# FR24 dump1090 Bridge — Home Assistant App

**Version 0.7.2** — Aircraft motion geometry, local analytical history and proximity analysis.

FR24 dump1090 Bridge displays aircraft from one selected input source in Home Assistant. For non-FAA sources, it also provides normalized dump1090/readsb-compatible aircraft feeds. It does not alter receiver hardware or the receiver’s upstream feed.

## v0.7.2 features

- **Repeated motion geometry:** constant-radius turns, orbit candidates, repeated orbits, course reversals and racetrack/holding-like patterns, with supporting evidence and duration.
- **Local track history:** a rolling hour of sampled observations, selected-aircraft trails and compressed GeoJSON exports for selected/all tracks. Selected downloads include the reported ICAO hex, with a local-ID fallback. GeoJSON display has been tested in QGIS.
- **Nearby aircraft:** up to ten neighbors within 10 NM horizontally, ordered by approximate slant range, with horizontal/vertical separation, horizontal closing speed and five-minute constant-velocity CPA/TCPA estimates where supported.
- **Destination movement:** Moving toward / Moving away labels relative to the last reported destination; sustained movement-away evidence is suppressed during established racetrack/repeated-orbit geometry. Destination metadata age is explicitly unknown.
- **Usability and recovery:** expanded popup sections persist through updates, map controls collapse, source changes reload the map, and SBS byte-idle/status-only sessions reconnect.
- **Touchdown estimates:** experimental modeled touchdown scenarios can respond to sustained observed descent.

Motion and prediction thresholds remain experimental. Observations do not establish flight intent, a confirmed diversion, or unsafe separation. Go-around detection, formation analysis and richer composite sequences remain future work. Analytical history is transient and clears on restart. Deliberate local FAA analytical downloads are supported; automatic FAA aircraft-feed bridging remains disabled.


## Supported sources

- **SBS/BaseStation TCP (`sbs_30003`)** — Recommended; typically receiver port `30003`.
- **FR24 `flights.js` (`flights_js`)** — Authenticated receiver snapshot polling.
- **dump1090/readsb (`aircraft_json`)** — Polls a configured compatible aircraft feed.
- **FAA SWIM TFMS (`swim_tfms`)** — Authorized, geographically filtered, local-only map view.
- **FAA SWIM SFDPS (`swim_sfdps`)** — Authorized FIXM surveillance, local-only map, density and motion analysis.

**FAA SWIM behavior:** Selecting TFMS or SFDPS disables automatic downstream aircraft-feed bridging. Deliberate density, envelope and aircraft-history downloads, plus selected trails, are available for personal retention and non-operational analysis. Applicable service terms and LADD protections remain the user’s responsibility; upstream subscriber-level filtering is not assumed.

## What's new in v0.7.1

- SQL aggregation and bounded NumPy batches accelerate envelope generation while retaining base-cell precision.
- Separate **Load envelopes** and **Build envelopes** controls.
- Last successful build persists across restarts, with age and a 12-hour refresh recommendation.
- Failed rebuilds preserve the saved set; density import/clear/pruning invalidate it. Source and Home must match.
- Expanded envelope stage diagnostics under `verbose_logging`.

Build once after upgrading to create the saved set. Existing density history and settings are retained. NumPy is installed by the App image; no user package installation is needed.

## Introduced in v0.7.0

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
