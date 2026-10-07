# Traffic Density — v0.6.0

v0.6.0 adds an independent persistent observation-density dataset and one map layer, off by default. It preserves the released **0.5° / 720-bin** range-coverage implementation. Existing coverage remains authoritative. Legacy 1° coverage migration remains supported, but is not the current resolution and does not seed density.

## Spatial choice and measured storage

The grid is a global geographic quadtree. Its root covers longitude −180°…180° and latitude −90°…90°. At level `z`, both axes divide into `2^z` cells. IDs are `z/x/y`, with `x` increasing eastward and `y` increasing southward. A parent is `z-1 / floor(x/2) / floor(y/2)`. This includes valid polar positions and has no dependency on receiver Home coordinates.

**Base level 17** is selected: approximately **153 m north–south × 227 m east–west at 42°N**. Width varies with latitude. This fits the approximately 125–250 m fine-resolution objective in the receiver region. Level 16 gives approximately 306 × 454 m display cells there. Level 18 was also measured, giving approximately 76 × 114 m; the quadtree permits future finer storage. Schema version 1 explicitly records its base level; a future finer-grid schema needs a deliberate migration and must not pretend older coarse observations had fine positions.

The checked-in sizing script uses 360,000 positioned observations across 24 synthetic routes, 500 samples per route per day, and 30 days. Route progression is approximately 145 m with small daily offsets, centered near 42°N. It does **not** measure actual reception or interpolate observations into storage. Final measurements are in `traffic-density-storage-estimate.json`.

| Candidate | Cell dimensions at 42°N | Occupied cells/month | Occupied cell/day rows | Monthly SQLite bytes | Bytes/day row | 18 equally sized months |
|---|---:|---:|---:|---:|---:|---:|
| Level 17, selected | 153 × 227 m | 18,597 | 293,887 | 36,085,760 (34.4 MiB) | 122.8 | 619.5 MiB |
| Level 18 | 76 × 114 m | 53,392 | 360,000 | 46,440,448 (44.3 MiB) | 129.0 | 797.2 MiB |

The finer scenario occupied 2.87× as many distinct cells, but used 1.29× the monthly storage: sparse daily occupancy, rather than a fully allocated world grid, determines cost. Selected-level flat daily JSON would use 81,506,956 bytes before pretty-printing and wrapper overhead.

Before freezing the counters, the script also compares the daily table to one retaining only observation count and timestamps, with comparable cell/day indexes. In this scenario, adding passage count, four altitude counters, altitude bounds and history completeness costs approximately **12.5 bytes per daily row** at level 17, about **3.7 MB per month** for 293,887 rows. SQLite uses variable-length integers; higher counts and non-integral altitude bounds cost more. This is a scenario estimate, not a fixed row-size guarantee. Metadata, origins, indexes and page allocation are included in monthly file sizes; transient transaction journals and backup/export files are additional.

Repeat from the repository root:

```sh
python3 tools/estimate_density_storage.py
python3 tools/estimate_density_storage.py --snapshots ./saved-aircraft-json
```

For saved snapshots, place valid dump1090-style `.json` files in chronological filename order, including numeric `now` and an `aircraft` array. That mode compares spatial occupancy of supplied positions; it does not reproduce the live stale-position filter or passage algorithm. Actual traffic distribution, track cadence, traffic volume and route repetition will change the occupied-cell counts and sizes. Eighteen-month figures multiply this one-month scenario by 18; they are not forecasts or hard byte limits.

## Observations and passages

Every successful selected-source publication invokes collection once. Flights.js and aircraft.json use their configured poll intervals; SBS and TFMS use their consolidated one-second publications. Density does not count raw messages, repeated HTTP reads, or an independently sampled copy of `latest_data`. Collection works with all four sources even when the map and layer are closed. A successful poll of an unchanged aircraft snapshot still represents a new Bridge cycle.

A valid observation requires an aircraft identity and finite latitude/longitude in the global valid ranges. Duplicate identities within a snapshot receive at most one credit. A reported position age (`seen_pos`, falling back to `seen`) above 90 seconds, negative or nonfinite is excluded. Missing age metadata is accepted. Latitude/longitude at zero are valid. Exact poles and ±180° are supported.

