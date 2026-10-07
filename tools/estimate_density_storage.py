#!/usr/bin/env python3
"""Reproducible candidate-grid storage estimate; synthetic or saved aircraft snapshots.

Usage: python tools/estimate_density_storage.py [--snapshots DIR]
DIR contains dump1090 aircraft.json snapshots named in chronological order.
The synthetic run is a sizing scenario, never a claim about receiver observations.
"""
import argparse
import json
import math
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from traffic_density import FIELDS, SCHEMA, cell_id, empty


def snapshots(directory=None):
    if directory:
        for path in sorted(Path(directory).glob('*.json')):
            data=json.loads(path.read_text())
            yield float(data['now']),data['aircraft']
        return
    base=datetime(2026,10,1,tzinfo=timezone.utc)
    # 24 routes, 500 actual sampled points per route/day, 30 days = 360,000 observations.
    # ~145 m progression, small daily shifts, ~72 km route length, centered near 42 N.
    for day in range(30):
        for step in range(500):
            aircraft=[]
            for route in range(24):
                angle=2*math.pi*route/24
                distance=20+step*.145
                lat=42+distance*math.sin(angle)/111.32 + (day%7)*.0003
                lon=-77+distance*math.cos(angle)/(111.32*math.cos(math.radians(42)))+(day%5)*.0003
                aircraft.append({'hex':str(route),'lat':lat,'lon':lon,'alt_baro':1000 if route%3==0 else 10000 if route%3==1 else 30000})
            yield (base+timedelta(days=day,seconds=step)).timestamp(),aircraft


def estimate(directory=None):
    records={17:{},18:{}}
    observations=0
    for now,aircraft in snapshots(directory):
        day=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
        for ac in aircraft:
            try:
                keys={z:cell_id(ac['lat'],ac['lon'],z) for z in records}
            except (KeyError,ValueError,TypeError):
                continue
            observations+=1
            for z,key in keys.items():
                row=records[z].setdefault((key,day),empty())
                row['observation_count']+=1
                value=ac.get('alt_baro')
                try:
                    value=float(value)
                    if not math.isfinite(value):value=None
                except (ValueError,TypeError):value=None
                band='unknown' if value is None else 'below_1200_ft' if value<1200 else '1200_to_17999_ft' if value<18000 else '18000_ft_and_above'
                row[band]+=1
                row['passage_count']=1
                if value is not None:
                    row['min_ft']=value if row['min_ft'] is None else min(row['min_ft'],value)
                    row['max_ft']=value if row['max_ft'] is None else max(row['max_ft'],value)
                row['first_observed']=now if row['first_observed'] is None else min(row['first_observed'],now)
                row['last_observed']=now
    result={'scenario':'saved snapshots' if directory else 'synthetic routes, not receiver measurements','observations':observations,'candidates':[]}
    for z,rows in records.items():
        with tempfile.TemporaryDirectory() as temp:
            total=0
            for month in sorted({day[:7] for _,day in rows}):
                path=Path(temp)/f'{month}.dat';db=sqlite3.connect(path);db.executescript(SCHEMA)
                db.executemany('INSERT INTO metadata VALUES (?,?)',[('schema_version','1'),('base_zoom',str(z))])
                selected=[(key,day,*(v[k] for k in FIELDS)) for (key,day),v in sorted(rows.items()) if day[:7]==month]
                db.executemany('INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',selected)
                cells=sorted({row[0] for row in selected})
                db.executemany('INSERT INTO origins VALUES (?,?)',[(key,'01234567-89ab-cdef-0123-456789abcdef') for key in cells])
                db.commit();db.close();total+=path.stat().st_size
            # Altitude/passage increment cost: measured comparable table with only observations/time.
            path=Path(temp)/'minimal.db';db=sqlite3.connect(path)
            db.execute('CREATE TABLE daily(cell TEXT,day TEXT,observation_count INTEGER,first_observed REAL,last_observed REAL,PRIMARY KEY(cell,day))')
            db.execute('CREATE INDEX daily_day ON daily(day)')
            db.executemany('INSERT INTO daily VALUES (?,?,?,?,?)',[(key,day,v['observation_count'],v['first_observed'],v['last_observed']) for (key,day),v in sorted(rows.items())]);db.commit();db.close()
            # Comparable full daily table without origins/metadata.
            path_full=Path(temp)/'daily.db';db=sqlite3.connect(path_full);db.executescript(SCHEMA)
            db.executemany('INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',[(key,day,*(v[k] for k in FIELDS)) for (key,day),v in sorted(rows.items())]);db.commit();db.close()
            extra=path_full.stat().st_size-path.stat().st_size
        occupied=len({key for key,_ in rows})
        json_bytes=sum(len(json.dumps({'cell_id':key,'day':day,**v},separators=(',',':'))) for (key,day),v in rows.items())
        result['candidates'].append({'zoom':z,'cell_height_m':round(40075016.6856 / 2 / (1<<z),1),'cell_width_m_at_42N':round(40075016.6856*math.cos(math.radians(42))/(1<<z),1),
           'occupied_cells':occupied,'daily_cell_rows':len(rows),'sqlite_bytes':total,
           'bytes_per_daily_row':round(total/max(1,len(rows)),1),
           'extra_daily_altitude_passage_and_completeness_bytes_per_row':round(extra/max(1,len(rows)),1),
           'flat_daily_json_bytes':json_bytes,
           '18_month_bytes_if_each_month_matches_this_30_day_scenario':total*18})
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshots')
    args=parser.parse_args();print(json.dumps(estimate(args.snapshots),indent=2))
