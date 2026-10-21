"""Bounded analytical observations, independent of motion qualification."""
from airport_context import classify_airport_context, classify_destination_movement
from collections import OrderedDict, deque
import copy
import ipaddress
import threading
import time
from motion_state import number, timestamp, leg, KNOT_MPS

DEFAULT_NETWORKS='127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7'

def allowed_peer(peer, networks=DEFAULT_NETWORKS):
    try:
        address=ipaddress.ip_address(peer)
        if getattr(address,'ipv4_mapped',None):address=address.ipv4_mapped
        return any(address in ipaddress.ip_network(n.strip()) for n in networks.split(',') if n.strip())
    except ValueError:return False

class TrackHistory:
    def __init__(self,source,clock=time.time):
        self.source,self.clock=source,clock
        self.lock=threading.RLock();self.tracks=OrderedDict()
    def prune(self,now):
        for key,track in list(self.tracks.items()):
            while track['samples'] and now-track['samples'][0]['t']>3600:track['samples'].popleft()
            if not track['samples']:del self.tracks[key]
    def observe(self,aircraft,received,source_now=None,metadata=None):
        metadata=metadata or {};source_now=number(source_now) or received
        with self.lock:
            self.prune(received)
            for ac in aircraft:
                key=str(ac.get('hex') or '').strip().lower()
                lat,lon=number(ac.get('lat')),number(ac.get('lon'))
                if not key or len(key)>64 or lat is None or lon is None or not(-90<=lat<=90 and -180<=lon<=180):continue
                meta=metadata.get(key,{})
                explicit=timestamp(meta.get('position_time')) or timestamp(ac.get('position_time'))
                if self.source=='swim_sfdps' and explicit is None:continue
                age=number(ac.get('seen_pos'))
                t=explicit if explicit is not None else source_now-age if age is not None and age>=0 else received
                if t<=0 or t>received+5 or received-t>3600:continue
                track=self.tracks.get(key)
                if track is None:
                    if len(self.tracks)>=1024:self.tracks.popitem(last=False)
                    track={'samples':deque(maxlen=360),'segment':1,'identity':{}};self.tracks[key]=track
                points=track['samples'];prev=points[-1] if points else None
                if prev and (t<=prev['t'] or (t-prev['t']<10)):continue
                if prev and explicit is None and age is None and lat==prev['lat'] and lon==prev['lon']:continue
                reason=None
                if prev:
                    if meta.get('occurrence') and prev.get('occurrence') and meta['occurrence']!=prev['occurrence']:reason='occurrence_change'
                    elif t-prev['t']>(45 if self.source=='swim_sfdps' else 120 if self.source=='swim_tfms' else 30):reason='observation_gap'
                    elif leg(prev,{'lat':lat,'lon':lon})[0]/(t-prev['t'])/KNOT_MPS>1500:reason='position_discontinuity'
                    if reason:track['segment']+=1
                row={'t':t,'received_at':received,'lat':lat,'lon':lon,'segment':track['segment'],'break_reason':reason,
                     'position_time_basis':'source_position_time' if explicit is not None else 'snapshot_minus_seen_pos' if age is not None else 'receipt_assumption',
                     'alt_baro':ac.get('alt_baro'),'alt_geom':ac.get('alt_geom'),'reported_speed_knots':number(ac.get('gs')),
                     'reported_track_degrees':number(ac.get('track')),'reported_vertical_rate_fpm':number(ac.get('baro_rate')),
                     'occurrence':meta.get('occurrence'),'field_metadata':copy.deepcopy(meta),
                     'derived_ground_speed_knots':round(leg(prev,{'lat':lat,'lon':lon})[0]/(t-prev['t'])/KNOT_MPS,3) if prev and not reason else None}
                row['destination_code']=str(ac.get('route_destination') or ac.get('destination') or track['identity'].get('route_destination') or track['identity'].get('destination') or '').strip().upper()
                points.append(row)
                track['identity'].update({k:ac[k] for k in ('flight','registration','aircraft_type','origin','destination','route_origin','route_destination','icao_address','aircraft_category') if ac.get(k) is not None})
                self.tracks.move_to_end(key)
    def resolve_hex(self,hex_code):
        with self.lock:
            self.prune(self.clock())
            return [k for k,v in self.tracks.items() if k==hex_code or str(v['identity'].get('icao_address','')).lower()==hex_code]
    def annotate(self,engine,received,airports=None):
        with self.lock,engine.lock:
            for key,track in self.tracks.items():
                if key in engine.tracks and track['samples'] and track['samples'][-1]['received_at']!=received:
                    engine.tracks[key]['state'].pop('destination_movement',None)
                    movement=track['samples'][-1].get('motion',{}).get('destination_movement')
                    if movement and engine.tracks[key]['state'].get('quality')!='stale':engine.tracks[key]['state']['destination_movement']=copy.deepcopy(movement)
                    context=track['samples'][-1].get('motion',{}).get('airport_context')
                    if context:engine.tracks[key]['state']['airport_context']=copy.deepcopy(context)
                if track['samples'] and track['samples'][-1]['received_at']==received and key in engine.tracks:
                    state=engine.tracks[key]['state']
                    track['samples'][-1]['motion']={k:copy.deepcopy(state[k]) for k in ('quality','metrics','primitives','patterns','speed_diagnostics') if k in state}
                    if airports is not None:
                        movement=classify_destination_movement(track['identity'],list(track['samples']),airports)
                        state.pop('destination_movement',None)
                        if movement:
                            state['destination_movement']=movement
                            track['samples'][-1]['motion']['destination_movement']=copy.deepcopy(movement)
                        context=classify_airport_context(track['identity'],list(track['samples']),airports)
                        state.pop('airport_context',None)
                        if context:
                            state['airport_context']=context
                            track['samples'][-1]['motion']['airport_context']=copy.deepcopy(context)
    def snapshot(self,keys=None):
        with self.lock:
            self.prune(self.clock())
            selected=list(self.tracks) if keys is None else keys
            return {'schema_version':1,'source':self.source,'generated_at':self.clock(),'history_seconds':3600,
                    'sample_interval_seconds':10,'max_samples_per_track':360,'transient':True,
                    'purpose':'personal retention and non-operational analysis','termination_semantics':'last observation is not proof of landing',
                    'tracks':{k:copy.deepcopy({'identity':self.tracks[k]['identity'],'samples':list(self.tracks[k]['samples'])}) for k in selected if k in self.tracks}}

    def kinematic_snapshot(self):
        """Small analytical view: omit verbose per-observation diagnostic payloads."""
        with self.lock:
            now=self.clock();self.prune(now)
            fields=('t','lat','lon','segment','alt_baro','alt_geom','reported_speed_knots')
            tracks={}
            for key,track in self.tracks.items():
                if not track['samples']:continue
                end=track['samples'][-1]['t']
                rows=[{f:p.get(f) for f in fields} for p in track['samples'] if end-p['t']<=120]
                latest=track['samples'][-1].get('motion',{})
                rows[-1]['motion']={f:copy.deepcopy(latest.get(f,[])) for f in ('patterns','primitives')}
                tracks[key]={'identity':dict(track['identity']),'samples':rows}
            return {'source':self.source,'generated_at':now,'tracks':tracks}