An observation credits only its actual base cell. No track history, line interpolation, range bin, legacy maximum, or inferred traversal creates observations in other cells.

A passage is the first recent observation of an aircraft in a particular base cell. A per-aircraft cache remembers cell visits for **90 seconds**, refreshing the cell's visit time while occupied. Returning within that interval does not add another passage. Continuous occupancy remains one passage; a longer absence creates another. This suppresses common boundary jitter and short track dropouts while recording real observations on both sides of a boundary. It intentionally merges genuine quick returns within the grace interval. Unobserved intermediate cells receive no passage credit.

Passage tracking is held in memory and starts fresh after restart or restore. An aircraft present at that point can receive a new passage, so passage counts are empirical estimates rather than exact unique-flight counts. The maximum in-memory visit horizon is 90 seconds.

Parent-cell `passage_count` is the **sum of base-cell passages**, not a deduplicated parent-entry count. The API identifies this with `passage_aggregation: sum_of_base_cell_passages`, and coarse map popups label it accordingly. Raw track identities are not stored, so exact deduplication at arbitrary coarser resolutions cannot be reconstructed.

## Altitudes and integrity

The first usable value is selected from `alt_baro`, then `alt_geom`; `ground` becomes 0 ft. Missing, boolean, nonnumeric or nonfinite values are unknown. The input's supplied altitude reference is retained; no conversion between barometric and geometric altitude is inferred.

| Counter | Notional band |
|---|---|
| `below_1200_ft` | Below 1,200 ft |
| `1200_to_17999_ft` | At least 1,200 ft and below 18,000 ft |
| `18000_ft_and_above` | At least 18,000 ft |
| `unknown` | No usable altitude |

These are not airspace classes. Each cell/day retains min/max usable altitude, observation and passage counts, first/last timestamps and `history_complete`. Min/max are null when all observations are unknown. The invariant is:

```text
observation_count = below_1200_ft + 1200_to_17999_ft + 18000_ft_and_above + unknown
```

The aggregate API presents the counters inside `altitude`, matching the requested cell-statistics concepts. Export preserves their underlying daily counters. Unknown observations contribute to the initial combined All Traffic map but are never assigned to Low, Middle or High.

## Monthly persistence and time windows

The dataset is separate from range coverage:

```text
/data/traffic-density/identity.json
/data/traffic-density/2026-10.dat
/data/traffic-density/2026-09.dat
...
```

Each `.dat` is a SQLite database, not a custom binary format. Its sparse `daily` table has a composite `cell, day` key; `origins` stores cell/month provenance and `metadata` records schema/base level. Monthly totals are reconstructible from daily rows. Files are created only for months with observations or restored records.

Retention keeps the current UTC calendar month and the previous 17 months. In October 2026, the oldest retained month is May 2025. Pruning runs at collection/query and through a 30-second maintenance loop, including during upstream outages. Records older than the horizon are not restored. Future-month imports are ignored.

The default map/API covers **today plus the preceding 29 UTC dates**. This crosses month boundaries and includes the partial current day. `start` and `end` can select arbitrary inclusive daily windows in retained history. Daily counters cannot provide an exact arbitrary-hour rolling 30×24-hour window; v0.6.0 deliberately provides calendar-day precision. Cell timestamps on query results describe the selected window, rather than claiming lifetime history outside it.

SQLite transactions commit at most every 30 seconds during ordinary collection and flush on normal SIGTERM/exit. An abrupt power loss can lose the current uncommitted interval. Existing invalid/corrupt/incompatible files prevent collection from starting; they are not replaced with an empty history. The Bridge feed continues, and density endpoints report unavailable. Collection/read errors are logged and exposed through the density status endpoint.

Ordinary App restart/upgrade preserves `/data`. Uninstall, reinstall or a destructive rebuild can remove it. Export density and range coverage separately before such operations. Normal Home Assistant backup behavior has not been exercised in this development environment.

## API and map

All URLs below are relative to the App's HTTP root, so Home Assistant Ingress works without hard-coded prefixes.

