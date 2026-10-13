# Bundled airport reference data

The lookup is generated from [datasets/airport-codes](https://github.com/datasets/airport-codes), derived from [OurAirports](https://ourairports.com/data/). The repository describes nightly updates; the bundled snapshot was updated October 12, 2026 at 04:15:06 UTC. The data package declares **ODC-PDDL-1.0**, not CC0. The Bridge code remains Apache-2.0.

See `provenance.json` for the pinned commit, source URL, hashes and conversion details, and `LICENSE` for the dataset license declaration and reference. The older williamkapke/mwgg JSON is not included.

To regenerate, download the pinned CSV in `provenance.json`, verify its SHA-256, then run from the repository root:

```sh
python3 tools/build_airport_lookup.py airport-codes.csv fr24-dump1090/airports.json
```

The converter retains 72,662 non-closed records with valid coordinates. CSV coordinates are latitude, longitude. The server accepts exact identifiers and unambiguous IATA, database-ident and GPS aliases; ambiguous identifiers return no match. It never guesses a country prefix. The `icao` field is the preferred lookup identifier and can be a GPS/database identifier where no ICAO code exists.

Coordinates represent airport reference locations, not runway thresholds or route waypoints. Bundled updates occur when a new snapshot is prepared; the App does not fetch reference data from the Internet at runtime.

Dev.11 retains validated `elevation_ft` and airport type for experimental arrival scenarios. Unknown/invalid elevation stays absent; airport elevation is not silently assumed to be zero. Reference coordinates are airport centers, not touchdown points.
