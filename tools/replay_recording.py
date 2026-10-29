#!/usr/bin/env python3
"""Replay a normalized day recording locally, without sockets or wall-clock delays."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from motion_state import MotionEngine

def replay(path,events_path=None):
    now=[0];engine=None;previous={};counts=collections.Counter();snapshots=0;first=None;last=None
    opener=gzip.open if str(path).endswith('.gz') else open
    events=open(events_path,'w',encoding='utf-8') if events_path else None
    try:
        with opener(path,'rt',encoding='utf-8') as stream:
            header=json.loads(next(stream))
            metadata=header['recording_metadata'];source=metadata['source']
            engine=MotionEngine(source,clock=lambda:now[0])
            for line in stream:
                row=json.loads(line)
                if row.get('source')!=source:raise ValueError('Mixed source recording')
                now[0]=float(row['observed']);first=now[0] if first is None else first;last=now[0]
                engine.observe(row['aircraft'],now[0],row.get('source_now'),row.get('metadata'))
                state=engine.snapshot(now=now[0])
                for key,ac in state['aircraft'].items():
                    labels=tuple(sorted((p['name'],p.get('status','active')) for p in ac.get('patterns',[])))
                    if labels!=previous.get(key,()):
                        for name,status in labels:counts[name+':'+status]+=1
                        if events:events.write(json.dumps({'observed':now[0],'track_id':key,'patterns':ac.get('patterns',[])})+'\n')
                    previous[key]=labels
                snapshots+=1
    finally:
        if events:events.close()
    return {'source':source,'snapshots_replayed':snapshots,'first_observed':first,'last_observed':last,
        'pattern_entry_counts':dict(counts),'recorded_loss_counters':metadata.get('recording_status',{}),
        'note':'Replay uses the installed motion model; entry counts are label transitions, not distinct maneuvers.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording');parser.add_argument('--events',help='Optional local pattern-transition JSONL output')
    args=parser.parse_args();print(json.dumps(replay(args.recording,args.events),indent=2))