| Endpoint | Result |
|---|---|
| `GET /traffic-density` | Recent cell statistics; includes observation and passage metrics |
| `GET /traffic-density?start=2026-09-06&end=2026-10-05&zoom=16` | Inclusive daily window aggregated to parent cells |
| `GET /traffic-density.geojson` | Recent actual base-cell polygons and statistics |
| `GET /traffic-density.geojson?zoom=16&bbox=-79,41,-75,44` | Parent polygons appropriate to a map viewport |
| `GET /traffic-density/export` | JSON snapshot of all retained months, cells and daily counters |
| `GET /traffic-density/export?month=2026-10` | JSON snapshot of one month |
| `POST /traffic-density/import` | Validated whole-cell/month restore |
| `GET /traffic-density/status` | Availability, stored months, file sizes and collection errors |

`zoom` is the density hierarchy level, not the Leaflet zoom; accepted levels are 0…17. `bbox` is west,south,east,north and must not cross the date line. A displayed parent includes the sums of its occupied children. A parent polygon does not assert that all its fine children were observed. Base-level GeoJSON contains only actual occupied cells.

**Traffic Density** is unchecked at initial map load. The combined map uses a logarithmic blue-to-red color scale, normalized to the current viewport, and refreshes every 15 seconds while enabled. Coarser parent cells are requested at smaller map zooms; the stored data remains level 17. Popups include observation counts, base-cell passage sums, all altitude counters, the displayed window and history-start certainty. Status-page controls provide JSON backup/restore and GeoJSON export. The backup selector can export retained months individually.

JSON exports can be considerably larger than their SQLite source. HTTP import accepts up to 256 MiB per request; export one month at a time for large histories. Each monthly export has the same schema and can be restored separately. Exporting all 18 months into a single JSON object can also require substantial server/browser memory; monthly backup is recommended for mature datasets. GeoJSON is an analysis/display export, not a restore format.

## Restore and provenance

A JSON backup has `schema_version: 1`, `scheme: geographic-quadtree`, `base_zoom: 17`, and a `months` object. Each month's cell record contains `cell_id`, `provenance`, and a `days` object. Internal daily timestamps are numeric UTC Unix seconds; public cell-query timestamps use ISO 8601. This is an explicit versioned schema, not an import of range-coverage JSON.

The whole payload is validated before mutation, including canonical cell IDs, month/day membership, timestamps, nonnegative counters, altitude bounds, count integrity, completeness flags and duplicate monthly cell records. Invalid bodies make no changes.

Collisions operate on **cell + month**. They never add overlapping histories. A deterministic rank selects one entire snapshot: latest daily `last_observed`, then provenance string, then a canonical content hash. The content hash excludes completeness/first-start markers so uncertainty propagation cannot change which counters win. An identical restore is idempotent. An older backup cannot replace a newer colliding snapshot merely because it has larger counts. A newer whole snapshot can replace counts for the whole cell/month; days from a losing snapshot are not silently unioned.

If colliding records have different provenance, either has incomplete history, or equal-ranked content disagrees about its start, all retained daily records for the winning cell/month have `first_observed = null` and `history_complete = false`. Unknown starts remain unknown during subsequent collection. No epoch/1970 start is invented. Noncolliding records retain their own known-start metadata.

Restore commits atomically **per monthly file**, not across an entire multi-month archive. A validation failure occurs before all writes; an I/O failure during restore can leave earlier months committed. The HTTP error identifies that limitation. Re-export and inspect, then retry the saved snapshots; the merge policy remains nonadditive. Ordinary collection and restore are serialized.

## Scope and validation

This release collects all four altitude counters from its first observation. Selectable Low/Middle/High combinations and density-derived range envelopes remain v0.6.x follow-ons. No density-derived range is substituted for existing 0.5° coverage.

Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q fr24-dump1090
```

Tests cover global/polar coordinates, altitude fallback/band edges/count integrity, no inferred cells, boundary jitter, short/long dropouts, continuous occupancy, UTC daily/month boundaries, hierarchy aggregation, retention, restart persistence, repeated/older/newer/conflicting restore, deterministic collision order, invalid-import rejection and corruption protection. Local HTTP tests exercise the density endpoints and status/map HTML, and publisher tests exercise all four source hooks. Existing 720-bin coverage migration tests remain included. The new module is copied into the image and allowed by AppArmor.

The package has not been built or installed inside a live Home Assistant instance here. Docker/AppArmor runtime, real-feed sizing and the rendered Leaflet layer still need installation checks on the user's system.
