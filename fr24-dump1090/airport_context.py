"""Conservative airport context; never replaces geometric observations or infers clearance."""
import math


def distance_nm(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    dlat = lat2-lat1; dlon = math.radians(b['lon']-a['lon'])
    h = math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 3440.065*2*math.asin(min(1, math.sqrt(max(0, h))))


def classify_airport_context(identity, samples, airports):
    """Require fresh contiguous history, known elevation and sustained altitude trend.

    Candidates include route endpoints and nearby airports. Relative altitude is a
    reported barometric altitude minus field elevation, not measured radar AGL.
    """
    if len(samples)<3:return None
    latest=samples[-1]
    if type(latest.get('alt_baro')) not in (int,float) or not math.isfinite(latest['alt_baro']):return None
    recent=[s for s in samples if latest['t']-s['t']<=120 and s['segment']==latest['segment']]
    valid=[s for s in recent if type(s.get('alt_baro')) in (int,float) and math.isfinite(s['alt_baro'])]
    if len(valid)<3 or valid[-1]['t']-valid[0]['t']<30:return None
    if latest.get('motion',{}).get('quality')=='stale':return None
    span=valid[-1]['t']-valid[0]['t']
    rate=(valid[-1]['alt_baro']-valid[0]['alt_baro'])*60/span
    origin=str(identity.get('route_origin') or identity.get('origin') or '').upper()
    destination=str(identity.get('route_destination') or identity.get('destination') or '').upper()
    candidates=airports.lookup_many([origin,destination])
    nearby=airports.nearby(latest['lat'],latest['lon']) if hasattr(airports,'nearby') else []
    records={a['icao']:a for a in [*candidates.values(),*nearby] if a}
    labels=[]
    for airport in records.values():
        elevation=airport.get('elevation_ft')
        if type(elevation) not in (int,float):continue
        height=valid[-1]['alt_baro']-elevation
        if height < -500:continue
        distance=distance_nm(latest,airport)
        change=distance-distance_nm(valid[0],airport)
        aliases={airport['icao'],airport.get('iata')}
        name=None
        if destination in aliases and distance<=60 and height<=18000 and rate<=-300 and change<=-.5:
            name='likely_approach'
        elif origin in aliases and distance<=40 and height<=18000 and rate>=300 and change>=.5:
            name='likely_departure'
        elif distance<=10 and height<=4000:
            motion=latest.get('motion',{});patterns=motion.get('patterns',[])
            turning=any(p.get('name') in ('turning_left','turning_right') for p in motion.get('primitives',[])) or bool(patterns)
            turns={p.get('first_supported') for s in samples if latest['t']-s['t']<=900 and s['segment']==latest['segment'] for p in s.get('motion',{}).get('patterns',[]) if abs(p.get('evidence',{}).get('cumulative_turn_degrees',p.get('evidence',{}).get('turn_degrees',0)))>=135}
            if turning:name='possible_airport_circuit' if len(turns)>=2 else 'likely_airport_maneuvering'
        if name:
            labels.append((0 if name in ('likely_approach','likely_departure') else 1,distance,dict(name=name,airport=airport['icao'],distance_nm=round(distance,1),height_above_airport_ft=round(height),vertical_trend_fpm=round(rate),distance_change_nm=round(change,2),support_seconds=round(span),basis='route, proximity and observed motion; intent unconfirmed')))
    return min(labels,key=lambda x:(x[0],x[1]))[2] if labels else None


def classify_destination_movement(identity, samples, airports):
    """Radial movement relative to the last reported destination, never intent.

    A 60–120 second window supports direction; divergence needs 180–300
    seconds and at least 2 NM of predominantly increasing range. Established
    racetracks/repeated orbits suppress divergence, but retain radial direction.
    """
    destination=str(identity.get('route_destination') or identity.get('destination') or '').strip().upper()
    if not destination or not samples:return None
    airport=airports.lookup_many([destination]).get(destination)
    if not airport:return None
    latest=samples[-1]
    if latest.get('motion',{}).get('quality')=='stale':return None
    points=[]
    for s in reversed(samples):
        if s.get('segment')!=latest.get('segment') or latest['t']-s['t']>300:break
        if s.get('destination_code')!=destination:break
        points.append(s)
    points.reverse()
    recent=[s for s in points if latest['t']-s['t']<=120]
    if len(recent)<5 or recent[-1]['t']-recent[0]['t']<60:return None
    def radial(seq):
        times=[s['t']-seq[0]['t'] for s in seq];ranges=[distance_nm(s,airport) for s in seq]
        mean_t=sum(times)/len(times);mean_r=sum(ranges)/len(ranges)
        denominator=sum((t-mean_t)**2 for t in times)
        slope=sum((t-mean_t)*(r-mean_r) for t,r in zip(times,ranges))/denominator
        return ranges,slope*3600
    ranges,rate=radial(recent)
    direction='inbound' if rate<=-30 else 'outbound' if rate>=30 else 'crossing'
    holding=lambda s:any(p.get('name') in ('racetrack','repeated_orbit') and p.get('status')=='established' for p in s.get('motion',{}).get('patterns',[]))
    suppressed=any(holding(s) for s in points)
    sustained=False
    if len(points)>=10 and points[-1]['t']-points[0]['t']>=180:
        history,_=radial(points)
        increasing=sum(b-a>.01 for a,b in zip(history,history[1:]))/(len(history)-1)
        sustained=direction=='outbound' and history[-1]-history[0]>=2 and increasing>=.8 and not suppressed
    return dict(destination=airport['icao'],reported_destination=destination,direction=direction,
                distance_nm=round(ranges[-1],2),radial_speed_knots=round(rate,1),
                support_seconds=round(recent[-1]['t']-recent[0]['t']),
                sustained_movement_away=sustained,divergence_suppressed=suppressed,
                metadata_freshness='unknown',basis='observed range trend relative to last reported destination; crossing means little radial movement')
