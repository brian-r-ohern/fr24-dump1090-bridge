#!/usr/bin/env python3
"""Replay analytical JSON through motion geometry without connecting to a feed."""
import argparse,json,sys,gzip,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from motion_state import MotionEngine
from history_geojson import history_from_geojson

def load_history(path):
    """Read plain JSON, gzip JSON or a ZIP containing exactly one JSON member."""
    path=Path(path)
    with path.open('rb') as stream: magic=stream.read(4)
    if magic[:2]==b'\x1f\x8b':
        with gzip.open(path,'rt',encoding='utf-8') as stream:return history_from_geojson(json.load(stream))
    if magic[:2]==b'PK':
        with zipfile.ZipFile(path) as archive:
            names=[n for n in archive.namelist() if n.lower().endswith(('.json','.geojson')) and not n.startswith('__MACOSX/')]
            if len(names)!=1:raise ValueError('History ZIP must contain exactly one JSON file')
            with archive.open(names[0]) as stream:return history_from_geojson(json.load(stream))
    return history_from_geojson(json.loads(path.read_text()))


def replay(payload):
    if payload.get('schema_version')!=1 or not isinstance(payload.get('tracks'),dict):raise ValueError('Unsupported history schema')
    now=[0.];engine=MotionEngine(payload['source'],clock=lambda:now[0]);result=[]
    # Feed chronologically; never use later observations to classify an earlier point.
    observations=sorted((p['t'],key,p) for key,track in payload['tracks'].items() for p in track['samples'])
    previous={}
    for t,key,p in observations:
        now[0]=t
        if key in engine.tracks and previous.get(key)!=p['segment']:engine._reset(engine.tracks[key],p.get('break_reason') or 'recorded_segment_boundary')
        previous[key]=p['segment']
        ac={'hex':key,'lat':p['lat'],'lon':p['lon'],'gs':p.get('reported_speed_knots'),'alt_baro':p.get('alt_baro'),'alt_geom':p.get('alt_geom'),'seen_pos':0}
        metadata={**p.get('field_metadata',{}),'position_time':t}
        engine.observe([ac],t,t,{key:metadata})
        state=engine.snapshot([key],now=t,include_events=True)['aircraft'].get(key)
        result.append({'t':t,'track_id':key,'state':state})
    return {'source':payload['source'],'purpose':'offline motion replay; not a touchdown outcome label','observations':result}
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('input',type=Path);parser.add_argument('-o','--output',required=True,type=Path);args=parser.parse_args()
    args.output.write_text(json.dumps(replay(load_history(args.input)),separators=(',',':'))+'\n')
