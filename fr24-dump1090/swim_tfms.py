#!/usr/bin/env python3
"""Independent FAA SWIM transport and TFMS track parser for FR24 dump1090 Bridge.

This module interoperates with Solace PubSub+ using its public Python API.  It
contains no FAA JumpStart source code.
"""
from datetime import datetime
import math
import re
import threading
import time
import xml.etree.ElementTree as ET


def _local(tag):
    return tag.rsplit('}', 1)[-1].lower() if isinstance(tag, str) else ''


def _text_map(elem):
    out = {}
    for node in elem.iter():
        txt = (node.text or '').strip()
        if txt:
            out.setdefault(_local(node.tag), txt)
    return out


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coord(value, is_lat):
    """Parse decimal degrees or common TFMS DMS forms such as 412345N."""
    if value is None:
        return None
    v = str(value).strip().upper().replace(' ', '')
    try:
        x = float(v)
        if (-90 <= x <= 90) if is_lat else (-180 <= x <= 180):
            return x
    except ValueError:
        pass
    hemi = None
    if v and v[-1:] in 'NSEW':
        hemi, v = v[-1], v[:-1]
    elif v and v[:1] in 'NSEW':
        hemi, v = v[0], v[1:]
    nums = re.findall(r'\d+(?:\.\d+)?', v)
    if len(nums) >= 3:
        deg, minute, sec = map(float, nums[:3])
    elif len(nums) == 1:
        raw = nums[0]
        whole = raw.split('.')[0]
        degdigits = 2 if is_lat else 3
        if len(whole) < degdigits + 4:
            return None
        deg = float(whole[:degdigits]); minute = float(whole[degdigits:degdigits+2]); sec = float(raw[degdigits+2:])
    else:
        return None
    result = deg + minute / 60.0 + sec / 3600.0
    if hemi in ('S', 'W'):
        result = -result
    if (-90 <= result <= 90) if is_lat else (-180 <= result <= 180):
        return result
    return None


def _first(m, *names):
    for name in names:
        if name.lower() in m:
            return m[name.lower()]
    return None



def _attributes(elem):
    return {_local(k): v.strip() for k, v in elem.attrib.items()}


def _position_coord(track, is_lat):
    """Read current track position, including TFMS DMS attributes."""
    name = 'latitude' if is_lat else 'longitude'
    short = 'lat' if is_lat else 'lon'
    # Search current position only; nextEvent may describe a future waypoint.
    positions = [n for n in track.iter() if _local(n.tag) == 'position']
    scope = positions[0] if positions else track
    for node in scope.iter():
        if _local(node.tag) in (name, short):
            result = _coord((node.text or '').strip(), is_lat)
            if result is not None:
                return result
    for node in scope.iter():
        if _local(node.tag) == name + 'dms':
            attrs = _attributes(node)
            values = _text_map(node)
            values.update(attrs)
            deg = _number(values.get('degrees'))
            minute = _number(values.get('minutes'))
            sec = _number(values.get('seconds'))
            direction = values.get('direction', '').strip().upper()
            direction = {'NORTH': 'N', 'SOUTH': 'S', 'EAST': 'E', 'WEST': 'W'}.get(direction, direction)
            if (deg is None or minute is None or sec is None or
                    not all(math.isfinite(v) for v in (deg, minute, sec)) or
                    deg < 0 or not 0 <= minute < 60 or not 0 <= sec < 60 or
                    direction not in (('N', 'S') if is_lat else ('E', 'W'))):
                continue
            result = deg + minute / 60 + sec / 3600
            if direction in ('S', 'W'):
                result = -result
            limit = 90 if is_lat else 180
            if -limit <= result <= limit:
                return result
    return None


