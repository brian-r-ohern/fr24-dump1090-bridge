#!/usr/bin/env python3
"""FR24 receiver -> dump1090/readsb-compatible HTTP bridge for Home Assistant OS."""

import ast
import atexit
import signal
import sys
import json
import math
import os
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, Request, build_opener, urlopen

from bridge_config import validate_options
from bridge_settings import settings_page, settings_post
from traffic_density import DensityStore
from density_archive import archive_file, geojson_file, restore_stream
from density_envelopes import EnvelopeCache
from pathlib import Path
import shutil
import sqlite3

from swim_tfms import SwimTfmsClient, parse_tfms_tracks, update_tfms_course

BUILD_VERSION = "0.6.8"

CONFIG_PATH = os.environ.get("FR24_OPTIONS_PATH", "/data/options.json")
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8085
DEGRADED_AFTER_SECONDS = 10
UNHEALTHY_AFTER_SECONDS = 30
SBS_SNAPSHOT_INTERVAL = 1.0
SBS_AIRCRAFT_TIMEOUT = 60.0
SBS_RECONNECT_DELAY = 2.0
SBS_SOCKET_TIMEOUT = 5.0
SOURCE_LABELS = {"sbs_30003":"SBS", "flights_js":"FR24 HTTP", "aircraft_json":"ADSB JSON", "swim_tfms":"FAA TFMS"}
SOURCE_PREFIXES = {"sbs_30003":"sbs", "flights_js":"fr24", "aircraft_json":"d1090", "swim_tfms":"faa"}

def source_title():
    return SOURCE_LABELS[CFG["source"]] + " → dump1090"

def export_name(dataset, extension="json"):
    return SOURCE_PREFIXES[CFG["source"]] + "-" + dataset + "." + extension

VALID_SOURCES = ("sbs_30003", "flights_js", "aircraft_json", "swim_tfms")
OSM_TILE_BASE = "https://tile.openstreetmap.org"
OSM_TILE_CACHE = os.environ.get("FR24_TILE_CACHE", "/data/map-tile-cache-v2")
OSM_TILE_USER_AGENT = "FR24-dump1090-Bridge/0.6.8 (+https://github.com/brian-r-ohern/fr24-dump1090-bridge)"
OSM_TILE_FALLBACK_TTL = 7 * 24 * 60 * 60
OSM_TILE_TIMEOUT = 10
TILE_PROXY_BUILD = "v" + BUILD_VERSION
tile_proxy_requests = 0
tile_proxy_cache_hits = 0
tile_proxy_upstream_fetches = 0
tile_proxy_blocked = 0
tile_proxy_last_error = None
tile_proxy_last_referer = None


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        return validate_options(json.load(handle))


CFG = load_config()
if CFG["enrichment_source"] not in ("adsb_tracker", "none"):
    raise ValueError("enrichment_source must be adsb_tracker or none")
RECEIVER_URL = f"http://{CFG['receiver_host']}:{CFG['receiver_port']}/flights.js" if CFG["receiver_host"] else None

password_mgr = HTTPPasswordMgrWithDefaultRealm()
if RECEIVER_URL:
    password_mgr.add_password(None, RECEIVER_URL, CFG["username"], CFG["password"])
opener = build_opener(HTTPDigestAuthHandler(password_mgr))

latest_data = {"now": int(time.time()), "messages": 0, "aircraft": []}
lock = threading.Lock()
START_TIME = time.time()
last_success_time = None
last_poll_duration_ms = None
consecutive_failures = 0
total_successful_polls = 0
total_failed_polls = 0
requests_served = 0
json_last_messages = None
json_message_rate = None
json_previous_messages = None
json_previous_message_time = None


# FAA SWIM/TFMS source state. Credentials and queue identifiers are never exposed
# through HTTP diagnostics. Home coordinates are used only in memory for the
# configured geographic gate and are likewise never emitted by /status.
swim_aircraft = {}
swim_connected = False
swim_last_message_time = None
swim_messages_received = 0
swim_records_seen = 0
swim_track_records = 0
swim_parser_diagnostics = {
    'message_types': {}, 'track_information': 0, 'positioned_tracks': 0,
    'missing_latitude': 0, 'missing_longitude': 0,
    'first_message_structure': [], 'first_track_structure': [],
}
swim_track_records_accepted = 0
swim_track_records_outside_gate = 0
swim_parse_errors = 0
swim_reconnects = 0
swim_last_error = None
swim_started = None

# Home Assistant Core API state used only by the map presentation layer.
# Coordinates are deliberately excluded from /status and aircraft JSON output.
home_marker = None
home_marker_last_attempt = None
home_marker_last_success = None
home_marker_error = None

# Optional ADSB Aircraft Tracker enrichment used only by the map presentation
# layer. The bridge aircraft feed remains unchanged. Missing Tracker entities are
# normal and simply produce an empty enrichment result.
tracker_enrichment = {"available": False, "closest_hex": None, "military_hexes": [], "origin_hexes": [], "destination_hexes": [], "aircraft": {}}
tracker_enrichment_last_attempt = 0.0
tracker_enrichment_cache_seconds = 2.0
tracker_available_logged = None
tracker_ever_detected = False

# Empirical 0.5-degree maxima; preserve legacy 1-degree data separately.
# Legacy 1-degree imports explicitly seed adjacent bins and retain provenance.
COVERAGE_PATH = os.environ.get("FR24_COVERAGE_PATH", "/data/range-coverage.json")
COVERAGE_FLUSH_SECONDS = 30.0
coverage_io_lock = threading.Lock()
COVERAGE_BIN_DEGREES = 0.5
COVERAGE_BIN_COUNT = 720
coverage_baseline = None
coverage_pending = []
coverage_bins = [None] * COVERAGE_BIN_COUNT
coverage_dirty = False
coverage_generation = 0
coverage_last_flush = 0.0
coverage_loaded = False
coverage_last_import = None
coverage_stats = {
    "collection_started": None,
    "total_updates": 0,
    "first_fills": 0,
    "record_replacements": 0,
    "last_update": None,
    "hourly_updates": {},
}

# SBS/BaseStation source state. Each field carries the newest value observed for
# an ICAO address; last_seen and position_seen retain independent ages.
sbs_aircraft = {}
sbs_connected = False
sbs_last_message_time = None
sbs_total_messages = 0
sbs_parse_errors = 0
sbs_reconnects = 0
sbs_connection_attempts = 0
sbs_message_rate = 0.0



def _cache_max_age(headers, now):
    cache_control = headers.get("Cache-Control", "")
    match = re.search(r"(?:^|,)\s*max-age=(\d+)", cache_control, re.I)
    if match:
        return max(0, int(match.group(1)))
    expires = headers.get("Expires")
    if expires:
        try:
            dt = parsedate_to_datetime(expires)
            return max(0, int(dt.timestamp() - now))
        except (TypeError, ValueError, OverflowError):
            pass
    return OSM_TILE_FALLBACK_TTL


def _tile_paths(z, x, y):
    directory = os.path.join(OSM_TILE_CACHE, str(z), str(x))
    return directory, os.path.join(directory, f"{y}.png"), os.path.join(directory, f"{y}.json")


def _read_tile_meta(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_tile_cache(tile_path, meta_path, body, meta):
    os.makedirs(os.path.dirname(tile_path), exist_ok=True)
    tmp_tile = tile_path + ".tmp"
    tmp_meta = meta_path + ".tmp"
    with open(tmp_tile, "wb") as handle:
        handle.write(body)
    with open(tmp_meta, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, separators=(",", ":"))
    os.replace(tmp_tile, tile_path)
    os.replace(tmp_meta, meta_path)


class TileBlockedError(RuntimeError):
    pass


def _valid_web_origin(value):
    """Return a safe origin-only Referer, or None. Never forward an Ingress path/token."""
    if not value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}/"


def _remove_cached_tile(tile_path, meta_path):
    for path in (tile_path, meta_path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"[WARN] Unable to remove rejected map cache entry {path}: {exc}", flush=True)


def get_map_tile(z, x, y, referer=None):
    if z < 0 or z > 19 or x < 0 or y < 0 or x >= (1 << z) or y >= (1 << z):
        raise ValueError("invalid tile coordinates")
    directory, tile_path, meta_path = _tile_paths(z, x, y)
    del directory
    now = time.time()
    meta = _read_tile_meta(meta_path)
    if os.path.isfile(tile_path) and float(meta.get("expires_at", 0)) > now:
        with open(tile_path, "rb") as handle:
            return handle.read(), meta, True

    headers = {"User-Agent": OSM_TILE_USER_AGENT, "Accept": "image/png,image/*;q=0.8,*/*;q=0.5"}
    # Preserve the real browser Referer end-to-end when Ingress supplies one.
    if referer:
        headers["Referer"] = referer
    if os.path.isfile(tile_path):
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]

    global tile_proxy_upstream_fetches, tile_proxy_blocked, tile_proxy_last_error, tile_proxy_last_referer
    tile_proxy_upstream_fetches += 1
    tile_proxy_last_referer = referer
    request = Request(f"{OSM_TILE_BASE}/{z}/{x}/{y}.png", headers=headers, method="GET")
    try:
        with urlopen(request, timeout=OSM_TILE_TIMEOUT) as response:
            body = response.read()
            response_headers = response.headers
            blocked = response_headers.get("X-Blocked")
            content_type = (response_headers.get("Content-Type") or "").lower()
            if blocked or not content_type.startswith("image/png"):
                _remove_cached_tile(tile_path, meta_path)
                reason = blocked or f"unexpected content type {content_type or 'missing'}"
                tile_proxy_blocked += 1
                tile_proxy_last_error = str(reason)
                raise TileBlockedError(reason)
            ttl = _cache_max_age(response_headers, now)
            new_meta = {
                "fetched_at": now,
                "expires_at": now + ttl,
                "etag": response_headers.get("ETag"),
                "last_modified": response_headers.get("Last-Modified"),
                "cache_control": response_headers.get("Cache-Control", f"public, max-age={ttl}"),
                "expires": response_headers.get("Expires"),
            }
            _write_tile_cache(tile_path, meta_path, body, new_meta)
            return body, new_meta, False
    except HTTPError as exc:
        if exc.code == 304 and os.path.isfile(tile_path):
            ttl = _cache_max_age(exc.headers, now)
            meta.update({
                "fetched_at": now,
                "expires_at": now + ttl,
                "etag": exc.headers.get("ETag") or meta.get("etag"),
                "last_modified": exc.headers.get("Last-Modified") or meta.get("last_modified"),
                "cache_control": exc.headers.get("Cache-Control") or meta.get("cache_control") or f"public, max-age={ttl}",
                "expires": exc.headers.get("Expires") or meta.get("expires"),
            })
            with open(tile_path, "rb") as handle:
                body = handle.read()
            _write_tile_cache(tile_path, meta_path, body, meta)
            return body, meta, True
        raise

def fetch_data(retries=3):
    last_error = None
    for attempt in range(retries):
        try:
            with opener.open(RECEIVER_URL, timeout=CFG["request_timeout"]) as response:
                raw = response.read().decode("utf-8", errors="replace")
            if raw and "fr24_callback" in raw:
                return raw
            last_error = ValueError("Receiver response did not contain fr24_callback")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt + 1 < retries:
            time.sleep(0.5)
    raise ValueError(f"Failed to fetch valid FR24 data after {retries} attempts: {last_error}")


def parse_jsonp(raw):
    start = raw.find("(")
    end = raw.rfind(")")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Bad FR24 JSONP format")
    js = raw[start + 1:end]
    js = js.replace("true", "True").replace("false", "False").replace("null", "None")
    while ",," in js:
        js = js.replace(",,", ",None,")
    return ast.literal_eval(js)


def transform(data):
    """Conservatively map FR24 fields to dump1090/readsb aircraft.json fields."""
    aircraft = []
    for _hex_id, values in data.items():
        try:
            ac = {"hex": str(values[0]).lower(), "seen": 0}
            if values[1] and values[2]:
                ac["lat"] = values[1]
                ac["lon"] = values[2]
            if values[3] or values[4] or values[5] or (values[1] and values[2]):
                ac["track"] = values[3]
            if values[4]:
                ac["alt_baro"] = values[4]
            if values[5]:
                ac["gs"] = values[5]
            if len(values) > 16:
                flight = str(values[16]).strip()
                if flight:
                    ac["flight"] = flight
            aircraft.append(ac)
        except (IndexError, TypeError, ValueError):
            continue
    return {"now": int(time.time()), "messages": len(aircraft), "aircraft": aircraft}


density_store = None
density_startup_error = None


def collect_density(aircraft, observed):
    if density_store is None:
        return
    try:
        density_store.observe(aircraft, observed, CFG["source"])
        density_store.last_error = None
    except Exception as exc:
        density_store.last_error = str(exc)
        print(f"[WARN] Traffic density collection failed: {exc}", flush=True)


def density_maintenance():
    while True:
        time.sleep(30)
        if density_store is not None:
            try:
                density_store.prune()
                density_store.flush()
            except Exception as exc:
                density_store.last_error = str(exc)
                print(f"[WARN] Traffic density maintenance failed: {exc}", flush=True)


def flights_js_updater():
    global latest_data, last_success_time, last_poll_duration_ms
    global consecutive_failures, total_successful_polls, total_failed_polls
    while True:
        started = time.time()
        try:
            transformed = transform(parse_jsonp(fetch_data()))
            finished = time.time()
            with lock:
                latest_data = transformed
                last_success_time = finished
                last_poll_duration_ms = round((finished - started) * 1000, 1)
                consecutive_failures = 0
                total_successful_polls += 1
            collect_density(transformed["aircraft"], finished)
        except Exception as exc:
            with lock:
                consecutive_failures += 1
                total_failed_polls += 1
                last_poll_duration_ms = round((time.time() - started) * 1000, 1)
            print(f"[ERROR] FR24 poll failed: {exc}", flush=True)
        time.sleep(CFG["poll_interval"])



def normalize_aircraft_json(data):
    """Validate and normalize a dump1090/readsb aircraft.json snapshot."""
    if not isinstance(data, dict) or not isinstance(data.get("aircraft"), list):
        raise ValueError("aircraft_json response must be an object containing an aircraft array")
    aircraft = []
    for raw in data["aircraft"]:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        hex_id = str(item.get("hex", "")).strip().lower()
        if not hex_id:
            continue
        item["hex"] = hex_id
        aircraft.append(item)
    messages = data.get("messages")
    if not isinstance(messages, (int, float)) or isinstance(messages, bool):
        messages = len(aircraft)
    now_value = data.get("now")
    if not isinstance(now_value, (int, float)) or isinstance(now_value, bool):
        now_value = int(time.time())
    return {"now": now_value, "messages": messages, "aircraft": aircraft}


