"""Lossless analytical history wrapped in GIS-friendly GeoJSON geometry.

The retained record is authoritative; geometry is a 2D visualization only.
"""
from copy import deepcopy
import math

def valid_position(p):
    return all(type(p.get(k)) in (int,float) and math.isfinite(p[k]) and abs(p[k])<=bound for k,bound in (("lat",90),("lon",180)))

def geometry(samples):
    runs=[];run=[];previous=None
    for p in samples:
        if not valid_position(p):
            if run:runs.append(run)
            run=[];previous=None;continue
        if previous and (p.get('segment')!=previous.get('segment') or p.get('break_reason') or p['t']-previous['t']>30 or p['t']<=previous['t'] or abs(p['lon']-previous['lon'])>180):
            if run:runs.append(run)
            run=[]
        run.append([p['lon'],p['lat']]);previous=p
    if run:runs.append(run)
    lines=[x for x in runs if len(x)>1];points=[x[0] for x in runs if len(x)==1]
    parts=[]
    if lines:parts.append({'type':'MultiLineString','coordinates':lines})
    if points:parts.append({'type':'MultiPoint','coordinates':points})
    if not parts:return None
    if len(parts)==1:return parts[0]
    return {'type':'GeometryCollection','geometries':parts}

def history_geojson(payload):
    features=[]
    for key,track in payload['tracks'].items():
        identity=track.get('identity',{});samples=track.get('samples',[])
        props={k:identity.get(k) for k in ('flight','icao_address','route_origin','route_destination')}
        props.update(track_id=key,source=payload.get('source'),sample_count=len(samples),start_time=samples[0]['t'] if samples else None,end_time=samples[-1]['t'] if samples else None,record=deepcopy(track))
        features.append({'type':'Feature','id':key,'geometry':geometry(samples),'properties':props})
    return {'type':'FeatureCollection','history_geojson_version':1,'history_metadata':deepcopy({k:v for k,v in payload.items() if k!='tracks'}),'features':features}

def history_from_geojson(payload):
    if payload.get('type')!='FeatureCollection':return payload
    if payload.get('history_geojson_version')!=1:raise ValueError('Unsupported analytical GeoJSON schema')
    result=deepcopy(payload['history_metadata']);tracks={}
    for f in payload['features']:
        key=f['properties']['track_id']
        if key in tracks:raise ValueError('Duplicate analytical track identifier')
        tracks[key]=deepcopy(f['properties']['record'])
    result['tracks']=tracks
    return result
