"""Bounded, transient motion estimates and basic primitives; stdlib only.

No interpolation, orbit/holding detection, intent labels or feed mutation.
See docs/motion-primitives-v0.7.0-dev.1.md for exact preview thresholds.
"""
from collections import OrderedDict, deque
from datetime import datetime
import statistics
import math
import threading
import time

EARTH_M = 6371008.8
KNOT_MPS = 0.5144444444444445
MOTION_SOURCES = ('sbs_30003', 'aircraft_json', 'swim_sfdps')
LIMITS = {
    'max_aircraft': 1024, 'max_samples_per_aircraft': 128,
    'history_seconds': 600, 'expire_seconds': 300, 'sample_interval_seconds': 5,
    'analysis_interval_seconds': 5, 'min_samples': 5, 'max_completed_events_per_aircraft': 64,
    'max_speed_knots': 1500, 'future_tolerance_seconds': 5,
    'course_min_speed_knots': 30, 'level_rate_fpm': 150,
    'vertical_entry_fpm': 300, 'vertical_exit_fpm': 200,
    'speed_stable_knots': 10, 'course_stable_degrees': 8,
    'turn_entry_deg_s': 0.5, 'turn_exit_deg_s': 0.3,
    'acceleration_entry_knots_s': 0.15, 'acceleration_exit_knots_s': 0.1,
    'speed_trend_residual_knots': 8, 'vertical_residual_ft': 150,
    'vertical_max_fpm': 10000, 'turn_consistency_fraction': 0.8,
}


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def timestamp(value):
    result = number(value)
    if result is not None:
        return result
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.timestamp() if dt.tzinfo else None
        except (ValueError, OverflowError):
            pass
    return None


def delta_degrees(a, b):
    return (b - a + 180) % 360 - 180


def leg(a, b):
    """Spherical distance and initial ground bearing; antimeridian safe."""
    p1, p2 = math.radians(a['lat']), math.radians(b['lat'])
    dp = p2-p1
    dl = math.radians(delta_degrees(a['lon'], b['lon']))
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    distance = 2*EARTH_M*math.asin(math.sqrt(min(1, max(0, h))))
    y = math.sin(dl)*math.cos(p2)
    x = math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dl)
    return distance, math.degrees(math.atan2(y, x)) % 360


def fit(points):
    """OLS slope, RMS residual and range of equally weighted (time,value) pairs."""
    if len(points) < 3:
        return None
    origin = points[0][0]
    x = [p[0]-origin for p in points]; y = [p[1] for p in points]
    mx, my = sum(x)/len(x), sum(y)/len(y)
    denominator = sum((v-mx)**2 for v in x)
    if denominator <= 0:
        return None
    slope = sum((a-mx)*(b-my) for a,b in zip(x,y))/denominator
    residual = math.sqrt(sum((b-(my+slope*(a-mx)))**2 for a,b in zip(x,y))/len(x))
    return slope, residual, max(y)-min(y)


def profile(source):
    if source == 'swim_sfdps':
        return {'window_seconds':120,'minimum_samples':5,'minimum_span_seconds':60,'gap_seconds':45,'fresh_seconds':45,'field_fresh_seconds':45,'movement_floor_m':25}
    return {'window_seconds': 60,
            'minimum_samples': LIMITS['min_samples'],
            'minimum_span_seconds': 30,
            'gap_seconds': 30,
            'fresh_seconds': 15,
            'field_fresh_seconds': 15,
            'movement_floor_m': 25}


