#!/usr/bin/env python3
"""FR24 receiver -> dump1090/readsb-compatible HTTP bridge for Home Assistant OS."""

import ast
import json
import os
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


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    required = ("receiver_host", "username", "password")
    missing = [key for key in required if not str(cfg.get(key, "")).strip()]
    if missing:
        raise ValueError("Missing required option(s): " + ", ".join(missing))
    return {
        "receiver_host": str(cfg["receiver_host"]).strip(),
        "receiver_port": int(cfg.get("receiver_port", 80)),
        "username": str(cfg["username"]),
        "password": str(cfg["password"]),
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
            # FR24 zero altitude is ambiguous; do not synthesize "ground".
            if values[4]:
                ac["alt_baro"] = values[4]
            # FR24 exposes one altitude here; do not synthesize alt_geom.
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


def updater():
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


def iso_utc(timestamp):
    return None if timestamp is None else datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def human_utc(timestamp):
    return "Never" if timestamp is None else datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def snapshot_status():
    with lock:
        aircraft = latest_data.get("aircraft", [])
        success_time = last_success_time
        poll_ms = last_poll_duration_ms
        failures = consecutive_failures
        successes = total_successful_polls
        failed_polls = total_failed_polls
        served = requests_served
    now = time.time()
    age = None if success_time is None else max(0.0, now - success_time)
    positioned = sum(1 for ac in aircraft if ac.get("lat") is not None and ac.get("lon") is not None)
    if successes == 0 and failed_polls == 0:
        feed_status, receiver = "starting", "connecting"
    elif success_time is None or age > UNHEALTHY_AFTER_SECONDS:
        feed_status, receiver = "unhealthy", "disconnected"
    elif age > DEGRADED_AFTER_SECONDS:
        feed_status, receiver = "degraded", "stale"
    else:
        feed_status, receiver = "ok", "connected"
    return {
        "service_status": "ok",
        "feed_status": feed_status,
        "receiver": receiver,
        "uptime_seconds": round(now - START_TIME, 1),
        "poll_interval_seconds": CFG["poll_interval"],
        "last_success": iso_utc(success_time),
        "last_poll_age_seconds": None if age is None else round(age, 1),
        "last_poll_duration_ms": poll_ms,
        "consecutive_failures": failures,
        "successful_polls": successes,
        "failed_polls": failed_polls,
        "aircraft_total": len(aircraft),
        "aircraft_with_position": positioned,
        "aircraft_without_position": len(aircraft) - positioned,
        "requests_served": served,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Keep app logs useful; poll failures are logged separately.
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
            with lock:
                success = last_success_time
            age = "N/A" if s["last_poll_age_seconds"] is None else f'{s["last_poll_age_seconds"]:.1f} sec'
            poll_ms = "N/A" if s["last_poll_duration_ms"] is None else f'{s["last_poll_duration_ms"]} ms'
            html = f"""<!doctype html><html><head><meta charset=\"utf-8\"><meta http-equiv=\"refresh\" content=\"5\">
<title>FR24 to dump1090</title><style>
body{{font-family:sans-serif;max-width:760px;margin:40px auto;padding:0 20px;background:#111;color:#eee}}
table{{border-collapse:collapse;width:100%}}td{{padding:8px;border-bottom:1px solid #333}}td:first-child{{color:#aaa;width:45%}}
a{{color:#7db7ff}}.ok{{color:#6ddc79}}.starting{{color:#7db7ff}}.degraded{{color:#ffd166}}.unhealthy{{color:#ff6b6b}}
</style></head><body><h1>FR24 &rarr; dump1090</h1>
<p>Feed status: <strong class=\"{s['feed_status']}\">{s['feed_status'].upper()}</strong></p><table>
<tr><td>Service health</td><td><span class=\"ok\">OK</span></td></tr><tr><td>Receiver</td><td>{s['receiver']}</td></tr>
<tr><td>Last successful poll</td><td>{human_utc(success)}</td></tr><tr><td>Last poll age</td><td>{age}</td></tr>
<tr><td>Last poll duration</td><td>{poll_ms}</td></tr><tr><td>Poll interval</td><td>{s['poll_interval_seconds']} sec</td></tr>
<tr><td>Aircraft total</td><td>{s['aircraft_total']}</td></tr><tr><td>Aircraft with position</td><td>{s['aircraft_with_position']}</td></tr>
<tr><td>Aircraft without position</td><td>{s['aircraft_without_position']}</td></tr><tr><td>Consecutive failures</td><td>{s['consecutive_failures']}</td></tr>
<tr><td>Successful polls</td><td>{s['successful_polls']}</td></tr><tr><td>Failed polls</td><td>{s['failed_polls']}</td></tr>
<tr><td>HTTP requests served</td><td>{s['requests_served']}</td></tr><tr><td>Uptime</td><td>{s['uptime_seconds']} sec</td></tr></table>
<h2>Endpoints</h2><p><a href=\"/data/aircraft.json\">/data/aircraft.json</a><br><a href=\"/aircraft.json\">/aircraft.json</a><br><a href=\"/status\">/status</a><br><a href=\"/health\">/health</a></p>
<p><small>This page refreshes every 5 seconds.</small></p></body></html>"""
            self.send_html(html)
            return
        self.send_json({"error": "not found", "path": path}, 404)


def main():
    print(f"FR24 receiver: http://{CFG['receiver_host']}:{CFG['receiver_port']}/flights.js", flush=True)
    print(f"Poll interval: {CFG['poll_interval']} seconds", flush=True)
    print(f"Serving on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    threading.Thread(target=updater, daemon=True).start()
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
