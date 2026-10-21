"""Experimental geometric patterns from contiguous independent positions.

No intent inference, no airport/runway inference and no motion across gaps.
"""
import math
import statistics

EARTH_M=6371008.8
LIMITS={'history_seconds':3600,'sample_interval_seconds':10,'max_samples':360,
        'minimum_samples':12,'minimum_speed_knots':30,'turn_rate_deg_s':.1,
        'minimum_phase_seconds':20,'minimum_straight_m':926,
        'minimum_radius_m':463,'maximum_radius_m':74080,
        'circle_residual_fraction':.12,'direction_consistency':.85,
        'turn_centroid_fraction':.35,'straight_heading_tolerance_deg':20,
        'exit_seconds':30,'max_completed_events':32}


def delta(a,b):return (b-a+180)%360-180

def project(samples):
    origin=samples[0];cosine=math.cos(math.radians(origin['lat']))
    if abs(cosine)<.05:return []
    return [(EARTH_M*math.radians(delta(origin['lon'],s['lon']))*cosine,
             EARTH_M*math.radians(s['lat']-origin['lat']),s['t']) for s in samples]


def circle(points):
    """Centered least-squares circle; reject singular/short straight arcs."""
    if len(points)<6:return None
    mx=sum(p[0] for p in points)/len(points);my=sum(p[1] for p in points)/len(points)
    xy=[(p[0]-mx,p[1]-my) for p in points]
    xx=sum(x*x for x,y in xy);yy=sum(y*y for x,y in xy);xy_sum=sum(x*y for x,y in xy)
    denominator=xx*yy-xy_sum*xy_sum
    if denominator<=max(1,xx*yy*1e-8):return None
    bx=sum(x*(x*x+y*y) for x,y in xy)/2;by=sum(y*(x*x+y*y) for x,y in xy)/2
    cx=(bx*yy-by*xy_sum)/denominator;cy=(by*xx-bx*xy_sum)/denominator
    radii=[math.hypot(x-cx,y-cy) for x,y in xy];radius=sum(radii)/len(radii)
    residual=math.sqrt(sum((r-radius)**2 for r in radii)/len(radii))/max(1,radius)
    if not LIMITS['minimum_radius_m']<=radius<=LIMITS['maximum_radius_m'] or residual>LIMITS['circle_residual_fraction']:return None
    return {'x':cx+mx,'y':cy+my,'radius':radius,'residual':residual}


def phases(points):
    """Overlapping 20–30 second chords stabilize position-derived course."""
    courses=[]
    for i in range(1,len(points)):
        j=i-1
        while j>0 and points[i][2]-points[j][2]<20:j-=1
        a,b=points[j],points[i];dt=b[2]-a[2];distance=math.hypot(b[0]-a[0],b[1]-a[1])
        if dt<=0 or distance/dt/.5144444444<LIMITS['minimum_speed_knots']:return []
        courses.append((i,math.degrees(math.atan2(b[0]-a[0],b[1]-a[1]))%360))
    result=[]
    for (j,old),(i,new) in zip(courses,courses[1:]):
        change=delta(old,new);dt=points[i][2]-points[j][2]
        kind=('right' if change>0 else 'left') if abs(change/dt)>=LIMITS['turn_rate_deg_s'] else 'straight'
        if not result or result[-1]['kind']!=kind:
            result.append(dict(kind=kind,start=j,end=i,angle=change,absolute_angle=abs(change)))
        else:result[-1]['end']=i;result[-1]['angle']+=change;result[-1]['absolute_angle']+=abs(change)
    # Absorb brief interruptions only between phases of the same kind.
    changed=True
    while changed:
        changed=False
        for i in range(1,len(result)-1):
            a,b,c=result[i-1:i+2]
            if a['kind']==c['kind'] and points[b['end']][2]-points[b['start']][2]<20:
                result[i-1:i+2]=[dict(kind=a['kind'],start=a['start'],end=c['end'],angle=a['angle']+b['angle']+c['angle'],absolute_angle=a['absolute_angle']+b['absolute_angle']+c['absolute_angle'])]
                changed=True;break
    for phase in result:
        a,b=points[phase['start']],points[phase['end']]
        phase.update(seconds=b[2]-a[2],length=math.hypot(b[0]-a[0],b[1]-a[1]),
                     course=math.degrees(math.atan2(b[0]-a[0],b[1]-a[1]))%360)
    return result


def describe(name,status,start,end,evidence,confidence):
    return dict(name=name,status=status,first_supported=start,last_supported=end,
                duration_seconds=round(end-start,1),confidence=round(confidence,2),
                confidence_is_calibrated=False,evidence=evidence)


