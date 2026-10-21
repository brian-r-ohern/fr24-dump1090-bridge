"""Selected-aircraft separation and bounded constant-velocity closest approach.

Informational analysis only. No collision alerts or separation-minimum inference.
"""
import math
from airport_context import distance_nm
EARTH=6371008.8
NM=1852

def number(v):return type(v) in (int,float) and math.isfinite(v)
def xy(p,origin):
    return (EARTH*math.radians((p['lon']-origin['lon']+180)%360-180)*math.cos(math.radians(origin['lat'])),EARTH*math.radians(p['lat']-origin['lat']))
def slope(rows,field):
    values=[(r['t'],r[field]) for r in rows if number(r.get(field))]
    if len(values)<3 or values[-1][0]-values[0][0]<20:return None
    center=sum(t for t,v in values)/len(values)
    denom=sum((t-center)**2 for t,v in values)
    return sum((t-center)*v for t,v in values)/denom if denom else None

def state(track,now,fresh,source):
    rows=track.get('samples',[])
    if not rows:return None
    last=rows[-1];age=now-last['t']
    if not 0<=age<=fresh or not number(last.get('lat')) or not number(last.get('lon')):return None
    rows=[r for r in rows if r.get('segment')==last.get('segment') and last['t']-r['t']<=90]
    # Last observation stays available even before velocity support is sufficient.
    enriched=[]
    for r in rows:
        x,y=xy(r,last);enriched.append({**r,'x':x,'y':y})
    vx,vy=slope(enriched,'x'),slope(enriched,'y')
    if vx is not None and vy is not None:
        speed=math.hypot(vx,vy)
        if speed>1500*.514444: vx=vy=None
        elif source=='swim_sfdps' and speed>.5 and number(last.get('reported_speed_knots')) and 0<=last['reported_speed_knots']<=1500:
            scale=last['reported_speed_knots']*.514444/speed;vx*=scale;vy*=scale
    motion=last.get('motion',{})
    maneuvering=bool(motion.get('patterns')) or any(p.get('name') in ('turning_left','turning_right','accelerating','decelerating') for p in motion.get('primitives',[]))
    altitude_field='alt_baro' if number(last.get('alt_baro')) else 'alt_geom' if number(last.get('alt_geom')) else None
    altitude=last.get(altitude_field) if altitude_field else None
    rate=slope(rows,altitude_field) if altitude_field else None
    if rate is not None and abs(rate)>10000/60:rate=None
    return dict(last=last,age=age,vx=vx,vy=vy,altitude_field=altitude_field,altitude=altitude,vertical_rate=rate,maneuvering=maneuvering)

def proximity_view(payload,selected,now=None,radius_nm=10,horizon_seconds=300,limit=10):
    now=payload['generated_at'] if now is None else now;source=payload['source']
    result=dict(source=source,selected=selected,generated_at=now,radius_nm=radius_nm,horizon_seconds=horizon_seconds,informational_only=True,model='constant ground velocity; no intent or collision warning',pairs=[])
    if source not in ('sbs_30003','aircraft_json','swim_sfdps'):
        return {**result,'reason':'source_precision_or_cadence_excluded'}
    fresh=45 if source=='swim_sfdps' else 15
    tracks=payload['tracks'];result['selected_identity']=dict(tracks.get(selected,{}).get('identity',{}));a=state(tracks.get(selected,{}),now,fresh,source)
    if not a:return {**result,'reason':'selected_position_missing_or_stale'}
    for key,track in tracks.items():
        if key==selected:continue
        b=state(track,now,fresh,source)
        if not b:continue
        # Both positions are extrapolated only as far as the newer source timestamp.
        common=max(a['last']['t'],b['last']['t']);da=common-a['last']['t'];db=common-b['last']['t']
        velocity=all(number(s[k]) for s in (a,b) for k in ('vx','vy'))
        if (da or db) and not velocity:continue
        x,y=xy(b['last'],a['last'])
        if velocity:x+=b['vx']*db-a['vx']*da;y+=b['vy']*db-a['vy']*da
        separation=math.hypot(x,y)
        if separation>radius_nm*NM:continue
        pair=dict(track_id=key,flight=track.get('identity',{}).get('flight') or key,horizontal_nm=round(separation/NM,3),common_time=common,selected_age_seconds=round(a['age'],1),other_age_seconds=round(b['age'],1),alignment_seconds=round(max(da,db),1),vertical_ft=None,vertical_at_cpa_ft=None,cpa_nm=None,tcpa_seconds=None,trend='unknown',quality='insufficient_velocity',horizon_limited=False,altitude_basis=None)
        same_altitude=a['altitude_field'] is not None and a['altitude_field']==b['altitude_field']
        dz=None;vz=None
        if same_altitude:
            pair['altitude_basis']=a['altitude_field']
            if (da==0 or a['vertical_rate'] is not None) and (db==0 or b['vertical_rate'] is not None):
                dz=b['altitude']+(b['vertical_rate'] or 0)*db-a['altitude']-(a['vertical_rate'] or 0)*da
                pair['vertical_ft']=round(abs(dz))
            if a['vertical_rate'] is not None and b['vertical_rate'] is not None:vz=b['vertical_rate']-a['vertical_rate']
        pair['slant_nm']=round(math.hypot(separation,dz*.3048)/NM,3) if dz is not None else None
        if velocity:
            vx=b['vx']-a['vx'];vy=b['vy']-a['vy'];v2=vx*vx+vy*vy;dot=x*vx+y*vy
            pair['quality']='maneuvering_reduces_confidence' if a['maneuvering'] or b['maneuvering'] else 'constant_velocity_baseline'
            closing=-dot/separation if separation>.1 else 0
            pair['closing_knots']=round(closing/.514444,1)
            pair['trend']='closing' if closing>.5 else 'opening' if closing<-.5 else 'nearly_steady'
            if v2>=.25:
                unconstrained=-dot/v2
                if unconstrained>=0:
                    t=min(horizon_seconds,unconstrained);pair['horizon_limited']=unconstrained>horizon_seconds
                    pair['tcpa_seconds']=round(t,1);pair['cpa_nm']=round(math.hypot(x+vx*t,y+vy*t)/NM,3)
                    if dz is not None and vz is not None:pair['vertical_at_cpa_ft']=round(abs(dz+vz*t))
                else:pair['prediction_reason']='closest_approach_already_past'
            else:pair['prediction_reason']='relative_velocity_too_small'
        result['pairs'].append(pair)
    result['pairs']=sorted(result['pairs'],key=lambda p:(p['slant_nm'] is None,p['slant_nm'] if p['slant_nm'] is not None else p['horizontal_nm'],p['track_id']))[:limit]
    result['reason']='ok';return result