def parse_tfms_tracks(xml_text, diagnostics=None):
    """Return minimally normalized TFMS trackInformation records.

    Namespace-insensitive by design because TFMS payload namespace prefixes can
    vary. Unknown/missing fields are omitted rather than invented.
    """
    root = ET.fromstring(xml_text)
    records = []
    diag = {'message_types': {}, 'track_information': 0, 'positioned_tracks': 0,
            'missing_latitude': 0, 'missing_longitude': 0,
            'first_message_structure': [], 'first_track_structure': []}
    def structure(elem):
        # Names only: never include XML text or attribute values.
        return sorted({(_local(n.tag)[:80] + (
            '[' + ','.join(sorted(_local(k)[:80] for k in n.attrib)[:16]) + ']'
            if n.attrib else '')) for n in elem.iter()})[:128]
    all_messages = [e for e in root.iter() if _local(e.tag) == 'fltdmessage']
    if not all_messages and _local(root.tag) == 'fltdmessage':
        all_messages = [root]
    for msg in all_messages:
        m = _text_map(msg)
        attrs = _attributes(msg)
        msg_type = (attrs.get('msgtype') or attrs.get('messagetype') or
                    _first(m, 'msgtype', 'messagetype') or '').strip().lower()
        type_label = msg_type[:80] or '(missing)'
        # Bound per-payload diagnostic cardinality.
        if type_label not in diag['message_types'] and len(diag['message_types']) >= 32:
            type_label = '(other)'
        diag['message_types'][type_label] = diag['message_types'].get(type_label, 0) + 1
        if not diag['first_message_structure']:
            diag['first_message_structure'] = structure(msg)
        if msg_type != 'trackinformation':
            continue
        diag['track_information'] += 1
        if not diag['first_track_structure']:
            diag['first_track_structure'] = structure(msg)
        track = next((n for n in msg.iter() if _local(n.tag) == 'trackinformation'), msg)
        lat = _position_coord(track, True)
        lon = _position_coord(track, False)
        # Some TFMS forms wrap latitude/longitude in position elements but the
        # namespace-insensitive text map above still captures the leaf values.
        diag['missing_latitude'] += int(lat is None)
        diag['missing_longitude'] += int(lon is None)
        if lat is None or lon is None:
            continue
        flight = (_first(m, 'aircraftid', 'callsign', 'acid') or attrs.get('acid') or '').strip().upper()
        rec = {'lat': lat, 'lon': lon}
        for src, dst in (('airline','airline'),('deparpt','route_origin'),('arrarpt','route_destination')):
            if attrs.get(src): rec[dst] = attrs[src]
        rec['position_time'] = _first(m, 'timeatposition') or attrs.get('sourcetimestamp')
        for node in track.iter():
            na = _attributes(node)
            if _local(node.tag) == 'qualifiedaircraftid':
                for src, dst in (('aircraftcategory','aircraft_category'),('usercategory','user_category')):
                    if na.get(src): rec[dst] = na[src]
            if _local(node.tag) == 'eta' and na.get('timevalue'):
                rec['arrival_time'] = na['timevalue']
                rec['arrival_time_type'] = na.get('etatype', '')
            if _local(node.tag) == 'assignedaltitude':
                value = _first(_text_map(node), 'simplealtitude')
                if value: rec['assigned_altitude_raw'] = value

        if flight:
            rec['flight'] = flight
        alt = _number(_first(m, 'altitude', 'reportedaltitude', 'actualaltitude'))
        if alt is not None:
            # TFMS altitude is commonly expressed as flight level/hundreds of
            # feet. Preserve clearly foot-scaled values; expand FL-like values.
            rec['alt_baro'] = int(round(alt * 100 if abs(alt) < 1000 else alt))
        gs = _number(_first(m, 'speed', 'groundspeed'))
        if gs is not None:
            rec['gs'] = gs
        track = _number(_first(m, 'heading', 'track', 'course'))
        if track is not None:
            rec['track'] = track % 360
        # TFMS identity is not guaranteed to be an ICAO Mode-S address. Keep
        # occurrence identifiers as private metadata for later correlation.
        for src, dst in (('gufi','_tfms_gufi'), ('flightref','_tfms_flight_ref'), ('computerid','_tfms_computer_id')):
            value = _first(m, src) or attrs.get(src)
            if value:
                rec[dst] = value
        records.append(rec)
    diag['positioned_tracks'] = len(records)
    if diagnostics is not None:
        diagnostics.update(diag)
    return records, len(all_messages)


class SwimTfmsClient:
    """Small reusable SWIM/Solace transport wrapper for a durable FAA queue."""
    def __init__(self, config, on_payload, on_state):
        self.config = config
        self.on_payload = on_payload
        self.on_state = on_state
        self.service = None
        self.receiver = None
        self._stop = threading.Event()

    def run(self):
        from solace.messaging.messaging_service import MessagingService
        from solace.messaging.resources.queue import Queue
        from solace.messaging.config.transport_security_strategy import TLS
        from solace.messaging.config.retry_strategy import RetryStrategy
        cfg = self.config
        security = TLS.create().with_certificate_validation(False, True, '/etc/ssl/certs', '')
        retry = RetryStrategy.parametrized_retry(cfg['swim_retry_count'], cfg['swim_retry_interval_ms'])
        props = {
            'solace.messaging.transport.host': cfg['swim_host'],
            'solace.messaging.service.vpn-name': cfg['swim_vpn'],
            'solace.messaging.authentication.scheme.basic.username': cfg['swim_username'],
            'solace.messaging.authentication.scheme.basic.password': cfg['swim_password'],
        }
        self.service = (MessagingService.builder().from_properties(props)
                        .with_connection_retry_strategy(retry)
                        .with_reconnection_retry_strategy(retry)
                        .with_transport_security_strategy(security).build())
        self.on_state('connecting', None)
        self.service.connect()
        queue = Queue.durable_exclusive_queue(cfg['swim_queue'])
        self.receiver = self.service.create_persistent_message_receiver_builder().build(queue)
        self.receiver.start()
        self.on_state('connected', None)
        while not self._stop.is_set():
            message = self.receiver.receive_message(1000)
            if message is None:
                continue
            try:
                payload = message.get_payload_as_string()
                self.on_payload(payload)
                self.receiver.ack(message)
            except Exception as exc:
                # Do not ACK a payload we failed to process; the durable queue
                # may redeliver it after reconnect/restart.
                self.on_state('message_error', str(exc))
        self.on_state('stopping', None)

    def stop(self):
        self._stop.set()


def update_tfms_course(current, previous):
    if not previous:
        return current
    def epoch(record):
        try:
            value = datetime.fromisoformat(record['position_time'].replace('Z', '+00:00'))
            return value.timestamp() if value.tzinfo else None
        except (KeyError, ValueError, TypeError, AttributeError):
            return None
    before, after = epoch(previous), epoch(current)
    if before is not None and after is not None and after <= before:
        return previous
    if before is not None and after is not None and 0 < after-before <= 300:
        lat1, lat2 = math.radians(previous['lat']), math.radians(current['lat'])
        delta = math.radians(current['lon']-previous['lon'])
        a = math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(delta/2)**2
        distance = 3440.065*2*math.asin(math.sqrt(min(1,max(0,a))))
        if distance >= 0.05 and distance*3600/(after-before) <= 1200 and 'track' not in current:
            y = math.sin(delta)*math.cos(lat2)
            x = math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(delta)
            current['track'] = math.degrees(math.atan2(y,x)) % 360
            current['track_source'] = 'calculated'
        elif distance < 0.05 and 'track' not in current and 'track' in previous:
            current['track'] = previous['track']
            current['track_source'] = previous.get('track_source','reported')
    return current