class MotionEngine:
    def __init__(self, source, clock=time.time):
        self.source, self.clock = source, clock
        self.profile = profile(source)
        self.lock = threading.RLock()
        self.tracks = OrderedDict()
        self.counters = dict.fromkeys(('accepted', 'duplicates', 'throttled', 'invalid', 'out_of_order', 'gaps', 'discontinuities', 'occurrence_changes', 'evicted'), 0)
        self.last_error = None
        self.last_batch_seconds = 0
        self.last_summary_at = None
        self.rejection_reasons = dict.fromkeys(("missing_coordinates", "invalid_coordinate_value", "coordinate_out_of_range", "nonpositive_position_time", "future_position_time", "missing_report_time"), 0)
        self.previous_diagnostics = {"counters": dict(self.counters), "rejections": dict(self.rejection_reasons)}

    def _reject(self, reason):
        self.rejection_reasons[reason] += 1
        return None

    def diagnostic_summary(self):
        """Bounded aggregate deltas since the previous diagnostic summary."""
        with self.lock:
            counters = dict(self.counters)
            reasons = dict(self.rejection_reasons)
            result = {"source": self.source, "scope": "since_previous_verbose_summary",
                      "counters_delta": {k:v-self.previous_diagnostics["counters"][k] for k,v in counters.items()},
                      "rejection_reasons_delta": {k:v-self.previous_diagnostics["rejections"][k] for k,v in reasons.items()},
                      "rejection_reasons_total": reasons,
                      "tracked_aircraft": len(self.tracks),
                      "retained_samples": sum(len(t["samples"]) for t in self.tracks.values()),
                      "retained_events": sum(len(t["completed"]) for t in self.tracks.values()),
                      "last_batch_seconds": round(self.last_batch_seconds, 6)}
            bases={};blockers={};derived=[];reported=[];intervals=[];differences=[];ranges=[];residuals=[];trends=[];stale=0
            for track in self.tracks.values():
                state=track['state'];diagnostics=state.get('speed_diagnostics',{})
                if not track['samples'] or self.clock()-track['samples'][-1]['t']>self.profile['fresh_seconds']:
                    stale+=1;continue
                basis=diagnostics.get('speed_basis','unavailable');bases[basis]=bases.get(basis,0)+1
                for reason in diagnostics.get('blockers',[]):blockers[reason]=blockers.get(reason,0)+1
                value=state.get('metrics',{}).get('ground_speed_knots')
                if value is not None:derived.append(value)
                value=diagnostics.get('reported_speed_knots')
                if value is not None:reported.append(value)
                value=diagnostics.get('latest_leg_derived_minus_latest_reported_knots')
                if value is not None:differences.append(value)
                for field,values in [('speed_range_knots',ranges),('speed_residual_knots',residuals),('acceleration_knots_s',trends)]:
                    value=diagnostics.get(field)
                    if value is not None:values.append(value)
                value=diagnostics.get('report_intervals_seconds')
                if value:intervals.append(value['median'])
            def distribution(values):
                return {'count':len(values),'min':round(min(values),2),'median':round(statistics.median(values),2),'max':round(max(values),2)} if values else {'count':0}
            result['speed_analysis']={'scope':'current_fresh_tracks','stale_tracks_excluded':stale,
                'speed_basis_counts':bases,'stable_speed_blockers':blockers,'blockers_can_overlap':True,
                'reported_speed_semantics':'reported_ground_speed',
                'derived_ground_speed_knots':distribution(derived),'reported_speed_knots':distribution(reported),
                'latest_leg_derived_minus_latest_reported_knots':distribution(differences),
                'per_track_median_report_interval_seconds':distribution(intervals),
                'per_track_speed_range_knots':distribution(ranges),'per_track_fit_residual_knots':distribution(residuals),
                'per_track_speed_trend_knots_s':distribution(trends)}
            self.previous_diagnostics = {"counters": counters, "rejections": reasons}
            return result

    def _sample(self, ac, received, source_now, metadata):
        lat, lon = number(ac.get('lat')), number(ac.get('lon'))
        if ac.get('lat') is None or ac.get('lon') is None:
            return self._reject('missing_coordinates')
        if lat is None or lon is None:
            return self._reject('invalid_coordinate_value')
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            return self._reject('coordinate_out_of_range')
        t = timestamp(metadata.get('position_time'))
        if self.source == 'swim_sfdps' and t is None:
            return self._reject('missing_report_time')
        basis = metadata.get('time_basis', 'position_receipt')
        if t is None and number(ac.get('seen_pos')) is not None and ac['seen_pos'] >= 0:
            t = source_now-ac['seen_pos']; basis = 'snapshot_minus_seen_pos'
        known = t is not None
        if t is None:
            t = source_now; basis = 'snapshot_position_change'
        if t <= 0:
            return self._reject('nonpositive_position_time')
        if t > received+LIMITS['future_tolerance_seconds']:
            return self._reject('future_position_time')
        altitude, reference = None, None
        if ac.get('alt_baro') != 'ground':
            for name in ('alt_baro', 'alt_geom'):
                value = number(ac.get(name))
                if value is not None:
                    field_time = timestamp(metadata.get(name+'_time'))
                    if field_time is None or abs(t-field_time) <= self.profile['field_fresh_seconds']:
                        altitude, reference = value, metadata.get('altitude_reference', name)
                    break
        reported = number(ac.get('gs'))
        reported_time = timestamp(metadata.get('gs_time'))
        reported_fresh = reported is not None and 0 <= reported <= LIMITS['max_speed_knots'] and (reported_time is None or abs(t-reported_time) <= self.profile['field_fresh_seconds'])
        return {'reported_speed': reported if reported_fresh else None,
                'reported_speed_timing': 'field_receipt' if reported_time is not None else 'snapshot_assumption',
                't': t, 'lat': lat, 'lon': lon, 'altitude': altitude, 'reference': reference,
                'time_basis': basis, 'known_time': known,
                'altitude_timing': 'field_receipt' if metadata.get('alt_baro_time') or metadata.get('alt_geom_time') else 'snapshot_assumption',
                'ground': ac.get('alt_baro') == 'ground'}

    def observe(self, aircraft, received=None, source_now=None, metadata=None):
        if self.source not in MOTION_SOURCES:
            return
        started = time.perf_counter()
        received = self.clock() if received is None else received
        source_now = number(source_now) or received
        if number(received) is None or number(source_now) is None:
            return
        metadata = metadata or {}
        with self.lock:
            self._prune(received)
            for ac in aircraft:
                if not isinstance(ac, dict):
                    continue
                key = str(ac.get('hex') or '').strip().lower()
                if not key or len(key) > 64:
                    continue
                meta = metadata.get(key, {})
                sample = self._sample(ac, received, source_now, meta)
                if sample is None:
                    self.counters['invalid'] += 1; continue
                track = self.tracks.get(key)
                if track is None:
                    if len(self.tracks) >= LIMITS['max_aircraft']:
                        self.tracks.popitem(last=False); self.counters['evicted'] += 1
                    track = {'samples': deque(maxlen=LIMITS['max_samples_per_aircraft']), 'segment': 1,
                             'reason': 'first_observation', 'last_received': received, 'last_analysis': 0,
                             'occurrence': meta.get('occurrence'), 'state': {}, 'events': {},
                             'completed': deque(maxlen=LIMITS['max_completed_events_per_aircraft'])}
                    self.tracks[key] = track
                prev = track['samples'][-1] if track['samples'] else None
                occurrence = meta.get('occurrence')
                if occurrence and track['occurrence'] and occurrence != track['occurrence']:
                    self._reset(track, 'occurrence_change'); self.counters['occurrence_changes'] += 1; prev = None
                if occurrence:
                    track['occurrence'] = occurrence
                if prev:
                    dt = sample['t']-prev['t']
                    same = sample['lat'] == prev['lat'] and sample['lon'] == prev['lon']
                    if (abs(dt) <= 0.25 and same) or (not sample['known_time'] and same):
                        self.counters['duplicates'] += 1; continue
                    if dt <= 0:
                        self.counters['out_of_order'] += 1; continue
                    if dt > self.profile['gap_seconds']:
                        self._reset(track, 'observation_gap'); self.counters['gaps'] += 1
                    elif leg(prev, sample)[0]/dt/KNOT_MPS > LIMITS['max_speed_knots']:
                        self._reset(track, 'position_discontinuity'); self.counters['discontinuities'] += 1
                    elif dt < LIMITS['sample_interval_seconds']:
                        self.counters['throttled'] += 1; continue
                track['samples'].append(sample)
                while track['samples'] and sample['t']-track['samples'][0]['t'] > LIMITS['history_seconds']:
                    track['samples'].popleft()
                track['last_received'] = received
                self.tracks.move_to_end(key)
                self.counters['accepted'] += 1
                if received-track['last_analysis'] >= LIMITS['analysis_interval_seconds'] or not track['state']:
                    self._analyze(track)
                    track['last_analysis'] = received
            self.last_batch_seconds = time.perf_counter()-started

    def _finish(self, track, names, ended_at, reason):
        for name in names:
            event = track['events'][name]
            track['completed'].append({'name': name, 'segment': track['segment'],
                'first_supported': event['first_supported'], 'detected_at': event['detected_at'],
                'last_supported': ended_at, 'ended_reason': reason})

    def _reset(self, track, reason):
        if track['samples']:
            self._finish(track, list(track['events']), track['samples'][-1]['t'], reason)
        track['samples'].clear(); track['events'].clear(); track['state'] = {}
        track['segment'] += 1; track['reason'] = reason; track['last_analysis'] = 0

    def _prune(self, now):
        for key in [k for k,v in self.tracks.items() if now-v['last_received'] > LIMITS['expire_seconds']]:
            del self.tracks[key]

    def _analyze(self, track):
        last = track['samples'][-1]
        samples = [s for s in track['samples'] if last['t']-s['t'] <= self.profile['window_seconds']]
        span = samples[-1]['t']-samples[0]['t']
        state = {'window_samples': len(samples), 'window_span_seconds': round(span, 2), 'analyzed_at': last['t'], 'metrics': {}, 'primitives': []}
        metrics = state['metrics']
        legs = []
        for a,b in zip(samples,samples[1:]):
            distance, course = leg(a,b)
            dt = b['t']-a['t']
            if distance >= self.profile['movement_floor_m']:
                legs.append(((a['t']+b['t'])/2, distance/dt/KNOT_MPS, course))
        minimum = self.profile['minimum_samples']
        eligible = len(samples) >= minimum and span >= self.profile['minimum_span_seconds'] and not last['ground']
        speeds = [(t,v) for t,v,c in legs]
        derived_speed_fit = fit(speeds)
        reported_speeds=[]
        if self.source=='swim_sfdps':
            for sample in reversed(samples):
                if sample.get('reported_speed') is None:break
                reported_speeds.append((sample['t'],sample['reported_speed']))
            reported_speeds.reverse()
        speed_basis='reported_ground_speed' if reported_speeds else 'position_derived_ground_speed'
        analysis_speeds=reported_speeds if reported_speeds else speeds
        speed_fit=fit(analysis_speeds)
        speed_minimum=minimum if reported_speeds else minimum-1
        speed_min_span=self.profile['minimum_span_seconds'] if reported_speeds else self.profile['minimum_span_seconds']-LIMITS['sample_interval_seconds']
        speed_span=analysis_speeds[-1][0]-analysis_speeds[0][0] if analysis_speeds else 0
        metrics['speed_basis']=speed_basis
        if analysis_speeds:metrics['analysis_speed_knots']=round(analysis_speeds[-1][1],2)
        if track['state'].get('speed_basis') not in (None,speed_basis):
            affected=[n for n in track['events'] if n in ('stable_speed','steady_flight','accelerating','decelerating')]
            self._finish(track,affected,track['state'].get('analyzed_at',last['t']),'speed_basis_changed')
            for name in affected:track['events'].pop(name,None)
        state['speed_basis']=speed_basis
        courses = []
        for t,v,c in legs:
            if v >= LIMITS['course_min_speed_knots']:
                value = c if not courses else courses[-1][1]+delta_degrees(courses[-1][1] % 360,c)
                courses.append((t,value))
        course_fit = fit(courses)
        # Use only the contiguous suffix with one usable altitude reference.
        altitude = []
        for sample in reversed(samples):
            if sample['altitude'] is None or sample['reference'] != last['reference']:
                break
            altitude.append((sample['t'], sample['altitude']))
        altitude.reverse(); vertical = fit(altitude)
        alt_eligible = eligible and len(altitude) >= minimum and altitude[-1][0]-altitude[0][0] >= self.profile['minimum_span_seconds'] if altitude else False
        if speeds:
            metrics['ground_speed_knots'] = round(speeds[-1][1], 2)
        if courses:
            metrics['course_degrees'] = round(courses[-1][1] % 360, 2)
        if speed_fit:
            metrics.update(acceleration_knots_s=round(speed_fit[0],4), speed_residual_knots=round(speed_fit[1],2), speed_range_knots=round(speed_fit[2],2))
        if course_fit:
            metrics.update(turn_rate_deg_s=round(course_fit[0],4), course_residual_degrees=round(course_fit[1],2), course_range_degrees=round(course_fit[2],2))
        if vertical:
            metrics.update(vertical_rate_fpm=round(vertical[0]*60,1), altitude_residual_ft=round(vertical[1],2), altitude_reference=last['reference'])
        labels = []
        def choose(name, value, entry, exit_value):
            threshold = exit_value if name in track['events'] else entry
            if value >= threshold: labels.append(name)
        if alt_eligible and vertical[1] <= LIMITS['vertical_residual_ft'] and abs(vertical[0]*60) <= LIMITS['vertical_max_fpm']:
            rate = vertical[0]*60
            choose('climbing',rate,LIMITS['vertical_entry_fpm'],LIMITS['vertical_exit_fpm'])
            choose('descending',-rate,LIMITS['vertical_entry_fpm'],LIMITS['vertical_exit_fpm'])
            if abs(rate) <= LIMITS['level_rate_fpm']:labels.append('level_altitude')
        motion_eligible = eligible and len(legs) >= minimum-1 and legs[-1][0]-legs[0][0] >= self.profile['minimum_span_seconds']-LIMITS['sample_interval_seconds'] if legs else False
        speed_eligible=eligible and len(analysis_speeds)>=speed_minimum and speed_span>=speed_min_span
        if speed_eligible and speed_fit and speed_fit[1] <= LIMITS['speed_trend_residual_knots']:
            choose('accelerating',speed_fit[0],LIMITS['acceleration_entry_knots_s'],LIMITS['acceleration_exit_knots_s'])
            choose('decelerating',-speed_fit[0],LIMITS['acceleration_entry_knots_s'],LIMITS['acceleration_exit_knots_s'])
            if speed_fit[2] <= LIMITS['speed_stable_knots'] and abs(speed_fit[0]) < LIMITS['acceleration_exit_knots_s']:labels.append('stable_speed')
        if motion_eligible and course_fit and course_fit[1] <= LIMITS['course_stable_degrees']:
            rates = [(b[1]-a[1])/(b[0]-a[0]) for a,b in zip(courses,courses[1:])]
            for name,sign in (('turning_right',1),('turning_left',-1)):
                consistent = sum(sign*rate >= LIMITS['turn_exit_deg_s'] for rate in rates)/len(rates)
                if consistent >= LIMITS['turn_consistency_fraction']:
                    choose(name,sign*course_fit[0],LIMITS['turn_entry_deg_s'],LIMITS['turn_exit_deg_s'])
            if course_fit[2] <= LIMITS['course_stable_degrees']:labels.append('stable_course')
        if all(label in labels for label in ('level_altitude','stable_speed','stable_course')):labels.append('steady_flight')
        blockers=[]
        if last['ground']:blockers.append('on_ground')
        if len(samples)<minimum:blockers.append('too_few_position_samples')
        if span<self.profile['minimum_span_seconds']:blockers.append('insufficient_position_span')
        if len(analysis_speeds)<speed_minimum:blockers.append('too_few_usable_speed_samples')
        if speed_span<speed_min_span:blockers.append('insufficient_speed_span')
        if not speed_fit:blockers.append('speed_fit_unavailable')
        else:
            if speed_fit[1]>LIMITS['speed_trend_residual_knots']:blockers.append('excessive_fit_residual')
            if speed_fit[2]>LIMITS['speed_stable_knots']:blockers.append('excessive_speed_variation')
            if abs(speed_fit[0])>=LIMITS['acceleration_exit_knots_s']:blockers.append('speed_trend')
        intervals=[b['t']-a['t'] for a,b in zip(samples,samples[1:])]
        values=[v for t,v in speeds]
        reported=last.get('reported_speed')
        derived=metrics.get('ground_speed_knots')
        def stats(values):
            return {'min':round(min(values),3),'median':round(statistics.median(values),3),'max':round(max(values),3)} if values else None
        state['speed_diagnostics']={'stable_speed': 'stable_speed' in labels,'blockers':blockers,
            'speed_basis':speed_basis,'position_samples':len(samples),'usable_speed_samples':len(analysis_speeds),
            'position_span_seconds':round(span,2),'speed_span_seconds':round(speed_span,2),
            'report_intervals_seconds':stats(intervals),'derived_speeds_knots':stats(values),
            'analysis_speeds_knots':stats([v for t,v in analysis_speeds]),
            'derived_speed_range_knots':round(derived_speed_fit[2],2) if derived_speed_fit else None,
            'derived_speed_residual_knots':round(derived_speed_fit[1],2) if derived_speed_fit else None,
            'derived_acceleration_knots_s':round(derived_speed_fit[0],4) if derived_speed_fit else None,
            'reported_speed_knots':reported,'reported_speed_semantics':'reported_ground_speed',
            'reported_speed_timing':last.get('reported_speed_timing'),
            'latest_leg_derived_minus_latest_reported_knots':round(derived-reported,2) if derived is not None and reported is not None else None,
            'speed_range_knots':metrics.get('speed_range_knots'),'speed_residual_knots':metrics.get('speed_residual_knots'),
            'acceleration_knots_s':metrics.get('acceleration_knots_s'),
            'thresholds':{'range_knots':LIMITS['speed_stable_knots'],'residual_knots':LIMITS['speed_trend_residual_knots'],'absolute_trend_knots_s':LIMITS['acceleration_exit_knots_s']}}
        start = samples[0]['t']
        events = {}
        for name in labels:
            old = track['events'].get(name)
            support_start = altitude[0][0] if name in ('climbing','descending','level_altitude') else analysis_speeds[0][0] if name in ('stable_speed','accelerating','decelerating') and analysis_speeds else start
            events[name] = old or {'first_supported': support_start, 'detected_at': last['t']}
            state['primitives'].append({'name': name, 'duration_seconds': round(last['t']-events[name]['first_supported'],1), 'first_supported': events[name]['first_supported'], 'last_supported': last['t'], 'detected_at': events[name]['detected_at'], **({'speed_basis':speed_basis} if name in ('stable_speed','accelerating','decelerating','steady_flight') else {})})
        self._finish(track, [name for name in track['events'] if name not in events], track['state'].get('analyzed_at', last['t']), 'criteria_no_longer_met')
        track['events'] = events
        state['quality'] = 'warming_up' if not eligible else 'supported' if labels else 'insufficient_or_unclassified'
        state['time_basis'] = last['time_basis']; state['altitude_timing'] = last['altitude_timing']
        track['state'] = state

    def snapshot(self, keys=None, now=None, include_events=False):
        now = self.clock() if now is None else now
        with self.lock:
            self._prune(now)
            result = {}
            for key in (list(self.tracks) if keys is None else keys):
                track = self.tracks.get(key)
                if not track or not track['samples']:continue
                last = track['samples'][-1]; age = max(0,now-last['t'])
                state = dict(track['state'])
                state.update(position_age_seconds=round(age,1), source_time=last['t'], segment=track['segment'], segment_reason=track['reason'], retained_samples=len(track['samples']))
                if age > self.profile['fresh_seconds']:
                    state['quality'] = 'stale'; state['primitives'] = []
                if include_events:
                    state['completed_events'] = [dict(event) for event in track['completed']]
                result[key] = state
            return {'source': self.source, 'available': self.source in MOTION_SOURCES,
                    'reason': None if self.source in MOTION_SOURCES else ('position_precision_excluded' if self.source == 'flights_js' else 'selected_source_excluded'),
                    'transient': True, 'fresh_seconds': self.profile['fresh_seconds'], 'aircraft': result}

    def periodic_summary(self, now=None, monotonic_now=None):
        """Current-state counts, at most once per minute; no aircraft identities."""
        if self.source not in MOTION_SOURCES:
            return None
        now = self.clock() if now is None else now
        tick = time.monotonic() if monotonic_now is None else monotonic_now
        with self.lock:
            if self.last_summary_at is not None and tick-self.last_summary_at < 60:
                return None
            self.last_summary_at = tick
            states = self.snapshot(now=now)['aircraft']
            quality = dict.fromkeys(('warming_up', 'supported', 'insufficient_or_unclassified', 'stale'), 0)
            primitives = {}
            for state in states.values():
                quality[state['quality']] += 1
                for primitive in state.get('primitives', []):
                    name = primitive['name']
                    primitives[name] = primitives.get(name, 0)+1
            return {'source': self.source, 'window': 'current state',
                    'tracked_aircraft': len(states), 'quality': quality,
                    'primitives': dict(sorted(primitives.items())),
                    'labels_can_overlap': True}

    def status(self):
        with self.lock:
            self._prune(self.clock())
            return {'available': self.source in MOTION_SOURCES, 'source': self.source,
                    'reason': None if self.source in MOTION_SOURCES else ('position_precision_excluded' if self.source == 'flights_js' else 'selected_source_excluded'),
                    'supported_sources': list(MOTION_SOURCES), 'transient': True,
                    'tracked_aircraft': len(self.tracks), 'retained_samples': sum(len(t['samples']) for t in self.tracks.values()),
                    'retained_events': sum(len(t['completed']) for t in self.tracks.values()), 'last_batch_seconds': round(self.last_batch_seconds,6),
                    'limits': dict(LIMITS), 'profile': dict(self.profile), 'counters': dict(self.counters), 'rejection_reasons': dict(self.rejection_reasons), 'last_error': self.last_error}