def aircraft_json_updater():
    global latest_data, last_success_time, last_poll_duration_ms
    global consecutive_failures, total_successful_polls, total_failed_polls
    global json_last_messages, json_message_rate, json_previous_messages, json_previous_message_time
    while True:
        started = time.time()
        try:
            request = Request(CFG["aircraft_json_url"], headers={"User-Agent": OSM_TILE_USER_AGENT}, method="GET")
            with urlopen(request, timeout=CFG["request_timeout"]) as response:
                raw = response.read().decode("utf-8", errors="replace")
            transformed = normalize_aircraft_json(json.loads(raw))
            finished = time.time()
            messages = transformed.get("messages")
            with lock:
                if isinstance(messages, (int, float)) and not isinstance(messages, bool):
                    json_last_messages = messages
                    if json_previous_messages is not None and json_previous_message_time is not None and messages >= json_previous_messages:
                        elapsed = max(0.001, finished - json_previous_message_time)
                        json_message_rate = (messages - json_previous_messages) / elapsed
                    json_previous_messages = messages
                    json_previous_message_time = finished
                latest_data = transformed
                last_success_time = finished
                last_poll_duration_ms = round((finished - started) * 1000, 1)
                consecutive_failures = 0
                total_successful_polls += 1
            collect_density(transformed["aircraft"], finished)
        except Exception as exc:
            with lock:
                consecutive_failures += 1
                total_failed_polls += 1
                last_poll_duration_ms = round((time.time() - started) * 1000, 1)
            print(f"[ERROR] aircraft.json poll failed: {exc}", flush=True)
        time.sleep(CFG["aircraft_json_poll_interval"])


def _supervisor_core_request(path):
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN is unavailable")
    request = Request(
        f"http://supervisor/core/api{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="GET",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def refresh_home_marker():
    global home_marker, home_marker_last_attempt, home_marker_last_success, home_marker_error
    home_marker_last_attempt = time.time()
    try:
        state = _supervisor_core_request("/states/zone.home")
        attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
        lat = float(attrs["latitude"])
        lon = float(attrs["longitude"])
        radius = float(attrs.get("radius", 0))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("zone.home coordinates are out of range")
        with lock:
            home_marker = {"latitude": lat, "longitude": lon, "radius": max(0, radius)}
            home_marker_last_success = time.time()
            home_marker_error = None
    except Exception as exc:
        with lock:
            home_marker_error = str(exc)
        print(f"[WARN] Home marker unavailable from Home Assistant zone.home: {exc}", flush=True)


def home_marker_updater():
    while True:
        refresh_home_marker()
        time.sleep(300)


def map_config():
    with lock:
        marker = dict(home_marker) if home_marker else None
    return {"source": CFG["source"], "title": source_title(), "coverage_outline_enabled": CFG["source"] != "swim_tfms", "home": marker, "destination_airport": CFG["destination_airport"] or None, "enrichment_source": CFG["enrichment_source"], "track_history_available": bool(CFG["history_url"]), "track_history_query": "callsign" if CFG["source"] == "swim_tfms" else "hex"}


def _coverage_distance_bearing(lat1, lon1, lat2, lon2):
    """Return great-circle distance in nautical miles and initial bearing."""
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    distance_nm = r_nm * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return distance_nm, bearing


def _validated_coverage_bins(payload):
    if not isinstance(payload, dict):
        raise ValueError("coverage import must be a JSON object")
    resolution = payload.get("bin_degrees", 1)
    if isinstance(resolution, bool) or resolution not in (1, 0.5):
        raise ValueError("coverage import must use 1 or 0.5-degree bins")
    bins = payload.get("bins")
    if not isinstance(bins, list) or len(bins) > int(360 / resolution):
        raise ValueError("invalid coverage bins array")
    clean_bins, seen = [], set()
    for item in bins:
        if not isinstance(item, dict):
            raise ValueError("every coverage bin must be an object")
        bearing = item.get("bearing")
        if isinstance(bearing, bool) or not isinstance(bearing, (int, float)) or not math.isfinite(bearing) or not 0 <= bearing < 360 or bearing / resolution != int(bearing / resolution):
            raise ValueError("coverage bearing must align with the source resolution")
        if bearing in seen:
            raise ValueError(f"duplicate coverage bearing {bearing}")
        seen.add(bearing)
        for key, low, high in (("distance_nm", 0, float("inf")), ("latitude", -90, 90), ("longitude", -180, 180)):
            value = item.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"invalid {key} for bearing {bearing}")
        clean = dict(item)
        clean.setdefault("first_observed", clean.get("observed"))
        clean.setdefault("update_count", 1)
        clean_bins.append(clean)
    return resolution, clean_bins


def _coverage_index(bearing):
    return int(math.floor((bearing % 360) / COVERAGE_BIN_DEGREES + 0.5)) % COVERAGE_BIN_COUNT


def _merge_coverage_item(item, resolution, marker, result):
    clean = dict(item)
    if resolution == 1:
        clean["source_bin_degrees"] = 1
        clean["source_bearing"] = item["bearing"]
        clean["provenance"] = "legacy_adjacent_seed"
        clean["seeded"] = True
        if marker:
            _, actual_bearing = _coverage_distance_bearing(marker["latitude"], marker["longitude"], item["latitude"], item["longitude"])
            clean["measured_bearing"] = actual_bearing
        indexes = [int(item["bearing"] * 2), (int(item["bearing"] * 2) + 1) % COVERAGE_BIN_COUNT]
    else:
        indexes = [int(item["bearing"] / COVERAGE_BIN_DEGREES)]
    for index in indexes:
        target = dict(clean)
        target["bearing"] = index * COVERAGE_BIN_DEGREES
        current = coverage_bins[index]
        if current is None:
            coverage_bins[index] = target
            result["added"] += 1
        elif float(target["distance_nm"]) > float(current["distance_nm"]):
            coverage_bins[index] = target
            result["replaced"] += 1
        else:
            result["retained"] += 1


def load_coverage():
    global coverage_bins, coverage_loaded, coverage_stats, coverage_baseline, coverage_pending, coverage_dirty, coverage_generation
    try:
        with open(COVERAGE_PATH, "r", encoding="utf-8") as handle:
            original = handle.read()
        payload = json.loads(original)
        resolution, bins = _validated_coverage_bins(payload)
        baseline = payload if resolution == 1 else payload.get("baseline_1_degree")
        if baseline is not None and _validated_coverage_bins(baseline)[0] != 1:
            raise ValueError("baseline must use 1-degree bins")
        pending = payload.get("pending_1_degree", []) if resolution == 0.5 else []
        if pending:
            _, pending = _validated_coverage_bins({"bin_degrees": 1, "bins": pending})
        # Archive exact original bytes before allowing a legacy file to be replaced.
        if resolution == 1:
            backup = COVERAGE_PATH + ".1-degree-baseline.json"
            try:
                with open(backup, "x", encoding="utf-8") as handle:
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                pass
        with lock:
            coverage_bins = [None] * COVERAGE_BIN_COUNT
            coverage_baseline = baseline
            coverage_pending = []
            marker = dict(home_marker) if home_marker else None
            result = {"added": 0, "replaced": 0, "retained": 0, "pending": 0}
            for item in bins:
                _merge_coverage_item(item, resolution, marker, result)
            for item in pending:
                _merge_coverage_item(item, 1, marker, result)
            if resolution == 0.5 and baseline is not None:
                for item in _validated_coverage_bins(baseline)[1]:
                    _merge_coverage_item(item, 1, marker, result)
            old_stats = payload.get("stats", {})
            if isinstance(old_stats, dict):
                coverage_stats.update(old_stats)
            coverage_loaded = True
            if resolution == 1 or pending or (resolution == 0.5 and (result["added"] or result["replaced"])):
                coverage_dirty = True
                coverage_generation += 1
        print(f"[INFO] Coverage history loaded: {sum(x is not None for x in coverage_bins)}/{COVERAGE_BIN_COUNT} bins; {len(coverage_pending)} legacy positions pending Home", flush=True)
    except FileNotFoundError:
        coverage_loaded = True
        print(f"[INFO] Coverage history initialized: 0/{COVERAGE_BIN_COUNT} bearing bins", flush=True)
    except Exception as exc:
        # Avoid overwriting unreadable data during startup.
        coverage_loaded = False
        print(f"[WARN] Coverage history could not be loaded; collection paused: {exc}", flush=True)


def flush_coverage(force=False):
    with coverage_io_lock:
        _flush_coverage(force)


def _flush_coverage(force=False):
    global coverage_dirty, coverage_last_flush
    now = time.time()
    with lock:
        if not coverage_loaded:
            return
        if not coverage_dirty and not force:
            return
        if not force and now - coverage_last_flush < COVERAGE_FLUSH_SECONDS:
            return
        bins = [dict(item) for item in coverage_bins if item is not None]
        stats = dict(coverage_stats)
        stats["hourly_updates"] = dict(coverage_stats.get("hourly_updates", {}))
        generation = coverage_generation
        baseline = coverage_baseline
        pending = [dict(x) for x in coverage_pending]
    payload = {"version": 3, "bin_degrees": COVERAGE_BIN_DEGREES, "updated": iso_utc(now), "stats": stats, "bins": bins, "baseline_1_degree": baseline, "pending_1_degree": pending}
    tmp = COVERAGE_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(COVERAGE_PATH) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, COVERAGE_PATH)
        with lock:
            if coverage_generation == generation:
                coverage_dirty = False
            coverage_last_flush = now
    except Exception as exc:
        print(f"[WARN] Coverage history could not be saved: {exc}", flush=True)
        try:
            os.unlink(tmp)
        except OSError:
            pass


