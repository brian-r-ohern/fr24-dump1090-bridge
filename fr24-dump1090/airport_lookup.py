"""Local airport coordinates for map-only destination estimates."""
import json
import math
from pathlib import Path
import re
import threading


def normalize_code(value):
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if re.fullmatch(r'[A-Z0-9]{1,8}', code) else None


class AirportLookup:
    """Load once; prefer exact identifiers and reject ambiguous IATA aliases."""
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._index = None
        self._spatial = {}

    def _load(self):
        if self._index is not None:
            return
        with self._lock:
            if self._index is not None:
                return
            data = json.loads(self.path.read_text(encoding='utf-8'))
            rows = list(data.values()) if isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise ValueError('Airport data must contain airport records')
            identifiers, aliases = {}, {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = normalize_code(row.get('icao'))
                lat, lon = row.get('lat'), row.get('lon')
                if (not code or isinstance(lat, bool) or isinstance(lon, bool)
                    or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float))
                    or not math.isfinite(lat) or not math.isfinite(lon)
                    or not -90 <= lat <= 90 or not -180 <= lon <= 180):
                    continue
                record = {'icao': code, 'iata': normalize_code(row.get('iata')),
                          'name': str(row.get('name') or code), 'lat': lat, 'lon': lon}
                elevation=row.get('elevation_ft')
                if type(elevation) in (int,float) and math.isfinite(elevation) and -1500<=elevation<=30000:
                    record['elevation_ft']=elevation
                if row.get('airport_type'):record['airport_type']=str(row['airport_type'])
                if code in identifiers and identifiers[code] != record:
                    identifiers[code] = None
                else:
                    identifiers[code] = record
                for alias in (record['iata'], normalize_code(row.get('ident')), normalize_code(row.get('gps_code'))):
                    if alias:
                        aliases.setdefault(alias, {})[code] = record
            index = {}
            for code, matches in aliases.items():
                candidates = [record for canonical, record in matches.items()
                              if identifiers.get(canonical) == record]
                index[code] = candidates[0] if len(matches) == 1 and len(candidates) == 1 else None
            index.update(identifiers)
            for record in identifiers.values():
                if record:
                    bucket=(math.floor(record['lat']), math.floor(record['lon']))
                    self._spatial.setdefault(bucket, []).append(record)
            self._index = index

    def lookup_many(self, codes):
        if len(codes) > 256:
            raise ValueError('At most 256 airport codes per request')
        self._load()
        return {code: self._index.get(code) for value in codes
                if (code := normalize_code(value))}

    def nearby(self, lat, lon):
        """Small spatial grid for airport context; exact distance checked by caller."""
        self._load()
        width=min(180, math.ceil(1/max(.01, math.cos(math.radians(lat)))))
        result=[]
        for y in range(max(-90,math.floor(lat)-1), min(89,math.floor(lat)+1)+1):
            for x in range(math.floor(lon)-width,math.floor(lon)+width+1):
                result.extend(self._spatial.get((y,(x+180)%360-180),[]))
        return result