def detect(samples, diagnostics=None):
    diagnostics={} if diagnostics is None else diagnostics
    def reject(reason):diagnostics[reason]=diagnostics.get(reason,0)+1
    if len(samples)<LIMITS['minimum_samples']:reject('insufficient_history');return []
    if samples[-1].get('ground'):reject('on_ground');return []
    points=project(samples)
    if not points:reject('projection_unavailable');return []
    segments=phases(points)
    if not segments:reject('unusable_chord_speed_or_time');return []
    now=points[-1][2]
    # Repeating straight/180-turn grammar. Check later candidates first.
    for count,status in ((8,'established'),(4,'candidate')):
        for offset in range(len(segments)-count,-1,-1):
            sequence=segments[offset:offset+count]
            if any(p['seconds']<20 for p in sequence):reject('phase_too_short');continue
            turns=[p for p in sequence if p['kind']!='straight'];straights=[p for p in sequence if p['kind']=='straight']
            if len(turns)!=count//2 or len(straights)!=count//2:reject('insufficient_turn_straight_phases');continue
            if any((a['kind']=='straight')==(b['kind']=='straight') for a,b in zip(sequence,sequence[1:])):reject('nonalternating_phases');continue
            if any(abs(p['angle'])/max(1,p['absolute_angle'])<LIMITS['direction_consistency'] for p in turns):reject('inconsistent_turn_direction');continue
            if len({p['kind'] for p in turns})!=1 or any(not 145<=abs(p['angle'])<=215 for p in turns):reject('turn_angle_or_direction');continue
            if any(p['length']<LIMITS['minimum_straight_m'] for p in straights):reject('straight_too_short');continue
            if any(abs(abs(delta(a['course'],b['course']))-180)>20 for a,b in zip(straights,straights[1:])):reject('nonreciprocal_straights');continue
            if max(p['length'] for p in straights)>4*min(p['length'] for p in straights):reject('unequal_straights');continue
            fits=[circle(points[p['start']:p['end']+1]) for p in turns]
            if any(f is None for f in fits):reject('circle_fit_rejected');continue
            radius=statistics.median(f['radius'] for f in fits)
            if max(f['radius'] for f in fits)>1.8*min(f['radius'] for f in fits):reject('unequal_turn_radii');continue
            # Two opposite turn centers must recur, not migrate down a zigzag.
            if len(fits)==4 and any(math.hypot(fits[i]['x']-fits[i-2]['x'],fits[i]['y']-fits[i-2]['y'])>max(926,.35*radius) for i in (2,3)):reject('turn_centers_migrating');continue
            a=points[sequence[0]['start']];b=points[sequence[-1]['end']]
            if math.hypot(a[0]-b[0],a[1]-b[1])>max(1852,.6*radius):reject('path_not_closed');continue
            # Keep an established pattern while still on its observed path.
            # Sustained off-path motion exits; a long straight extension cannot latch it.
            template=points[sequence[0]['start']:sequence[-1]['end']+1]
            latest=[p for p in points if now-p[2]<=LIMITS['exit_seconds']]
            corridor=max(926,.35*radius)
            def off_path(p):return min(math.hypot(p[0]-q[0],p[1]-q[1]) for q in template)>corridor
            if latest and latest[-1][2]-latest[0][2]>=20 and all(off_path(p) for p in latest):reject('exited_corridor');continue
            if now-b[2]>3600:continue
            return [describe('racetrack',status,a[2],now,dict(turns=len(turns),cycles=count//4,
                turn_direction=turns[0]['kind'],turn_radius_nm=round(radius/1852,2),
                straight_lengths_nm=[round(p['length']/1852,2) for p in straights],
                centroid_repeat_verified=len(fits)==4,
                turn_center_repeat_errors_nm=[round(math.hypot(fits[i]['x']-fits[i-2]['x'],fits[i]['y']-fits[i-2]['y'])/1852,3) for i in range(2,len(fits))],
                reciprocal_heading_errors_degrees=[round(abs(abs(delta(a['course'],b['course']))-180),2) for a,b in zip(straights,straights[1:])],
                closure_nm=round(math.hypot(a[0]-b[0],a[1]-b[1])/1852,3),
                exit_corridor_nm=round(corridor/1852,2)),.85 if status=='established' else .55)]
    # Latest uninterrupted turn; straightening for 30 seconds exits an orbit.
    turn=segments[-1]
    if turn['kind']=='straight' and turn['seconds']<30 and len(segments)>1:turn=segments[-2]
    if turn['kind']!='straight' and turn['seconds']>=45 and abs(turn['angle'])>=90:
        arc=points[turn['start']:turn['end']+1];geometry=circle(arc)
        if geometry is None:reject('circle_fit_rejected')
        if geometry and abs(turn['angle'])/max(1,turn['absolute_angle'])>=LIMITS['direction_consistency']:
            angle=abs(turn['angle']);name='repeated_orbit' if angle>=690 else 'orbit' if angle>=330 else 'constant_radius_turn'
            status='established' if name=='repeated_orbit' else 'candidate'
            center_shift=None;radius_ratio=None
            if name=='repeated_orbit':
                middle=len(arc)//2;first=circle(arc[:middle+1]);second=circle(arc[middle:])
                if not first or not second or math.hypot(first['x']-second['x'],first['y']-second['y'])>.25*geometry['radius'] or not .8<=first['radius']/second['radius']<=1.25:return []
                center_shift=round(math.hypot(first['x']-second['x'],first['y']-second['y'])/1852,3)
                radius_ratio=round(first['radius']/second['radius'],3)
            return [describe(name,status,arc[0][2],now,dict(turn_direction=turn['kind'],
                cumulative_turn_degrees=round(angle,1),radius_nm=round(geometry['radius']/1852,2),
                radial_rms_fraction=round(geometry['residual'],4),
                direction_consistency=round(abs(turn['angle'])/max(1,turn['absolute_angle']),3),
                half_fit_center_shift_nm=center_shift,half_fit_radius_ratio=radius_ratio,completed_orbits=int((angle+30)//360)),
                min(.95,(.85 if status=='established' else .6)*(1-geometry['residual'])))]
    # A completed approximately half-turn remains a short-lived geometric event.
    for turn in reversed(segments):
        if turn['kind']!='straight' and turn['seconds']>=20 and 150<=abs(turn['angle'])<=210 and now-points[turn['end']][2]<=60:
            return [describe('course_reversal','candidate',points[turn['start']][2],now,
                dict(turn_degrees=round(turn['angle'],1),turn_direction=turn['kind']),.6)]
    reject('no_qualifying_recent_geometry')
    return []