def update_coverage_from_snapshot():
    global coverage_dirty, coverage_generation, coverage_stats
    with lock:
        marker = dict(home_marker) if home_marker else None
        aircraft = list(latest_data.get("aircraft", []))
    if not marker or not coverage_loaded or CFG["source"] == "swim_tfms":
        return
    with lock:
        if coverage_pending:
            pending = list(coverage_pending)
            coverage_pending.clear()
            result = {"added": 0, "replaced": 0, "retained": 0, "pending": 0}
            for item in pending:
                _merge_coverage_item(item, 1, marker, result)
            coverage_dirty = True
            coverage_generation += 1
    home_lat, home_lon = marker["latitude"], marker["longitude"]
    changed = False
    now = time.time()
    observed = iso_utc(now)
    hour_key = time.strftime("%Y-%m-%dT%H:00:00Z", time.gmtime(now))
    for ac in aircraft:
        try:
            lat, lon = float(ac["lat"]), float(ac["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        distance_nm, bearing = _coverage_distance_bearing(home_lat, home_lon, lat, lon)
        bin_no = _coverage_index(bearing)
        with lock:
            current = coverage_bins[bin_no]
            if current is not None and float(current.get("distance_nm", -1)) >= distance_nm:
                continue
            first_fill = current is None
            first_observed = observed if first_fill else current.get("first_observed") or current.get("observed") or observed
            update_count = 1 if first_fill else int(current.get("update_count", 1)) + 1
            coverage_bins[bin_no] = {
                "bearing": bin_no * COVERAGE_BIN_DEGREES,
                "measured_bearing": bearing,
                "source_bin_degrees": COVERAGE_BIN_DEGREES,
                "provenance": "observed",
                "distance_nm": round(distance_nm, 2),
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "hex": str(ac.get("hex", "")).strip().lower() or None,
                "flight": str(ac.get("flight", "")).strip() or None,
                "altitude_ft": ac.get("alt_baro"),
                "first_observed": first_observed,
                "observed": observed,
                "update_count": update_count,
            }
            if not coverage_stats.get("collection_started"):
                coverage_stats["collection_started"] = observed
            coverage_stats["total_updates"] = int(coverage_stats.get("total_updates", 0)) + 1
            key = "first_fills" if first_fill else "record_replacements"
            coverage_stats[key] = int(coverage_stats.get(key, 0)) + 1
            coverage_stats["last_update"] = observed
            hourly = coverage_stats.setdefault("hourly_updates", {})
            hourly[hour_key] = int(hourly.get(hour_key, 0)) + 1
            coverage_dirty = True
            coverage_generation += 1
            changed = True
    if changed:
        flush_coverage()



def import_coverage_payload(payload):
    """Merge native maxima or explicitly seed two adjacent bins per legacy sector."""
    global coverage_dirty, coverage_generation, coverage_last_import, coverage_baseline
    resolution, bins = _validated_coverage_bins(payload)
    # Validate embedded migration data before changing any live state.
    baseline = payload.get("baseline_1_degree")
    if baseline is not None:
        if _validated_coverage_bins(baseline)[0] != 1:
            raise ValueError("baseline must use 1-degree bins")
    pending = payload.get("pending_1_degree", [])
    if pending:
        _, pending = _validated_coverage_bins({"bin_degrees": 1, "bins": pending})
    if not coverage_loaded:
        raise ValueError("coverage history failed to load; repair it before importing")
    result = {"received": len(bins), "added": 0, "replaced": 0, "retained": 0, "pending": 0}
    with lock:
        marker = dict(home_marker) if home_marker else None
        if coverage_baseline is None:
            coverage_baseline = json.loads(json.dumps(payload if resolution == 1 else baseline))
        for item in bins:
            _merge_coverage_item(item, resolution, marker, result)
        for item in pending:
            _merge_coverage_item(item, 1, marker, result)
        imported_stats = payload.get("stats", {})
        if isinstance(imported_stats, dict):
            starts = [x for x in (coverage_stats.get("collection_started"), imported_stats.get("collection_started")) if x]
            if starts:
                coverage_stats["collection_started"] = min(starts)
        coverage_last_import = iso_utc(time.time())
        coverage_dirty = True
        coverage_generation += 1
        result["populated_bins"] = sum(x is not None for x in coverage_bins)
    flush_coverage(force=True)
    result["total_bins"] = COVERAGE_BIN_COUNT
    result["last_import"] = coverage_last_import
    return result

def clear_coverage():
    global coverage_bins, coverage_baseline, coverage_pending, coverage_dirty
    global coverage_generation, coverage_loaded, coverage_last_import
    with coverage_io_lock:
        with lock:
            coverage_bins = [None] * COVERAGE_BIN_COUNT
            coverage_baseline = None
            coverage_pending = []
            coverage_stats.update(collection_started=None,total_updates=0,first_fills=0,record_replacements=0,last_update=None,hourly_updates={})
            coverage_generation += 1
            coverage_loaded = True
            coverage_dirty = True
            coverage_last_import = None
            Path(COVERAGE_PATH+'.1-degree-baseline.json').unlink(missing_ok=True)
        _flush_coverage(True)
    return {'cleared':'range_coverage'}


def coverage_updater():
    if CFG["source"] == "swim_tfms":
        return
    refresh_home_marker()
    load_coverage()
    while True:
        try:
            update_coverage_from_snapshot()
            flush_coverage()
        except Exception as exc:
            print(f"[WARN] Coverage update failed: {exc}", flush=True)
        time.sleep(1)


def coverage_payload():
    with lock:
        bins = [dict(item) for item in coverage_bins if item is not None]
        stats = dict(coverage_stats)
        stats["hourly_updates"] = dict(coverage_stats.get("hourly_updates", {}))
        available = bool(home_marker)
        marker = dict(home_marker) if home_marker else None
        baseline = coverage_baseline
        pending = [dict(x) for x in coverage_pending]
    return {"envelope_segments": coverage_envelope_segments(bins, marker), "available": available, "version": 3, "bin_degrees": COVERAGE_BIN_DEGREES, "populated_bins": len(bins), "total_bins": COVERAGE_BIN_COUNT, "baseline_1_degree": baseline, "pending_1_degree": pending, "last_import": coverage_last_import, "stats": stats, "bins": bins}


def _coverage_destination(marker, bearing, distance_nm):
    distance = distance_nm / 3440.065
    theta = math.radians(bearing)
    lat, lon = math.radians(marker["latitude"]), math.radians(marker["longitude"])
    lat2 = math.asin(math.sin(lat) * math.cos(distance) + math.cos(lat) * math.sin(distance) * math.cos(theta))
    lon2 = lon + math.atan2(math.sin(theta) * math.sin(distance) * math.cos(lat), math.cos(distance) - math.sin(lat) * math.sin(lat2))
    return [((math.degrees(lon2) + 540) % 360) - 180, math.degrees(lat2)]


def coverage_envelope_segments(bins, marker):
    """Stepped bin footprints; break at every empty sector, including wraparound."""
    if not marker or not bins:
        return []
    by_index = {int(x["bearing"] / COVERAGE_BIN_DEGREES): x for x in bins}
    # Start just after a gap so north-crossing observed runs stay connected.
    missing = next((i for i in range(COVERAGE_BIN_COUNT) if i not in by_index), None)
    start = 0 if missing is None else (missing + 1) % COVERAGE_BIN_COUNT
    segments, run = [], []
    for offset in range(COVERAGE_BIN_COUNT):
        i = (start + offset) % COVERAGE_BIN_COUNT
        item = by_index.get(i)
        if item is None:
            if run:
                segments.append(run)
                run = []
            continue
        center = i * COVERAGE_BIN_DEGREES
        left = _coverage_destination(marker, center - COVERAGE_BIN_DEGREES / 2, item["distance_nm"])
        right = _coverage_destination(marker, center + COVERAGE_BIN_DEGREES / 2, item["distance_nm"])
        run.extend([left, right])
    if run:
        if missing is None:
            run.append(run[0])
        segments.append(run)
    return segments


def coverage_geojson_payload():
    """Ordered empirical points plus the exact map envelope, without gap bridging."""
    coverage = coverage_payload()
    bins = coverage["bins"]
    features = []
    segments = coverage["envelope_segments"]
    if segments:
        complete = len(bins) == COVERAGE_BIN_COUNT
        features.append({
            "type": "Feature",
            "properties": {"name": "Rendered empirical range envelope", "representation": "derived_bin_footprint", "bin_degrees": COVERAGE_BIN_DEGREES, "populated_bins": len(bins), "total_bins": COVERAGE_BIN_COUNT, "complete": complete, "gap_policy": "break_at_every_unobserved_bin", "interpolation": "none", "legacy_seed_bins": sum(x.get("provenance") == "legacy_adjacent_seed" for x in bins)},
            "geometry": {"type": "Polygon", "coordinates": [segments[0]]} if complete else {"type": "MultiLineString", "coordinates": segments},
        })
    for order, item in enumerate(bins):
        properties = {key: value for key, value in item.items() if key not in ("latitude", "longitude")}
        properties.update({"name": f"Bearing {item['bearing']:05.1f}°", "order": order, "representation": "legacy_sector_seed" if item.get("provenance") == "legacy_adjacent_seed" else "empirical_maximum", "bin_degrees": COVERAGE_BIN_DEGREES})
        features.append({"type": "Feature", "properties": properties, "geometry": {"type": "Point", "coordinates": [item["longitude"], item["latitude"]]}})
    return {"type": "FeatureCollection", "name": "FR24 dump1090 Bridge range coverage", "features": features}


def _entity_attributes(entity_id):
    state = _supervisor_core_request(f"/states/{entity_id}")
    attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
    return attrs if isinstance(attrs, dict) else {}


def refresh_tracker_enrichment(force=False):
    global tracker_enrichment, tracker_enrichment_last_attempt, tracker_available_logged, tracker_ever_detected
    if CFG["enrichment_source"] == "none":
        return {"available": False, "tracker_state": "disabled", "closest_hex": None, "military_hexes": [], "origin_hexes": [], "destination_hexes": [], "aircraft": {}}
    now = time.time()
    with lock:
        if not force and now - tracker_enrichment_last_attempt < tracker_enrichment_cache_seconds:
            return dict(tracker_enrichment)
        tracker_enrichment_last_attempt = now

    result = {"available": False, "closest_hex": None, "military_hexes": [], "origin_hexes": [], "destination_hexes": [], "aircraft": {}}
    try:
        closest = _entity_attributes("sensor.adsb_closest_aircraft")
        military = _entity_attributes("sensor.adsb_military_aircraft_details")
        all_aircraft = _entity_attributes("sensor.adsb_all_aircraft")

        # Require the Tracker's aggregate sensor, rather than treating an empty
        # entity response as a successful discovery.
        if "total_aircraft" not in all_aircraft:
            raise ValueError("ADSB Aircraft Tracker aggregate sensor unavailable")

        closest_hex = str(closest.get("hex", "")).strip().lower()
        if closest_hex:
            result["closest_hex"] = closest_hex

        military_hexes = set()
        for key, value in military.items():
            if not re.fullmatch(r"military_\d+", str(key)) or not isinstance(value, dict):
                continue
            hex_id = str(value.get("hex", "")).strip().lower()
            if hex_id:
                military_hexes.add(hex_id)
        result["military_hexes"] = sorted(military_hexes)

        airport = CFG["destination_airport"]
        origin_hexes, destination_hexes = set(), set()
        metadata = {}
        keep = ("tail", "flight", "distance_mi", "distance_display", "aircraft_type", "description", "operator",
                "route_origin", "route_origin_name", "route_destination", "route_destination_name")
        for key, value in all_aircraft.items():
            if not re.fullmatch(r"aircraft_\d+", str(key)) or not isinstance(value, dict):
                continue
            hex_id = str(value.get("hex", "")).strip().lower()
            if not hex_id:
                continue
            metadata[hex_id] = {name: value.get(name) for name in keep if value.get(name) not in (None, "")}
            if airport and str(value.get("route_origin", "")).strip().upper() == airport:
                origin_hexes.add(hex_id)
            if airport and str(value.get("route_destination", "")).strip().upper() == airport:
                destination_hexes.add(hex_id)
        result["origin_hexes"] = sorted(origin_hexes)
        result["destination_hexes"] = sorted(destination_hexes)
        result["aircraft"] = metadata
        result["available"] = True
    except Exception:
        # Tracker is optional; absence leaves the v0.4.0 map behavior intact.
        pass

    # Discovery is deliberately runtime-based. Home Assistant entities may not
    # be readable during bridge startup even though Tracker is installed. Do
    # not turn that startup race into a false "not found" result. Log the
    # first successful enrichment read, then only log real loss/recovery
    # transitions after Tracker has been seen at least once.
    if result["available"]:
        if not tracker_ever_detected:
            print("[INFO] ADSB Aircraft Tracker detected; Tracker enrichment active", flush=True)
        elif tracker_available_logged is False:
            print("[INFO] ADSB Aircraft Tracker enrichment restored", flush=True)
        tracker_ever_detected = True
        tracker_available_logged = True
    elif tracker_ever_detected and tracker_available_logged is not False:
        print("[WARNING] ADSB Aircraft Tracker enrichment unavailable", flush=True)
        tracker_available_logged = False

    result["tracker_state"] = ("active" if result["available"] else ("unavailable" if tracker_ever_detected else "awaiting"))
    with lock:
        tracker_enrichment = result
        return dict(tracker_enrichment)

def _number(value, integer=False):
    if value == "":
        return None
    try:
        return int(float(value)) if integer else float(value)
    except (TypeError, ValueError):
        return None


def parse_sbs_line(line):
    """Parse one BaseStation/SBS MSG record into an incremental state update."""
    fields = line.rstrip("\r\n").split(",")
    if len(fields) < 22 or fields[0] != "MSG":
        return None
    hex_id = fields[4].strip().lower()
    if not hex_id:
        return None
    update = {"hex": hex_id}
    flight = fields[10].strip()
    if flight:
        update["flight"] = flight
    altitude = _number(fields[11], integer=True)
    gs = _number(fields[12])
    track = _number(fields[13])
    lat = _number(fields[14])
    lon = _number(fields[15])
    baro_rate = _number(fields[16], integer=True)
    squawk = fields[17].strip()
    on_ground = fields[21].strip()
    if altitude is not None:
        update["alt_baro"] = altitude
    if gs is not None:
        update["gs"] = gs
    if track is not None:
        update["track"] = track
    if lat is not None and lon is not None:
        update["lat"] = lat
        update["lon"] = lon
        update["position_update"] = True
    if baro_rate is not None:
        update["baro_rate"] = baro_rate
    if squawk:
        update["squawk"] = squawk
    if on_ground in ("-1", "1"):
        update["alt_baro"] = "ground"
    return update


def apply_sbs_update(update, observed_at):
    ac = sbs_aircraft.setdefault(update["hex"], {"hex": update["hex"]})
    for key in ("flight", "alt_baro", "gs", "track", "lat", "lon", "baro_rate", "squawk"):
        if key in update:
            ac[key] = update[key]
    ac["last_seen"] = observed_at
    if update.get("position_update"):
        ac["position_seen"] = observed_at


def sbs_reader():
    global sbs_connected, sbs_last_message_time, sbs_total_messages
    global sbs_parse_errors, sbs_reconnects, sbs_connection_attempts
    had_connection = False
    target = (CFG["receiver_host"], CFG["sbs_port"])
    while True:
        with lock:
            sbs_connection_attempts += 1
        try:
            print(f"Connecting to SBS/BaseStation feed at {target[0]}:{target[1]}", flush=True)
            with socket.create_connection(target, timeout=SBS_SOCKET_TIMEOUT) as sock:
                sock.settimeout(SBS_SOCKET_TIMEOUT)
                with lock:
                    if had_connection:
                        sbs_reconnects += 1
                    sbs_connected = True
                had_connection = True
                print("SBS/BaseStation feed connected", flush=True)
                buffer = b""
                while True:
                    try:
                        chunk = sock.recv(65536)
                    except socket.timeout:
                        continue
                    if not chunk:
                        raise ConnectionError("receiver closed TCP/30003 connection")
                    buffer += chunk
                    while b"\n" in buffer:
                        raw_line, buffer = buffer.split(b"\n", 1)
                        line = raw_line.decode("ascii", errors="replace")
                        observed_at = time.time()
                        try:
                            update = parse_sbs_line(line)
                        except Exception:
                            update = None
                            with lock:
                                sbs_parse_errors += 1
                        if update is None:
                            continue
                        with lock:
                            apply_sbs_update(update, observed_at)
                            sbs_total_messages += 1
                            sbs_last_message_time = observed_at
        except Exception as exc:
            with lock:
                sbs_connected = False
            print(f"[ERROR] SBS/BaseStation connection failed: {exc}", flush=True)
            time.sleep(SBS_RECONNECT_DELAY)


def sbs_publisher():
    """Publish one consolidated dump1090 record per active ICAO each second."""
    global latest_data, sbs_message_rate
    previous_count = 0
    previous_time = time.time()
    while True:
        time.sleep(SBS_SNAPSHOT_INTERVAL)
        now = time.time()
        with lock:
            expired = [hex_id for hex_id, ac in sbs_aircraft.items()
                       if now - ac.get("last_seen", 0) > SBS_AIRCRAFT_TIMEOUT]
            for hex_id in expired:
                del sbs_aircraft[hex_id]

            aircraft = []
            for ac in sbs_aircraft.values():
                item = {"hex": ac["hex"], "seen": round(max(0.0, now - ac["last_seen"]), 1)}
                for key in ("flight", "alt_baro", "gs", "track", "lat", "lon", "baro_rate", "squawk"):
                    if key in ac:
                        item[key] = ac[key]
                if "position_seen" in ac:
                    item["seen_pos"] = round(max(0.0, now - ac["position_seen"]), 1)
                aircraft.append(item)
            aircraft.sort(key=lambda ac: ac["hex"])
            latest_data = {"now": int(now), "messages": sbs_total_messages, "aircraft": aircraft}
            elapsed = max(0.001, now - previous_time)
            sbs_message_rate = (sbs_total_messages - previous_count) / elapsed
            previous_count = sbs_total_messages
            previous_time = now
        collect_density(aircraft, now)



def _haversine_nm(lat1, lon1, lat2, lon2):
    r = math.pi / 180.0
    p1, p2 = lat1 * r, lat2 * r
    dp, dl = (lat2 - lat1) * r, (lon2 - lon1) * r
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1.0, math.sqrt(a)))


def _swim_home():
    with lock:
        hm = dict(home_marker) if isinstance(home_marker, dict) else None
    if not hm:
        return None
    try:
        return float(hm['latitude']), float(hm['longitude'])
    except (KeyError, TypeError, ValueError):
        return None


def _swim_hex(rec):
    # TFMS does not guarantee a Mode-S/ICAO address. Use it only when a future
    # parser can prove one; otherwise create a source-local stable identifier
    # from flight occurrence/callsign for dump1090-compatible transport.
    import hashlib
    identity = rec.get('_tfms_gufi') or rec.get('_tfms_flight_ref') or rec.get('flight')
    if not identity:
        return None
    return '~' + hashlib.sha1(str(identity).encode('utf-8')).hexdigest()[:6]


def _handle_swim_payload(payload):
    global swim_last_message_time, swim_messages_received, swim_records_seen
    global swim_track_records, swim_track_records_accepted, swim_track_records_outside_gate, swim_parse_errors
    now = time.time()
    try:
        diagnostics = {}
        records, record_count = parse_tfms_tracks(payload, diagnostics)
    except Exception:
        with lock:
            swim_parse_errors += 1
        raise
    home = _swim_home()
    with lock:
        swim_last_message_time = now
        swim_messages_received += 1
        swim_records_seen += record_count
        swim_track_records += diagnostics['track_information']
        for name in ('track_information', 'positioned_tracks', 'missing_latitude', 'missing_longitude'):
            swim_parser_diagnostics[name] += diagnostics[name]
        for name in ('first_message_structure', 'first_track_structure'):
            if not swim_parser_diagnostics[name]:
                swim_parser_diagnostics[name] = diagnostics[name]
        types = swim_parser_diagnostics['message_types']
        for name, count in diagnostics['message_types'].items():
            if name not in types and len(types) >= 32:
                name = '(other)'
            types[name] = types.get(name, 0) + count
    if home is None:
        # Never retain national-scale TFMS state before the private geographic
        # reference is available from Home Assistant.
        return
    for rec in records:
        distance = _haversine_nm(home[0], home[1], rec['lat'], rec['lon'])
        if distance > CFG['swim_radius_nm']:
            with lock:
                swim_track_records_outside_gate += 1
            continue
        key = _swim_hex(rec)
        if not key:
            continue
        ac = {k: v for k, v in rec.items() if not k.startswith('_')}
        ac['hex'] = key
        ac['seen'] = 0.0
        ac['_last_seen'] = now
        with lock:
            swim_aircraft[key] = update_tfms_course(ac, swim_aircraft.get(key))
            swim_track_records_accepted += 1


def _swim_state(state, error):
    global swim_connected, swim_last_error, swim_reconnects
    with lock:
        if state == 'connected':
            if swim_last_error is not None:
                swim_reconnects += 1
            swim_connected = True
            swim_last_error = None
        elif state in ('connecting',):
            swim_connected = False
        elif state in ('message_error',):
            swim_last_error = error
        elif state in ('stopping',):
            swim_connected = False
    if error:
        print(f'[ERROR] SWIM {state}: {error}', flush=True)


