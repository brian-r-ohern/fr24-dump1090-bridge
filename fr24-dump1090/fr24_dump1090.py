#!/usr/bin/env python3
"""FR24 receiver -> dump1090/readsb-compatible HTTP bridge for Home Assistant OS."""

import ast
import json
import math
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, Request, build_opener, urlopen

CONFIG_PATH = os.environ.get("FR24_OPTIONS_PATH", "/data/options.json")
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8085
DEGRADED_AFTER_SECONDS = 10
UNHEALTHY_AFTER_SECONDS = 30
SBS_SNAPSHOT_INTERVAL = 1.0
SBS_AIRCRAFT_TIMEOUT = 60.0
SBS_RECONNECT_DELAY = 2.0
SBS_SOCKET_TIMEOUT = 5.0
VALID_SOURCES = ("sbs_30003", "flights_js", "aircraft_json")
OSM_TILE_BASE = "https://tile.openstreetmap.org"
OSM_TILE_CACHE = os.environ.get("FR24_TILE_CACHE", "/data/map-tile-cache-v2")
OSM_TILE_USER_AGENT = "FR24-dump1090-Bridge/0.5.1 (+https://github.com/brian-r-ohern/fr24-dump1090-bridge)"
OSM_TILE_FALLBACK_TTL = 7 * 24 * 60 * 60
OSM_TILE_TIMEOUT = 10
TILE_PROXY_BUILD = "v0.5.1"
tile_proxy_requests = 0
tile_proxy_cache_hits = 0
tile_proxy_upstream_fetches = 0
tile_proxy_blocked = 0
tile_proxy_last_error = None
tile_proxy_last_referer = None


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    source = str(cfg.get("source", "sbs_30003")).strip() or "sbs_30003"
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid source {source!r}; expected one of: {', '.join(VALID_SOURCES)}")
    receiver_host = str(cfg.get("receiver_host", "")).strip()
    aircraft_json_url = str(cfg.get("aircraft_json_url", "")).strip()
    username = str(cfg.get("username", ""))
    password = str(cfg.get("password", ""))
    if source in ("sbs_30003", "flights_js") and not receiver_host:
        raise ValueError(f"{source} source requires receiver_host")
    if source == "flights_js" and (not username.strip() or not password):
        raise ValueError("flights_js source requires username and password")
    if source == "aircraft_json":
        parts = urlsplit(aircraft_json_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("aircraft_json source requires a valid http(s) aircraft_json_url")
    return {
        "source": source,
        "receiver_host": receiver_host,
        "receiver_port": int(cfg.get("receiver_port", 80)),
        "sbs_port": int(cfg.get("sbs_port", 30003)),
        "username": username,
        "password": password,
        "poll_interval": int(cfg.get("poll_interval", 2)),
        "request_timeout": int(cfg.get("request_timeout", 3)),
        "aircraft_json_url": aircraft_json_url,
        "aircraft_json_poll_interval": int(cfg.get("aircraft_json_poll_interval", 1)),
        "destination_airport": str(cfg.get("destination_airport", "")).strip().upper(),
    }


CFG = load_config()
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

# Persistent empirical receiver-coverage envelope. Each integer bearing bin
# retains only the farthest aircraft position ever observed in that 1-degree
# sector. Empty bins remain empty on disk; the map simply connects successive
# populated bins to form a continuous observed-range outline.
COVERAGE_PATH = os.environ.get("FR24_COVERAGE_PATH", "/data/range-coverage.json")
COVERAGE_FLUSH_SECONDS = 30.0
coverage_bins = [None] * 360
coverage_dirty = False
coverage_generation = 0
coverage_last_flush = 0.0
coverage_loaded = False
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
    return {"home": marker, "destination_airport": CFG["destination_airport"] or None}


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


def load_coverage():
    global coverage_bins, coverage_loaded, coverage_stats
    try:
        with open(COVERAGE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        bins = payload.get("bins", []) if isinstance(payload, dict) else []
        loaded = [None] * 360
        if isinstance(bins, list):
            for item in bins:
                if not isinstance(item, dict):
                    continue
                bearing = item.get("bearing")
                distance = item.get("distance_nm")
                if isinstance(bearing, int) and 0 <= bearing < 360 and isinstance(distance, (int, float)) and distance >= 0:
                    # v1 coverage files did not have first_observed/update_count.
                    # Preserve the learned maximum and seed the new metadata from
                    # the winning observation rather than resetting coverage.
                    item = dict(item)
                    item.setdefault("first_observed", item.get("observed"))
                    item.setdefault("update_count", 1)
                    loaded[bearing] = item

        old_stats = payload.get("stats", {}) if isinstance(payload, dict) else {}
        observed_times = [x.get("observed") for x in loaded if x and x.get("observed")]
        first_times = [x.get("first_observed") for x in loaded if x and x.get("first_observed")]
        populated = sum(x is not None for x in loaded)
        stats = {
            "collection_started": old_stats.get("collection_started") or (min(first_times) if first_times else None),
            "total_updates": int(old_stats.get("total_updates", populated)),
            "first_fills": int(old_stats.get("first_fills", populated)),
            "record_replacements": int(old_stats.get("record_replacements", 0)),
            "last_update": old_stats.get("last_update") or (max(observed_times) if observed_times else None),
            "hourly_updates": dict(old_stats.get("hourly_updates", {})) if isinstance(old_stats.get("hourly_updates", {}), dict) else {},
        }
        with lock:
            coverage_bins = loaded
            coverage_stats = stats
            coverage_loaded = True
        print(f"[INFO] Coverage history loaded: {populated}/360 bearing bins", flush=True)
    except FileNotFoundError:
        with lock:
            coverage_loaded = True
        print("[INFO] Coverage history initialized: 0/360 bearing bins", flush=True)
    except Exception as exc:
        with lock:
            coverage_loaded = True
        print(f"[WARN] Coverage history could not be loaded; starting empty: {exc}", flush=True)


def flush_coverage(force=False):
    global coverage_dirty, coverage_last_flush
    now = time.time()
    with lock:
        if not coverage_dirty and not force:
            return
        if not force and now - coverage_last_flush < COVERAGE_FLUSH_SECONDS:
            return
        bins = [dict(item) for item in coverage_bins if item is not None]
        stats = dict(coverage_stats)
        stats["hourly_updates"] = dict(coverage_stats.get("hourly_updates", {}))
        generation = coverage_generation
    payload = {"version": 2, "bin_degrees": 1, "updated": iso_utc(now), "stats": stats, "bins": bins}
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
    if not marker:
        return
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
        bin_no = int(round(bearing)) % 360
        with lock:
            current = coverage_bins[bin_no]
            if current is not None and float(current.get("distance_nm", -1)) >= distance_nm:
                continue
            first_fill = current is None
            first_observed = observed if first_fill else current.get("first_observed") or current.get("observed") or observed
            update_count = 1 if first_fill else int(current.get("update_count", 1)) + 1
            coverage_bins[bin_no] = {
                "bearing": bin_no,
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


def coverage_updater():
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
    return {"available": available, "bin_degrees": 1, "populated_bins": len(bins), "total_bins": 360, "stats": stats, "bins": bins}


def _entity_attributes(entity_id):
    state = _supervisor_core_request(f"/states/{entity_id}")
    attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
    return attrs if isinstance(attrs, dict) else {}


def refresh_tracker_enrichment(force=False):
    global tracker_enrichment, tracker_enrichment_last_attempt, tracker_available_logged, tracker_ever_detected
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
            "service_status": "ok", "source": source, "feed_status": feed_status,
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
    return {
        "service_status": "ok", "source": "sbs_30003", "feed_status": feed_status,
        "receiver": receiver, "uptime_seconds": round(now - START_TIME, 1),
        "sbs_port": CFG["sbs_port"], "snapshot_interval_seconds": SBS_SNAPSHOT_INTERVAL,
        "last_message": iso_utc(success_time),
        "last_message_age_seconds": None if age is None else round(age, 1),
        "messages_received": total_messages, "message_rate_per_second": round(message_rate, 1),
        "parse_errors": parse_errors, "connection_attempts": attempts, "reconnections": reconnects,
        "aircraft_total": len(aircraft), "aircraft_with_position": positioned,
        "aircraft_without_position": len(aircraft) - positioned, "requests_served": served,
    }


MAP_HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Raw ADS-B Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>
html,body,#map{height:100%;margin:0;background:#111;font-family:system-ui,-apple-system,Segoe UI,sans-serif}#map{position:absolute;inset:0}
.topbar{position:absolute;z-index:1000;top:10px;left:50%;transform:translateX(-50%);background:rgba(17,17,17,.90);color:#eee;border-radius:8px;padding:8px 12px;box-shadow:0 2px 8px #0008;display:flex;gap:12px;align-items:center;white-space:nowrap}.topbar strong{font-size:14px}.stats{font-size:12px;color:#ccc}.ok{color:#6ddc79}.bad{color:#ff6b6b}.degraded{color:#ffd166}.btn{border:1px solid #666;background:#222;color:#eee;border-radius:5px;padding:5px 8px;cursor:pointer}.btn:hover{background:#333}
.info{position:absolute;z-index:1000;right:10px;bottom:24px;min-width:205px;background:rgba(17,17,17,.90);color:#ddd;border-radius:7px;padding:8px 10px;box-shadow:0 2px 8px #0008;font-size:11px}.info-title{font-weight:700;font-size:12px;margin-bottom:5px}.info-grid{display:grid;grid-template-columns:auto auto;gap:2px 12px}.info-grid span:nth-child(odd){color:#aaa}.info-grid span:nth-child(even){text-align:right}.nav{border-top:1px solid #444;margin-top:6px;padding-top:5px;text-align:right}.nav a{color:#8fc1ff;text-decoration:none}.plane{position:relative;width:24px;height:24px;color:#1367a8;filter:drop-shadow(0 0 1px white) drop-shadow(0 0 1px white);transform-origin:50% 50%}.plane svg{display:block;width:24px;height:24px;fill:currentColor}.plane.military{color:#22a447}.plane.closest{filter:drop-shadow(0 0 1px white) drop-shadow(0 0 1px white) drop-shadow(0 0 4px #f33) drop-shadow(0 0 7px #f33)}.plane.destination::after,.plane.origin::after{position:absolute;right:-7px;top:-7px;font:700 9px/13px system-ui;color:#111;background:#ffd166;border:1px solid #7a5a00;border-radius:50%;width:13px;height:13px;text-align:center;transform:rotate(var(--counter-rotation,0deg))}.plane.destination::after{content:"D"}.plane.origin::after{content:"O"}.plane.origin.destination::after{content:"O/D";width:21px;right:-11px;border-radius:7px}.leaflet-popup-content{min-width:190px}.ac-title{font-weight:700;font-size:15px}.ac-flags{margin-top:4px;color:#b22;font-size:11px}.ac-grid{margin-top:6px;display:grid;grid-template-columns:auto auto;gap:2px 10px}.ac-grid span:nth-child(odd){color:#666}.home-marker{font-size:26px;line-height:26px;text-shadow:0 0 3px white,0 0 3px white}
@media (max-width:600px){.topbar{left:8px;right:8px;top:8px;transform:none;white-space:normal;display:grid;grid-template-columns:1fr auto;gap:4px 8px;padding:7px 9px}.topbar strong{min-width:0}.topbar .stats{grid-column:1 / -1;grid-row:2}.topbar .btn{grid-column:2;grid-row:1}.info{right:6px;bottom:20px;max-width:calc(100vw - 32px)}}
</style></head><body><div id="map"></div><div class="topbar"><strong>Raw ADS-B Map</strong><span id="stats" class="stats">Loading aircraft…</span><button class="btn" id="fit">Fit aircraft</button></div><div class="info"><div class="info-title">Bridge status</div><div id="info-grid" class="info-grid"><span>Feed</span><span>Loading…</span></div><div class="nav"><a href="status-page">Status</a> · <a href="data/aircraft.json">aircraft.json</a></div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
(()=>{const map=L.map('map',{zoomControl:true}).setView([39.5,-98.35],4);const tileTemplate='tiles/{z}/{x}/{y}.png?ref_origin='+encodeURIComponent(window.location.origin);const tiles=L.tileLayer(tileTemplate,{maxZoom:19,tileSize:256,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});tiles.on('tileerror',e=>console.warn('FR24 tile proxy error',e?.tile?.src||e));tiles.addTo(map);const markers=new Map();let homeMarker=null,homeCircle=null,coverageLine=null;let initialFit=false,lastBounds=null;let enrichment={available:false,tracker_state:'awaiting',closest_hex:null,military_hexes:[],origin_hexes:[],destination_hexes:[],aircraft:{}};let destinationAirport=null;const statsEl=document.getElementById('stats'),infoEl=document.getElementById('info-grid');const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const fmt=(v,s='')=>(v===undefined||v===null||v==='')?'—':`${esc(v)}${s}`;const altitude=v=>v==='ground'?'Ground':(v===undefined||v===null?'—':`${Number(v).toLocaleString()} ft`);const signed=v=>(v===undefined||v===null)?'—':`${Number(v)>0?'+':''}${Number(v).toLocaleString()} ft/min`;const duration=v=>{v=Number(v);if(!Number.isFinite(v))return '—';const h=Math.floor(v/3600),m=Math.floor((v%3600)/60);return h?`${h}h ${m}m`:`${m}m`};
function flagsFor(key){const military=new Set(enrichment.military_hexes||[]),origin=new Set(enrichment.origin_hexes||[]),destination=new Set(enrichment.destination_hexes||[]);return{military:military.has(key),closest:enrichment.closest_hex===key,origin:origin.has(key),destination:destination.has(key)}}
function trackerFor(key){return(enrichment.aircraft||{})[key]||{}}
function bearing(a,b){const r=Math.PI/180,p1=a.lat*r,p2=b.lat*r,dl=(b.lon-a.lon)*r,y=Math.sin(dl)*Math.cos(p2),x=Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl);return(Math.atan2(y,x)/r+360)%360}
function distanceM(a,b){const r=Math.PI/180,R=6371000,p1=a.lat*r,p2=b.lat*r,dp=(b.lat-a.lat)*r,dl=(b.lon-a.lon)*r,h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.asin(Math.sqrt(h))}
const motion=new Map();
function displayTrack(key,ac,lat,lon){const now=Date.now(),cur={lat,lon,t:now},prev=motion.get(key);let d=Number(ac.track),source=Number.isFinite(d)?'reported':'none';if(prev){const moved=distanceM(prev,cur);if(moved>=40){d=bearing(prev,cur);source='calculated';motion.set(key,cur)}else if(now-prev.t>15000){motion.set(key,cur)}}else motion.set(key,cur);return{degrees:Number.isFinite(d)?d:null,source}}
function popup(ac,flags,key,orientation){const t=trackerFor(key),title=(t.flight||ac.flight||'').trim()||ac.hex.toUpperCase(),tail=t.tail&&t.tail!=='Unknown'?t.tail:null,type=[t.aircraft_type,t.description&&t.description!=='Unknown aircraft'?t.description:null].filter(Boolean).join(' · '),badges=[];if(flags.military)badges.push('MILITARY');if(flags.closest)badges.push('CLOSEST');if(flags.origin)badges.push(`ORIGIN: ${destinationAirport}`);if(flags.destination)badges.push(`DESTINATION: ${destinationAirport}`);const route=(t.route_origin||t.route_destination)?`${esc(t.route_origin||'—')}${t.route_origin_name?` (${esc(t.route_origin_name)})`:''} → ${esc(t.route_destination||'—')}${t.route_destination_name?` (${esc(t.route_destination_name)})`:''}`:null;const enriched=[tail?`<span>Registration</span><b>${esc(tail)}</b>`:'',type?`<span>Aircraft</span><b>${esc(type)}</b>`:'',route?`<span>Route</span><b>${route}</b>`:'',t.distance_display?`<span>Distance</span><b>${esc(t.distance_display)}</b>`:''].join('');const badgeHtml=badges.length?`<div class="ac-flags">${badges.map(x=>`<b>${esc(x)}</b>`).join(' · ')}</div>`:'';const trackText=orientation.degrees==null?'—':`${orientation.degrees.toFixed(1)}°${orientation.source==='calculated'?' (course)':''}`;return `<div class="ac-title">${esc(title)}</div>${badgeHtml}<div class="ac-grid">${enriched}<span>ICAO</span><b>${esc(ac.hex.toUpperCase())}</b><span>Altitude</span><b>${altitude(ac.alt_baro)}</b><span>Ground speed</span><b>${fmt(ac.gs,' kt')}</b><span>Track/course</span><b>${trackText}</b><span>Vertical rate</span><b>${signed(ac.baro_rate)}</b><span>Squawk</span><b>${fmt(ac.squawk)}</b><span>Last message</span><b>${fmt(ac.seen,' sec')}</b><span>Last position</span><b>${fmt(ac.seen_pos,' sec')}</b></div>`}
function icon(track,flags){const d=Number.isFinite(Number(track))?Number(track):0,visual=d,classes=['plane'];if(flags.military)classes.push('military');if(flags.closest)classes.push('closest');if(flags.origin)classes.push('origin');if(flags.destination)classes.push('destination');const planeSvg='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1.5 14.2 9l6.8 4v2l-6.8-1.8-.7 5.2 2.5 1.8v1.5L12 20.5 8 21.7v-1.5l2.5-1.8-.7-5.2L3 15v-2l6.8-4L12 1.5Z"/></svg>';return L.divIcon({className:'',html:`<div class="${classes.join(' ')}" style="transform:rotate(${visual}deg);--counter-rotation:${-visual}deg">${planeSvg}</div>`,iconSize:[24,24],iconAnchor:[12,12]})}
function fitAircraft(){if(lastBounds&&lastBounds.isValid())map.fitBounds(lastBounds.pad(.08),{maxZoom:10})}document.getElementById('fit').addEventListener('click',fitAircraft);
function trackerLabel(){const state=enrichment.tracker_state||(enrichment.available?'active':'awaiting');return state==='active'?'Detected / active':(state==='unavailable'?'Temporarily unavailable':'Awaiting detection')}
function renderInfo(s){if(!s){infoEl.innerHTML='<span>Status</span><span class="bad">Unavailable</span>';return}const cls=s.feed_status==='ok'?'ok':(s.feed_status==='degraded'?'degraded':'bad');const rows=[['Feed',`<b class="${cls}">${esc(String(s.feed_status||'unknown').toUpperCase())}</b>`],['Source',esc(s.source)],['Receiver',esc(s.receiver)],['Messages',s.messages_received!=null?Number(s.messages_received).toLocaleString():'—'],['Message rate',s.message_rate_per_second!=null?`${esc(s.message_rate_per_second)} / sec`:'—'],['Aircraft',esc(s.aircraft_total)],['With position',esc(s.aircraft_with_position)],['Without position',esc(s.aircraft_without_position)],['Parse errors',s.parse_errors!=null?esc(s.parse_errors):'—'],['Reconnects',s.reconnections!=null?esc(s.reconnections):'—'],['Tracker',trackerLabel()],['O/D airport',destinationAirport||'—'],['Uptime',duration(s.uptime_seconds)]];infoEl.innerHTML=rows.map(([k,v])=>`<span>${esc(k)}</span><span>${v}</span>`).join('')}
function homeIcon(){return L.divIcon({className:'',html:'<div class="home-marker">⌂</div>',iconSize:[26,26],iconAnchor:[13,13]})}
async function refreshHome(){try{const r=await fetch('map-config',{cache:'no-store'});if(!r.ok)return;const c=await r.json(),h=c?.home;destinationAirport=c?.destination_airport||null;if(!h)return;const lat=Number(h.latitude),lon=Number(h.longitude),radius=Number(h.radius||0);if(!Number.isFinite(lat)||!Number.isFinite(lon))return;if(!homeMarker)homeMarker=L.marker([lat,lon],{icon:homeIcon(),zIndexOffset:1000}).addTo(map).bindPopup('<b>Home</b>');else homeMarker.setLatLng([lat,lon]);if(radius>0){if(!homeCircle)homeCircle=L.circle([lat,lon],{radius,weight:1,fillOpacity:.05}).addTo(map);else{homeCircle.setLatLng([lat,lon]);homeCircle.setRadius(radius)}}}catch(err){console.warn('Home marker unavailable',err)}}
async function refreshEnrichment(){try{const r=await fetch('tracker-enrichment',{cache:'no-store'});if(r.ok)enrichment=await r.json()}catch(err){enrichment={available:false,tracker_state:'awaiting',closest_hex:null,military_hexes:[],origin_hexes:[],destination_hexes:[],aircraft:{}}}}
async function refreshCoverage(){try{const r=await fetch('range-coverage',{cache:'no-store'});if(!r.ok)return;const c=await r.json(),bins=Array.isArray(c.bins)?c.bins:[];const pts=bins.filter(x=>Number.isFinite(Number(x.latitude))&&Number.isFinite(Number(x.longitude))).sort((a,b)=>Number(a.bearing)-Number(b.bearing)).map(x=>[Number(x.latitude),Number(x.longitude)]);if(pts.length>=2){if(!coverageLine)coverageLine=L.polyline(pts.concat([pts[0]]),{color:'#ff1c1c',weight:2,opacity:.85,interactive:false}).addTo(map);else coverageLine.setLatLngs(pts.concat([pts[0]]))}else if(coverageLine){map.removeLayer(coverageLine);coverageLine=null}}catch(err){console.warn('Coverage outline unavailable',err)}}
async function refresh(){try{const [ar,sr,er]=await Promise.all([fetch('data/aircraft.json',{cache:'no-store'}),fetch('status',{cache:'no-store'}),fetch('tracker-enrichment',{cache:'no-store'})]);if(er.ok)enrichment=await er.json();else enrichment={available:false,tracker_state:'awaiting',closest_hex:null,military_hexes:[],origin_hexes:[],destination_hexes:[],aircraft:{}};if(!ar.ok)throw new Error(`aircraft.json HTTP ${ar.status}`);const data=await ar.json(),status=sr.ok?await sr.json():null,active=new Set(),points=[];for(const ac of(data.aircraft||[])){const lat=Number(ac.lat),lon=Number(ac.lon);if(!Number.isFinite(lat)||!Number.isFinite(lon))continue;const key=String(ac.hex||'').toLowerCase();if(!key)continue;active.add(key);points.push([lat,lon]);const flags=flagsFor(key),orientation=displayTrack(key,ac,lat,lon);let m=markers.get(key);if(!m){m=L.marker([lat,lon],{icon:icon(orientation.degrees,flags)}).addTo(map);m.bindPopup(popup(ac,flags,key,orientation),{autoPan:false});markers.set(key,m)}else{m.setLatLng([lat,lon]);m.setIcon(icon(orientation.degrees,flags));if(m.getPopup())m.setPopupContent(popup(ac,flags,key,orientation));else m.bindPopup(popup(ac,flags,key,orientation),{autoPan:false})}}for(const [key,m]of markers)if(!active.has(key)){map.removeLayer(m);markers.delete(key)}lastBounds=points.length?L.latLngBounds(points):null;if(!initialFit&&points.length){fitAircraft();initialFit=true}const total=status?.aircraft_total??(data.aircraft||[]).length,rate=status?.message_rate_per_second,feed=status?.feed_status||'unknown';statsEl.innerHTML=`<span class="${feed==='ok'?'ok':(feed==='degraded'?'degraded':'bad')}">${esc(feed.toUpperCase())}</span> · ${points.length} positioned / ${total} total${rate!=null?` · ${esc(rate)} msg/sec`:''}`;renderInfo(status)}catch(err){statsEl.innerHTML=`<span class="bad">MAP DATA ERROR</span> · ${esc(err.message)}`}}refreshHome();setInterval(refreshHome,300000);refreshCoverage();setInterval(refreshCoverage,5000);refresh();setInterval(refresh,1000)})();
</script></body></html>
'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, payload, code=200):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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

    def do_GET(self):
        global requests_served, tile_proxy_requests, tile_proxy_cache_hits
        with lock:
            requests_served += 1
        path, _, query_string = self.path.partition("?")
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
        if path == "/range-coverage":
            self.send_json(coverage_payload())
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
            self.send_html(MAP_HTML)
            return
        if path == "/status-page":
            s = snapshot_status()
            common = f"""<!doctype html><html><head><meta charset=\"utf-8\"><meta http-equiv=\"refresh\" content=\"5\">
<title>FR24 to dump1090</title><style>
body{{font-family:sans-serif;max-width:760px;margin:40px auto;padding:0 20px;background:#111;color:#eee}}
table{{border-collapse:collapse;width:100%}}td{{padding:8px;border-bottom:1px solid #333}}td:first-child{{color:#aaa;width:45%}}
a{{color:#7db7ff}}.ok{{color:#6ddc79}}.starting{{color:#7db7ff}}.degraded{{color:#ffd166}}.unhealthy{{color:#ff6b6b}}
</style></head><body><h1>FR24 &rarr; dump1090</h1>
<p>Feed status: <strong class=\"{s['feed_status']}\">{s['feed_status'].upper()}</strong></p><table>
<tr><td>Input source</td><td>{s['source']}</td></tr><tr><td>Service health</td><td><span class=\"ok\">OK</span></td></tr>
<tr><td>Receiver</td><td>{s['receiver']}</td></tr>"""
            if s["source"] in ("flights_js", "aircraft_json"):
                age = "N/A" if s["last_poll_age_seconds"] is None else f'{s["last_poll_age_seconds"]:.1f} sec'
                poll_ms = "N/A" if s["last_poll_duration_ms"] is None else f'{s["last_poll_duration_ms"]} ms'
                source_rows = f"""<tr><td>Last successful poll</td><td>{human_utc(last_success_time)}</td></tr>
<tr><td>Last poll age</td><td>{age}</td></tr><tr><td>Last poll duration</td><td>{poll_ms}</td></tr>
<tr><td>Poll interval</td><td>{s['poll_interval_seconds']} sec</td></tr><tr><td>Consecutive failures</td><td>{s['consecutive_failures']}</td></tr>
<tr><td>Successful polls</td><td>{s['successful_polls']}</td></tr><tr><td>Failed polls</td><td>{s['failed_polls']}</td></tr>"""
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
<h2>Navigation</h2><p><a href=\"./\">Raw ADS-B Map</a></p>
<h2>Data &amp; API Endpoints</h2><p>
<a href=\"data/aircraft.json\">/data/aircraft.json</a> &mdash; normalized aircraft data<br>
<a href=\"aircraft.json\">/aircraft.json</a> &mdash; compatibility aircraft data<br>
<a href=\"status\">/status</a> &mdash; bridge and feed status<br>
<a href=\"health\">/health</a> &mdash; health check<br>
<a href=\"range-coverage\">/range-coverage</a> &mdash; observed range coverage<br>
<a href=\"tracker-enrichment\">/tracker-enrichment</a> &mdash; ADSB Tracker enrichment<br>
<a href=\"map-config\">/map-config</a> &mdash; map configuration
</p>
<h2>Diagnostics</h2><p><a href=\"tile-debug\">/tile-debug</a> &mdash; map tile proxy diagnostics</p>
<p><small>Map tiles are served internally through <code>/tiles/{z}/{x}/{y}.png</code>.</small></p>
<p><small>This page refreshes every 5 seconds.</small></p></body></html>"""
            self.send_html(html)
            return
        self.send_json({"error": "not found", "path": path}, 404)


def main():
    threading.Thread(target=home_marker_updater, daemon=True).start()
    threading.Thread(target=coverage_updater, daemon=True).start()
    if CFG["source"] == "sbs_30003":
        print(f"Input source: SBS/BaseStation TCP {CFG['receiver_host']}:{CFG['sbs_port']}", flush=True)
        print(f"Snapshot interval: {SBS_SNAPSHOT_INTERVAL} second", flush=True)
        threading.Thread(target=sbs_reader, daemon=True).start()
        threading.Thread(target=sbs_publisher, daemon=True).start()
    elif CFG["source"] == "flights_js":
        print(f"Input source: flights.js at {RECEIVER_URL}", flush=True)
        print(f"Poll interval: {CFG['poll_interval']} seconds", flush=True)
        threading.Thread(target=flights_js_updater, daemon=True).start()
    else:
        print(f"Input source: dump1090/readsb aircraft.json at {CFG['aircraft_json_url']}", flush=True)
        print(f"Poll interval: {CFG['aircraft_json_poll_interval']} seconds", flush=True)
        threading.Thread(target=aircraft_json_updater, daemon=True).start()
    refresh_tracker_enrichment(force=True)
    if CFG["destination_airport"]:
        print(f"[INFO] Airport origin/destination highlight configured: {CFG['destination_airport']}", flush=True)
    print(f"Serving on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
