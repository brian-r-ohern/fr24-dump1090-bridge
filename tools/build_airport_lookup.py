#!/usr/bin/env python3
"""Convert the PDDL airport-codes CSV to a minimal local lookup snapshot."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def convert(source):
    records = []
    with Path(source).open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['type'] == 'closed':
                continue
            # This CSV stores latitude, longitude (not GeoJSON coordinate order).
            try:
                lat, lon = map(float, row['coordinates'].split(','))
            except (ValueError, KeyError):
                continue
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                continue
            code = row.get('icao_code') or row.get('gps_code') or row['ident']
            try:elevation=float(row.get('elevation_ft') or 'nan')
            except ValueError:elevation=float('nan')
            elevation=elevation if math.isfinite(elevation) and -1500<=elevation<=30000 else None
            records.append({'elevation_ft':elevation,'airport_type':row['type'],'icao': code, 'iata': row.get('iata_code') or '',
                            'ident': row['ident'], 'gps_code': row.get('gps_code') or '',
                            'name': row['name'], 'lat': lat, 'lon': lon})
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv')
    parser.add_argument('json')
    args = parser.parse_args()
    records = convert(args.csv)
    Path(args.json).write_text(json.dumps(records, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    print(json.dumps({'records': len(records), 'source_sha256': hashlib.sha256(Path(args.csv).read_bytes()).hexdigest(),
                      'output_sha256': hashlib.sha256(Path(args.json).read_bytes()).hexdigest()}))