def swim_tfms_runner():
    global swim_connected, swim_last_error, swim_reconnects, swim_started
    swim_started = time.time()
    delay = max(1.0, CFG['swim_retry_interval_ms'] / 1000.0)
    while True:
        try:
            client = SwimTfmsClient(CFG, _handle_swim_payload, _swim_state)
            client.run()
        except Exception as exc:
            with lock:
                swim_connected = False
                swim_last_error = str(exc)
                swim_reconnects += 1
            print(f'[ERROR] SWIM connection failed: {exc}', flush=True)
            time.sleep(delay)


def swim_publisher():
    global latest_data, last_success_time
    while True:
        now = time.time()
        with lock:
            expired = [k for k, v in swim_aircraft.items() if now - v.get('_last_seen', 0) > CFG['swim_aircraft_timeout']]
            for k in expired:
                swim_aircraft.pop(k, None)
            aircraft = []
            for value in swim_aircraft.values():
                ac = {k: v for k, v in value.items() if not k.startswith('_')}
                ac['seen'] = round(max(0.0, now - value.get('_last_seen', now)), 1)
                aircraft.append(ac)
            latest_data = {'now': int(now), 'messages': swim_messages_received, 'aircraft': aircraft}
            if swim_last_message_time is not None:
                last_success_time = swim_last_message_time
        collect_density(aircraft, now)
        time.sleep(1.0)


def iso_utc(timestamp):
    return None if timestamp is None else datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def human_utc(timestamp):
    return "Never" if timestamp is None else datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def snapshot_status():
    with lock:
        aircraft = list(latest_data.get("aircraft", []))
        served = requests_served
        source = CFG["source"]
        if source in ("flights_js", "aircraft_json"):
            success_time = last_success_time
            poll_ms = last_poll_duration_ms
            failures = consecutive_failures
            successes = total_successful_polls
            failed_polls = total_failed_polls
            source_messages = json_last_messages if source == "aircraft_json" else None
            source_rate = json_message_rate if source == "aircraft_json" else None
        else:
            success_time = sbs_last_message_time
            connected = sbs_connected
            total_messages = sbs_total_messages
            parse_errors = sbs_parse_errors
            reconnects = sbs_reconnects
            attempts = sbs_connection_attempts
            message_rate = sbs_message_rate
    now = time.time()
    age = None if success_time is None else max(0.0, now - success_time)
    positioned = sum(1 for ac in aircraft if ac.get("lat") is not None and ac.get("lon") is not None)

    if source in ("flights_js", "aircraft_json"):
        if successes == 0 and failed_polls == 0:
            feed_status, receiver = "starting", "connecting"
        elif success_time is None or age > UNHEALTHY_AFTER_SECONDS:
            feed_status, receiver = "unhealthy", "disconnected"
        elif age > DEGRADED_AFTER_SECONDS:
            feed_status, receiver = "degraded", "stale"
        else:
            feed_status, receiver = "ok", "connected"
        result = {
            "build_version": BUILD_VERSION, "coverage_bin_degrees": COVERAGE_BIN_DEGREES, "coverage_total_bins": COVERAGE_BIN_COUNT, "service_status": "ok", "source": source, "feed_status": feed_status,
            "receiver": receiver, "uptime_seconds": round(now - START_TIME, 1),
            "poll_interval_seconds": CFG["poll_interval"] if source == "flights_js" else CFG["aircraft_json_poll_interval"],
            "last_success": iso_utc(success_time),
            "last_poll_age_seconds": None if age is None else round(age, 1),
            "last_poll_duration_ms": poll_ms, "consecutive_failures": failures,
            "successful_polls": successes, "failed_polls": failed_polls,
            "aircraft_total": len(aircraft), "aircraft_with_position": positioned,
            "aircraft_without_position": len(aircraft) - positioned, "requests_served": served,
        }
        if source == "aircraft_json":
            result["messages_received"] = source_messages
            result["message_rate_per_second"] = None if source_rate is None else round(source_rate, 1)
        return result

    if success_time is None:
        feed_status, receiver = ("starting", "connecting") if attempts <= 1 else ("unhealthy", "disconnected")
    elif not connected or age > UNHEALTHY_AFTER_SECONDS:
        feed_status, receiver = "unhealthy", "disconnected"
    elif age > DEGRADED_AFTER_SECONDS:
        feed_status, receiver = "degraded", "stale"
    else:
        feed_status, receiver = "ok", "connected"
    if source == "swim_tfms":
        with lock:
            connected = swim_connected
            last_msg = swim_last_message_time
            received = swim_messages_received
            records = swim_records_seen
            parser_diag = {
                k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
                for k, v in swim_parser_diagnostics.items()
            }
            tracks = swim_track_records
            accepted = swim_track_records_accepted
            outside = swim_track_records_outside_gate
            errors = swim_parse_errors
            reconnects = swim_reconnects
            last_error = swim_last_error
            aircraft_count = len(latest_data.get("aircraft", []))
        age = None if last_msg is None else max(0.0, now - last_msg)
        feed_status = "ok" if connected and age is not None and age <= UNHEALTHY_AFTER_SECONDS else ("degraded" if connected else "unavailable")
        return {
            "build_version": BUILD_VERSION, "coverage_bin_degrees": COVERAGE_BIN_DEGREES, "coverage_total_bins": COVERAGE_BIN_COUNT, "service_status": "ok", "source": "swim_tfms", "feed_status": feed_status,
            "receiver": "connected" if connected else "disconnected",
            "uptime_seconds": round(now - START_TIME, 1), "connected": connected,
            "last_message_age_seconds": None if age is None else round(age, 1),
            "aircraft": aircraft_count, "aircraft_total": aircraft_count,
            "aircraft_with_position": positioned, "aircraft_without_position": aircraft_count - positioned,
            "messages_received": received,
            "tfms_records_seen": records, "track_records": tracks,
            "tfms_parser_diagnostics": parser_diag,
            "track_records_accepted": accepted, "track_records_outside_gate": outside,
            "parse_errors": errors, "reconnects": reconnects,
            "radius_nm": CFG["swim_radius_nm"],
            "last_error": last_error, "requests_served": requests_served,
        }

    return {
        "build_version": BUILD_VERSION, "coverage_bin_degrees": COVERAGE_BIN_DEGREES, "coverage_total_bins": COVERAGE_BIN_COUNT, "service_status": "ok", "source": "sbs_30003", "feed_status": feed_status,
        "receiver": receiver, "uptime_seconds": round(now - START_TIME, 1),
        "sbs_port": CFG["sbs_port"], "snapshot_interval_seconds": SBS_SNAPSHOT_INTERVAL,
        "last_message": iso_utc(success_time),
        "last_message_age_seconds": None if age is None else round(age, 1),
        "messages_received": total_messages, "message_rate_per_second": round(message_rate, 1),
        "parse_errors": parse_errors, "connection_attempts": attempts, "reconnections": reconnects,
        "aircraft_total": len(aircraft), "aircraft_with_position": positioned,
        "aircraft_without_position": len(aircraft) - positioned, "requests_served": served,
    }


