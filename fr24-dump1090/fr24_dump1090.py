#!/usr/bin/env python3
"""FR24 receiver -> dump1090/readsb-compatible HTTP bridge for Home Assistant OS."""

import ast
import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, build_opener

CONFIG_PATH = os.environ.get("FR24_OPTIONS_PATH", "/data/options.json")
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8085
DEGRADED_AFTER_SECONDS = 10
UNHEALTHY_AFTER_SECONDS = 30
SBS_SNAPSHOT_INTERVAL = 1.0
SBS_AIRCRAFT_TIMEOUT = 60.0
SBS_RECONNECT_DELAY = 2.0
SBS_SOCKET_TIMEOUT = 5.0
VALID_SOURCES = ("sbs_30003", "flights_js")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    source = str(cfg.get("source", "sbs_30003")).strip() or "sbs_30003"
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid source {source!r}; expected one of: {', '.join(VALID_SOURCES)}")
    receiver_host = str(cfg.get("receiver_host", "")).strip()
    if not receiver_host:
        raise ValueError("Missing required option: receiver_host")
    username = str(cfg.get("username", ""))
    password = str(cfg.get("password", ""))
    if source == "flights_js" and (not username.strip() or not password):
        raise ValueError("flights_js source requires username and password")
    return {
        "source": source,
        "receiver_host": receiver_host,
        "receiver_port": int(cfg.get("receiver_port", 80)),
        "sbs_port": int(cfg.get("sbs_port", 30003)),
        "username": username,
        "password": password,
        "poll_interval": int(cfg.get("poll_interval", 2)),
        "request_timeout": int(cfg.get("request_timeout", 3)),
    }


CFG = load_config()
RECEIVER_URL = f"http://{CFG['receiver_host']}:{CFG['receiver_port']}/flights.js"

password_mgr = HTTPPasswordMgrWithDefaultRealm()
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
        if CFG["source"] == "flights_js":
            success_time = last_success_time
            poll_ms = last_poll_duration_ms
            failures = consecutive_failures
            successes = total_successful_polls
            failed_polls = total_failed_polls
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

    if CFG["source"] == "flights_js":
        if successes == 0 and failed_polls == 0:
            feed_status, receiver = "starting", "connecting"
        elif success_time is None or age > UNHEALTHY_AFTER_SECONDS:
            feed_status, receiver = "unhealthy", "disconnected"
        elif age > DEGRADED_AFTER_SECONDS:
            feed_status, receiver = "degraded", "stale"
        else:
            feed_status, receiver = "ok", "connected"
        return {
            "service_status": "ok", "source": "flights_js", "feed_status": feed_status,
            "receiver": receiver, "uptime_seconds": round(now - START_TIME, 1),
            "poll_interval_seconds": CFG["poll_interval"], "last_success": iso_utc(success_time),
            "last_poll_age_seconds": None if age is None else round(age, 1),
            "last_poll_duration_ms": poll_ms, "consecutive_failures": failures,
            "successful_polls": successes, "failed_polls": failed_polls,
            "aircraft_total": len(aircraft), "aircraft_with_position": positioned,
            "aircraft_without_position": len(aircraft) - positioned, "requests_served": served,
        }

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

    def do_GET(self):
        global requests_served
        with lock:
            requests_served += 1
        path = self.path.split("?", 1)[0]
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
            if s["source"] == "flights_js":
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
<tr><td>HTTP requests served</td><td>{s['requests_served']}</td></tr><tr><td>Uptime</td><td>{s['uptime_seconds']} sec</td></tr></table>
<h2>Endpoints</h2><p><a href=\"data/aircraft.json\">/data/aircraft.json</a><br><a href=\"aircraft.json\">/aircraft.json</a><br><a href=\"status\">/status</a><br><a href=\"health\">/health</a></p>
<p><small>This page refreshes every 5 seconds.</small></p></body></html>"""
            self.send_html(html)
            return
        self.send_json({"error": "not found", "path": path}, 404)


def main():
    if CFG["source"] == "sbs_30003":
        print(f"Input source: SBS/BaseStation TCP {CFG['receiver_host']}:{CFG['sbs_port']}", flush=True)
        print(f"Snapshot interval: {SBS_SNAPSHOT_INTERVAL} second", flush=True)
        threading.Thread(target=sbs_reader, daemon=True).start()
        threading.Thread(target=sbs_publisher, daemon=True).start()
    else:
        print(f"Input source: flights.js at {RECEIVER_URL}", flush=True)
        print(f"Poll interval: {CFG['poll_interval']} seconds", flush=True)
        threading.Thread(target=flights_js_updater, daemon=True).start()
    print(f"Serving on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
