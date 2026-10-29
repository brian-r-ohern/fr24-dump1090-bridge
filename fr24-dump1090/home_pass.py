"""Bounded closest approach to a fixed Home location using observed 3D velocity."""
import math
from proximity import state,xy,number,NM

def home_passes(payload,home,horizon_seconds=300,radius_nm=3):
    if not home or not all(number(home.get(k)) for k in ('latitude','longitude','elevation_m')):return {}
    source=payload['source']
    if source not in ('sbs_30003','aircraft_json','swim_sfdps'):return {}
    now=payload['generated_at'];out={};fresh=45 if source=='swim_sfdps' else 15
    for key,track in payload['tracks'].items():
        s=state(track,now,fresh,source)
        if not s or not all(number(s.get(k)) for k in ('vx','vy','altitude','vertical_rate')):continue
        vx,vy=s['vx'],s['vy'];vz=s['vertical_rate']*.3048
        if math.hypot(vx,vy)<30*.514444:continue
        x,y=xy(s['last'],{'lat':home['latitude'],'lon':home['longitude']})
        z=s['altitude']*.3048-home['elevation_m']
        # Bring fresh source position forward to display time before predicting.
        x+=vx*s['age'];y+=vy*s['age'];z+=vz*s['age']
        dot=x*vx+y*vy+z*vz;v2=vx*vx+vy*vy+vz*vz
        if dot>=0:continue
        raw=-dot/v2;t=min(horizon_seconds,raw)
        horizontal=math.hypot(x+vx*t,y+vy*t);vertical=z+vz*t
        if vertical < -152.4:continue  # Do not highlight a projection through the ground.
        slant=math.hypot(horizontal,vertical)/NM
        if slant>radius_nm:continue
        out[key]={'slant_nm':round(slant,3),'horizontal_nm':round(horizontal/NM,3),
          'vertical_ft':round(abs(vertical)/.3048),'seconds':round(t,1),
          'horizon_seconds':horizon_seconds,'radius_nm':radius_nm,'horizon_limited':raw>horizon_seconds,
          'altitude_basis':s['altitude_field'],'quality':'maneuvering_reduces_confidence' if s['maneuvering'] else 'constant_velocity_baseline',
          'model':'constant observed 3D velocity; aircraft altitude relative to configured Home elevation; approximate',
          'predicted_at':now,'position_age_seconds':round(s['age'],1)}
    return out
