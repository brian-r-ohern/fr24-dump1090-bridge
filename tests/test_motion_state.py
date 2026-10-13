"""Synthetic motion, source timing, discontinuity and bounded-state checks."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from motion_state import MotionEngine, LIMITS, EARTH_M, KNOT_MPS, fit

BASE = 1700000000.0


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.now = BASE
        self.engine = MotionEngine('sbs_30003', clock=lambda:self.now)

    def sample(self, seconds, x, y=0, altitude=10000, key='abc123', engine=None, **meta):
        engine = engine or self.engine
        self.now = BASE+seconds
        ac = {'hex':key,'lat':42+math.degrees(y/EARTH_M),
              'lon':-77+math.degrees(x/(EARTH_M*math.cos(math.radians(42)))), 'alt_baro':altitude}
        engine.observe([ac], self.now, self.now, {key:{'position_time':self.now,'alt_baro_time':self.now,**meta}})
        return ac

    def state(self,engine=None,key='abc123'):
        return (engine or self.engine).snapshot(now=self.now)['aircraft'][key]

    def names(self,engine=None):
        return {p['name'] for p in self.state(engine)['primitives']}

    def test_steady_flight_and_measured_metrics(self):
        for t in range(0,66,5):self.sample(t,200*KNOT_MPS*t)
        s=self.state()
        self.assertIn('steady_flight',self.names())
        self.assertAlmostEqual(s['metrics']['ground_speed_knots'],200,delta=.2)
        self.assertAlmostEqual(s['metrics']['course_degrees'],90,delta=.1)
        self.assertEqual(s['metrics']['vertical_rate_fpm'],0)
        self.assertEqual(s['time_basis'],'position_receipt')
        self.assertEqual(s['altitude_timing'],'field_receipt')

    def test_climb_descent_speed_trends_and_hysteresis(self):
        for sign in (1,-1):
            self.engine=MotionEngine('sbs_30003',clock=lambda:self.now)
            for t in range(0,66,5):self.sample(t,KNOT_MPS*(200*t+sign*.5*t*t),altitude=10000+sign*10*t)
            self.assertIn('climbing' if sign==1 else 'descending',self.names())
            self.assertIn('accelerating' if sign==1 else 'decelerating',self.names())
            self.assertAlmostEqual(self.state()['metrics']['vertical_rate_fpm'],sign*600,delta=.1)
            self.assertAlmostEqual(self.state()['metrics']['acceleration_knots_s'],sign,delta=.01)
        self.assertNotIn('steady_flight',self.names())

    def test_signed_turn_across_north(self):
        for sign in (1,-1):
            self.engine=MotionEngine('sbs_30003',clock=lambda:self.now)
            # Tangent course crosses north; physical turn rate is +/-1 degree/s.
            for t in range(0,66,5):
                angle=math.radians(60-sign*t)
                self.sample(t,9000*math.cos(angle),9000*math.sin(angle))
            self.assertIn('turning_right' if sign==1 else 'turning_left',self.names())
            self.assertAlmostEqual(self.state()['metrics']['turn_rate_deg_s'],sign,delta=.01)
            self.assertNotIn('stable_course',self.names())

    def test_duplicates_out_of_order_throttle_and_stale(self):
        ac=self.sample(0,0)
        for t in (1,2,3):self.engine.observe([ac],BASE+t,BASE+t,{'abc123':{'position_time':BASE}})
        self.assertEqual(self.engine.status()['counters']['duplicates'],3)
        self.sample(1,50)
        self.assertEqual(self.engine.status()['counters']['throttled'],1)
        self.engine.observe([{**ac,'lon':-77.001}],BASE+5,BASE+5,{'abc123':{'position_time':BASE-1}})
        self.assertEqual(self.engine.status()['counters']['out_of_order'],1)
        self.now=BASE+20
        self.assertEqual(self.state()['quality'],'stale')
        self.assertEqual(self.state()['primitives'],[])

    def test_gaps_discontinuities_and_occurrence_changes_reset(self):
        self.sample(0,0,occurrence='one');self.sample(5,500,occurrence='one')
        self.sample(40,4000,occurrence='one')
        self.assertEqual(self.state()['segment_reason'],'observation_gap')
        self.assertEqual(self.state()['retained_samples'],1)
        self.sample(45,100000,occurrence='one')
        self.assertEqual(self.state()['segment_reason'],'position_discontinuity')
        self.sample(50,100500,occurrence='two')
        self.assertEqual(self.state()['segment_reason'],'occurrence_change')
        self.assertEqual(self.state()['primitives'],[])

    def test_tfms_explicitly_excluded(self):
        engine=MotionEngine('swim_tfms',clock=lambda:self.now)
        for t in range(0,241,60):self.sample(t,300*KNOT_MPS*t,engine=engine)
        self.assertFalse(engine.status()['available'])
        self.assertEqual(engine.status()['reason'],'selected_source_excluded')
        self.assertEqual(engine.status()['retained_samples'],0)
        self.assertEqual(engine.snapshot(now=self.now)['aircraft'],{})

    def test_flights_js_precision_explicitly_excluded(self):
        engine=MotionEngine('flights_js',clock=lambda:self.now)
        for t in range(0,66,5):self.sample(t,100*t,engine=engine)
        self.assertFalse(engine.status()['available'])
        self.assertEqual(engine.status()['reason'],'position_precision_excluded')
        self.assertEqual(engine.status()['retained_samples'],0)

    def test_missing_position_timestamp_and_assigned_altitude(self):
        engine=MotionEngine('aircraft_json',clock=lambda:self.now)
        ac={'hex':'abc123','lat':42,'lon':-77,'assigned_altitude_raw':'370C'}
        for t in range(10):engine.observe([ac],BASE+t,BASE+t)
        self.assertEqual(engine.status()['counters']['accepted'],1)
        self.assertEqual(engine.status()['counters']['duplicates'],9)
        self.assertEqual(engine.snapshot(now=BASE+10)['aircraft']['abc123']['metrics'],{'speed_basis':'position_derived_ground_speed'})

    def test_stale_altitude_reference_switch_and_ground(self):
        for t in range(0,66,5):
            ac=self.sample(t,100*t,altitude=10000+10*t)
        self.assertIn('climbing',self.names())
        self.now=BASE+70
        self.engine.observe([{**ac,'lon':ac['lon']+.005}],self.now,self.now,
                            {'abc123':{'position_time':self.now,'alt_baro_time':BASE}})
        self.assertNotIn('climbing',self.names())
        self.sample(75,7500,altitude='ground')
        self.assertEqual(self.names(),set())

    def test_invalid_and_bounded_expiring_state(self):
        self.engine.observe([{'hex':'bad','lat':True,'lon':0}],BASE,BASE)
        self.engine.observe([{'hex':'bad','lat':0,'lon':0}],BASE,BASE,{'bad':{'position_time':BASE+30}})
        self.assertEqual(self.engine.status()['counters']['invalid'],2)
        with patch.dict(LIMITS,{'max_aircraft':2,'max_samples_per_aircraft':8}):
            for t in range(0,101,5):self.sample(t,100*t)
            self.assertEqual(self.state()['retained_samples'],8)
            self.sample(105,0,key='two');self.sample(110,0,key='three')
            self.assertEqual(self.engine.status()['tracked_aircraft'],2)
            self.assertEqual(self.engine.status()['counters']['evicted'],1)
        self.now=BASE+500
        self.assertEqual(self.engine.status()['tracked_aircraft'],0)

    def test_antimeridian_and_ols_offset(self):
        engine=MotionEngine('aircraft_json',clock=lambda:self.now)
        for t,lon in [(0,179.999),(5,-179.999)]:
            engine.observe([{'hex':'abc123','lat':0,'lon':lon,'seen_pos':0}],BASE+t,BASE+t)
        state=engine.snapshot(now=BASE+5)['aircraft']['abc123']
        self.assertAlmostEqual(state['metrics']['ground_speed_knots'],86.46,delta=.1)
        self.assertEqual(state['segment'],1)
        result=fit([(BASE,1000),(BASE+10,1100),(BASE+20,1200)])
        self.assertEqual(result[0],10);self.assertEqual(result[1],0)

    def test_completed_events_are_bounded_and_gap_separated(self):
        with patch.dict(LIMITS,{'max_completed_events_per_aircraft':3}):
            for t in range(0,66,5):self.sample(t,100*t)
            self.sample(110,11000)
            state=self.engine.snapshot(now=self.now,include_events=True)['aircraft']['abc123']
            self.assertEqual(len(state['completed_events']),3)
            self.assertTrue(all(e['segment']==1 and e['ended_reason']=='observation_gap' for e in state['completed_events']))
            self.assertEqual(state['segment'],2)
            self.assertNotIn('completed_events',self.state())

    def test_vertical_hysteresis_and_reference_switch(self):
        altitude=10000
        for t in range(0,66,5):
            if t:altitude+=350/60*5
            self.sample(t,100*t,altitude=altitude)
        self.assertIn('climbing',self.names())
        for t in range(70,136,5):
            altitude+=225/60*5
            self.sample(t,100*t,altitude=altitude)
        self.assertIn('climbing',self.names())
        self.now=BASE+140
        ac={'hex':'abc123','lat':42,'lon':-77+math.degrees(14000/(EARTH_M*math.cos(math.radians(42)))),'alt_geom':altitude}
        self.engine.observe([ac],self.now,self.now,{'abc123':{'position_time':self.now,'alt_geom_time':self.now}})
        self.assertNotIn('climbing',self.names())

    def test_periodic_summary_counts_throttle_and_staleness(self):
        for seconds in range(0, 61, 5):
            self.sample(seconds, seconds*100, altitude=10000-seconds*10)
        self.sample(60, 1000, key='def456')
        summary = self.engine.periodic_summary(now=self.now, monotonic_now=100)
        self.assertEqual(summary['tracked_aircraft'], 2)
        self.assertEqual(summary['quality']['warming_up'], 1)
        self.assertEqual(summary['quality']['supported'], 1)
        self.assertEqual(summary['primitives']['descending'], 1)
        self.assertEqual(sum(summary['quality'].values()), 2)
        self.assertNotIn('abc123', str(summary))
        self.assertIsNone(self.engine.periodic_summary(now=self.now, monotonic_now=159))
        stale = self.engine.periodic_summary(now=self.now+16, monotonic_now=160)
        self.assertEqual(stale['quality']['stale'], 2)
        self.assertEqual(stale['primitives'], {})
        for source in ('swim_tfms', 'flights_js'):
            self.assertIsNone(MotionEngine(source).periodic_summary())


if __name__=='__main__':unittest.main()
