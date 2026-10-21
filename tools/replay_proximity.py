#!/usr/bin/env python3
"""Evaluate a selected track against contemporaneous recorded observations only."""
import argparse,json,sys
from collections import deque
from itertools import groupby
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from proximity import proximity_view
from replay_aircraft_history import load_history

def replay_proximity(payload,selector):
 tracks=payload['tracks'];keys=[k for k,t in tracks.items() if k==selector or t.get('identity',{}).get('flight','').strip().lower()==selector.lower()]
 if len(keys)!=1:raise ValueError('Select exactly one local track identifier or unique flight callsign')
 selected=keys[0];retained={};views=[]
 observations=sorted((p['t'],key,p) for key,track in tracks.items() for p in track['samples'])
 for t,group in groupby(observations,key=lambda x:x[0]):
  changed=set()
  for _,key,p in group:
   track=retained.setdefault(key,{'identity':tracks[key].get('identity',{}),'samples':deque(maxlen=360)})
   track['samples'].append(p);changed.add(key)
   while track['samples'] and t-track['samples'][0]['t']>120:track['samples'].popleft()
  if selected in changed:
   views.append(proximity_view({'source':payload['source'],'generated_at':t,'tracks':retained},selected))
 return {'source':payload['source'],'selected':selected,'purpose':'offline informational evaluation; no encounter ground truth','frames':views,'frames_with_pairs':sum(bool(v['pairs']) for v in views)}

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('input',type=Path);parser.add_argument('--track',required=True);parser.add_argument('-o','--output',required=True,type=Path);args=parser.parse_args()
 args.output.write_text(json.dumps(replay_proximity(load_history(args.input),args.track),separators=(',',':'))+'\n')