MAP_HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__SOURCE_TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>
html,body,#map{height:100%;margin:0;background:#111;font-family:system-ui,-apple-system,Segoe UI,sans-serif}#map{position:absolute;inset:0}
.topbar{position:absolute;z-index:1000;top:10px;left:50%;transform:translateX(-50%);background:rgba(17,17,17,.90);color:#eee;border-radius:8px;padding:8px 12px;box-shadow:0 2px 8px #0008;display:flex;gap:12px;align-items:center;white-space:normal;flex-wrap:wrap;justify-content:center;max-width:calc(100vw - 44px);width:max-content;box-sizing:border-box}.topbar strong{font-size:14px}.topbar{max-height:55vh;overflow:auto}.toolbar-main{display:flex;gap:8px 12px;align-items:center;justify-content:center;flex-wrap:wrap;width:100%}.analysis-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;width:100%;align-items:start}.analysis-controls{font-size:12px;min-width:0;border:1px solid #666;border-radius:5px;padding:6px 8px;box-sizing:border-box}.analysis-controls summary{cursor:pointer;min-height:24px}.analysis-body{display:flex;gap:8px 12px;flex-wrap:wrap;align-items:center;padding-top:6px}.analysis-body>span{flex-basis:100%;font-size:11px;color:#ccc}.analysis-body label{white-space:normal}[hidden]{display:none!important}.stats{font-size:12px;color:#ccc}.ok{color:#6ddc79}.bad{color:#ff6b6b}.degraded{color:#ffd166}.btn{border:1px solid #666;background:#222;color:#eee;border-radius:5px;padding:5px 8px;cursor:pointer}.btn:hover{background:#333}
.bottom-dock{position:absolute;z-index:1000;left:10px;right:10px;bottom:28px;display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:8px;pointer-events:none}.bottom-dock>*{pointer-events:auto;max-width:100%;box-sizing:border-box}.info{position:static;margin-left:auto;min-width:205px;background:rgba(17,17,17,.90);color:#ddd;border-radius:7px;padding:8px 10px;box-shadow:0 2px 8px #0008;font-size:11px}.info-title{font-weight:700;font-size:12px;cursor:pointer;min-height:28px;line-height:28px}.info-body{max-height:var(--status-body-height,40vh);overflow:auto;overscroll-behavior:contain}.info[open] .info-title{margin-bottom:5px}.info-grid{display:grid;grid-template-columns:auto auto;gap:2px 12px}.info-grid span:nth-child(odd){color:#aaa}.info-grid span:nth-child(even){text-align:right}.nav{border-top:1px solid #444;margin-top:6px;padding-top:5px;text-align:right}.nav a{color:#8fc1ff;text-decoration:none}.plane{position:relative;width:24px;height:24px;color:#1367a8;filter:drop-shadow(0 0 1px white) drop-shadow(0 0 1px white);transform-origin:50% 50%}.plane svg{display:block;width:24px;height:24px;fill:currentColor}.plane.military{color:#22a447}.plane.closest{filter:drop-shadow(0 0 1px white) drop-shadow(0 0 1px white) drop-shadow(0 0 4px #f33) drop-shadow(0 0 7px #f33)}.plane.destination::after,.plane.origin::after{position:absolute;right:-7px;top:-7px;font:700 9px/13px system-ui;color:#111;background:#ffd166;border:1px solid #7a5a00;border-radius:50%;width:13px;height:13px;text-align:center;transform:rotate(var(--counter-rotation,0deg))}.plane.destination::after{content:"D"}.plane.origin::after{content:"O"}.plane.origin.destination::after{content:"O/D";width:21px;right:-11px;border-radius:7px}.leaflet-popup-content{min-width:190px}.ac-title{font-weight:700;font-size:15px}.ac-flags{margin-top:4px;color:#b22;font-size:11px}.ac-grid{margin-top:6px;display:grid;grid-template-columns:auto auto;gap:2px 10px}.ac-grid span:nth-child(odd){color:#666}.home-marker{width:28px;height:28px;filter:drop-shadow(0 0 2px white) drop-shadow(0 0 2px white)}.home-marker svg{display:block;width:28px;height:28px}.trackbox{display:none;position:static;min-width:0;background:rgba(17,17,17,.90);color:#eee;border-radius:7px;padding:7px 8px;box-shadow:0 2px 8px #0008;font-size:11px}.trackbox input{width:78px;background:#222;color:#eee;border:1px solid #666;border-radius:4px;padding:4px;text-transform:uppercase}.trackbox .btn{padding:4px 6px}.track-status{margin-left:5px;color:#bbb}
@media (max-width:900px),(max-height:600px){.topbar{left:60px;right:10px;top:10px;transform:none;max-width:none;width:auto;gap:5px 8px;padding:7px 9px}.topbar strong{min-width:0}.bottom-dock{left:8px;right:8px}.info{min-width:0}.track-status{overflow-wrap:anywhere}}
@media (max-width:600px){.toolbar-main{justify-content:flex-start}.analysis-row{grid-template-columns:minmax(0,1fr)}.info-grid{grid-template-columns:minmax(0,1fr) auto}.info-grid span{overflow-wrap:anywhere}}

</style></head><body><div id="map"></div><div class="topbar"><div class="toolbar-main"><strong>__SOURCE_TITLE__</strong><span id="stats" class="stats">Loading aircraft…</span><button class="btn" id="fit">Fit aircraft</button><button class="btn" id="density-refresh" hidden>Refresh density</button><label style="font-size:12px"><input id="density-toggle" type="checkbox"> Traffic Density</label><span id="density-state" style="font-size:11px"></span><label id="range-control" style="font-size:12px"><input id="range-toggle" type="checkbox" checked> Range ring</label></div><div class="analysis-row"><details id="density-options" class="analysis-controls" hidden><summary>Density altitude selection</summary><div class="analysis-body"><label><input class="density-band" value="low" type="checkbox"> Low &lt; 1,200 ft</label><label><input class="density-band" value="middle" type="checkbox"> Middle 1,200–17,999 ft</label><label><input class="density-band" value="high" type="checkbox"> High ≥ 18,000 ft</label><label><input class="density-band" value="all" type="checkbox" checked> All Traffic (includes Unknown)</label></div></details><details id="envelope-control" class="analysis-controls"><summary>Density envelopes · comparison</summary><div class="analysis-body"><span>30 days · cell centers · 0.5° bearings</span><button class="btn" id="envelope-generate">Generate envelopes</button><label style="color:#33d6dc"><input class="envelope-band" value="all" type="checkbox"> All</label><label style="color:#59d86b"><input class="envelope-band" value="low" type="checkbox" checked> Low</label><label style="color:#ffaa33"><input class="envelope-band" value="middle" type="checkbox" checked> Middle</label><label style="color:#ca8cff"><input class="envelope-band" value="high" type="checkbox" checked> High</label><span id="envelope-state">Generate on demand; existing range ring remains authoritative.</span></div></details></div></div><div class="bottom-dock"><div id="trackbox" class="trackbox"><input id="trackhex" maxlength="6" placeholder="ICAO hex"><button class="btn" id="trackshow">Track</button><button class="btn" id="trackclear">Clear</button><span id="trackstatus" class="track-status"></span></div><details id="bridge-info" class="info" open><summary class="info-title">Bridge status</summary><div class="info-body"><div id="info-grid" class="info-grid"><span>Feed</span><span>Loading…</span></div><div class="nav"><a href="status-page">Status</a> · <a href="data/aircraft.json">aircraft.json</a></div></div></details></div>
<script id="overlay-layout">
(()=>{
  const info=document.getElementById('bridge-info'),body=info.querySelector('.info-body'),summary=info.querySelector('summary'),bar=document.querySelector('.topbar'),dock=document.querySelector('.bottom-dock'),track=document.getElementById('trackbox'),surface=document.getElementById('map');
  const compact=window.matchMedia('(max-width:900px), (max-height:600px)');
  info.open=!compact.matches;
  function layout(){
    const bounds=surface.getBoundingClientRect(),top=bar.getBoundingClientRect(),panel=info.getBoundingClientRect(),trail=track.getBoundingClientRect();
    const zoom=document.querySelector('.leaflet-control-zoom'),zoomBottom=zoom?zoom.getBoundingClientRect().bottom:bounds.top+74;
    const stacked=trail.height>0&&trail.bottom<=panel.top+1;
    const chrome=summary.getBoundingClientRect().height+16+(info.open?5:0);
    const bottom=Number.parseFloat(getComputedStyle(dock).bottom)||28;
    const maximum=Math.max(0,Math.floor(bounds.bottom-bottom-Math.max(top.bottom,zoomBottom)-10-chrome-(stacked?trail.height+8:0)));
    const height=maximum+'px';if(body.style.getPropertyValue('--status-body-height')!==height)body.style.setProperty('--status-body-height',height);
  }
  let pending=false;function schedule(){if(!pending){pending=true;requestAnimationFrame(()=>{pending=false;layout()})}}
  info.addEventListener('toggle',schedule);window.addEventListener('resize',schedule);window.addEventListener('orientationchange',schedule);
  if(compact.addEventListener)compact.addEventListener('change',()=>{info.open=!compact.matches;schedule()});else compact.addListener(()=>{info.open=!compact.matches;schedule()});
  if(window.ResizeObserver){const observer=new ResizeObserver(schedule);for(const element of[bar,dock,track,surface])observer.observe(element)}
  schedule();
})();
</script>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
(()=>{const map=L.map('map',{zoomControl:true}).setView([39.5,-98.35],4);for(const control of document.querySelectorAll('.topbar,.bottom-dock')){L.DomEvent.disableClickPropagation(control);L.DomEvent.disableScrollPropagation(control)}const tileTemplate='tiles/{z}/{x}/{y}.png?ref_origin='+encodeURIComponent(window.location.origin);const tiles=L.tileLayer(tileTemplate,{maxZoom:19,tileSize:256,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});tiles.on('tileerror',e=>console.warn('FR24 tile proxy error',e?.tile?.src||e));tiles.addTo(map);const markers=new Map();let homeMarker=null,homeCircle=null,coverageLine=null,trackLine=null,homeLatLng=null;let initialFit=false,lastBounds=null,maxObservedRange=null;let enrichment={available:false,tracker_state:'awaiting',closest_hex:null,military_hexes:[],origin_hexes:[],destination_hexes:[],aircraft:{}};const rangeToggle=document.getElementById('range-toggle');rangeToggle.addEventListener('change',()=>{if(!rangeToggle.checked&&coverageLine){map.removeLayer(coverageLine);coverageLine=null}if(rangeToggle.checked)refreshCoverage()});let inputSource=null,coverageOutlineEnabled=false;let destinationAirport=null,enrichmentSource='adsb_tracker',trackHistoryAvailable=false;const statsEl=document.getElementById('stats'),infoEl=document.getElementById('info-grid'),trackBox=document.getElementById('trackbox'),trackStatus=document.getElementById('trackstatus');const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const fmt=(v,s='')=>(v===undefined||v===null||v==='')?'—':`${esc(v)}${s}`;const altitude=v=>v==='ground'?'Ground':(v===undefined||v===null?'—':`${Number(v).toLocaleString()} ft`);const signed=v=>(v===undefined||v===null)?'—':`${Number(v)>0?'+':''}${Number(v).toLocaleString()} ft/min`;const duration=v=>{v=Number(v);if(!Number.isFinite(v))return '—';const h=Math.floor(v/3600),m=Math.floor((v%3600)/60);return h?`${h}h ${m}m`:`${m}m`};
function flagsFor(key,ac={}){const military=new Set(enrichment.military_hexes||[]),origin=new Set(enrichment.origin_hexes||[]),destination=new Set(enrichment.destination_hexes||[]);return{military:military.has(key),closest:enrichment.closest_hex===key,origin:inputSource==='swim_tfms'?airportMatches(ac.route_origin,destinationAirport):origin.has(key),destination:inputSource==='swim_tfms'?airportMatches(ac.route_destination,destinationAirport):destination.has(key)}}
function airportMatches(a,b){return !!a&&!!b&&String(a).trim().toUpperCase()===String(b).trim().toUpperCase()}
function cardinalDirection(degrees){if(degrees===null||degrees===undefined||degrees==='')return '';const d=Number(degrees);if(!Number.isFinite(d))return '';const dirs=['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];return dirs[Math.floor((((d%360)+360)%360+11.25)/22.5)%16]}
function trackerFor(key){return(enrichment.aircraft||{})[key]||{}}
function bearing(a,b){const r=Math.PI/180,p1=a.lat*r,p2=b.lat*r,dl=(b.lon-a.lon)*r,y=Math.sin(dl)*Math.cos(p2),x=Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl);return(Math.atan2(y,x)/r+360)%360}
function distanceM(a,b){const r=Math.PI/180,R=6371000,p1=a.lat*r,p2=b.lat*r,dp=(b.lat-a.lat)*r,dl=(b.lon-a.lon)*r,h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.asin(Math.sqrt(h))}
const motion=new Map();
function displayTrack(key,ac,lat,lon){const now=Date.now(),cur={lat,lon,t:now},prev=motion.get(key);let d=Number(ac.track),source=Number.isFinite(d)?'reported':'none';if(prev){const moved=distanceM(prev,cur);if(moved>=40){d=bearing(prev,cur);source='calculated';motion.set(key,cur)}else if(now-prev.t>15000){motion.set(key,cur)}}else motion.set(key,cur);return{degrees:Number.isFinite(d)?d:null,source}}
function popup(ac,flags,key,orientation){const t=trackerFor(key),title=(t.flight||ac.flight||'').trim()||ac.hex.toUpperCase(),tail=t.tail&&t.tail!=='Unknown'?t.tail:null,type=[t.aircraft_type,t.description&&t.description!=='Unknown aircraft'?t.description:null].filter(Boolean).join(' · '),badges=[];if(flags.military)badges.push('MILITARY');if(flags.closest)badges.push('CLOSEST');if(flags.origin)badges.push(`ORIGIN: ${destinationAirport}`);if(flags.destination)badges.push(`DESTINATION: ${destinationAirport}`);const route=(t.route_origin||t.route_destination)?`${esc(t.route_origin||'—')}${t.route_origin_name?` (${esc(t.route_origin_name)})`:''} → ${esc(t.route_destination||'—')}${t.route_destination_name?` (${esc(t.route_destination_name)})`:''}`:null;const enriched=[tail?`<span>Registration</span><b>${esc(tail)}</b>`:'',type?`<span>Aircraft</span><b>${esc(type)}</b>`:'',route?`<span>Route</span><b>${route}</b>`:'',t.distance_display?`<span>Distance</span><b>${esc(t.distance_display)}</b>`:''].join('');const tfmsMeta=['airline','route_origin','route_destination','aircraft_category','user_category','arrival_time','position_time','assigned_altitude_raw'].filter(k=>ac[k]).map(k=>'<span>'+esc(k.replaceAll('_',' '))+'</span><b>'+esc(ac[k])+'</b>').join('');const badgeHtml=badges.length?`<div class="ac-flags">${badges.map(x=>`<b>${esc(x)}</b>`).join(' · ')}</div>`:'';const trackText=orientation.degrees==null?'—':`${orientation.degrees.toFixed(1)}° (${cardinalDirection(orientation.degrees)})${(orientation.source==='calculated'||ac.track_source==='calculated')?' (course)':''}`;return `<div class="ac-title">${esc(title)}</div>${badgeHtml}<div class="ac-grid">${enriched}${tfmsMeta}<span>ICAO</span><b>${esc(ac.hex.toUpperCase())}</b><span>Altitude</span><b>${altitude(ac.alt_baro)}</b><span>Ground speed</span><b>${fmt(ac.gs,' kt')}</b><span>Track/course</span><b>${trackText}</b><span>Vertical rate</span><b>${signed(ac.baro_rate)}</b><span>Squawk</span><b>${fmt(ac.squawk)}</b><span>Last message</span><b>${fmt(ac.seen,' sec')}</b><span>Last position</span><b>${fmt(ac.seen_pos,' sec')}</b></div>`}
function icon(track,flags){const d=Number.isFinite(Number(track))?Number(track):0,visual=d,classes=['plane'];if(flags.military)classes.push('military');if(flags.closest)classes.push('closest');if(flags.origin)classes.push('origin');if(flags.destination)classes.push('destination');const planeSvg='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1.5 14.2 9l6.8 4v2l-6.8-1.8-.7 5.2 2.5 1.8v1.5L12 20.5 8 21.7v-1.5l2.5-1.8-.7-5.2L3 15v-2l6.8-4L12 1.5Z"/></svg>';return L.divIcon({className:'',html:`<div class="${classes.join(' ')}" style="transform:rotate(${visual}deg);--counter-rotation:${-visual}deg">${planeSvg}</div>`,iconSize:[24,24],iconAnchor:[12,12]})}
function stabilizeMap(){requestAnimationFrame(()=>requestAnimationFrame(()=>{map.invalidateSize({animate:false,pan:false});if(coverageLine)coverageLine.redraw();if(trackLine)trackLine.redraw()}))}function fitAircraft(){if(lastBounds&&lastBounds.isValid()){map.invalidateSize({animate:false,pan:false});map.fitBounds(lastBounds.pad(.08),{maxZoom:10,animate:false});stabilizeMap()}}document.getElementById('fit').addEventListener('click',fitAircraft);const mapContainer=document.getElementById('map');if(window.ResizeObserver)new ResizeObserver(()=>stabilizeMap()).observe(mapContainer);document.addEventListener('visibilitychange',()=>{if(!document.hidden)stabilizeMap()});window.addEventListener('pageshow',stabilizeMap);window.addEventListener('focus',stabilizeMap);map.on('zoomend moveend',()=>{if(coverageLine)coverageLine.redraw();if(trackLine)trackLine.redraw()});
function trackerLabel(){if(enrichmentSource==='none')return 'Disabled';const state=enrichment.tracker_state||(enrichment.available?'active':'awaiting');return state==='active'?'Detected / active':(state==='unavailable'?'Temporarily unavailable':'Awaiting detection')}
function renderInfo(s){if(!s){infoEl.innerHTML='<span>Status</span><span class="bad">Unavailable</span>';return}const cls=s.feed_status==='ok'?'ok':(s.feed_status==='degraded'?'degraded':'bad');const rows=[['Build',esc(s.build_version)],['Feed',`<b class="${cls}">${esc(String(s.feed_status||'unknown').toUpperCase())}</b>`],['Source',esc(s.source)],['Receiver',esc(s.receiver)],['Messages',s.messages_received!=null?Number(s.messages_received).toLocaleString():'—'],['Message rate',s.message_rate_per_second!=null?`${esc(s.message_rate_per_second)} / sec`:'—'],['Aircraft',esc(s.aircraft_total)],['With position',esc(s.aircraft_with_position)],['Without position',esc(s.aircraft_without_position)],['Max range',maxObservedRange!=null?`${maxObservedRange.toFixed(1)} NM`:'—'],['Parse errors',s.parse_errors!=null?esc(s.parse_errors):'—'],['Reconnects',s.reconnections!=null?esc(s.reconnections):'—'],['Tracker',trackerLabel()],['O/D airport',destinationAirport||'—'],['Uptime',duration(s.uptime_seconds)]];infoEl.innerHTML=rows.map(([k,v])=>`<span>${esc(k)}</span><span>${v}</span>`).join('')}
function homeIcon(){const svg='<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M3 15.5 16 4l13 11.5-2.7 3L16 9.4 5.7 18.5Z" fill="#e35b4f" stroke="#fff" stroke-width="1.2"/><path d="M7.5 16.8 16 9.5l8.5 7.3V28h-6v-7h-5v7h-6Z" fill="#f2d6a2" stroke="#555" stroke-width="1"/></svg>';return L.divIcon({className:'',html:`<div class="home-marker">${svg}</div>`,iconSize:[28,28],iconAnchor:[14,24]})}
async function refreshHome(){try{const r=await fetch('map-config',{cache:'no-store'});if(!r.ok)return;const c=await r.json(),h=c?.home;inputSource=c?.source||null;coverageOutlineEnabled=c?.coverage_outline_enabled===true;document.getElementById('range-control').style.display=coverageOutlineEnabled?'':'none';rangeToggle.disabled=!coverageOutlineEnabled;document.getElementById('envelope-control').hidden=!coverageOutlineEnabled;if(!coverageOutlineEnabled)envelopeLayers.clearLayers();if(c?.title){document.title=c.title;document.querySelector('.topbar strong').textContent=c.title}if(!coverageOutlineEnabled&&coverageLine){map.removeLayer(coverageLine);coverageLine=null;maxObservedRange=null;}destinationAirport=c?.destination_airport||null;enrichmentSource=c?.enrichment_source||'adsb_tracker';trackHistoryAvailable=!!c?.track_history_available;document.getElementById('trackhex').dataset.query=c?.track_history_query||'hex';document.getElementById('trackhex').placeholder=c?.track_history_query==='callsign'?'Flight callsign':'ICAO hex';document.getElementById('trackhex').maxLength=c?.track_history_query==='callsign'?16:6;trackBox.style.display=trackHistoryAvailable?'block':'none';if(!h)return;const lat=Number(h.latitude),lon=Number(h.longitude),radius=Number(h.radius||0);if(!Number.isFinite(lat)||!Number.isFinite(lon))return;homeLatLng={lat,lon};if(!homeMarker)homeMarker=L.marker([lat,lon],{icon:homeIcon(),zIndexOffset:1000}).addTo(map).bindPopup('<b>Home</b>');else homeMarker.setLatLng([lat,lon]);if(radius>0){if(!homeCircle)homeCircle=L.circle([lat,lon],{radius,weight:1,fillOpacity:.05}).addTo(map);else{homeCircle.setLatLng([lat,lon]);homeCircle.setRadius(radius)}}}catch(err){console.warn('Home marker unavailable',err)}}
async function refreshEnrichment(){try{const r=await fetch('tracker-enrichment',{cache:'no-store'});if(r.ok)enrichment=await r.json()}catch(err){enrichment={available:false,tracker_state:'awaiting',closest_hex:null,military_hexes:[],origin_hexes:[],destination_hexes:[],aircraft:{}}}}
function destinationPoint(origin,bearingDeg,distanceNm){const R=3440.065,d=distanceNm/R,t=bearingDeg*Math.PI/180,p1=origin.lat*Math.PI/180,l1=origin.lon*Math.PI/180;const p2=Math.asin(Math.sin(p1)*Math.cos(d)+Math.cos(p1)*Math.sin(d)*Math.cos(t));const l2=l1+Math.atan2(Math.sin(t)*Math.sin(d)*Math.cos(p1),Math.cos(d)-Math.sin(p1)*Math.sin(p2));return[p2*180/Math.PI,((l2*180/Math.PI+540)%360)-180]}


const densityLayer=L.layerGroup(),densityRenderer=L.canvas({padding:.2});let densitySequence=0,densityController=null,densityTimer=null;
const densityToggle=document.getElementById('density-toggle'),densityState=document.getElementById('density-state');
const bandInputs=[...document.querySelectorAll('.density-band')];
function densitySelection(){const selected=bandInputs.filter(x=>x.checked).map(x=>x.value);return selected.includes('all')?'all':selected.join(',')||'none'}
for(const input of bandInputs)input.addEventListener('change',()=>{if(input.checked){for(const other of bandInputs){if(input.value==='all'||other.value==='all')if(other!==input)other.checked=false}}markDensityChanged()});
const envelopeLayers=L.layerGroup().addTo(map);let envelopeData=null;
const envelopeColors={all:'#33d6dc',low:'#59d86b',middle:'#ffaa33',high:'#ca8cff'};
function renderEnvelopes(){envelopeLayers.clearLayers();if(!envelopeData||!coverageOutlineEnabled)return;for(const input of document.querySelectorAll('.envelope-band')){if(!input.checked)continue;const product=envelopeData.products[input.value];const segments=product.envelope_segments.map(run=>run.map(p=>[p[1],p[0]]));if(segments.length)L.polyline(segments,{color:envelopeColors[input.value],weight:3,opacity:.8,dashArray:'6 4',interactive:false}).addTo(envelopeLayers)}}
for(const input of document.querySelectorAll('.envelope-band'))input.addEventListener('change',renderEnvelopes);
document.getElementById('envelope-generate').addEventListener('click',async()=>{const out=document.getElementById('envelope-state'),button=document.getElementById('envelope-generate');button.disabled=true;out.textContent='Generating comparison…';try{const r=await fetch('traffic-density/envelopes',{cache:'no-store'}),data=await r.json();if(!r.ok)throw new Error(data.error||'Generation failed');envelopeData=data;renderEnvelopes();out.textContent=(data.cached?'Cached':'Generated')+' '+data.generated_at+' · '+data.window.start+' – '+data.window.end+' · '+Object.entries(data.products).map(([band,p])=>band+': '+p.populated_bins+'/720').join(' · ')}catch(e){out.textContent=e.message}finally{button.disabled=false}});
let densityInFlight=false,densityViewRevision=0;
async function refreshDensity(periodic=false){
  if(periodic&&densityInFlight)return;
  const viewRevision=densityViewRevision;
  const sequence=++densitySequence;if(densityController)densityController.abort();
  document.getElementById('density-options').hidden=!densityToggle.checked;
  document.getElementById('density-refresh').hidden=!densityToggle.checked;
  if(!densityToggle.checked){densityLayer.clearLayers();densityState.textContent='';return}
  const selection=densitySelection();if(selection==='none'){densityLayer.clearLayers();densityState.textContent='Select altitude bands';return}
  densityController=new AbortController();densityInFlight=true;densityState.textContent='Loading…';
  const requestController=densityController,started=performance.now();
  const timeout=setTimeout(()=>requestController.abort('timeout'),120000);
  try{const b=map.getBounds(),west=Math.max(-180,b.getWest()),east=Math.min(180,b.getEast()),south=Math.max(-90,b.getSouth()),north=Math.min(90,b.getNorth());
    const z=Math.max(0,Math.min(17,Math.floor(map.getZoom())+3));let query='max_cells=6000&zoom='+z+'&bands='+encodeURIComponent(selection);
    if(west<=east)query+='&bbox='+[west,south,east,north].join(',');
    const r=await fetch('traffic-density.geojson?'+query,{cache:'no-store',signal:densityController.signal});
    const data=await r.json();if(!r.ok)throw new Error(data.error||'Density unavailable');if(sequence!==densitySequence||!densityToggle.checked)return;
    densityLayer.clearLayers();const maximum=data.features.reduce((maximum,f)=>Math.max(maximum,f.properties.selected_observation_count),1);
    L.geoJSON(data,{style:f=>{const t=Math.log1p(f.properties.selected_observation_count)/Math.log1p(maximum);return{renderer:densityRenderer,stroke:false,fillOpacity:.2+.5*t,fillColor:'hsl('+Math.round(240*(1-t))+',90%,50%)'}},onEachFeature:(f,l)=>{const p=f.properties,a=p.altitude;l.bindPopup('<b>Traffic Density</b><br>'+esc(p.cell_id)+'<br>'+Number(p.selected_observation_count).toLocaleString()+' selected observations ('+Number(p.observation_count).toLocaleString()+' all-band) · '+Number(p.passage_count).toLocaleString()+(data.window.display_zoom<17?' all-band base-cell passages<br>Low: ':' all-band passages<br>Low: ')+a.below_1200_ft+' · Middle: '+a['1200_to_17999_ft']+'<br>High: '+a['18000_ft_and_above']+' · Unknown: '+a.unknown+'<br>'+esc(data.window.start)+' – '+esc(data.window.end)+' (UTC)<br>'+(p.history_complete?'History start known':'History start uncertain'))}}).addTo(densityLayer);
    densityState.textContent='30 days · '+(selection==='all'?'All Traffic':selection.replaceAll(',', ' + '))+' · '+data.features.length.toLocaleString()+' cells · grid z'+data.window.display_zoom+' · '+((performance.now()-started)/1000).toFixed(1)+'s · blue → red'+(viewRevision!==densityViewRevision?' · Changed — refresh density':'');
  }catch(e){if(sequence===densitySequence){densityState.textContent=requestController.signal.reason==='timeout'?'Density request timed out after 120s':('Unavailable: '+e.message);console.warn('Traffic density',e)}}finally{clearTimeout(timeout);if(sequence===densitySequence)densityInFlight=false}
}
densityToggle.addEventListener('change',()=>{if(densityToggle.checked)densityLayer.addTo(map);else map.removeLayer(densityLayer);refreshDensity()});
function markDensityChanged(){densityViewRevision++;if(densityToggle.checked)densityState.textContent='Changed — refresh density';}
map.on('moveend zoomend',markDensityChanged);
document.getElementById('density-refresh').addEventListener('click',()=>refreshDensity());

async function refreshCoverage(){if(!coverageOutlineEnabled||!rangeToggle.checked)return;try{const r=await fetch('range-coverage',{cache:'no-store'});if(!r.ok)return;const c=await r.json(),bins=Array.isArray(c.bins)?c.bins:[];const ranges=bins.map(x=>Number(x.distance_nm)).filter(Number.isFinite);maxObservedRange=ranges.length?Math.max(...ranges):null;const segs=(Array.isArray(c.envelope_segments)?c.envelope_segments:[]).map(run=>run.map(p=>[p[1],p[0]]));if(!rangeToggle.checked)return;if(segs.length){if(!coverageLine)coverageLine=L.polyline(segs,{color:'#ff1c1c',weight:2,opacity:.85,interactive:false,noClip:true}).addTo(map);else coverageLine.setLatLngs(segs);coverageLine.redraw()}else if(coverageLine){map.removeLayer(coverageLine);coverageLine=null}}catch(err){console.warn('Coverage outline unavailable',err)}}
function clearTrack(){if(trackLine){map.removeLayer(trackLine);trackLine=null}trackStatus.textContent=''}
async function showTrack(){const hex=document.getElementById('trackhex').value.trim().toLowerCase();const queryType=document.getElementById('trackhex').dataset.query||'hex';if(!(queryType==='callsign'?/^[a-z0-9]{1,16}$/:/^[0-9a-f]{6}$/).test(hex)){trackStatus.textContent=queryType==='callsign'?'Flight callsign required':'6-digit hex required';return}trackStatus.textContent='Loading…';try{const r=await fetch(`track-history?${queryType}=${encodeURIComponent(hex)}`,{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);const fields=Array.isArray(d.trail_fields)?d.trail_fields:[],ilat=fields.indexOf('lat'),ilon=fields.indexOf('lon'),pts=(Array.isArray(d.trail)?d.trail:[]).map(row=>[Number(row[ilat]),Number(row[ilon])]).filter(p=>Number.isFinite(p[0])&&Number.isFinite(p[1]));clearTrack();if(pts.length<1){trackStatus.textContent='No positions';return}trackLine=L.polyline(pts,{weight:4,opacity:.75,interactive:false}).addTo(map);trackStatus.textContent=`${(d.callsign||d.query||hex).toUpperCase()} · ${pts.length} positions`;trackLine.bringToFront();stabilizeMap()}catch(err){trackStatus.textContent=err.message}}
document.getElementById('trackshow').addEventListener('click',showTrack);document.getElementById('trackclear').addEventListener('click',clearTrack);document.getElementById('trackhex').addEventListener('keydown',e=>{if(e.key==='Enter')showTrack()});
async function refresh(){try{const [ar,sr,er]=await Promise.all([fetch('data/aircraft.json',{cache:'no-store'}),fetch('status',{cache:'no-store'}),fetch('tracker-enrichment',{cache:'no-store'})]);if(er.ok)enrichment=await er.json();else enrichment={available:false,tracker_state:'awaiting',closest_hex:null,military_hexes:[],origin_hexes:[],destination_hexes:[],aircraft:{}};if(!ar.ok)throw new Error(`aircraft.json HTTP ${ar.status}`);const data=await ar.json(),status=sr.ok?await sr.json():null,active=new Set(),points=[];for(const ac of(data.aircraft||[])){const lat=Number(ac.lat),lon=Number(ac.lon);if(!Number.isFinite(lat)||!Number.isFinite(lon))continue;const key=String(ac.hex||'').toLowerCase();if(!key)continue;active.add(key);points.push([lat,lon]);const flags=flagsFor(key,ac),orientation=displayTrack(key,ac,lat,lon);let m=markers.get(key);if(!m){m=L.marker([lat,lon],{icon:icon(orientation.degrees,flags)}).addTo(map);m.bindPopup(popup(ac,flags,key,orientation),{autoPan:false});markers.set(key,m)}else{m.setLatLng([lat,lon]);m.setIcon(icon(orientation.degrees,flags));if(m.getPopup())m.setPopupContent(popup(ac,flags,key,orientation));else m.bindPopup(popup(ac,flags,key,orientation),{autoPan:false})}}for(const [key,m]of markers)if(!active.has(key)){map.removeLayer(m);markers.delete(key)}lastBounds=points.length?L.latLngBounds(points):null;if(!initialFit&&points.length){fitAircraft();initialFit=true}const total=status?.aircraft_total??(data.aircraft||[]).length,rate=status?.message_rate_per_second,feed=status?.feed_status||'unknown';statsEl.innerHTML=`<span class="${feed==='ok'?'ok':(feed==='degraded'?'degraded':'bad')}">${esc(feed.toUpperCase())}</span> · ${points.length} positioned / ${total} total${rate!=null?` · ${esc(rate)} msg/sec`:''}`;renderInfo(status)}catch(err){statsEl.innerHTML=`<span class="bad">MAP DATA ERROR</span> · ${esc(err.message)}`}}refreshHome();setInterval(refreshHome,300000);refreshCoverage();setInterval(refreshCoverage,5000);refresh();setInterval(refresh,1000)})();
</script></body></html>
'''

class Handler(BaseHTTPRequestHandler):
    def _operation(self, method):
        path, _, raw_query = self.path.partition('?')
        query = parse_qs(raw_query)
        datasets = {'/traffic-density/import': 'traffic-density', '/range-coverage/import': 'range-coverage',
                    '/data/clear': 'collected-data', '/traffic-density/export': 'traffic-density',
                    '/traffic-density.geojson': 'traffic-density', '/range-coverage': 'range-coverage',
                    '/range-coverage.geojson': 'range-coverage', '/range-coverage-baseline': 'range-baseline',
                    '/traffic-density/envelopes': 'density-envelopes', '/traffic-density/envelopes.geojson': 'density-envelopes'}
        if path not in datasets:
            return None
        if method == 'POST':
            if path not in ('/traffic-density/import','/range-coverage/import','/data/clear'):
                return None
            action = 'clear' if path == '/data/clear' else 'import'
        else:
            if path.endswith('/import') or path == '/data/clear':
                return None
            if path == '/range-coverage' and query.get('download') != ['1']:
                return None  # The live map polls this endpoint every five seconds.
            if path == '/traffic-density.geojson' and ('bbox' in query or 'max_cells' in query):
                return None  # Interactive heat-map queries have their own timing logs.
            action = 'generate' if path == '/traffic-density/envelopes' and query.get('download') != ['1'] else 'export'
        return {'action':action, 'dataset':datasets[path], 'source':CFG['source']}

    def _run_operation(self, method, handler):
        self.operation_details = self._operation(method)
        self.operation_status = None
        started = time.monotonic()
        failure = None
        if self.operation_details:
            print('[INFO] Data operation ' + json.dumps({**self.operation_details, 'phase':'started', 'timestamp':iso_utc(time.time())}), flush=True)
        try:
            handler()
        except (BrokenPipeError, ConnectionResetError) as exc:
            failure = type(exc).__name__
        except Exception as exc:
            failure = type(exc).__name__
            raise
        finally:
            if self.operation_details:
                status = self.operation_status
                result = 'aborted' if failure in ('BrokenPipeError','ConnectionResetError') else ('failed' if failure or status is None or status >= 400 else 'completed')
                record = {**self.operation_details, 'phase':result, 'timestamp':iso_utc(time.time()),
                          'seconds':round(time.monotonic()-started,3), 'http_status':status}
                if failure: record['error_type'] = failure
                print(('[INFO]' if result=='completed' else '[WARN]')+' Data operation '+json.dumps(record), flush=True)
            self.operation_details = None

    def do_POST(self):
        self._run_operation('POST', self._do_POST)

    def do_GET(self):
        self._run_operation('GET', self._do_GET)

    def send_response(self, code, message=None):
        self.operation_status = code
        super().send_response(code, message)

    def log_message(self, fmt, *args):
        return

    def send_json(self, payload, code=200, filename=None):
        body = json.dumps(payload, indent=2).encode("utf-8")
        details = getattr(self, 'operation_details', None)
        if details and isinstance(payload, dict):
            for key in ('added','replaced','retained','received','ignored_months','populated_bins','total_bins','pending'):
                value = payload.get(key)
                if isinstance(value, int): details[key] = value
            if isinstance(payload.get('features'), list): details['features'] = len(payload['features'])
            if isinstance(payload.get('cleared'), list): details['cleared'] = payload['cleared']
            details['response_bytes'] = len(body)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, filename, content_type="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        details = getattr(self, 'operation_details', None)
        if details: details['response_bytes'] = path.stat().st_size
        with path.open("rb") as file:
            shutil.copyfileobj(file, self.wfile, length=65536)

    def send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_tile(self, body, meta):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("X-FR24-Tile-Proxy", TILE_PROXY_BUILD)
        self.send_header("Cache-Control", meta.get("cache_control") or "public, max-age=604800")
        if meta.get("etag"):
            self.send_header("ETag", meta["etag"])
        if meta.get("last_modified"):
            self.send_header("Last-Modified", meta["last_modified"])
        if meta.get("expires"):
            self.send_header("Expires", meta["expires"])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _do_POST(self):
        path, _, _query_string = self.path.partition("?")
        if path.startswith("/settings/"):
            settings_post(self, path)
            return
        if path == "/data/clear":
            try:
                if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                    raise ValueError('clear requires application/json')
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 1024:
                    raise ValueError('invalid clear request')
                request = json.loads(self.rfile.read(length))
                target = request.get('target')
                if target in ('density','range','all'): self.operation_details['target'] = target
                expected = 'CLEAR ALL' if target=='all' else 'CLEAR'
                if target not in ('density','range','all') or request.get('confirmation') != expected:
                    raise ValueError('explicit confirmation required')
                if density_store is None and target in ('density','all'):
                    raise ValueError('density storage unavailable; resolve its startup error first')
                cleared=[]
                if target in ('density','all'):
                    density_store.clear(); cleared.append('current source traffic density')
                if target=='all':
                    root = Path(os.environ.get('FR24_DENSITY_PATH','/data/traffic-density'))
                    # Only known source directories, never configuration or arbitrary paths.
                    for source in VALID_SOURCES:
                        folder=root/source
                        if folder.exists() and folder.resolve()!=density_store.directory.resolve():
                            with_store=DensityStore(folder,source_type=source)
                            try: with_store.clear()
                            finally: with_store.close()
                    cleared.append('other source traffic density')
                if target in ('range','all'):
                    clear_coverage(); cleared.append('range coverage and legacy baseline')
                self.send_json({'ok':True,'cleared':cleared})
            except (ValueError,TypeError) as exc:
                self.send_json({'error':str(exc)},400)
            except Exception as exc:
                print(f'[WARN] Clear data failed: {exc}',flush=True)
                self.send_json({'error':'Clear failed; inspect App logs before retrying.'},500)
            return
        if path == "/traffic-density/import":
            if density_store is None:
                self.send_json({"error": "traffic density unavailable"}, 503)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                self.operation_details["input_bytes"] = max(0,length)
                if length <= 0:
                    raise ValueError("density import requires Content-Length")
                legacy_source = parse_qs(_query_string).get("legacy_source", [None])[0]
                self.send_json({"ok": True, **restore_stream(density_store, self.rfile, length, legacy_source)})
            except (UnicodeDecodeError, ValueError, TypeError, KeyError, OverflowError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:
                print(f"[WARN] Density restore failed: {exc}", flush=True)
                self.send_json({"ok": False, "error": "Restore failed; monthly chunks commit independently. Re-export and inspect before retrying."}, 500)
            return
        if path == "/range-coverage/import" and CFG["source"] == "swim_tfms":
            self.send_json({"error": "Range coverage is disabled for FAA TFMS"}, 404)
            return
        if path != "/range-coverage/import":
            self.send_json({"error": "not found", "path": path}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        self.operation_details["input_bytes"] = max(0,length)
        if length <= 0 or length > 2 * 1024 * 1024:
            self.send_json({"error": "coverage import must be a JSON body no larger than 2 MiB"}, 400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if payload.get("source_type") not in (None, CFG["source"]):
                raise ValueError("Backup source does not match the selected source")
            result = import_coverage_payload(payload)
            print(f"[INFO] Coverage import complete: {result['added']} added, {result['replaced']} replaced, {result['retained']} retained", flush=True)
            self.send_json({"ok": True, **result})
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            print(f"[WARN] Coverage import failed: {exc}", flush=True)
            self.send_json({"ok": False, "error": "coverage import failed"}, 500)

    def _do_GET(self):
        global requests_served, tile_proxy_requests, tile_proxy_cache_hits
        with lock:
            requests_served += 1
        path, _, query_string = self.path.partition("?")
        if path == "/settings":
            self.send_html(settings_page())
            return
        if path in ("/traffic-density/envelopes", "/traffic-density/envelopes.geojson"):
            if density_store is None:
                self.send_json({"error": density_startup_error or "traffic density unavailable"},503)
                return
            try:
                query = parse_qs(query_string)
                payload = density_envelope_payload(query.get("start",[None])[0],query.get("end",[None])[0])
                if path.endswith(".geojson"):
                    self.send_json(density_envelope_geojson(payload),filename=export_name("density-envelopes","geojson"))
                else:
                    self.send_json(payload,filename=export_name("density-envelopes"))
            except (ValueError,TypeError,KeyError,OverflowError) as exc:
                self.send_json({"error":str(exc)},400)
            except Exception as exc:
                print(f"[WARN] Density envelope request failed: {exc}",flush=True)
                self.send_json({"error":"density envelope generation failed"},500)
            return
        if path in ("/traffic-density", "/traffic-density.geojson", "/traffic-density/export", "/traffic-density/status"):
            if density_store is None:
                self.send_json({"available": False, "error": density_startup_error or "traffic density unavailable"}, 503)
                return
            try:
                if path == "/traffic-density/export":
                    month = parse_qs(query_string).get("month", [None])[0]
                    with archive_file(density_store, month) as file:
                        self.send_file(file, export_name("traffic-density" + ("-"+month if month else "")))
                    return
                elif path == "/traffic-density/status":
                    payload = density_store.status()
                else:
                    query = parse_qs(query_string)
                    options = {"start": query.get("start", [None])[0], "end": query.get("end", [None])[0],
                               "zoom": int(query.get("zoom", [17])[0]), "bands": query.get("bands", ["all"])[0]}
                    if "max_cells" in query:
                        options["max_cells"] = int(query["max_cells"][0])
                    if "bbox" in query:
                        options["bbox"] = [float(v) for v in query["bbox"][0].split(",")]
                    if path.endswith(".geojson") and "bbox" not in options and "max_cells" not in options:
                        with geojson_file(density_store, **options) as file:
                            self.send_file(file, export_name("traffic-density", "geojson"), "application/geo+json")
                        return
                    payload = density_store.geojson(**options) if path.endswith(".geojson") else density_store.query(**options)
                self.send_json(payload)
            except (BrokenPipeError, ConnectionResetError):
                raise
            except (ValueError, TypeError, OverflowError) as exc:
                self.send_json({"error": str(exc)}, 400)
            except Exception as exc:
                print(f"[WARN] Density request failed: {exc}", flush=True)
                self.send_json({"error": "traffic density read failed"}, 500)
            return
        tile_match = re.fullmatch(r"/tiles/(\d+)/(\d+)/(\d+)\.png", path)
        if path == "/tile-debug":
            self.send_json({"build": TILE_PROXY_BUILD, "requests": tile_proxy_requests, "cache_hits": tile_proxy_cache_hits, "upstream_fetches": tile_proxy_upstream_fetches, "blocked": tile_proxy_blocked, "last_error": tile_proxy_last_error, "last_referer": tile_proxy_last_referer})
            return
        if tile_match:
            tile_proxy_requests += 1
            try:
                z, x, y = (int(value) for value in tile_match.groups())
                query = parse_qs(query_string, keep_blank_values=False)
                # Ingress can suppress the browser Referer. The page supplies only its
                # actual origin (never the Ingress path/token), which is what a normal
                # strict-origin cross-site tile request would disclose.
                referer = _valid_web_origin(self.headers.get("Referer"))
                if not referer:
                    referer = _valid_web_origin((query.get("ref_origin") or [None])[0])
                body, meta, _cached = get_map_tile(z, x, y, referer)
                if _cached:
                    tile_proxy_cache_hits += 1
                self.send_tile(body, meta)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
            except TileBlockedError as exc:
                print(f"[WARN] Map tile {path} rejected upstream: {exc}", flush=True)
                self.send_json({"error": "tile upstream rejected request"}, 502)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                print(f"[WARN] Map tile {path} failed: {exc}", flush=True)
                self.send_json({"error": "tile upstream unavailable"}, 502)
            return
        if path == "/map-config":
            self.send_json(map_config())
            return
        if path == "/tracker-enrichment":
            self.send_json(refresh_tracker_enrichment())
            return
        if path == "/track-history":
            tfms = CFG["source"] == "swim_tfms"
            if not CFG["history_url"]:
                self.send_json({"error": "track history is not configured"}, 404)
                return
            query = parse_qs(query_string, keep_blank_values=False)
            query_key = "callsign" if tfms else "hex"
            identity = str((query.get(query_key) or [""])[0]).strip().lower()
            pattern = r"[a-z0-9]{1,16}" if tfms else r"[0-9a-f]{6}"
            if not re.fullmatch(pattern, identity):
                self.send_json({"error": "valid flight callsign required" if tfms else "hex must be a 6-digit ICAO address"}, 400)
                return
            base_url = CFG["history_url"]
            try:
                req = Request(f"{base_url}/flight?{query_key}={quote(identity)}", headers={"User-Agent": "FR24-dump1090-Bridge/0.6.8"})
                with urlopen(req, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.send_json(payload)
            except Exception as exc:
                print(f"[WARN] Track history lookup failed: {exc}", flush=True)
                self.send_json({"error": "track history unavailable"}, 502)
            return
        if path.startswith("/range-coverage") and CFG["source"] == "swim_tfms":
            self.send_json({"error": "Range coverage is disabled for FAA TFMS"}, 404)
            return
        if path == "/range-coverage-baseline":
            with lock:
                baseline = coverage_baseline
            self.send_json({**baseline, "source_type": CFG["source"]} if baseline is not None else {"error": "no 1-degree baseline available"}, 200 if baseline is not None else 404, filename=export_name("range-coverage-1-degree-baseline") if baseline is not None else None)
            return
        if path == "/range-coverage":
            self.send_json({**coverage_payload(), "source_type": CFG["source"]}, filename=export_name("range-coverage"))
            return
        if path == "/range-coverage.geojson":
            self.send_json({**coverage_geojson_payload(), "source_type": CFG["source"]}, filename=export_name("range-coverage", "geojson"))
            return
        if path in ("/aircraft.json", "/data/aircraft.json"):
            with lock:
                payload = latest_data
            self.send_json(payload)
            return
        if path == "/health":
            self.send_json({"service_status": "ok", "uptime_seconds": round(time.time() - START_TIME, 1)})
            return
        if path == "/status":
            self.send_json(snapshot_status())
            return
        if path == "/":
            page = MAP_HTML.replace("__SOURCE_TITLE__", escape(source_title()))
            if CFG["source"] == "swim_tfms":
                page = page.replace('id="envelope-control" class="analysis-controls"', 'id="envelope-control" class="analysis-controls" hidden')
                page = page.replace('id="range-control" style="font-size:12px"', 'id="range-control" style="display:none;font-size:12px"')
            self.send_html(page)
            return
        if path == "/status-page":
            s = snapshot_status()
            common = f"""<!doctype html><html><head><meta charset=\"utf-8\">
<title>{escape(source_title())}</title><style>
body{{font-family:sans-serif;max-width:760px;margin:40px auto;padding:0 20px;background:#111;color:#eee}}
table{{border-collapse:collapse;width:100%}}td{{padding:8px;border-bottom:1px solid #333}}td:first-child{{color:#aaa;width:45%}}
a{{color:#7db7ff}}button{{margin:4px 8px 4px 0;padding:7px 10px}}input[type=file]{{max-width:100%}}#coverage-result{{color:#aaa}}.ok{{color:#6ddc79}}.starting{{color:#7db7ff}}.degraded{{color:#ffd166}}.unhealthy{{color:#ff6b6b}}
</style></head><body><h1>{escape(source_title())}</h1>
<p>Feed status: <strong class=\"{s['feed_status']}\">{s['feed_status'].upper()}</strong></p><table>
<tr><td>Coverage resolution</td><td>0.5° / 720 bins</td></tr>
<tr><td>Build version</td><td>{s['build_version']}</td></tr>
<tr><td>Input source</td><td>{s['source']}</td></tr><tr><td>Service health</td><td><span class=\"ok\">OK</span></td></tr>
<tr><td>Receiver</td><td>{s['receiver']}</td></tr>"""
            if s["source"] in ("flights_js", "aircraft_json"):
                age = "N/A" if s["last_poll_age_seconds"] is None else f'{s["last_poll_age_seconds"]:.1f} sec'
                poll_ms = "N/A" if s["last_poll_duration_ms"] is None else f'{s["last_poll_duration_ms"]} ms'
                source_rows = f"""<tr><td>Last successful poll</td><td>{human_utc(last_success_time)}</td></tr>
<tr><td>Last poll age</td><td>{age}</td></tr><tr><td>Last poll duration</td><td>{poll_ms}</td></tr>
<tr><td>Poll interval</td><td>{s['poll_interval_seconds']} sec</td></tr><tr><td>Consecutive failures</td><td>{s['consecutive_failures']}</td></tr>
<tr><td>Successful polls</td><td>{s['successful_polls']}</td></tr><tr><td>Failed polls</td><td>{s['failed_polls']}</td></tr>"""
            elif s["source"] == "swim_tfms":
                age = "N/A" if s["last_message_age_seconds"] is None else f'{s["last_message_age_seconds"]:.1f} sec'
                source_rows = f"""<tr><td>SWIM product</td><td>TFMS</td></tr>
<tr><td>Geographic gate</td><td>{s['radius_nm']} NM</td></tr><tr><td>Last message age</td><td>{age}</td></tr>
<tr><td>Solace messages received</td><td>{s['messages_received']}</td></tr><tr><td>TFMS records seen</td><td>{s['tfms_records_seen']}</td></tr>
<tr><td>trackInformation identified</td><td>{s['track_records']}</td></tr>
<tr><td>Tracks with usable position</td><td>{s['tfms_parser_diagnostics']['positioned_tracks']}</td></tr>
<tr><td>Tracks missing/unrecognized latitude</td><td>{s['tfms_parser_diagnostics']['missing_latitude']}</td></tr>
<tr><td>Tracks missing/unrecognized longitude</td><td>{s['tfms_parser_diagnostics']['missing_longitude']}</td></tr>
<tr><td>TFMS message types</td><td>{escape(json.dumps(s['tfms_parser_diagnostics']['message_types'], sort_keys=True))}</td></tr>
<tr><td>First TFMS record structure (names only)</td><td>{escape(', '.join(s['tfms_parser_diagnostics']['first_message_structure']))}</td></tr>
<tr><td>First trackInformation structure (names only)</td><td>{escape(', '.join(s['tfms_parser_diagnostics']['first_track_structure']))}</td></tr>
<tr><td>Tracks accepted</td><td>{s['track_records_accepted']}</td></tr>
<tr><td>Tracks outside gate</td><td>{s['track_records_outside_gate']}</td></tr><tr><td>Parse errors</td><td>{s['parse_errors']}</td></tr>
<tr><td>Reconnects</td><td>{s['reconnects']}</td></tr>"""
            else:
                age = "N/A" if s["last_message_age_seconds"] is None else f'{s["last_message_age_seconds"]:.1f} sec'
                source_rows = f"""<tr><td>SBS/BaseStation port</td><td>{s['sbs_port']}</td></tr>
<tr><td>Last message</td><td>{human_utc(sbs_last_message_time)}</td></tr><tr><td>Last message age</td><td>{age}</td></tr>
<tr><td>Message rate</td><td>{s['message_rate_per_second']} / sec</td></tr><tr><td>Messages received</td><td>{s['messages_received']}</td></tr>
<tr><td>Snapshot interval</td><td>{s['snapshot_interval_seconds']} sec</td></tr><tr><td>Parse errors</td><td>{s['parse_errors']}</td></tr>
<tr><td>Connection attempts</td><td>{s['connection_attempts']}</td></tr><tr><td>Reconnections</td><td>{s['reconnections']}</td></tr>"""
            html = common + source_rows + f"""<tr><td>Aircraft total</td><td>{s['aircraft_total']}</td></tr>
<tr><td>Aircraft with position</td><td>{s['aircraft_with_position']}</td></tr><tr><td>Aircraft without position</td><td>{s['aircraft_without_position']}</td></tr>
<tr><td>ADSB Aircraft Tracker</td><td>{(lambda e: 'Detected / active' if e.get('tracker_state') == 'active' else ('Temporarily unavailable' if e.get('tracker_state') == 'unavailable' else 'Awaiting detection'))(refresh_tracker_enrichment())}</td></tr><tr><td>O/D airport</td><td>{CFG['destination_airport'] or 'Not configured'}</td></tr>
<tr><td>HTTP requests served</td><td>{s['requests_served']}</td></tr><tr><td>Uptime</td><td>{s['uptime_seconds']} sec</td></tr></table>
<h2>Navigation</h2><p><a href="settings">Settings backup / recovery</a> · <a href=\"./\">Raw ADS-B Map</a></p>
<section style="border:2px solid #398851;border-radius:6px;padding:1em;margin:1em 0"><h2>Data &amp; API Endpoints</h2><p>
<a href=\"data/aircraft.json\">/data/aircraft.json</a> &mdash; normalized aircraft data<br>
<a href=\"aircraft.json\">/aircraft.json</a> &mdash; compatibility aircraft data<br>
<a href=\"status\">/status</a> &mdash; bridge and feed status<br>
<a href=\"health\">/health</a> &mdash; health check<br>
<a href=\"range-coverage\">/range-coverage</a> &mdash; observed range coverage<br>
<a href=\"range-coverage.geojson\">/range-coverage.geojson</a> &mdash; observed range coverage as GeoJSON<br>
<code>/range-coverage/import</code> &mdash; validated merge/restore of exported coverage<br>
<a href=\"tracker-enrichment\">/tracker-enrichment</a> &mdash; ADSB Tracker enrichment<br>
<a href=\"map-config\">/map-config</a> &mdash; map configuration
</p>
</section><section id="density-backup" style="border:2px solid #c5a02b;border-radius:6px;padding:1em;margin:1em 0"><h2>Traffic Density — {SOURCE_LABELS[CFG["source"]]}</h2>
<p>Collected independently of this map. Recent view: 30 UTC calendar days. Monthly history: 18 months.</p>
<p><label>Backup window: <select id="density-month"><option value="">All retained history</option></select></label> <a id="density-export" href="traffic-density/export" download="{export_name("traffic-density")}">Export density JSON</a> · <a href="traffic-density.geojson" download="{export_name("traffic-density","geojson")}">Export recent spatial cells (GeoJSON)</a> · <a href="traffic-density/status">Collection status</a></p>
<p><input id="density-file" type="file" accept="application/json,.json"> <button id="density-import" type="button">Restore density JSON</button></p>
<p><label><input id="density-legacy" type="checkbox"> This older, untagged backup belongs to {SOURCE_LABELS[CFG["source"]]}.</label></p>
<p id="density-result">Restore selects whole cell/month snapshots; overlapping histories are never added.</p>
<script>
fetch('traffic-density/status').then(r=>r.json()).then(s=>{{const select=document.getElementById('density-month');for(const month of(s.months||[]).slice().reverse()){{const option=document.createElement('option');option.value=month;option.textContent=month;select.appendChild(option)}}select.addEventListener('change',()=>{{const link=document.getElementById('density-export');link.href='traffic-density/export'+(select.value?'?month='+encodeURIComponent(select.value):'');link.download='{SOURCE_PREFIXES[CFG['source']]}-traffic-density'+(select.value?'-'+select.value:'')+'.json'}})}}).catch(()=>{{}});
document.getElementById('density-import').addEventListener('click',async()=>{{const f=document.getElementById('density-file').files[0],out=document.getElementById('density-result');if(!f){{out.textContent='Select a density JSON export first.';return}}try{{out.textContent='Restoring…';const r=await fetch('traffic-density/import'+(document.getElementById('density-legacy').checked?'?legacy_source={CFG["source"]}':''),{{method:'POST',headers:{{'Content-Type':'application/json'}},body:f}});const x=await r.json();if(!r.ok)throw new Error(x.error||'Restore failed');out.textContent=`Restore complete: ${{x.added}} added, ${{x.replaced}} replaced, ${{x.retained}} retained; ${{x.ignored_months}} expired/future months ignored.`}}catch(e){{out.textContent=e.message}}}});
</script>
</section><section id="density-envelope-backup" style="border:2px solid #c5a02b;border-radius:6px;padding:1em;margin:1em 0"><h2>Density-derived envelopes — consistency comparison</h2>
<p>All four products use the same source, dates, Home position and 0.5° bearings. Cell-center ranges are approximate; these do not replace authoritative range coverage. FAA products describe reported traffic extent, not receiver coverage. Passage evidence is combined across altitude bands in qualifying cells.</p>
<p><label>Start (UTC): <input id="envelope-start" type="date"></label> <label>End (UTC): <input id="envelope-end" type="date"></label> <button id="envelope-preview" type="button">Generate comparison</button></p>
<p><a id="envelope-json" href="traffic-density/envelopes?download=1" download="{export_name("density-envelopes")}">Export envelopes JSON</a> · <a id="envelope-geojson" href="traffic-density/envelopes.geojson" download="{export_name("density-envelopes","geojson")}">Export envelopes GeoJSON</a></p>
<p id="envelope-result">Generated on demand; cached for up to five minutes. Unknown altitude is included only in All Traffic.</p>
<script>
function envelopeQuery(){{const q=new URLSearchParams();for(const name of['start','end']){{const value=document.getElementById('envelope-'+name).value;if(value)q.set(name,value)}}return q.size?'?'+q.toString():''}}
for(const name of['start','end'])document.getElementById('envelope-'+name).addEventListener('change',()=>{{const query=envelopeQuery();document.getElementById('envelope-json').href='traffic-density/envelopes'+(query?query+'&download=1':'?download=1');document.getElementById('envelope-geojson').href='traffic-density/envelopes.geojson'+query;document.getElementById('envelope-result').textContent='Dates changed; generate the comparison again.'}});
document.getElementById('envelope-preview').addEventListener('click',async()=>{{const out=document.getElementById('envelope-result'),button=document.getElementById('envelope-preview');button.disabled=true;out.textContent='Generating…';try{{const r=await fetch('traffic-density/envelopes'+envelopeQuery(),{{cache:'no-store'}}),data=await r.json();if(!r.ok)throw new Error(data.error||'Generation failed');out.textContent=data.extent_kind+' · '+data.window.start+' – '+data.window.end+' (UTC) · '+Object.entries(data.products).map(([band,p])=>band+': '+p.populated_bins+'/720 sectors').join(' · ')+' · '+(data.cached?'cached':'generated')+' '+data.generated_at}}catch(e){{out.textContent=e.message}}finally{{button.disabled=false}}}});
</script></section>
<section id="range-backup" style="border:2px solid #c5a02b;border-radius:6px;padding:1em;margin:1em 0"><h2>Range Coverage Backup / Restore</h2>
<p><a href="range-coverage-baseline?download=1" download="{export_name("range-coverage-1-degree-baseline")}"><button type="button">Export 1° baseline</button></a> <a href="range-coverage?download=1" download="{export_name("range-coverage")}"><button type="button">Export coverage JSON</button></a> <a href="range-coverage.geojson" download="{export_name("range-coverage","geojson")}"><button type="button">Export coverage GeoJSON</button></a></p>
<p><input id="coverage-file" type="file" accept="application/json,.json"> <button id="coverage-import" type="button">Import / merge coverage</button></p>
<p id="coverage-result"><small>Import merges by bearing and keeps the farther range, so restoring an older backup will not overwrite a newer maximum.</small></p>
<script>
document.getElementById('coverage-import').addEventListener('click',async()=>{{const f=document.getElementById('coverage-file').files[0],out=document.getElementById('coverage-result');if(!f){{out.textContent='Select a coverage JSON file first.';return}}try{{const text=await f.text();JSON.parse(text);out.textContent='Importing...';const r=await fetch('range-coverage/import',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:text}});const x=await r.json();if(!r.ok||!x.ok)throw new Error(x.error||`HTTP ${{r.status}}`);out.textContent=`Import complete: ${{x.added}} added, ${{x.replaced}} replaced, ${{x.retained}} retained; ${{x.populated_bins}}/${{x.total_bins}} bins populated; ${{x.pending}} legacy positions pending Home.`}}catch(e){{out.textContent='Import failed: '+e.message}}}});
</script>
</section>
<h2>Diagnostics</h2><p><a href="tile-debug">/tile-debug</a> &mdash; map tile proxy diagnostics</p>
<p><small>Map tiles are served internally through <code>/tiles/{{z}}/{{x}}/{{y}}.png</code>.</small></p>
<section style="border:2px solid #b33;border-radius:6px;padding:1em;margin:1em 0"><h2>Danger Zone</h2>
<p>Deletion is permanent. Export backups first. Configuration and credentials are preserved; collection starts fresh.</p>
<button class="clear-data" data-target="density">Clear current-source traffic density</button>
<button class="clear-data" data-target="range">Clear range coverage and legacy baseline</button>
<button class="clear-data" data-target="all">Clear all collected data (all sources)</button><p id="clear-result"></p>
<script>
for(const button of document.querySelectorAll('.clear-data'))button.addEventListener('click',async()=>{{
 const target=button.dataset.target,required=target==='all'?'CLEAR ALL':'CLEAR';
 const answer=prompt(button.textContent+'? This permanently deletes stored observations. Type '+required+' to confirm.');
 if(answer!==required)return;
 const out=document.getElementById('clear-result');button.disabled=true;out.textContent='Clearing…';
 try{{const r=await fetch('data/clear',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{target,confirmation:answer}})}});const data=await r.json();if(!r.ok)throw new Error(data.error);out.textContent='Cleared: '+data.cleared.join(', ');}}catch(e){{out.textContent=e.message;}}finally{{button.disabled=false;}}
}});
</script></section>
</body></html>"""
            if CFG["source"] == "swim_tfms":
                html = re.sub(r'<section id="range-backup" style="border:2px solid #c5a02b;border-radius:6px;padding:1em;margin:1em 0">.*?</section>', "<p>Range ring collection and backups are disabled for FAA TFMS.</p>", html, flags=re.S)
                html = re.sub(r'<a href=\"range-coverage.*?<br>', "", html)
                html = re.sub(r'<code>/range-coverage/import</code>.*?<br>', "", html)
                html = html.replace("0.5° / 720 bins", "Disabled for FAA TFMS")
            if density_startup_error:
                html = html.replace("<h2>Traffic Density", "<p class=\"unhealthy\">"+escape(density_startup_error)+"</p><h2>Traffic Density")
            self.send_html(html)
            return
        self.send_json({"error": "not found", "path": path}, 404)


def open_density_store():
    root = Path(os.environ.get("FR24_DENSITY_PATH", "/data/traffic-density"))
    root.mkdir(parents=True, exist_ok=True)
    marker = root / 'migration.json'
    legacy = sorted(root.glob('????-??.dat'))
    if legacy or marker.exists():
        attribution = CFG.get('density_legacy_source', 'unassigned')
        if marker.exists():
            migration = json.loads(marker.read_text())
            attribution = migration['source']
        else:
            if attribution not in VALID_SOURCES:
                raise ValueError("Existing density history is preserved but has no source identity. Set density_legacy_source to its original source in App Configuration and restart; collection is paused until attribution.")
            migration = {'source':attribution, 'months':[p.name for p in legacy]}
            if (root/attribution).exists():
                raise ValueError('Legacy migration target already exists; export both histories before restoring explicitly.')
            temporary = marker.with_suffix('.tmp')
            temporary.write_text(json.dumps(migration))
            os.replace(temporary,marker)
        if attribution not in VALID_SOURCES or any(not re.fullmatch(r'\d{4}-\d{2}\.dat', name) for name in migration['months']):
            raise ValueError('invalid legacy migration marker')
        identity = json.loads((root/'identity.json').read_text())
        if identity.get('base_zoom') != 17 or identity.get('scheme') != 'geographic-quadtree' or not identity.get('provenance'):
            raise ValueError('invalid legacy density identity')
        target = root/attribution
        target.mkdir(exist_ok=True)
        for name in migration['months']:
            original, destination = root/name, target/name
            if original.exists():
                if destination.exists():
                    raise ValueError('Legacy migration collision; history preserved for manual review')
                # Opening and closing recovers a hot journal and checkpoints WAL
                # before moving the main SQLite file after an interrupted stop.
                db = sqlite3.connect(original)
                try:
                    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise ValueError("corrupt legacy density chunk")
                finally:
                    db.close()
                os.replace(original,destination)
            elif not destination.exists():
                raise ValueError('Legacy migration chunk missing')
        identity['source_type'] = attribution
        temporary = target/'identity.tmp'
        temporary.write_text(json.dumps(identity))
        os.replace(temporary,target/'identity.json')
        marker.unlink()
    return DensityStore(root/CFG['source'], source_type=CFG['source'])


def density_envelope_payload(start=None,end=None):
    store = density_store
    if store is None:
        raise ValueError('traffic density unavailable')
    with lock:
        home = dict(home_marker) if home_marker else None
    with store.lock:
        if not hasattr(store,'envelope_service'):
            store.envelope_service = EnvelopeCache(store)
        service = store.envelope_service
    payload = service.get(home,start,end)
    for product in payload['products'].values():
        product['envelope_segments'] = coverage_envelope_segments(product['bins'],payload['home'])
    return payload


def density_envelope_geojson(payload):
    features=[]
    for band,product in payload['products'].items():
        for segment in product['envelope_segments']:
            if len(segment)>=2:
                features.append({'type':'Feature','geometry':{'type':'LineString','coordinates':segment},
                    'properties':{'band':band,'derived':True,'position_method':'base_cell_center'}})
        for item in product['bins']:
            features.append({'type':'Feature','geometry':{'type':'Point','coordinates':item['cell_center']},
                'properties':{'band':band,**{k:v for k,v in item.items() if k!='cell_center'}}})
    return {'type':'FeatureCollection','metadata':{k:v for k,v in payload.items() if k!='products'},'features':features}


def main():
    global density_store, density_startup_error
    try:
        density_store = open_density_store()
        atexit.register(density_store.close)
    except Exception as exc:
        density_startup_error = str(exc)
        print(f"[WARN] Traffic density paused to protect existing history: {exc}", flush=True)
    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
    threading.Thread(target=density_maintenance, daemon=True).start()
    threading.Thread(target=home_marker_updater, daemon=True).start()
    if CFG["source"] != "swim_tfms":
        threading.Thread(target=coverage_updater, daemon=True).start()
    else:
        print("[INFO] Range coverage processing disabled for TFMS input", flush=True)
    if CFG["source"] == "sbs_30003":
        print(f"Input source: SBS/BaseStation TCP {CFG['receiver_host']}:{CFG['sbs_port']}", flush=True)
        print(f"Snapshot interval: {SBS_SNAPSHOT_INTERVAL} second", flush=True)
        threading.Thread(target=sbs_reader, daemon=True).start()
        threading.Thread(target=sbs_publisher, daemon=True).start()
    elif CFG["source"] == "flights_js":
        print(f"Input source: flights.js at {RECEIVER_URL}", flush=True)
        print(f"Poll interval: {CFG['poll_interval']} seconds", flush=True)
        threading.Thread(target=flights_js_updater, daemon=True).start()
    elif CFG["source"] == "aircraft_json":
        print(f"Input source: dump1090/readsb aircraft.json at {CFG['aircraft_json_url']}", flush=True)
        print(f"Poll interval: {CFG['aircraft_json_poll_interval']} seconds", flush=True)
        threading.Thread(target=aircraft_json_updater, daemon=True).start()
    else:
        print("Input source: FAA SWIM TFMS", flush=True)
        print(f"SWIM product: {CFG['swim_product']}; geographic gate: {CFG['swim_radius_nm']:.0f} NM", flush=True)
        threading.Thread(target=swim_tfms_runner, daemon=True).start()
        threading.Thread(target=swim_publisher, daemon=True).start()
    refresh_tracker_enrichment(force=True)
    if CFG["destination_airport"]:
        print(f"[INFO] Airport origin/destination highlight configured: {CFG['destination_airport']}", flush=True)
    print(f"Serving on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
