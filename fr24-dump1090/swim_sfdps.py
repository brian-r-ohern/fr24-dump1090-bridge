"""Local SFDPS FIXM 3.x surveillance view parser (no export or persistence).

Reads the observed enRoute position, never targetPosition or planned waypoints.
Prefixes are ignored; element scope, CRS, units and observation time are checked.
"""
from datetime import datetime
import math
import xml.etree.ElementTree as ET


def local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def child(node, name):
    return next((n for n in node if local(n.tag) == name), None) if node is not None else None


def path(node, *names):
    for name in names:
        node = child(node, name)
    return node


def text(node):
    return (node.text or '').strip() if node is not None else ''


def measure(node, unit):
    if node is None or node.get('uom', '').upper() != unit:
        return None
    try:
        value = float(text(node))
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def parse_sfdps_tracks(payload, diagnostics=None):
    root = ET.fromstring(payload)
    flights = [n for n in root.iter() if local(n.tag) == 'flight']
    diag = {'message_types': {}, 'track_information': 0, 'positioned_tracks': 0,
            'missing_latitude': 0, 'missing_longitude': 0,
            'first_message_structure': [], 'first_track_structure': [],
            'invalid_position_time': 0, 'unsupported_crs': 0, 'non_surveillance': 0}
    records = []
    for flight in flights:
        label = flight.get('source', '(missing)')[:80]
        if label not in diag['message_types'] and len(diag['message_types']) >= 32:
            label = '(other)'
        diag['message_types'][label] = diag['message_types'].get(label, 0) + 1
        if not diag['first_message_structure']:
            diag['first_message_structure'] = sorted({local(n.tag) for n in flight.iter()})[:128]
        position = path(flight, 'enRoute', 'position')
        if position is None:
            continue
        diag['track_information'] += 1
        if not diag['first_track_structure']:
            diag['first_track_structure'] = sorted({local(n.tag) for n in position.iter()})[:128]
        if position.get('reportSource') != 'SURVEILLANCE':
            diag['non_surveillance'] += 1
            continue
        location = path(position, 'position', 'location')
        if location is None or location.get('srsName') not in ('urn:ogc:def:crs:EPSG::4326', 'EPSG:4326'):
            diag['unsupported_crs'] += 1
            continue
        try:
            lat, lon = map(float, text(child(location, 'pos')).split())
            valid = math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
        except ValueError:
            valid = False
        if not valid:
            diag['missing_latitude'] += 1
            diag['missing_longitude'] += 1
            continue
        timestamp = position.get('positionTime', '')
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                raise ValueError('unqualified time')
            epoch = dt.timestamp()
        except (ValueError, OverflowError):
            diag['invalid_position_time'] += 1
            continue
        gufi = text(child(flight, 'gufi'))
        identity = child(flight, 'flightIdentification')
        callsign = identity.get('aircraftIdentification', '').strip().upper() if identity is not None else ''
        if not gufi:
            # Callsigns alone are not a reliable flight-occurrence identity.
            continue
        rec = {'lat': lat, 'lon': lon, 'position_time': timestamp,
               '_tfms_gufi': gufi, '_position_epoch': epoch, 'flight': callsign,
               'report_source': 'SURVEILLANCE'}
        altitude = measure(child(position, 'altitude'), 'FEET')
        if altitude is not None:
            rec['alt_baro'] = round(altitude)
        speed = measure(path(position, 'actualSpeed', 'surveillance'), 'KNOTS')
        if speed is not None and speed >= 0:
            rec['gs'] = speed
        # Preserve no unverified axis-to-heading conversion. Course is derived
        # from two actual time-qualified positions by the shared view updater.
        for name, attr, field in (('departure', 'departurePoint', 'route_origin'),
                                  ('arrival', 'arrivalPoint', 'route_destination')):
            node = child(flight, name)
            if node is not None and node.get(attr):
                rec[field] = node.get(attr)
        organization = path(flight, 'operator', 'operatingOrganization', 'organization')
        if organization is not None and organization.get('name'):
            rec['airline'] = organization.get('name')
        for node in flight.iter():
            if local(node.tag) == 'nameValue' and node.get('name') == 'ADSB_02M_52B':
                value = node.get('value', '').lstrip('+-').lower()
                if len(value) == 6 and all(c in '0123456789abcdef' for c in value):
                    rec['icao_address'] = value
        records.append(rec)
    diag['positioned_tracks'] = len(records)
    if diagnostics is not None:
        diagnostics.update(diag)
    return records, len(flights)
